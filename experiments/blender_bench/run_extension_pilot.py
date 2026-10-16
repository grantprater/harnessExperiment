"""Five real Blender tasks with persistent generated tools and independent checks.

Run explicitly. It uses the existing Reticle subscription login by default.
The model only operates in the newly created workspace, not the verifier or driver.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reticle.interactive import add_arguments, launch
from reticle.runtime.session import LocalRuntime
from reticle.runtime.telemetry import usage_report
from reticle.storage.artifacts import atomic_write_json


BLENDER = Path(r'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe')
TASKS = [
    {'id': '01-chair', 'kind': 'dining chair', 'surface': 'Seat', 'width': 0.48, 'depth': 0.48, 'height': 0.45,
     'back_height': 0.90, 'supports': ['Leg_1', 'Leg_2', 'Leg_3', 'Leg_4']},
    {'id': '02-stool', 'kind': 'backless stool', 'surface': 'Seat', 'width': 0.36, 'depth': 0.36, 'height': 0.65,
     'supports': ['Leg_1', 'Leg_2', 'Leg_3', 'Leg_4']},
    {'id': '03-bench', 'kind': 'bench with two solid end supports', 'surface': 'Seat', 'width': 1.20, 'depth': 0.40,
     'height': 0.45, 'back_height': 0.85, 'supports': ['Support_1', 'Support_2']},
    {'id': '04-curved-chair', 'kind': 'chair with a curved back', 'surface': 'Seat', 'width': 0.52, 'depth': 0.50,
     'height': 0.46, 'back_height': 0.95, 'curved': True, 'supports': ['Leg_1', 'Leg_2', 'Leg_3', 'Leg_4']},
    {'id': '05-table', 'kind': 'rectangular dining table', 'surface': 'Tabletop', 'width': 1.20, 'depth': 0.70,
     'height': 0.75, 'supports': ['Leg_1', 'Leg_2', 'Leg_3', 'Leg_4']},
]


def prompt(spec, first):
    introduction = ('This is the first of a sequence of related furniture tasks. You may construct, test, '
                    'and revise reusable Python extensions when useful, using extension_stage. '
                    'Extensions activate at the next user turn. Solve this task now using existing primitives '
                    'as needed, and preserve useful tools for later tasks. Choose your own abstractions.\n'
                    if first else 'Continue the furniture sequence. Reuse generated tools when useful; '
                    'revise or build tools if this task calls for new capabilities.\n')
    return introduction + f'''Create a {spec['kind']} in Blender from a new empty scene.
Blender executable: {BLENDER.as_posix()}
Use headless Blender Python via commands or generated Python adapters. The harness Python itself has no bpy.
Executable commands may use quoted absolute paths. Blender supports --background --factory-startup
--python-exit-code 1 --python SCRIPT.py. Use --python-exit-code so Python errors fail visibly.
Read ENVIRONMENT.md for execution details and the extension interface. You may edit your workspace and
generated tools; do not edit the harness, experiment driver, verifier, credentials or anything outside this workspace.

Requirements (all dimensions in meters, X=width, Y=depth, Z=up):
- Use metric units, scale_length=1. Surface must be a mesh object named {spec['surface']}.
- Surface width={spec['width']}, depth={spec['depth']}, thickness=0.05.
- Surface TOP is at z={spec['height']}; bottom is 0.05 lower.
- Required support mesh objects: {', '.join(spec['supports'])}. They must meet the floor at z=0
  and reach the underside of the surface. Place them sensibly at distinct corners or bench ends.
- {f"A mesh named Back must span the surface width and reach z={spec['back_height']}." if spec.get('back_height') else 'There must be no object named Back.'}
- {'The back must curve across its width in the XY plane, with the center and outer portions differing in mean Y by at least 0.03m. Use enough mesh segments to show a real arc.' if spec.get('curved') else 'Use a simple clean furniture design.'}
- Give the furniture an appropriate material. Add a floor, camera and studio lighting.
- Meshes must have consistent outward winding, no degenerate or duplicate faces, and no same-facing
  coplanar overlaps between parts. Opposite-facing contact surfaces at joints are allowed. Inspect
  source and evaluated geometry, not just object bounding boxes. ext_mesh_audit is available when
  the runner was started with --mesh-quality-tools. Fix geometry findings before finishing.
- Render a clearly framed 512x512 PNG to artifacts/{spec['id']}.png. Use Cycles CPU with 16 samples
  to keep rendering modest; configure the camera to show the entire piece.
- Save the completed scene to artifacts/{spec['id']}.blend. Preserve earlier artifacts and generated tools.
- Inspect the saved scene or check your computed geometry and report what you verified.

Smoke tests for an extension must work in a temporary empty workspace without external services.
A Blender adapter may run small headless Blender smoke tests, or test argument/script construction separately
when context['validation'] is true. A staging success does not establish furniture correctness.
Finish only after the requested .blend and PNG exist. If blocked, report the actual problem.
'''


def verify(run, workspace, spec):
    directory = run / 'verification' / spec['id']
    directory.mkdir(parents=True, exist_ok=True)
    spec_path, result_path = directory / 'spec.json', directory / 'result.json'
    atomic_write_json(spec_path, spec)
    blend = workspace / 'artifacts' / (spec['id'] + '.blend')
    image = workspace / 'artifacts' / (spec['id'] + '.png')
    result = {'all_passed': False, 'checks': {'blend_exists': blend.is_file(), 'render_exists': image.is_file()}}
    if blend.is_file():
        process = subprocess.run([str(BLENDER), '--background', str(blend), '--python-exit-code', '1',
                                  '--python', str(Path(__file__).with_name('verify_furniture.py')),
                                  '--', str(spec_path), str(result_path)],
                                 capture_output=True, timeout=120, cwd=directory)
        (directory / 'blender.stdout.txt').write_bytes(process.stdout)
        (directory / 'blender.stderr.txt').write_bytes(process.stderr)
        if process.returncode == 0 and result_path.is_file():
            measured = json.loads(result_path.read_text(encoding='utf-8'))
            result = {**measured, 'checks': {**measured['checks'], **result['checks']}}
        else:
            result['verifier_exit_code'] = process.returncode
    if image.is_file():
        from PIL import Image, ImageStat
        with Image.open(image) as preview:
            result['checks']['render_dimensions'] = preview.size == (512, 512)
            result['checks']['render_nonblank'] = max(ImageStat.Stat(preview.convert('RGB')).stddev) > 2
    else:
        result['checks']['render_dimensions'] = result['checks']['render_nonblank'] = False
    result['passed'] = sum(result['checks'].values())
    result['total'] = len(result['checks'])
    result['all_passed'] = all(result['checks'].values())
    atomic_write_json(result_path, result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--client', default='chatgpt-subscription')
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--max-steps', type=int, default=30)
    parser.add_argument('--mesh-quality-tools', action='store_true',
                        help='Provide a validated mesh audit extension from the first turn')
    options = parser.parse_args()
    run = Path(options.run_dir).resolve()
    if run.exists():
        raise ValueError('Use a new run directory; existing pilot results are never overwritten')
    workspace = run / 'workspace'
    workspace.mkdir(parents=True)
    (workspace / 'artifacts').mkdir()
    session = workspace / '.reticle/session'
    report_path = run / 'usage.json'
    if options.mesh_quality_tools:
        import shutil
        from reticle.execution import TrustedLocalBackend
        from reticle.runtime.extensions import ExtensionRegistry
        source = workspace / 'provided_tools/mesh_audit'
        shutil.copytree(ROOT / 'examples/extensions/blender_mesh_audit', source,
                        ignore=shutil.ignore_patterns('__pycache__'))
        runtime = LocalRuntime(session, workspace)
        ExtensionRegistry(runtime, TrustedLocalBackend(), sys.executable).stage(source)
    (workspace / 'ENVIRONMENT.md').write_text(
        f'Blender: `{BLENDER.as_posix()}` (5.0.0). Use background Python, not bpy in harness Python.\n'
        'The workspace is your only editing scope. Artifacts and extension sources persist across turns.\n'
        'Generated tools: write a directory containing manifest.json and tool.py. The manifest requires\n'
        'name ext_*, description, parameters (object JSON schema), entrypoint "tool.py:execute",\n'
        'smoke_tests [{"arguments": {...}, "expected": optional JSON}], optional timeout_seconds (0–600).\n'
        'def execute(arguments, context) receives workspace (absolute path) and validation (bool), returning JSON.\n'
        'Use extension_stage(path=directory) to validate/queue. Schemas and versions freeze for this turn;\n'
        'the next turn activates pending tools. extension_list lists versions, extension_rollback queues a prior one.\n'
        'Schemas support explicit types, properties, required, additionalProperties=false, items, enum,\n'
        'minimum/maximum, min/maxLength, min/maxItems. Unknown constraints are rejected.\n'
        'Use ordinary Python subprocess calls inside adapters to invoke Blender. No packages are installed for you.\n',
        encoding='utf-8')
    summary = {'started_at': datetime.now(timezone.utc).isoformat(), 'model': options.model,
               'client': options.client, 'condition': 'persistent-generated-extensions',
               'model_usage_feedback': False, 'runtime_source_modification': False,
               'mesh_quality_tools': options.mesh_quality_tools,
               'run_dir': str(run), 'tasks': [], 'status': 'running'}
    atomic_write_json(run / 'summary.json', summary)
    argument_parser = argparse.ArgumentParser()
    add_arguments(argument_parser)
    try:
        for index, spec in enumerate(TASKS):
            task_prompt = prompt(spec, index == 0)
            (run / (spec['id'] + '.prompt.txt')).write_text(task_prompt, encoding='utf-8')
            arguments = [task_prompt, '--once', '--extensions', '--client', options.client,
                         '--model', options.model, '--max-steps', str(options.max_steps),
                         '--usage-report', str(report_path), '-C', str(workspace)]
            arguments += ['--session-dir' if index == 0 and not options.mesh_quality_tools else '--resume', str(session)]
            print(f'\n=== {spec["id"]}: {spec["kind"]} ===', flush=True)
            started = time.monotonic()
            exit_code = launch(argument_parser.parse_args(arguments))
            elapsed = time.monotonic() - started
            measurements = usage_report(LocalRuntime(session))
            atomic_write_json(run / (spec['id'] + '.usage.json'), measurements)
            checked = verify(run, workspace, spec)
            row = {'id': spec['id'], 'exit_code': exit_code, 'duration_seconds': round(elapsed, 2),
                   'verification': checked, 'usage': measurements['tasks'][-1] if measurements['tasks'] else None}
            summary['tasks'].append(row)
            atomic_write_json(run / 'summary.json', summary)
            print(f'Independent checks: {checked["passed"]}/{checked["total"]}', flush=True)
            if row['usage'] and row['usage']['stop_reason'] in ('model_error', 'needs_reconciliation'):
                summary['status'] = 'blocked'
                break
        else:
            summary['status'] = 'complete'
    except Exception as exc:
        summary['status'] = 'error'
        summary['error'] = str(exc)
        traceback.print_exc()
    finally:
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(run / 'summary.json', summary)
        print(f'\nPilot {summary["status"]}: {run}', flush=True)
    return 0 if summary['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
