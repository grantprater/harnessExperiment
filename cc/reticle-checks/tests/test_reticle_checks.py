"""Hook contract tests: synthesized hook JSON on stdin against temporary projects.

Run from cc/reticle-checks:  python -m unittest discover -s tests -v
Every hook call spawns the real script (python reticle_checks.py <entry>) with the
payload on stdin, as Claude Code would; no model or network is involved.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'scripts' / 'reticle_checks.py'
sys.path.insert(0, str(SCRIPT.parent))
import reticle_checks as rc  # noqa: E402

# A fake unittest-verbosity-2 runner driven by outcomes.json, so delta cases are exact.
FAKE_UNITTEST = textwrap.dedent('''
    import json, sys
    spec = json.load(open("outcomes.json"))
    word = {"ok": "ok", "FAIL": "FAIL", "ERROR": "ERROR", "skip": "skipped 'x'"}
    for name, res in spec["tests"].items():
        print(f"{name} (mod.T.{name}) ... {word[res]}")
    bad = [(n, r) for n, r in spec["tests"].items() if r in ("FAIL", "ERROR")]
    for name, res in bad:
        print("=" * 70)
        print(f"{res}: {name} (mod.T.{name})")
        print("-" * 70)
        print("Traceback (most recent call last):")
        for i in range(spec.get("trace_lines", 1)):
            print(f'  File "mod.py", line {i}, in {name}')
        print(f"AssertionError: {name} broke")
        print()
    print("-" * 70)
    print(f"Ran {len(spec['tests'])} tests in 0.001s")
    print()
    print("FAILED (failures=%d)" % len(bad) if bad else "OK")
    sys.exit(1 if bad else 0)
''')

PYTEST_OUTPUT = textwrap.dedent('''
    import sys
    print("============================= test session starts =============================")
    print("collected 3 items")
    print("")
    print("tests/test_x.py .F.                                                       [100%]")
    print("")
    print("=================================== FAILURES ===================================")
    print("_________________________________ test_beta __________________________________")
    print("")
    print("    def test_beta():")
    print(">       assert 1 == 2")
    print("E       assert 1 == 2")
    print("")
    print("tests/test_x.py:5: AssertionError")
    print("==================================== PASSES ====================================")
    print("=========================== short test summary info ============================")
    print("PASSED tests/test_x.py::test_alpha")
    print("PASSED tests/test_x.py::test_gamma")
    print("FAILED tests/test_x.py::test_beta - assert 1 == 2")
    print("========================= 1 failed, 2 passed in 0.02s ==========================")
    sys.exit(1)
''')


class Project:
    def __init__(self, test, config, files):
        self.root = Path(tempfile.mkdtemp(prefix='rc-test-'))
        test.addCleanup(shutil.rmtree, self.root, True)
        for rel, text in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(text), encoding='utf-8')
        self.write_config(config)
        self.session = 'sess-1'

    def write_config(self, config):
        (self.root / '.claude').mkdir(exist_ok=True)
        merged = {'source_globs': ['src.py'], 'timeout_s': 20, 'mode': 'selective', **config}
        (self.root / '.claude' / 'reticle-checks.json').write_text(json.dumps(merged), encoding='utf-8')

    def touch_source(self, text):
        (self.root / 'src.py').write_text(text, encoding='utf-8')

    def outcomes(self, tests, trace_lines=1):
        (self.root / 'outcomes.json').write_text(
            json.dumps({'tests': tests, 'trace_lines': trace_lines}), encoding='utf-8')

    def payload(self, rel='src.py', tool='Edit', event='PostToolUse', **extra):
        path = str(self.root / rel)
        base = {'session_id': self.session, 'cwd': str(self.root), 'hook_event_name': event,
                'transcript_path': '', 'permission_mode': 'default'}
        if event == 'PostToolUse':
            tool_input = {'file_path': path}
            if tool == 'Edit':
                tool_input.update(old_string='a', new_string='b', replace_all=False)
            elif tool == 'MultiEdit':
                tool_input['edits'] = [{'old_string': 'a', 'new_string': 'b'}]
            else:
                tool_input['content'] = 'x'
            base.update(tool_name=tool, tool_input=tool_input,
                        tool_response={'filePath': path}, tool_use_id='toolu_test', duration_ms=3)
        base.update(extra)
        return base

    def hook(self, entry='post-tool-use', payload=None):
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_PROJECT_DIR'}
        done = subprocess.run([sys.executable, str(SCRIPT), entry],
                              input=json.dumps(payload or self.payload()).encode(),
                              capture_output=True, timeout=120, env=env, cwd=str(self.root))
        assert done.returncode == 0, done.stderr
        out = done.stdout.decode('utf-8')
        return json.loads(out) if out.strip() else None

    def context(self, **kw):
        result = self.hook(payload=self.payload(**kw) if kw else None)
        assert result is not None, 'hook produced no output'
        return result['hookSpecificOutput']['additionalContext']

    def events(self):
        path = self.root / '.claude' / 'reticle-checks' / self.session / 'events.jsonl'
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

    def checks(self):
        return [e for e in self.events() if e['kind'] == 'check']


PY = sys.executable
UNITTEST = [PY, '-B', '-m', 'unittest', '-v', 'test_src']
PASSING = {'src.py': 'def f():\n    return 1\n',
           'test_src.py': '''
               import unittest, src
               class T(unittest.TestCase):
                   def test_one(self):
                       self.assertEqual(src.f(), 1)
                   def test_two(self):
                       self.assertTrue(True)
           '''}
FAILING = {'src.py': 'def f():\n    return 2\n', 'test_src.py': PASSING['test_src.py']}


def fake_project(test, mode, n=8):
    project = Project(test, {'command': [PY, 'fake_runner.py'], 'mode': mode},
                      {'src.py': 'v = 0\n', 'fake_runner.py': FAKE_UNITTEST})
    project.outcomes({f'test_{i}': 'ok' for i in range(n)})
    return project


class OutputShape(unittest.TestCase):
    def test_no_config_is_silent(self):
        root = Path(tempfile.mkdtemp(prefix='rc-test-'))
        self.addCleanup(shutil.rmtree, root, True)
        (root / 'src.py').write_text('x = 1\n')
        payload = {'session_id': 's', 'cwd': str(root), 'hook_event_name': 'PostToolUse',
                   'tool_name': 'Edit', 'tool_input': {'file_path': str(root / 'src.py')}}
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_PROJECT_DIR'}
        done = subprocess.run([sys.executable, str(SCRIPT), 'post-tool-use'], env=env,
                              input=json.dumps(payload).encode(), capture_output=True)
        self.assertEqual((done.returncode, done.stdout), (0, b''))
        self.assertFalse((root / '.claude').exists())

    def test_json_shape_and_log_path_last(self):
        project = Project(self, {'command': UNITTEST}, PASSING)
        result = project.hook()
        self.assertEqual(set(result), {'hookSpecificOutput'})
        self.assertEqual(set(result['hookSpecificOutput']), {'hookEventName', 'additionalContext'})
        self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'PostToolUse')
        last = result['hookSpecificOutput']['additionalContext'].splitlines()[-1]
        self.assertTrue(last.startswith('Full log: '))
        log = Path(last[len('Full log: '):])
        self.assertTrue(log.is_file())
        self.assertIn('---- output ----', log.read_text(encoding='utf-8'))

    def test_journal_row_fields(self):
        project = Project(self, {'command': UNITTEST}, PASSING)
        project.hook()
        row = project.checks()[0]
        for key in ('version', 'session_id', 'tool_use_id', 'trigger_file', 'mode', 'status',
                    'tests_run', 'duration_s', 'full_bytes', 'visible_bytes', 'log_path',
                    'delta_fallback', 'delta_fallback_reason', 'visible_text', 'ts'):
            self.assertIn(key, row)
        self.assertEqual(row['version'], rc.VERSION)
        self.assertEqual(row['tool_use_id'], 'toolu_test')
        self.assertEqual(row['trigger_file'], 'src.py')
        self.assertEqual(row['visible_bytes'], len(row['visible_text'].encode()))
        self.assertGreater(row['full_bytes'], row['visible_bytes'])
        self.assertIsNone(row['delta_fallback'])  # not in delta mode

    def test_invalid_config_warns_user_only(self):
        project = Project(self, {'command': 'not-a-list'}, PASSING)
        result = project.hook()
        self.assertEqual(set(result), {'systemMessage'})
        self.assertIn('command', result['systemMessage'])

    def test_write_and_multiedit_trigger(self):
        project = Project(self, {'command': UNITTEST}, PASSING)
        self.assertIn('check #1', project.context(tool='Write'))
        project.touch_source('def f():\n    return 1  # changed\n')
        self.assertIn('check #2', project.context(tool='MultiEdit'))

    def test_other_tool_ignored(self):
        project = Project(self, {'command': UNITTEST}, PASSING)
        payload = project.payload()
        payload['tool_name'] = 'Read'
        self.assertIsNone(project.hook(payload=payload))


class Statuses(unittest.TestCase):
    def test_pass_selective_is_header_only(self):
        project = Project(self, {'command': UNITTEST}, PASSING)
        lines = project.context().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith('Post-edit check passed; tests=2; failing=0'))
        self.assertEqual(project.checks()[0]['status'], 'passed')

    def test_fail_selective_names_test_with_traceback(self):
        project = Project(self, {'command': UNITTEST}, FAILING)
        text = project.context()
        self.assertTrue(text.startswith('Post-edit check failed; tests=2; failing=1'))
        self.assertIn('FAILED: test_src.T.test_one', text)
        self.assertIn('AssertionError: 2 != 1', text)
        self.assertNotIn('test_two', text)

    def test_no_tests(self):
        project = Project(self, {'command': UNITTEST},
                          {'src.py': 'x = 1\n', 'test_src.py': 'import unittest\n'})
        self.assertIn('Post-edit check no_tests', project.context())
        self.assertEqual(project.checks()[0]['status'], 'no_tests')

    def test_all_skipped_is_no_tests(self):
        project = fake_project(self, 'selective', n=2)
        project.outcomes({'test_0': 'skip', 'test_1': 'skip'})
        self.assertIn('Post-edit check no_tests', project.context())

    def test_timeout(self):
        project = Project(self, {'command': [PY, '-c', 'import time; print("started", flush=True); time.sleep(30)'],
                                 'timeout_s': 1}, {'src.py': 'x = 1\n'})
        text = project.context()
        self.assertIn('Post-edit check timeout', text)
        self.assertIn('timed out after 1 s', text)
        self.assertLess(project.checks()[0]['duration_s'], 15)

    def test_error_when_command_missing(self):
        project = Project(self, {'command': ['definitely-not-a-real-binary-xyz']}, {'src.py': 'x = 1\n'})
        text = project.context()
        self.assertIn('Post-edit check error', text)
        self.assertIn('Check execution error', text)

    def test_stale_when_source_changes_during_check(self):
        mutate = "open('src.py','a').write('# touched\\n'); print('Ran 1 test in 0.0s'); print('OK')"
        project = Project(self, {'command': [PY, '-c', mutate]}, {'src.py': 'x = 1\n'})
        text = project.context()
        self.assertTrue(text.startswith('Post-edit check stale (underlying result passed'))
        row = project.checks()[0]
        self.assertEqual(row['status'], 'stale')
        self.assertNotEqual(row['source_before'], row['source_after'])
        # The edit that landed during the check is checked on the next trigger.
        self.assertIsNotNone(project.hook())

    def test_unchanged_source_is_skipped_and_journaled(self):
        project = Project(self, {'command': UNITTEST}, PASSING)
        self.assertIsNotNone(project.hook())
        self.assertIsNone(project.hook())
        kinds = [(e['kind'], e.get('reason')) for e in project.events()]
        self.assertEqual(kinds, [('check', None), ('skip', 'source_unchanged')])

    def test_non_source_edit_is_noop(self):
        project = Project(self, {'command': UNITTEST}, PASSING)
        self.assertIsNone(project.hook(payload=project.payload(rel='test_src.py')))
        self.assertIsNone(project.hook(payload=project.payload(rel='../elsewhere.py')))
        self.assertFalse((project.root / '.claude' / 'reticle-checks').exists())

    def test_pytest_ra_summary_parsed(self):
        project = Project(self, {'command': [PY, 'fake_pytest.py']},
                          {'src.py': 'x = 1\n', 'fake_pytest.py': PYTEST_OUTPUT})
        text = project.context()
        self.assertIn('Post-edit check failed; tests=3; failing=1', text)
        self.assertIn('FAILED: tests/test_x.py::test_beta', text)
        self.assertIn('E       assert 1 == 2', text)
        self.assertEqual(project.checks()[0]['runner'], 'pytest')

    def test_unknown_runner_uses_exit_code_and_excerpt(self):
        script = "import sys\nfor i in range(60): print('line', i)\nsys.exit(3)\n"
        project = Project(self, {'command': [PY, 'tool.py']}, {'src.py': 'x = 1\n', 'tool.py': script})
        text = project.context()
        self.assertIn('Post-edit check failed', text)
        self.assertIn('Exit code 3; no per-test results were parsed', text)
        self.assertIn('line 0', text)
        self.assertIn('line 59', text)
        self.assertIn('[20 output lines omitted; see full log]', text)
        project.write_config({'command': [PY, '-c', 'print("fine")']})
        project.touch_source('x = 2\n')
        self.assertTrue(project.context().startswith('Post-edit check passed'))


class Modes(unittest.TestCase):
    def test_full_mode_includes_output_and_states_cap(self):
        project = Project(self, {'command': UNITTEST, 'mode': 'full'}, PASSING)
        text = project.context()
        self.assertIn('mode=full (output shown whole up to 8000 bytes)', text)
        self.assertIn('test_one (test_src.T', text)
        self.assertIn('Ran 2 tests', text)
        self.assertNotIn('\r', text)  # Windows child output is normalised to \n

    def test_full_mode_caps_middle(self):
        script = "for i in range(400): print('row %03d ' % i + 'x' * 40)\n"
        project = Project(self, {'command': [PY, 'tool.py'], 'mode': 'full', 'full_cap_bytes': 1000},
                          {'src.py': 'x = 1\n', 'tool.py': script})
        text = project.context()
        self.assertIn('row 000', text)
        self.assertIn('row 399', text)
        self.assertNotIn('row 200', text)
        self.assertRegex(text, r'\[\.\.\. \d+ bytes omitted from the middle \(full-mode cap 1000 bytes\)')
        self.assertLess(project.checks()[0]['visible_bytes'], 1700)

    def test_selective_long_traceback_excerpt(self):
        project = fake_project(self, 'selective', n=3)
        project.outcomes({'test_0': 'ok', 'test_1': 'FAIL', 'test_2': 'ok'}, trace_lines=30)
        text = project.context()
        self.assertIn('FAILED: mod.T.test_1', text)
        self.assertIn('line 0, in test_1', text)   # head (4 lines incl. "Traceback")
        self.assertIn('line 2, in test_1', text)
        self.assertNotIn('line 3, in test_1', text)
        self.assertIn('[19 traceback lines omitted; see full log]', text)
        self.assertIn('line 29, in test_1', text)  # tail (last 9 lines)
        self.assertIn('AssertionError: test_1 broke', text)

    def test_selective_long_output_bounded_below_hook_cap(self):
        project = fake_project(self, 'selective', n=200)
        project.outcomes({f'test_{i}': 'FAIL' for i in range(200)}, trace_lines=12)
        text = project.context()
        self.assertLessEqual(len(text), 9000)
        self.assertIn('characters omitted to fit the hook context limit', text)
        self.assertTrue(text.splitlines()[-1].startswith('Full log: '))


class Delta(unittest.TestCase):
    def test_first_check_falls_back_without_baseline(self):
        project = fake_project(self, 'delta')
        text = project.context()
        self.assertIn('mode=selective', text)
        row = project.checks()[0]
        self.assertEqual((row['rendered_as'], row['delta_fallback'], row['delta_fallback_reason']),
                         ('selective', True, 'no_baseline'))

    def _two_failing_then_one_new(self):
        project = fake_project(self, 'delta')
        tests = {f'test_{i}': 'ok' for i in range(8)}
        tests['test_1'] = 'FAIL'
        tests['test_2'] = 'FAIL'
        project.outcomes(tests, trace_lines=6)
        project.context()                       # check 1: baseline, selective
        tests['test_2'] = 'ok'
        tests['test_5'] = 'FAIL'
        project.outcomes(tests, trace_lines=6)
        project.touch_source('v = 1\n')
        return project, tests

    def test_delta_shows_newly_failing_passing_and_still_count(self):
        project, _ = self._two_failing_then_one_new()
        text = project.context()
        self.assertIn('mode=delta (relative to check #1; changed 2/8 test ids)', text)
        self.assertIn('Newly failing (1):\nFAILED: mod.T.test_5', text)
        self.assertIn('AssertionError: test_5 broke', text)
        self.assertIn('Newly passing (1): mod.T.test_2', text)
        self.assertIn('Still failing: 1 (as reported in check #1).', text)
        self.assertNotIn('test_1 broke', text)  # still-failing traceback not repeated
        row = project.checks()[-1]
        self.assertEqual((row['rendered_as'], row['delta_fallback'], row['changed_fraction']),
                         ('delta', False, 0.25))

    def test_delta_smaller_than_selective(self):
        project, tests = self._two_failing_then_one_new()
        delta_text = project.context()
        project.write_config({'command': [PY, 'fake_runner.py'], 'mode': 'selective'})
        project.touch_source('v = 2\n')
        selective_text = project.context()
        self.assertLess(len(delta_text.encode()), len(selective_text.encode()))

    def test_unchanged_failures_render_as_delta(self):
        project = fake_project(self, 'delta')
        tests = {f'test_{i}': 'ok' for i in range(8)}
        tests['test_3'] = 'FAIL'
        project.outcomes(tests, trace_lines=6)
        project.context()
        project.touch_source('v = 1\n')
        text = project.context()
        self.assertIn('Newly failing: none.', text)
        self.assertIn('Still failing: 1', text)
        self.assertNotIn('test_3 broke', text)

    def test_falls_back_when_changes_not_sparse(self):
        project = fake_project(self, 'delta')
        project.context()
        project.outcomes({f'test_{i}': ('FAIL' if i < 3 else 'ok') for i in range(8)})
        project.touch_source('v = 1\n')
        text = project.context()
        self.assertIn('mode=selective', text)
        row = project.checks()[-1]
        self.assertEqual(row['delta_fallback_reason'], 'changes_not_sparse')
        self.assertEqual(row['changed_fraction'], 3 / 8)

    def test_falls_back_when_delta_not_smaller(self):
        project = fake_project(self, 'delta')
        project.context()
        project.touch_source('v = 1\n')
        text = project.context()                  # pass -> pass: header only is smallest
        self.assertEqual(len(text.splitlines()), 2)
        self.assertEqual(project.checks()[-1]['delta_fallback_reason'], 'delta_not_smaller')

    def test_falls_back_when_status_not_comparable(self):
        project = fake_project(self, 'delta')
        project.context()
        project.write_config({'command': [PY, '-c', 'import time; time.sleep(30)'],
                              'mode': 'delta', 'timeout_s': 1})
        project.touch_source('v = 1\n')
        project.context()
        self.assertEqual(project.checks()[-1]['delta_fallback_reason'], 'status_not_comparable')

    def test_compaction_invalidates_baseline(self):
        for entry_payload in ({'event': 'PreCompact', 'trigger': 'auto', 'custom_instructions': None},
                              {'event': 'SessionStart', 'source': 'compact'}):
            with self.subTest(entry_payload['event']):
                project, _ = self._two_failing_then_one_new()
                out = project.hook('invalidate', project.payload(**entry_payload))
                self.assertIsNone(out)  # prints nothing (SessionStart stdout would become context)
                text = project.context()
                self.assertIn('mode=selective', text)
                row = project.checks()[-1]
                self.assertEqual(row['delta_fallback_reason'], 'baseline_not_in_context')
                inval = [e for e in project.events() if e['kind'] == 'baseline_invalidated']
                self.assertEqual(len(inval), 1)
                self.assertTrue(inval[0]['had_baseline_in_context'])
                # The check after compaction is in context again, so the next one may be a delta.
                tests = {f'test_{i}': 'ok' for i in range(8)}
                tests.update(test_1='FAIL', test_5='FAIL', test_6='FAIL')
                project.outcomes(tests, trace_lines=6)
                project.touch_source('v = 9\n')
                self.assertIn('mode=delta', project.context())

    def test_invalidate_without_config_or_session_is_silent(self):
        project = fake_project(self, 'delta')
        self.assertIsNone(project.hook('invalidate', project.payload(event='PreCompact', trigger='manual')))
        self.assertEqual(project.events(), [])

    def test_stale_result_does_not_become_baseline(self):
        project = fake_project(self, 'delta')
        project.context()                          # baseline from check 1
        mutate = ("import runpy, sys; open('src.py','a').write('#\\n'); sys.argv=['fake_runner.py'];"
                  " runpy.run_path('fake_runner.py', run_name='__main__')")
        project.write_config({'command': [PY, '-c', mutate], 'mode': 'delta'})
        project.touch_source('v = 1\n')
        project.context()
        state = json.loads((project.root / '.claude' / 'reticle-checks' / project.session /
                            'state.json').read_text())
        self.assertEqual(state['baseline']['number'], 1)


class Helpers(unittest.TestCase):
    def test_glob_to_regex(self):
        cases = [('*.py', 'a.py', True), ('*.py', 'pkg/a.py', False), ('**/*.py', 'a.py', True),
                 ('**/*.py', 'pkg/sub/a.py', True), ('src/**', 'src/x/y.txt', True),
                 ('calc.py', 'calc.py', True), ('calc.py', 'calc.pyc', False),
                 ('test_?.py', 'test_a.py', True), ('[ab].py', 'c.py', False)]
        for pattern, path, expected in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(bool(rc.glob_to_regex(pattern).match(path)), expected)

    def test_unittest_parser_py310_and_docstring_forms(self):
        output = ('test_a (pkg.mod.T) ... ok\n'
                  'test_b (pkg.mod.T.test_b)\nDoes b ... FAIL\n'
                  'test_c (pkg.mod.T.test_c) ... skipped \'later\'\n'
                  'Ran 3 tests in 0.0s\n')
        parsed = rc.parse_unittest(output)
        self.assertEqual(parsed['results'], {'pkg.mod.T.test_a': 'passed', 'pkg.mod.T.test_b': 'failed',
                                             'pkg.mod.T.test_c': 'skipped'})
        self.assertEqual(parsed['tests_run'], 3)

    def test_excerpt_rule(self):
        self.assertEqual(len(rc.excerpt_trace('\n'.join(map(str, range(14))))), 14)
        cut = rc.excerpt_trace('\n'.join(map(str, range(15))))
        self.assertEqual(cut[:4], ['0', '1', '2', '3'])
        self.assertEqual(cut[-9:], [str(i) for i in range(6, 15)])
        self.assertEqual(len(cut), 14)


if __name__ == '__main__':
    unittest.main()
