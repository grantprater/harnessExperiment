"""Offline regression coverage for editing, searching and execution ergonomics."""
import sys
from unittest.mock import Mock

from tests.test_toolset_v3 import ContractTestCase
from reticle.context.baseline import render_output_view
from reticle.execution.backends import ExecutionRequest, IsolatedOCIBackend
from reticle.tools.knowledge import KnowledgeTools
from reticle.tools.primitives import ToolSuite
from reticle.tools.finish_guard import FinishGuard
from reticle.runtime.source_edits import SourceEditTracker


class ToolsetV4Tests(ContractTestCase):
    def test_patch_triggers_knowledge_recheck_and_source_tracking(self):
        knowledge = Mock()
        knowledge.snapshot_id = 'snapshot'
        knowledge.recheck.return_value = [{'validity': 'needs_recheck'}]
        cls = type('Tools', (KnowledgeTools, ToolSuite), {})
        tools = cls(self.runtime, interpreter=sys.executable, knowledge=knowledge)
        guard = FinishGuard(self.runtime, SourceEditTracker(self.runtime.workspace))
        arguments = {'path': 'pkg/core.py', 'patch': '@@ -1 +1 @@\n-def get_name(x):\n+def changed(x):\n'}
        outcome = tools.dispatch('apply_patch', arguments, 'patch')
        self.assertEqual(outcome.status, 'success', outcome.content)
        knowledge.recheck.assert_called_once_with()
        self.assertIn('needs_recheck', outcome.content)
        guard.observe('apply_patch', arguments, outcome, 'patch')
        self.assertEqual(guard.first_edit_step, 1)
        self.assertIn('pkg/core.py', guard.tracker.edited_files())

    def test_patch_multiple_hunks_preserves_crlf_and_untouched_bytes(self):
        target = self.workspace / 'pkg/core.py'
        target.write_bytes(b'first\r\nold\r\nkeep\r\nlast')
        outcome = self.dispatch('apply_patch', path='pkg/core.py', patch=
                                'diff --git a/pkg/core.py b/pkg/core.py\nindex 123..456 100644\n'
                                '--- a/pkg/core.py\n+++ b/pkg/core.py\n'
                                '@@ -1,2 +1,3 @@\n first\n-old\n+new\n+added\n'
                                '@@ -4 +5 @@\n-last\n\\ No newline at end of file\n'
                                '+final\n\\ No newline at end of file\n')
        self.assertEqual(outcome.status, 'success', outcome.content)
        self.assertEqual(target.read_bytes(), b'first\r\nnew\r\nadded\r\nkeep\r\nfinal')
        self.assertTrue(any(e.kind == 'action_dispatched' and e.payload.get('effect_class') == 'workspace_mutation'
                            for e in self.runtime.journal.read_all()))

    def test_bad_later_hunk_and_bad_counts_leave_file_unchanged(self):
        target = self.workspace / 'pkg/core.py'
        before = target.read_bytes()
        for patch in ['@@ -1 +1 @@\n-def get_name(x):\n+def renamed(x):\n@@ -6 +6 @@\n-wrong\n+new\n',
                      '@@ -1,2 +1 @@\n-def get_name(x):\n+new\n']:
            outcome = self.dispatch('apply_patch', path='pkg/core.py', patch=patch)
            self.assertEqual(outcome.status, 'rejected', outcome.content)
            self.assertEqual(target.read_bytes(), before)

    def test_insert_delete_and_path_escape(self):
        target = self.workspace / 'pkg/core.py'
        target.write_bytes(b'a\nb\n')
        outcome = self.dispatch('apply_patch', path='pkg/core.py', patch='@@ -0,0 +1 @@\n+start\n@@ -2 +2,0 @@\n-b\n')
        self.assertEqual(outcome.status, 'success', outcome.content)
        self.assertEqual(target.read_bytes(), b'start\na\n')
        self.assertNotEqual(self.dispatch('apply_patch', path='../outside', patch='@@ -0,0 +1 @@\n+x\n').status, 'success')

    def test_regex_context_and_literal_default(self):
        result = self.dispatch('search_text', query=r'def (get_name|other)\(', regex=True,
                               context_lines=1, path='pkg', file_glob='*.py')
        self.assertEqual(result.status, 'success')
        self.assertIn('2 match(es)', result.content)
        self.assertIn('pkg/core.py:2-     return', result.content)
        self.assertIn('Python regex', result.content)
        literal = self.dispatch('search_text', query='get_.*', path='pkg')
        self.assertIn('0 match(es)', literal.content)
        for extra in [{'regex': True, 'query': '['}, {'context_lines': -1, 'query': 'def'}]:
            self.assertEqual(self.dispatch('search_text', **extra).status, 'rejected')
        found = self.dispatch('search_output', id=result.handle, query='return.*split', regex=True, context_lines=1)
        self.assertIn('2 match(es)', found.content)

    def test_cwd_and_sequence_stop_continue_and_preflight(self):
        cwd = self.dispatch('run', command='python -c "import os; print(os.path.basename(os.getcwd()))"', cwd='pkg')
        self.assertEqual(cwd.status, 'success', cwd.content)
        self.assertIn('cwd: pkg', cwd.content)
        self.assertIn('--- stdout ---\npkg', cwd.content)
        commands = ['python -c "import sys; sys.exit(3)"', 'python -c "print(777)"']
        stopped = self.dispatch('run', commands=commands)
        self.assertIn('Executed 1 of 2', stopped.content)
        self.assertEqual(stopped.status, 'error')
        continued = self.dispatch('run', commands=commands, stop_on_error=False)
        self.assertIn('Executed 2 of 2', continued.content)
        self.assertIn('777', continued.content)
        self.assertEqual(continued.status, 'error')
        rejected = self.dispatch('run', commands=['python -c "open(\'oops\', \'w\').close()"', 'echo x && echo y'])
        self.assertEqual(rejected.status, 'rejected')
        self.assertFalse((self.workspace / 'oops').exists())
        self.assertEqual(self.dispatch('run', command='python -c pass', commands=commands).status, 'rejected')
        self.assertEqual(self.dispatch('run', command='python -c pass', cwd='..').status, 'rejected')

    def test_oci_subdirectory_mounts_full_workspace(self):
        backend = IsolatedOCIBackend('local:test', engine='docker')
        request = ExecutionRequest([sys.executable, '-c', 'pass'], self.workspace / 'pkg',
                                   workspace_root=self.workspace)
        command = backend.build_command(request, 'test')
        self.assertEqual(command[command.index('--workdir')+1], '/workspace/pkg')
        self.assertIn(f'src={self.workspace}', command[command.index('--mount')+1])

    def test_large_output_keeps_middle_failure_and_exact_retrieval(self):
        lines = ['progress ' + str(i) for i in range(1000)]
        lines[500] = 'Traceback: important middle failure'
        lines[501] = '  offending_function()'
        lines[-1] = 'final summary'
        view, metadata = render_output_view('\n'.join(lines), 'out_1', 4000, True)
        self.assertLessEqual(len(view.encode('utf-8')), 4000)
        self.assertIn('L501: Traceback: important middle failure', view)
        self.assertIn('L502:   offending_function()', view)
        self.assertIn('final summary', view)
        self.assertIn('read_output(id="out_1"', view)
        self.assertIn(501, metadata['diagnostic_lines'])
