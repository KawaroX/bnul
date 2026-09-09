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
        c=Mock();c.rooms.return_value=[{'id':'101','name':'1F自习区（安静区）'}, {'id':'202','name':'2F自习区'}]
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'BNUL_CONFIG':tmp+'/session.json'}):
            first=room_catalog(c,'123',True)
            self.assertEqual(resolve_room('1',first),'101')
            c.rooms.return_value=[{'id':'202','name':'2F新名称'}, {'id':'303','name':'3F阅览区'}]
            updated=room_catalog(c,'123',True)
            self.assertEqual([(r['id'],r['number'],r['active']) for r in updated['rooms']], [('101',1,False),('202',2,True),('303',3,True)])
            with self.assertRaises(Error):resolve_room('1',updated)
            self.assertEqual(resolve_room('2',updated),'202')
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
    def test_corrupt_cache_does_not_reassign_numbers(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'BNUL_CONFIG':tmp+'/session.json'}):
            Path(tmp+'/rooms-123.json').write_text('broken')
            with self.assertRaises(Error):room_catalog(Mock(),'123',True)
    def test_rooms_without_times_and_partial_times(self):
        from bnul.cli import parser,main
        args=parser().parse_args(['rooms'])
        self.assertIsNone(args.start);self.assertIsNone(args.end)
        with patch('sys.stdout',new_callable=__import__('io').StringIO),patch('bnul.cli.Client') as c:
            self.assertEqual(main(['--json','rooms','--start','19:00']),1)
            c.assert_not_called()
