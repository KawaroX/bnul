import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bnul.client import Client, Error, minute, day, signed_headers, signing_key, save_token
from bnul.cli import main

class FakeClient(Client):
    def __init__(self, mode=0):
        self.system = {'mackCaptcha': mode}
        self.calls = []
    def api(self, path, body=None):
        self.calls.append((path, body))
        if 'getTimeLine' in path: return {'freeList': [{'label': '14:04-23:00'}]}
        if 'getStartTimes' in path: return [['now', '现在'], ['840', '14:00'], ['1140', '19:00']]
        if 'getEndTimes' in path: return [['990', '16:30']]
        if 'freeBook' in path: return {'status': 'RESERVE', 'message': '请完成签到'}
        raise AssertionError(path)

class Tests(unittest.TestCase):
    def test_minutes(self):
        self.assertEqual(minute('14:04'),844)
        for value in ['24:00','13:60','-1:00','14.04']:
            with self.assertRaises(ValueError): minute(value)
        self.assertEqual(day('2026-09-09'),'2026-09-09')
        with self.assertRaises(ValueError): day('2026-02-30')

    def test_signing(self):
        import hashlib,hmac
        got=signed_headers(b'test','id',123)
        self.assertEqual(got['X-hmac-request-key'],hmac.new(b'test',b'seat::id::123::POST',hashlib.sha256).hexdigest())
        self.assertNotEqual(signed_headers(b'test')['X-request-id'],signed_headers(b'test')['X-request-id'])

    def test_aes_config(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
        key='0123456789abcdef'; iv='fedcba9876543210'
        pad=PKCS7(128).padder(); raw=pad.update(b'signing-secret')+pad.finalize()
        enc=Cipher(algorithms.AES(key.encode()),modes.CBC(iv.encode())).encryptor()
        value=base64.b64encode(enc.update(raw)+enc.finalize()).decode()
        self.assertEqual(signing_key({'makePrefix':key,'makeSuffix':iv,'hmacKey':value}),b'signing-secret')

    def test_preview_and_validation(self):
        c=FakeClient()
        self.assertTrue(c.validate_booking('123','2026-09-09',840,990)['validated'])
        self.assertFalse(any('freeBook' in p for p,b in c.calls))
        self.assertFalse(any('getTimeLine' in p for p,b in c.calls))
        for start,end in [(845,990),(840,1000),(990,844)]:
            with self.assertRaises(Error): c.validate_booking('123','2026-09-09',start,end)

    def test_booking_and_captcha(self):
        c=FakeClient()
        self.assertEqual(c.book('123','2026-09-09',840,990)['status'],'RESERVE')
        self.assertEqual(sum('freeBook' in p for p,b in c.calls),1)
        c=FakeClient(2)
        with self.assertRaisesRegex(Error,'验证码'): c.book('123','2026-09-09',840,990)
        self.assertFalse(any('freeBook' in p for p,b in c.calls))

    def test_business_error_and_no_retry(self):
        c=Client('fake'); response=io.BytesIO(json.dumps({'status':False,'code':500,'message':'已有1个有效预约','data':{'ctId':'123'}}).encode())
        with patch.object(c.opener,'open',return_value=response) as op:
            with self.assertRaises(Error) as caught: c.api('user/currentUseMake')
            self.assertEqual(caught.exception.data,{'ctId':'123'})
            op.assert_called_once()

    def test_session_file_permissions(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'BNUL_CONFIG':tmp+'/auth.json'}):
            save_token('abc')
            self.assertEqual(json.loads(Path(tmp+'/auth.json').read_text())['token'],'abc')
            if os.name != 'nt':
                self.assertEqual(Path(tmp+'/auth.json').stat().st_mode & 0o777,0o600)

    def test_stop_mismatch(self):
        with patch('bnul.cli.Client') as cls, patch('sys.stdout',new_callable=io.StringIO):
            c=cls.return_value
            c.api.return_value={'id':'123','status':'CHECK_IN'}
            self.assertEqual(main(['--json','stop','--execute','--expect-id','456']),1)
            c.api.assert_called_once_with('user/currentUseMake')

    def test_seats_preserve_status_and_label(self):
        with patch('bnul.cli.Client') as cls, patch('sys.stdout',new_callable=io.StringIO) as out:
            cls.return_value.seats.return_value={'123':{'id':'123','label':'008','status':'IN_USE','afterFree':True}}
            self.assertEqual(main(['--json','seats','--start','19:00','--end','20:00','--label','008']),0)
            self.assertEqual(json.loads(out.getvalue())['data'][0]['status'],'IN_USE')

if __name__ == '__main__': unittest.main()

class BrowserAuthTests(unittest.TestCase):
    def test_only_official_session_requests(self):
        from bnul.browser_auth import session_request_token
        path='/jsq/static/frontApi/user/getUserInfo'
        self.assertEqual(session_request_token('https://libseat.bnu.edu.cn'+path,{'token':'session'}),'session')
        for url in ['https://evil.example'+path,'http://libseat.bnu.edu.cn'+path,'https://libseat.bnu.edu.cn/jsq/static/public/auth/cas/jwt']:
            self.assertIsNone(session_request_token(url,{'token':'session'}))
    def test_login_command(self):
        with patch('bnul.browser_auth.browser_login',return_value={'saved':True}) as login, patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(['--no-proxy','auth','login']),0)
            login.assert_called_once_with(True,300)

@unittest.skipUnless(__import__("importlib.util", fromlist=["find_spec"]).find_spec("playwright"), "optional browser dependency")
class BrowserFlowTests(unittest.TestCase):
    def test_browser_capture_validates_before_save(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from bnul.browser_auth import browser_login
        pw=MagicMock(); context=pw.chromium.launch_persistent_context.return_value
        page=MagicMock(); context.pages=[page]
        callbacks={}
        context.on.side_effect=lambda event, fn: callbacks.update({event:fn})
        page.goto.side_effect=lambda *a,**k: callbacks['request'](SimpleNamespace(
            url='https://libseat.bnu.edu.cn/jsq/static/frontApi/user/getUserInfo', headers={'token':'fresh'}))
        manager=MagicMock(); manager.__enter__.return_value=pw
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'BNUL_CONFIG':tmp+'/session.json'}), patch('playwright.sync_api.sync_playwright',return_value=manager), patch('bnul.browser_auth.Client') as client, patch('bnul.browser_auth.save_token') as save, patch('sys.stderr',new_callable=io.StringIO):
            self.assertTrue(browser_login(True,1)['saved'])
            client.return_value.api.assert_called_once_with('user/getUserInfo')
            save.assert_called_once_with('fresh')
            context.close.assert_called_once()

class AuthCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        env=patch.dict(os.environ,{'BNUL_CONFIG':str(self.root/'bnul/session.json'),'BNUL_SETTINGS':str(self.root/'bnul/settings.json'),
                                   'BNUL_WEBVPN_PROFILE':str(self.root/'webvpn')},clear=True)
        env.start(); self.addCleanup(env.stop)
    def test_removed_commands_are_rejected(self):
        for argv in [['login'],['auth','import'],['auth','exchange-link'],['auth','clear'],['auth','forget']]:
            with patch('bnul.browser_auth.browser_login') as login, patch('sys.stderr',new_callable=io.StringIO), self.assertRaises(SystemExit):
                main(argv)
            login.assert_not_called()
    def test_global_options_accepted_after_subcommand(self):
        with patch('bnul.browser_auth.browser_login',return_value={}) as login, patch('sys.stdout',new_callable=io.StringIO) as out:
            self.assertEqual(main(['auth','login','--no-proxy','--json']),0)
            login.assert_called_once_with(True,300)
            self.assertTrue(json.loads(out.getvalue())['ok'])
    def test_browser_flag_is_saved_for_automatic_login(self):
        from bnul.browser_auth import browser_options
        settings=self.root/'bnul/settings.json'; settings.parent.mkdir()
        settings.write_text(json.dumps({'transport':'auto','browser_executable':str(self.root/'missing')}))
        with patch('bnul.browser_auth.browser_login',return_value={}), patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(['auth','login','--browser','chrome']),0)
        self.assertEqual(json.loads(settings.read_text()),{'transport':'auto','browser_executable':str(self.root/'missing'),'browser':'chrome'})
        self.assertEqual(browser_options(),{'channel':'chrome'})
        with patch.dict(os.environ,{'BNUL_BROWSER':'msedge'}): self.assertEqual(browser_options(),{'channel':'msedge'})
    def test_logout_removes_password_session_and_browser_state(self):
        session=self.root/'bnul/session.json'; profile=self.root/'bnul/browser-profile'; vpn=self.root/'webvpn'
        for directory in (profile, vpn/'browser-profile'): directory.mkdir(parents=True)
        for path in (session, profile/'Cookies', vpn/'cookies.txt', vpn/'unrelated.txt'): path.write_text('x')
        with patch('bnul.credentials.backend') as backend, patch('sys.stdout',new_callable=io.StringIO) as out:
            backend.return_value.get_password.return_value='{}'
            self.assertEqual(main(['--json','auth','logout']),0)
            backend.return_value.delete_password.assert_called_once()
        data=json.loads(out.getvalue())['data']
        self.assertTrue(data['loggedOut']); self.assertTrue(data['credentialsRemoved'])
        self.assertFalse(any(p.exists() for p in (session, profile, vpn/'cookies.txt', vpn/'browser-profile')))
        self.assertTrue((vpn/'unrelated.txt').exists())
    def test_logout_reports_environment_credentials_and_keyring_failure(self):
        with patch.dict(os.environ,{'BNUL_USERNAME':'test','BNUL_PASSWORD':'test'}), patch('bnul.credentials.backend',side_effect=Error('unavailable','CREDENTIALS_UNAVAILABLE')), patch('sys.stdout',new_callable=io.StringIO) as out:
            self.assertEqual(main(['--json','auth','logout']),0)
        data=json.loads(out.getvalue())['data']
        self.assertFalse(data['loggedOut']); self.assertTrue(data['environmentCredentialsPresent']); self.assertIn('credentialError',data)
    def test_status_reports_credential_source_without_secret(self):
        with patch.dict(os.environ,{'BNUL_USERNAME':'student','BNUL_PASSWORD':'test-only'}), patch('bnul.cli.Client') as cls, patch('sys.stdout',new_callable=io.StringIO) as out:
            cls.return_value.network.mode='direct'
            cls.return_value.bootstrap.side_effect=Error('没有本地会话','LOCAL_AUTH_MISSING')
            self.assertEqual(main(['--json','auth','status']),0)
            self.assertFalse(cls.return_value.auto_auth)
        data=json.loads(out.getvalue())['data']
        self.assertEqual((data['authenticated'],data['credentials'],data['browser'],data['reasonCode']),(False,'环境变量','chromium','LOCAL_AUTH_MISSING'))
        self.assertNotIn('test-only',out.getvalue())
        with patch.dict(os.environ,{'BNUL_USERNAME':'student','BNUL_PASSWORD':'test-only'}), patch('bnul.cli.Client') as cls, patch('sys.stdout',new_callable=io.StringIO) as out:
            cls.return_value.network.mode='direct'
            cls.return_value.bootstrap.side_effect=Error('没有本地会话','LOCAL_AUTH_MISSING')
            self.assertEqual(main(['auth','status']),0)
        self.assertIn('登录状态: 未登录',out.getvalue()); self.assertIn('后台自动登录',out.getvalue())
    def test_status_shows_account_without_contact_details_or_key(self):
        info={'username':'202621040038','fullName':'测试','flagName':'研究生','maxMinute':900,'breachNum':2,
              'phone':'13800000000','email':'a@b.c','hmacKey':'secret-key','totalTime':11074}
        with patch('bnul.cli.Client') as cls, patch('bnul.credentials.backend') as backend, patch('sys.stdout',new_callable=io.StringIO) as out:
            backend.return_value.get_password.return_value=None
            cls.return_value.network.mode='direct'; cls.return_value.api.return_value=info
            self.assertEqual(main(['auth','status']),0)
        text=out.getvalue()
        for shown in ('登录状态: 已登录','202****40038','测试','单次最长预约: 15 小时','违约次数: 2','184 小时 34 分钟','自动登录凭据: 未配置'):
            self.assertIn(shown,text)
        for hidden in ('13800000000','a@b.c','secret-key','202621040038'):
            self.assertNotIn(hidden,text)
    def test_setup_falls_back_to_private_file_only_after_confirmation(self):
        from bnul.credentials import get_credentials
        unavailable=Error('无法将登录凭据保存到 系统凭据存储','CREDENTIALS_UNAVAILABLE')
        path=self.root/'bnul/credentials.env'
        with patch('bnul.credentials.store_credentials',side_effect=unavailable), patch('builtins.input',side_effect=['student','n']), patch('getpass.getpass',return_value='p"w\\ #1'), patch('sys.stdout',new_callable=io.StringIO), patch('sys.stderr',new_callable=io.StringIO):
            self.assertEqual(main(['auth','setup']),1)
        self.assertFalse(path.exists())
        with patch('bnul.credentials.store_credentials',side_effect=unavailable), patch('builtins.input',side_effect=['student','y']), patch('getpass.getpass',return_value='p"w\\ #1'), patch('sys.stdout',new_callable=io.StringIO) as out, patch('sys.stderr',new_callable=io.StringIO):
            self.assertEqual(main(['auth','setup']),0)
        self.assertIn('凭据文件',out.getvalue())
        if os.name!='nt': self.assertEqual(path.stat().st_mode & 0o777,0o600)
        with patch('bnul.credentials.backend') as backend:
            self.assertEqual(get_credentials(),{'username':'student','password':'p"w\\ #1'})
            backend.assert_not_called()
        with patch('bnul.credentials.backend') as backend, patch('sys.stdout',new_callable=io.StringIO):
            backend.return_value.get_password.return_value=None
            self.assertEqual(main(['auth','logout']),0)
        self.assertFalse(path.exists())
    def test_keyring_setup_removes_stale_fallback_file(self):
        from bnul.credentials import store_credentials, store_credentials_file
        path=store_credentials_file('student','old')
        with patch('bnul.credentials.backend'):
            store_credentials('student','new')
        self.assertFalse(path.exists())

class LifeCommandTests(unittest.TestCase):
    def test_life_defaults_to_current_reservation(self):
        with patch('bnul.cli.Client') as cls, patch('sys.stdout',new_callable=io.StringIO) as out:
            c=cls.return_value
            c.api.side_effect=lambda path: {'id':123,'status':'CHECK_IN'} if path=='user/currentUseMake' else [{'status':'CHECK_IN'}]
            self.assertEqual(main(['life']),0)
            self.assertEqual([call.args[0] for call in c.api.call_args_list],['user/currentUseMake','user/makeLife/123'])
            self.assertIn('预约ID: 123',out.getvalue())
    def test_life_without_current_reservation_fails(self):
        with patch('bnul.cli.Client') as cls, patch('sys.stdout',new_callable=io.StringIO) as out:
            c=cls.return_value; c.api.return_value=None
            self.assertEqual(main(['--json','life']),1)
            c.api.assert_called_once_with('user/currentUseMake')
            self.assertEqual(json.loads(out.getvalue())['code'],'NO_CURRENT_RESERVATION')
    def test_life_with_id_skips_current_lookup(self):
        with patch('bnul.cli.Client') as cls, patch('sys.stdout',new_callable=io.StringIO):
            c=cls.return_value; c.api.return_value=[]
            self.assertEqual(main(['life','456']),0)
            c.api.assert_called_once_with('user/makeLife/456')

class AutoAuthTests(unittest.TestCase):
    def test_expired_read_restored_once(self):
        with patch.dict(os.environ,{},clear=True):
            c=Client()
        with patch.object(c,'request',side_effect=[Error('expired',20003),{'id':'ok'}]) as req, patch.object(c,'recover_auth') as recover:
            self.assertEqual(c.api('user/currentUseMake'),{'id':'ok'})
            recover.assert_called_once()
            self.assertEqual(req.call_count,2)
    def test_failed_recovery_does_not_loop(self):
        c=Client();c.auto_auth=True
        with patch.object(c,'request',side_effect=Error('expired',20003)) as req, patch.object(c,'recover_auth') as recover:
            with self.assertRaises(Error):c.api('user/getUserInfo')
            recover.assert_called_once();self.assertEqual(req.call_count,2)
    def test_write_preflight_recovers_but_write_is_not_replayed(self):
        c=Client();c.auto_auth=True
        with patch.object(c,'request',side_effect=[Error('expired',20003),{},Error('network unknown')]) as req, patch.object(c,'recover_auth') as recover:
            with self.assertRaises(Error):c.api('make/stop')
            recover.assert_called_once()
            self.assertEqual(sum(call.args[0].endswith('make/stop') for call in req.call_args_list),1)
    def test_explicit_token_not_overridden(self):
        c=Client('explicit')
        with patch.object(c,'request',side_effect=Error('expired',20003)),patch.object(c,'recover_auth') as recover:
            with self.assertRaises(Error):c.api('user/getUserInfo')
            recover.assert_not_called()
    def test_unrelated_error_not_retried(self):
        c=Client();c.auto_auth=True
        with patch.object(c,'request',side_effect=Error('已有有效预约',500)),patch.object(c,'recover_auth') as recover:
            with self.assertRaises(Error):c.api('user/currentUseMake')
            recover.assert_not_called()
    def test_credentials_only_on_cas_origin(self):
        from unittest.mock import MagicMock
        from bnul.browser_auth import submit_credentials
        page=MagicMock();page.url='https://evil.example/cas/login'
        self.assertFalse(submit_credentials(page,{'username':'a','password':'b'}))
        page.locator.assert_not_called()
    def test_captcha_blocks_password_submission(self):
        from unittest.mock import MagicMock
        from bnul.browser_auth import submit_credentials
        page=MagicMock();page.url='https://cas.bnu.edu.cn/cas/login'
        page.locator.return_value.is_visible.return_value=True
        with self.assertRaises(Error) as e:submit_credentials(page,{'username':'a','password':'b'})
        self.assertEqual(e.exception.code,'AUTH_INTERACTION_REQUIRED')
        page.locator.return_value.fill.assert_not_called()
    def test_credentials_use_keychain(self):
        from bnul.credentials import store_credentials,get_credentials,forget_credentials,SERVICE,ACCOUNT
        with patch('bnul.credentials.backend') as backend:
            store_credentials('user','secret')
            value=backend.return_value.set_password.call_args.args
            self.assertEqual(value[:2],(SERVICE,ACCOUNT))
            backend.return_value.get_password.return_value=value[2]
            self.assertEqual(get_credentials()['password'],'secret')
            forget_credentials()
            backend.return_value.delete_password.assert_called_once_with(SERVICE,ACCOUNT)

class PasswordFormTests(unittest.TestCase):
    def test_observed_form_filled_and_submitted(self):
        from unittest.mock import MagicMock
        from bnul.browser_auth import submit_credentials
        page=MagicMock();page.url='https://cas.bnu.edu.cn/cas/login?service=official'
        fields={s:MagicMock() for s in ['#loginForm .username input','#loginForm #password-input','#loginForm input[name="code"]','#loginForm .login-btn']}
        page.locator.side_effect=fields.__getitem__
        fields['#loginForm .username input'].is_visible.return_value=True
        fields['#loginForm #password-input'].is_visible.return_value=True
        fields['#loginForm input[name="code"]'].is_visible.return_value=False
        self.assertTrue(submit_credentials(page,{'username':'student','password':'test-only'}))
        fields['#loginForm .username input'].fill.assert_called_once_with('student')
        fields['#loginForm #password-input'].fill.assert_called_once_with('test-only')
        fields['#loginForm .login-btn'].click.assert_called_once()

class PlatformTests(unittest.TestCase):
    def test_backend_routing(self):
        from bnul.credentials import backend_spec
        self.assertEqual(backend_spec('win32'),('keyring.backends.Windows','WinVaultKeyring'))
        self.assertEqual(backend_spec('linux'),('keyring.backends.SecretService','Keyring'))
        self.assertEqual(backend_spec('darwin'),('keyring.backends.macOS','Keyring'))
    def test_browser_selection(self):
        from bnul.browser_auth import browser_options
        for platform, expected in [('win32',{}),('linux',{}),('darwin',{})]:
            with patch('bnul.browser_auth.sys.platform',platform),patch.dict(os.environ,{},clear=True):
                self.assertEqual(browser_options(),expected)
        with patch.dict(os.environ,{'BNUL_BROWSER':'msedge'}):self.assertEqual(browser_options(),{'channel':'msedge'})
    def test_headless_credentials_without_keyring(self):
        from bnul.credentials import get_credentials
        with patch.dict(os.environ,{'BNUL_USERNAME':'test','BNUL_PASSWORD':'test'}),patch('bnul.credentials.backend') as b:
            self.assertEqual(get_credentials(),{'username':'test','password':'test'})
            b.assert_not_called()
    def test_partial_environment_rejected(self):
        from bnul.credentials import get_credentials
        with patch.dict(os.environ,{'BNUL_USERNAME':'test'},clear=True):
            with self.assertRaises(Error): get_credentials()

class InstallationTests(unittest.TestCase):
    def test_skill_installs_bundled_files(self):
        from bnul.install import install_skill
        with tempfile.TemporaryDirectory() as temp:
            result=install_skill(temp)
            self.assertEqual(result['installed'],temp)
            self.assertTrue((Path(temp)/'SKILL.md').is_file())
            for name in ('installation', 'webvpn', 'auth', 'watch'):
                self.assertTrue((Path(temp)/f'references/{name}.md').is_file())
    def test_browser_installs_in_cli_python(self):
        from bnul.install import install_browser
        import sys
        with patch('bnul.install.subprocess.run') as run:
            run.return_value.returncode=0
            install_browser(True)
            self.assertEqual(run.call_args.args[0],[sys.executable,'-m','playwright','install','--with-deps','chromium'])

class NowTests(unittest.TestCase):
    def test_now_input(self):
        from bnul.client import start_minute
        for value in ['now','现在','-1']: self.assertEqual(start_minute(value),-1)
        from bnul.cli import parser
        self.assertEqual(parser().parse_args(['times','--seat','123','--start','-1']).start,-1)
    def test_now_queries_clock_but_books_sentinel(self):
        c=FakeClient()
        with patch('bnul.client.query_start',return_value=941):
            c.book('123','2026-09-09',-1,990)
        paths=[p for p,b in c.calls]
        self.assertIn('res/getEndTimes/123/2026-09-09/941',paths)
        self.assertIn('make/freeBook/123/2026-09-09/-1/990?capToken=capToken',paths)
    def test_now_unavailable(self):
        c=FakeClient()
        with patch.object(c,'times',return_value={'starts':[['960','16:00']],'ends':[['990','16:30']]}),patch('bnul.client.query_start',return_value=941):
            with self.assertRaises(Error):c.validate_booking('123','2026-09-09',-1,990)
    def test_future_now_rejected(self):
        from bnul.client import query_start
        with self.assertRaises(Error):query_start(-1,'2999-01-01')
    def test_arbitrary_minutes_not_in_options_rejected(self):
        with self.assertRaises(Error):FakeClient().validate_booking('123','2026-09-09',844,990)
    def test_now_matched_as_string_not_integer(self):
        c=FakeClient()
        c.times=lambda seat,date,start,**_:{'starts':[['now','现在'],['960','16:00']],'ends':[['990','16:30']]}
        with patch('bnul.client.query_start',return_value=941):
            result=c.validate_booking('123','2026-09-09',-1,990)
        self.assertTrue(result['validated'])
        self.assertEqual(result['beginMinute'],-1)
    def test_now_missing_from_starts_rejects(self):
        c=FakeClient()
        c.times=lambda seat,date,start,**_:{'starts':[['960','16:00']],'ends':[['990','16:30']]}
        with patch('bnul.client.query_start',return_value=941):
            with self.assertRaises(Error) as ctx:
                c.validate_booking('123','2026-09-09',-1,990)
            self.assertEqual(ctx.exception.code,'TIME_UNAVAILABLE')
    def test_now_not_confused_with_numeric_zero(self):
        c=FakeClient()
        c.times=lambda seat,date,start,**_:{'starts':[['0','00:00']],'ends':[['60','01:00']]}
        with patch('bnul.client.query_start',return_value=0):
            with self.assertRaises(Error):
                c.validate_booking('123','2026-09-09',-1,60)
    def test_fixed_start_matched_as_integer_string(self):
        c=FakeClient()
        c.times=lambda seat,date,start,**_:{'starts':[['960','16:00']],'ends':[['990','16:30']]}
        result=c.validate_booking('123','2026-09-09',960,990)
        self.assertTrue(result['validated'])


class ReadRetryTests(unittest.TestCase):
    def test_read_only_retries_once_on_network_error(self):
        c = Client('test')
        c.auto_auth = False
        calls = [0]
        def flaky(path, body=None, public=False):
            calls[0] += 1
            if calls[0] == 1:
                raise Error('网络请求失败')
            return {'id': '123'}
        with patch.object(c, 'request', side_effect=flaky):
            result = c.api('user/currentUseMake')
        self.assertEqual(calls[0], 2)
        self.assertEqual(result, {'id': '123'})

    def test_read_only_does_not_retry_more_than_once(self):
        c = Client('test')
        c.auto_auth = False
        with patch.object(c, 'request', side_effect=Error('网络请求失败')):
            with self.assertRaises(Error):
                c.api('user/currentUseMake')

    def test_write_does_not_retry_on_network_error(self):
        c = Client('test')
        c.auto_auth = False
        calls = [0]
        def counting(path, body=None, public=False):
            calls[0] += 1
            raise Error('网络请求失败')
        with patch.object(c, 'request', side_effect=counting):
            with self.assertRaises(Error):
                c.api('make/freeBook/123/2026-09-09/960/990')
        self.assertEqual(calls[0], 1)

    def test_auth_error_not_retried_as_network(self):
        c = Client('test')
        c.auto_auth = False
        with patch.object(c, 'request', side_effect=Error('服务器判定登录失效', 20003)):
            with self.assertRaises(Error) as ctx:
                c.api('res/findRoomDuration/123/2026-09-09')
        self.assertEqual(ctx.exception.code, 20003)


class RoomsPaginationTests(unittest.TestCase):
    def test_missing_total_page_returns_first_page(self):
        c = Client('test')
        with patch.object(c, 'api', return_value={'pageList': [{'id': '1'}]}) as api:
            result = c.rooms('123', '2026-09-09', 0, 0)
            self.assertEqual(len(result), 1)
            api.assert_called_once()

    def test_zero_total_page_returns_first_page(self):
        c = Client('test')
        with patch.object(c, 'api', return_value={'pageList': [{'id': '1'}], 'totalPage': 0}) as api:
            result = c.rooms('123', '2026-09-09', 0, 0)
            self.assertEqual(len(result), 1)
            api.assert_called_once()

    def test_non_numeric_total_page(self):
        c = Client('test')
        with patch.object(c, 'api', return_value={'pageList': [], 'totalPage': 'abc'}) as api:
            result = c.rooms('123', '2026-09-09', 0, 0)
            self.assertEqual(result, [])

    def test_malformed_response_raises_error(self):
        c = Client('test')
        with patch.object(c, 'api', return_value='not a dict'):
            with self.assertRaises(Error):
                c.rooms('123', '2026-09-09', 0, 0)

    def test_missing_page_list_raises_error(self):
        c = Client('test')
        with patch.object(c, 'api', return_value={'totalPage': 1}):
            with self.assertRaises(Error):
                c.rooms('123', '2026-09-09', 0, 0)


class OutputEncodingTests(unittest.TestCase):
    def test_help_with_legacy_pipe_encoding(self):
        import subprocess,sys
        env=dict(os.environ,PYTHONIOENCODING='cp1252')
        result=subprocess.run([sys.executable,'-m','bnul','--help'],env=env,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('北师大',result.stdout.decode('utf-8'))
