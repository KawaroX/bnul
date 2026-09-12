import io
import json
import unittest
from unittest.mock import patch, call
from bnul.cli import main
from bnul.client import Client, Error


class ReservationTests(unittest.TestCase):
    def invoke(self, argv, current, result=7):
        with patch('bnul.cli.Client') as cls, patch('sys.stdout', new_callable=io.StringIO) as out:
            c = cls.return_value
            c.api.side_effect = [current, result]
            code = main(['--json'] + argv)
            return code, json.loads(out.getvalue()), c.api.call_args_list

    def test_cancel_preview(self):
        code, data, calls = self.invoke(['cancel'], {'id': '123', 'status': 'RESERVE'})
        self.assertEqual(code, 0)
        self.assertFalse(data['data']['submitted'])
        self.assertEqual(data['data']['action'], 'cancel')
        self.assertEqual(calls, [call('user/currentUseMake')])

    def test_cancel_exact_id_and_raw_response(self):
        code, data, calls = self.invoke(['cancel', '--execute', '--expect-id', '123'], {'id': '123', 'status': 'RESERVE'})
        self.assertEqual(code, 0)
        self.assertEqual(data['data'], 7)
        self.assertEqual(calls, [call('user/currentUseMake'), call('make/cancel/123')])

    def test_no_current(self):
        for current in ('', None, {}, []):
            code, data, calls = self.invoke(['cancel', '--execute', '--expect-id', '123'], current)
            self.assertEqual(code, 1)
            self.assertEqual(data['code'], 'NO_CURRENT_RESERVATION')
            self.assertEqual(len(calls), 1)

    def test_missing_or_changed_id(self):
        for extra in ([], ['--expect-id', '456']):
            code, data, calls = self.invoke(['cancel', '--execute'] + extra, {'id': '123', 'status': 'RESERVE'})
            self.assertEqual(code, 1)
            self.assertEqual(data['code'], 'RESERVATION_CHANGED')
            self.assertEqual(len(calls), 1)

    def test_states_and_routing(self):
        for command, status, hint in [('cancel', 'CHECK_IN', 'stop'), ('cancel', 'AWAY', 'stop'), ('stop', 'RESERVE', 'cancel'), ('cancel', 'STOP', None), ('stop', 'UNKNOWN', None)]:
            code, data, calls = self.invoke([command, '--execute', '--expect-id', '123'], {'id': '123', 'status': status})
            self.assertEqual(code, 1)
            self.assertEqual(data['code'], 'INVALID_RESERVATION_STATE')
            if hint:
                self.assertIn(hint, data['error'])
            self.assertEqual(len(calls), 1)
        for status in ('CHECK_IN', 'AWAY'):
            code, _, calls = self.invoke(['stop', '--execute', '--expect-id', '123'], {'id': '123', 'status': status})
            self.assertEqual(code, 0)
            self.assertEqual(calls[-1], call('make/stop'))

    def test_cancel_error_preserved(self):
        code, data, calls = self.invoke(['cancel', '--execute', '--expect-id', '123'], {'id': '123', 'status': 'RESERVE'}, Error('取消时间限制', 500))
        self.assertEqual(code, 1)
        self.assertEqual(data['error'], '取消时间限制')
        self.assertEqual(len(calls), 2)

    def test_uncertain_cancel_not_replayed(self):
        c = Client('test')
        with patch.object(c, 'request', side_effect=Error('network unknown')) as request:
            with self.assertRaises(Error):
                c.api('make/cancel/123')
            request.assert_called_once()

    def test_paginated_queries(self):
        for command in ('history', 'breach'):
            with patch('bnul.cli.Client') as cls, patch('sys.stdout', new_callable=io.StringIO) as out:
                response = {'list': [{'id': '123'}], 'count': 21}
                cls.return_value.api.return_value = response
                self.assertEqual(main(['--json', command, '--page', '2', '--page-size', '20']), 0)
                cls.return_value.api.assert_called_once_with(f'user/{command}/2/20')
                self.assertEqual(json.loads(out.getvalue())['data'], response)
            for args in (['--page', '0'], ['--page-size', '101'], ['--page-size', '0']):
                with patch('bnul.cli.Client') as cls, patch('sys.stdout', new_callable=io.StringIO):
                    self.assertEqual(main(['--json', command] + args), 1)
                    cls.assert_not_called()
