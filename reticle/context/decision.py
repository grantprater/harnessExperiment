"""Versioned decision policy: compact observations, auditable state, bounded escalation."""
import json
import hashlib

from reticle.context.minimal import MinimalContextPolicy
from reticle.runtime.decision_state import decision_state
from reticle.storage.artifacts import atomic_write_json


class DecisionContextPolicy(MinimalContextPolicy):
    policy_version = 'decision-v1'

    def _record(self, runtime, task, messages, tools, max_context_bytes, selected,
                pin_overflow, diagnostics, omitted_items=None):
        state_message = {'role':'user', 'content':self._state_text, '_context_id':'decision-state'}
        # Keep volatile state at the end, beside resource status, rather than
        # changing the beginning of an otherwise reusable request prefix.
        position = len(messages)-1 if messages and messages[-1].get('_context_id') == 'resource-status' else len(messages)
        messages = [*messages[:position], state_message, *messages[position:]]
        selected = [*selected, {'kind':'decision_state', 'state_event_id':self._state_event_id,
                               'rendering':'full', 'next_step_hint':self._state['next_step_hint']}]
        return super()._record(runtime, task, messages, tools, self._original_limit,
                               selected, pin_overflow, diagnostics, omitted_items=omitted_items)

    def build(self, runtime, task, transcript, tools, max_context_bytes,
              diagnostics=None, resource_status=None):
        self._state = decision_state(runtime, task, transcript)
        self.routine_view_bytes = 4096 if self._state['escalation_reasons'] else 1024
        self._original_limit = max_context_bytes
        public_state = dict(self._state)
        if not task.budgets.get('token_target') and not (resource_status or {}).get('model_token_usage'):
            for key in ('reported_total_tokens','usage_complete','token_target'):
                public_state.pop(key, None)
        self._state_text = ('Decision state (observed data; hint, not a required plan). '
                            'Execute known routine steps together; retrieve only information that changes '
                            'the next decision. Diagnose actual failures. No extra narration is required.\n'
                            + json.dumps(public_state, separators=(',', ':')))
        self._state_event_id = runtime.journal.append('decision_state_snapshot', {
            **self._state, 'policy_version':self.policy_version,
            'routine_view_bytes':self.routine_view_bytes}).event_id
        filename = hashlib.sha256(task.task_id.encode('utf-8')).hexdigest() + '.json'
        atomic_write_json(runtime.session_dir/'decision-state'/filename, self._state)
        reserve = len(json.dumps({'role':'user','content':self._state_text}, ensure_ascii=False).encode('utf-8')) + 64
        return super().build(runtime, task, transcript, tools, max(1, max_context_bytes-reserve),
                             diagnostics=diagnostics, resource_status=resource_status)
