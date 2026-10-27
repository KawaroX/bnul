import argparse
import getpass
import json
import os
import sys
from importlib.metadata import version
from .client import Client, Error, BUILDING, ROOM, minute, start_minute, query_start, day, identifier, config_path

BROWSERS = ('chromium', 'chrome', 'msedge')


def global_options(parser, default=False):
    output = parser.add_mutually_exclusive_group()
    output.add_argument('--json', action='store_true', default=default, help='完整命令结果的 JSON 输出（包括错误，不做展示性删减）')
    output.add_argument('--text', action='store_true', default=default, help='按命令展示主要信息的纯文本（默认，无需指定）')
    parser.add_argument('--no-proxy', action='store_true', default=default, help='忽略环境代理')
    parser.add_argument('--transport', choices=['direct', 'webvpn', 'auto'],
                        default=None if default is False else default, help='直连、学校 WebVPN 或请求前自动选择')


class CommandParser(argparse.ArgumentParser):
    """Subcommands also accept the global options; SUPPRESS keeps a value given before the subcommand."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        global_options(self, argparse.SUPPRESS)


def parser():
    p = argparse.ArgumentParser(prog='bnul', description='北师大图书馆座位预约；日期按上海时区，写操作默认预览')
    p.add_argument('-v', '--version', action='version', version='bnul ' + version('bnul'), help='显示已安装版本并退出')
    global_options(p)
    sub = p.add_subparsers(dest='command', required=True, parser_class=CommandParser)
    a = sub.add_parser('auth', help='登录、检查会话、退出登录',
                       description='自动登录凭据依次读取：环境变量 BNUL_USERNAME + BNUL_PASSWORD（或 BNUL_CREDENTIAL_ENV 指向的 dotenv 文件），'
                                   '再到 auth setup 保存的凭据（系统凭据库；不可用时经确认存入仅本用户可读的 credentials.env）。'
                                   '配置后无需登录命令，业务命令会在会话失效时后台自动登录，无需浏览器。')
    auth = a.add_subparsers(dest='action', required=True)
    auth.add_parser('setup', help='一次配置学校账号密码（优先系统凭据库），失效后自动登录')
    a = auth.add_parser('login', help='打开可见浏览器，处理人工登录、验证码或二次认证（需浏览器支持）')
    a.add_argument('--browser', choices=BROWSERS, help='使用的浏览器，同时保存为默认值')
    a.add_argument('--timeout', type=int, default=300, help='等待登录的秒数，默认 300')
    auth.add_parser('status', help='检查会话（不自动恢复），显示账号、凭据来源、自动登录方式和预约额度')
    auth.add_parser('logout', help='删除本机的会话、已保存的账号密码、登录浏览器资料和 WebVPN 会话')
    a = auth.add_parser('webvpn', help='学校 WebVPN 手机二维码认证；会话保存在当前电脑或 VPS')
    group = a.add_mutually_exclusive_group()
    group.add_argument('--status', action='store_true', help='读取后台扫码认证状态')
    group.add_argument('--refresh', action='store_true', help='生成新二维码，替换旧的待确认请求')
    a = auth.add_parser('install-browser', help='为可见窗口登录安装 Chromium（需浏览器支持）')
    a.add_argument('--with-deps', action='store_true', help='同时安装 Linux 系统依赖（可能需要管理员权限）')
    a = sub.add_parser('vpn', help='Linux 专用学校 SSL VPN，使用已有凭据自动重新登录')
    a.add_argument('action', choices=['run', 'route'], help='run 用于 systemd；route 用于 OpenConnect 钩子')
    a = sub.add_parser('skill', help='安装随 CLI 打包的 agent skill')
    a.add_argument('action', choices=['install'])
    a.add_argument('--dest', help='目标 skill 文件夹；默认安装到 Codex skills')
    a = sub.add_parser('watch', help='预约临期监控；默认预览，Linux/macOS')
    a.add_argument('-e', '--exe', '--execute', dest='execute', action='store_true', help='临期取消/结束并尝试重约')
    mode = a.add_mutually_exclusive_group()
    mode.add_argument('--once', action='store_true', help='白天检查一次后退出；夜间返回休眠状态')
    mode.add_argument('--status', action='store_true', help='只读本地监控状态和心跳')
    mode.add_argument('--notify-test', action='store_true', help='发送明确标记的测试通知')
    mode.add_argument('--health-check', action='store_true', help='独立检测停机或心跳超时并通知')
    a.add_argument('--state-file', help='持久状态文件，默认会话目录/watch-state.json')
    a.add_argument('--interval', type=int, default=120, help='未签到、临近暂离截止或异常时的检查秒数，默认 120；其余状态自适应')
    a.add_argument('--threshold', type=int, default=300, help='严格少于此秒数才操作，默认 300')
    a.add_argument('--max-renewals', type=int, default=3, help='每日最多尝试重约次数，0–3')
    a.add_argument('--notify', choices=['none', 'slack'], default='none', help='失败、恢复、操作结果通知')
    a.add_argument('--max-age', type=int, default=360, help='独立健康检查允许的心跳年龄，秒')
    sub.add_parser('buildings', help='楼馆、楼层和开放预约日期')
    for name in ('current', 'recent'):
        sub.add_parser(name, help='当前预约' if name == 'current' else '最近预约详情')
    a = sub.add_parser('life', help='预约变更记录；省略预约 ID 时查看当前预约')
    a.add_argument('make_id', type=identifier, nargs='?', help='预约 ID；默认当前预约（待签到、使用中或暂离）')
    for name, description in [('stop', '结束已签到的当前使用'), ('cancel', '取消未签到的当前预约')]:
        a = sub.add_parser(name, help=description + '；状态不符时自动改用另一操作；默认仅预览')
        a.add_argument('-e', '--exe', '--execute', dest='execute', action='store_true', help='实际提交；默认仅预览')
        a.add_argument('--expect-id', type=identifier, help='预期的当前预约 ID；指定时须一致，省略时使用本次读取的当前预约')
    for name, description in [('history', '分页查询预约历史'), ('breach', '分页查询违约记录')]:
        a = sub.add_parser(name, help=description)
        a.add_argument('--page', type=int, default=1, help='页码，从 1 开始')
        a.add_argument('--page-size', type=int, default=10, help='每页数量，1–100，默认 10')
    a = sub.add_parser('room-list', help='列出房间固定别名、名称和 ID')
    a.add_argument('--building', default=BUILDING, help='楼馆固定别名或 ID')
    a = sub.add_parser('recommend', help='按完整自习时段推荐座位，只查询，不预约')
    a.add_argument('--date', type=day, default='today')
    a.add_argument('--start', type=start_minute, required=True, help='HH:MM 或 now/现在/-1')
    a.add_argument('--end', type=minute, required=True)
    a.add_argument('--building', default=BUILDING, help='楼馆固定别名或 ID')
    a.add_argument('--floor', default='0', help='楼层固定别名或 ID；省略时查询全部楼层')
    group = a.add_mutually_exclusive_group()
    group.add_argument('--room', help='房间固定别名或 ID')
    group.add_argument('--room-order', help='依次搜索指定房间的固定别名或 ID，例如 r4,r3,r2')
    group.add_argument('--room-sequence', help=argparse.SUPPRESS)
    a.add_argument('--limit', type=int, default=5, help='推荐数量，默认 5，最多 20')
    a.add_argument('--max-checks', type=int, default=50, help='最多逐座校验数量，默认 50，最多 200')
    for name in ('rooms', 'seats', 'times', 'book'):
        a = sub.add_parser(name)
        a.add_argument('--date', type=day, default='today')
        if name == 'rooms':
            a.add_argument('--building', default=BUILDING, help='楼馆固定别名或 ID')
            a.add_argument('--floor', default='0', help='楼层固定别名或 ID；省略时查询全部楼层')
            a.add_argument('--power', action='store_true')
            a.add_argument('--windows', action='store_true')
        if name in ('seats', 'book'):
            a.add_argument('--room', help='房间固定别名或 ID；仅主馆可省略，默认 r4')
            a.add_argument('--building', default=BUILDING, help='楼馆固定别名或 ID')
        if name == 'seats':
            a.add_argument('--label', help='保留前导零，例如 008')
        if name == 'times':
            a.add_argument('--seat', type=identifier, required=True)
        if name == 'book':
            a.add_argument('--seat', required=True, help='座位编号（保留前导零，如 008）或座位 ID')
        a.add_argument('--start', type=start_minute, help='HH:MM 或 now/现在/-1（现在）', required=name in ('seats', 'book'))
        if name != 'times':
            a.add_argument('--end', type=minute, required=name != 'rooms')
        if name == 'book':
            a.add_argument('-e', '--exe', '--execute', dest='execute', action='store_true', help='实际提交一次预约')
    return p


def account_summary(info):
    # Identity and booking limits only; contact details and the signing key never leave the client.
    if not isinstance(info, dict):
        return {}
    username = str(info.get('username') or '')
    keys = ('fullName', 'flagName', 'collegeDepName', 'maxMinute', 'stepMinute', 'breachNum',
            'blackTime', 'blackMessage', 'totalMake', 'totalTime')
    return {'username': username[:3] + '****' + username[-5:] if len(username) > 8 else username,
            **{key: info[key] for key in keys if key in info}}


def run(args):
    if args.command == 'watch':
        from .watch import run_watch
        return run_watch(args)
    if args.command == 'vpn':
        from .sslvpn import run_vpn, configure_routes
        return run_vpn() if args.action == 'run' else configure_routes()
    if args.command == 'skill':
        from .install import install_skill
        return install_skill(args.dest)
    if args.command == 'auth' and args.action == 'install-browser':
        from .install import install_browser
        return install_browser(args.with_deps)
    if args.command == 'auth' and getattr(args, 'browser', None):
        from .network import save_setting
        save_setting('browser', args.browser)
    if args.command == 'auth' and args.action == 'login':
        if args.timeout <= 0:
            raise Error('timeout 必须大于 0')
        from .browser_auth import browser_login
        return browser_login(args.no_proxy, args.timeout)
    if args.command == 'auth':
        if args.action == 'webvpn':
            from .webvpn import start_login, read_status
            result = read_status() if args.status else start_login(args.refresh)
            if result.get('status') == 'failed':
                raise Error('学校 WebVPN 登录助手失败', 'WEBVPN_LOGIN_FAILED', result)
            return result
        if args.action == 'setup':
            from .credentials import credential_file, store_credentials, store_credentials_file
            username = input('学校账号: ').strip()
            password = getpass.getpass('学校密码（输入隐藏）: ')
            try:
                store_credentials(username, password)
                storage = '系统凭据库'
            except Error as exc:
                if exc.code != 'CREDENTIALS_UNAVAILABLE':
                    raise
                # Plaintext on disk is weaker than a keyring, so it needs an explicit yes every time.
                print(f'{exc}。\n可改为保存到 {credential_file()}：明文，仅当前系统用户可读。', file=sys.stderr)
                try:
                    answer = input('确认保存到该文件？[y/N] ').strip().lower()
                except EOFError:
                    answer = ''
                if answer not in ('y', 'yes'):
                    raise Error('未保存账号密码；也可用环境变量 BNUL_USERNAME/BNUL_PASSWORD 提供', 'CREDENTIALS_UNAVAILABLE') from None
                storage = f'凭据文件 {store_credentials_file(username, password)}'
            return {'configured': True, 'storage': storage, 'automaticLogin': True}
        if args.action == 'logout':
            from .browser_auth import logout
            return logout()
        if args.action == 'status':
            from .credentials import credential_source
            from datetime import datetime
            from zoneinfo import ZoneInfo
            result = {'credentials': credential_source() or '未配置'}
            if os.environ.get('BNUL_TOKEN'):
                result['session'] = {'source': '环境变量 BNUL_TOKEN'}
            elif config_path().is_file():
                saved = datetime.fromtimestamp(config_path().stat().st_mtime, ZoneInfo('Asia/Shanghai'))
                result['session'] = {'path': str(config_path()), 'savedAt': saved.strftime('%Y-%m-%d %H:%M:%S')}
            c = Client(no_proxy=args.no_proxy)
            c.auto_auth = False
            result['transport'] = c.network.mode
            result['loginMethod'] = 'HTTP（无需浏览器）'
            try:
                c.bootstrap()
                info = c.api('user/getUserInfo')
            except Error as exc:
                if str(exc.code) not in ('20003', '401', 'LOCAL_AUTH_MISSING', 'SESSION_SIGNING_KEY_MISSING'):
                    raise
                return {'authenticated': False, 'reason': str(exc), 'reasonCode': exc.code, **result}
            return {'authenticated': True, 'account': account_summary(info), **result}
    if args.command == 'rooms' and (args.start is None) != (args.end is None):
        raise Error('rooms 的 --start 和 --end 必须一起提供；不提供时显示房间清单')
    if hasattr(args, 'end') and args.end is not None and query_start(args.start, args.date) >= args.end:
        raise Error('结束时间必须晚于开始时间，且不可跨天')
    if args.command in ('history', 'breach') and (args.page < 1 or not 1 <= args.page_size <= 100):
        raise Error('page 必须大于 0；page-size 必须在 1–100 之间')
    c = Client(no_proxy=args.no_proxy)
    c.bootstrap()
    if args.command in ('history', 'breach'):
        return c.api(f'user/{args.command}/{args.page}/{args.page_size}')
    if args.command == 'buildings':
        from .buildings import building_catalog
        return building_catalog(c)
    if args.command in ('current', 'recent'):
        return c.api('user/currentUseMake' if args.command == 'current' else 'user/lastMake')
    if args.command == 'life':
        if args.make_id is None:
            # The current reservation is the only one the user can mean without naming an ID.
            current = c.api('user/currentUseMake')
            if not isinstance(current, dict) or not current.get('id'):
                raise Error('没有当前预约；查看其他预约的变更记录请提供预约 ID', 'NO_CURRENT_RESERVATION')
            args.make_id = identifier(str(current['id']))
        return c.api('user/makeLife/' + args.make_id)
    if hasattr(args, 'building'):
        from .buildings import location_selector
        args.building, floor = location_selector(c, args.building, getattr(args, 'floor', None))
        if hasattr(args, 'floor'):
            args.floor = floor
    if args.command in ('seats', 'book') and args.room is None:
        if args.building != BUILDING:
            raise Error('选择主馆以外的楼馆时，请用 --room 指定该馆的房间', 'ROOM_REQUIRED')
        args.room = ROOM
    if args.command == 'room-list' or (args.command == 'rooms' and args.start is None):
        from .rooms import room_catalog
        if args.command == 'rooms' and (args.power or args.windows):
            raise Error('设施筛选需同时提供 --start 和 --end；room-list 只列区域身份')
        result = room_catalog(c, args.building, refresh=True)
        floor = getattr(args, 'floor', '0')
        return {**result, 'rooms': [r for r in result['rooms'] if r['active']
                                   and (floor == '0' or r['floorId'] == floor)]}
    if args.command in ('seats', 'book', 'recommend') and args.room:
        from .rooms import room_selector
        args.room = room_selector(c, args.building, args.room)
    if args.command == 'recommend':
        from .rooms import ordered_rooms
        order = ordered_rooms(c, args.building, args.room_order, args.room_sequence) if args.room_order is not None or args.room_sequence is not None else None
        from .recommend import recommend
        return recommend(c, args.date, args.start, args.end, args.building, args.room,
                         args.floor, args.limit, args.max_checks, order)
    if args.command == 'rooms':
        return c.rooms(args.building, args.date, args.start, args.end,
                       args.floor, args.power, args.windows)
    if args.command == 'seats':
        seats = c.seats(args.room, args.date, args.start, args.end)
        rows = list(seats.values())
        if args.label:
            rows = [s for s in rows if s.get('label') == args.label]
        return sorted(rows, key=lambda s: s.get('label', ''))
    if args.command == 'times':
        return c.times(args.seat, args.date, args.start)
    if args.command == 'book':
        seats = c.seats(args.room, args.date, args.start, args.end)
        # A label such as 008 resolves from the seat list this command already fetched.
        matches = [args.seat] if args.seat in seats else [k for k, s in seats.items() if s.get('label') == args.seat]
        if len(matches) != 1:
            raise Error('指定座位不在该房间返回的座位列表中' if not matches else '该编号对应多个座位，请改用座位 ID',
                        'SEAT_NOT_FOUND')
        args.seat = identifier(matches[0])
        if args.execute:
            return c.book(args.seat, args.date, args.start, args.end, os.environ.get('BNUL_CAP_TOKEN'))
        plan = c.validate_booking(args.seat, args.date, args.start, args.end)
        plan.update({'roomId': args.room, 'seatLabel': seats[args.seat].get('label'), 'submitted': False})
        return plan
    if args.command in ('stop', 'cancel'):
        current = c.api('user/currentUseMake')
        if not isinstance(current, dict) or not current.get('id'):
            raise Error('没有当前预约可操作', 'NO_CURRENT_RESERVATION')
        make_id = identifier(str(current['id']))
        # Without --expect-id the ID read just above is the target; a given one must still match.
        if args.execute and args.expect_id is not None and args.expect_id != make_id:
            raise Error('当前预约 ID 与 --expect-id 不一致，未执行操作', 'RESERVATION_CHANGED')
        status = current.get('status')
        # Status alone decides how to release: unsigned is cancelled, signed-in use is stopped.
        action = {'RESERVE': 'cancel', 'CHECK_IN': 'stop', 'AWAY': 'stop'}.get(status)
        if action is None:
            raise Error('当前预约状态不支持此操作', 'INVALID_RESERVATION_STATE', {'status': status})
        switched = {'requestedAction': args.command, 'switched': True} if action != args.command else {}
        if not args.execute:
            return {'submitted': False, 'action': action, **switched, 'current': current}
        path = 'make/cancel/' + make_id if action == 'cancel' else 'make/stop'
        result = c.api(path)
        # Keep the raw server result unless the action changed, which the caller must see.
        return {'action': action, 'makeId': make_id, **switched, 'result': result} if switched else result


def main(argv=None):
    # UTF-8 output is stable for Chinese help and JSON, including Windows pipes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    previous_transport = os.environ.get('BNUL_TRANSPORT')
    try:
        if args.transport:
            os.environ['BNUL_TRANSPORT'] = args.transport
        data = run(args)
        if args.json:
            print(json.dumps({'ok': True, 'data': data}, ensure_ascii=False))
        else:
            from .output import format_text
            print(format_text(args, data))
        return 0
    except (Error, ValueError, OSError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, Error) else '输入或响应格式异常，请检查参数和配置'
        error = {'ok': False, 'error': message}
        if isinstance(exc, Error):
            error.update({'code': exc.code, 'data': exc.data})
        from .output import format_error
        print(json.dumps(error, ensure_ascii=False) if args.json else format_error(error),
              file=sys.stdout if args.json else sys.stderr)
        return 1
    finally:
        if args.transport:
            if previous_transport is None:
                os.environ.pop('BNUL_TRANSPORT', None)
            else:
                os.environ['BNUL_TRANSPORT'] = previous_transport
