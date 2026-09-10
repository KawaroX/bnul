import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from bnul.client import Error
from bnul.rooms import room_catalog,resolve_room,ordered_rooms

class RoomTests(unittest.TestCase):
    def test_stable_numbers_across_refresh(self):
        c=Mock();c.rooms.return_value=[{'id':'1888096971220160512','name':'3F自习区'}, {'id':'1887370822454185984','name':'2F自习区'}]
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'BNUL_CONFIG':tmp+'/session.json'}):
            first=room_catalog(c,'1887388460760797184',True)
            self.assertEqual(resolve_room('4',first),'1888096971220160512')
            c.rooms.return_value.reverse()
            self.assertEqual(first,room_catalog(c,'1887388460760797184'))
            c.rooms.return_value=[{'id':'1887370822454185984','name':'2F新名称'}, {'id':'303','name':'新增区域'}]
            updated=room_catalog(c,'1887388460760797184',True)
            self.assertEqual([r['number'] for r in updated['rooms']], [2,None])
            with self.assertRaises(Error):resolve_room('4',updated)
            self.assertEqual(resolve_room('新增',updated),'303')
            self.assertEqual(list(Path(tmp).iterdir()),[])
    def rows(self):
        return {'rooms':[{'id':'101','number':1,'name':'3F自习区（低声区）','shortName':'3F自习区','active':True},
                         {'id':'202','number':2,'name':'2F自习区（低声区）','shortName':'2F自习区','active':True},
                         {'id':'303','number':10,'name':'阅览室','shortName':'阅览室','active':True}]}
    def test_selectors_and_ambiguity(self):
        for key in ['101','1','r1','3F自习区（低声区）','3f自习']:
            self.assertEqual(resolve_room(key,self.rows()),'101')
        self.assertEqual(resolve_room('0',self.rows()),'303')
        with self.assertRaises(Error) as e:resolve_room('自习',self.rows())
        self.assertEqual(e.exception.code,'ROOM_AMBIGUOUS')
    def test_order_syntax_and_duplicates(self):
        with patch('bnul.rooms.room_catalog',return_value=self.rows()):
            self.assertEqual(ordered_rooms(None,'123',order='2,3F自习,0'),['202','101','303'])
            self.assertEqual(ordered_rooms(None,'123',sequence='210'),['202','101','303'])
            self.assertEqual(ordered_rooms(None,'123',order='10'),['303'])
            for kwargs in [{'order':'1,r1'},{'sequence':'2a'},{'order':''}]:
                with self.assertRaises(Error):ordered_rooms(None,'123',**kwargs)
    def test_legacy_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'BNUL_CONFIG':tmp+'/session.json'}):
            path=Path(tmp+'/rooms-1887388460760797184.json')
            path.write_text('broken')
            c=Mock();c.rooms.return_value=[{'id':'1888096971220160512','name':'3F自习区'}]
            self.assertEqual(resolve_room('4',room_catalog(c,'1887388460760797184')),'1888096971220160512')
            self.assertEqual(path.read_text(),'broken')
    def test_other_building_has_no_assigned_numbers(self):
        c=Mock();c.rooms.return_value=[{'id':'1888096971220160512','name':'其他区域'}]
        catalog=room_catalog(c,'123')
        self.assertIsNone(catalog['rooms'][0]['number'])
        with self.assertRaises(Error):resolve_room('4',catalog)
    def test_rooms_without_times_and_partial_times(self):
        from bnul.cli import parser,main
        args=parser().parse_args(['rooms'])
        self.assertIsNone(args.start);self.assertIsNone(args.end)
        with patch('sys.stdout',new_callable=__import__('io').StringIO),patch('bnul.cli.Client') as c:
            self.assertEqual(main(['--json','rooms','--start','19:00']),1)
            c.assert_not_called()

class CatalogCliTests(unittest.TestCase):
    def test_floor_filter_keeps_original_numbers(self):
        import io
        from bnul.cli import main
        data={'rooms':[{'id':'a','number':4,'active':True,'floorId':'3'},
                       {'id':'b','number':5,'active':True,'floorId':'4'}]}
        with patch('bnul.cli.Client'),patch('bnul.rooms.room_catalog',return_value=data),patch('sys.stdout',new_callable=io.StringIO) as out:
            self.assertEqual(main(['--json','rooms','--floor','3']),0)
            self.assertEqual([r['number'] for r in json.loads(out.getvalue())['data']['rooms']],[4])
