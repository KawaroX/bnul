import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from bnul.client import Client, Error, save_token, load_session_hmac_key
from bnul.browser_auth import login_response_session, browser_login


def config():
    return {'hmac': 1, 'hmacKey': '', 'makePrefix': 'server_date_time',
            'makeSuffix': 'client_date_time'}


def encrypted_key():
    pad = PKCS7(128).padder()
    raw = pad.update(b'login-issued-test-key') + pad.finalize()
    enc = Cipher(algorithms.AES(b'server_date_time'), modes.CBC(b'client_date_time')).encryptor()
    return base64.b64encode(enc.update(raw) + enc.finalize()).decode()


class SessionSigningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {'BNUL_CONFIG': self.tmp.name + '/session.json'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_cached_login_key_is_used_and_signed_request_sent(self):
        save_token('session', encrypted_key())
        c = Client(token='session')
        with patch.object(c, 'request', return_value=config()):
            c.bootstrap()
        self.assertEqual(c.key, b'login-issued-test-key')
        import io
        with patch.object(c.opener, 'open', return_value=io.BytesIO(b'{"status":true,"data":{}}')) as op:
            c.api('user/currentUseMake')
        self.assertIn('X-hmac-request-key', dict(op.call_args.args[0].header_items()))

    def test_no_key_is_reused_for_another_token(self):
        save_token('one', encrypted_key())
        self.assertIsNone(load_session_hmac_key('two'))
        c = Client(token='two')
        with patch.object(c, 'request', return_value=config()), patch.object(c, 'recover_auth') as recover:
            with self.assertRaises(Error) as err:
                c.bootstrap()
        self.assertEqual(err.exception.code, 'SESSION_SIGNING_KEY_MISSING')
        recover.assert_not_called()

    def test_legacy_token_migrates_via_one_login(self):
        save_token('old')
        c = Client()
        c.auto_auth = True
        def login(**kwargs):
            save_token('fresh', encrypted_key())
        with patch.object(c, 'request', side_effect=lambda *a, **k: config()), \
                patch('bnul.browser_auth.browser_login', side_effect=login) as login_mock:
            c.bootstrap()
        login_mock.assert_called_once()
        self.assertEqual(c.token, 'fresh')
        self.assertEqual(c.key, b'login-issued-test-key')

    def test_login_without_key_fails_without_loop(self):
        save_token('old')
        c = Client()
        c.auto_auth = True
        with patch.object(c, 'request', side_effect=lambda *a, **k: config()), \
                patch('bnul.browser_auth.browser_login') as login:
            with self.assertRaises(Error) as err:
                c.bootstrap()
        self.assertEqual(err.exception.code, 'SESSION_SIGNING_KEY_MISSING')
        login.assert_called_once()

    def test_saving_new_token_clears_previous_key(self):
        save_token('old', encrypted_key())
        save_token('new')
        self.assertIsNone(load_session_hmac_key('new'))
        self.assertEqual(json.loads(Path(os.environ['BNUL_CONFIG']).read_text()), {'token': 'new'})

    def test_old_public_key_protocol_still_works(self):
        c = Client(token='session')
        with patch.object(c, 'request', return_value={**config(), 'hmacKey': encrypted_key()}):
            c.bootstrap()
        self.assertEqual(c.key, b'login-issued-test-key')

    def test_login_payload_only_from_official_success_response(self):
        payload = {'status': True, 'data': {'token': 'fresh', 'userInfoRes': {'hmacKey': encrypted_key()}}}
        url = 'https://libseat.bnu.edu.cn/jsq/static/public/auth/cas/ticket'
        self.assertEqual(login_response_session(url, payload), ('fresh', encrypted_key()))
        for bad in [url.replace('https:', 'http:'), url.replace('libseat.bnu.edu.cn', 'evil.example'),
                    'https://libseat.bnu.edu.cn/jsq/static/frontApi/user/getUserInfo']:
            self.assertIsNone(login_response_session(bad, payload))
        self.assertIsNone(login_response_session(url, {**payload, 'status': False}))

    def test_browser_validates_login_token_and_key_before_saving(self):
        pw = MagicMock()
        context = pw.chromium.launch_persistent_context.return_value
        page = MagicMock()
        context.pages = [page]
        callbacks = {}
        context.on.side_effect = lambda name, callback: callbacks.update({name: callback})
        response = SimpleNamespace(
            url='https://libseat.bnu.edu.cn/jsq/static/public/auth/cas/ticket',
            json=lambda: {'status': True, 'data': {'token': 'fresh', 'userInfoRes': {'hmacKey': encrypted_key()}}})
        page.goto.side_effect = lambda *a, **k: callbacks['response'](response)
        manager = MagicMock()
        manager.__enter__.return_value = pw
        with patch('playwright.sync_api.sync_playwright', return_value=manager), \
                patch('bnul.browser_auth.Client') as client, patch('bnul.browser_auth.save_token') as save:
            result = browser_login(timeout=1, headless=True)
        self.assertTrue(result['saved'])
        self.assertEqual(client.return_value.session_hmac_key, encrypted_key())
        client.return_value.api.assert_called_once_with('user/getUserInfo')
        save.assert_called_once_with('fresh', encrypted_key())

