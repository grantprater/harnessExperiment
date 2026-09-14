import importlib
import unittest
from dispatchdesk.billing.models import LineItem
from dispatchdesk.billing.service import quote_order
from dispatchdesk.events.models import Event
from dispatchdesk.events.service import list_events
from dispatchdesk.cache.service import FeedCache

class Billing(unittest.TestCase):
    def test_promotion_tax(self):
        q = quote_order([LineItem('x',4,50)],20,0.0825)
        self.assertEqual((q.taxable,q.tax,q.total),(160,13.2,173.2))
    def test_regular_order(self):
        self.assertEqual(quote_order([LineItem('x',2,25)],0,0.065).total,68.25)
    def test_shipping_after_promotion(self):
        self.assertEqual(quote_order([LineItem('x',1,160)],20,0).shipping,15)
    def test_invalid_promotion(self):
        with self.assertRaises(ValueError): quote_order([],101)

class Cache(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.cache = FeedCache(ttl=10,clock=lambda:self.now)
    def test_tenant_isolation(self):
        self.cache.get('a','open',1,lambda:'A')
        self.assertEqual(self.cache.get('b','open',1,lambda:'B'),'B')
    def test_status_isolation(self):
        self.cache.get('a','open',1,lambda:'open')
        self.assertEqual(self.cache.get('a','closed',1,lambda:'closed'),'closed')
    def test_page_isolation(self):
        self.cache.get('a','open',1,lambda:'one')
        self.assertEqual(self.cache.get('a','open',2,lambda:'two'),'two')
    def test_cache_hit(self):
        self.cache.get('a',None,1,lambda:'old')
        self.assertEqual(self.cache.get('a',None,1,lambda:'new'),'old')
    def test_ttl_boundary(self):
        self.cache.get('a',None,1,lambda:'old')
        self.now = 110
        self.assertEqual(self.cache.get('a',None,1,lambda:'new'),'new')

class Feed(unittest.TestCase):
    def setUp(self):
        self.events = [Event(8,'b','open',90),Event(3,'a','open',20),Event(1,'a','open',20),Event(2,'a','closed',30),Event(4,'a','open',10)]
    def test_first_page(self):
        page = list_events(self.events,'a','open',1,2)
        self.assertEqual([e.id for e in page['items']],[1,3])
        self.assertEqual(page['total'],3)
    def test_empty_page_total(self):
        self.assertEqual(list_events(self.events,'a',page=9)['total'],4)
    def test_invalid_page(self):
        with self.assertRaises(ValueError): list_events(self.events,'a',page=0)
    def test_preserves_input(self):
        before = list(self.events)
        list_events(self.events,'a')
        self.assertEqual(before,self.events)

class Resources(unittest.TestCase):
    def test_generated_adapters(self):
        resources = 'account carrier container customer delivery invoice item location manifest order parcel payment pickup product route warehouse'.split()
        for resource in resources:
            with self.subTest(resource=resource):
                model = importlib.import_module(f'dispatchdesk.resources.{resource}.model')
                codec = importlib.import_module(f'dispatchdesk.resources.{resource}.codec')
                query = importlib.import_module(f'dispatchdesk.resources.{resource}.query')
                policy = importlib.import_module(f'dispatchdesk.resources.{resource}.policy')
                row = model.new_record('r1','tenant',name='Example',amount=12.5)
                self.assertEqual(codec.decode(codec.encode(row)),row)
                self.assertEqual(query.for_tenant([row],'tenant'),[row])
                self.assertEqual(query.for_tenant([row],'other'),[])
                self.assertTrue(policy.can_read(row,'tenant'))
                self.assertFalse(policy.can_read(row,'other'))
if __name__ == '__main__': unittest.main()
