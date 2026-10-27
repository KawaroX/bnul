"""Background login through the school CAS with plain HTTP requests, direct or via WebVPN; no browser needed."""
import base64
import http.cookiejar
import json
import os
import random
import re
import uuid
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request, build_opener
from .client import Client, Error, config_path, save_token

CAS = 'https://cas.bnu.edu.cn'
LIBRARY = 'https://libseat.bnu.edu.cn'
ENTRY = LIBRARY + '/rem/static/sso/login?redirectUrl=' + quote(LIBRARY + '/jsq-v', safe='')
HOSTS = ('libseat.bnu.edu.cn', 'cas.bnu.edu.cn')
MAX_HOPS = 8
# The school pages were verified with a desktop browser identity.
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')
RETRY_HINT = '未重复提交密码。请运行 bnul auth login 在可见窗口查看官网提示'


class KeepRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # every hop is checked before it is followed


class Session:
    """Request official URLs over the network's transport; redirects come back as official URLs."""
    def __init__(self, network):
        self.network = network
        # WebVPN requests must carry the scanned WebVPN cookies; direct logins start from a clean jar.
        jar = network.cookies if network.cookies is not None else http.cookiejar.CookieJar()
        handlers = [KeepRedirect(), HTTPCookieProcessor(jar)]
        if network.no_proxy:
            handlers.append(ProxyHandler({}))
        self.opener = build_opener(*handlers)

    def wire(self, url):
        return self.network.wire(url)

    def resolve(self, base, ref):
        # Links on WebVPN pages are relative to the rewritten URL.
        return self.network.official(urljoin(self.wire(base), ref))

    def send(self, url, data=None, headers=None):
        wire = self.wire(url)
        req = Request(wire, data, {'User-Agent': USER_AGENT, **(headers or {})},
                      method='GET' if data is None else 'POST')
        try:
            with self.opener.open(req, timeout=20) as response:
                status, location, body = response.status, response.headers.get('Location'), response.read()
        except HTTPError as exc:
            status, location, body = exc.code, exc.headers.get('Location'), exc.read()
        except (URLError, OSError):
            raise Error('自动登录时网络请求失败；未重复提交密码') from None
        if location:
            target = urlsplit(urljoin(wire, location))
            if target.netloc == 'webvpn.bnu.edu.cn' and target.path.startswith('/login'):
                raise Error('学校 WebVPN 会话失效；运行 bnul --json auth webvpn 获取新二维码。', 'WEBVPN_LOGIN_REQUIRED')
            location = self.resolve(url, location)
        return status, location, body.decode('utf-8', 'replace')


def flow_changed(sent=False):
    return Error('学校登录页面流程与预期不符，已停止自动登录；' + (RETRY_HINT if sent else '请运行 bnul auth login'),
                 'AUTH_FLOW_CHANGED')


def cas_login(url):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.netloc == 'cas.bnu.edu.cn'
            and parsed.path.split(';', 1)[0] == '/cas/login')


def library_token(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'libseat.bnu.edu.cn' or not parsed.path.startswith('/jsq-v'):
        return None
    query = parse_qs(parsed.query) or parse_qs(parsed.fragment.partition('?')[2])
    value = (query.get('token') or [''])[0].strip()
    return value or None


def device_id():
    # A stable id stands in for the official page's browser fingerprint, so CAS sees one device.
    path = config_path().parent / 'device-id'
    try:
        value = path.read_text(encoding='ascii').strip()
        if re.fullmatch(r'[0-9a-f]{32}', value):
            return value
    except (OSError, UnicodeError):
        pass
    value = uuid.uuid4().hex
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='ascii') as stream:
            stream.write(value)
    except OSError:
        pass
    return value


def encrypt(public_key, value):
    # JSEncrypt on the official page: RSA PKCS#1 v1.5, base64.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    key = serialization.load_der_public_key(base64.b64decode(public_key))
    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError('CAS public key is not RSA')
    return base64.b64encode(key.encrypt(value.encode(), padding.PKCS1v15())).decode()


def submit_password(session, page_url, page, credentials=None):
    """Post the CAS form once, the way the official page does; return the redirect target."""
    form = re.search(r'<form id="loginForm" action="([^"]+)"', page)
    hidden = {name: unescape(value) for name, value in
              re.findall(r'<input type="hidden" name="(lt|execution|_eventId)"[^>]*?value="([^"]*)"', page)}
    if not form or set(hidden) != {'lt', 'execution', '_eventId'}:
        raise flow_changed()
    if re.search(r'value="true" ref="codeOpen"', page):
        raise Error('学校要求验证码，请运行 bnul auth login 完成此次验证', 'AUTH_INTERACTION_REQUIRED')
    action = session.resolve(page_url, unescape(form.group(1)))
    if not cas_login(action):
        raise flow_changed()
    if credentials is None:
        from .credentials import get_credentials
        credentials = get_credentials()
    if not credentials:
        raise Error('登录会话已失效且未配置账号密码；请先运行 bnul auth setup，之后自动登录', 'AUTH_SETUP_REQUIRED')
    wire = urlsplit(session.wire(page_url))
    headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Origin': f'{wire.scheme}://{wire.netloc}',
               'Referer': session.wire(page_url)}
    _, _, body = session.send(CAS + '/cas/rsa', b'', headers)
    try:
        public_key = json.loads(body)['publicKey']
        ul, pl = encrypt(public_key, credentials['username']), encrypt(public_key, credentials['password'])
    except (ValueError, KeyError, TypeError):
        raise flow_changed() from None
    # Same body the official page builds, including its literal "null" captcha and raw service URL.
    service = (parse_qs(urlsplit(page_url).query).get('service') or [''])[0]
    check = urlencode({'method': 'check', 'captcha': 'null', 'ul': ul, 'pl': pl, 'random': repr(random.random())})
    _, _, body = session.send(CAS + '/cas/secondAuth', (check + ('&service=' + service if service else '')).encode(), headers)
    try:
        result = json.loads(body)
    except ValueError:
        raise flow_changed(sent=True) from None
    if not isinstance(result, dict):
        raise flow_changed(sent=True)
    if result.get('result') != 'true':
        reason = str(result.get('error') or '账号或密码错误')
        raise Error(f'学校拒绝登录：{reason}；未重复提交。密码已更改时运行 bnul auth setup 重新保存，'
                    '或运行 bnul auth login 查看官网提示', 'AUTH_REJECTED')
    if result.get('info') != 'noAuth':
        raise Error('学校要求二次认证，请运行 bnul auth login 在可见窗口完成', 'AUTH_INTERACTION_REQUIRED')
    fields = {'rsa': '', 'ul': ul, 'pl': pl, 'lt': hidden['lt'], 'execution': hidden['execution'],
              'choosenumber': '', 'device': device_id(), '_eventId': hidden['_eventId']}
    status, location, _ = session.send(action, urlencode(fields).encode(), headers)
    if status in (301, 302, 303, 307) and location:
        return location
    raise Error('学校未接受此次登录（可能需要验证码或二次认证）；' + RETRY_HINT, 'AUTH_INTERACTION_REQUIRED')


def exchange(session, token, network):
    """Trade the redirect token for the session token and its login-issued signing key."""
    from .browser_auth import login_response_session
    from .client import signed_headers
    system = Client(network=network).request('/static/public/cg/getSysSet/PC', public=True)
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'Origin': LIBRARY,
               'Referer': LIBRARY + '/jsq-v/', 'loginType': 'PC'}
    if isinstance(system, dict) and str(system.get('hmac')) == '1':
        headers.update(signed_headers(b''))  # the official page signs with the empty public key here
    url = LIBRARY + '/jsq/static/public/auth/cas/' + quote(token, safe='')
    _, _, body = session.send(url, json.dumps({'token': token, 'loginType': 'PC'}).encode(), headers)
    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    pair = login_response_session(url, payload)
    if not pair:
        message = payload.get('message') if isinstance(payload, dict) else None
        raise Error('学校登录成功但图书馆未签发会话' + (f'：{message}' if message else ''), 'AUTH_FLOW_CHANGED')
    return pair


def http_login(no_proxy=False, credentials=None, network=None):
    from .network import network_for
    network = network or network_for(no_proxy)
    try:
        return login_flow(Session(network), network, credentials)
    finally:
        network.save()  # keep WebVPN cookies the school refreshed along the way


def login_flow(session, network, credentials):
    url, submitted = ENTRY, False
    for _ in range(MAX_HOPS):
        status, location, page = session.send(url)
        if cas_login(url) and status == 200:
            if submitted:
                raise Error('学校登录页再次要求登录；' + RETRY_HINT, 'AUTH_INTERACTION_REQUIRED')
            location = submit_password(session, url, page, credentials)
            submitted = True
        if not location:
            raise flow_changed(submitted)
        url = location
        token = library_token(url)
        if token:
            session_token, key = exchange(session, token, network)
            client = Client(token=session_token, network=network)
            client.session_hmac_key = key
            client.bootstrap()
            client.api('user/getUserInfo')
            save_token(session_token, key)
            return {'saved': True, 'path': str(config_path()), 'method': 'http', 'transport': network.mode}
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc not in HOSTS:
            raise flow_changed(submitted)
    raise flow_changed(submitted)

