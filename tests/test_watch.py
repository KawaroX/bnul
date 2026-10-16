import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from bnul.client import Error, ROOM
from bnul.cli import main, parser
from bnul.watch import SHANGHAI, Store, away_deadline, away_policy, plan, run_watch, tick, timestamp


RULES = {'signEndMinute': 30, 'mackCaptcha': 0, 'agreements':
         '<p>暂离时间是30分钟。</p><p>用餐时段(中午11:30-13:30，下午16:30-18:30)不计入暂离时间</p>'}


def at(clock):
    return datetime.fromisoformat('2026-09-29T' + clock).replace(tzinfo=SHANGHAI)


def reservation(status='RESERVE', **changes):
    return dict({'id': '123', 'seatId': '456', 'roomId': ROOM, 'makeDateStr': '2026-09-29',
                 'makeBegin': 600, 'makeEnd': 1380, 'status': status, 'message': ''}, **changes)


class FakeClient:
    def __init__(self, rows, cancel=2):
        self.rows = iter(rows)
        self.system = RULES.copy()
        self.auth_recovered = False
        self.cancel = cancel
        self.calls = []
        self.book = Mock()
        self.check_booking_captcha = Mock()

    def bootstrap(self):
        return self.system

    def api(self, path):
        self.calls.append(path)
        if path == 'user/currentUseMake':
            result = next(self.rows)
            if isinstance(result, Exception):
                raise result
            return result
        if path.startswith('make/'):
            if isinstance(self.cancel, Exception):
                raise self.cancel
            return self.cancel
        if path == 'user/getUserInfo':
            return {}
        raise AssertionError(path)


class DeadlineTests(unittest.TestCase):
    def test_meal_examples_and_boundaries(self):
        duration, meals = away_policy(RULES)
        for start, expected in [('11:01', '13:31'), ('11:30', '14:00'), ('13:20', '14:00'),
                                ('16:30', '19:00'), ('18:20', '19:00'), ('18:30', '19:00'),
                                ('09:00', '09:30'), ('11:00', '11:30'), ('16:15', '18:45')]:
            with self.subTest(start=start):
                self.assertEqual(away_deadline(at(start), duration, meals), at(expected))

    def test_rule_change_fails_closed(self):
        for agreements in ['', '暂离30分钟', RULES['agreements'].replace('13:30', '10:30')]:
            with self.assertRaises(Error):
                away_policy({'agreements': agreements})

    def test_sign_deadline_and_specific_server_message(self):
        row = reservation()
        self.assertEqual(plan(row, RULES, at('10:26'))['remainingSeconds'], 240)
        row['message'] = '请在 10:15 至 10:32 之间完成签到'
        self.assertEqual(plan(row, RULES, at('10:26'))['remainingSeconds'], 360)

    def test_away_timestamp_and_meal_policy(self):
        for raw in ['2026-09-29 11:01:00', '11:01:00', str(int(at('11:01').timestamp() * 1000)),
                    str(int(at('11:01').timestamp())), at('11:01').isoformat()]:
            row = reservation('AWAY', awayTime=raw)
            self.assertEqual(plan(row, RULES, at('13:27'))['remainingSeconds'], 240)
        for value in ['', '30', '1790', 'garbage']:
            with self.assertRaises(Error):
                timestamp(value, '2026-09-29')

    def test_unknown_or_inconsistent_away_time_never_guessed(self):
        for raw in ['', '2026-09-28 10:00:00', '2026-09-29 10:28:00', '2026-09-29 09:00:00']:
            with self.assertRaises(Error):
                plan(reservation('AWAY', awayTime=raw), RULES, at('10:26'))

    def test_natural_end_and_other_states(self):
        self.assertIsNone(plan(reservation('AWAY', awayTime='10:10', makeEnd=630), RULES, at('10:26')))
        for state in ['CHECK_IN', 'STOP', 'UNKNOWN']:
            self.assertIsNone(plan(reservation(state), RULES, at('10:26')))
        self.assertIsNone(plan(reservation(makeDateStr='2026-09-30'), RULES, at('10:26')))
        with self.assertRaises(Error):
            plan(reservation(roomId='unknown'), RULES, at('10:26'))


@unittest.skipIf(os.name == 'nt', 'watch daemon requires POSIX file locks')
class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state.json')

    def tick(self, c, **kwargs):
        return tick(c, self.store, clock=lambda: at('10:26'), **kwargs)

    def test_preview_and_threshold_do_not_write(self):
        c = FakeClient([reservation()])
        self.assertEqual(self.tick(c)['event'], 'would_rebook')
        self.assertEqual(c.calls, ['user/currentUseMake'])
        self.assertFalse(self.store.data['actions'])
        for clock in ['10:25', '10:24', '10:30', '10:31']:
            c = FakeClient([reservation()])
            self.assertEqual(tick(c, self.store, True, clock=lambda: at(clock))['event'],
                             'missed_deadline' if clock >= '10:30' else 'observing')
            c.book.assert_not_called()

    def test_cancel_rebook_preserves_seat_end_and_uses_now(self):
        c = FakeClient([reservation(), reservation(), '', reservation(id='999', makeBegin=626)])
        result = self.tick(c, execute=True)
        self.assertEqual(result['event'], 'rebooked')
        self.assertEqual(result['newId'], '999')
        c.book.assert_called_once_with('456', '2026-09-29', -1, 1380)
        self.assertEqual(c.calls.count('make/cancel/123'), 1)
        self.assertEqual(self.store.data['attempts']['2026-09-29'], 1)

    def test_stop_rebook_only_away(self):
        row = reservation('AWAY', awayTime='10:00')
        c = FakeClient([row, row, '', reservation(id='999')])
        self.assertEqual(self.tick(c, execute=True)['event'], 'rebooked')
        self.assertIn('make/stop', c.calls)
        for status in ['CHECK_IN', 'STOP']:
            c = FakeClient([reservation(status)])
            self.assertEqual(self.tick(c, execute=True)['event'], 'observing')
            c.book.assert_not_called()

    def test_changed_id_status_seat_end_deadline_aborts(self):
        for changes in [dict(id='999'), dict(status='CHECK_IN'), dict(seatId='777'),
                        dict(makeEnd=1320), dict(makeBegin=601)]:
            c = FakeClient([reservation(), reservation(**changes)])
            self.assertEqual(self.tick(c, execute=True)['event'], 'changed_before_release')
            self.assertFalse(any(p.startswith('make/') for p in c.calls))

    def test_captcha_detected_before_release(self):
        c = FakeClient([reservation()])
        c.check_booking_captcha.side_effect = Error('captcha needed')
        with self.assertRaises(Error):
            self.tick(c, execute=True)
        self.assertFalse(self.store.data['actions'])
        self.assertFalse(any(p.startswith('make/') for p in c.calls))

    def test_no_rebook_when_cancel_quota_zero_or_unknown(self):
        for response in [0, None, '', True, -1, '2']:
            self.store.data['actions'] = {}
            c = FakeClient([reservation(), reservation(), ''], cancel=response)
            self.assertEqual(self.tick(c, execute=True)['event'], 'released_without_rebooking')
            c.book.assert_not_called()

    def test_daily_limit_still_releases_without_rebooking(self):
        self.store.data['attempts']['2026-09-29'] = 3
        c = FakeClient([reservation(), reservation(), ''])
        result = self.tick(c, execute=True)
        self.assertEqual(result['event'], 'released_without_rebooking')
        self.assertEqual(result['reason'], 'daily_renewal_limit')
        c.book.assert_not_called()
        c.check_booking_captcha.assert_not_called()

    def test_release_uncertain_queries_but_never_replays(self):
        c = FakeClient([reservation(), reservation(), ''], cancel=Error('timeout'))
        self.assertEqual(self.tick(c, execute=True)['event'], 'attention')
        self.assertEqual(c.calls.count('make/cancel/123'), 1)
        c.book.assert_not_called()
        reloaded = Store(self.store.path)
        with reloaded.locked():
            c = FakeClient([reservation()])
            result = tick(c, reloaded, True, clock=lambda: at('10:27'))
            self.assertEqual(result['event'], 'already_handled')
            self.assertEqual(c.calls, ['user/currentUseMake'])

    def test_release_not_confirmed_does_not_book(self):
        for after in [reservation(), reservation(id='999')]:
            self.store.data['actions'] = {}
            c = FakeClient([reservation(), reservation(), after])
            self.assertIn(self.tick(c, execute=True)['event'], ['attention', 'reservation_changed'])
            c.book.assert_not_called()

    def test_booking_timeout_never_replayed(self):
        c = FakeClient([reservation(), reservation(), '', reservation(id='999')])
        c.book.side_effect = Error('timeout')
        self.assertEqual(self.tick(c, execute=True)['event'], 'attention')
        c.book.assert_called_once()
        self.assertEqual(self.store.data['actions']['123']['observedId'], '999')

    def test_journal_saved_before_each_mutation(self):
        c = FakeClient([reservation(), reservation(), '', reservation(id='999')])
        original = c.api
        def api(path):
            if path.startswith('make/'):
                persisted = json.loads(self.store.path.read_text())
                self.assertEqual(persisted['actions']['123']['phase'], 'release_requested')
            return original(path)
        c.api = api
        def booked(*args):
            persisted = json.loads(self.store.path.read_text())
            self.assertEqual(persisted['actions']['123']['phase'], 'booking_requested')
        c.book.side_effect = booked
        self.assertEqual(self.tick(c, execute=True)['event'], 'rebooked')
        self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)

    def test_crash_before_release_not_replayed(self):
        self.store.data['actions']['123'] = {'phase': 'release_requested'}
        c = FakeClient([reservation()])
        self.assertEqual(self.tick(c, execute=True)['event'], 'already_handled')
        self.assertEqual(c.calls, ['user/currentUseMake'])

    def test_invalid_current_does_not_mean_no_reservation(self):
        for row in [{}, [], 'unexpected']:
            with self.assertRaises(Error):
                self.tick(FakeClient([row]), execute=True)

    def test_store_lock_and_corruption(self):
        with self.store.locked():
            with self.assertRaises(Error):
                with Store(self.store.path).locked():
                    pass
        self.store.path.write_text('{}')
        with self.assertRaises(Error):
            with Store(self.store.path).locked():
                pass

    def test_cli_once_and_default_interval(self):
        args = parser().parse_args(['watch'])
        self.assertEqual(args.interval, 120)
        self.assertFalse(args.execute)
        c = FakeClient([reservation()])
        with patch('bnul.watch.Client', return_value=c), patch('bnul.watch.now_local', return_value=at('10:26')), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(main(['--json', 'watch', '--once', '--state-file', str(self.store.path)]), 0)
            self.assertTrue(json.loads(out.getvalue())['ok'])
        for options in [['--interval', '300'], ['--interval', '0'], ['--max-renewals', '4']]:
            with self.assertRaises(Error):
                run_watch(parser().parse_args(['watch'] + options))

    def test_once_errors_use_failure_exit_code(self):
        with patch('bnul.watch.now_local', return_value=at('10:26')), patch('bnul.watch.tick', side_effect=Error('unknown', 'DEADLINE_UNKNOWN')), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(main(['--json', 'watch', '--once', '--state-file', str(self.store.path)]), 1)
            self.assertFalse(json.loads(out.getvalue())['ok'])


if __name__ == '__main__':
    unittest.main()
