import unittest
from unittest.mock import Mock, patch
from bnul.client import Error
from bnul.recommend import recommend

class RecommendTests(unittest.TestCase):
    def client(self):
        c=Mock()
        c.rooms.return_value=[{'id':'1','name':'自习区','buildingName':'主馆','floorName':'3层'},
                              {'id':'2','name':'阅览室','buildingName':'主馆','floorName':'4层'}]
        c.seats.side_effect=lambda room,*args: {room+'01':{'id':room+'01','label':'001','status':'IN_USE','afterFree':True},
                                               room+'02':{'id':room+'02','label':'002','status':'FREE','afterFree':False}}
        c.validate_booking.side_effect=lambda seat,date,start,end:{'seatId':seat,'date':date,'beginMinute':start,'endMinute':end,'validated':True}
        return c
    def test_exact_interval_and_diverse_rooms(self):
        c=self.client();r=recommend(c,'2999-01-01',1140,1260,limit=2)
        self.assertEqual([s['seatId'] for s in r['recommendations']],['101','201'])
        self.assertEqual(r['recommendations'][0]['currentStatus'],'IN_USE')
        self.assertFalse(r['submitted']);self.assertFalse(r['searchExhausted'])
        c.validate_booking.assert_any_call('101','2999-01-01',1140,1260)
        c.book.assert_not_called();c.api.assert_not_called()
    def test_does_not_trust_free_status(self):
        c=self.client();c.validate_booking.side_effect=Error('not selectable','TIME_UNAVAILABLE')
        r=recommend(c,'2999-01-01',1140,1260)
        self.assertEqual(r['recommendations'],[]);self.assertTrue(r['searchExhausted'])
    def test_budget_is_not_global_no_availability(self):
        c=self.client();c.validate_booking.side_effect=Error('not selectable','TIME_UNAVAILABLE')
        r=recommend(c,'2999-01-01',1140,1260,limit=1,max_checks=2)
        self.assertEqual(r['checkedSeats'],2);self.assertEqual(r['stopReason'],'check_limit')
        self.assertFalse(r['searchExhausted'])
    def test_network_and_auth_errors_propagate(self):
        for code in [None,20003,500]:
            c=self.client();c.validate_booking.side_effect=Error('failure',code)
            with self.assertRaises(Error):recommend(c,'2999-01-01',1140,1260)
    def test_room_scope(self):
        c=self.client();r=recommend(c,'2999-01-01',1140,1260,room='2')
        self.assertEqual({s['roomId'] for s in r['recommendations']},{'2'})
        self.assertTrue(r['searchExhausted'])
        c.seats.assert_called_once()
    def test_now_preserved(self):
        c=self.client()
        with patch('bnul.recommend.query_start',return_value=941):
            r=recommend(c,'2999-01-01',-1,1260,limit=1)
        self.assertEqual(r['start'],'now')
        c.validate_booking.assert_called_once_with('101','2999-01-01',-1,1260)
    def test_invalid_range_or_past_rejected(self):
        for date,start,end in [('2000-01-01',1140,1260),('2999-01-01',1260,1140)]:
            c=self.client()
            with self.assertRaises(Error):recommend(c,date,start,end)
            c.rooms.assert_not_called()
    def test_unknown_room(self):
        with self.assertRaises(Error):recommend(self.client(),'2999-01-01',1140,1260,room='9')
    def test_empty_scope(self):
        c=self.client();c.rooms.return_value=[]
        r=recommend(c,'2999-01-01',1140,1260)
        self.assertEqual(r['recommendations'],[]);self.assertTrue(r['searchExhausted'])
