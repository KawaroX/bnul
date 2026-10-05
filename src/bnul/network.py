"""Per-client transports; never change routes or replay a business request."""
import http.cookiejar
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPCookieProcessor, HTTPRedirectHandler
from .client import Error, NoRedirect

VPN = 'https://webvpn.bnu.edu.cn'
LIBRARY = 'libseat.bnu.edu.cn'


def settings():
    configured = os.environ.get('BNUL_SETTINGS')
    if configured:
        path = Path(configured).expanduser()
    else:
        try:
            path = Path.home() / '.config/bnul/settings.json'
        except RuntimeError:
            return {}  # optional settings; Windows processes may deliberately clear HOME
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise Error('bnul settings.json 无法读取或不是合法 JSON', 'CONFIG_INVALID') from None
    if not isinstance(value, dict):
        raise Error('bnul settings.json 必须是 JSON 对象', 'CONFIG_INVALID')
    return value


def webvpn_profile():
    configured = os.environ.get('BNUL_WEBVPN_PROFILE') or settings().get('webvpn_profile')
    return Path(configured).expanduser() if configured else Path.home() / '.config/bnul-webvpn'


def route_host(host):
    # Public URL conversion used by the school's portal, not an authentication key.
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    try:
        from cryptography.hazmat.decrepit.ciphers.modes import CFB
    except ImportError:
        from cryptography.hazmat.primitives.ciphers.modes import CFB
    key = b'wrdvpnisthebest!'
    cipher = Cipher(algorithms.AES(key), CFB(key)).encryptor()
    return '/https/' + key.hex() + (cipher.update(host.encode()) + cipher.finalize()).hex()


def cookiejar(required=True):
    jar = http.cookiejar.MozillaCookieJar(str(webvpn_profile() / 'cookies.txt'))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, http.cookiejar.LoadError):
        if required:
            raise Error('学校 WebVPN 需要手机认证；运行 bnul --json auth webvpn 并发送返回的二维码图片。',
                        'WEBVPN_LOGIN_REQUIRED') from None
    return jar


def save_cookies(jar):
    directory = webvpn_profile()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix='.cookies-', dir=directory)
    os.close(fd)
    try:
        jar.save(tmp, ignore_discard=True, ignore_expires=True)
        os.replace(tmp, directory / 'cookies.txt')
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class WebVPNRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.netloc == 'webvpn.bnu.edu.cn' and parsed.path.startswith('/login'):
            raise Error('学校 WebVPN 会话失效；运行 bnul --json auth webvpn 获取新二维码。',
                        'WEBVPN_LOGIN_REQUIRED')
        raise Error('服务器意外重定向；未转发凭据或重新提交请求。', 'UNEXPECTED_REDIRECT')


class Network:
    def __init__(self, mode='direct', no_proxy=False):
        self.mode = mode
        self.no_proxy = no_proxy or mode == 'webvpn'
        self.cookies = cookiejar() if mode == 'webvpn' else None
        self.base = (VPN + route_host(LIBRARY) if self.cookies is not None
                     else 'https://' + LIBRARY) + '/jsq'
        self.page = self.base[:-4] + '/jsq-v/'
        handlers = [WebVPNRedirect() if self.cookies is not None else NoRedirect()]
        if no_proxy or self.cookies is not None:
            handlers.append(ProxyHandler({}))
        if self.cookies is not None:
            handlers.append(HTTPCookieProcessor(self.cookies))
        self.opener = build_opener(*handlers)

    def save(self):
        if self.cookies is not None:
            save_cookies(self.cookies)

    def session_path(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'https':
            return None
        if self.mode == 'direct':
            return parsed.path if parsed.netloc == LIBRARY else None
        prefix = route_host(LIBRARY)
        if parsed.netloc == 'webvpn.bnu.edu.cn' and parsed.path.startswith(prefix + '/'):
            return parsed.path[len(prefix):]
        return None

    def cas_login(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'https':
            return False
        path = parsed.path.split(';', 1)[0]
        return ((parsed.netloc == 'cas.bnu.edu.cn' and path == '/cas/login') or
                (self.mode == 'webvpn' and parsed.netloc == 'webvpn.bnu.edu.cn'
                 and path == route_host('cas.bnu.edu.cn') + '/cas/login'))

    def browser_cookies(self):
        result = []
        for cookie in self.cookies or []:
            if cookie.domain.lstrip('.') != 'webvpn.bnu.edu.cn':
                continue
            value = {'name': cookie.name, 'value': cookie.value, 'domain': cookie.domain,
                     'path': cookie.path, 'secure': cookie.secure,
                     'httpOnly': cookie.has_nonstandard_attr('HttpOnly')}
            if cookie.expires:
                value['expires'] = cookie.expires
            result.append(value)
        return result


def network_for(no_proxy=False, mode=None):
    mode = mode or os.environ.get('BNUL_TRANSPORT') or settings().get('transport', 'direct')
    if mode not in ('direct', 'webvpn', 'auto'):
        raise Error('transport 必须为 direct、webvpn 或 auto', 'CONFIG_INVALID')
    if mode == 'auto':
        # Select a transport before any token or business request is sent.
        opener = build_opener(NoRedirect(), ProxyHandler({}))
        req = Request('https://libseat.bnu.edu.cn/jsq/static/public/cg/getSysSet/PC',
                      b'{}', {'Content-Type': 'application/json'})
        try:
            with opener.open(req, timeout=6) as response:
                value = json.load(response)
            mode = 'direct' if isinstance(value, dict) and value.get('status') is True else 'webvpn'
        except (OSError, ValueError, Error):
            mode = 'webvpn'
        no_proxy = True
    return Network(mode, no_proxy)
