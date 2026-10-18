import copy
import unittest
from unittest.mock import Mock, patch

from bnul.buildings import building_catalog, location_selector
from bnul.cli import parser, run
from bnul.client import BUILDING, Error
from bnul.floors import floor_number, floor_selector, resolve_floor


SOUTH = '1864245010251223040'
MAIN_FIRST = '100000000001'
MAIN_THIRD = '100000000003'
MAIN_TENTH = '100000000010'
SOUTH_THIRD = '200000000003'
SPECIAL = '100000000099'
DATE = '2999-01-01'


def live_catalog():
    return {'dates': [DATE], 'buildings': [
        {'id': BUILDING, 'name': '主馆', 'enabled': True, 'floors': [
            {'id': MAIN_THIRD, 'name': '3层', 'enabled': True, 'extra': 'preserved'},
            {'id': MAIN_TENTH, 'name': '10层', 'enabled': True},
            {'id': MAIN_FIRST, 'name': '1层', 'enabled': True},
            {'id': SPECIAL, 'name': '研修夹层（安静区）', 'enabled': True},
        ]},
        {'id': SOUTH, 'name': '主馆南区', 'enabled': True, 'floors': [
            {'id': SOUTH_THIRD, 'name': '3层', 'enabled': True},
        ]},
    ]}


class FloorTests(unittest.TestCase):
    def catalog(self, source=None):
        client = Mock()
        client.api.return_value = live_catalog() if source is None else source
        return building_catalog(client)

    def test_catalog_uses_actual_level_not_list_position(self):
        source = live_catalog()
        before = copy.deepcopy(source)
        catalog = self.catalog(source)
        self.assertEqual(source, before)
        floors = catalog['buildings'][0]['floors']
        self.assertEqual([row['number'] for row in floors], [3, 10, 1, None])
        self.assertEqual([row['alias'] for row in floors], ['f3', 'f10', 'f1', None])
        self.assertEqual(floors[3]['shortName'], '研修夹层')
        self.assertEqual(catalog['buildings'][1]['floors'][0]['number'], 3)
        for original, enhanced in zip(source['buildings'][0]['floors'], floors):
            self.assertIsNot(original, enhanced)
            self.assertEqual({key: enhanced[key] for key in original}, original)

    def test_recognizable_names_and_unknown_names(self):
        for name, expected in [('3层', 3), ('三楼', 3), ('第十一层', 11), ('二十一楼', 21),
                               ('两层', 2), ('f3', 3), ('3F', 3), ('03楼', 3), ('99层', 99),
                               ('地下一层', None), ('-1层', None), ('B1', None),
                               ('东区3层', None), ('夹层', None), ('0', None), ('三F', None)]:
            with self.subTest(name=name):
                self.assertEqual(floor_number(name), expected)

    def test_every_supported_third_floor_spelling(self):
        catalog = self.catalog()
        for selector in ('3', 'f3', 'F3', '3F', '3f', '3层', '3楼', '三层', '三楼',
                         '第3层', '第三楼', ' 3 F ', '03'):
            with self.subTest(selector=selector):
                self.assertEqual(resolve_floor(BUILDING, selector, catalog), MAIN_THIRD)

    def test_identical_levels_are_scoped_to_selected_building(self):
        catalog = self.catalog()
        self.assertEqual(resolve_floor(BUILDING, 'f3', catalog), MAIN_THIRD)
        self.assertEqual(resolve_floor(SOUTH, 'f3', catalog), SOUTH_THIRD)
        with self.assertRaises(Error) as caught:
            resolve_floor(SOUTH, '1', catalog)
        self.assertEqual(caught.exception.code, 'FLOOR_NOT_FOUND')

    def test_reordering_or_removing_floors_does_not_renumber(self):
        source = live_catalog()
        source['buildings'][0]['floors'].reverse()
        catalog = self.catalog(source)
        self.assertEqual(resolve_floor(BUILDING, '1', catalog), MAIN_FIRST)
        self.assertEqual(resolve_floor(BUILDING, '3', catalog), MAIN_THIRD)
        source['buildings'][0]['floors'] = [row for row in source['buildings'][0]['floors'] if row['id'] != MAIN_THIRD]
        catalog = self.catalog(source)
        self.assertEqual(resolve_floor(BUILDING, '10', catalog), MAIN_TENTH)
        with self.assertRaises(Error):
            resolve_floor(BUILDING, '3', catalog)

    def test_multidigit_level_never_matches_another_number_as_fragment(self):
        source = live_catalog()
        source['buildings'][0]['floors'] = [source['buildings'][0]['floors'][1]]
        catalog = self.catalog(source)
        self.assertEqual(resolve_floor(BUILDING, '10', catalog), MAIN_TENTH)
        self.assertEqual(resolve_floor(BUILDING, '十楼', catalog), MAIN_TENTH)
        for selector in ('1', 'f1', '1F', '1层', '一楼', 'f0', '0F'):
            with self.subTest(selector=selector), self.assertRaises(Error) as caught:
                resolve_floor(BUILDING, selector, catalog)
            self.assertEqual(caught.exception.code, 'FLOOR_NOT_FOUND')

    def test_unknown_floor_names_remain_selectable_without_assigned_number(self):
        catalog = self.catalog()
        for selector in ('研修夹层（安静区）', '研修夹层', '研修', '安静'):
            with self.subTest(selector=selector):
                self.assertEqual(resolve_floor(BUILDING, selector, catalog), SPECIAL)
        with self.assertRaises(Error):
            resolve_floor(BUILDING, '4', catalog)

    def test_ambiguous_name_and_duplicate_level_report_candidates(self):
        catalog = self.catalog()
        with self.assertRaises(Error) as caught:
            resolve_floor(BUILDING, '层', catalog)
        self.assertEqual(caught.exception.code, 'FLOOR_AMBIGUOUS')
        self.assertIn('f3: 3层', str(caught.exception))
        source = live_catalog()
        source['buildings'][0]['floors'].append({'id': '100000000033', 'name': '3F', 'enabled': True})
        catalog = self.catalog(source)
        with self.assertRaises(Error) as caught:
            resolve_floor(BUILDING, 'f3', catalog)
        self.assertEqual(caught.exception.code, 'FLOOR_AMBIGUOUS')
        self.assertEqual(resolve_floor(BUILDING, '3层', catalog), MAIN_THIRD)

    def test_exact_qualified_name_resolves_even_when_level_is_shared(self):
        source = live_catalog()
        source['buildings'][0]['floors'][0]['name'] = '3层（东区）'
        source['buildings'][0]['floors'].append({'id': '100000000033', 'name': '3层（西区）', 'enabled': True})
        catalog = self.catalog(source)
        self.assertEqual(resolve_floor(BUILDING, '3层(东区)', catalog), MAIN_THIRD)
        with self.assertRaises(Error):
            resolve_floor(BUILDING, '3层', catalog)
        with self.assertRaises(Error):
            resolve_floor(BUILDING, '3层（不存在）', catalog)

    def test_disabled_floor_and_building_fail_without_fallback(self):
        for disabled in (False, 0):
            source = live_catalog()
            source['buildings'][0]['floors'][0]['enabled'] = disabled
            catalog = self.catalog(source)
            for selector in ('3', 'F3', '三楼', '3层'):
                with self.subTest(disabled=disabled, selector=selector), self.assertRaises(Error) as caught:
                    resolve_floor(BUILDING, selector, catalog)
                self.assertEqual(caught.exception.code, 'FLOOR_DISABLED')
            source['buildings'][0]['enabled'] = disabled
            with self.assertRaises(Error) as caught:
                resolve_floor(BUILDING, '1', self.catalog(source))
            self.assertEqual(caught.exception.code, 'BUILDING_DISABLED')

    def test_missing_building_floor_and_invalid_selector_do_not_fall_back(self):
        catalog = self.catalog()
        with self.assertRaises(Error) as caught:
            resolve_floor('999999999999', '3', catalog)
        self.assertEqual(caught.exception.code, 'BUILDING_NOT_FOUND')
        for selector in ('f0', '0F', '4', '不存在', '', '-1', '-1层', '-3层', '三F'):
            with self.subTest(selector=selector), self.assertRaises(Error) as caught:
                resolve_floor(BUILDING, selector, catalog)
            self.assertEqual(caught.exception.code, 'FLOOR_NOT_FOUND')

    def test_all_and_complete_id_skip_catalog(self):
        client = Mock()
        for selector in ('0', 'all', 'ALL', '全部'):
            self.assertEqual(floor_selector(client, BUILDING, selector), '0')
        for selector in (MAIN_THIRD, '999999999999'):
            self.assertEqual(floor_selector(client, BUILDING, selector), selector)
        client.api.assert_not_called()

    def test_optional_catalog_reuse_and_standalone_query(self):
        client = Mock()
        client.api.return_value = live_catalog()
        self.assertEqual(floor_selector(client, SOUTH, '3'), SOUTH_THIRD)
        client.api.assert_called_once_with('res/buildingFloorDate')
        client.api.reset_mock()
        self.assertEqual(floor_selector(client, SOUTH, '3', self.catalog()), SOUTH_THIRD)
        client.api.assert_not_called()

    def test_combined_location_resolves_with_at_most_one_directory_request(self):
        for building, floor, expected_floor, calls in (
                ('南区', '三层', SOUTH_THIRD, 1), ('b2', 'f3', SOUTH_THIRD, 1),
                (SOUTH, '3F', SOUTH_THIRD, 1), ('2', SOUTH_THIRD, SOUTH_THIRD, 1),
                (SOUTH, SOUTH_THIRD, SOUTH_THIRD, 0), (SOUTH, '0', '0', 0),
                (SOUTH, 'all', '0', 0), (SOUTH, None, None, 0)):
            with self.subTest(building=building, floor=floor):
                client = Mock()
                client.api.return_value = live_catalog()
                self.assertEqual(location_selector(client, building, floor), (SOUTH, expected_floor))
                self.assertEqual(client.api.call_count, calls)


class FloorCliTests(unittest.TestCase):
    def client(self):
        client = Mock()
        client.api.return_value = live_catalog()
        client.rooms.return_value = [
            {'id': '999999999991', 'name': '主馆三层房间', 'floorId': MAIN_THIRD},
            {'id': '999999999992', 'name': '南区三层房间', 'floorId': SOUTH_THIRD},
        ]
        return client

    def invoke(self, argv, client):
        with patch('bnul.cli.Client', return_value=client):
            return run(parser().parse_args(argv))

    def times(self):
        return ['--date', DATE, '--start', '19:00', '--end', '20:00']

    def test_rooms_without_times_filters_resolved_floor_in_selected_building(self):
        client = self.client()
        result = self.invoke(['rooms', '--building', '南区', '--floor', '3'], client)
        self.assertEqual(result['buildingId'], SOUTH)
        self.assertEqual([row['id'] for row in result['rooms']], ['999999999992'])
        self.assertEqual(client.rooms.call_args.args[0], SOUTH)
        client.api.assert_called_once_with('res/buildingFloorDate')

    def test_rooms_with_times_forwards_resolved_building_and_floor(self):
        client = self.client()
        self.invoke(['rooms', '--building', 'b2', '--floor', 'f3', '--windows'] + self.times(), client)
        client.rooms.assert_called_once_with(SOUTH, DATE, 1140, 1200, SOUTH_THIRD, False, True)
        client.api.assert_called_once_with('res/buildingFloorDate')

    def test_recommend_forwards_resolved_building_and_floor(self):
        client = self.client()
        with patch('bnul.recommend.recommend', return_value={'recommendations': []}) as recommend:
            self.invoke(['recommend', '--building', '南区', '--floor', '三楼'] + self.times(), client)
        recommend.assert_called_once_with(client, DATE, 1140, 1200, SOUTH, None, SOUTH_THIRD, 5, 50, None)
        client.api.assert_called_once_with('res/buildingFloorDate')

    def test_default_building_and_all_floor_aliases_do_not_query_catalog(self):
        for selector in (None, '0', 'all', '全部', MAIN_THIRD):
            with self.subTest(selector=selector):
                client = self.client()
                argv = ['rooms'] + self.times()
                if selector is not None:
                    argv += ['--floor', selector]
                self.invoke(argv, client)
                floor_id = MAIN_THIRD if selector == MAIN_THIRD else '0'
                client.rooms.assert_called_once_with(BUILDING, DATE, 1140, 1200, floor_id, False, False)
                client.api.assert_not_called()

    def test_bad_floor_stops_before_room_queries(self):
        for selector in ('1', '层', 'f0'):
            with self.subTest(selector=selector):
                client = self.client()
                if selector == '层':
                    client.api.return_value['buildings'][1]['floors'] += [
                        {'id': '200000000004', 'name': '4层', 'enabled': True}]
                with self.assertRaises(Error):
                    self.invoke(['rooms', '--building', '南区', '--floor', selector], client)
                client.rooms.assert_not_called()


if __name__ == '__main__':
    unittest.main()
