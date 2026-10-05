import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from bnul.client import Error
from bnul.webvpn import worker, write_status, read_status, start_login, current_attempt


class Response(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url
    def geturl(self):
        return self.url


class WebVPNTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.profile = Path(self.directory.name) / 'private'
        self.images = Path(self.directory.name) / 'images'
        env = patch.dict(os.environ, {'BNUL_WEBVPN_PROFILE': str(self.profile),
                                     'BNUL_QR_DIR': str(self.images),
                                     'BNUL_SETTINGS': self.directory.name + '/absent.json'}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        write_status('attempt', status='starting')

    def responses(self, final):
        return [Response(b'login', 'https://webvpn.bnu.edu.cn/login'),
                Response(b'<img src="qr_code.php?uuid=official_test_id&amp;appid=17">', 'https://weixin.bnu.edu.cn'),
                Response(b'\x89PNG\r\n\x1a\nimage', 'https://weixin.bnu.edu.cn'), *final]

    def test_valid_session_reused_without_qr(self):
        opener = Mock()
        opener.open.return_value = Response(b'portal', 'https://webvpn.bnu.edu.cn/')
        with patch('bnul.webvpn.build_opener', return_value=opener), patch('bnul.webvpn.save_cookies') as save:
            worker('attempt')
        self.assertEqual(read_status()['status'], 'already_authenticated')
        opener.open.assert_called_once()
        save.assert_called_once()
        self.assertFalse(self.images.exists())

    def test_expired_qr_is_reported_and_image_is_deliverable(self):
        opener = Mock()
        opener.open.side_effect = self.responses([Response(b'window.wx_errcode=402;', 'https://weixin.bnu.edu.cn')])
        with patch('bnul.webvpn.build_opener', return_value=opener):
            worker('attempt')
        self.assertEqual(read_status()['status'], 'qr_expired')
        image = self.images / 'login-attempt.png'
        self.assertTrue(image.read_bytes().startswith(b'\x89PNG'))
        self.assertFalse(image.is_relative_to(self.profile))
        if os.name != 'nt':
            self.assertEqual(image.stat().st_mode & 0o777, 0o600)

    def test_callback_must_be_the_actual_school_portal(self):
        opener = Mock()
        opener.open.side_effect = self.responses([
            Response(b'window.wx_errcode=405;window.wx_code="test_code";', 'https://weixin.bnu.edu.cn'),
            Response(b'other', 'https://evil.example/')])
        with patch('bnul.webvpn.build_opener', return_value=opener), patch('bnul.webvpn.save_cookies') as save:
            with self.assertRaises(Error):
                worker('attempt')
            save.assert_not_called()

    def test_accepted_callback_saves_cookies_and_authenticates(self):
        opener = Mock()
        opener.open.side_effect = self.responses([
            Response(b'window.wx_errcode=405;window.wx_code="test_code";', 'https://weixin.bnu.edu.cn'),
            Response(b'portal', 'https://webvpn.bnu.edu.cn/')])
        with patch('bnul.webvpn.build_opener', return_value=opener), patch('bnul.webvpn.save_cookies') as save:
            worker('attempt')
        self.assertEqual(read_status()['status'], 'authenticated')
        save.assert_called_once()

    def test_refresh_supersedes_old_attempt_and_pending_qr_is_reused(self):
        write_status('old', status='scan_required', qr_path='/existing.png')
        with patch('bnul.webvpn.subprocess.Popen') as spawn:
            self.assertEqual(start_login()['attempt'], 'old')
            spawn.assert_not_called()
        def start(command, **kwargs):
            write_status(command[-1], status='scan_required', qr_path='/new.png')
        with patch('bnul.webvpn.subprocess.Popen', side_effect=start):
            result = start_login(refresh=True)
        self.assertNotEqual(result['attempt'], 'old')
        self.assertFalse(current_attempt('old'))


if __name__ == '__main__':
    unittest.main()
