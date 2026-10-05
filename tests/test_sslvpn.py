import os
import unittest
from unittest.mock import Mock, patch
from bnul.sslvpn import configure_routes, run_vpn


class SSLVPNTests(unittest.TestCase):
    def test_only_school_host_routes_are_configured(self):
        env = {'reason': 'connect', 'TUNDEV': 'bnuvpn0', 'INTERNAL_IP4_ADDRESS': '10.0.0.4'}
        addresses = [('libseat.bnu.edu.cn', '219.224.31.128'), ('cas.bnu.edu.cn', '114.255.219.19')]
        def resolve(host, *args):
            return [(None, None, None, None, (dict(addresses)[host], 443))]
        with patch.dict(os.environ, env, clear=True), patch('bnul.sslvpn.sys.platform', 'linux'), \
             patch('bnul.sslvpn.shutil.which', return_value='/sbin/ip'), \
             patch('bnul.sslvpn.socket.getaddrinfo', side_effect=resolve), patch('bnul.sslvpn.subprocess.run') as run:
            configure_routes()
        commands = [call.args[0] for call in run.call_args_list]
        routes = [cmd for cmd in commands if 'route' in cmd]
        self.assertEqual({cmd[3] for cmd in routes}, {'219.224.31.128/32', '114.255.219.19/32'})
        self.assertFalse(any('default' in cmd for cmd in commands))

    def test_auth_rejection_stops_and_password_is_only_stdin(self):
        process = Mock()
        process.communicate.return_value = (None, 'Invalid username or password')
        process.returncode = 1
        with patch.dict(os.environ, {}, clear=True), patch('bnul.sslvpn.sys.platform', 'linux'), \
             patch('bnul.sslvpn.shutil.which', return_value='/sbin/openconnect'), \
             patch('bnul.credentials.get_credentials', return_value={'username': 'student', 'password': 'secret-password'}), \
             patch('bnul.sslvpn.subprocess.Popen', return_value=process) as spawn:
            with self.assertRaises(SystemExit) as caught:
                run_vpn()
        self.assertEqual(caught.exception.code, 78)
        self.assertNotIn('secret-password', ' '.join(spawn.call_args.args[0]))
        self.assertNotIn('BNUL_PASSWORD', spawn.call_args.kwargs['env'])
        process.communicate.assert_called_once_with('secret-password\n')


if __name__ == '__main__':
    unittest.main()
