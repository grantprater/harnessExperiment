"""Actual extension registry/Blender integration; no model calls."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from reticle.interactive import add_arguments, learning_tools
from reticle.runtime.session import LocalRuntime
import argparse


ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path(r'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe')


@unittest.skipUnless(BLENDER.is_file(), 'Local Blender 5.0 is required')
class BlenderMeshExtensionTests(unittest.TestCase):
    def test_read_only_audit_through_versioned_extension_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / 'workspace'
            workspace.mkdir()
            asset = workspace / 'fixture.blend'
            fixture = subprocess.run([str(BLENDER), '--background', '--factory-startup', '--python-exit-code', '1',
                                      '--python-expr', f'import bpy; bpy.ops.wm.save_as_mainfile(filepath={str(asset)!r})'],
                                     capture_output=True, timeout=60)
            self.assertEqual(fixture.returncode, 0, fixture.stderr.decode(errors='replace'))
            original = hashlib.sha256(asset.read_bytes()).hexdigest()
            source = workspace / 'provided_tools/mesh_audit'
            shutil.copytree(ROOT / 'examples/extensions/blender_mesh_audit', source,
                            ignore=shutil.ignore_patterns('__pycache__'))
            runtime = LocalRuntime(root / 'session', workspace)
            parser = argparse.ArgumentParser()
            add_arguments(parser)
            tools = learning_tools(runtime, parser.parse_args(['--extensions', '--quiet']))[0]
            tools.quiet = True
            staged = tools.dispatch('extension_stage', {'path': 'provided_tools/mesh_audit'}, 'stage')
            self.assertEqual(staged.status, 'success', staged.content)
            tools.extensions.begin_turn('audit-test')
            outcome = tools.dispatch('ext_mesh_audit', {'blend_file': 'fixture.blend'}, 'audit')
            self.assertEqual(outcome.status, 'success', outcome.content)
            value = json.loads(outcome.content.rsplit('RETICLE_EXTENSION_RESULT=', 1)[1])
            self.assertTrue(value['passed'], value)
            self.assertTrue(value['complete'])
            self.assertTrue((workspace / value['report_path']).is_file())
            self.assertEqual(hashlib.sha256(asset.read_bytes()).hexdigest(), original)
            report = json.loads((workspace / value['report_path']).read_text(encoding='utf-8'))
            self.assertEqual(report['summary']['objects'], 1)


if __name__ == '__main__':
    unittest.main()
