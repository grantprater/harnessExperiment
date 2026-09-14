"""Supplementary contract checks, unavailable through the participant interface.

These checks were added during the pilot and are supplementary validation,
not a preregistered primary endpoint.
"""
import json
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

task, candidate = sys.argv[1:3]
sys.path.insert(0,str(Path(candidate).resolve()))

class ExtraChecks(unittest.TestCase):
    def test_billing_discount_cases(self):
        if task != 'billing': self.skipTest('Other task')
        from models import Cart, CartItem, PromoCode
        from pricing import calculate_final_bill
        for subtotal in [20,100,150,300,500,1000]:
            for percent in [0,0.1,0.25]:
                for state,rate in [('CA',0.0825),('OR',0),('TX',0.0625)]:
                    cart = Cart([CartItem('x','X',subtotal,1)])
                    bill = calculate_final_bill(cart,state,PromoCode('P',percent))
                    taxable = round(subtotal-round(subtotal*percent,2),2)
                    self.assertEqual(bill['tax_amount'],round(taxable*rate,2))
                    self.assertEqual(bill['taxable_amount'],taxable)
                    self.assertEqual(bill['final_total'],round(taxable+bill['tax_amount']+bill['shipping_fee'],2))

    def test_kv_contract_boundaries(self):
        if task != 'kv': self.skipTest('Other task')
        from models import KVEntry
        from engine import KVStore
        self.assertTrue(KVEntry('a','b',0).is_expired(now=0))
        self.assertFalse(KVEntry('a','b',1).is_expired(now=0))
        self.assertFalse(KVEntry('a','b').is_expired(now=0))
        with patch('time.time',return_value=100):
            store = KVStore()
            store.set('expired','old',0)
            store.set('keep','value')
            self.assertEqual(json.loads(store.export_json()),{'keep':'value'})
            self.assertIsNone(store.get('expired'))
            self.assertNotIn('expired',store._store)
            self.assertEqual(store.import_json('{"new":"v","keep":"changed"}'),2)
            self.assertEqual(store.get('keep'),'changed')
            self.assertEqual(store.get('new'),'v')
            self.assertEqual(store.import_json('{}'),0)
            self.assertTrue(store.delete('new'))
            self.assertFalse(store.delete('new'))

    def test_pagination_generated_cases(self):
        if task != 'pagination': self.skipTest('Other task')
        from models import Record
        from service import list_records
        rng = random.Random(173)
        rows = [Record(i,rng.choice(['a','b']),rng.choice(['open','closed']),rng.randrange(5)) for i in range(30)]
        rng.shuffle(rows)
        original = list(rows)
        for owner in ['a','b','missing']:
            for status in [None,'open','closed']:
                expected = sorted([r for r in rows if r.owner==owner and (status is None or r.status==status)],key=lambda r:(-r.created_at,r.id))
                for page in [1,2,5]:
                    for size in [1,3,50]:
                        actual = list_records(rows,owner,status,page,size)
                        self.assertEqual(actual,{'items':expected[(page-1)*size:page*size],'total':len(expected)})
                        self.assertEqual(rows,original)
        for page,size in [(0,1),(1,0),(-2,3),(2,-3)]:
            with self.assertRaises(ValueError): list_records(rows,'a',page=page,page_size=size)

if __name__ == '__main__': unittest.main(argv=[sys.argv[0]])
