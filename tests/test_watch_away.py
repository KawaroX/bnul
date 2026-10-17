import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from bnul.cli import parser
from bnul.client import Error
from bnul.watch import (SHANGHAI, Store, away_start, check_cycle, failure_notice, observation,
                        plan, read_status, record_result, tick)
from bnul.watch_schedule import interval_for
from test_watch import RULES, FakeClient, at, reservation

SAMPLES = json.loads((Path(__file__).parent / 'fixtures' / 'away_seconds.json').read_text())['samples']


def replay(sample, **changes):
    return reservation('AWAY', makeDateStr=sample['date'], makeBegin=sample['begin'], makeEnd=sample['end'],
                       awayTime=sample['awayTime'], awayTimeM=sample['awayTimeM'], awayRange=sample['awayRange'], **changes)


class AwayEvidenceTests(unittest.TestCase):
    def test_real_second_minute_and_display_fields_agree(self):
        for sample in SAMPLES:
            with self.subTest(sample=sample['date']):
                row = replay(sample)
                start, source = away_start(row, sample['date'])
                expected = datetime.fromisoformat(sample['date']).replace(tzinfo=SHANGHAI) + timedelta(seconds=sample['awayTime'])
                self.assertEqual(start, expected)
                self.assertEqual(start.strftime('%H:%M'), sample['awayRange'])
                self.assertEqual(source, 'awayTime-seconds-since-midnight')
                if sample.get('lifeAwayAt'):
                    self.assertEqual(start, datetime.fromisoformat(sample['lifeAwayAt']).replace(tzinfo=SHANGHAI))

    def test_real_october_case_natural_end_precedes_away_expiry(self):
        row = replay(SAMPLES[0])
        now = datetime(2026, 10, 17, 22, 48, 37, tzinfo=SHANGHAI)
        result = plan(row, RULES, now)
        self.assertEqual(result['awayStartedAt'], '2026-10-17T22:39:38+08:00')
        self.assertEqual(result['deadline'], '2026-10-17T23:09:38+08:00')
        self.assertEqual(result['naturalEndAt'], '2026-10-17T23:00:00+08:00')
        self.assertFalse(result['actionRequired'])
        self.assertEqual(result['remainingSeconds'], 1261)
        self.assertEqual(interval_for({'event': 'observing', **result}), 420)

    def test_seconds_formats_and_day_boundaries(self):
        for raw in (81578, '81578', ' 81578 '):
            row = replay(SAMPLES[0]); row['awayTime'] = raw
            self.assertEqual(away_start(row, SAMPLES[0]['date'])[0].second, 38)
        for raw, expected in [(0, '00:00:00'), (86399, '23:59:59')]:
            result, _ = away_start({'awayTime': raw}, '2026-09-29')
            self.assertEqual(result.strftime('%H:%M:%S'), expected)

    def test_invalid_or_conflicting_units_fail_closed(self):
        for raw in (-1, 86400, 999999, 81578.5, True, False, None, '', {}, [], '22:99', '2026-99-99 22:39'):
            row = replay(SAMPLES[0]); row['awayTime'] = raw
            with self.subTest(raw=raw), self.assertRaises(Error) as caught:
                away_start(row, SAMPLES[0]['date'])
            self.assertEqual(caught.exception.code, 'DEADLINE_UNKNOWN')
        for key, value in [('awayTimeM', 81578), ('awayTimeM', 1358), ('awayTimeM', True),
                           ('awayTimeM', 1359.5), ('awayRange', '22:38'), ('awayRange', '22:39-23:00')]:
            row = replay(SAMPLES[0]); row[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(Error):
                away_start(row, SAMPLES[0]['date'])

    def test_seconds_with_meal_exemption_preserve_subminute_precision(self):
        row = reservation('AWAY', awayTime=11*3600+60+38, awayTimeM=661, awayRange='11:01')
        result = plan(row, RULES, at('13:27'))
        self.assertEqual(result['deadline'], at('13:31:38').isoformat())
        self.assertEqual(result['remainingSeconds'], 278)

    def test_future_or_pre_booking_seconds_are_rejected(self):
        for seconds in (9*3600, 11*3600):
            with self.assertRaises(Error):
                plan(reservation('AWAY', awayTime=seconds), RULES, at('10:26'))

    def test_observation_is_bounded_and_excludes_account_fields(self):
        row = reservation('AWAY', awayTime={'unknown': 'private'}, awayRange='x'*1000,
                          token='private', username='private', fullName='private', hmacKey='private')
        result = observation(row, at('10:00'))['reservation']
        self.assertEqual(result['awayTime'], {'type': 'dict'})
        self.assertEqual(len(result['awayRange']), 120)
        for field in ('token', 'username', 'fullName', 'hmacKey', 'seatId'):
            self.assertNotIn(field, result)

    def test_notices_only_mention_login_for_auth_failures(self):
        for result in [dict(event='error', code='DEADLINE_UNKNOWN'), dict(event='error', code='NETWORK'),
                       dict(event='missed_deadline'), dict(event='error', code='WATCH_HEARTBEAT_STALE')]:
            with self.subTest(result=result):
                self.assertNotIn('登录', ''.join(failure_notice(result)))
                self.assertNotIn('退避', ''.join(failure_notice(result)))
        title, detail = failure_notice({'code': 'AUTH_INTERACTION_REQUIRED', 'loginDeferredUntil': at('10:30').timestamp()})
        self.assertIn('登录', title)
        self.assertIn('10:30:00+08:00', detail)


@unittest.skipIf(os.name == 'nt', 'POSIX daemon')
class AwayExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'watch.json')
        self.args = parser().parse_args(['watch', '--state-file', str(self.store.path)])

    def test_replay_real_natural_expiry_never_stops_or_books(self):
        row = replay(SAMPLES[0])
        c = FakeClient([row])
        now = datetime(2026, 10, 17, 22, 58, 5, tzinfo=SHANGHAI)
        result = tick(c, self.store, execute=True, clock=lambda: now)
        self.assertEqual(result['event'], 'observing')
        self.assertEqual(result['reason'], 'reservation_ends_before_away_deadline')
        self.assertEqual(c.calls, ['user/currentUseMake'])
        c.book.assert_not_called()
        self.assertFalse(self.store.data['actions'])
        self.assertEqual(self.store.data['lastObservation']['reservation']['awayTime'], 81578)

    def test_real_seconds_trigger_guarded_stop_rebook_only_in_window(self):
        row = replay(SAMPLES[1])
        after = {**row, 'id': '999', 'status': 'RESERVE', 'awayTime': ''}
        c = FakeClient([row, row, '', after])
        result = tick(c, self.store, execute=True, clock=lambda: at('22:30:35'))
        self.assertEqual(result['event'], 'rebooked')
        self.assertEqual(c.calls.count('make/stop'), 1)
        c.book.assert_called_once_with('456', '2026-09-29', -1, 1380)
        c = FakeClient([row])
        result = tick(c, Store(Path(self.tmp.name) / 'boundary.json'), execute=True, clock=lambda: at('22:29:35'))
        self.assertEqual(result['event'], 'observing')
        c.book.assert_not_called()
        self.assertNotIn('make/stop', c.calls)

    def test_live_loop_selects_seven_then_two_minute_intervals(self):
        row = replay(SAMPLES[1])
        for clock, expected in [('22:20:00', 420), ('22:25:00', 120)]:
            result = tick(FakeClient([row]), self.store, clock=lambda: at(clock))
            self.assertEqual(interval_for(result), expected)

    def test_invalid_away_after_successful_login_keeps_diagnostics_without_auth_backoff(self):
        row = reservation('AWAY', awayTime=81578, awayTimeM=1)
        c = FakeClient([row]); c.auth_recovered = True
        result = check_cycle(self.args, self.store, lambda: at('22:50'), lambda **kw: c)
        self.assertEqual(result['code'], 'DEADLINE_UNKNOWN')
        self.assertTrue(result['loginRecovered'])
        self.assertNotIn('loginDeferredUntil', result)
        self.assertEqual(self.store.data['auth'], {})
        self.assertEqual(result['observation']['reservation']['awayTime'], 81578)
        self.assertEqual(result['status'], 'AWAY')
        self.assertEqual(json.loads(self.store.path.read_text())['lastObservation'], result['observation'])
        record_result(self.store, result, at('22:50'), True)
        notice = next(iter(self.store.data['notifications'].values()))['text']
        self.assertIn('期限无法确认', notice)
        self.assertNotIn('登录', notice)
        self.assertNotIn('退避', notice)
        self.assertEqual(c.calls, ['user/currentUseMake'])
        c.book.assert_not_called()

    def test_sleep_does_not_hide_unresolved_deadline_failure(self):
        record_result(self.store, {'event': 'error', 'code': 'DEADLINE_UNKNOWN'}, at('22:58'), False)
        self.store.data['heartbeatAt'] = at('23:01').isoformat(); self.store.save()
        status = read_status(self.store.path, clock=lambda: at('23:01'))
        self.assertTrue(status['sleeping'])
        self.assertTrue(status['fresh'])
        self.assertFalse(status['healthy'])
        self.assertEqual(status['health']['status'], 'degraded')
