import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from bnul.client import Client, Error
from bnul.browser_auth import session_request_token, browser_options
from bnul.network import Network, network_for, route_host, WebVPNRedirect
from bnul.cli import main


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {'BNUL_SETTINGS': self.directory.name + '/settings.json',
                                         'BNUL_WEBVPN_PROFILE': self.directory.name + '/webvpn'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_default_direct_never_probes_network(self):
        with patch('bnul.network.build_opener') as build:
            network = network_for()
            build.return_value.open.assert_not_called()
        self.assertEqual(network.mode, 'direct')

    def test_auto_probe_carries_no_credentials_and_prefers_direct(self):
        with patch('bnul.network.build_opener') as build:
            build.return_value.open.return_value = io.BytesIO(b'{"status":true}')
            network = network_for(mode='auto')
            request = build.return_value.open.call_args.args[0]
        self.assertEqual(network.mode, 'direct')
        self.assertIsNone(request.get_header('Token'))
        self.assertIsNone(request.get_header('Cookie'))

    def test_blocked_auto_requires_official_webvpn_login(self):
        with patch('bnul.network.build_opener') as build:
            build.return_value.open.side_effect = HTTPError('https://libseat.bnu.edu.cn', 483, '', {}, None)
            with self.assertRaises(Error) as caught:
                network_for(mode='auto')
        self.assertEqual(caught.exception.code, 'WEBVPN_LOGIN_REQUIRED')

    def test_request_after_selection_does_not_switch_or_replay_write(self):
        client = Client('explicit', no_proxy=True)
        with patch.object(client.opener, 'open', side_effect=HTTPError(client.network.base, 483, '', {}, None)) as opened:
            with patch('bnul.network.network_for') as selector:
                with self.assertRaises(Error):
                    client.api('make/stop')
                selector.assert_not_called()
                opened.assert_called_once()

    def test_url_conversion_matches_school_portal(self):
        self.assertEqual(route_host('libseat.bnu.edu.cn'),
                         '/https/77726476706e69737468656265737421fcfe438f22317c1e7c069ce29d51367b7c4f')

    def test_webvpn_only_accepts_exact_library_request_tokens(self):
        with patch('bnul.network.cookiejar', return_value=[]):
            network = Network('webvpn')
        path = '/jsq/static/frontApi/user/getUserInfo'
        good = 'https://webvpn.bnu.edu.cn' + route_host('libseat.bnu.edu.cn') + path
        self.assertEqual(session_request_token(good, {'token': 'fresh'}, network), 'fresh')
        for url in [good.replace('webvpn.bnu.edu.cn', 'evil.example'),
                    good.replace('https:', 'http:'),
                    'https://webvpn.bnu.edu.cn' + route_host('evil.example') + path,
                    good.replace('/frontApi/', '/public/')]:
            self.assertIsNone(session_request_token(url, {'token': 'fresh'}, network))

    def test_proxied_cas_requires_exact_authenticated_resource(self):
        with patch('bnul.network.cookiejar', return_value=[]):
            network = Network('webvpn')
        good = 'https://webvpn.bnu.edu.cn' + route_host('cas.bnu.edu.cn') + '/cas/login'
        self.assertTrue(network.cas_login(good))
        self.assertFalse(network.cas_login(good.replace('webvpn.bnu.edu.cn', 'evil.example')))
        self.assertFalse(network.cas_login(good.replace('/cas/login', '/cas/login-evil')))

    def test_auth_redirect_is_explicit_and_does_not_forward(self):
        with self.assertRaises(Error) as caught:
            WebVPNRedirect().redirect_request(None, None, 302, '', {}, 'https://webvpn.bnu.edu.cn/login')
        self.assertEqual(caught.exception.code, 'WEBVPN_LOGIN_REQUIRED')
        with self.assertRaises(Error) as caught:
            WebVPNRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example/login')
        self.assertEqual(caught.exception.code, 'UNEXPECTED_REDIRECT')

    def test_configured_executable_and_transport_flag_are_scoped(self):
        executable = Path(self.directory.name) / 'chrome'
        executable.touch()
        with patch.dict(os.environ, {'BNUL_BROWSER_EXECUTABLE': str(executable)}):
            self.assertEqual(browser_options(), {'executable_path': str(executable)})
        with patch('bnul.webvpn.read_status', return_value={'status': 'authenticated'}), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(main(['--transport', 'auto', '--json', 'auth', 'webvpn', '--status']), 0)
        self.assertNotIn('BNUL_TRANSPORT', os.environ)


if __name__ == '__main__':
    unittest.main()
