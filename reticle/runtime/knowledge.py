"""Immutable, evidence-linked knowledge snapshots and bounded retrieval.

Source journals remain authoritative. Imported claims are assertions, not instructions
or acceptance decisions. Dependency completeness and semantic relevance remain unknown.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from reticle.runtime.ownership import SessionWriterLock
from reticle.storage.artifacts import atomic_write_json

VERSION = 'knowledge-snapshot-v1'
MODES = ('transcript', 'graph', 'valid')
MAX_ENTITIES = 3000


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


class KnowledgeLibrary:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def latest(self):
        path = self.root / 'latest.json'
        if not path.exists():
            return None
        snapshot_id = json.loads(path.read_text(encoding='utf-8'))['snapshot_id']
        if not re.fullmatch(r'[0-9a-f]{64}', snapshot_id):
            raise ValueError('Invalid knowledge snapshot ID')
        return self.root / 'snapshots' / (snapshot_id + '.json')

    def consolidate(self, runtime, reasoning):
        """Retain explicit assertions with their authorized evidence; no extra model call."""
        with SessionWriterLock(self.root).acquire('knowledge-' + uuid4().hex):
            previous = self.latest()
            value = load_snapshot(previous) if previous else {
                'version': VERSION, 'entities': {}, 'relations': [], 'sessions': {}, 'feedback': [], 'history': {}}
            # The session must be idle when exported; lock its journal while projecting.
            with SessionWriterLock(runtime.session_dir).acquire('knowledge-export-' + uuid4().hex):
                entities, relations, events = reasoning._projection()
                prefix = hashlib.sha256(str(runtime.session_dir).encode()).hexdigest()[:16] + ':'
                namespace = lambda key: prefix + key
                for key, entity in entities.items():
                    item = deepcopy(entity)
                    item['id'] = namespace(key)
                    item['source_session'] = prefix[:-1]
                    item['evidence'] = [namespace(ref) for ref in entity['evidence']]
                    if item.get('observation'):
                        item['observation'] = namespace(item['observation'])
                    if item.get('predictions'):
                        item['predictions'] = {namespace(k): v for k, v in item['predictions'].items()}
                    value['entities'][item['id']] = item
                for link in relations:
                    item = dict(source=namespace(link['source']), relation=link['relation'], target=namespace(link['target']))
                    if item not in value['relations']:
                        value['relations'].append(item)
                value['sessions'][prefix[:-1]] = {
                    'session_dir': str(runtime.session_dir), 'workspace': str(runtime.workspace.root),
                    'high_water_sequence': events[-1].sequence if events else 0}
                from reticle.runtime.queries import SessionQueryService
                records = SessionQueryService(runtime)._visible_records(events, events,
                                                                         kinds=['tool_output', 'transcript_message'])
                history = value.setdefault('history', {})
                for record in records:
                    if record['source'] in ('reasoning_state', 'assess_check'):
                        continue
                    key = namespace(record['event_id'])
                    history[key] = {'id': key, 'source_session': prefix[:-1], 'source': record['source'],
                                    'text': record['text'][:4000], 'source_event': record['event_id'],
                                    'truncated': len(record['text']) > 4000}
                # Store only explicit, bounded retrieval/controller summaries, never evaluator artifacts.
                value['feedback'] = [f for f in value['feedback'] if f['session'] != prefix[:-1]]
                for event in events:
                    if event.kind in ('knowledge_retrieval', 'knowledge_feedback'):
                        value['feedback'].append({'session': prefix[:-1], 'kind': event.kind, 'payload': event.payload})
            if len(value['entities']) > MAX_ENTITIES or len(value['relations']) > 6000 or len(value['history']) > 6000:
                raise ValueError('Knowledge capacity reached; use a new scoped library rather than silently dropping evidence')
            value['feedback'] = value['feedback'][-1000:]
            snapshot_id = digest(value)
            target = self.root / 'snapshots' / (snapshot_id + '.json')
            if not target.exists():
                atomic_write_json(target, {'snapshot_id': snapshot_id, 'data': value})
            atomic_write_json(self.root / 'latest.json', {'snapshot_id': snapshot_id})
            return target


def load_snapshot(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    data = value['data']
    if data.get('version') != VERSION or value.get('snapshot_id') != digest(data):
        raise ValueError('Knowledge snapshot version or digest is invalid')
    if len(data['entities']) > MAX_ENTITIES or len(data['relations']) > 6000:
        raise ValueError('Knowledge snapshot exceeds bounds')
    if not all(link['source'] in data['entities'] and link['target'] in data['entities']
               for link in data['relations']):
        raise ValueError('Knowledge snapshot has an unknown relation endpoint')
    return data


class KnowledgeView:
    def __init__(self, runtime, snapshot, mode='valid', max_bytes=10000):
        if mode not in MODES or type(max_bytes) is not int or max_bytes < 512:
            raise ValueError('Invalid knowledge mode or retrieval budget')
        self.runtime, self.mode, self.max_bytes = runtime, mode, max_bytes
        self.data = load_snapshot(snapshot)
        self.snapshot_id = digest(self.data)
        self.used = set()

    def validity(self):
        entities, relations = self.data['entities'], self.data['relations']
        states, reasons = {}, {}
        superseded = {r['target'] for r in relations if r['relation'] == 'supersedes'}
        dependencies = {}
        for link in relations:
            if link['relation'] == 'depends_on':
                dependencies.setdefault(link['source'], []).append(link['target'])
        for key, entity in entities.items():
            states[key] = 'unknown'
            if key in superseded:
                states[key], reasons[key] = 'superseded', ['A newer assertion supersedes this one']
            elif entity['kind'] == 'code_entity' and entity.get('path') and entity.get('content_hash'):
                try:
                    path = self.runtime.workspace._resolve(entity['path'])
                    current = hashlib.sha256(path.read_bytes()).hexdigest()
                except (OSError, ValueError):
                    current = None
                states[key] = 'unchanged' if current == entity['content_hash'] else 'needs_recheck'
                reasons[key] = [entity['path'] + (' fingerprint matches' if current == entity['content_hash']
                                                else ' changed, disappeared, or is outside this workspace')]
        for link in relations:
            if link['relation'] == 'contradicts' and states[link['target']] != 'superseded':
                states[link['target']] = 'needs_recheck'
                reasons.setdefault(link['target'], []).append(
                    'An observation is asserted to contradict this claim: ' + link['source'])
        # Fixed point propagates stale/superseded dependencies through assertions.
        for _ in range(len(entities)):
            changed = False
            for key, targets in dependencies.items():
                if states[key] == 'superseded':
                    continue
                bad = [target for target in targets if states[target] in ('needs_recheck', 'superseded')]
                if bad and states[key] != 'needs_recheck':
                    states[key], reasons[key] = 'needs_recheck', ['Dependency ' + target + ' requires rechecking' for target in bad]
                    changed = True
            if not changed:
                break
        return states, reasons

    def retrieve(self, query, limit=5):
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError('query must contain 1-4000 characters')
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('limit must be between 1 and 20')
        if self.mode == 'transcript':
            return self._retrieve_transcript(query, limit)
        entities, links = self.data['entities'], self.data['relations']
        terms = set(re.findall(r'[a-z0-9_]+', query.lower()))
        ranked = []
        for key, entity in entities.items():
            tokens = set(re.findall(r'[a-z0-9_]+', (entity['text'] + ' ' + entity.get('path', '')).lower()))
            matches = sorted(terms & tokens)
            if matches:
                ranked.append((len(matches) / max(1, len(terms)), key, matches))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        seeds = ranked[:limit]
        selected = {key for _, key, _ in seeds}
        # Include bounded adjacent evidence/dependencies for the same seed selection in all arms.
        for _ in range(2):
            neighbors = {endpoint for link in links if link['source'] in selected
                         for endpoint in (link['source'], link['target'])}
            neighbors |= {item.get('observation') for key, item in entities.items() if key in selected and item.get('observation')}
            evidence = {ref for key in selected for ref in entities[key].get('evidence', [])}
            neighbors |= {key for key, item in entities.items() if item['origin'] == 'runtime_observation'
                          and evidence.intersection(item['evidence'])}
            selected |= set(sorted(neighbors - selected)[:max(0, 25 - len(selected))])
        # All arms receive the same selected base records and relations; valid adds calculated findings.
        selected_links = [link for link in links if link['source'] in selected and link['target'] in selected]
        states, reasons = self.validity() if self.mode == 'valid' else ({}, {})
        output = {'snapshot_id': self.snapshot_id, 'mode': self.mode, 'advisory': True,
                  'matched_terms': {key: matches for _, key, matches in seeds},
                  'dependency_completeness': 'unknown; dependency links and applicability are assertions',
                  'records': [], 'relations': [], 'truncated': False}
        order = [key for _, key, _ in seeds] + sorted(selected - {key for _, key, _ in seeds})
        retained = set()
        for key in order:
            item = deepcopy(entities[key])
            if self.mode == 'valid':
                item['validity'] = states[key]
                item['validity_reasons'] = reasons.get(key, [])
            if self.mode == 'transcript':
                item = {'id': key, 'record_text': json.dumps(item, sort_keys=True)}
            output['records'].append(item)
            if len(encoded(output)) > self.max_bytes:
                output['records'].pop()
                output['truncated'] = True
                break
            retained.add(key)
        for link in selected_links:
            if link['source'] in retained and link['target'] in retained:
                output['relations'].append(link)
                if len(encoded(output)) > self.max_bytes:
                    output['relations'].pop()
                    output['truncated'] = True
                    break
        if len(encoded(output)) > self.max_bytes:
            output['matched_terms'] = {}
            output['truncated'] = True
        self.used |= retained
        self.runtime.journal.append('knowledge_retrieval', {
            'snapshot_id': self.snapshot_id, 'mode': self.mode, 'query': query, 'ids': sorted(retained),
            'needs_recheck': sorted(key for key in retained if states.get(key) == 'needs_recheck'),
            'result_hash': digest(output), 'bytes': len(encoded(output)), 'truncated': output['truncated']})
        return output

    def _retrieve_transcript(self, query, limit):
        terms = set(re.findall(r'[a-z0-9_]+', query.lower()))
        ranked = []
        for key, record in self.data.get('history', {}).items():
            matches = terms & set(re.findall(r'[a-z0-9_]+', record['text'].lower()))
            if matches:
                ranked.append((len(matches) / len(terms), key))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        result = {'snapshot_id': self.snapshot_id, 'mode': self.mode, 'advisory': True,
                  'records': [], 'truncated': False,
                  'scope': 'Authorized prior transcript/tool-output excerpts; applicability is not established'}
        for _, key in ranked[:limit]:
            record = self.data['history'][key]
            result['records'].append({'id': key, 'record_text': record['text'],
                                      'source_session': record['source_session'], 'source_event': record['source_event']})
            if len(encoded(result)) > self.max_bytes:
                result['records'].pop()
                result['truncated'] = True
                break
        self.runtime.journal.append('knowledge_retrieval', {
            'snapshot_id': self.snapshot_id, 'mode': self.mode, 'query': query,
            'ids': [item['id'] for item in result['records']], 'needs_recheck': [],
            'result_hash': digest(result), 'bytes': len(encoded(result)), 'truncated': result['truncated']})
        return result

    def recheck(self):
        if self.mode != 'valid':
            return []
        states, reasons = self.validity()
        return [{'id': key, 'status': states[key], 'reasons': reasons.get(key, [])}
                for key in sorted(self.used) if states[key] in ('needs_recheck', 'superseded')]


def propose_experiments(snapshot):
    """Bounded outer-loop hypotheses from repeated observed retrieval issues."""
    data = load_snapshot(snapshot)
    counts, evidence = {}, {}
    for item in data['feedback']:
        if item['kind'] != 'knowledge_retrieval':
            continue
        payload = item['payload']
        issue = 'stale_dependencies' if payload.get('needs_recheck') else (
            'retrieval_truncation' if payload.get('truncated') else ('no_match' if not payload.get('ids') else None))
        if issue:
            counts[issue] = counts.get(issue, 0) + 1
            evidence.setdefault(issue, set()).add(item['session'])
    return [{'issue': issue, 'occurrences': count, 'source_sessions': sorted(evidence[issue]),
             'status': 'hypothesis_to_test', 'acceptance': 'Improve verified fresh-task completion at matched budgets',
             'next_step': 'Compare one retrieval or revalidation change against the incumbent on untouched tasks'}
            for issue, count in sorted(counts.items(), key=lambda item: -item[1]) if len(evidence[issue]) >= 2][:3]
