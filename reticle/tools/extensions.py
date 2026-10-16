"""Optional tool construction and dispatch over a frozen extension registry."""
import json
from uuid import uuid4

from reticle.execution import ExecutionController
from reticle.tools.primitives import ToolOutcome, _function
from reticle.runtime.extensions import check_arguments


EXTENSION_SCHEMAS = [
    _function('extension_stage', 'Validate and queue a Python extension directory for the next user turn. '
              'The directory needs manifest.json with name (ext_*), description, parameters (object schema), '
              'entrypoint (file.py:function), smoke_tests ([{arguments, expected?}]), optional timeout_seconds. '
              'The function receives (arguments, context) and returns JSON. context contains workspace and validation. '
              'Validation runs in a temporary workspace. Current tools stay frozen until the next turn.',
              {'path': {'type': 'string'}}, ['path']),
    _function('extension_list', 'List this turn\'s frozen extension versions and durable active/previous/pending versions.', {}, []),
    _function('extension_rollback', 'Validate and queue the previous version of an extension for the next user turn.',
              {'name': {'type': 'string'}}, ['name']),
]
PARAMETERS = {s['function']['name']: s['function']['parameters'] for s in EXTENSION_SCHEMAS}


class ExtensionTools:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extensions = None

    def schemas(self):
        schemas = super().schemas()
        return [*schemas, *EXTENSION_SCHEMAS, *self.extensions.schemas()] if self.extensions else schemas

    def _dispatch(self, name, arguments, call_id):
        registry = self.extensions
        if not registry or name not in PARAMETERS and name not in registry.frozen:
            return super()._dispatch(name, arguments, call_id)
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            schema = PARAMETERS[name] if name in PARAMETERS else registry.frozen[name]['manifest']['parameters']
            check_arguments(parsed, schema)
            if name in PARAMETERS:
                def action():
                    if name == 'extension_stage':
                        value = registry.stage(self.runtime.workspace._resolve(parsed['path']))
                    elif name == 'extension_rollback':
                        value = registry.rollback(parsed['name'])
                    else:
                        value = registry.list()
                    return ToolOutcome(json.dumps(value, sort_keys=True), 'success')
                return self._journaled(call_id, name, parsed, action)
            version = registry.frozen[name]['version']
            request = registry.request(version, 'execute', parsed)
        except (ValueError, TypeError, OSError, KeyError) as exc:
            message = str(exc)
            return self._journaled(call_id, name, {}, lambda: ToolOutcome('ERROR: ' + message, 'rejected'))
        invocation_id = 'extension-' + uuid4().hex
        payload = {'invocation_id': invocation_id, 'task_id': registry.task_id,
                   'call_id': call_id, 'name': name, 'version': version}
        self.runtime.journal.append('extension_invocation_started', payload)
        # Each extension invocation is conservatively a workspace mutation. A crash
        # after dispatch follows the same reconciliation rules as ordinary commands.
        record = ExecutionController(self.runtime, self.backend).execute(request, call_id=call_id,
                                                                      operation_id=invocation_id)
        execution = record.execution
        status = execution.status
        stdout = execution.stdout.decode('utf-8', errors='replace')
        stderr = execution.stderr.decode('utf-8', errors='replace')
        if status == 'success':
            try:
                json.loads(stdout.rsplit('\nRETICLE_EXTENSION_RESULT=', 1)[1])
            except (ValueError, IndexError):
                status = 'error'
                stderr += '\nExtension did not return a JSON result.'
        self.runtime.journal.append('extension_invocation_finished', {
            **payload, 'status': status, 'duration_ms': execution.duration_ms,
            'exit_code': execution.exit_code, 'output_truncated': execution.output_truncated})
        return ToolOutcome(f'Extension {name} @ {version}\nstatus: {status}; {execution.duration_ms} ms\n'
                           + stdout + ('\n--- stderr ---\n' + stderr if stderr else ''), status)
