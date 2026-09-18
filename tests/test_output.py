import copy
import io
import json
import unittest
from unittest.mock import patch

from bnul.cli import main
from bnul.client import Error
from bnul.output import table, present


class OutputTests(unittest.TestCase):
    def invoke(self, argv, data=None, error=None):
        with patch('bnul.cli.run', return_value=data, side_effect=error) as run, \
                patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch('sys.stderr', new_callable=io.StringIO) as err:
            code = main(argv)
            run.assert_called_once()
            return code, out.getvalue(), err.getvalue()

    def test_seat_text_is_compact_and_json_preserves_all_fields(self):
        data = [{'id': str(100 + i), 'label': f'{i:03}', 'status': 'IN_USE',
                 'afterFree': True, 'extra': {'layout': list(range(100))}} for i in range(80)]
        original = copy.deepcopy(data)
        args = ['seats', '--start', '19:00', '--end', '20:00']
        code, text, _ = self.invoke(args, data)
        self.assertEqual(code, 0)
        self.assertIn('008 | 使用中 | 是 | 108', text)
        self.assertIn('079 | 使用中 | 是 | 179', text)
        self.assertEqual(len([line for line in text.splitlines() if line[:3].isdigit()]), 80)
        self.assertNotIn('--json', text)
        self.assertNotIn('layout', text)
        self.assertEqual(self.invoke(['--text'] + args, data)[1], text)
        raw = self.invoke(['--json'] + args, data)[1]
        self.assertEqual(json.loads(raw), {'ok': True, 'data': original})
        self.assertEqual(data, original)
        self.assertLess(len(text), len(raw) // 3)

    def test_recommendation_retains_scope_and_incomplete_search(self):
        data = {'date': '2026-09-16', 'start': 'now', 'end': '22:00',
                'scope': {'roomId': '123', 'roomOrder': ['123', '456'], 'strategy': 'priority'},
                'recommendations': [], 'checkedSeats': 50, 'candidateSeats': 900,
                'searchExhausted': False, 'stopReason': 'check_limit', 'submitted': False,
                'note': '未创建预约'}
        args = ['recommend', '--start', 'now', '--end', '22:00']
        text = self.invoke(args, data)[1]
        for expected in ['尚未查完', '达到检查上限', '50/900',
                         '房间ID: 123', '已检查的候选中未找到', '未创建预约']:
            self.assertIn(expected, text)
        self.assertEqual(json.loads(self.invoke(['--json'] + args, data)[1])['data'], data)

    def test_reservation_preview_status_message_and_ids(self):
        data = {'submitted': False, 'action': 'cancel', 'current': {
            'id': '1234567890123456789', 'status': 'RESERVE', 'message': '请于 15:00 前签到'}}
        text = self.invoke(['cancel'], data)[1]
        for expected in ['未提交', '1234567890123456789', '待签到', '15:00 前签到']:
            self.assertIn(expected, text)
        text = self.invoke(['cancel', '--execute', '--expect-id', '123'], 7)[1]
        self.assertIn('服务端结果：\n7', text)
        self.assertNotIn('积分', text)

    def test_empty_and_scalar_results(self):
        for data in [None, '', {}, []]:
            self.assertIn('没有当前预约', self.invoke(['current'], data)[1])
            self.assertIn('没有最近预约', self.invoke(['recent'], data)[1])
            self.assertEqual(json.loads(self.invoke(['--json', 'current'], data)[1])['data'], data)
        for data in [0, False, '服务端消息']:
            self.assertEqual(self.invoke(['current'], data)[0], 0)

    def test_times_uses_complete_readable_options_without_layout_metadata(self):
        data = {'starts': [['now', '现在'], ['1140', '19:00']], 'ends': [['1200', '20:00']],
                'timeline': {'freeList': [{'label': '19:00-20:00'}]},
                'futureField': {'a': {'b': {'c': {'d': 1}}}}}
        args = ['times', '--seat', '123']
        text = self.invoke(args, data)[1]
        for value in ['现在、19:00', '20:00', '19:00-20:00']:
            self.assertIn(value, text)
        for value in ['futureField', '--json', '1140', '1200']:
            self.assertNotIn(value, text)
        self.assertEqual(json.loads(self.invoke(['--json'] + args, data)[1])['data'], data)

    def test_all_history_records_and_long_messages_survive(self):
        data = {'list': [{'id': str(i), 'message': '重要消息' * 100, 'internal': 'x' * 1000}
                         for i in range(50)], 'count': 120}
        args = ['history', '--page', '2', '--page-size', '50']
        text = self.invoke(args, data)[1]
        self.assertIn('页码: 2', text)
        self.assertIn('总数: 120', text)
        self.assertIn('下一页: --page 3', text)
        self.assertEqual(text.count('重要消息' * 100), 50)
        self.assertIn('预约ID: 49', text)
        self.assertNotIn('internal', text)
        self.assertNotIn('已省略', text)
        self.assertEqual(json.loads(self.invoke(['--json'] + args, data)[1])['data'], data)

    def test_error_details_and_exit_status_in_both_modes(self):
        error = Error('已有有效预约', 500, {'ctId': '123', 'unknown': [1, 2, 3]})
        code, out, err = self.invoke(['current'], error=error)
        self.assertEqual((code, out), (1, ''))
        for value in ['已有有效预约', '500', '当前预约ID: 123']:
            self.assertIn(value, err)
        code, out, err = self.invoke(['--json', 'current'], error=error)
        self.assertEqual((code, err), (1, ''))
        self.assertEqual(json.loads(out), {'ok': False, 'error': str(error), 'code': 500,
                                         'data': error.data})

    def test_all_other_command_views(self):
        cases = [(['buildings'], {'buildings': [{'id': '123', 'name': '主馆'}]}),
                 (['rooms', '--start', '19:00', '--end', '20:00'], [{'id': '123', 'name': '自习室'}]),
                 (['room-list'], {'rooms': [{'id': '123', 'number': 4, 'name': '3F自习区'}]}),
                 (['rooms'], {'rooms': []}), (['life', '123'], [{'status': 'CHECK_IN'}]),
                 (['breach'], {'list': [], 'count': 0}),
                 (['book', '--seat', '123', '--start', 'now', '--end', '22:00'],
                  {'submitted': False, 'beginMinute': -1, 'endMinute': 1320}),
                 (['stop'], {'submitted': False}), (['auth', 'status'], {'authenticated': True}),
                 (['skill', 'install'], {'installed': '/tmp/example'})]
        for args, data in cases:
            with self.subTest(args=args):
                self.assertEqual(self.invoke(args, data)[0], 0)
                self.assertEqual(json.loads(self.invoke(['--json'] + args, data)[1])['data'], data)

    def test_reservation_business_fields_take_precedence_over_server_flags(self):
        data = {'id': '123', 'seatId': '456', 'roomId': '789', 'seatLabel': '008',
                'makeDateStr': '2026-09-15', 'makeBeginStr': '12:17', 'makeEndStr': '17:00',
                'makeBegin': 737, 'makeEnd': 1020, 'location': '主馆|3层|自习区',
                'status': 'RESERVE', 'isSign': 1, 'showCheckBtn': True,
                'message': '请在 12:38 至 12:47 之间完成签到', 'remark': '', 'actualStr': None,
                'username': 'test', 'fullName': 'test'}
        text = self.invoke(['current'], data)[1]
        for value in ['2026-09-15 12:17–17:00', '主馆 / 3层 / 自习区', '座位: 008',
                      '状态: 待签到', '预约ID: 123', '座位ID: 456', '房间ID: 789', data['message']]:
            self.assertIn(value, text)
        for value in ['isSign', 'showCheckBtn', 'username', 'fullName', '737', '1020', '备注', '实际使用', '--json']:
            self.assertNotIn(value, text)

    def test_buildings_retains_deep_floor_identity_and_dates(self):
        data = {'dates': ['2026-09-15', '2026-09-16'], 'buildings': [
            {'name': '主馆', 'id': '123', 'seTime': '07:00 _ 23:00', 'autoScale': 90,
             'floors': [{'name': f'{i}层', 'id': str(500 + i), 'properties': {}} for i in range(25)],
             'remark': ''}]}
        text = self.invoke(['buildings'], data)[1]
        for value in ['2026-09-16', '07:00–23:00', '楼层: 24层；ID: 524']:
            self.assertIn(value, text)
        for value in ['autoScale', 'properties', '备注', '--json']:
            self.assertNotIn(value, text)

    def test_room_facilities_keep_real_zeros(self):
        data = [{'id': '123', 'name': '3F自习区', 'seatTotal': 158, 'seatFree': 82,
                 'seatPower': 34, 'seatWindows': 0, 'seatComputer': 0, 'remark': '', 'layHv': 1}]
        text = self.invoke(['rooms', '--start', '19:00', '--end', '21:00'], data)[1]
        for value in ['电源', '靠窗', '电脑', '158 | 82 | 34 | 0 | 0']:
            self.assertIn(value, text)
        for value in ['备注', 'layHv', '--json']:
            self.assertNotIn(value, text)

    def test_empty_values_are_hidden_but_false_zero_and_unknown_errors_remain(self):
        error = Error('校验失败', 0, {'empty': '', 'null': None, 'list': [], 'map': {},
                                   'allowed': False, 'count': 0, 'future': {'detail': '完整错误'}})
        text = self.invoke(['current'], error=error)[2]
        for value in ['错误码: 0', 'allowed: 否', 'count: 0', '完整错误']:
            self.assertIn(value, text)
        for value in ['empty:', 'null:', 'list:', 'map:', '--json']:
            self.assertNotIn(value, text)

    def test_times_does_not_limit_start_options(self):
        data = {'starts': [[str(i * 30), f'{i // 2:02}:{i % 2 * 30:02}'] for i in range(48)], 'ends': []}
        text = self.invoke(['times', '--seat', '123'], data)[1]
        self.assertIn('23:30', text)
        self.assertIn('可选结束: 无', text)
        self.assertNotIn('未显示', text)

    def test_known_and_unknown_states_and_empty_seat_columns(self):
        data = [{'label': '008', 'name': '', 'status': 'NEW_STATE', 'afterFree': False, 'id': '123'}]
        text = self.invoke(['seats', '--start', '19:00', '--end', '21:00'], data)[1]
        self.assertIn('008 | NEW_STATE | 否 | 123', text)
        self.assertNotIn('位置', text)
        self.assertNotIn('空字符串', text)


class TableTests(unittest.TestCase):
    def test_empty_rows_returns_empty_string(self):
        columns = [('A', lambda r: r.get('a')), ('B', lambda r: r.get('b'))]
        self.assertEqual(table([], columns), '')

    def test_all_columns_empty_returns_empty_string(self):
        rows = [{'a': None, 'b': ''}, {'a': None, 'b': None}]
        columns = [('A', lambda r: r.get('a')), ('B', lambda r: r.get('b'))]
        self.assertEqual(table(rows, columns), '')

    def test_empty_columns_returns_empty_string(self):
        rows = [{'a': 1}]
        self.assertEqual(table(rows, []), '')

    def test_zero_and_false_columns_retained(self):
        rows = [{'a': 0, 'b': False, 'c': None}]
        columns = [('A', lambda r: r.get('a')), ('B', lambda r: r.get('b')), ('C', lambda r: r.get('c'))]
        result = table(rows, columns)
        self.assertIn('A | B', result)
        self.assertIn('0 | 否', result)
        self.assertNotIn('C', result)

    def test_mixed_present_columns(self):
        rows = [{'x': 'hello', 'y': None}, {'x': None, 'y': 'world'}]
        columns = [('X', lambda r: r.get('x')), ('Y', lambda r: r.get('y')), ('Z', lambda r: r.get('z'))]
        result = table(rows, columns)
        self.assertIn('X | Y', result)
        self.assertNotIn('Z', result)
        lines = result.strip().split('\n')
        self.assertEqual(len(lines), 3)


class PresentTests(unittest.TestCase):
    def test_present_rejects_empty_values(self):
        for value in [None, '', [], {}]:
            self.assertFalse(present(value))

    def test_present_accepts_zero_and_false(self):
        for value in [0, False, 'text', [1], {'a': 1}]:
            self.assertTrue(present(value))
