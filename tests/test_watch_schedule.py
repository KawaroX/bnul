import io
import json
import os
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from bnul.cli import parser
from bnul.client import Error
from bnul.watch import (Client, Store, check_cycle, deliver_notifications, health_check,
                        read_status, record_result, run_watch)
from bnul.watch_notify import enqueue, flush
from bnul.watch_schedule import active, interval_for, next_open, schedule_for
from test_watch import at, FakeClient


class ScheduleTests(unittest.TestCase):
    def test_beijing_window_including_exact_boundaries(self):
        for hour, expected in [('00:00', False), ('05:00', False), ('07:59:59', False),
                               ('08:00', True), ('22:59:59', True), ('23:00', False)]:
            with self.subTest(hour=hour):
                self.assertEqual(active(at(hour)), expected)
                self.assertEqual(active(at(hour).astimezone(timezone.utc)), expected)
        self.assertEqual(next_open(at('07:59')), at('08:00'))
        self.assertEqual(next_open(at('23:00')), at('08:00') + timedelta(days=1))

    def test_intervals_and_ten_minute_boundary(self):
        for result, expected in [({'event': 'idle'}, 1800),
                ({'event': 'observing', 'status': 'CHECK_IN'}, 1200),
                ({'event': 'observing', 'status': 'RESERVE'}, 120),
                ({'event': 'observing', 'status': 'AWAY', 'remainingSeconds': 601}, 420),
                ({'event': 'observing', 'status': 'AWAY', 'remainingSeconds': 600}, 120),
                ({'event': 'observing', 'status': 'AWAY', 'remainingSeconds': 599}, 120),
                ({'event': 'observing', 'status': 'AWAY'}, 120),
                ({'event': 'observing', 'status': 'UNKNOWN'}, 120),
                ({'event': 'error'}, 120), ({'event': 'attention'}, 120),
                ({'event': 'rebooked', 'status': 'AWAY', 'remainingSeconds': 900}, 120)]:
            with self.subTest(result=result):
                self.assertEqual(interval_for(result), expected)

    def test_cycle_time_and_close_clip_next_query(self):
        result = {'event': 'idle'}
        self.assertEqual(schedule_for(result, at('10:00'), at('10:01'))['nextCheckAt'], at('10:30').isoformat())
        self.assertEqual(schedule_for(result, at('22:50'), at('22:51'))['nextCheckAt'], at('23:00').isoformat())
        result = schedule_for(result, at('22:59'), at('23:01'))
        self.assertEqual(result['mode'], 'sleeping')
        self.assertEqual(result['nextCheckAt'], (at('08:00') + timedelta(days=1)).isoformat())

    def test_network_and_login_guards_after_close(self):
        with patch('bnul.watch.now_local', return_value=at('23:00')), patch('bnul.watch.BaseClient.__init__') as init:
            with self.assertRaises(Error) as error:
                Client()
            self.assertEqual(error.exception.code, 'WATCH_SLEEPING')
            init.assert_not_called()
        client = object.__new__(Client)
        for method in ('request', 'recover_auth'):
            with patch('bnul.watch.now_local', return_value=at('23:00')), patch('bnul.watch.BaseClient.' + method) as base:
                with self.assertRaises(Error):
                    getattr(client, method)(*(['/static/test'] if method == 'request' else []))
                base.assert_not_called()


@unittest.skipIf(os.name == 'nt', 'POSIX daemon')
class DaemonScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'watch.json'
        self.store = Store(self.path)
        self.args = parser().parse_args(['watch', '--state-file', str(self.path), '--notify', 'slack'])

    def test_night_skips_client_and_keeps_auth_backoff_unchanged(self):
        self.store.data['auth'] = {'failures': 1, 'retryAt': at('05:00').timestamp()}
        factory = Mock()
        result = check_cycle(self.args, self.store, lambda: at('05:30'), factory)
        self.assertEqual(result['event'], 'sleeping')
        factory.assert_not_called()
        self.assertEqual(self.store.data['auth']['failures'], 1)

    def test_closing_mid_cycle_does_not_start_login_backoff_or_alarm(self):
        with patch('bnul.watch.tick', side_effect=Error('休眠', 'WATCH_SLEEPING')):
            result = check_cycle(self.args, self.store, lambda: at('22:59:59'), lambda **kw: FakeClient([]))
        self.assertEqual(result['event'], 'sleeping')
        self.assertEqual(self.store.data['auth'], {})
        self.assertNotIn('notifications', self.store.data)

    def test_first_start_at_night_has_heartbeat_without_fake_successful_query(self):
        self.args.once = True
        with patch('bnul.watch.now_local', return_value=at('05:00')), patch('bnul.watch.Client') as client:
            self.assertEqual(run_watch(self.args)['event'], 'sleeping')
        status = read_status(self.path, clock=lambda: at('05:01'))
        self.assertTrue(status['fresh'])
        self.assertEqual(status['lastCheck'], {})
        self.assertNotIn('lastSuccess', status['health'])
        client.assert_not_called()

    def test_once_night_preserves_last_check_and_pending_notifications(self):
        record_result(self.store, {'event': 'error', 'code': 'NETWORK'}, at('22:58'), True)
        before = json.loads(self.path.read_text())
        self.args.once = True
        with patch('bnul.watch.now_local', return_value=at('23:00')), patch('bnul.watch.Client') as client, patch('bnul.watch.flush') as send:
            result = run_watch(self.args)
        after = json.loads(self.path.read_text())
        self.assertEqual(result['event'], 'sleeping')
        for key in ('lastCheck', 'health', 'notifications'):
            self.assertEqual(before[key], after[key])
        client.assert_not_called()
        send.assert_not_called()
        status = read_status(self.path, clock=lambda: at('23:00'))
        self.assertTrue(status['sleeping'])
        self.assertTrue(status['fresh'])
        self.assertEqual(status['health']['status'], 'degraded')

    def test_night_health_check_missing_or_stale_state_never_alerts_or_flushes(self):
        for exists in (False, True):
            if exists:
                record_result(self.store, {'event': 'idle'}, at('10:00'), False)
            with patch('bnul.watch.flush') as send:
                result = health_check(self.args, self.path, lambda: at('05:00'))
                self.assertEqual(result['event'], 'sleeping')
                send.assert_not_called()
                self.assertFalse(Path(str(self.path) + '.health').exists())

    def test_no_failure_queue_or_manual_test_notice_at_night(self):
        record_result(self.store, {'event': 'error', 'code': 'NETWORK'}, at('23:00'), True)
        self.assertNotIn('notifications', self.store.data)
        self.args.notify_test = True
        with patch('bnul.watch.now_local', return_value=at('23:00')), patch('bnul.watch.send_slack') as send:
            self.assertFalse(run_watch(self.args)['sent'])
            send.assert_not_called()

    def test_delivery_rechecks_close_between_pending_messages(self):
        enqueue(self.store, 'one', 'one', at('22:59'))
        enqueue(self.store, 'two', 'two', at('22:59'))
        times = iter([at('22:59:59'), at('22:59:59'), at('23:00')])
        sender = Mock(return_value={'ts': '123'})
        with patch('bnul.watch.flush', side_effect=lambda store, now, **kw: flush(store, now, sender, **kw)):
            deliver_notifications(self.store, lambda: next(times))
        sender.assert_called_once_with('one')
        self.assertEqual(self.store.data['notifications']['two']['attempts'], 0)
        self.assertNotIn('deliveredAt', self.store.data['notifications']['two'])

    def test_long_query_interval_has_fresh_heartbeat_but_hung_process_is_detected(self):
        record_result(self.store, {'event': 'idle'}, at('10:00'), False)
        self.store.data['heartbeatAt'] = at('10:25').isoformat()
        self.store.save()
        status = read_status(self.path, clock=lambda: at('10:26'))
        self.assertTrue(status['healthy'])
        self.assertEqual(status['lastQueryAgeSeconds'], 1560)
        with patch('bnul.watch.flush', return_value=[]):
            self.assertTrue(health_check(self.args, self.path, lambda: at('10:26'))['fresh'])
            self.assertFalse(health_check(self.args, self.path, lambda: at('10:32'))['fresh'])
        data = json.loads(Path(str(self.path) + '.health').read_text())
        self.assertEqual(len(data['notifications']), 1)

    def run_with_clock(self, start, end, events):
        current, queries = [start], []
        def tick(*args):
            queries.append(current[0])
            return next(events)
        def advance(seconds):
            self.assertGreater(seconds, 0)
            self.assertLessEqual(seconds, 60)
            current[0] += timedelta(seconds=seconds)
            if current[0] >= end:
                raise KeyboardInterrupt()
        with patch('bnul.watch.Client', return_value=FakeClient([])), patch('bnul.watch.tick', side_effect=tick), patch('bnul.watch.now_local', side_effect=lambda: current[0]), patch('bnul.watch.time.sleep', side_effect=advance), patch('bnul.watch.flush', return_value=[]) as send, patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaises(KeyboardInterrupt):
                run_watch(self.args)
        self.assertTrue(all(active(call.args[1]) for call in send.call_args_list))
        return queries

    def test_daemon_adapts_to_observed_states(self):
        events = iter([{'event': 'idle'}, {'event': 'observing', 'status': 'CHECK_IN'},
                       {'event': 'observing', 'status': 'AWAY', 'remainingSeconds': 900},
                       {'event': 'observing', 'status': 'AWAY', 'remainingSeconds': 480},
                       {'event': 'observing', 'status': 'RESERVE'}])
        queries = self.run_with_clock(at('09:00'), at('10:01'), events)
        self.assertEqual(queries, [at(t) for t in ('09:00', '09:30', '09:50', '09:57', '09:59')])

    def test_daemon_sleeps_across_midnight_and_queries_at_eight(self):
        events = iter([{'event': 'observing', 'status': 'CHECK_IN'}, {'event': 'idle'}])
        tomorrow = at('08:00') + timedelta(days=1)
        queries = self.run_with_clock(at('22:50'), tomorrow + timedelta(minutes=1), events)
        self.assertEqual(queries, [at('22:50'), tomorrow])
        data = json.loads(self.path.read_text())
        self.assertEqual(data['health']['checkCount'], 2)
        self.assertEqual(data['schedule']['nextCheckAt'], (tomorrow + timedelta(minutes=30)).isoformat())
