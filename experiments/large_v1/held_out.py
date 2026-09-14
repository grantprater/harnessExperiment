import random
import unittest
from dispatchdesk.billing.models import LineItem
from dispatchdesk.billing.service import quote_order
from dispatchdesk.events.models import Event
from dispatchdesk.events.service import list_events
from dispatchdesk.cache.service import FeedCache
from dispatchdesk.cache.keys import feed_key

class HeldOut(unittest.TestCase):
    def test_quote_matrix(self):
        for price in [0,13.37,49.99,151,999.95]:
            for quantity in [1,3]:
                for discount in [0,7,25,100]:
                    for rate in [0,0.05,0.0825]:
                        subtotal = round(price*quantity,2)
                        taxable = round(subtotal-round(subtotal*discount/100,2),2)
                        quote = quote_order([LineItem('z',quantity,price)],discount,rate)
                        self.assertEqual(quote.tax,round(taxable*rate,2))
                        self.assertEqual(quote.total,round(taxable+quote.tax+(0 if taxable>=150 else 15),2))
    def test_cache_identity_and_none(self):
        cache = FeedCache(ttl=10,clock=lambda:0)
        keys = [(t,s,p) for t in ['a','a:b',''] for s in [None,'','open','x:y'] for p in [1,2]]
        identities = [feed_key(*key) for key in keys]
        self.assertEqual(len(set(identities)),len(keys))
        for i,key in enumerate(keys):
            self.assertEqual(cache.get(*key,lambda i=i:i),i)
        for i,key in enumerate(keys):
            self.assertEqual(cache.get(*key,lambda:-1),i)
        cache.get('none',None,1,lambda:None)
        self.assertIsNone(cache.get('none',None,1,lambda:'wrong'))
    def test_cache_time_and_loader_failure(self):
        now = [0]
        cache = FeedCache(ttl=1,clock=lambda:now[0])
        self.assertEqual(cache.get('x',None,1,lambda:1),1)
        now[0] = 0.999
        self.assertEqual(cache.get('x',None,1,lambda:2),1)
        now[0] = 1
        self.assertEqual(cache.get('x',None,1,lambda:2),2)
        zero = FeedCache(ttl=0,clock=lambda:0)
        zero.get('x',None,1,lambda:1)
        self.assertEqual(zero.get('x',None,1,lambda:2),2)
        def failing(): raise RuntimeError('upstream')
        with self.assertRaises(RuntimeError): cache.get('bad',None,1,failing)
        self.assertEqual(cache.get('bad',None,1,lambda:3),3)
    def test_feed_matrix(self):
        rng = random.Random(802)
        events = [Event(i,rng.choice(['a','b']),rng.choice(['open','closed']),rng.randrange(8)) for i in range(80)]
        rng.shuffle(events)
        before = list(events)
        for tenant in ['a','b','missing']:
            for status in [None,'open','closed']:
                expected = sorted([e for e in events if e.tenant==tenant and (status is None or e.status==status)],key=lambda e:(-e.created_at,e.id))
                for page in [1,2,8]:
                    for size in [1,7,100]:
                        self.assertEqual(list_events(events,tenant,status,page,size),{'items':expected[(page-1)*size:page*size],'total':len(expected)})
                        self.assertEqual(events,before)
        for page,size in [(0,1),(1,0),(-1,5),(2,-5)]:
            with self.assertRaises(ValueError): list_events(events,'a',page=page,page_size=size)
if __name__ == '__main__': unittest.main()
