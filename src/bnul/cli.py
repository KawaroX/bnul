import argparse
import getpass
import html
import json
import os
import re
import sys
from urllib.parse import parse_qs, urlparse, quote
from .client import Client, Error, BUILDING, ROOM, minute, start_minute, query_start, day, identifier, save_token, config_path


def parser():
    p = argparse.ArgumentParser(prog='bnul', description='北师大图书馆座位预约；日期按上海时区，写操作默认预览')
    p.add_argument('--json', action='store_true', help='结构化 JSON 输出（包括错误）')
    p.add_argument('--no-proxy', action='store_true', help='忽略环境代理')
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('login', help='auth login 的兼容别名：浏览器登录')
    a.add_argument('--timeout', type=int, default=300, help='等待登录的秒数，默认 300')
    a = sub.add_parser('auth', help='登录、检查会话、导入或清除本地凭据')
    auth = a.add_subparsers(dest='action', required=True)
    a = auth.add_parser('login', help='打开可见浏览器，处理人工登录或验证码')
    a.add_argument('--timeout', type=int, default=300, help='等待登录的秒数，默认 300')
    a.add_argument('--file', help=argparse.SUPPRESS)
    for action, description in [('import', '备用：导入请求头 token 或 curl'),
                                ('exchange-link', '高级诊断：兑换 URL 票据，不是常规登录')]:
        a = auth.add_parser(action, help=description)
        a.add_argument('--file', help='从文件读取；- 表示标准输入，否则隐藏输入')
    auth.add_parser('setup', help='一次配置学校账号密码到 系统凭据存储，失效后自动登录')
    auth.add_parser('forget', help='删除系统凭据存储账号密码，保留现有会话')
    auth.add_parser('status', help='向服务器验证当前保存的会话')
    auth.add_parser('clear', help='仅清除本地 token，保留系统凭据存储/浏览器资料，后续可自动恢复')
    a = auth.add_parser('install-browser', help='安装自动登录使用的 Chromium')
    a.add_argument('--with-deps', action='store_true', help='同时安装 Linux 系统依赖（可能需要管理员权限）')
    a = sub.add_parser('skill', help='安装随 CLI 打包的 agent skill')
    a.add_argument('action', choices=['install'])
    a.add_argument('--dest', help='目标 skill 文件夹；默认安装到 Codex skills')
    sub.add_parser('buildings', help='楼馆、楼层和开放预约日期')
    for name in ('current', 'recent'):
        sub.add_parser(name, help='当前预约' if name == 'current' else '最近预约详情')
    a = sub.add_parser('life', help='预约变更记录')
    a.add_argument('make_id', type=identifier)
    a = sub.add_parser('stop', help='结束当前使用；默认仅预览')
    a.add_argument('--execute', action='store_true')
    a.add_argument('--expect-id', type=identifier, help='执行时必须指定预期的当前预约 ID')
    a = sub.add_parser('room-list', help='列出稳定序号、简称、房间名称和 ID')
    a.add_argument('--building', type=identifier, default=BUILDING)
    a = sub.add_parser('recommend', help='按完整自习时段推荐座位，只查询，不预约')
    a.add_argument('--date', type=day, default='today')
    a.add_argument('--start', type=start_minute, required=True, help='HH:MM 或 now/现在/-1')
    a.add_argument('--end', type=minute, required=True)
    a.add_argument('--building', type=identifier, default=BUILDING)
    a.add_argument('--floor', type=identifier, default='0')
    group = a.add_mutually_exclusive_group()
    group.add_argument('--room', help='房间 ID、清单序号、名称或唯一缩写')
    group.add_argument('--room-order', help='依次搜索指定房间，例如 4,3,2 或 3F自习,2F自习')
    group.add_argument('--room-sequence', help='紧凑序号顺序，例如 432；0 表示第 10 项')
    a.add_argument('--limit', type=int, default=5, help='推荐数量，默认 5，最多 20')
    a.add_argument('--max-checks', type=int, default=50, help='最多逐座校验数量，默认 50，最多 200')
    for name in ('rooms', 'seats', 'times', 'book'):
        a = sub.add_parser(name)
        a.add_argument('--date', type=day, default='today')
        if name == 'rooms':
            a.add_argument('--building', type=identifier, default=BUILDING)
            a.add_argument('--floor', type=identifier, default='0')
            a.add_argument('--power', action='store_true')
            a.add_argument('--windows', action='store_true')
        if name in ('seats', 'book'):
            a.add_argument('--room', default=ROOM, help='房间 ID、序号、名称或唯一缩写')
            a.add_argument('--building', type=identifier, default=BUILDING)
        if name == 'seats':
            a.add_argument('--label', help='保留前导零，例如 008')
        if name in ('times', 'book'):
            a.add_argument('--seat', type=identifier, required=True)
        a.add_argument('--start', type=start_minute, help='HH:MM 或 now/现在/-1（现在）', required=name in ('seats', 'book'))
        if name != 'times':
            a.add_argument('--end', type=minute, required=name != 'rooms')
        if name == 'book':
            a.add_argument('--execute', action='store_true', help='实际提交一次预约')
    return p


def read_secret(args):
    if args.file:
        if args.file == '-':
            return sys.stdin.read().strip()
        from pathlib import Path
        return Path(args.file).read_text(encoding="utf-8").strip()
    prompt = '粘贴新鲜官网登录链接（输入隐藏；自动获取请用 bnul auth login）: ' if args.action == 'exchange-link' else '粘贴请求头 token 或 curl（输入隐藏）: '
    return getpass.getpass(prompt).strip()


def imported_token(text):
    text = html.unescape(text)
    match = re.search(r"(?:-H|--header)\s+['\"]token:\s*([^'\"\r\n]+)", text, re.I)
    if match:
        return match.group(1).strip()
    if not text or re.search(r'\s', text) or '://' in text:
        raise Error('未找到请求头 token；常规登录请使用 auth login；URL 诊断用 auth exchange-link')
    return text


def login_link_token(text):
    text = html.unescape(text.strip())
    match = re.fullmatch(r'\[[^\]]*\]\((https://[^\s]+)\)', text)
    if match:
        text = match.group(1)
    url = urlparse(text)
    if url.scheme != 'https' or url.netloc != 'libseat.bnu.edu.cn':
        raise Error('需要 libseat.bnu.edu.cn 的 HTTPS 登录链接')
    tokens = parse_qs(url.query).get('token', [])
    if len(tokens) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', tokens[0]):
        raise Error('登录链接需包含唯一、完整的 JWT token；不要粘贴转义后的文本')
    return tokens[0]


def run(args):
    if args.command == 'skill':
        from .install import install_skill
        return install_skill(args.dest)
    if args.command == 'auth' and args.action == 'install-browser':
        from .install import install_browser
        return install_browser(args.with_deps)
    if args.command == 'login' or (args.command == 'auth' and args.action == 'login'):
        if getattr(args, 'file', None):
            raise Error('auth login 现为浏览器登录；旧 --file URL 兑换请显式使用 auth exchange-link --file，不会自动改变操作')
        if args.timeout <= 0:
            raise Error('timeout 必须大于 0')
        from .browser_auth import browser_login
        return browser_login(args.no_proxy, args.timeout)
    if args.command == 'auth':
        if args.action == 'setup':
            from .credentials import store_credentials
            username = input('学校账号: ').strip()
            password = getpass.getpass('学校密码（仅保存到 系统凭据存储，输入隐藏）: ')
            store_credentials(username, password)
            return {'configured': True, 'storage': 'system keyring', 'automaticLogin': True}
        if args.action == 'forget':
            from .credentials import forget_credentials
            forget_credentials()
            return {'credentialsRemoved': True}
        if args.action == 'clear':
            config_path().unlink(missing_ok=True)
            return {'cleared': True, 'environmentTokenPresent': bool(os.environ.get('BNUL_TOKEN'))}
        if args.action == 'import':
            token = imported_token(read_secret(args))
            client = Client(token, args.no_proxy)
            client.bootstrap()
            client.api('user/getUserInfo')
            save_token(token)
            return {'saved': True, 'path': str(config_path())}
        if args.action == 'exchange-link':
            token = login_link_token(read_secret(args))
            client = Client(no_proxy=args.no_proxy)
            client.bootstrap()
            try:
                data = client.request('/static/public/auth/cas/' + quote(token, safe=''),
                                      {'token': token, 'loginType': 'PC'}, public=True)
            except Error as exc:
                raise Error('登录链接兑换失败；服务端返回：' + str(exc).replace(token, '[REDACTED]') + '。具体原因尚未确认；常规登录请用 bnul auth login', exc.code) from None
            save_token(data['token'])
            return {'saved': True, 'path': str(config_path())}
    if args.command == 'rooms' and (args.start is None) != (args.end is None):
        raise Error('rooms 的 --start 和 --end 必须一起提供；不提供时显示房间清单')
    if hasattr(args, 'end') and args.end is not None and query_start(args.start, args.date) >= args.end:
        raise Error('结束时间必须晚于开始时间，且不可跨天')
    c = Client(no_proxy=args.no_proxy)
    c.bootstrap()
    if args.command == 'auth':
        c.auto_auth = False
        c.api('user/getUserInfo')
        return {'authenticated': True}
    if args.command == 'buildings':
        return c.api('res/buildingFloorDate')
    if args.command in ('current', 'recent', 'life'):
        path = {'current': 'user/currentUseMake', 'recent': 'user/lastMake',
                'life': 'user/makeLife/' + getattr(args, 'make_id', '')}[args.command]
        return c.api(path)
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
        if args.seat not in seats:
            raise Error('指定座位不在该房间返回的座位列表中')
        if args.execute:
            return c.book(args.seat, args.date, args.start, args.end, os.environ.get('BNUL_CAP_TOKEN'))
        plan = c.validate_booking(args.seat, args.date, args.start, args.end)
        plan.update({'roomId': args.room, 'seatLabel': seats[args.seat].get('label'), 'submitted': False})
        return plan
    if args.command == 'stop':
        current = c.api('user/currentUseMake')
        if not isinstance(current, dict) or not current.get('id'):
            raise Error('没有当前预约可结束')
        if not args.execute:
            return {'submitted': False, 'action': 'stop', 'current': current}
        if args.expect_id != str(current['id']):
            raise Error('当前预约 ID 与 --expect-id 不一致，未执行结束操作')
        return c.api('make/stop')


def main(argv=None):
    # UTF-8 output is stable for Chinese help and JSON, including Windows pipes.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        data = run(args)
        if args.json:
            print(json.dumps({'ok': True, 'data': data}, ensure_ascii=False))
        elif args.command == 'room-list' or (args.command == 'rooms' and args.start is None):
            print('序号  别名  简称 / 全名 / ID')
            for room in data['rooms']:
                print(f"{room['number']:>2}  {room['alias']}  {room['shortName']} / {room['name']} / {room['id']}")
            print('序号在本机该楼馆内保留；新增房间追加，已移除编号不复用。0 可代指 10。')
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    except (Error, ValueError, OSError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, Error) else '输入或响应格式异常，请检查参数和配置'
        error = {'ok': False, 'error': message}
        if isinstance(exc, Error):
            error.update({'code': exc.code, 'data': exc.data})
        print(json.dumps(error, ensure_ascii=False) if args.json else message,
              file=sys.stdout if args.json else sys.stderr)
        return 1
