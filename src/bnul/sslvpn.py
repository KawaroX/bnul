"""Opt-in Linux OpenConnect service; route only library and school CAS traffic."""
import ipaddress
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path
from .client import Error

HOSTS = ('libseat.bnu.edu.cn', 'cas.bnu.edu.cn')


def interface():
    value = os.environ.get('BNUL_VPN_INTERFACE', 'bnuvpn0')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,15}', value):
        raise Error('BNUL_VPN_INTERFACE 不是合法网络接口名', 'CONFIG_INVALID')
    return value


def configure_routes():
    if sys.platform != 'linux':
        raise Error('SSL VPN 路由服务仅支持 Linux', 'PLATFORM_UNSUPPORTED')
    device = interface()
    if os.environ.get('TUNDEV', device) != device:
        raise Error('OpenConnect 网络接口与配置不一致', 'CONFIG_INVALID')
    ip = shutil.which('ip')
    if not ip:
        raise Error('请安装 iproute2', 'VPN_DEPENDENCY_MISSING')
    def call(*args, check=True):
        return subprocess.run([ip, *args], check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    reason = os.environ.get('reason')
    if reason in ('connect', 'reconnect'):
        address = str(ipaddress.IPv4Address(os.environ['INTERNAL_IP4_ADDRESS']))
        mtu = max(576, min(1500, int(os.environ.get('INTERNAL_IP4_MTU') or 1400)))
        call('link', 'set', 'dev', device, 'mtu', str(mtu), 'up')
        call('addr', 'replace', address + '/32', 'dev', device)
        for host in HOSTS:
            for addr in sorted({x[4][0] for x in socket.getaddrinfo(host, 443, socket.AF_INET)}):
                call('route', 'replace', str(ipaddress.IPv4Address(addr)) + '/32',
                     'dev', device, 'metric', '5')
    elif reason == 'disconnect':
        call('route', 'flush', 'dev', device, check=False)
    return {'configured': reason, 'interface': device}


def run_vpn():
    if sys.platform != 'linux':
        raise Error('SSL VPN 服务仅支持 Linux', 'PLATFORM_UNSUPPORTED')
    executable = shutil.which('openconnect')
    if not executable:
        raise Error('请先安装 openconnect；学校 SSL VPN 需另行申请开通', 'VPN_DEPENDENCY_MISSING')
    # An explicit administrator-selected existing dotenv file is optional. No credentials are written.
    if os.environ.get('BNUL_CREDENTIAL_ENV'):
        from dotenv import dotenv_values
        values = dotenv_values(Path(os.environ['BNUL_CREDENTIAL_ENV']).expanduser())
        for key in ('BNUL_USERNAME', 'BNUL_PASSWORD'):
            if key not in os.environ and values.get(key):
                os.environ[key] = values[key]
    from .credentials import get_credentials
    credentials = get_credentials()
    if not credentials:
        print('School VPN credentials are missing.', file=sys.stderr)
        raise SystemExit(78)
    username, password = credentials['username'], credentials['password']
    command = [executable, '--protocol=pulse', '--non-inter', '--passwd-on-stdin',
               '--no-proxy', '--no-dtls', '--user', username, '--authgroup', 'LDAP-User',
               '--interface', interface(), '--script',
               shlex.join([sys.executable, '-m', 'bnul', 'vpn', 'route']),
               '--reconnect-timeout', '60', 'https://sslvpn.bnu.edu.cn/']
    environment = {k: v for k, v in os.environ.items() if k not in ('BNUL_USERNAME', 'BNUL_PASSWORD')}
    print('Connecting school VPN; only library and CAS host routes are configured.', file=sys.stderr, flush=True)
    process = subprocess.Popen(command, env=environment, stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    def stop(signum, frame):
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
    old = signal.signal(signal.SIGTERM, stop)
    try:
        _, error = process.communicate(password + '\n')
    finally:
        signal.signal(signal.SIGTERM, old)
    clean = error.replace(username, '[account]').replace(password, '[redacted]')
    if os.environ.get('BNUL_VPN_LOG'):
        path = Path(os.environ['BNUL_VPN_LOG']).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(clean)
    if any(term in clean.lower() for term in ('invalid username or password', 'authentication failed', 'login failed')):
        print('School rejected authentication; stopped to avoid repeated password attempts.', file=sys.stderr)
        raise SystemExit(78)
    return {'connected': False, 'exitCode': process.returncode, 'reconnect': 'systemd'}
