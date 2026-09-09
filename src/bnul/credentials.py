"""Native credential stores or explicit environment injection; never plaintext JSON."""
import json
import sys
import os
import importlib
from .client import Error

SERVICE = 'cn.edu.bnu.bnul.cas'
ACCOUNT = 'default'


def backend_spec(platform):
    if platform == 'darwin':
        return 'keyring.backends.macOS', 'Keyring'
    if platform == 'win32':
        return 'keyring.backends.Windows', 'WinVaultKeyring'
    if platform.startswith('linux'):
        return 'keyring.backends.SecretService', 'Keyring'
    raise Error('此平台未配置系统凭据存储，可通过 BNUL_USERNAME/BNUL_PASSWORD 注入凭据', 'CREDENTIALS_UNAVAILABLE')


def backend():
    module, name = backend_spec(sys.platform)
    try:
        return getattr(importlib.import_module(module), name)()
    except ImportError:
        raise Error('请安装登录依赖：python -m pip install -e ".[browser]"；Linux 还需可用的 Secret Service', 'CREDENTIALS_UNAVAILABLE') from None


def get_credentials():
    username, password = os.environ.get('BNUL_USERNAME'), os.environ.get('BNUL_PASSWORD')
    if username is not None or password is not None:
        if not username or not password:
            raise Error('BNUL_USERNAME 与 BNUL_PASSWORD 必须同时提供非空值', 'CREDENTIALS_UNAVAILABLE')
        return {'username': username, 'password': password}
    try:
        raw = backend().get_password(SERVICE, ACCOUNT)
        if raw is None:
            return None
        data = json.loads(raw)
        if not isinstance(data.get('username'), str) or not isinstance(data.get('password'), str):
            raise ValueError()
        return data
    except Error:
        raise
    except Exception:
        raise Error('无法读取系统凭据；Linux 请确认 Secret Service 与会话 D-Bus 已启动并解锁，或注入 BNUL_USERNAME/BNUL_PASSWORD', 'CREDENTIALS_UNAVAILABLE') from None


def store_credentials(username, password):
    if not username.strip() or not password:
        raise Error('账号和密码不能为空')
    try:
        backend().set_password(SERVICE, ACCOUNT, json.dumps({'username': username.strip(), 'password': password}))
    except Error:
        raise
    except Exception:
        raise Error('无法将登录凭据保存到 系统凭据存储', 'CREDENTIALS_UNAVAILABLE') from None


def forget_credentials():
    try:
        keychain = backend()
        if keychain.get_password(SERVICE, ACCOUNT) is not None:
            keychain.delete_password(SERVICE, ACCOUNT)
    except Error:
        raise
    except Exception:
        raise Error('无法删除系统凭据', 'CREDENTIALS_UNAVAILABLE') from None
