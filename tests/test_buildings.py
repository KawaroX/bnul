import copy
import unittest
from unittest.mock import Mock, patch

from bnul.buildings import building_catalog, building_selector, resolve_building
from bnul.cli import parser, run
from bnul.client import BUILDING, ROOM, Error


SOUTH = '1864245010251223040'
EDUCATION = '1887389250929922048'
SHAHE = '2067149686880440320'
SOUTH_ROOM = '1891371692804116480'
SEAT = '9876543210987654321'
DATE = '2999-01-01'


def live_catalog():
    return {
        'dates': [DATE], 'extra': {'preserved': True},
        'buildings': [
            {'id': BUILDING, 'name': '主馆', 'enabled': True,
             'floors': [{'id': '123456789012', 'name': '3层', 'enabled': True}]},
            {'id': SOUTH, 'name': '主馆南区', 'enabled': 1, 'floors': []},
            {'id': EDUCATION, 'name': '教育学分馆', 'enabled': True, 'floors': []},
            {'id': SHAHE, 'name': '沙河', 'enabled': True, 'floors': []},
        ],
    }


class BuildingTests(unittest.TestCase):
    def catalog(self, data=None):
        client = Mock()
        client.api.return_value = data if data is not None else live_catalog()
        return building_catalog(client)

    def test_catalog_preserves_response_without_mutation(self):
        source = live_catalog()
        original = copy.deepcopy(source)
        catalog = self.catalog(source)
        self.assertEqual(source, original)
        self.assertIsNot(catalog, source)
        self.assertEqual(catalog['dates'], source['dates'])
        self.assertEqual(catalog['extra'], source['extra'])
        for before, after in zip(source['buildings'], catalog['buildings']):
            self.assertIsNot(before, after)
            self.assertEqual({key: after[key] for key in before if key != 'floors'},
                             {key: before[key] for key in before if key != 'floors'})
            self.assertEqual(len(after['floors']), len(before['floors']))
            for old_floor, new_floor in zip(before['floors'], after['floors']):
                self.assertIsNot(old_floor, new_floor)
                self.assertEqual({key: new_floor[key] for key in old_floor}, old_floor)
        self.assertEqual([row['number'] for row in catalog['buildings']], [1, 2, 3, 4])
        self.assertEqual([row['alias'] for row in catalog['buildings']], ['b1', 'b2', 'b3', 'b4'])

    def test_fixed_numbers_survive_reordering_and_removal(self):
        source = live_catalog()
        source['buildings'].reverse()
        catalog = self.catalog(source)
        for selector, expected in [('1', BUILDING), ('2', SOUTH), ('3', EDUCATION), ('4', SHAHE)]:
            self.assertEqual(resolve_building(selector, catalog), expected)
        source['buildings'] = [row for row in source['buildings'] if row['id'] != SOUTH]
        catalog = self.catalog(source)
        self.assertEqual(resolve_building('b3', catalog), EDUCATION)
        for selector in ('2', 'b2', '南区'):
            with self.subTest(selector=selector), self.assertRaises(Error) as caught:
                resolve_building(selector, catalog)
            self.assertEqual(caught.exception.code, 'BUILDING_NOT_FOUND')

    def test_number_alias_full_name_and_unique_fragment(self):
        catalog = self.catalog()
        for selector, expected in [('1', BUILDING), (' b1 ', BUILDING), ('B2', SOUTH),
                                   ('主馆', BUILDING), ('主馆南区', SOUTH), ('南区', SOUTH),
                                   ('教育', EDUCATION), ('b4', SHAHE)]:
            with self.subTest(selector=selector):
                self.assertEqual(resolve_building(selector, catalog), expected)

    def test_full_name_precedes_short_name_and_substrings(self):
        source = live_catalog()
        source['buildings'][1]['name'] = '主馆（南区）'
        catalog = self.catalog(source)
        self.assertEqual(resolve_building('主馆', catalog), BUILDING)
        self.assertEqual(resolve_building('主馆(南区)', catalog), SOUTH)
        source['buildings'][3]['name'] = '沙河（校区）'
        catalog = self.catalog(source)
        self.assertEqual(resolve_building('沙 河', catalog), SHAHE)
        self.assertEqual(catalog['buildings'][3]['shortName'], '沙河')

    def test_ambiguous_fragment_reports_candidates(self):
        with self.assertRaises(Error) as caught:
            resolve_building('主', self.catalog())
        self.assertEqual(caught.exception.code, 'BUILDING_AMBIGUOUS')
        self.assertIn('b1: 主馆', str(caught.exception))
        self.assertIn('b2: 主馆南区', str(caught.exception))

    def test_unknown_and_empty_selectors_fail(self):
        for selector in ('其他分馆', '0', 'b9', '   '):
            with self.subTest(selector=selector), self.assertRaises(Error) as caught:
                resolve_building(selector, self.catalog())
            self.assertEqual(caught.exception.code, 'BUILDING_NOT_FOUND')

    def test_disabled_exact_match_never_falls_back_to_another_building(self):
        for disabled in (False, 0):
            source = live_catalog()
            source['buildings'][0]['enabled'] = disabled
            catalog = self.catalog(source)
            for selector in ('1', 'B1', '主馆', BUILDING):
                with self.subTest(selector=selector, disabled=disabled), self.assertRaises(Error) as caught:
                    resolve_building(selector, catalog)
                self.assertEqual(caught.exception.code, 'BUILDING_DISABLED')

    def test_new_building_gets_no_automatic_number(self):
        source = live_catalog()
        new_id = '9999999999999999999'
        source['buildings'].insert(0, {'id': new_id, 'name': '未来新馆', 'enabled': True})
        catalog = self.catalog(source)
        self.assertIsNone(catalog['buildings'][0]['number'])
        self.assertIsNone(catalog['buildings'][0]['alias'])
        self.assertEqual(resolve_building('未来', catalog), new_id)
        self.assertEqual(resolve_building('1', catalog), BUILDING)
        with self.assertRaises(Error):
            resolve_building('5', catalog)

    def test_complete_id_skips_catalog_and_short_selector_fetches_once(self):
        client = Mock()
        for value in (BUILDING, SOUTH, '123456789012', '9999999999999999999'):
            self.assertEqual(building_selector(client, value), value)
        client.api.assert_not_called()
        client.api.return_value = live_catalog()
        self.assertEqual(building_selector(client, 'B2'), SOUTH)
        client.api.assert_called_once_with('res/buildingFloorDate')


class BuildingCliTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.api.return_value = live_catalog()
        client.rooms.return_value = [{'id': SOUTH_ROOM, 'name': '工具报刊外文阅览区', 'floorId': '123456789012'}]
        client.seats.return_value = {SEAT: {'id': SEAT, 'label': '008'}}
        client.validate_booking.return_value = {'validated': True}
        client.book.return_value = {'submitted': True}
        return client

    def invoke(self, argv, client):
        with patch('bnul.cli.Client', return_value=client):
            return run(parser().parse_args(argv))

    def time_args(self):
        return ['--date', DATE, '--start', '19:00', '--end', '20:00']

    def test_buildings_command_keeps_dates_and_floors(self):
        client = self.client()
        result = self.invoke(['buildings'], client)
        self.assertEqual(result['dates'], [DATE])
        original_floor = live_catalog()['buildings'][0]['floors'][0]
        actual_floor = result['buildings'][0]['floors'][0]
        self.assertEqual({key: actual_floor[key] for key in original_floor}, original_floor)
        self.assertEqual((actual_floor['number'], actual_floor['alias'], actual_floor['shortName']), (3, 'f3', '3层'))
        self.assertEqual(result['buildings'][0]['alias'], 'b1')
        client.api.assert_called_once_with('res/buildingFloorDate')

    def test_room_list_and_rooms_without_times_resolve_building(self):
        for command in ('room-list', 'rooms'):
            with self.subTest(command=command):
                client = self.client()
                result = self.invoke([command, '--building', '南区'], client)
                self.assertEqual(result['buildingId'], SOUTH)
                self.assertEqual(client.rooms.call_args.args[0], SOUTH)
                client.api.assert_called_once_with('res/buildingFloorDate')

    def test_rooms_with_times_forwards_resolved_id_and_floor(self):
        client = self.client()
        self.invoke(['rooms', '--building', '2', '--floor', '123456789012',
                     '--power'] + self.time_args(), client)
        client.rooms.assert_called_once_with(SOUTH, DATE, 1140, 1200, '123456789012', True, False)
        client.api.assert_called_once_with('res/buildingFloorDate')

    def test_seats_resolves_room_inside_selected_building(self):
        client = self.client()
        result = self.invoke(['seats', '--building', 'B2', '--room', '工具报刊'] + self.time_args(), client)
        self.assertEqual(client.rooms.call_args.args[0], SOUTH)
        client.seats.assert_called_once_with(SOUTH_ROOM, DATE, 1140, 1200)
        client.api.assert_called_once_with('res/buildingFloorDate')
        self.assertEqual(result[0]['label'], '008')

    def test_book_only_submits_with_execute(self):
        for execute in (False, True):
            with self.subTest(execute=execute):
                client = self.client()
                argv = ['book', '--building', '南区', '--room', '工具报刊', '--seat', SEAT] + self.time_args()
                if execute:
                    argv.append('--execute')
                result = self.invoke(argv, client)
                self.assertEqual(client.rooms.call_args.args[0], SOUTH)
                client.seats.assert_called_once_with(SOUTH_ROOM, DATE, 1140, 1200)
                client.api.assert_called_once_with('res/buildingFloorDate')
                if execute:
                    self.assertEqual(client.book.call_count, 1)
                    self.assertEqual(client.book.call_args.args[:4], (SEAT, DATE, 1140, 1200))
                else:
                    client.book.assert_not_called()
                    client.validate_booking.assert_called_once_with(SEAT, DATE, 1140, 1200)
                    self.assertFalse(result['submitted'])

    def test_book_seat_label_resolves_without_extra_request(self):
        for execute in (False, True):
            client = self.client()
            argv = ['book', '--seat', '008'] + self.time_args() + (['-e'] if execute else [])
            result = self.invoke(argv, client)
            client.seats.assert_called_once_with(ROOM, DATE, 1140, 1200)
            client.api.assert_not_called()
            client.rooms.assert_not_called()
            if execute:
                self.assertEqual(client.book.call_args.args[:4], (SEAT, DATE, 1140, 1200))
            else:
                client.validate_booking.assert_called_once_with(SEAT, DATE, 1140, 1200)
                self.assertEqual(result['seatLabel'], '008')

    def test_book_unknown_or_ambiguous_label_never_submits(self):
        other = '9876543210987654322'
        for seats in ({SEAT: {'id': SEAT, 'label': '007'}},
                      {SEAT: {'id': SEAT, 'label': '008'}, other: {'id': other, 'label': '008'}}):
            client = self.client()
            client.seats.return_value = seats
            with self.assertRaises(Error) as caught:
                self.invoke(['book', '--seat', '008', '--execute'] + self.time_args(), client)
            self.assertEqual(caught.exception.code, 'SEAT_NOT_FOUND')
            client.validate_booking.assert_not_called()
            client.book.assert_not_called()

    def test_recommend_forwards_resolved_building_and_room_order(self):
        client = self.client()
        with patch('bnul.recommend.recommend', return_value={'recommendations': []}) as recommend, \
                patch('bnul.rooms.ordered_rooms', return_value=[SOUTH_ROOM]) as ordered:
            self.invoke(['recommend', '--building', 'b2', '--room-order', '工具报刊'] + self.time_args(), client)
        ordered.assert_called_once_with(client, SOUTH, '工具报刊', None)
        recommend.assert_called_once_with(client, DATE, 1140, 1200, SOUTH, None, '0', 5, 50, [SOUTH_ROOM])
        client.api.assert_called_once_with('res/buildingFloorDate')

    def test_default_and_explicit_main_building_allow_default_room(self):
        for command in ('seats', 'book'):
            for selector in (None, '1', '主馆', BUILDING):
                with self.subTest(command=command, selector=selector):
                    client = self.client()
                    argv = [command] + self.time_args()
                    if command == 'book':
                        argv += ['--seat', SEAT]
                    if selector is not None:
                        argv += ['--building', selector]
                    self.invoke(argv, client)
                    client.seats.assert_called_once_with(ROOM, DATE, 1140, 1200)
                    client.rooms.assert_not_called()
                    client.book.assert_not_called()
                    if selector in (None, BUILDING):
                        client.api.assert_not_called()

    def test_other_buildings_require_room_before_seat_query_or_submission(self):
        for command in ('seats', 'book'):
            for selector in ('2', 'B2', '南区', SOUTH):
                with self.subTest(command=command, selector=selector):
                    client = self.client()
                    argv = [command, '--building', selector] + self.time_args()
                    if command == 'book':
                        argv += ['--seat', SEAT, '--execute']
                    with self.assertRaises(Error) as caught:
                        self.invoke(argv, client)
                    self.assertEqual(caught.exception.code, 'ROOM_REQUIRED')
                    client.rooms.assert_not_called()
                    client.seats.assert_not_called()
                    client.book.assert_not_called()
                    if selector == SOUTH:
                        client.api.assert_not_called()

    def test_invalid_or_disabled_selector_stops_before_room_query(self):
        for selector in ('主', 'b9', '主馆'):
            with self.subTest(selector=selector):
                client = self.client()
                client.api.return_value['buildings'][0]['enabled'] = False
                with self.assertRaises(Error):
                    self.invoke(['room-list', '--building', selector], client)
                client.rooms.assert_not_called()


if __name__ == '__main__':
    unittest.main()
