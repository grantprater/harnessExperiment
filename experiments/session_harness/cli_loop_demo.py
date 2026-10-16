"""One-task self-optimization demonstration; candidate changes stay in an isolated copy.

--prepare snapshots the harness and measures a baseline, with no paid model call.
--execute runs Reticle on that copy, then checks it with the fixed external benchmark.
"""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).with_name('cli_loop_demo_bench.py')
DEFAULT_OUT = ROOT / '.runtime/cli-loop-demo-openai'


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def benchmark(candidate):
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    result = subprocess.run([sys.executable, str(BENCH), str(candidate)],
                            cwd=candidate, env=env, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError('Benchmark failed: ' + result.stderr[-2000:])
    return json.loads(result.stdout)


def prepare(out):
    if out.exists():
        raise SystemExit('Output already exists; choose a new --out directory.')
    candidate = out / 'candidate'
    candidate.mkdir(parents=True)
    tracked = subprocess.check_output(['git', 'ls-files', 'reticle'], cwd=ROOT, text=True).splitlines()
    files = sorted(set(tracked) | {'reticle/interactive.py', 'reticle/providers/__init__.py',
                                  'reticle/providers/api.py', 'reticle/providers/claude_cli.py',
                                  'reticle/cognitive/chatgpt_auth.py',
                                  'reticle/cognitive/chatgpt_subscription.py'})
    for relative in files:
        source = ROOT / relative
        if source.is_file():
            target = candidate / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    shutil.copy2(BENCH, candidate / 'demo_check.py')
    target = candidate / 'reticle/runtime/workspace.py'
    shutil.copy2(target, out / 'workspace.before.py')
    baseline = benchmark(candidate)
    save(out / 'baseline.json', baseline)
    manifest = {relative: hashlib.sha256((candidate / relative).read_bytes()).hexdigest()
                for relative in files if (candidate / relative).is_file()}
    save(out / 'manifest.json', manifest)
    goal = (
        'Optimize this copy of the Reticle harness. Change only reticle/runtime/workspace.py. '
        'WorkspaceTracker.revision currently reads each whole file into memory. Reduce its peak '
        'Python allocations when hashing a 16 MiB file to below 4 MiB and below 25% of baseline. '
        'Preserve the exact sha256 revision format, path ordering, exclusions, and stale-write behavior. '
        'Do not cache hashes or assume files never change. Keep Python 3.9 compatibility. '
        'Run python demo_check.py before and after editing to check correctness and measure peak_bytes. '
        'Use bounded reads when hashing. Do not edit the benchmark, package files, or tests. '
        'Call finish with the before/after peak memory and tests run.'
    )
    (out / 'goal.txt').write_text(goal, encoding='utf-8')
    save(out / 'design.json', {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'task': 'Reduce allocations in WorkspaceTracker.revision through bounded reads',
        'client': 'chatgpt-subscription', 'model': 'gpt-6.1-sol', 'max_responses': 8,
        'metric': 'max tracemalloc peak across three 16 MiB file revision calls',
        'acceptance': 'all fixed correctness checks pass; peak < 4 MiB and < 25% baseline; only workspace.py changed',
        'limitations': 'one optimization task; Python allocations, not total process RSS; timing descriptive only',
        'baseline': baseline})
    print(json.dumps({'out': str(out), 'baseline': baseline}, indent=2))


def execute(out):
    candidate = out / 'candidate'
    if (out / 'result.json').exists():
        raise SystemExit('Experiment already completed.')
    goal = (out / 'goal.txt').read_text(encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING='utf-8')
    argv = [sys.executable, '-u', '-m', 'reticle', goal, '-C', str(candidate),
            '--client', 'chatgpt-subscription', '--model', 'gpt-6.1-sol', '--once', '--max-steps', '8',
            '--session-dir', str(out / 'session')]
    save(out / 'invocation.json', {'argv': argv})
    with (out / 'agent.stdout.txt').open('w', encoding='utf-8') as stdout, \
            (out / 'agent.stderr.txt').open('w', encoding='utf-8') as stderr:
        run = subprocess.run(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr, timeout=900)
    baseline = json.loads((out / 'baseline.json').read_text())
    after = benchmark(candidate)
    save(out / 'after.json', after)
    manifest = json.loads((out / 'manifest.json').read_text())
    changed = [name for name, digest in manifest.items()
               if not (candidate / name).is_file() or hashlib.sha256((candidate / name).read_bytes()).hexdigest() != digest]
    new_files = [p.relative_to(candidate).as_posix() for p in candidate.rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and p.relative_to(candidate).as_posix() not in manifest
                 and p.name != 'demo_check.py']
    bench_unchanged = (candidate / 'demo_check.py').read_bytes() == BENCH.read_bytes()
    before_text = (out / 'workspace.before.py').read_text(encoding='utf-8').splitlines(keepends=True)
    after_text = (candidate / 'reticle/runtime/workspace.py').read_text(encoding='utf-8').splitlines(keepends=True)
    (out / 'candidate.patch').write_text(''.join(difflib.unified_diff(
        before_text, after_text, fromfile='before/workspace.py', tofile='after/workspace.py')), encoding='utf-8')
    accepted = (run.returncode == 0 and after['correctness_passed'] and bench_unchanged and not new_files
                and changed == ['reticle/runtime/workspace.py']
                and after['peak_bytes'] < 4 * 1048576 and after['peak_bytes'] < baseline['peak_bytes'] * .25)
    result = {'accepted': accepted, 'agent_exit_code': run.returncode,
              'baseline': baseline, 'after': after, 'changed_files': changed, 'new_files': new_files,
              'benchmark_unchanged': bench_unchanged, 'production_code_updated': False,
              'memory_reduction_percent': 100 * (1 - after['peak_bytes'] / baseline['peak_bytes'])}
    save(out / 'result.json', result)
    (out / 'report.md').write_text(
        '# Reticle CLI loop demonstration\n\n'
        f'Accepted: {accepted}. Agent exit: {run.returncode}.\n\n'
        f"Peak Python allocation: {baseline['peak_bytes']:,} -> {after['peak_bytes']:,} bytes "
        f"({result['memory_reduction_percent']:.1f}% reduction).\n\n"
        f"Correctness: {after['checks']} checks, passed={after['correctness_passed']}.\n\n"
        'Candidate changes remain in the isolated copy. The production checkout was not updated.\n'
        'One task demonstrates the edit/measure loop; it does not establish general optimization ability.\n',
        encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    try:
        (prepare if args.prepare else execute)(args.out.resolve())
    except Exception as exc:
        if args.execute and args.out.is_dir():
            save(args.out / 'failure.json', {'error': str(exc), 'type': type(exc).__name__})
        raise
