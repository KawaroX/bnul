"""Capture a session issued by the official site in a dedicated browser profile."""
import os
import sys
import time
from urllib.parse import urlparse
from .client import Client, Error, config_path, save_token


def session_request_token(url, headers):
    parsed = urlparse(url)
    if (parsed.scheme == 'https' and parsed.netloc == 'libseat.bnu.edu.cn'
            and parsed.path.startswith('/jsq/static/frontApi/')):
        value = headers.get('token')
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def submit_credentials(page, credentials):
    # Exact origin and observed form selectors; never type secrets on another site.
    parsed = urlparse(page.url)
    if parsed.scheme != 'https' or parsed.netloc != 'cas.bnu.edu.cn' or parsed.path.split(';', 1)[0] != '/cas/login':
        return False
    username = page.locator('#loginForm .username input')
    password = page.locator('#loginForm #password-input')
    if not username.is_visible() or not password.is_visible():
        return False
    if page.locator('#loginForm input[name="code"]').is_visible():
        raise Error('学校要求验证码，请运行 bnul auth login 完成此次验证', 'AUTH_INTERACTION_REQUIRED')
    username.fill(credentials['username'])
    password.fill(credentials['password'])
    page.locator('#loginForm .login-btn').click()
    return True


def browser_options():
    selected = os.environ.get('BNUL_BROWSER', 'chromium')
    if selected not in ('chrome', 'msedge', 'chromium'):
        raise Error('BNUL_BROWSER 必须是 chrome、msedge 或 chromium')
    return {} if selected == 'chromium' else {'channel': selected}


def browser_login(no_proxy=False, timeout=300, headless=False, credentials=None):
    try:
        from playwright.sync_api import sync_playwright, Error as BrowserError
    except ImportError:
        raise Error('请先安装浏览器支持：python -m pip install -e ".[browser]"') from None
    profile = config_path().parent / 'browser-profile'
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(profile, 0o700)
    pending = []
    submitted = False
    lookup_done = credentials is not None
    seen = set()
    def capture(request):
        token = session_request_token(request.url, request.headers)
        if token and token not in seen:
            seen.add(token)
            pending.append(token)
    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(profile), **browser_options(), headless=headless,
                args=['--no-proxy-server'] if no_proxy else [])
            try:
                context.on('request', capture)
                page = context.pages[0] if context.pages else context.new_page()
                if not headless:
                    print('请在打开的专用浏览器 窗口完成官网登录；会话会自动保存，无需复制链接。', file=sys.stderr)
                page.goto('https://libseat.bnu.edu.cn/jsq-v/', wait_until='domcontentloaded', timeout=60000)
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if pending:
                        token = pending.pop(0)
                        client = Client(token=token, no_proxy=no_proxy)
                        client.bootstrap()
                        try:
                            client.api('user/getUserInfo')
                        except Error as exc:
                            if str(exc.code) in ('20003', '401', '403'):
                                continue
                            raise
                        save_token(token)
                        return {'saved': True, 'path': str(config_path()), 'method': 'background' if headless else 'browser'}
                    if page.is_closed():
                        pages = context.pages
                        if not pages:
                            raise Error('登录窗口已关闭，未保存新会话')
                        page = pages[0]
                    parsed = urlparse(page.url)
                    if parsed.netloc == 'cas.bnu.edu.cn' and parsed.scheme == 'https':
                        if not lookup_done:
                            from .credentials import get_credentials
                            credentials = get_credentials()
                            lookup_done = True
                        if credentials and not submitted:
                            try:
                                submitted = submit_credentials(page, credentials)
                            except Error:
                                if headless:
                                    raise
                                submitted = True  # visible window: user handles the challenge
                        elif headless and not credentials and page.locator('#loginForm #password-input').is_visible():
                            raise Error('学校登录状态已失效且未配置账号密码；请先运行 bnul auth setup，之后自动登录', 'AUTH_SETUP_REQUIRED')
                    page.wait_for_timeout(250)
                raise Error('自动登录未完成（可能需验证码、二次认证或账号密码校验失败）；未重复提交密码。请运行 bnul auth login 查看官网提示', 'AUTH_INTERACTION_REQUIRED')
            finally:
                context.close()
    except BrowserError:
        raise Error('浏览器登录未完成。请检查浏览器安装、Linux 运行依赖/显示环境或资料目录占用。Chromium 安装：python -m playwright install chromium；可设置 BNUL_BROWSER=chrome/msedge') from None
