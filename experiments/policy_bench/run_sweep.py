"""Explicitly invoked policy trials. Real drivers can spend model tokens.

Config specifies driver, fixed_arguments, repetitions, seed, and variants. Each
driver must accept --run-dir and emit summary.json and usage.json, including failures.
Optional independent evaluation.json: {"accepted":bool,"source":str,"protocol_id":str}.
"""
import argparse
import json
from pathlib import Path
import random
import subprocess
import sys
import html
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reticle.storage.artifacts import atomic_write_json
from experiments.policy_bench.compare_runs import compare_runs


def write_gallery(root, jobs):
    cards = []
    for index, job in enumerate(jobs):
        run = Path(job['run_dir'])
        directory = run/'workspace/artifacts'
        images = sorted(directory.glob('*.png')) if directory.exists() else []
        # Labels omit policy names so visual review can precede inspecting usage.
        pictures = ''.join(f'<figure><img src="{html.escape(image.relative_to(root).as_posix(), quote=True)}"><figcaption>{html.escape(image.name)}</figcaption></figure>' for image in images)
        cards.append(f'<section><h2>Attempt {index+1}: {html.escape(run.name)}</h2><div>{pictures or "No PNG artifacts"}</div></section>')
    (root/'gallery.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Policy comparison assets</title>'
        '<style>body{font:16px system-ui;background:#faf7ef;color:#483326;margin:32px}section{margin-bottom:40px}section div{display:flex;flex-wrap:wrap;gap:16px}figure{margin:0}img{width:360px;max-width:90vw}figcaption{font-size:13px}</style>'
        '<h1>Policy comparison: visual review</h1><p>Review subject completion, cozy autumn character and pair consistency. Composition can vary. Policy labels and token measurements are in comparison.json.</p>'
        + ''.join(cards) + '</html>', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    options = parser.parse_args()
    config = json.loads(options.config.read_text(encoding='utf-8'))
    if options.output_dir.exists():
        raise ValueError('Use a fresh sweep directory')
    repetitions = config.get('repetitions', 3)
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError('repetitions must be positive')
    variants = config['variants']
    if not variants or len({v['name'] for v in variants}) != len(variants):
        raise ValueError('Supply distinct named variants')
    driver = Path(config['driver']).resolve()
    jobs = [(index, repetition, variant) for repetition in range(repetitions) for index, variant in enumerate(variants)]
    random.Random(config.get('seed', 0)).shuffle(jobs)
    root = options.output_dir.resolve()
    root.mkdir(parents=True)
    atomic_write_json(root/'config.json', config)
    if config.get('review_protocol'):
        atomic_write_json(root/'review-protocol.json',config['review_protocol'])
    progress = {'started_at':datetime.now(timezone.utc).isoformat(), 'status':'running', 'jobs':[]}
    atomic_write_json(root/'progress.json', progress)
    paths = []
    for index, repetition, variant in jobs:
        # Names are labels, never path components.
        run = root/f'variant-{index:02d}-trial-{repetition:02d}'
        arguments = [sys.executable, '-u', str(driver), *config.get('fixed_arguments',[]),
                     *variant.get('arguments',[]), '--run-dir', str(run)]
        print(f'Trial {variant["name"]}, repetition {repetition+1}', flush=True)
        with (root/f'{run.name}.stdout.txt').open('wb') as stdout, (root/f'{run.name}.stderr.txt').open('wb') as stderr:
            result = subprocess.run(arguments, stdout=stdout, stderr=stderr)
        row = {'variant':variant['name'], 'repetition':repetition, 'run_dir':str(run), 'exit_code':result.returncode}
        if not (run/'summary.json').exists():
            run.mkdir(exist_ok=True)
            atomic_write_json(run/'summary.json', {'status':'driver_error','context_policy':variant['name']})
        atomic_write_json(run/'trial.json', row)
        paths.append(run)
        progress['jobs'].append(row)
        atomic_write_json(root/'progress.json', progress)
        atomic_write_json(root/'comparison.json', compare_runs(paths))
        write_gallery(root, progress['jobs'])
    progress.update(status='complete', finished_at=datetime.now(timezone.utc).isoformat())
    atomic_write_json(root/'progress.json', progress)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
