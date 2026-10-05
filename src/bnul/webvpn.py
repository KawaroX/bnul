"""Official QR authentication; detached workers never submit library operations."""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, ProxyHandler, HTTPCookieProcessor
from .client import Error
from .network import VPN, cookiejar, save_cookies, settings, webvpn_profile


def qr_directory():
    default = Path(os.environ.get('HERMES_HOME', str(Path.home() / '.hermes'))) / 'image_cache/bnu-webvpn'
    return Path(os.environ.get('BNUL_QR_DIR', settings().get('qr_directory', str(default)))).expanduser()


def read_status():
    try:
        data = json.loads((webvpn_profile() / 'login-status.json').read_text())
    except FileNotFoundError:
        return {'status': 'not_started'}
    except (OSError, ValueError):
        raise Error('WebVPN 状态文件无法读取', 'WEBVPN_STATUS_INVALID') from None
    if not isinstance(data, dict):
        raise Error('WebVPN 状态文件格式异常', 'WEBVPN_STATUS_INVALID')
    return data


def write_status(attempt, **data):
    directory = webvpn_profile()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    data.update(attempt=attempt, updated_at=time.time())
    fd, tmp = tempfile.mkstemp(prefix='.status-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, ensure_ascii=False)
        os.replace(tmp, directory / 'login-status.json')
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def current_attempt(attempt):
    return read_status().get('attempt') == attempt


def authenticated_location(url):
    parsed = urlsplit(url)
    return parsed.scheme == 'https' and parsed.netloc == 'webvpn.bnu.edu.cn' and parsed.path == '/'


def worker(attempt):
    jar = cookiejar(required=False)
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar))
    with opener.open(VPN + '/', timeout=15) as response:
        response.read()
        if authenticated_location(response.geturl()):
            if current_attempt(attempt):
                save_cookies(jar)
                write_status(attempt, status='already_authenticated')
            return
    query = urlencode({'appid': '17', 'scope': 'snsapi_login', 'redirect_uri': VPN + '/login?wechat_login=true',
                       'state': 'STATE', 'login_type': 'jssdk', 'style': 'white'})
    with opener.open('https://weixin.bnu.edu.cn/scan/qrconnect.php?' + query, timeout=15) as response:
        page = response.read().decode()
    match = re.search(r'qr_code.php\?uuid=([A-Za-z0-9_-]+)', page)
    if not match:
        raise Error('学校二维码页面格式已变化', 'WEBVPN_QR_INVALID')
    qr_id = match.group(1)
    directory = qr_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    qr = directory / ('login-' + attempt + '.png')
    with opener.open('https://weixin.bnu.edu.cn/scan/qr_code.php?' +
                     urlencode({'uuid': qr_id, 'appid': '17'}), timeout=15) as response:
        image = response.read()
    if not image.startswith(b'\x89PNG\r\n\x1a\n'):
        raise Error('学校未返回 PNG 二维码图片', 'WEBVPN_QR_INVALID')
    fd = os.open(str(qr), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(image)
    if not current_attempt(attempt):
        qr.unlink(missing_ok=True)
        return
    write_status(attempt, status='scan_required', qr_path=str(qr.resolve()), media='MEDIA:' + str(qr.resolve()),
                 instruction='在当前用户聊天发送 media 原生图片；扫码后用 bnul --json auth webvpn --status 确认。')
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline and current_attempt(attempt):
        try:
            with opener.open('https://weixin.bnu.edu.cn/scan/connect.php?' +
                             urlencode({'uuid': qr_id, '_': str(time.time())}), timeout=65) as response:
                result = response.read().decode()
            match = re.search(r'wx_errcode\s*=\s*(\d+)', result)
            code = int(match.group(1)) if match else 0
            if code == 405:
                match = re.search(r'wx_code\s*=\s*["\x27]([^"\x27]+)', result)
                if not match:
                    raise Error('学校扫码确认响应格式已变化', 'WEBVPN_QR_INVALID')
                callback = urlencode({'wechat_login': 'true', 'uuid': qr_id,
                                      'code': match.group(1), 'state': 'login'})
                with opener.open(VPN + '/login?' + callback, timeout=20) as response:
                    response.read()
                    accepted = authenticated_location(response.geturl())
                if not accepted:
                    raise Error('学校尚未接受此次扫码认证', 'WEBVPN_LOGIN_REQUIRED')
                if current_attempt(attempt):
                    save_cookies(jar)
                    write_status(attempt, status='authenticated')
                return
            if code == 402:
                break
        except OSError:
            pass
        time.sleep(2)
    if current_attempt(attempt):
        write_status(attempt, status='qr_expired')


def start_login(refresh=False):
    previous = read_status()
    if not refresh and previous.get('status') in ('starting', 'scan_required'):
        age = time.time() - previous.get('updated_at', 0)
        if age < (30 if previous['status'] == 'starting' else 180):
            return previous
    directory = webvpn_profile()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    attempt = uuid.uuid4().hex
    write_status(attempt, status='starting')
    fd = os.open(str(directory / 'login-worker.log'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a') as log:
        subprocess.Popen([sys.executable, '-m', 'bnul.webvpn', '--worker', attempt],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    for _ in range(40):
        value = read_status()
        if value.get('status') != 'starting':
            return value
        time.sleep(.5)
    return read_status()


def main(argv=None):
    parser = argparse.ArgumentParser(description='北师大学校官方 WebVPN 手机扫码认证')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--status', action='store_true')
    group.add_argument('--refresh', action='store_true')
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        try:
            worker(args.worker)
        except Exception as exc:
            if current_attempt(args.worker):
                write_status(args.worker, status='failed', error=type(exc).__name__)
        return 0
    try:
        data = read_status() if args.status else start_login(args.refresh)
        print(json.dumps(data, ensure_ascii=False))
        return 1 if data.get('status') == 'failed' else 0
    except (Error, OSError):
        print(json.dumps({'status': 'failed', 'error': 'WebVPN 登录助手无法启动'}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
