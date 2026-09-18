import unittest
from bnul.browser_auth import session_request_token, submit_credentials
from bnul.client import Error


class SessionRequestTokenTests(unittest.TestCase):
    def test_valid_api_request(self):
        url = 'https://libseat.bnu.edu.cn/jsq/static/frontApi/user/currentUseMake'
        headers = {'token': 'abc123'}
        self.assertEqual(session_request_token(url, headers), 'abc123')

    def test_strips_whitespace(self):
        url = 'https://libseat.bnu.edu.cn/jsq/static/frontApi/res/buildings'
        headers = {'token': '  token_value  '}
        self.assertEqual(session_request_token(url, headers), 'token_value')

    def test_wrong_host_returns_none(self):
        url = 'https://evil.example.com/jsq/static/frontApi/user/info'
        headers = {'token': 'abc123'}
        self.assertIsNone(session_request_token(url, headers))

    def test_wrong_path_returns_none(self):
        url = 'https://libseat.bnu.edu.cn/other/path'
        headers = {'token': 'abc123'}
        self.assertIsNone(session_request_token(url, headers))

    def test_http_returns_none(self):
        url = 'http://libseat.bnu.edu.cn/jsq/static/frontApi/user/info'
        headers = {'token': 'abc123'}
        self.assertIsNone(session_request_token(url, headers))

    def test_missing_token_returns_none(self):
        url = 'https://libseat.bnu.edu.cn/jsq/static/frontApi/user/info'
        self.assertIsNone(session_request_token(url, {}))

    def test_empty_token_returns_none(self):
        url = 'https://libseat.bnu.edu.cn/jsq/static/frontApi/user/info'
        headers = {'token': '   '}
        self.assertIsNone(session_request_token(url, headers))

    def test_non_string_token_returns_none(self):
        url = 'https://libseat.bnu.edu.cn/jsq/static/frontApi/user/info'
        headers = {'token': 12345}
        self.assertIsNone(session_request_token(url, headers))


class SubmitCredentialsTests(unittest.TestCase):
    def _page(self, url, username_visible=True, password_visible=True, code_visible=False):
        class Locator:
            def __init__(self, visible):
                self._visible = visible
                self.filled = None
                self.clicked = False
            def is_visible(self):
                return self._visible
            def fill(self, value):
                self.filled = value
            def click(self):
                self.clicked = True

        class Page:
            def __init__(self):
                self.url = url
                self._username = Locator(username_visible)
                self._password = Locator(password_visible)
                self._code = Locator(code_visible)
                self._login_btn = Locator(True)
            def locator(self, selector):
                if 'username' in selector:
                    return self._username
                if 'password' in selector:
                    return self._password
                if 'code' in selector:
                    return self._code
                if 'login-btn' in selector:
                    return self._login_btn
                return Locator(False)
        return Page()

    def test_fills_credentials_on_cas_login(self):
        page = self._page('https://cas.bnu.edu.cn/cas/login')
        creds = {'username': 'student', 'password': 'secret'}
        self.assertTrue(submit_credentials(page, creds))
        self.assertEqual(page._username.filled, 'student')
        self.assertEqual(page._password.filled, 'secret')
        self.assertTrue(page._login_btn.clicked)

    def test_cas_login_with_jsessionid(self):
        page = self._page('https://cas.bnu.edu.cn/cas/login;jsessionid=ABC123?service=https://example.com')
        creds = {'username': 'student', 'password': 'secret'}
        self.assertTrue(submit_credentials(page, creds))

    def test_wrong_host_returns_false(self):
        page = self._page('https://evil.example.com/cas/login')
        self.assertFalse(submit_credentials(page, {'username': 'a', 'password': 'b'}))

    def test_wrong_path_returns_false(self):
        page = self._page('https://cas.bnu.edu.cn/other/login')
        self.assertFalse(submit_credentials(page, {'username': 'a', 'password': 'b'}))

    def test_http_returns_false(self):
        page = self._page('http://cas.bnu.edu.cn/cas/login')
        self.assertFalse(submit_credentials(page, {'username': 'a', 'password': 'b'}))

    def test_hidden_username_returns_false(self):
        page = self._page('https://cas.bnu.edu.cn/cas/login', username_visible=False)
        self.assertFalse(submit_credentials(page, {'username': 'a', 'password': 'b'}))

    def test_captcha_visible_raises_error(self):
        page = self._page('https://cas.bnu.edu.cn/cas/login', code_visible=True)
        with self.assertRaises(Error) as ctx:
            submit_credentials(page, {'username': 'a', 'password': 'b'})
        self.assertEqual(ctx.exception.code, 'AUTH_INTERACTION_REQUIRED')
