"""Knowledge transfer, immutable snapshots, and dependency-change controls."""
import json
import importlib.util
from pathlib import Path
import tempfile
import unittest

from reticle.runtime.knowledge import KnowledgeLibrary, KnowledgeView, digest, load_snapshot, propose_experiments
from reticle.runtime.reasoning import EvidenceOntology
from reticle.runtime.session import LocalRuntime
from reticle.tools.primitives import ToolSuite
from reticle.tools.knowledge import KnowledgeTools


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ('rdflib', 'pyshacl')),
                     'install reticle[reasoning] for knowledge tests')
class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.workspace / 'protocol.py').write_text('UNITS = "milliseconds"\n')
        self.runtime = LocalRuntime(self.root / 'source', self.workspace)
        self.reasoning = EvidenceOntology(self.runtime, 'memory')
        tools = ToolSuite(self.runtime, interpreter=__import__('sys').executable)
        tools.dispatch('read_file', {'path': 'protocol.py'}, 'read')
        observations = [entity for entity in self.reasoning.state()['entities'] if entity['kind'] == 'observation']
        evidence = observations[-1]['evidence']
        self.reasoning.update(entities=[
            {'id': 'code', 'kind': 'code_entity', 'text': 'Timeout protocol', 'path': 'protocol.py', 'evidence': evidence},
            {'id': 'rule', 'kind': 'hypothesis', 'text': 'Timeout values are milliseconds', 'evidence': evidence},
            {'id': 'procedure', 'kind': 'procedure', 'text': 'Divide timeout by 1000 to get seconds',
             'conditions': ['Protocol still uses milliseconds'], 'evidence': evidence},
        ], relations=[{'source': 'rule', 'relation': 'depends_on', 'target': 'code'},
                      {'source': 'procedure', 'relation': 'depends_on', 'target': 'rule'}])
        self.library = KnowledgeLibrary(self.root / 'library')
        self.snapshot = self.library.consolidate(self.runtime, self.reasoning)

    def view(self, mode='valid', root=None):
        runtime = LocalRuntime(self.root / ('consumer-' + mode), root or self.workspace)
        return KnowledgeView(runtime, self.snapshot, mode)

    def test_transfer_and_transitive_regime_invalidation(self):
        fresh = self.root / 'fresh'
        fresh.mkdir()
        (fresh / 'protocol.py').write_text('UNITS = "milliseconds"\n')
        view = self.view(root=fresh)
        result = view.retrieve('timeout seconds')
        self.assertEqual(view.snapshot_id, digest(load_snapshot(self.snapshot)))
        self.assertFalse(view.recheck())
        (fresh / 'irrelevant').write_text('changed elsewhere')
        self.assertFalse(view.recheck())
        (fresh / 'protocol.py').write_text('UNITS = "seconds"\n')
        findings = view.recheck()
        self.assertTrue(any(item['id'].endswith(':procedure') for item in findings))
        self.assertTrue(any(item['id'].endswith(':rule') for item in findings))
        self.assertTrue(result['records'])

    def test_supersession_and_missing_dependencies(self):
        data = load_snapshot(self.snapshot)
        entities = data['entities']
        old = next(key for key in entities if key.endswith(':rule'))
        revised = old + '-revised'
        entities[revised] = {**entities[old], 'id': revised, 'text': 'Revised timeout interpretation'}
        data['relations'].append({'source': revised, 'relation': 'supersedes', 'target': old})
        path = self.root / 'revision.json'
        path.write_text(json.dumps({'snapshot_id': digest(data), 'data': data}))
        view = KnowledgeView(self.runtime, path)
        states, _ = view.validity()
        self.assertEqual(states[old], 'superseded')
        self.assertEqual(next(states[key] for key in states if key.endswith(':procedure')), 'needs_recheck')
        (self.workspace / 'protocol.py').unlink()
        states, _ = view.validity()
        self.assertEqual(next(states[key] for key in states if key.endswith(':code')), 'needs_recheck')

    def test_frozen_snapshot_and_detection_of_tampering(self):
        view = self.view()
        before = self.snapshot.read_bytes()
        self.library.consolidate(self.runtime, self.reasoning)
        self.assertEqual(self.snapshot.read_bytes(), before)
        self.assertEqual(view.snapshot_id, digest(load_snapshot(self.snapshot)))
        value = json.loads(before)
        value['data']['entities'].pop(next(iter(value['data']['entities'])))
        corrupt = self.root / 'corrupt.json'
        corrupt.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'digest'):
            load_snapshot(corrupt)

    def test_three_modes_share_corpus_no_warning_in_controls(self):
        (self.workspace / 'protocol.py').write_text('UNITS = "seconds"\n')
        results = {mode: self.view(mode).retrieve('timeout seconds') for mode in ('transcript', 'graph', 'valid')}
        ids = lambda result: [item['id'] for item in result['records']]
        self.assertEqual(ids(results['graph']), ids(results['valid']))
        self.assertEqual(results['graph']['snapshot_id'], results['transcript']['snapshot_id'])
        text = self.view('transcript').retrieve('milliseconds')
        self.assertTrue(text['records'])
        self.assertTrue(all('record_text' in item for item in text['records']))
        self.assertTrue(all('validity' not in item for item in results['graph']['records']))
        self.assertTrue(any(item.get('validity') == 'needs_recheck' for item in results['valid']['records']))

    def test_bounded_retrieval_and_automatic_edit_findings(self):
        view = self.view()
        view.retrieve('timeout seconds')
        cls = type('Tools', (KnowledgeTools, ToolSuite), {})
        tools = cls(view.runtime, interpreter=__import__('sys').executable, knowledge=view)
        outcome = tools.dispatch('write_file', {'path': 'protocol.py', 'content': 'UNITS = "seconds"'}, 'edit')
        self.assertIn('needs_recheck', outcome.content)
        self.assertEqual(tools._resolve_output(outcome.handle).decode(), outcome.content)
        small = KnowledgeView(view.runtime, self.snapshot, max_bytes=800)
        result = small.retrieve('timeout seconds')
        from reticle.runtime.knowledge import encoded
        self.assertLessEqual(len(encoded(result)), 800)
        self.assertTrue(result['truncated'])

    def test_assertion_fingerprint_is_not_recaptured_at_export(self):
        (self.workspace / 'protocol.py').write_text('UNITS = "seconds"\n')
        snapshot = self.library.consolidate(self.runtime, self.reasoning)
        view = KnowledgeView(self.runtime, snapshot)
        states, _ = view.validity()
        self.assertTrue(any(value == 'needs_recheck' for value in states.values()))

    def test_outer_loop_proposals_link_to_repeated_observations(self):
        view = self.view()
        (self.workspace / 'protocol.py').write_text('UNITS = "seconds"\n')
        view.retrieve('timeout seconds')
        snapshot = self.library.consolidate(view.runtime, EvidenceOntology(view.runtime, 'memory'))
        self.assertFalse(propose_experiments(snapshot))
        second = KnowledgeView(LocalRuntime(self.root / 'another-consumer', self.workspace), self.snapshot)
        second.retrieve('timeout units')
        snapshot = self.library.consolidate(second.runtime, EvidenceOntology(second.runtime, 'memory'))
        proposals = propose_experiments(snapshot)
        self.assertEqual(proposals[0]['issue'], 'stale_dependencies')
        self.assertEqual(proposals[0]['occurrences'], 2)
        self.assertEqual(proposals[0]['status'], 'hypothesis_to_test')

    def test_contradictory_evidence_requires_rechecking(self):
        data = load_snapshot(self.snapshot)
        claim = next(key for key in data['entities'] if key.endswith(':rule'))
        observation = next(key for key, value in data['entities'].items() if value['kind'] == 'observation')
        data['relations'].append({'source': observation, 'relation': 'contradicts', 'target': claim})
        path = self.root / 'contradiction.json'
        path.write_text(json.dumps({'snapshot_id': digest(data), 'data': data}))
        states, reasons = KnowledgeView(self.runtime, path).validity()
        self.assertEqual(states[claim], 'needs_recheck')
        self.assertIn('asserted', reasons[claim][0])

    def test_invalid_tool_arguments_return_journaled_rejection(self):
        view = self.view()
        cls = type('Tools', (KnowledgeTools, ToolSuite), {})
        tools = cls(view.runtime, interpreter=__import__('sys').executable, knowledge=view)
        result = tools.dispatch('knowledge_search', {}, 'invalid')
        self.assertEqual(result.status, 'rejected')
        self.assertIn('query', result.content)
