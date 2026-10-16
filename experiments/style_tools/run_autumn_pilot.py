"""Two real harness-generated raster assets with a pinned autumn style target.

Uses the existing subscription login. All model editing is scoped to a fresh
workspace; independent scoring uses the driver's original in-memory profile.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw, ImageStat
from reticle.interactive import add_arguments, launch
from reticle.runtime.session import LocalRuntime
from reticle.runtime.style import StyleService, check_measurements, measure, encoded
from reticle.runtime.telemetry import usage_report
from reticle.storage.artifacts import atomic_write_json

PALETTE = ['#f4e6ce', '#d9b382', '#b96b36', '#7d3f28', '#483326', '#72734a']
TASKS = [('01-reading', 'a steaming ceramic mug beside an open book, a knitted blanket and fallen autumn leaves'),
         ('02-lantern', 'a glowing lantern beside a pumpkin, a folded knitted scarf and fallen autumn leaves')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--max-steps', type=int, default=20)
    parser.add_argument('--context-policy', choices=['decision', 'minimal', 'pressure-v4'], default='decision')
    parser.add_argument('--max-context-bytes', type=int, default=32000)
    parser.add_argument('--token-target', type=int, default=5000,
                        help='Soft target per asset; two assets aim for 10000 total tokens')
    options = parser.parse_args()
    run = options.run_dir.resolve()
    if run.exists():
        raise ValueError('Use a fresh run directory')
    workspace = run / 'workspace'
    workspace.mkdir(parents=True)
    (workspace / 'artifacts').mkdir()
    (workspace / 'references').mkdir()
    reference = Image.new('RGB', (600, 100))
    draw = ImageDraw.Draw(reference)
    for index, color in enumerate(PALETTE):
        draw.rectangle((index*100, 0, (index+1)*100-1, 99), fill=color)
    reference.save(workspace / 'references/autumn-palette.png')
    brief = '''Cozy autumn: warm cream, oat, burnt orange, chestnut, dark cocoa and muted olive.
Create a cohesive pair of polished flat editorial illustrations: rounded forms,
gentle curves, dark cocoa outlines, restrained decorative marks, lots of breathing
room, cream background, similar stroke weight and visual scale. Avoid text.
This brief's composition/theme rules require visual review; the automated image
style checker measures the shared palette, with advisory density/brightness.
'''
    (workspace / 'references/STYLE.md').write_text(brief, encoding='utf-8')
    runtime = LocalRuntime(workspace / '.reticle/session', workspace)
    extracted = StyleService(runtime).extract(['references/autumn-palette.png'], 'Cozy autumn illustration palette')
    profile = extracted['profile']
    target = run / 'target-profile.json'
    target.write_bytes(encoded(profile))
    # Give the model a workspace copy, but score against the original profile above.
    (workspace / 'references/target-profile.json').write_bytes(encoded(profile))
    summary = {'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
               'model': options.model, 'profile_id': extracted['profile_id'],
               'condition': 'two-turn-cozy-autumn-with-pinned-style-tools',
               'context_policy': options.context_policy, 'max_context_bytes':options.max_context_bytes,
               'token_target_per_task':options.token_target,
               'token_target_total': options.token_target * len(TASKS),
               'automated_scope': 'Palette and artifact validity; theme/composition/style require visual review',
               'tasks': []}
    atomic_write_json(run / 'summary.json', summary)
    cli = argparse.ArgumentParser()
    add_arguments(cli)
    try:
        for index, (asset_id, subject) in enumerate(TASKS):
            prompt = f'''Generate visual asset {index+1} of 2 in a shared "cozy autumn" illustration project.
Subject: {subject}.
Read references/STYLE.md and references/autumn-palette.png. Use style_profile to
inspect the pinned target; use the six reference colors as your working palette.
Create an attractive, deliberate illustration, not a palette swatch or generic card.
The output must be a nonblank, opaque 768x768 PNG at artifacts/{asset_id}.png.
Use local Python/Pillow drawing, or SVG rendered locally if available. Pillow is
installed. Preserve your editable generation source in this workspace. No network,
package installation, external services or files outside this workspace.
{'Build a reusable drawing vocabulary for the next asset if useful.' if index == 0 else 'Inspect the first asset and reuse its visual vocabulary, stroke weight, rounded forms and scale.'}
You may create and stage reusable generated tools if useful; activation is between turns.
Use style_check on the generated PNG. If it reports palette drift, fix your source
or use style_apply to a new path and preserve the original; check again. Do not
modify the reference files, pinned target, harness or experiment driver. A passing
palette check does not establish theme/composition quality. Finish only after the
requested image exists and has been checked, and report limitations honestly.
'''
            (run / f'{asset_id}.prompt.txt').write_text(prompt, encoding='utf-8')
            arguments = cli.parse_args([prompt, '--once', '--extensions', '--style-tools', '--model-usage',
                '--style-profile', 'references/target-profile.json', '--resume', str(runtime.session_dir),
                '--model', options.model, '--max-steps', str(options.max_steps),
                '--context-policy', options.context_policy, '--max-context-bytes', str(options.max_context_bytes),
                '--token-target', str(options.token_target),
                '--usage-report', str(run / 'usage.json'), '-C', str(workspace)])
            print(f'=== {asset_id} ===', flush=True)
            start = time.monotonic()
            exit_code = launch(arguments)
            path = workspace / 'artifacts' / f'{asset_id}.png'
            checked = {'exists': path.is_file(), 'checks_passed': False}
            if path.is_file():
                measured = measure(path)
                with Image.open(path) as image:
                    validity = {'dimensions': image.size == (768, 768),
                                'nonblank': max(ImageStat.Stat(image.convert('RGB')).stddev) > 2,
                                'opaque': image.convert('RGBA').getchannel('A').getextrema() == (255, 255)}
                style = check_measurements(measured, profile)
                checked.update({'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                    'artifact_checks': validity, 'style': style,
                    'checks_passed': all(validity.values()) and style['measured_checks_passed']})
            target_unchanged = ((workspace / 'references/target-profile.json').read_bytes() == encoded(profile)
                                and target.read_bytes() == encoded(profile))
            checked['target_unchanged'] = target_unchanged
            checked['checks_passed'] = checked['checks_passed'] and target_unchanged
            atomic_write_json(run / f'{asset_id}.verification.json', checked)
            usage = usage_report(LocalRuntime(runtime.session_dir))
            atomic_write_json(run / 'usage.json', usage)
            summary['tasks'].append({'id': asset_id, 'subject': subject, 'exit_code': exit_code,
                'duration_seconds': round(time.monotonic()-start, 2), 'verification': checked,
                'usage': usage['tasks'][-1] if usage['tasks'] else None})
            atomic_write_json(run / 'summary.json', summary)
            print(f'Independent measured checks passed: {checked["checks_passed"]}', flush=True)
            if row_stop := ((summary['tasks'][-1].get('usage') or {}).get('stop_reason')):
                if row_stop == 'model_error':
                    summary['status'] = 'model_service_error'
                    break
        else:
            summary['status'] = 'complete' if all(row['exit_code']==0 for row in summary['tasks']) else 'incomplete'
        summary['all_measured_checks_passed'] = len(summary['tasks'])==len(TASKS) and all(row['verification']['checks_passed'] for row in summary['tasks'])
    except Exception as exc:
        summary.update(status='error', error=str(exc))
        traceback.print_exc()
    finally:
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(run / 'summary.json', summary)
        (run / 'preview.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Cozy autumn generation test</title>
<style>body{font:16px system-ui;background:#f4e6ce;color:#483326;margin:32px}section{display:flex;gap:24px;flex-wrap:wrap}img{width:min(42vw,600px);max-width:100%}</style>
<h1>Cozy autumn — two generated assets</h1><p>Shared pinned palette. Automated checks cover palette and file validity; theme and composition require visual review.</p>
<section><article><h2>Reading</h2><img src="workspace/artifacts/01-reading.png"></article><article><h2>Lantern</h2><img src="workspace/artifacts/02-lantern.png"></article></section></html>''', encoding='utf-8')
        print(f'Pilot {summary["status"]}: {run}', flush=True)
    return 0 if summary['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
