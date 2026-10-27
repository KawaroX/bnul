import base64
import json
import os
import stat
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urljoin

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from bnul.client import Error
from bnul import http_auth
from bnul.network import Network, route_host

KEY = rsa.generate_private_key(public_exponent=65537, key_size=1024)
PUBLIC = base64.b64encode(KEY.public_key().public_bytes(
    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
SERVICE = 'https://libseat.bnu.edu.cn/rem/static/sso/webOAuthRed'
CAS_URL = 'https://cas.bnu.edu.cn/cas/login?service=https%3A%2F%2Flibseat.bnu.edu.cn%2Frem%2Fstatic%2Fsso%2FwebOAuthRed'
CREDS = {'username': 'student', 'password': 'pass"word'}


def cas_page(captcha='false', action='/cas/login;jsessionid=ABC?service=https%3A%2F%2Flibseat.bnu.edu.cn%2Frem%2Fstatic%2Fsso%2FwebOAuthRed'):
    return f'''<form id="loginForm" action="{action}" method="post" onsubmit="return false;">
<input id="password-input" :type="secretType" v-model="userSecret"/>
<input type="hidden" id="rsa" name="rsa" v-model="rsa"/>
<input type="hidden" name="lt" id="lt" value="LT-1-abc&amp;def"/>
<input type="hidden" name="execution" value="e1s1"/>
<input type="hidden" name="_eventId" value="submit"/>
<input type="hidden" value="{captcha}" ref="codeOpen"/></form>'''


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def wire(self, url):
        return url

    def resolve(self, base, ref):
        return urljoin(base, ref)

    def send(self, url, data=None, headers=None):
        self.calls.append((url, data))
        for prefix, response in self.routes:
            if url.startswith(prefix):
                return response(url, data) if callable(response) else response
        raise AssertionError('unexpected request ' + url)


def decrypt(value):
    return KEY.decrypt(base64.b64decode(value), padding.PKCS1v15()).decode()


def routes(check=None, submit=None, page=None, entry=None):
    return [
        (http_auth.ENTRY, entry or (302, CAS_URL, '')),
        ('https://cas.bnu.edu.cn/cas/login;', submit or (302, SERVICE + '?ticket=ST-1', '')),
        ('https://cas.bnu.edu.cn/cas/login', (200, None, page or cas_page())),
        ('https://cas.bnu.edu.cn/cas/rsa', (200, None, json.dumps({'publicKey': PUBLIC}))),
        ('https://cas.bnu.edu.cn/cas/secondAuth', (200, None, json.dumps(check or {'result': 'true', 'info': 'noAuth'}))),
        (SERVICE, (302, 'https://libseat.bnu.edu.cn/jsq-v?token=redirect-token', '')),
    ]


class HttpLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {'BNUL_CONFIG': self.tmp.name + '/session.json'})
        env.start()
        self.addCleanup(env.stop)
        self.network = Network('direct', no_proxy=True)

    def login(self, fake, credentials=CREDS):
        with patch('bnul.http_auth.Session', return_value=fake), \
                patch('bnul.http_auth.exchange', return_value=('session-token', 'login-key')) as exchange, \
                patch('bnul.http_auth.Client') as client, patch('bnul.http_auth.save_token') as save:
            result = http_auth.http_login(credentials=credentials, network=self.network)
        return result, exchange, client, save

    def test_full_flow_saves_verified_session(self):
        fake = FakeSession(routes())
        result, exchange, client, save = self.login(fake)
        self.assertEqual(result['method'], 'http')
        self.assertEqual(exchange.call_args.args[1], 'redirect-token')
        self.assertEqual(client.return_value.session_hmac_key, 'login-key')
        client.return_value.api.assert_called_once_with('user/getUserInfo')
        save.assert_called_once_with('session-token', 'login-key')
        check = parse_qs(fake.calls[3][1].decode())
        self.assertEqual((check['method'], check['captcha'], check['service']), (['check'], ['null'], [SERVICE]))
        self.assertEqual((decrypt(check['ul'][0]), decrypt(check['pl'][0])), ('student', 'pass"word'))
        url, body = fake.calls[4]
        self.assertTrue(url.startswith('https://cas.bnu.edu.cn/cas/login;jsessionid=ABC?service='))
        form = parse_qs(body.decode(), keep_blank_values=True)
        self.assertEqual((form['lt'], form['execution'], form['_eventId']), (['LT-1-abc&def'], ['e1s1'], ['submit']))
        self.assertRegex(form['device'][0], r'^[0-9a-f]{32}$')
        # Secrets only ever travel encrypted, and only to the CAS host.
        for url, body in fake.calls:
            self.assertNotIn(b'pass', body or b'')
            if body:
                self.assertTrue(url.startswith('https://cas.bnu.edu.cn/'))

    def test_device_id_is_stable_and_private(self):
        first = http_auth.device_id()
        self.assertEqual(http_auth.device_id(), first)
        path = os.path.join(self.tmp.name, 'device-id')
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def assert_stops(self, fake, code, posted_form=False):
        with self.assertRaises(Error) as err:
            self.login(fake)
        self.assertEqual(err.exception.code, code)
        submitted = [url for url, body in fake.calls if body and url.startswith('https://cas.bnu.edu.cn/cas/login')]
        self.assertEqual(len(submitted), 1 if posted_form else 0)
        return fake

    def test_captcha_stops_before_credentials(self):
        fake = self.assert_stops(FakeSession(routes(page=cas_page('true'))), 'AUTH_INTERACTION_REQUIRED')
        self.assertEqual(len(fake.calls), 2)

    def test_rejected_password_is_not_resubmitted(self):
        fake = self.assert_stops(FakeSession(routes(check={'result': 'false', 'error': '用户名或密码错误', 'failureTimes': True})),
                                 'AUTH_REJECTED')
        self.assertEqual(sum(url.endswith('/secondAuth') for url, _ in fake.calls), 1)

    def test_second_factor_requires_visible_login(self):
        self.assert_stops(FakeSession(routes(check={'result': 'true', 'info': 'mobile'})), 'AUTH_INTERACTION_REQUIRED')

    def test_unaccepted_form_is_not_resubmitted(self):
        self.assert_stops(FakeSession(routes(submit=(200, None, cas_page()))), 'AUTH_INTERACTION_REQUIRED', posted_form=True)

    def test_second_login_page_after_submit_stops(self):
        fake = FakeSession(routes(submit=(302, CAS_URL, '')))
        self.assert_stops(fake, 'AUTH_INTERACTION_REQUIRED', posted_form=True)

    def test_unexpected_redirect_stops_before_credentials(self):
        fake = self.assert_stops(FakeSession(routes(entry=(302, 'https://evil.example/cas/login', ''))), 'AUTH_FLOW_CHANGED')
        self.assertEqual(len(fake.calls), 1)

    def test_foreign_form_action_is_refused(self):
        fake = FakeSession(routes(page=cas_page(action='https://evil.example/cas/login')))
        self.assert_stops(fake, 'AUTH_FLOW_CHANGED')
        self.assertFalse(any('rsa' in url for url, _ in fake.calls))

    def test_missing_credentials_need_setup(self):
        fake = FakeSession(routes())
        with patch('bnul.credentials.get_credentials', return_value=None), self.assertRaises(Error) as err:
            self.login(fake, credentials=None)
        self.assertEqual(err.exception.code, 'AUTH_SETUP_REQUIRED')
        self.assertEqual(len(fake.calls), 2)

    def test_library_token_only_from_official_page(self):
        self.assertEqual(http_auth.library_token('https://libseat.bnu.edu.cn/jsq-v?token=abc'), 'abc')
        self.assertEqual(http_auth.library_token('https://libseat.bnu.edu.cn/jsq-v/#/?token=abc'), 'abc')
        for url in ('http://libseat.bnu.edu.cn/jsq-v?token=abc', 'https://evil.example/jsq-v?token=abc',
                    'https://libseat.bnu.edu.cn/jsq-v?token='):
            self.assertIsNone(http_auth.library_token(url))

    def test_exchange_signs_like_official_page_and_requires_key(self):
        fake = FakeSession([('https://libseat.bnu.edu.cn/jsq/static/public/auth/cas/redirect-token',
                             (200, None, json.dumps({'status': True, 'data': {'token': 'fresh', 'userInfoRes': {'hmacKey': 'k'}}})))])
        with patch('bnul.http_auth.Client') as client:
            client.return_value.request.return_value = {'hmac': 1}
            self.assertEqual(http_auth.exchange(fake, 'redirect-token', self.network), ('fresh', 'k'))
        fake.routes = [(fake.routes[0][0], (200, None, json.dumps({'status': True, 'data': {'token': 'fresh', 'userInfoRes': {}}})))]
        with patch('bnul.http_auth.Client') as client, self.assertRaises(Error) as err:
            client.return_value.request.return_value = {'hmac': 1}
            http_auth.exchange(fake, 'redirect-token', self.network)
        self.assertEqual(err.exception.code, 'AUTH_FLOW_CHANGED')

    def test_recovery_uses_http_login_on_the_client_transport(self):
        from bnul.client import Client
        c = Client(network=self.network)
        with patch('bnul.http_auth.http_login') as login, patch('bnul.client.load_token', return_value='t'), \
                patch.object(c, 'bootstrap'), patch('sys.stderr'):
            c.recover_auth()
        login.assert_called_once_with(network=self.network)


def webvpn():
    network = Network.__new__(Network)
    network.mode, network.no_proxy, network.cookies = 'webvpn', True, None
    return network


class WebVPNMappingTests(unittest.TestCase):
    def test_official_urls_round_trip_through_webvpn(self):
        network = webvpn()
        url = 'https://cas.bnu.edu.cn/cas/login;jsessionid=A?service=' + SERVICE
        wire = network.wire(url)
        self.assertTrue(wire.startswith('https://webvpn.bnu.edu.cn' + route_host('cas.bnu.edu.cn') + '/cas/login;jsessionid=A?'))
        self.assertEqual(network.official(wire), url)
        self.assertEqual(Network('direct').wire(url), url)
        for other in ('https://webvpn.bnu.edu.cn/login', 'https://webvpn.bnu.edu.cn' + route_host('evil.example') + '/x'):
            self.assertEqual(network.official(other), other)

    def test_session_maps_redirects_and_detects_expired_webvpn(self):
        network = webvpn()
        session = http_auth.Session(network)
        page = 'https://cas.bnu.edu.cn/cas/login?service=' + SERVICE
        relative = route_host('cas.bnu.edu.cn') + '/cas/login;jsessionid=A?service=x'
        self.assertEqual(session.resolve(page, relative), 'https://cas.bnu.edu.cn/cas/login;jsessionid=A?service=x')

        class Opened:
            def __init__(self, location):
                self.response = SimpleNamespace(status=302, headers={'Location': location}, read=lambda: b'')
            def __enter__(self):
                return self.response
            def __exit__(self, *exc):
                return False
        target = network.wire('https://libseat.bnu.edu.cn/jsq-v?token=abc')
        with patch.object(session.opener, 'open', return_value=Opened(target)) as op:
            status, location, _ = session.send(http_auth.ENTRY)
        self.assertEqual(op.call_args.args[0].full_url, network.wire(http_auth.ENTRY))
        self.assertEqual((status, http_auth.library_token(location)), (302, 'abc'))
        with patch.object(session.opener, 'open', return_value=Opened('/login?redirect=x')), self.assertRaises(Error) as err:
            session.send(http_auth.ENTRY)
        self.assertEqual(err.exception.code, 'WEBVPN_LOGIN_REQUIRED')


if __name__ == '__main__':
    unittest.main()
