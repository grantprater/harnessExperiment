"""Generated tool lifecycle exercised with real child processes and offline models."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from reticle.context import TranscriptStore
from reticle.execution import TrustedLocalBackend
from reticle.interactive import ROOT, launch, learning_tools
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits
from reticle.runtime.extensions import ExtensionRegistry
from reticle.runtime.session import LocalRuntime
from reticle.runtime.telemetry import usage_report
from tests.test_runtime_updates import args, response


class SequenceClient:
    def __init__(self, calls):
        self.calls = iter(calls)
        self.schemas = []

    def complete(self, messages, tools):
        self.schemas.append(tools)
        name, arguments = next(self.calls)
        return response(len(self.schemas), name, arguments)


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.runtime = LocalRuntime(self.root / 'session', self.workspace)
        self.options = args('--extensions', '--quiet')
        self.tools = learning_tools(self.runtime, self.options)[0]
        self.tools.quiet = True
        self.registry = self.tools.extensions

    def source(self, delta=1, code=None, **overrides):
        directory = self.workspace / f'tools/add-{delta}'
        directory.mkdir(parents=True, exist_ok=True)
        manifest = {'name': 'ext_add', 'description': 'Add an offset to n.',
                    'parameters': {'type': 'object', 'properties': {'n': {'type': 'integer'}}, 'required': ['n']},
                    'entrypoint': 'tool.py:execute', 'smoke_tests': [{'arguments': {'n': 2}, 'expected': 2 + delta}],
                    **overrides}
        (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (directory / 'tool.py').write_text(code or f'def execute(arguments, context):\n    return arguments["n"] + {delta}\n', encoding='utf-8')
        return directory

    def begin(self, task='task'):
        self.registry.begin_turn(task)

    def invoke(self, n=2, name='ext_add', call='invoke'):
        return self.tools.dispatch(name, {'n': n}, call)

    def test_stage_freeze_invoke_revise_and_rollback(self):
        first = self.registry.stage(self.source())['version']
        self.assertNotIn('ext_add', [s['function']['name'] for s in self.tools.schemas()])
        self.begin('first')
        self.assertEqual(self.registry.versions(), {'ext_add': first})
        self.assertIn('RESULT=3', self.invoke().content)
        second = self.registry.stage(self.source(10))['version']
        self.assertIn('RESULT=3', self.invoke(call='still-first').content)
        self.assertEqual(self.registry.versions()['ext_add'], first)
        self.begin('second')
        self.assertIn('RESULT=12', self.invoke(call='second').content)
        self.registry.rollback('ext_add')
        self.assertEqual(self.registry.versions()['ext_add'], second)
        self.begin('rollback')
        self.assertIn('RESULT=3', self.invoke(call='rolled-back').content)
        report = usage_report(self.runtime)
        self.assertEqual(len(report['extensions']['invocations']), 4)
        self.assertEqual(sum(r['successful'] for r in report['extensions']['versions']), 4)

    def test_controller_constructs_tool_then_uses_it_on_followup(self):
        source = self.source()
        client = SequenceClient([('extension_stage', {'path': source.relative_to(self.workspace).as_posix()}),
                                 ('finish', {'summary': 'Tool built'})])
        result = AgentController(self.runtime, TaskEnvelope('build', 'Build a tool'), self.tools,
                                 client, AgentLimits(3, 120000)).run()
        self.assertEqual(result.stop_reason, 'finish_requested')
        self.assertTrue(all('ext_add' not in [s['function']['name'] for s in schemas] for schemas in client.schemas))
        client = SequenceClient([('ext_add', {'n': 7}), ('finish', {'summary': 'Tool used'})])
        result = AgentController(self.runtime, TaskEnvelope('use', 'Use the new tool'), self.tools,
                                 client, AgentLimits(3, 120000)).run()
        self.assertEqual(result.stop_reason, 'finish_requested')
        self.assertIn('ext_add', [s['function']['name'] for s in client.schemas[0]])
        report = usage_report(self.runtime)
        self.assertEqual(report['extensions']['invocations'][0]['task_id'], 'use')
        self.assertTrue(report['calls'][-1]['extension_versions']['ext_add'])
        self.assertEqual(report['calls'][0]['extension_versions'], {})

    def test_model_writes_the_bundle_and_resume_activates_it(self):
        source = self.source()
        manifest = (source / 'manifest.json').read_text()
        code = (source / 'tool.py').read_text()
        shutil.rmtree(source)
        session = self.root / 'cli-session'
        client = SequenceClient([('write_file', {'path': 'tools/add-1/manifest.json', 'content': manifest}),
                                 ('write_file', {'path': 'tools/add-1/tool.py', 'content': code}),
                                 ('extension_stage', {'path': 'tools/add-1'}), ('finish', {'summary': 'Built'})])
        with patch('reticle.interactive.connection', return_value=client), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launch(args('Build', '--once', '--quiet', '--extensions', '-C', str(self.workspace),
                                         '--session-dir', str(session))), 0)
        client = SequenceClient([('ext_add', {'n': 9}), ('finish', {'summary': 'Used'})])
        with patch('reticle.interactive.connection', return_value=client), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launch(args('Use', '--once', '--quiet', '--extensions', '--resume', str(session))), 0)
        report = usage_report(LocalRuntime(session))
        self.assertEqual(report['extensions']['versions'][0]['successful'], 1)

    def test_bad_smoke_test_does_not_replace_active_or_pending(self):
        first = self.registry.stage(self.source())['version']
        self.begin()
        with self.assertRaisesRegex(ValueError, 'validation'):
            self.registry.stage(self.source(2, smoke_tests=[{'arguments': {'n': 2}, 'expected': 999}]))
        self.assertEqual(self.registry.state()['tools']['ext_add']['active'], first)
        self.assertIsNone(self.registry.state()['tools']['ext_add']['pending'])

    def test_pending_tampering_is_rejected_and_active_tampering_rolls_back(self):
        first = self.registry.stage(self.source())['version']
        self.begin()
        pending = self.registry.stage(self.source(2))['version']
        (self.registry.bundle(pending) / 'tool.py').write_text('raise RuntimeError("tampered")')
        self.begin('reject')
        self.assertEqual(self.registry.versions()['ext_add'], first)
        second = self.registry.stage(self.source(3))['version']
        self.begin('updated')
        (self.registry.bundle(second) / 'extra.py').write_text('pass')
        self.begin('fallback')
        self.assertEqual(self.registry.versions()['ext_add'], first)
        self.assertTrue(any(e.kind == 'extension_rolled_back' for e in self.runtime.journal.read_all()))

    def test_bad_arguments_and_unsupported_schemas_are_rejected(self):
        for overrides in ({'name': 'finish'}, {'name': 12},
                          {'parameters': {'type': 'object', 'oneOf': []}},
                          {'parameters': {'type': 'object', 'additionalProperties': True}},
                          {'smoke_tests': []}):
            with self.assertRaises(ValueError):
                self.registry.stage(self.source(**overrides))
        self.registry.stage(self.source())
        self.begin()
        for arguments in ({'n': True}, {'n': '2'}, {'n': 1, 'unknown': 2}, {}, []):
            outcome = self.tools.dispatch('ext_add', arguments, 'bad-' + str(arguments))
            self.assertEqual(outcome.status, 'rejected')
        self.assertFalse(any(e.kind == 'extension_invocation_started' for e in self.runtime.journal.read_all()))

    def test_import_and_runtime_errors_do_not_escape_into_controller(self):
        outcome = self.tools.dispatch('extension_stage', {'path': self.source(code='def broken(:').relative_to(self.workspace).as_posix()}, 'syntax')
        self.assertEqual(outcome.status, 'error')
        self.assertIn('syntax error', outcome.content)
        with self.assertRaisesRegex(ValueError, 'validation'):
            self.registry.stage(self.source(code='raise RuntimeError("bad import")\n'))
        self.registry.stage(self.source(code='def execute(arguments, context):\n'
            '    if not context["validation"]: raise RuntimeError("runtime failure")\n'
            '    return arguments["n"] + 1\n'))
        self.begin()
        outcome = self.invoke()
        self.assertEqual(outcome.status, 'error')
        self.assertIn('runtime failure', outcome.content)
        self.assertEqual(usage_report(self.runtime)['extensions']['invocations'][0]['status'], 'error')

    def test_execution_timeout_is_recorded_without_replay(self):
        self.registry.stage(self.source(timeout_seconds=0.5, code='import time\n'
            'def execute(arguments, context):\n'
            '    if not context["validation"]: time.sleep(10)\n'
            '    return arguments["n"] + 1\n'))
        self.begin()
        self.assertEqual(self.invoke().status, 'timeout')
        report = usage_report(self.runtime)
        self.assertEqual(len(report['extensions']['invocations']), 1)
        self.assertEqual(report['extensions']['invocations'][0]['status'], 'timeout')

    def test_validation_writes_only_to_temporary_workspace(self):
        self.registry.stage(self.source(code='from pathlib import Path\n'
            'def execute(arguments, context):\n'
            '    (Path(context["workspace"]) / "marker").write_text("ok")\n'
            '    return arguments["n"] + 1\n'))
        self.assertFalse((self.workspace / 'marker').exists())
        self.begin()
        self.assertFalse((self.workspace / 'marker').exists())
        self.invoke()
        self.assertEqual((self.workspace / 'marker').read_text(), 'ok')

    def test_unfinished_calls_keep_original_version_when_library_changes(self):
        first = self.registry.stage(self.source())['version']
        self.begin('old-turn')
        second = self.registry.stage(self.source(10))['version']
        # Another session activates the shared library; this session has an unfinished call.
        other = LocalRuntime(self.root / 'other-session', self.workspace)
        ExtensionRegistry(other, TrustedLocalBackend(), sys.executable).begin_turn('other')
        self.assertEqual(self.registry.state()['tools']['ext_add']['active'], second)
        TranscriptStore(self.runtime).append({'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': 'unfinished', 'type': 'function', 'function': {'name': 'ext_add', 'arguments': '{"n":2}'}}]})
        self.begin('recovery')
        self.assertEqual(self.registry.versions()['ext_add'], first)
        self.assertIn('RESULT=3', self.invoke(call='recovery').content)

    def test_opt_in_and_workspace_library_constraints(self):
        tools = learning_tools(self.runtime, args())[0]
        self.assertIsNone(tools.extensions)
        self.assertNotIn('extension_stage', [s['function']['name'] for s in tools.schemas()])
        with self.assertRaises(ValueError):
            ExtensionRegistry(self.runtime, TrustedLocalBackend(), sys.executable, self.root / 'outside')
        with self.assertRaises(ValueError):
            self.registry.stage(self.workspace)

    def test_requests_use_portable_paths_and_the_configured_backend(self):
        from reticle.execution import IsolatedOCIBackend
        version = self.registry.stage(self.source())['version']
        request = self.registry.request(version, 'execute', {'n': 2})
        self.assertNotIn('\\', request.command[4])
        self.assertTrue(request.mutates_workspace)
        self.assertEqual(request.workspace_root, self.workspace)
        command = IsolatedOCIBackend('test-image', engine='docker').build_command(request, 'test-extension')
        self.assertIn('--network', command)
        self.assertIn(request.command[4], command)
        self.assertIn('type=bind,src=' + str(self.workspace) + ',dst=/workspace', command)

    def test_example_bundle_and_nested_parameter_bounds(self):
        source = self.workspace / 'example'
        shutil.copytree(ROOT / 'examples/extensions/scale_values', source)
        self.registry.stage(source)
        self.begin()
        result = self.tools.dispatch('ext_scale_values', {'values': [1, 2], 'factor': 3}, 'example')
        self.assertEqual(result.status, 'success')
        self.assertIn('RESULT=[3, 6]', result.content)
        for value in ([True], ['wrong'], [1] * 1001):
            result = self.tools.dispatch('ext_scale_values', {'values': value, 'factor': 3}, 'invalid-example')
            self.assertEqual(result.status, 'rejected')

    def test_usage_distinguishes_reused_call_ids_and_incomplete_invocations(self):
        start = {'task_id': 'task', 'call_id': 'same-id', 'name': 'ext_add', 'version': 'version'}
        self.runtime.journal.append('extension_invocation_started', {**start, 'invocation_id': 'one'})
        self.runtime.journal.append('extension_invocation_finished', {**start, 'invocation_id': 'one', 'status': 'error'})
        self.runtime.journal.append('extension_invocation_started', {**start, 'invocation_id': 'two'})
        self.runtime.journal.append('extension_invocation_finished', {**start, 'invocation_id': 'two', 'status': 'success'})
        self.runtime.journal.append('extension_invocation_started', {**start, 'invocation_id': 'three'})
        report = usage_report(self.runtime)['extensions']
        self.assertEqual([row['status'] for row in report['invocations']], ['error', 'success', 'incomplete'])
        self.assertEqual(report['versions'][0]['successful'], 1)
        self.assertEqual(report['versions'][0]['incomplete'], 1)

    def test_numeric_constraints_handle_large_integers_and_invalid_ranges(self):
        from reticle.runtime.extensions import check_arguments, check_schema
        check_arguments(10 ** 400, {'type': 'number'})
        check_arguments(10 ** 400, {'type': 'integer'})
        for value in (True, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                check_arguments(value, {'type': 'number'})
        with self.assertRaises(ValueError):
            check_schema({'type': 'integer', 'minimum': 5, 'maximum': 1})

    def test_runtime_worker_supports_extensions_and_custom_library(self):
        from reticle.runtime.supervisor import RuntimeSupervisor
        source = self.source()
        options = args('--runtime-updates', '--extensions', '--extension-library', str(self.workspace / '.reticle/custom'),
                       '--quiet', '-C', str(self.workspace), '--resume', str(self.runtime.session_dir))
        client = SequenceClient([('extension_stage', {'path': source.relative_to(self.workspace).as_posix()}),
                                 ('finish', {'summary': 'built'}), ('ext_add', {'n': 8}), ('finish', {'summary': 'used'})])
        supervisor = RuntimeSupervisor(self.runtime.session_dir, self.workspace, options, client, ROOT)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(supervisor.run_turn('Build'), 0)
            self.assertEqual(supervisor.run_turn('Use'), 0)
        self.assertEqual(usage_report(LocalRuntime(self.runtime.session_dir))['extensions']['versions'][0]['successful'], 1)


if __name__ == '__main__':
    unittest.main()
