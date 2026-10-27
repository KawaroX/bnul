"""Native credential stores, explicit environment injection, or an opted-in private env file."""
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


def credential_file():
    from .client import config_path
    return config_path().parent / 'credentials.env'


def quoted(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def store_credentials_file(username, password):
    """Plaintext fallback, written only after the user confirms; readable by the owner alone."""
    username = username.strip()
    if not username or not password:
        raise Error('账号和密码不能为空')
    if any(c in value for value in (username, password) for c in '\r\n'):
        raise Error('账号或密码包含换行，无法保存到凭据文件')
    import tempfile
    path = credential_file()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.credentials-')  # created 0600
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(f'BNUL_USERNAME={quoted(username)}\nBNUL_PASSWORD={quoted(password)}\n')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return path


def file_credentials():
    path = credential_file()
    if not path.is_file():
        return None
    from dotenv import dotenv_values
    with path.open(encoding='utf-8') as stream:
        values = dotenv_values(stream=stream, interpolate=False)
    if not values.get('BNUL_USERNAME') or not values.get('BNUL_PASSWORD'):
        raise Error(f'凭据文件 {path} 不完整，请重新运行 bnul auth setup', 'CREDENTIALS_UNAVAILABLE')
    return {'username': values['BNUL_USERNAME'], 'password': values['BNUL_PASSWORD']}


def get_credentials():
    # Read only the two requested keys from an explicitly selected existing dotenv file.
    from .env import env_value as setting
    username, password = setting('BNUL_USERNAME'), setting('BNUL_PASSWORD')
    if username is not None or password is not None:
        if not username or not password:
            raise Error('BNUL_USERNAME 与 BNUL_PASSWORD 必须同时提供非空值', 'CREDENTIALS_UNAVAILABLE')
        return {'username': username, 'password': password}
    # The file exists only because setup could not use the keyring, so it is checked first.
    found = file_credentials()
    if found:
        return found
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
    # A stale fallback file would otherwise shadow the keyring entry.
    credential_file().unlink(missing_ok=True)


def credential_source():
    """Where automatic login would read credentials from; never returns the values."""
    from .env import env_value as setting
    try:
        found = get_credentials()
    except Error as exc:
        return '不可用：' + str(exc)
    if not found:
        return None
    if setting('BNUL_USERNAME') is not None:
        return '环境变量'
    return f'凭据文件 {credential_file()}' if credential_file().is_file() else '系统凭据库'


def forget_credentials():
    try:
        keychain = backend()
        if keychain.get_password(SERVICE, ACCOUNT) is None:
            return False
        keychain.delete_password(SERVICE, ACCOUNT)
        return True
    except Error:
        raise
    except Exception:
        raise Error('无法删除系统凭据', 'CREDENTIALS_UNAVAILABLE') from None
