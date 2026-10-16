import io
import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from bnul.client import Error
from bnul.cli import parser
from bnul.credentials import get_credentials
from bnul.watch import (Store, check_cycle, record_result, read_status, health_check,
                        reconcile_actions, run_watch)
from bnul.watch_notify import enqueue, flush, send_slack, safe_error
from test_watch import at, reservation, FakeClient


@unittest.skipIf(os.name == 'nt', 'POSIX daemon')
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'watch.json'
        self.store = Store(self.path)
        self.args = parser().parse_args(['watch', '--state-file', str(self.path)])

    def test_auth_backoff_persists_and_external_login_recovers(self):
        factory = Mock(return_value=FakeClient([]))
        with patch('bnul.watch.tick', side_effect=Error('需要验证', 'AUTH_INTERACTION_REQUIRED')):
            result = check_cycle(self.args, self.store, lambda: at('10:00'), factory)
            self.assertEqual(result['code'], 'AUTH_INTERACTION_REQUIRED')
        reloaded = Store(self.path)
        with reloaded.locked():
            factory = Mock(return_value=FakeClient([]))
            with patch('bnul.watch.tick', side_effect=Error('会话失效', 20003)):
                result = check_cycle(self.args, reloaded, lambda: at('10:02'), factory)
            self.assertFalse(factory.return_value.auto_auth)
            self.assertEqual(result['code'], 'AUTH_INTERACTION_REQUIRED')
            self.assertEqual(reloaded.data['auth']['failures'], 1)
            c = FakeClient([''])
            result = check_cycle(self.args, reloaded, lambda: at('10:04'), lambda **kw: c)
            self.assertEqual(result['event'], 'idle')
            self.assertEqual(reloaded.data['auth'], {})

    def test_retry_after_backoff_and_doubling(self):
        self.store.data['auth'] = {'failures': 1, 'retryAt': at('10:30').timestamp()}
        c = FakeClient([])
        c.auto_auth = True
        c.auth_recovered = True
        with patch('bnul.watch.tick', side_effect=Error('浏览器异常')):
            check_cycle(self.args, self.store, lambda: at('10:31'), lambda **kw: c)
        self.assertTrue(c.auto_auth)
        self.assertEqual(self.store.data['auth']['retryAt'], at('11:31').timestamp())

    def test_network_errors_do_not_claim_password_failure(self):
        with patch('bnul.watch.tick', side_effect=Error('网络请求失败')):
            result = check_cycle(self.args, self.store, lambda: at('10:00'), lambda **kw: FakeClient([]))
        self.assertFalse(self.store.data['auth'])
        self.assertEqual(result['code'], 'WATCH_CHECK_FAILED')

    def test_login_failure_does_not_exit_daemon_and_loop_uses_120_seconds(self):
        c = FakeClient([])
        current = [at('10:00')]
        def advance(seconds):
            current[0] += timedelta(seconds=seconds)
            if current[0] >= at('10:04'):
                raise KeyboardInterrupt()
        with patch('bnul.watch.Client', return_value=c), patch('bnul.watch.tick', side_effect=Error('验证', 'AUTH_INTERACTION_REQUIRED')), patch('bnul.watch.now_local', side_effect=lambda: current[0]), patch('bnul.watch.time.sleep', side_effect=advance), patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaises(KeyboardInterrupt):
                run_watch(self.args)
        data = json.loads(self.path.read_text())
        self.assertEqual(data['health']['checkCount'], 2)
        self.assertEqual(data['lastCheck']['at'], at('10:02').isoformat())
        self.assertEqual(data['heartbeatAt'], at('10:03').isoformat())
        self.assertFalse(c.auto_auth)

    def test_failure_dedup_reminder_recovery_and_second_incident(self):
        bad = {'event': 'error', 'code': 'NETWORK', 'error': '网络失败'}
        record_result(self.store, bad, at('10:00'), True)
        record_result(self.store, bad, at('10:02'), True)
        self.assertEqual(len(self.store.data['notifications']), 1)
        record_result(self.store, bad, at('11:00'), True)
        self.assertEqual(len(self.store.data['notifications']), 2)
        record_result(self.store, {'event': 'idle'}, at('11:02'), True)
        self.assertEqual(len(self.store.data['notifications']), 3)
        record_result(self.store, bad, at('11:04'), True)
        self.assertEqual(len(self.store.data['notifications']), 4)

    def test_notification_failures_persist_retry_and_dedupe_after_restart(self):
        enqueue(self.store, 'test', '消息', at('10:00'))
        failing = Mock(side_effect=Error('offline'))
        self.assertTrue(flush(self.store, at('10:00'), failing))
        with Store(self.path).locked() as reloaded:
            sender = Mock(return_value={'ts': '123.45'})
            flush(reloaded, at('10:01'), sender)
            sender.assert_not_called()
            flush(reloaded, at('10:02'), sender)
            self.assertEqual(sender.call_count, 1)
            enqueue(reloaded, 'test', '消息', at('10:04'))
            flush(reloaded, at('10:04'), sender)
            self.assertEqual(sender.call_count, 1)
            self.assertEqual(reloaded.data['notifications']['test']['attempts'], 1)

    def test_rate_limit_respected(self):
        enqueue(self.store, 'test', '消息', at('10:00'))
        flush(self.store, at('10:00'), Mock(side_effect=Error('429', data={'retryAfter': 600})))
        self.assertEqual(self.store.data['notifications']['test']['nextAttempt'], at('10:10').timestamp())

    def test_interrupted_booking_reconciles_without_writing(self):
        self.store.data['actions']['123'] = {'id': '123', 'phase': 'booking_requested', 'seatId': '456',
                                          'date': '2026-09-29', 'end': 1380}
        reconcile_actions(self.store, reservation(id='999'))
        self.assertEqual(self.store.data['actions']['123']['phase'], 'rebooked')
        record_result(self.store, {'event': 'idle'}, at('10:00'), True)
        self.assertEqual(len(self.store.data['notifications']), 1)

    def test_interrupted_release_never_automatically_replayed(self):
        self.store.data['actions']['123'] = {'id': '123', 'phase': 'release_requested'}
        reconcile_actions(self.store, None)
        self.assertEqual(self.store.data['actions']['123']['phase'], 'attention')
        record_result(self.store, {'event': 'idle'}, at('10:00'), True)
        self.assertIn('action:123:attention', self.store.data['notifications'])

    def test_health_check_detects_hung_daemon_without_monitor_lock(self):
        self.args.notify = 'slack'
        record_result(self.store, {'event': 'idle'}, at('10:00'), False)
        self.assertTrue(read_status(self.path, clock=lambda: at('10:02'))['healthy'])
        self.assertFalse(read_status(self.path, clock=lambda: at('10:07'))['fresh'])
        with self.store.locked(), patch('bnul.watch.flush', return_value=[]):
            result = health_check(self.args, self.path, clock=lambda: at('10:07'))
        self.assertFalse(result['fresh'])
        data = json.loads(Path(str(self.path) + '.health').read_text())
        self.assertEqual(len(data['notifications']), 1)

    def test_status_is_read_only_and_handles_missing_file(self):
        self.args.status = True
        with patch('bnul.watch.Client') as client:
            self.assertFalse(run_watch(self.args)['healthy'])
            client.assert_not_called()
        self.assertFalse(self.path.exists())


class NotificationTransportTests(unittest.TestCase):
    def test_existing_dotenv_credentials_and_explicit_environment_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text('BNUL_USERNAME=test\nBNUL_PASSWORD=secret\nUNRELATED=unused\n')
            with patch.dict(os.environ, {'BNUL_CREDENTIAL_ENV': str(path)}, clear=True):
                self.assertEqual(get_credentials(), {'username': 'test', 'password': 'secret'})
                self.assertNotIn('UNRELATED', os.environ)
                self.assertNotIn('secret', safe_error(Error('secret')))
                with patch.dict(os.environ, {'BNUL_USERNAME': 'override', 'BNUL_PASSWORD': 'override-pass'}):
                    self.assertEqual(get_credentials()['username'], 'override')
            with patch.dict(os.environ, {'BNUL_CREDENTIAL_ENV': str(path) + '-missing'}, clear=True):
                with self.assertRaises(Error):
                    get_credentials()

    def test_slack_success_requires_receipt_and_uses_configured_destination(self):
        response = Mock()
        response.__enter__ = Mock(return_value=io.StringIO('{"ok":true,"ts":"123.4","channel":"C123"}'))
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.dict(os.environ, {'SLACK_BOT_TOKEN': 'private', 'SLACK_HOME_CHANNEL': 'C123', 'SLACK_HOME_CHANNEL_THREAD_ID': '100.1'}, clear=True), patch('bnul.watch_notify.build_opener', return_value=opener):
            self.assertEqual(send_slack('测试')['ts'], '123.4')
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://slack.com/api/chat.postMessage')
            self.assertEqual(json.loads(request.data)['thread_ts'], '100.1')
            self.assertEqual(request.get_header('Authorization'), 'Bearer private')

    def test_slack_error_does_not_echo_token_or_payload(self):
        response = Mock()
        response.__enter__ = Mock(return_value=io.StringIO('{"ok":false,"error":"private secret"}'))
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.dict(os.environ, {'SLACK_BOT_TOKEN': 'private', 'SLACK_HOME_CHANNEL': 'C123'}, clear=True), patch('bnul.watch_notify.build_opener', return_value=opener):
            with self.assertRaises(Error) as caught:
                send_slack('test')
            self.assertNotIn('private', str(caught.exception))
