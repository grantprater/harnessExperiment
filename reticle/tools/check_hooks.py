"""Experiment-scoped tools: identical edits, optional automatic test observations."""
from dataclasses import replace
import json
from reticle.runtime.check_hooks import VERSION, render_check, source_fingerprint
from reticle.tools.primitives import ToolOutcome, _function
from reticle.tools.toolset_v4 import ToolSuiteV4  # toolset v4, opt-in (owner, 2026-10-15)

ARMS = ('manual', 'automatic-full', 'automatic-selective')
ALLOWED = {'glob_files', 'read_file', 'outline', 'search_text', 'replace_text',
           'write_file', 'apply_patch', 'read_output', 'search_output', 'finish'}
MUTATIONS = {'replace_text', 'write_file', 'apply_patch'}
VERIFY_SCHEMA = _function('verify', 'Run the fixed project tests. Full results are returned; '
                          'this tool is available in all conditions.', {}, [])


class CheckHookTools(ToolSuiteV4):
    def __init__(self, runtime, *, interpreter, checker, source_paths, arm):
        super().__init__(runtime, interpreter=interpreter)
        if arm not in ARMS:
            raise ValueError('Unknown check-hook arm')
        self.checker, self.source_paths, self.arm = checker, tuple(source_paths), arm

    def schemas(self):
        return [s for s in super().schemas() if s['function']['name'] in ALLOWED] + [VERIFY_SCHEMA]

    def _check(self, call_id, trigger, mode):
        before = source_fingerprint(self.runtime.workspace.root, self.source_paths)
        try:
            result = self.checker()
        except Exception as exc:
            result = {'status': 'error', 'output': f'Check execution error: {type(exc).__name__}'}
        after = source_fingerprint(self.runtime.workspace.root, self.source_paths)
        if before != after:
            result = {**result, 'status': 'stale', 'output': result.get('output', '') +
                      '\nSource changed while the check ran; evidence is stale.'}
        full = json.dumps({**result, 'source_before': before, 'source_after': after}, indent=2)
        handle = self._register_output(call_id, 'fixed_check', full)
        visible = render_check(result, mode, handle, before)
        self.runtime.journal.append('post_edit_check', {
            'version': VERSION, 'arm': self.arm, 'call_id': call_id, 'trigger': trigger,
            'representation': mode, 'status': result['status'], 'source_before': before,
            'source_after': after, 'evidence_handle': handle,
            'tests_run': result.get('tests_run'), 'duration_s': result.get('duration_s'),
            'full_bytes': len(full.encode()), 'visible_bytes': len(visible.encode())})
        return visible

    def dispatch(self, name, arguments, call_id):
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except ValueError:
            parsed = None
        if name == 'verify':
            if parsed != {}:
                outcome = ToolOutcome('verify accepts no arguments.', 'rejected')
            else:
                outcome = self._journaled(call_id, 'verify', {},
                    lambda: ToolOutcome(self._check(call_id, 'manual_verify', 'full'), 'success'))
        elif name not in ALLOWED:
            outcome = self._journaled(call_id, name, {}, lambda: ToolOutcome('Tool unavailable in this probe.', 'rejected'))
        elif name in MUTATIONS and (not isinstance(parsed, dict) or parsed.get('path') not in self.source_paths):
            outcome = self._journaled(call_id, name, {},
                lambda: ToolOutcome('Only the listed existing source files may be edited; tests are read-only.', 'rejected'))
        else:
            before = source_fingerprint(self.runtime.workspace.root, self.source_paths)
            outcome = super().dispatch(name, arguments, call_id)
            after = source_fingerprint(self.runtime.workspace.root, self.source_paths)
            if (name in MUTATIONS and outcome.status == 'success' and before != after
                    and self.arm != 'manual'):
                mode = 'selective' if self.arm == 'automatic-selective' else 'full'
                visible = self._check(call_id, 'post_edit', mode)
                outcome = replace(outcome, content=outcome.content + '\n' + visible, handle=None)
            else:
                return outcome
        return replace(outcome, handle=self._register_output(call_id, name, outcome.content))
