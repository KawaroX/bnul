"""Single-account, restart-safe reservation monitoring for POSIX hosts."""
import html
import json
import os
import re
import tempfile
import time
import socket
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from .client import BUILDING, Client as BaseClient, Error, config_path, identifier, minute
from .rooms import FIXED_ROOMS
from .watch_notify import enqueue, flush, safe_error, send_slack

from .watch_schedule import SHANGHAI, HEARTBEAT_SECONDS, active, next_open, sleeping, schedule_for


def now_local():
    return datetime.now(SHANGHAI)


def require_active():
    if not active(now_local()):
        raise Error('当前为夜间休眠时段', 'WATCH_SLEEPING')


class Client(BaseClient):
    """Do not start a network probe, API request or login recovery after closing."""
    def __init__(self, *args, **kwargs):
        require_active()
        super().__init__(*args, **kwargs)

    def request(self, *args, **kwargs):
        require_active()
        return super().request(*args, **kwargs)

    def recover_auth(self):
        require_active()
        return super().recover_auth()


def date_time(date, minutes):
    return datetime.fromisoformat(date).replace(tzinfo=SHANGHAI) + timedelta(minutes=minutes)


def timestamp(value, date):
    """Only accept full timestamps or an explicit clock time, never durations."""
    raw = str(value or '').strip()
    if re.fullmatch(r'\d{13}|\d{10}', raw):
        return datetime.fromtimestamp(int(raw) / (1000 if len(raw) == 13 else 1), SHANGHAI)
    if re.fullmatch(r'\d{2}:\d{2}(:\d{2})?', raw):
        raw = date + 'T' + raw
    if not re.match(r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}', raw):
        raise Error('暂离起点格式未确认，未操作预约', 'DEADLINE_UNKNOWN')
    result = datetime.fromisoformat(raw)
    return result.replace(tzinfo=SHANGHAI) if result.tzinfo is None else result.astimezone(SHANGHAI)


def away_policy(system):
    # Parse the official rule, rather than interpreting awayTimeM/awayRange by name.
    text = re.sub(r'\s+', '', html.unescape(re.sub(r'<[^>]*>', '', system.get('agreements', ''))))
    duration = re.search(r'暂离时间是(\d+)分钟', text)
    meals = re.search(r'用餐时段[（(]中午(\d{1,2}:\d{2})[-–—](\d{1,2}:\d{2})[，,、]下午(\d{1,2}:\d{2})[-–—](\d{1,2}:\d{2})[）)]不计入暂离时间', text)
    if not duration or not meals or not 1 <= int(duration[1]) <= 120:
        raise Error('官网暂离规则格式变化，需核实后恢复自动处理', 'DEADLINE_UNKNOWN')
    times = [minute(v) for v in meals.groups()]
    if not 0 <= times[0] < times[1] < times[2] < times[3] < 1440:
        raise Error('用餐时间规则异常', 'DEADLINE_UNKNOWN')
    return int(duration[1]), [(times[0], times[1]), (times[2], times[3])]


def away_deadline(start, duration, meals):
    remaining = timedelta(minutes=duration)
    cursor = start
    for begin, end in meals:
        left, right = date_time(start.date().isoformat(), begin), date_time(start.date().isoformat(), end)
        if cursor >= right:
            continue
        if cursor < left:
            available = left - cursor
            if remaining <= available:
                return cursor + remaining
            remaining -= available
        cursor = right
    return cursor + remaining


def plan(current, system, now):
    state = current.get('status')
    if state not in ('RESERVE', 'AWAY'):
        return None
    date = current.get('makeDateStr')
    if date != now.date().isoformat():
        return None
    if str(current.get('roomId')) not in FIXED_ROOMS[BUILDING]:
        raise Error('首版监控仅支持已核实规则的主馆区域', 'WATCH_ROOM_UNSUPPORTED')
    begin, end = int(current['makeBegin']), int(current['makeEnd'])
    if not 0 <= begin < end < 1440:
        raise Error('预约时段异常', 'DEADLINE_UNKNOWN')
    end_at = date_time(date, end)
    if state == 'RESERVE':
        grace = int(system.get('signEndMinute', 0))
        if not 1 <= grace <= 120:
            raise Error('服务器签到宽限时间异常', 'DEADLINE_UNKNOWN')
        deadline = date_time(date, begin + grace)
        # A dated reservation's explicit server message is more specific than global settings.
        message = current.get('message') or ''
        match = re.search(r'请在\s*\d{1,2}:\d{2}\s*至\s*(\d{1,2}:\d{2})\s*之间完成签到', message)
        if match:
            deadline = date_time(date, minute(match[1]))
        source = 'signEndMinute' if not match else 'message'
    else:
        duration, meals = away_policy(system)
        start = timestamp(current.get('awayTime'), date)
        if start.date().isoformat() != date or start > now or start < date_time(date, begin):
            raise Error('暂离起点与预约时间不一致', 'DEADLINE_UNKNOWN')
        deadline, source = away_deadline(start, duration, meals), 'awayTime+official-rules'
        # The normal end releases the seat first; do not extend the original reservation.
        if end_at <= deadline:
            return None
    if end_at <= now:
        return None
    return {'id': identifier(current['id']), 'status': state,
            'seatId': identifier(current['seatId']), 'roomId': identifier(current['roomId']),
            'date': date, 'end': end, 'deadline': deadline.isoformat(), 'deadlineSource': source,
            'remainingSeconds': (deadline - now).total_seconds()}


def current_record(client):
    value = client.api('user/currentUseMake')
    if value in ('', None):
        return None
    if not isinstance(value, dict) or not value.get('id'):
        raise Error('当前预约返回格式异常，未执行写操作', 'WATCH_RESPONSE_INVALID')
    return value


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {'version': 1, 'actions': {}, 'attempts': {}}

    @contextmanager
    def locked(self):
        try:
            import fcntl
        except ImportError:
            raise Error('watch 当前支持 Linux/macOS', 'WATCH_PLATFORM_UNSUPPORTED') from None
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Error('同一状态文件已有监控进程运行', 'WATCH_ALREADY_RUNNING') from None
            if self.path.exists():
                try:
                    self.data = json.loads(self.path.read_text())
                    if (self.data.get('version') != 1 or not isinstance(self.data['actions'], dict)
                            or not isinstance(self.data['attempts'], dict)):
                        raise ValueError()
                except (ValueError, KeyError, AttributeError):
                    raise Error('监控状态损坏；保留文件并人工核实，未重置操作记录', 'WATCH_STATE_INVALID') from None
            yield self
        finally:
            os.close(fd)

    def save(self):
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.watch-')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(self.data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def tick(client, store, execute=False, threshold=300, max_renewals=3, clock=now_local):
    client.bootstrap()
    current = current_record(client)
    client._watch_read_ok = True
    reconcile_actions(store, current)
    if current is None:
        return {'event': 'idle'}
    candidate = plan(current, client.system, clock())
    if candidate is None:
        return {'event': 'observing', 'id': str(current['id']), 'status': current.get('status')}
    event = {'event': 'observing', **candidate}
    if candidate['remainingSeconds'] <= 0:
        return {**event, 'event': 'missed_deadline', 'error': '已超过签到或暂离截止时间，未自动操作'}
    if candidate['remainingSeconds'] >= threshold:
        return event
    old_id = candidate['id']
    if old_id in store.data['actions']:
        return {**event, 'event': 'already_handled', 'phase': store.data['actions'][old_id]['phase']}
    if not execute:
        return {**event, 'event': 'would_rebook', 'submitted': False}
    date = candidate['date']
    count = store.data['attempts'].get(date, 0)
    renew = count < max_renewals
    # Resolve authentication before the last state check, avoiding a slow login in between.
    client.api('user/getUserInfo')
    if renew:
        client.check_booking_captcha()
    latest = current_record(client)
    checked = plan(latest, client.system, clock()) if latest else None
    fields = ('id', 'status', 'seatId', 'roomId', 'date', 'end', 'deadline')
    if (checked is None or any(checked[k] != candidate[k] for k in fields)
            or not 0 < checked['remainingSeconds'] < threshold):
        return {**event, 'event': 'changed_before_release', 'submitted': False}
    action = {**checked, 'phase': 'release_requested', 'renew': renew,
              'startedAt': clock().isoformat()}
    store.data['actions'][old_id] = action
    if renew:
        store.data['attempts'][date] = count + 1
    # Durable before any write: never replay this reservation after an uncertain result/crash.
    store.save()
    try:
        path = 'make/cancel/' + old_id if checked['status'] == 'RESERVE' else 'make/stop'
        response = client.api(path)
        action['phase'] = 'released'
        if checked['status'] == 'RESERVE':
            # Official frontend renders this value as today's remaining cancellation count.
            if isinstance(response, bool) or not isinstance(response, int) or response < 0:
                renew = False
                action['reason'] = 'cancellation_quota_unknown'
            elif response == 0:
                renew = False
                action['reason'] = 'cancellation_quota_exhausted'
            else:
                action['remainingCancellations'] = response
        if not renew and 'reason' not in action:
            action['reason'] = 'daily_renewal_limit'
        store.save()
        after = current_record(client)
        if after is not None:
            action['phase'] = 'attention' if str(after['id']) == old_id else 'reservation_changed'
        elif not renew:
            action['phase'] = 'released_without_rebooking'
        elif clock() >= date_time(date, checked['end']):
            action['phase'] = 'released_without_rebooking'
            action['reason'] = 'original_end_reached'
        else:
            action['phase'] = 'booking_requested'
            store.save()
            client.book(checked['seatId'], date, -1, checked['end'])
            booked = current_record(client)
            if (booked and str(booked['id']) != old_id and str(booked.get('seatId')) == checked['seatId']
                    and booked.get('makeDateStr') == date and booked.get('makeEnd') == checked['end']
                    and booked.get('status') in ('RESERVE', 'CHECK_IN', 'AWAY')):
                action.update(phase='rebooked', newId=str(booked['id']), newStatus=booked['status'])
            else:
                action['phase'] = 'attention'
        store.save()
        return {'event': action['phase'], **{k: v for k, v in action.items() if k != 'phase'}}
    except (Error, ValueError, KeyError, TypeError, OSError) as exc:
        action.update(phase='attention', error=safe_error(exc))
        # Reconcile reads only. An uncertain write must never cause an automatic second write.
        try:
            observed = current_record(client)
            action['observedId'] = str(observed['id']) if observed else None
            action['observedStatus'] = observed.get('status') if observed else None
        except Error:
            action['observedStatus'] = 'unknown'
        store.save()
        return {'event': 'attention', 'id': old_id, 'error': safe_error(exc), 'submitted': True}



def matches_booking(action, current):
    return (current and str(current['id']) != action.get('id')
            and str(current.get('seatId')) == action.get('seatId')
            and current.get('makeDateStr') == action.get('date')
            and current.get('makeEnd') == action.get('end')
            and current.get('status') in ('RESERVE', 'CHECK_IN', 'AWAY'))


def reconcile_actions(store, current):
    """After a crash only read/reconcile. Never resume an uncertain write."""
    for old_id, action in store.data['actions'].items():
        phase = action.get('phase')
        if phase not in ('release_requested', 'released', 'booking_requested'):
            continue
        action['interruptedPhase'] = phase
        if phase == 'booking_requested' and matches_booking(action, current):
            action.update(phase='rebooked', newId=str(current['id']), newStatus=current['status'])
        else:
            action.update(phase='attention', reason='interrupted_action',
                          observedId=str(current['id']) if current else None,
                          observedStatus=current.get('status') if current else None)
        store.save()


AUTH_CODES = {'20003', '401', 'LOCAL_AUTH_MISSING', 'SESSION_SIGNING_KEY_MISSING',
              'AUTH_INTERACTION_REQUIRED', 'AUTH_SETUP_REQUIRED', 'CREDENTIALS_UNAVAILABLE',
              'WEBVPN_LOGIN_REQUIRED'}


def check_cycle(args, store, clock=now_local, factory=Client):
    now = clock()
    if not active(now):
        return sleeping(now)
    auth = store.data.setdefault('auth', {})
    gated = auth.get('retryAt', 0) > now.timestamp()
    client = None
    try:
        client = factory(no_proxy=args.no_proxy)
        if gated:
            client.auto_auth = False  # keep checking refreshed sessions every 120 seconds
        result = tick(client, store, args.execute, args.threshold, args.max_renewals, clock)
    except (Error, ValueError, KeyError, TypeError, OSError) as exc:
        code = str(getattr(exc, 'code', None) or 'WATCH_CHECK_FAILED')
        if code == 'WATCH_SLEEPING':
            return sleeping(clock())
        if gated and code in AUTH_CODES:
            result = {'event': 'error', 'code': auth.get('code', code),
                      'error': auth.get('error', safe_error(exc)), 'loginDeferredUntil': auth['retryAt']}
        else:
            result = {'event': 'error', 'code': code, 'error': safe_error(exc)}
            if (code in AUTH_CODES or (client is not None and client.auth_recovered
                                       and not getattr(client, '_watch_read_ok', False))):
                count = auth.get('failures', 0) + 1
                auth.update(failures=count, retryAt=now.timestamp() + min(21600, 1800 * 2 ** min(count - 1, 4)),
                            code=code, error=safe_error(exc))
                result['loginDeferredUntil'] = auth['retryAt']
    if client is not None and getattr(client, '_watch_read_ok', False):
        auth.clear()
        if client.auth_recovered:
            result['loginRecovered'] = True
    store.save()
    return result


def record_result(store, result, now, notify):
    notify = notify and active(now)
    health = store.data.setdefault('health', {})
    health['checkCount'] = health.get('checkCount', 0) + 1
    bad = result['event'] in ('error', 'missed_deadline')
    if bad:
        signature = str(result.get('code', result['event'])) + ':' + str(result.get('id', ''))
        previous = health.get('incident')
        if not previous or previous['signature'] != signature:
            incident = {'id': str(uuid.uuid4()), 'signature': signature, 'since': now.isoformat(), 'lastNotice': 0}
            health['incident'] = incident
        incident = health['incident']
        health.update(status='degraded', consecutiveFailures=health.get('consecutiveFailures', 0) + 1)
        if notify and now.timestamp() - incident['lastNotice'] >= 3600:
            enqueue(store, 'failure:' + incident['id'] + ':' + str(int(now.timestamp() // 3600)),
                    'bnul 监控失败\n时间：' + now.isoformat() + '\n' + result.get('error', signature)
                    + ('\n独立健康检查仍在运行，请检查服务状态。' if result.get('code') == 'WATCH_HEARTBEAT_STALE'
                       else '\n仍按配置间隔检查；登录恢复失败后按退避间隔重试。请查看 bnul watch --status。'), now)
            incident['lastNotice'] = now.timestamp()
    else:
        incident = health.pop('incident', None)
        health.update(status='healthy', consecutiveFailures=0, lastSuccess=now.isoformat())
        if incident and notify:
            enqueue(store, 'recovered:' + incident['id'],
                    'bnul 监控已恢复\n时间：' + now.isoformat() + '\n' + result.get('recoveryMessage', '已重新成功查询真实预约状态。'), now)
    store.data['lastCheck'] = {'at': now.isoformat(), **result}
    store.save()
    if notify:
        # Journal is the source of truth, including actions interrupted by process termination.
        for old_id, action in store.data['actions'].items():
            phase = action.get('phase')
            if phase in ('release_requested', 'released', 'booking_requested'):
                continue
            titles = {'rebooked': '已取消/结束并成功重约', 'attention': '操作未完成，需要核实',
                      'released_without_rebooking': '已释放座位，未重约',
                      'reservation_changed': '预约已变化，停止重约'}
            text = ('bnul：' + titles.get(phase, str(phase)) + '\n原预约：' + old_id
                    + '\n时间：' + action.get('startedAt', now.isoformat()))
            if action.get('newId'):
                text += '\n新预约：' + action['newId']
            if action.get('error') or action.get('reason'):
                text += '\n原因：' + str(action.get('error') or action['reason'])
            enqueue(store, 'action:' + old_id + ':' + str(phase), text, now)


def read_status(path, max_age=360, clock=now_local):
    now = clock()
    is_sleeping = not active(now)
    schedule = {'mode': 'sleeping', 'nextCheckAt': next_open(now).isoformat()} if is_sleeping else {}
    try:
        data = json.loads(Path(path).read_text())
        last_check = data.get('lastCheck', {})
        checked = datetime.fromisoformat(data.get('heartbeatAt') or last_check['at'])
        age = (now - checked).total_seconds()
        query_age = (now - datetime.fromisoformat(last_check['at'])).total_seconds() if last_check else None
        if not isinstance(data.get('health', {}), dict):
            raise ValueError()
        notices = data.get('notifications', {})
        if not isinstance(notices, dict) or any(not isinstance(n, dict) for n in notices.values()):
            raise ValueError()
        schedule = {**data.get('schedule', {}), **schedule}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'healthy': False, 'fresh': False, 'sleeping': is_sleeping, 'schedule': schedule,
                'reason': 'missing_or_invalid_heartbeat', 'path': str(path)}
    pending = sum(not n.get('deliveredAt') for n in notices.values())
    fresh = 0 <= age <= max_age
    return {'healthy': fresh and (is_sleeping or (data.get('health', {}).get('status') == 'healthy' and pending == 0)),
            'fresh': fresh, 'ageSeconds': round(age, 1), 'lastQueryAgeSeconds': query_age,
            'sleeping': is_sleeping, 'schedule': schedule, 'lastCheck': last_check,
            'health': data.get('health', {}), 'auth': data.get('auth', {}),
            'pendingNotifications': pending,
            'notificationErrors': [n['lastError'] for n in notices.values() if n.get('lastError')],
            'runtime': data.get('runtime', {}), 'actions': data.get('actions', {}), 'path': str(path)}


def deliver_notifications(store, clock):
    now = clock()
    if not active(now):
        return []
    return flush(store, now, allowed=lambda: active(clock()))


def health_check(args, path, clock=now_local):
    now = clock()
    # No state mutation, failure creation or queued Slack delivery during scheduled sleep.
    if not active(now):
        return {**sleeping(now), 'sleeping': True, 'notificationErrors': []}
    status = read_status(path, args.max_age, clock)
    # Separate file/lock: the monitor can be hung while holding its own lock.
    with Store(str(path) + '.health').locked() as store:
        result = ({'event': 'healthy', 'recoveryMessage': '监控心跳已恢复。'} if status['fresh'] else
                  {'event': 'error', 'code': 'WATCH_HEARTBEAT_STALE',
                   'error': '监控心跳缺失或超过 ' + str(args.max_age) + ' 秒；请检查 bnul-watch.service'})
        record_result(store, result, clock(), args.notify == 'slack')
        errors = deliver_notifications(store, clock) if args.notify == 'slack' else []
    return {'fresh': status['fresh'], 'sleeping': False, 'notificationErrors': errors}


def heartbeat(store, now):
    # Liveness is independent of reservation polling. A hung query cannot refresh this.
    store.data['heartbeatAt'] = now.isoformat()
    store.save()
    watchdog()


def wait_until(store, due, notify, clock=now_local, sleeper=time.sleep):
    while True:
        now = clock()
        remaining = (due - now).total_seconds()
        if remaining <= 0:
            return
        heartbeat(store, now)
        if notify:
            deliver_notifications(store, clock)
        # Re-evaluate wall time every minute, without querying the school or recovering login.
        remaining = (due - clock()).total_seconds()
        if remaining > 0:
            sleeper(min(HEARTBEAT_SECONDS, remaining))


def watchdog():
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        if address.startswith('@'):
            address = '\0' + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(b'WATCHDOG=1', address)


def run_watch(args):
    if not 10 <= args.interval <= 240 or not args.interval < args.threshold <= 600:
        raise Error('interval 需为 10–240 秒，threshold 需大于 interval 且不超过 600 秒')
    if not 0 <= args.max_renewals <= 3:
        raise Error('max-renewals 需为 0–3；0 表示临期只释放、不重约')
    if args.max_age < args.interval:
        raise Error('max-age 不能短于检查间隔')
    path = args.state_file or config_path().parent / 'watch-state.json'
    if args.status:
        return read_status(path, args.max_age, now_local)
    if args.health_check:
        return health_check(args, path, now_local)
    if args.notify_test:
        if args.notify != 'slack':
            raise Error('测试通知需指定 --notify slack')
        if not active(now_local()):
            return {**sleeping(now_local()), 'sent': False}
        return {'sent': True, 'receipt': send_slack('【测试】bnul 监控通知验收；此消息不表示真实故障。')}
    with Store(path).locked() as store:
        store.data['runtime'] = {'pid': os.getpid(), 'startedAt': now_local().isoformat(),
                                 'interval': args.interval, 'threshold': args.threshold,
                                 'execute': args.execute, 'notify': args.notify,
                                 'timezone': 'Asia/Shanghai', 'activeHours': '08:00–23:00',
                                 'idleInterval': 1800, 'inUseInterval': 1200, 'awayInterval': 420}
        heartbeat(store, now_local())
        while True:
            started = now_local()
            # Resolve defaults here so tests and embedders can inject clock/client without network.
            result = check_cycle(args, store, now_local, Client)
            finished = now_local()
            if result['event'] != 'sleeping':
                record_result(store, result, finished, args.notify == 'slack')
            schedule = schedule_for(result, started, finished, args.interval)
            store.data['schedule'] = schedule
            heartbeat(store, now_local())
            errors = deliver_notifications(store, now_local) if args.notify == 'slack' else []
            if errors:
                result['notificationErrors'] = errors
            result = {**result, 'nextCheckAt': schedule['nextCheckAt'],
                      'pollIntervalSeconds': schedule['intervalSeconds']}
            if args.once:
                if result['event'] in ('error', 'missed_deadline', 'attention') or errors:
                    raise Error(result.get('error', '监控操作或通知未完成'), result.get('code'), result)
                return result
            print(json.dumps({'at': now_local().isoformat(), **result}, ensure_ascii=False), flush=True)
            wait_until(store, datetime.fromisoformat(schedule['nextCheckAt']), args.notify == 'slack',
                       now_local, time.sleep)
