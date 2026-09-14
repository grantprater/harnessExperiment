"""Integrity checks for the larger experiment's shared interface."""
import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import large_controlled as driver

def b64(value): return base64.b64encode(value.encode()).decode()

class InterfaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        patcher = patch.object(driver,'HOME',self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.run = self.home/'runs'/'quote_1_adaptive'
        self.work = self.run/'work'
        (self.work/'dispatchdesk').mkdir(parents=True)
        (self.work/'dispatchdesk/__init__.py').write_text('')
        (self.work/'dispatchdesk/code.py').write_text('def answer():\n    return 41\n')
        (self.work/'test_contract.py').write_text('import unittest\nfrom dispatchdesk.code import answer\nclass T(unittest.TestCase):\n    def test_answer(self): self.assertEqual(answer(),42)\n')
        driver.save(self.run/'state.json',{'run_id':'quote_1_adaptive','task':'quote','started':None,'finished':False,'actions':[],'mode':'adaptive','initial_hashes':driver.hashes(self.work)})

    def act(self,verb,*args):
        with contextlib.redirect_stdout(io.StringIO()): driver.action('quote_1_adaptive',verb,list(args))
        return json.loads((self.run/'state.json').read_text())

    def test_adaptive_can_choose_all_views(self):
        for verb,args in [('file',[]),('outline',[]),('symbol',['answer']),('region',['1','2'])]:
            state = self.act(verb,'dispatchdesk/code.py',*args)
            self.assertFalse(state['actions'][-1]['error'])
        self.assertIn('return 41',state['actions'][-1]['result'])

    def test_modes_restrict_only_observation(self):
        for mode,rejected in [('full','outline'),('foveated','file')]:
            state = json.loads((self.run/'state.json').read_text())
            state['mode'] = mode
            driver.save(self.run/'state.json',state)
            state = self.act(rejected,'dispatchdesk/code.py')
            self.assertTrue(state['actions'][-1]['error'])
            state = self.act('search','answer')
            self.assertFalse(state['actions'][-1]['error'])

    def test_exact_edit_and_independent_finish(self):
        self.act('edit','dispatchdesk/code.py',b64('return 41'),b64('return 42'))
        state = self.act('finish')
        self.assertTrue(state['success'])

    def test_ambiguous_or_invalid_edit_is_atomic(self):
        before = (self.work/'dispatchdesk/code.py').read_bytes()
        for old,new in [('missing','x'),('return 41','if')]:
            state = self.act('edit','dispatchdesk/code.py',b64(old),b64(new))
            self.assertTrue(state['actions'][-1]['error'])
            self.assertEqual((self.work/'dispatchdesk/code.py').read_bytes(),before)

    def test_protected_files_paths_and_range(self):
        for verb,args in [('edit',['test_contract.py',b64('41'),b64('42')]),('file',['../held_out.py']),('region',['dispatchdesk/code.py','1','41'])]:
            state = self.act(verb,*args)
            self.assertTrue(state['actions'][-1]['error'])

    def test_failed_finish_not_success(self):
        self.assertFalse(self.act('finish')['success'])

if __name__=='__main__': unittest.main()
