"""Recheck saved furniture without rewriting assets or historical pilot scores."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.blender_bench.run_extension_pilot import BLENDER, TASKS
from reticle.storage.artifacts import atomic_write_json


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    options = parser.parse_args()
    run, output = Path(options.run_dir).resolve(), Path(options.output_dir).resolve()
    if output.exists():
        raise ValueError('Choose a new output directory to preserve previous results')
    output.mkdir(parents=True)
    rows = []
    for task in TASKS:
        asset = run / 'workspace/artifacts' / (task['id'] + '.blend')
        before = checksum(asset)
        spec_path, report_path = output / (task['id'] + '.spec.json'), output / (task['id'] + '.json')
        atomic_write_json(spec_path, task)
        process = subprocess.run([str(BLENDER), '--background', '--disable-autoexec', str(asset),
                                  '--python-exit-code', '1', '--python', str(Path(__file__).with_name('verify_furniture.py')),
                                  '--', str(spec_path), str(report_path)], capture_output=True, timeout=120)
        (output / (task['id'] + '.stdout.txt')).write_bytes(process.stdout)
        (output / (task['id'] + '.stderr.txt')).write_bytes(process.stderr)
        if process.returncode != 0 or not report_path.is_file():
            raise RuntimeError(f'Audit failed for {task["id"]}: {process.stderr.decode(errors="replace")[-1000:]}')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        quality = report['mesh_quality']
        pairs = sorted({tuple(p['objects']) for stage in quality['overlaps'].values() for p in stage['pairs']})
        row = {'id': task['id'], 'asset_sha256': before, 'asset_unchanged': checksum(asset) == before,
               'all_verifier_checks_passed': report['all_passed'], 'mesh_quality_passed': quality['passed'],
               'summary': quality['summary'], 'overlapping_object_pairs': pairs,
               'failed_checks': [name for name, passed in report['checks'].items() if not passed]}
        rows.append(row)
        implementation = ROOT / 'examples/extensions/blender_mesh_audit/mesh_audit.py'
        atomic_write_json(output / 'summary.json', {'audit_version': 1, 'implementation_sha256': checksum(implementation), 'assets': rows})
        print(json.dumps(row), flush=True)
        if not row['asset_unchanged']:
            raise RuntimeError('Read-only audit changed an asset')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
