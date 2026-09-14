"""Checks for measurement and verification integrity of the pilot driver."""
import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import controlled

class DriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(controlled, 'HOME', self.home).start()
        self.run = self.home / 'runs' / 'billing_1_foveated'
        self.work = self.run / 'work'
        self.work.mkdir(parents=True)
        (self.work / 'code.py').write_text('def answer():\n    return 41\n')
        (self.work / 'test_contract.py').write_text('import unittest\nfrom code import answer\nclass T(unittest.TestCase):\n    def test_answer(self): self.assertEqual(answer(),42)\n')
        controlled.write_json(self.run / 'state.json', {'started':None,'finished':False,'actions':[],'mode':'foveated','initial_hashes':controlled.digest(self.work)})

    def act(self, verb, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            controlled.action('billing_1_foveated',verb,list(args))
        return json.loads((self.run / 'state.json').read_text())

    def test_outline_and_range_cap(self):
        state = self.act('view','code.py')
        self.assertNotIn('return 41',state['actions'][-1]['result'])
        state = self.act('view','code.py','1','41')
        self.assertTrue(state['actions'][-1]['error'])
        state = self.act('view','code.py','1','2')
        self.assertIn('return 41',state['actions'][-1]['result'])

    def test_syntax_error_is_atomic(self):
        before = (self.work/'code.py').read_bytes()
        state = self.act('edit','code.py','2','2',base64.b64encode(b'    if').decode())
        self.assertTrue(state['actions'][-1]['error'])
        self.assertEqual((self.work/'code.py').read_bytes(),before)

    def test_tests_and_unknown_paths_rejected(self):
        for name in ['test_contract.py','../code.py']:
            state = self.act('edit',name,'1','1',base64.b64encode(b'pass').decode())
            self.assertTrue(state['actions'][-1]['error'])

    def test_finish_independently_fails(self):
        state = self.act('finish')
        self.assertTrue(state['finished'])
        self.assertFalse(state['success'])

    def test_success_requires_real_passing_tests(self):
        self.act('edit','code.py','2','2',base64.b64encode(b'    return 42').decode())
        state = self.act('finish')
        self.assertTrue(state['success'])
        self.assertTrue(state['test_integrity'])

if __name__ == '__main__': unittest.main()
