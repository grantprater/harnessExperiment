"""Evidence-linked refinement records using the existing journal/artifact store.

Records describe scoped experimental support, not deployment authorization or
universally true beliefs. Candidate activation remains a separate mechanism.
"""
from copy import deepcopy
import json
from reticle.runtime.observation_delta import encoded, fingerprint

VERSION = 'refinement-record-v1'
STATUSES = {'proposed', 'scoped_support', 'inconclusive', 'rejected'}


class RefinementRecords:
    def __init__(self, runtime):
        self.runtime = runtime

    def save(self, record, *, evidence=None, previous_artifact_id=None):
        record = deepcopy(record)
        required = {'id', 'hypothesis', 'weakness', 'implementation', 'conditions',
                    'verified_properties', 'limitations', 'status'}
        if not required <= record.keys() or record['status'] not in STATUSES:
            raise ValueError('Incomplete refinement record or invalid status')
        if any(not isinstance(record[key], str) or not record[key].strip()
               for key in ('id', 'hypothesis', 'weakness')):
            raise ValueError('Identity and claims must be nonempty strings')
        for key in ('conditions', 'verified_properties', 'limitations'):
            if not isinstance(record[key], list) or not record[key] or any(
                    not isinstance(v, str) or not v.strip() for v in record[key]):
                raise ValueError('Conditions, properties and limitations must be explicit lists')
        implementation = record['implementation']
        if not isinstance(implementation, dict) or not all(
                isinstance(implementation.get(key), str) and implementation[key]
                for key in ('version', 'source_sha256')):
            raise ValueError('Implementation must be versioned and fingerprinted')
        if record['status'] == 'scoped_support':
            if not isinstance(evidence, dict) or evidence.get('decision') != 'scoped_support':
                raise ValueError('Scoped support requires comparative evidence')
            if not evidence.get('protocol_id') or not evidence.get('scope'):
                raise ValueError('Evidence needs a protocol and scope')
            trials = evidence.get('trials', [])
            if not trials or any(t.get('accepted') is not True or not isinstance(t.get('usage'), dict)
                                 for t in trials):
                raise ValueError('Scoped support requires accepted, usage-reported trials')
            totals = {}
            pairs = {}
            for trial in trials:
                usage = trial['usage']
                values = [usage.get('prompt_tokens'), usage.get('completion_tokens')]
                if any(type(v) is not int or v < 0 for v in values):
                    raise ValueError('Usage must be complete and nonnegative')
                totals.setdefault(trial['arm'], []).append(sum(values))
                key = trial.get('case')
                if not isinstance(key, str) or trial['arm'] in pairs.setdefault(key, set()):
                    raise ValueError('Comparisons require distinct case/arm pairs')
                pairs[key].add(trial['arm'])
            if (set(totals) != {'full', 'adaptive'} or len(totals['full']) != len(totals['adaptive'])
                    or any(arms != {'full', 'adaptive'} for arms in pairs.values())
                    or sum(totals['adaptive']) >= sum(totals['full'])):
                raise ValueError('Scoped support requires lower comparative total tokens')
        if previous_artifact_id:
            previous = self.load(previous_artifact_id)
            if previous['record']['id'] != record['id']:
                raise ValueError('Revision must refer to the same refinement')
        # Evidence is stored independently, with immutable ancestry.
        parents = [previous_artifact_id] if previous_artifact_id else []
        evidence_id = None
        if evidence is not None:
            event = self.runtime.journal.append('refinement_evidence', {
                'refinement_id': record['id'], 'evidence_sha256': fingerprint(evidence)})
            artifact = self.runtime.artifacts.put(encoded(evidence), media_type='application/json',
                producer_event_id=event.event_id, labels=['refinement-evidence'])
            evidence_id = artifact.artifact_id
            parents.append(evidence_id)
        value = {'version': VERSION, 'record': record, 'evidence_artifact_id': evidence_id,
                 'previous_artifact_id': previous_artifact_id}
        event = self.runtime.journal.append('refinement_record', {
            'refinement_id': record['id'], 'status': record['status'], 'sha256': fingerprint(value)})
        artifact = self.runtime.artifacts.put(encoded(value), media_type='application/json',
            producer_event_id=event.event_id, parent_artifact_ids=parents, labels=['refinement-record'])
        return artifact.artifact_id

    def load(self, artifact_id):
        value = json.loads(self.runtime.artifacts.read(artifact_id))
        if value.get('version') != VERSION:
            raise ValueError('Unsupported refinement record')
        return value
