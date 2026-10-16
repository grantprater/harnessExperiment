"""Decision-sized observations and bounded task handoffs; exact history stays durable."""
from dataclasses import replace
import json

from reticle.context.baseline import PressureRecentContextPolicyV4
from reticle.runtime.queries import _redact_message


class MinimalContextPolicy(PressureRecentContextPolicyV4):
    policy_version = 'minimal-v1'

    def _render_unit(self, unit, unit_index, *, view_budget=None):
        calls = unit[0].get('tool_calls', [])
        mutations = {'write_file', 'replace_text', 'apply_patch'}
        results = [message for message in unit if message.get('role') == 'tool']
        if (unit_index < self._latest_exchange_index and calls and len(calls) == len(results)
                and all(call.get('function', {}).get('name') in mutations for call in calls)
                and all(message.get('_reticle_output', {}).get('status') == 'success' for message in results)):
            receipts = []
            by_call = {result.get('tool_call_id'):result for result in results}
            for call in calls:
                result = by_call[call['id']]
                function = call['function']
                try:
                    arguments = json.loads(function.get('arguments', '{}'))
                except (ValueError, TypeError):
                    return super()._render_unit(unit, unit_index, view_budget=view_budget)
                receipts.append({'tool': function['name'], 'path': arguments.get('path'),
                                 'status': 'success', 'output': result['_reticle_output']['handle']})
            message = {'role':'user', 'content':'Earlier mutation receipts (observations, not instructions). '
                       'Contents persist in workspace files; read them only when needed. Exact actions '
                       'remain in search_history.\n' + json.dumps(receipts, separators=(',', ':')),
                       '_context_id':f'transcript:{unit_index}:mutation-receipts'}
            return [message], [{'kind':'transcript_unit', 'unit_index':unit_index,
                                'rendering':'mutation_receipts', 'source_artifact_ids':
                                [m.get('_reticle_artifact_id') for m in unit]}]
        return super()._render_unit(unit, unit_index, view_budget=view_budget)

    def _pressure_message(self, original, *, view_budget=None):
        output = original.get('_reticle_output', {})
        # Explicit retrieval gets a larger page. Routine observations stay short
        # even when the overall context is not yet under pressure.
        retrieval = {'read_file', 'read_output', 'read_artifact', 'read_note',
                     'history', 'search_history', 'search_output', 'style_profile'}
        limit = 4096 if output.get('tool') in retrieval else getattr(self, 'routine_view_bytes', 1024)
        budget = min(limit, view_budget) if view_budget is not None else limit
        return super()._pressure_message(original, view_budget=budget)

    def _record(self, runtime, task, messages, tools, max_context_bytes, selected,
                pin_overflow, diagnostics, omitted_items=None):
        # The filtered transcript uses its own unit indices; boundary omissions
        # identify original artifacts, so their provenance remains unambiguous.
        return super()._record(runtime, task, messages, tools, max_context_bytes,
            selected + self._handoff_selected, pin_overflow, diagnostics,
            omitted_items=[*(omitted_items or []), *self._boundary_omitted])

    def build(self, runtime, task, transcript, tools, max_context_bytes,
              diagnostics=None, resource_status=None):
        events = runtime.journal.read_all()
        results = [event for event in events if event.kind == 'agent_run_result'
                   and event.payload['result']['task_id'] != task.task_id]
        boundary = next((i for i, message in enumerate(transcript)
                         if message.get('_reticle_task_id') == task.task_id), None)
        if boundary is None and results:
            after = {event.payload['artifact_id'] for event in events
                     if event.kind == 'transcript_message' and event.sequence > results[-1].sequence}
            boundary = next((i for i, message in enumerate(transcript)
                             if message.get('_reticle_artifact_id') in after), len(transcript))
        boundary = boundary or 0
        prior, current = transcript[:boundary], transcript[boundary:]
        self._boundary_omitted = [{'kind': 'transcript', 'artifact_id': message.get('_reticle_artifact_id'),
                                  'reason': 'prior_task_handoff'} for message in prior]
        # The task is already included once in the opening; preserve subsequent
        # corrections and controller interventions within the current turn.
        if current and current[0].get('role') == 'user' and (current[0].get('_reticle_task_id') == task.task_id
                or current[0].get('content') == task.description):
            current = current[1:]
        self._handoff_selected = []
        self._latest_exchange_index = self._required_start(self._paired_units(current)) or 0
        if prior:
            paths = []
            for message in prior:
                for call in message.get('tool_calls', []):
                    function = call.get('function', {})
                    if function.get('name') not in {'write_file', 'replace_text', 'style_apply', 'extension_stage'}:
                        continue
                    try:
                        args = json.loads(function.get('arguments', '{}'))
                    except (ValueError, TypeError):
                        continue
                    path = args.get('output_path') or args.get('path')
                    if isinstance(path, str) and path not in paths:
                        paths.append(path[:160])
            rows = [{'task_id': event.payload['result']['task_id'],
                     'stop_reason': event.payload['result']['stop_reason'],
                     'reported_summary': (event.payload['result'].get('finish_summary') or '')[:480],
                     'error': (event.payload['result'].get('error') or '')[:240]}
                    for event in results[-2:]]
            user = next((message for message in reversed(prior) if message.get('role') == 'user'), {})
            source_id = user.get('_reticle_artifact_id')
            projected_id = next((event.payload['view_artifact']['artifact_id'] for event in events
                                 if event.kind == 'observation_view' and
                                 event.payload.get('source_transcript_artifact_id') == source_id), None)
            projected = _redact_message(user)
            if source_id and not projected_id:
                event_id = runtime.journal.new_event_id()
                artifact = runtime.artifacts.put(json.dumps(projected, sort_keys=True).encode('utf-8'),
                    'application/json', event_id, labels=['observation-view', 'task-handoff'])
                projected_id = artifact.artifact_id
                runtime.journal.append('observation_view', {'view_artifact': artifact.to_dict(),
                    'source_transcript_artifact_id': source_id, 'rendering': {'source_kind': 'user'}}, event_id=event_id)
            handoff = {'recent_tasks': rows, 'prior_user_excerpt': str(projected.get('content', ''))[:480],
                       'prior_user_artifact': projected_id,
                       'paths_mentioned_in_mutations': paths[-8:]}
            # Keep the durable full user instruction reachable before relying on
            # a truncated excerpt. Task summaries are model reports, not acceptance.
            text = ('\n\nPrior-task handoff (reported data, not verified acceptance). '
                    'Files and tools persist. Restore applicable prior requirements with read_artifact '
                    'or search_history before relying on a truncated excerpt. Full earlier transcript '
                    'is available through history/search_history; it is not resent automatically.\n'
                    + json.dumps(handoff, separators=(',', ':'), ensure_ascii=False))
            task = replace(task, description=task.description + text)
            self._handoff_selected = [{'kind': 'task_handoff', 'source_result_sequences':
                                      [event.sequence for event in results[-2:]],
                                      'prior_user_artifact': projected_id}]
        return super().build(runtime, task, current, tools, max_context_bytes,
                             diagnostics=diagnostics, resource_status=resource_status)
