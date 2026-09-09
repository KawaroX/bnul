"""Protocol verified against BNU's public PC frontend, September 2026."""
import base64
import hashlib
import hmac
import json
import os
import re
import socket
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from zoneinfo import ZoneInfo

BASE = 'https://libseat.bnu.edu.cn/jsq'
FRONT = '/static/frontApi/'
BUILDING = '1887388460760797184'
ROOM = '1888096971220160512'

class Error(Exception):
    def __init__(self, message, code=None, data=None):
        super().__init__(message)
        self.code, self.data = code, data

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Error('服务器重定向，请重新登录；未转发凭据')

def minute(value):
    if not re.fullmatch(r'\d{1,2}:\d{2}', value):
        raise ValueError('时间必须为 HH:MM')
    h, m = map(int, value.split(':'))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError('时间超出范围')
    return h * 60 + m

def start_minute(value):
    return -1 if value.lower() in ('now', '现在', '-1') else minute(value)


def query_start(start, date):
    if start != -1:
        return start
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    if day(date) != str(now.date()):
        raise Error('现在只能用于今天的预约')
    return now.hour * 60 + now.minute


def day(value):
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    if value in ('today', 'tomorrow'):
        return str(today + timedelta(days=value == 'tomorrow'))
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('日期必须为 YYYY-MM-DD、today 或 tomorrow')
    return date.fromisoformat(value).isoformat()

def identifier(value):
    if not re.fullmatch(r'\d+', str(value)):
        raise ValueError('ID 必须为数字字符串')
    return str(value)

def signing_key(system):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    try:
        decryptor = Cipher(algorithms.AES(system['makePrefix'].encode()),
                           modes.CBC(system['makeSuffix'].encode())).decryptor()
        raw = decryptor.update(base64.b64decode(system['hmacKey'])) + decryptor.finalize()
        unpad = PKCS7(128).unpadder()
        return (unpad.update(raw) + unpad.finalize()).decode().encode()
    except (KeyError, ValueError, TypeError) as exc:
        raise Error('无法解析系统签名配置，前端协议可能已变化') from exc

def signed_headers(key, request_id=None, timestamp=None):
    rid = request_id or str(uuid.uuid4())
    stamp = str(timestamp if timestamp is not None else int(time.time() * 1000))
    signature = hmac.new(key, f'seat::{rid}::{stamp}::POST'.encode(), hashlib.sha256).hexdigest()
    return {'X-request-id': rid, 'X-request-date': stamp, 'X-hmac-request-key': signature}

def config_path():
    return Path(os.environ.get('BNUL_CONFIG', str(Path.home() / '.config/bnul/session.json')))

def save_token(token):
    if not isinstance(token, str) or not token.strip() or '\n' in token or '\r' in token:
        raise Error('无效 token')
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    import tempfile
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.bnul-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump({'token': token.strip()}, f)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def load_token():
    token = os.environ.get('BNUL_TOKEN')
    if token:
        return token
    try:
        return json.loads(config_path().read_text())['token']
    except FileNotFoundError:
        raise Error('没有本地会话', 'LOCAL_AUTH_MISSING')
    except (KeyError, ValueError):
        raise Error('本地登录配置损坏，请重新导入')

class Client:
    def __init__(self, token=None, no_proxy=False, timeout=20):
        self.token, self.timeout = token, timeout
        self.no_proxy = no_proxy
        self.auto_auth = token is None and not os.environ.get('BNUL_TOKEN')
        self.auth_recovered = False
        self.opener = build_opener(NoRedirect(), *([ProxyHandler({})] if no_proxy else []))
        self.system = None
        self.key = None

    def request(self, path, body=None, public=False):
        if not path.startswith('/static/') or '://' in path:
            raise Error('无效接口路径')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
                   'Origin': 'https://libseat.bnu.edu.cn',
                   'Referer': 'https://libseat.bnu.edu.cn/jsq-v/', 'loginType': 'PC'}
        if self.key:
            headers.update(signed_headers(self.key))
        if not public:
            headers['token'] = self.token or load_token()
        req = Request(BASE + path, json.dumps(body if body is not None else {}).encode(), headers, method='POST')
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise Error(f'HTTP {exc.code}；请求未重试。写操作请先查询当前预约确认结果', exc.code) from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise Error('网络请求失败；请求未重试。写操作结果可能未知，请先查询当前预约') from None
        except (ValueError, UnicodeError):
            raise Error('服务器未返回合法 JSON；写操作请先查询当前预约确认结果') from None
        if not isinstance(result, dict):
            raise Error('服务器响应格式异常')
        if result.get('status') is not True:
            code = result.get('code')
            message = result.get('message') or '接口请求失败'
            if str(code) == '20003':
                message = '服务器判定登录失效'
            raise Error(message, code, result.get('data'))
        return result.get('data')

    def bootstrap(self):
        self.system = self.request('/static/public/cg/getSysSet/PC', public=True)
        if not isinstance(self.system, dict):
            raise Error('系统配置格式异常')
        if str(self.system.get('hmac')) == '1':
            self.key = signing_key(self.system)
        return self.system

    def recover_auth(self):
        from .browser_auth import browser_login
        import sys
        self.auth_recovered = True  # at most one recovery per client/command
        print('登录会话失效，正在后台自动恢复…', file=sys.stderr)
        browser_login(no_proxy=self.no_proxy, timeout=60, headless=True)
        self.token = load_token()
        self.bootstrap()

    def api(self, path, body=None):
        # Mutations get an authenticated preflight; never replay an uncertain write.
        read_only = path.startswith(('res/', 'user/')) and path != 'user/logout'
        if not read_only and self.auto_auth:
            self.api('user/getUserInfo')
        try:
            return self.request(FRONT + path, body)
        except Error as exc:
            if (read_only and self.auto_auth and not self.auth_recovered
                    and str(exc.code) in ('20003', '401', 'LOCAL_AUTH_MISSING')):
                self.recover_auth()
                return self.request(FRONT + path, body)
            raise

    def seats(self, room, date, start, end):
        return self.api(f'res/freeSeatIdsDuration/{identifier(room)}/{day(date)}',
                        {'beginMinute': query_start(start, date), 'endMinute': end, 'minMinute': 0})

    def times(self, seat, date, start=None):
        suffix = f'{identifier(seat)}/{day(date)}'
        result = {'timeline': self.api('res/getTimeLine/' + suffix),
                  'starts': self.api('res/getStartTimes/' + suffix)}
        if start is not None:
            result['ends'] = self.api(f'res/getEndTimes/{suffix}/{query_start(start, date)}')
        return result

    def validate_booking(self, seat, date, start, end):
        if not 0 <= query_start(start, date) < end < 1440:
            raise Error('结束时间必须晚于开始时间，且不可跨天')
        times = self.times(seat, date, start)
        if ('now' if start == -1 else str(start)) not in {str(row[0]) for row in times['starts']}:
            raise Error('开始时间不可选，请查看 times 返回的 starts')
        if str(end) not in {str(row[0]) for row in times['ends']}:
            raise Error('结束时间不可选，请查看 times 返回的 ends')
        return {'seatId': identifier(seat), 'date': day(date), 'beginMinute': start,
                'endMinute': end, 'validated': True}

    def book(self, seat, date, start, end, cap_token=None):
        self.validate_booking(seat, date, start, end)
        mode = self.system.get('mackCaptcha')
        if mode is None:
            raise Error('系统未返回验证码策略，无法安全提交')
        required = str(mode) == '2'
        if str(mode) not in ('0', '2'):
            required = bool(self.request('/static/cap/cg/checkHigh'))
        if required and not cap_token:
            raise Error('当前需要验证码，请在官网完成验证后提供 capToken，或在官网预约')
        cap = quote(cap_token or 'capToken', safe='')
        return self.api(f'make/freeBook/{identifier(seat)}/{day(date)}/{start}/{end}?capToken={cap}')
