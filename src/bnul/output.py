"""Task-oriented text views. JSON serialization is independent of these views."""

STATUSES = {'RESERVE': '待签到', 'CHECK_IN': '使用中', 'AWAY': '暂离',
            'STOP': '已结束', 'FREE': '空闲', 'IN_USE': '使用中', 'BOOKED': '已预约'}
LABELS = {'id': 'ID', 'message': '服务端提示', 'remark': '备注', 'code': '错误码',
          'error': '错误', 'data': '详情', 'status': '状态', 'ctId': '当前预约ID',
          'makeId': '预约ID', 'seatId': '座位ID', 'roomId': '房间ID',
          'name': '名称', 'date': '日期', 'reason': '原因', 'type': '类型',
          'createdDate': '时间', 'beginMinute': '开始', 'endMinute': '结束',
          'installed': '安装位置', 'authenticated': '已登录', 'configured': '已配置',
          'storage': '凭据存储', 'automaticLogin': '自动登录', 'saved': '已保存',
          'path': '保存位置', 'credentials': '自动登录凭据', 'browser': '浏览器',
          'loggedOut': '已退出登录', 'credentialsRemoved': '已删除系统凭据库中的账号密码',
          'credentialError': '凭据删除失败', 'removed': '已删除文件',
          'environmentCredentialsPresent': '环境变量中仍有账号密码，自动登录仍可用',
          'environmentTokenPresent': '环境中仍有指定 token'}


def present(value):
    return value is not None and value != '' and value != [] and value != {}


def scalar(value):
    if not present(value):
        return ''
    if isinstance(value, bool):
        return '是' if value else '否'
    return str(value)


def clock(value):
    if value in (-1, 'now'):
        return '现在'
    if isinstance(value, int) and not isinstance(value, bool):
        return f'{value // 60:02d}:{value % 60:02d}'
    return scalar(value)


def first(row, *keys):
    return next((row[key] for key in keys if present(row.get(key))), None)


def status(value):
    return STATUSES.get(value, scalar(value))


def fields(pairs, separator='；'):
    return separator.join(f'{label}: {scalar(value)}' for label, value in pairs if present(value))


def location(row):
    return scalar(row.get('location')).replace('|', ' / ') or ' / '.join(
        scalar(value) for value in (first(row, 'buildingName', 'buildName'), row.get('floorName'), row.get('roomName')) if present(value))


def period(row):
    date = first(row, 'makeDateStr', 'date')
    begin = clock(first(row, 'makeBeginStr', 'beginMinute', 'makeBegin', 'start'))
    end = clock(first(row, 'makeEndStr', 'endMinute', 'makeEnd', 'end'))
    interval = f'{begin}–{end}' if begin and end else fields([('开始', begin), ('结束', end)])
    return ' '.join(scalar(v) for v in (date, interval) if present(v))


def plain(value):
    """Fallback for errors and response types without an observed business schema."""
    if isinstance(value, dict):
        return '\n'.join(f'{LABELS.get(key, key)}: {plain(item)}' for key, item in value.items() if present(item))
    if isinstance(value, list):
        return '\n'.join(plain(item) for item in value if present(item))
    return scalar(value)


def table(rows, columns):
    # Drop empty columns, retaining real zero / false values and every record.
    columns = [(title, getter) for title, getter in columns if any(present(getter(row)) for row in rows)]
    if not rows or not columns:
        return ''
    lines = [' | '.join(title for title, _ in columns)]
    lines.extend(' | '.join(scalar(getter(row)) for _, getter in columns) for row in rows)
    return '\n'.join(lines)


def reservation(row):
    if not isinstance(row, dict):
        return plain(row)
    pairs = [('时段', period(row)), ('地点', location(row)), ('座位', row.get('seatLabel')),
             ('状态', status(row.get('status'))), ('预约ID', row.get('id')),
             ('房间ID', row.get('roomId')), ('座位ID', row.get('seatId')),
             ('实际使用', row.get('actualStr')), ('暂离时段', row.get('awayRange')),
             ('使用分钟', row.get('useMinute') if row.get('actualStr') else None),
             ('时段校验', '通过' if row.get('validated') else None),
             ('服务端提示', row.get('message')), ('备注', row.get('remark'))]
    return fields(pairs, '\n') or plain(row)


def reservation_list(data):
    if isinstance(data, list):
        return '\n\n'.join(f'{i}. {reservation(row)}' for i, row in enumerate(data, 1))
    return reservation(data)


def buildings(data):
    lines = [fields([('可预约日期', '、'.join(map(str, data.get('dates', []))))])]
    for row in data.get('buildings', []):
        lines.append(fields([('楼馆', row.get('name')), ('别名', row.get('alias')), ('ID', row.get('id')),
                             ('开放时间', scalar(row.get('seTime')).replace(' _ ', '–')),
                             ('启用', bool(row['enabled']) if 'enabled' in row else None), ('备注', row.get('remark'))]))
        for floor in row.get('floors', []):
            lines.append('  ' + fields([('楼层', floor.get('name')), ('别名', floor.get('alias')), ('ID', floor.get('id')),
                                       ('启用', bool(floor['enabled']) if 'enabled' in floor else None)]))
    return '\n'.join(line for line in lines if line) or '没有楼馆信息。'


def rooms(args, data):
    if isinstance(data, dict) and 'rooms' in data:
        rows = data['rooms']
        heading = f'房间清单：{len(rows)} 个'
        columns = [('别名', lambda r: r.get('alias')),
                   ('房间', lambda r: r.get('name')), ('房间ID', lambda r: r.get('id'))]
    else:
        rows = data
        heading = f'房间查询：{period(vars(args))}，{len(rows)} 个'
        columns = [('楼馆', lambda r: r.get('buildingName')), ('楼层', lambda r: r.get('floorName')),
                   ('房间', lambda r: r.get('name')), ('房间ID', lambda r: r.get('id')),
                   ('总座位', lambda r: r.get('seatTotal')), ('空闲数', lambda r: r.get('seatFree')),
                   ('锁定', lambda r: r.get('seatLock')), ('电源', lambda r: r.get('seatPower')),
                   ('靠窗', lambda r: r.get('seatWindows')), ('电脑', lambda r: r.get('seatComputer')),
                   ('最长分钟', lambda r: r.get('maxMinute')), ('备注', lambda r: r.get('remark'))]
    return heading + ('\n' + table(rows, columns) if rows else '\n没有匹配房间。')


def seats(args, data):
    heading = f'座位查询：{period(vars(args))}\n房间ID: {args.room}；共 {len(data)} 个座位'
    if not data:
        return heading + '\n没有匹配座位。'
    columns = [('座位', lambda r: r.get('label')), ('位置', lambda r: r.get('name')),
               ('当前状态', lambda r: status(r.get('status'))),
               ('afterFree', lambda r: r.get('afterFree')), ('座位ID', lambda r: r.get('id'))]
    return heading + '\n' + table(data, columns)


def times(args, data):
    lines = [fields([('座位ID', args.seat), ('日期', args.date)])]
    timeline = data.get('timeline', {})
    free = timeline.get('freeList', []) if isinstance(timeline, dict) else []
    lines.append('空闲时段: ' + ('、'.join(str(row['label']) for row in free if row.get('label')) or '无'))
    for key, title in [('starts', '可选开始'), ('ends', '可选结束')]:
        if key in data:
            options = [scalar(row[1] if len(row) > 1 else row[0]) for row in data[key] if row]
            context = f'（从 {clock(args.start)} 开始）' if key == 'ends' and args.start is not None else ''
            lines.append(f'{title}{context}: ' + ('、'.join(options) or '无'))
    return '\n'.join(lines)


def recommend(data):
    rows = data.get('recommendations', [])
    scope = data.get('scope', {})
    lines = [f'座位推荐：{period(data)}；找到 {len(rows)} 个',
             fields([('楼馆ID', scope.get('buildingId')), ('楼层ID', scope.get('floorId') if scope.get('floorId') != '0' else None),
                     ('房间ID', scope.get('roomId')), ('搜索房间数', scope.get('roomsSearched')),
                     ('房间顺序', ' → '.join(scope.get('roomOrder') or []))]),
             f"已检查 {data.get('checkedSeats', 0)}/{data.get('candidateSeats', 0)} 个候选；" +
             ('已查完该范围。' if data.get('searchExhausted') else
              {'result_limit': '已达到推荐数量。', 'check_limit': '已达到检查上限，尚未查完。'}.get(data.get('stopReason'), '尚未查完。'))]
    if not rows:
        lines.append('已检查的候选中未找到匹配座位。')
    for i, row in enumerate(rows, 1):
        lines.append(f'{i}. ' + fields([('地点', location(row)), ('座位', row.get('seatLabel')),
                                       ('当前状态', status(row.get('currentStatus'))),
                                       ('房间ID', row.get('roomId')), ('座位ID', row.get('seatId')),
                                       ('校验时间', row.get('checkedAt'))]))
    if rows and all(row.get('validated') for row in rows):
        lines.append('以上座位均通过完整时段校验。')
    lines.append('未创建预约。' if data.get('submitted') is False else fields([('已提交', data.get('submitted'))]))
    return '\n'.join(line for line in lines if line)


def life(args, data):
    if not data:
        return '没有预约变更记录。'
    if not isinstance(data, list):
        return plain(data)
    columns = [('时间', lambda r: r.get('createdDate')), ('变更', lambda r: first(r, 'stageName', 'stage', 'status')),
               ('来源', lambda r: first(r, 'sourceName', 'source')), ('说明', lambda r: r.get('message'))]
    return f'预约ID: {args.make_id}\n' + table(data, columns)


def minutes(value):
    if not isinstance(value, int) or isinstance(value, bool):
        return scalar(value)
    hours, rest = divmod(value, 60)
    return f'{hours} 小时 {rest} 分钟' if hours and rest else f'{hours} 小时' if hours else f'{rest} 分钟'


def auth_status(data):
    account = data.get('account') or {}
    session = data.get('session') or {}
    who = '，'.join(scalar(account.get(k)) for k in ('fullName', 'flagName', 'collegeDepName') if present(account.get(k)))
    lines = [fields([('登录状态', '已登录' if data.get('authenticated') else '未登录'),
                     ('原因', data.get('reason'))]),
             fields([('账号', account.get('username'))]) + (f'（{who}）' if who else ''),
             fields([('会话', session.get('source') or session.get('path')), ('保存于', session.get('savedAt'))]),
             fields([('连接方式', {'direct': '直连', 'webvpn': '学校 WebVPN'}.get(data.get('transport'), data.get('transport'))),
                     ('自动登录凭据', data.get('credentials')), ('浏览器', data.get('browser'))])]
    if account:
        lines.append(fields([('单次最长预约', minutes(account.get('maxMinute'))), ('时间粒度', minutes(account.get('stepMinute'))),
                             ('违约次数', account.get('breachNum')), ('禁约至', account.get('blackTime')),
                             ('禁约说明', account.get('blackMessage'))]))
        lines.append(fields([('累计预约', f"{account['totalMake']} 次" if present(account.get('totalMake')) else None),
                             ('累计时长', minutes(account.get('totalTime')))]))
    if not data.get('authenticated'):
        if session.get('source'):
            hint = '已指定 BNUL_TOKEN，不会自动登录；更换 token 或取消该环境变量'
        elif data.get('credentials') in (None, '未配置') or str(data.get('credentials')).startswith('不可用'):
            hint = '先运行 bnul auth setup，或设置环境变量 BNUL_USERNAME/BNUL_PASSWORD'
        else:
            hint = '直接运行业务命令即可，会在后台自动登录'
        lines.append('下一步: ' + hint)
    return '\n'.join(line for line in lines if line)


def format_text(args, data):
    command = args.command
    if command == 'auth' and getattr(args, 'action', None) == 'status' and isinstance(data, dict):
        return auth_status(data)
    if command == 'buildings' and isinstance(data, dict):
        return buildings(data)
    if command in ('room-list', 'rooms') and isinstance(data, (dict, list)):
        return rooms(args, data)
    if command == 'seats' and isinstance(data, list):
        return seats(args, data)
    if command == 'times' and isinstance(data, dict):
        return times(args, data)
    if command == 'recommend' and isinstance(data, dict):
        return recommend(data)
    if command in ('current', 'recent'):
        if not present(data):
            return '没有当前预约。' if command == 'current' else '没有最近预约记录。'
        return reservation_list(data)
    if command in ('history', 'breach') and isinstance(data, dict):
        rows = data.get('list', [])
        heading = fields([('页码', args.page), ('总数', data.get('count')), ('本页', len(rows))])
        if command == 'breach':
            # No nonempty breach sample yet: retain nonempty fields rather than guess their meaning.
            body = plain(rows) if rows else '没有违约记录。'
        else:
            body = reservation_list(rows) if rows else '没有预约历史。'
        if isinstance(data.get('count'), int) and args.page * args.page_size < data['count']:
            heading += f'；下一页: --page {args.page + 1}'
        return heading + '\n' + body
    if command == 'life':
        return life(args, data)
    if command in ('book', 'cancel', 'stop'):
        heading = '已提交请求；以下为服务端结果：' if args.execute else '操作预览（未提交）：'
        if isinstance(data, dict) and data.get('switched'):
            names = {'cancel': 'cancel（取消预约）', 'stop': 'stop（结束使用）'}
            verb = '已自动改用' if args.execute else '执行时将改用'
            heading = f'当前预约状态不适用 {data["requestedAction"]}，{verb} {names[data["action"]]}。\n' + heading
            if args.execute:
                data = data['result']
        payload = data.get('current', data) if isinstance(data, dict) else data
        return heading + '\n' + (reservation_list(payload) or '服务端未返回详情。')
    return plain(data) or '完成。'


def format_error(error):
    return plain({key: value for key, value in error.items() if key != 'ok'})
