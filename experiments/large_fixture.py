"""Deterministic synthetic DispatchDesk source repository and seeded defects.

All golden and held-out checks are defined before trial launch. Generated
resource adapters deliberately have regular structure; this is not a natural
repository sample and must not be described as one.
"""
from __future__ import annotations
import textwrap

RESOURCES = 'account carrier container customer delivery invoice item location manifest order parcel payment pickup product route warehouse'.split()
TASKS = {
    'quote': 'quote_order produces excessive tax when a promotion is applied. Tax must use the discounted merchandise amount. Preserve quantity, shipping, and currency-rounding behavior. Fix the implementation and verify.',
    'cache': 'FeedCache leaks cached feed results between tenants and between status filters. Requests for the same tenant, status, and page may reuse an entry, but distinct tenants, status filters, or pages must remain independent. Entries must expire at their TTL boundary. Preserve the public FeedCache.get API and verify.',
    'feed': 'list_events returns incorrect pages and totals. Filter by tenant and optional status before pagination; order newest first with ascending event id for ties. Total must count all matching events, even for an empty page. Pages are one-based and page/page_size must be positive. Preserve input events and verify.',
}

def clean(source): return textwrap.dedent(source).lstrip('\n')

CORE = {
    'dispatchdesk/__init__.py': '"""DispatchDesk: synthetic dispatch and order operations library."""\n',
    'dispatchdesk/billing/__init__.py': '',
    'dispatchdesk/billing/models.py': clean('''
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class LineItem:
            sku: str
            quantity: int
            unit_price: float

        @dataclass(frozen=True)
        class Quote:
            subtotal: float
            discount: float
            taxable: float
            tax: float
            shipping: float
            total: float
    '''),
    'dispatchdesk/billing/service.py': clean('''
        from .models import Quote
        from .pricing import merchandise_total, promotion_amount, sales_tax, shipping_charge

        def quote_order(items, discount_percent=0.0, tax_rate=0.0):
            """Quote merchandise, promotion, tax, and post-promotion shipping."""
            subtotal = merchandise_total(items)
            discount = promotion_amount(subtotal, discount_percent)
            taxable = round(subtotal - discount, 2)
            tax = sales_tax(taxable, tax_rate)
            shipping = shipping_charge(taxable)
            return Quote(subtotal, discount, taxable, tax, shipping,
                         round(taxable + tax + shipping, 2))
    '''),
    'dispatchdesk/billing/pricing.py': clean('''
        """Pricing rules and reusable tariff-report transformations."""
        import math

        def merchandise_total(items):
            """Sum line amounts, rounding each line to cents."""
            return round(sum(round(item.quantity * item.unit_price, 2) for item in items), 2)

        def promotion_amount(subtotal, percent):
            """Return a percentage discount in currency units."""
            if not 0 <= percent <= 100:
                raise ValueError("Percentage must be between 0 and 100")
            return round(subtotal * percent / 100, 2)

        def sales_tax(taxable, rate):
            """Round tax on the supplied taxable amount to currency precision."""
            return round(taxable * rate, 2)

        def shipping_charge(amount):
            """Shipping is free for a qualifying amount of at least 150."""
            return 0.0 if amount >= 150 else 15.0
    '''),
    'dispatchdesk/events/__init__.py': '',
    'dispatchdesk/events/models.py': clean('''
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class Event:
            id: int
            tenant: str
            status: str
            created_at: int
            payload: str = ""
    '''),
    'dispatchdesk/events/query.py': clean('''
        """Event selection and projection utilities."""

        def select_events(events, tenant, status=None):
            """Return matching events without mutating the input."""
            return [e for e in events if e.tenant == tenant and (status is None or e.status == status)]

        def order_events(events):
            """Newest first, ascending id for tied timestamps."""
            return sorted(events, key=lambda e: (-e.created_at, e.id))

        def take_page(events, page, page_size):
            """Select a positive, one-based page."""
            if page <= 0 or page_size <= 0:
                raise ValueError("Page and page_size must be positive")
            start = (page - 1) * page_size
            return events[start:start + page_size]
    '''),
    'dispatchdesk/events/service.py': clean('''
        from .query import select_events, order_events, take_page

        def list_events(events, tenant, status=None, page=1, page_size=20):
            """Return items and total for a tenant-scoped event feed."""
            selected = order_events(select_events(events, tenant, status))
            return {"items": take_page(selected, page, page_size), "total": len(selected)}
    '''),
    'dispatchdesk/cache/__init__.py': '',
    'dispatchdesk/cache/keys.py': clean('''
        """Cache key normalization."""

        def feed_key(tenant, status, page):
            """Build an immutable identity for a feed request."""
            return (tenant, status, page)

        def document_key(tenant, document_id):
            return ("document", tenant, document_id)

        def cache_namespace(environment, version):
            return f"{environment}:v{version}"
    '''),
    'dispatchdesk/cache/storage.py': clean('''
        """Clock-injected in-memory cache backend."""
        from dataclasses import dataclass

        @dataclass
        class Entry:
            value: object
            expires_at: float

            def expired(self, now):
                return now >= self.expires_at

        class MemoryBackend:
            def __init__(self):
                self.entries = {}

            def lookup(self, key, now):
                entry = self.entries.get(key)
                if entry is None:
                    return None
                if entry.expired(now):
                    del self.entries[key]
                    return None
                return entry

            def put(self, key, value, expires_at):
                self.entries[key] = Entry(value, expires_at)

            def clear(self):
                self.entries.clear()
    '''),
    'dispatchdesk/cache/service.py': clean('''
        """Caching facade for materialized event feeds."""
        import time
        from .keys import feed_key
        from .storage import MemoryBackend

        class FeedCache:
            def __init__(self, ttl=30.0, clock=None):
                self.ttl = ttl
                self.clock = clock or time.time
                self.backend = MemoryBackend()

            def get(self, tenant, status, page, loader):
                """Reuse a matching unexpired entry, otherwise call loader()."""
                now = self.clock()
                key = feed_key(tenant, status, page)
                entry = self.backend.lookup(key, now)
                if entry is not None:
                    return entry.value
                value = loader()
                self.backend.put(key, value, now + self.ttl)
                return value
    '''),
    'dispatchdesk/resources/__init__.py': '',
}

PUBLIC = clean('''
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
''')

HIDDEN = clean('''
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
''')

def adapters(resource):
    prefix = f'dispatchdesk/resources/{resource}/'
    model = clean(f'''
        """Record schema and transformations for {resource} operations."""
        from dataclasses import dataclass, replace

        @dataclass(frozen=True)
        class Record:
            id: str
            tenant: str
            name: str = ""
            status: str = "active"
            amount: float = 0.0
            quantity: int = 0
            priority: int = 0
            created_at: int = 0
            updated_at: int = 0
            region: str = ""
            category: str = ""
            archived: bool = False

        def new_record(record_id, tenant, **attributes):
            """Construct a typed {resource} record."""
            return Record(id=record_id, tenant=tenant, **attributes)
    ''')
    fields = [('name','str'),('status','str'),('amount','float'),('quantity','int'),('priority','int'),('created_at','int'),('updated_at','int'),('region','str'),('category','str'),('archived','bool')]
    for field,kind in fields:
        model += f'\n\ndef with_{field}(record, value):\n    """Return a copy with normalized {field}."""\n    return replace(record, {field}={kind}(value))\n'
        model += f'\n\ndef same_{field}(left, right):\n    """Compare {field} across two records."""\n    return left.{field} == right.{field}\n'
    codec = clean(f'''
        """JSON and flat-column codecs for {resource} records."""
        import json
        from dataclasses import asdict
        from .model import Record

        def encode(record):
            return json.dumps(asdict(record), sort_keys=True)

        def decode(payload):
            return Record(**json.loads(payload))

        def encode_many(records):
            return json.dumps([asdict(record) for record in records], sort_keys=True)

        def decode_many(payload):
            return [Record(**row) for row in json.loads(payload)]

        def flatten(record):
            return asdict(record)
    ''')
    query = clean(f'''
        """Tenant-scoped {resource} query helpers."""
        def for_tenant(records, tenant):
            return [r for r in records if r.tenant == tenant]

        def by_id(records, record_id):
            return next((r for r in records if r.id == record_id), None)

        def active(records):
            return [r for r in records if not r.archived]
    ''')
    policy = clean(f'''
        """Authorization and transitions for {resource} records."""
        def can_read(record, tenant):
            return record.tenant == tenant

        def can_write(record, tenant):
            return can_read(record, tenant) and not record.archived

        def can_archive(record, tenant):
            return can_write(record, tenant) and record.status != "pending"
    ''')
    for field,kind in fields:
        codec += f'\n\ndef {field}_column(records):\n    """Extract a {field} column for export."""\n    return [r.{field} for r in records]\n'
        codec += f'\n\ndef parse_{field}(value):\n    """Coerce a typed {field} value."""\n    return {kind}(value)\n'
        query += f'\n\ndef with_{field}(records, value):\n    """Filter records by exact {field}."""\n    return [r for r in records if r.{field} == value]\n'
        query += f'\n\ndef order_by_{field}(records):\n    """Stable ascending sort by {field} and id."""\n    return sorted(records, key=lambda r: (r.{field}, r.id))\n'
        policy += f'\n\ndef can_change_{field}(record, tenant, value):\n    """Allow {field} updates on writable records."""\n    return can_write(record, tenant) and value is not None\n'
        policy += f'\n\ndef {field}_changed(before, after):\n    """Detect a material {field} update."""\n    return before.{field} != after.{field}\n'
    return {prefix+'__init__.py':'',prefix+'model.py':model,prefix+'codec.py':codec,prefix+'query.py':query,prefix+'policy.py':policy}

def report_helpers(prefix, fields):
    """Working scalar aggregation helpers, not blank-line/comment padding."""
    source = ''
    for field in fields:
        source += f'\n\ndef {prefix}_{field}_total(rows):\n    """Sum {field} values in reporting dictionaries."""\n    return sum(row.get("{field}", 0) for row in rows)\n'
        source += f'\n\ndef {prefix}_{field}_mean(rows):\n    """Mean {field}, defaulting to zero for an empty report."""\n    rows = list(rows)\n    return {prefix}_{field}_total(rows) / len(rows) if rows else 0\n'
        source += f'\n\ndef {prefix}_{field}_above(rows, threshold):\n    """Select report dictionaries above a {field} threshold."""\n    return [row for row in rows if row.get("{field}", 0) > threshold]\n'
        source += f'\n\ndef {prefix}_{field}_range(rows):\n    """Return the minimum and maximum {field}, or zeros."""\n    values = [row.get("{field}", 0) for row in rows]\n    return (min(values), max(values)) if values else (0, 0)\n'
    return source

def repository():
    sources = dict(CORE)
    for resource in RESOURCES: sources.update(adapters(resource))
    fields = 'base fuel handling distance weight volume insurance customs tax discount surcharge storage pickup delivery service'.split()
    # Place relevant pricing behavior amid other executable pricing/report code.
    pricing = sources['dispatchdesk/billing/pricing.py']
    before, marker, after = pricing.partition('def sales_tax(')
    sources['dispatchdesk/billing/pricing.py'] = before + report_helpers('tariff',fields[:8]) + '\n\n' + marker+after + report_helpers('tariff',fields[8:])
    query = sources['dispatchdesk/events/query.py']
    before,marker,after = query.partition('def order_events(')
    sources['dispatchdesk/events/query.py'] = before+report_helpers('event','latency attempts size duration retry count priority sequence'.split())+'\n\n'+marker+after+report_helpers('event','age delay backlog throughput'.split())
    sources['test_contract.py'] = PUBLIC
    sources['README.md'] = '# DispatchDesk\n\nSynthetic multi-tenant operations library for a controlled agent benchmark.\n\nPackages cover order quotes, event feeds, feed caching, and typed resource adapters.\nRun `python -B -m unittest test_contract.py` to validate public contracts.\nNo external dependencies. Python 3.10+.\n'
    return sources

MUTATIONS = {
    'quote': [('dispatchdesk/billing/service.py','tax = sales_tax(taxable, tax_rate)','tax = sales_tax(subtotal, tax_rate)')],
    'cache': [('dispatchdesk/cache/keys.py','return (tenant, status, page)','return (page,)'),('dispatchdesk/cache/storage.py','return now >= self.expires_at','return now > self.expires_at')],
    'feed': [
        ('dispatchdesk/events/service.py','selected = order_events(select_events(events, tenant, status))\n    return {"items": take_page(selected, page, page_size), "total": len(selected)}','selected = select_events(take_page(order_events(events), page, page_size), tenant, status)\n    return {"items": selected, "total": len(selected)}'),
        ('dispatchdesk/events/query.py','return sorted(events, key=lambda e: (-e.created_at, e.id))','return sorted(events, key=lambda e: e.created_at, reverse=True)'),
        ('dispatchdesk/events/query.py','start = (page - 1) * page_size','start = page * page_size'),
    ],
}
