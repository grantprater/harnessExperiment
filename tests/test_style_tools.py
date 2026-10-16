"""Image/CSS profiles and model tool dispatch without external model services."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from reticle.interactive import ROOT, launch, learning_tools
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.controller import AgentController, AgentLimits
from reticle.runtime.session import LocalRuntime
from reticle.runtime.style import StyleService, css_measurements
from reticle.runtime.telemetry import usage_report
from tests.test_extensions import SequenceClient
from tests.test_runtime_updates import args


REFERENCE = ':root { --brand: #203040; --paper: #e0d0c0; }\n.card { color: var(--brand); background: var(--paper); font-family: "Inter", sans-serif; padding: 8px 16px; gap: 8px; border-radius: 4px; font-size: 16px; }\n'
CANDIDATE = '.card { color: #ff0000; background: #00ff00; font-family: Georgia, serif; padding: 13px; gap: 7px; border-radius: 11px; font-size: 22px; }\n'


class StyleToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        (self.workspace / 'reference.css').write_text(REFERENCE, encoding='utf-8')
        (self.workspace / 'candidate.css').write_text(CANDIDATE, encoding='utf-8')
        self.runtime = LocalRuntime(self.root / 'session', self.workspace)
        self.style = StyleService(self.runtime)

    def profile(self, references=None):
        return self.style.extract(references or ['reference.css'])

    def image(self, name, colors, alpha=False):
        image = Image.new('RGBA', (32, 32), (*colors[0], 0 if alpha else 255))
        for x in range(16, 32):
            for y in range(32):
                image.putpixel((x, y), (*colors[1], 128 if alpha else 255))
        image.save(self.workspace / name)

    def test_css_profile_check_and_explicit_application(self):
        profile = self.profile()
        before = self.style.check('candidate.css', profile['profile_id'])
        self.assertFalse(before['measured_checks_passed'])
        self.assertEqual({f['feature'] for f in before['findings']},
                         {'palette', 'font_family', 'spacing', 'radii', 'font_sizes'})
        self.assertTrue(self.style.check('reference.css', profile['profile_id'])['measured_checks_passed'])
        result = self.style.apply('candidate.css', 'aligned.css',
                                 ['palette', 'fonts', 'spacing', 'radii', 'font_sizes'], profile['profile_id'])
        self.assertTrue(result['after']['measured_checks_passed'], result)
        self.assertIn('@@', result['diff'])
        self.assertEqual((self.workspace / 'candidate.css').read_text(), CANDIDATE)
        self.assertFalse(result['after']['semantic_style_assessed'])

    def test_missing_features_and_malformed_targets_do_not_pass(self):
        import copy
        profile = self.profile()
        self.assertEqual(self.style.profile(profile['profile_id'])['profile'], profile['profile'])
        (self.workspace / 'layout-only.css').write_text('.x { display: flex; }', encoding='utf-8')
        result = self.style.check('layout-only.css', profile['profile_id'])
        self.assertFalse(result['complete'])
        self.assertFalse(result['measured_checks_passed'])
        for replacement in (None, {'palette': []}, {'palette': [], 'font_families': [], 'length_tokens': {'spacing': [None]}}):
            malformed = copy.deepcopy(profile['profile'])
            malformed['domains']['css'] = replacement
            with self.assertRaises(ValueError):
                self.style.store(malformed)

    def test_partial_css_operations_do_not_claim_all_mismatches_fixed(self):
        profile = self.profile()
        result = self.style.apply('candidate.css', 'colors-only.css', ['palette'], profile['profile_id'])
        self.assertFalse(result['after']['measured_checks_passed'])
        self.assertNotIn('palette', {f['feature'] for f in result['after']['findings']})
        self.assertEqual((self.workspace / 'candidate.css').read_text(), CANDIDATE)

    def test_image_palette_application_preserves_source_dimensions_and_alpha(self):
        self.image('reference.png', [(30, 60, 90), (210, 190, 150)])
        self.image('candidate.png', [(255, 0, 0), (0, 255, 0)], alpha=True)
        original = (self.workspace / 'candidate.png').read_bytes()
        profile = self.profile(['reference.png'])
        before = self.style.check('candidate.png', profile['profile_id'])
        self.assertFalse(before['measured_checks_passed'])
        result = self.style.apply('candidate.png', 'aligned.png', ['palette'], profile['profile_id'])
        self.assertTrue(result['after']['measured_checks_passed'], result)
        self.assertEqual((self.workspace / 'candidate.png').read_bytes(), original)
        with Image.open(self.workspace / 'candidate.png') as source, Image.open(self.workspace / 'aligned.png') as output:
            self.assertEqual(source.size, output.size)
            self.assertEqual(source.getchannel('A').tobytes(), output.getchannel('A').tobytes())

    def test_mixed_visual_and_css_references(self):
        self.image('reference.png', [(30, 60, 90), (210, 190, 150)])
        profile = self.profile(['reference.css', 'reference.png'])
        self.assertEqual(set(profile['profile']['domains']), {'image', 'css'})
        self.assertEqual(len(profile['profile']['references']), 2)

    def test_profiles_are_content_addressed_and_tampering_is_rejected(self):
        first = self.profile()
        self.assertEqual(first['profile_id'], self.profile()['profile_id'])
        path = self.workspace / first['profile_path']
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'changed after extraction'):
            self.style.check('candidate.css', first['profile_id'])

    def test_pinned_target_survives_resume_and_cannot_be_replaced_by_proposal(self):
        first = self.profile()
        pinned = StyleService(self.runtime, self.workspace / first['profile_path'])
        proposal = pinned.extract(['candidate.css'])
        self.assertTrue(proposal['proposal_only'])
        with self.assertRaisesRegex(ValueError, 'pinned'):
            pinned.check('candidate.css', proposal['profile_id'])
        resumed = StyleService(LocalRuntime(self.runtime.session_dir))
        self.assertEqual(resumed.target_id, first['profile_id'])
        self.assertFalse(resumed.check('candidate.css')['measured_checks_passed'])
        with self.assertRaisesRegex(ValueError, 'fresh session'):
            StyleService(self.runtime, self.workspace / proposal['profile_path'])

    def test_unknown_css_coverage_is_not_a_pass_and_strings_are_preserved(self):
        profile = self.profile()
        for value in ('.a {color: red;}', '.a {color: hsl(0 100% 50%);}', '.a {color: var(--missing);}'):
            (self.workspace / 'unknown.css').write_text(value)
            result = self.style.check('unknown.css', profile['profile_id'])
            self.assertFalse(result['complete'])
            self.assertFalse(result['measured_checks_passed'])
        (self.workspace / 'url.css').write_text('.a { background-image: url("icons/#ff0000.svg"); content: "#ff0000;"; color: #203040; }')
        result = self.style.apply('url.css', 'url-aligned.css', ['palette'], profile['profile_id'])
        self.assertIn('url("icons/#ff0000.svg")', (self.workspace / 'url-aligned.css').read_text())
        self.assertIn('content: "#ff0000;"', (self.workspace / 'url-aligned.css').read_text())

    def test_css_scanner_handles_nested_rules_comments_and_percentages(self):
        measured = css_measurements(b'/* note */ @media (min-width: 800px) { .x { padding: 5%; font-family: "A;B", serif; color: rgb(20, 30, 40); } }')
        self.assertEqual(measured['lengths']['spacing'][0]['unit'], '%')
        self.assertEqual(measured['colors'][0]['rgb'], [20, 30, 40])
        self.assertEqual(measured['fonts'][0]['family'], '"a;b",serif')

    def test_css_application_aligns_simple_variables_without_injecting_font_syntax(self):
        (self.workspace / 'special-reference.css').write_text('.x {font-family: "A;B", serif; padding:8px; border-radius:4px;}')
        profile = self.profile(['special-reference.css'])
        (self.workspace / 'variables.css').write_text(':root {--space:13px; --radius:7px; --font:Arial;} .x {padding:var(--space); border-radius:var(--radius); font-family:var(--font);}')
        result = self.style.apply('variables.css', 'variables-aligned.css', ['spacing', 'radii', 'fonts'], profile['profile_id'])
        self.assertTrue(result['after']['measured_checks_passed'], result)
        output = (self.workspace / 'variables-aligned.css').read_text()
        self.assertIn('--font:"a;b",serif;', output)
        self.assertIn('padding:var(--space)', output)

    def test_invalid_inputs_and_outputs_are_rejected(self):
        profile = self.profile()
        for output in ('candidate.css', 'reference.css', '../escape.css'):
            with self.assertRaises(ValueError):
                self.style.apply('candidate.css', output, ['palette'], profile['profile_id'])
        with self.assertRaises(ValueError):
            self.style.extract(['../outside.css'])
        with self.assertRaises(ValueError):
            self.style.apply('candidate.css', 'invalid.css', ['invented_operation'], profile['profile_id'])
        self.assertFalse((self.workspace / 'invalid.css').exists())

    def test_controller_tools_and_usage_reports(self):
        profile = self.profile()
        tools = learning_tools(self.runtime, args('--style-tools'))[0]
        tools.quiet = True
        client = SequenceClient([('style_check', {'candidate': 'candidate.css', 'profile_id': profile['profile_id']}),
                                 ('style_apply', {'candidate': 'candidate.css', 'profile_id': profile['profile_id'],
                                  'output_path': 'aligned.css', 'operations': ['palette', 'fonts', 'spacing', 'radii', 'font_sizes']}),
                                 ('finish', {'summary': 'Aligned'})])
        result = AgentController(self.runtime, TaskEnvelope('style-task', 'Align CSS'), tools,
                                 client, AgentLimits(4, 120000)).run()
        self.assertEqual(result.stop_reason, 'finish_requested')
        report = usage_report(self.runtime)
        self.assertEqual(report['style']['applications'][0]['task_id'], 'style-task')
        self.assertFalse(report['style']['checks'][0]['measured_checks_passed'])
        self.assertTrue(report['style']['checks'][-1]['measured_checks_passed'])
        disabled = learning_tools(self.runtime, args())[0]
        self.assertNotIn('style_extract', [s['function']['name'] for s in disabled.schemas()])

    def test_model_gets_decision_summary_with_retrievable_full_report(self):
        profile = self.profile()
        tools = learning_tools(self.runtime, args('--style-tools'))[0]
        tools.quiet = True
        failed = json.loads(tools.dispatch('style_check', {'candidate':'candidate.css', 'profile_id':profile['profile_id']}, 'failed-check').content)
        full = json.loads((self.workspace/failed['report_path']).read_text())
        self.assertGreater(len(full['findings']), len(failed['findings']))
        self.assertEqual(len(failed['findings']), 3)
        self.assertFalse(failed['measured_checks_passed'])
        passed = json.loads(tools.dispatch('style_check', {'candidate':'reference.css', 'profile_id':profile['profile_id']}, 'passed-check').content)
        self.assertTrue(passed['measured_checks_passed'])
        self.assertNotIn('findings', passed)
        self.assertTrue((self.workspace/passed['report_path']).exists())

    def test_runtime_workers_support_pinned_style_profile(self):
        from reticle.runtime.supervisor import RuntimeSupervisor
        profile = self.profile()
        options = args('--runtime-updates', '--style-tools', '--style-profile', str(self.workspace / profile['profile_path']),
                       '--quiet', '-C', str(self.workspace), '--resume', str(self.runtime.session_dir))
        client = SequenceClient([('style_check', {'candidate': 'reference.css'}), ('finish', {'summary': 'Checked'})])
        supervisor = RuntimeSupervisor(self.runtime.session_dir, self.workspace, options, client, ROOT)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(supervisor.run_turn('Check project style'), 0)
        report = usage_report(LocalRuntime(self.runtime.session_dir))
        self.assertEqual(report['calls'][0]['style_profile_id'], profile['profile_id'])


if __name__ == '__main__':
    unittest.main()
