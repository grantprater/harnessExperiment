import unittest
from models import Record
from service import list_records

class Contract(unittest.TestCase):
    def setUp(self):
        self.rows = [Record(8,'b','open',90), Record(3,'a','open',20), Record(1,'a','open',20), Record(2,'a','closed',30), Record(4,'a','open',10)]
    def test_filter_then_page(self):
        result = list_records(self.rows,'a','open',1,2)
        self.assertEqual([r.id for r in result['items']], [1,3])
    def test_total(self):
        self.assertEqual(list_records(self.rows,'a','open',2,2)['total'],3)
    def test_second_page(self):
        self.assertEqual([r.id for r in list_records(self.rows,'a','open',2,2)['items']],[4])
    def test_no_status(self):
        self.assertEqual([r.id for r in list_records(self.rows,'a',page_size=4)['items']],[2,1,3,4])
    def test_empty_page(self):
        self.assertEqual(list_records(self.rows,'a',page=9)['items'],[])
        self.assertEqual(list_records(self.rows,'a',page=9)['total'],4)
    def test_invalid(self):
        for page,size in [(0,2),(-1,2),(1,0),(1,-1)]:
            with self.assertRaises(ValueError): list_records(self.rows,'a',page=page,page_size=size)
    def test_preserves_input(self):
        before = list(self.rows)
        list_records(self.rows,'a')
        self.assertEqual(self.rows,before)
    def test_missing_owner(self):
        self.assertEqual(list_records(self.rows,'z'),{'items': [], 'total': 0})
