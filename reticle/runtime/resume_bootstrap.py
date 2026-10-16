"""Standalone session launcher: load the saved supervisor even if the editable checkout is broken.

Copied to SESSION/runtime-updates/resume.py. Uses only stdlib before verifying the
baseline bundle and adding it to the import path.
"""
import hashlib
import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parent
    state = json.loads((root / 'state.json').read_text(encoding='utf-8'))
    version = state['baseline']
    if len(version) != 64 or any(c not in '0123456789abcdef' for c in version):
        raise ValueError('Invalid baseline runtime version')
    bundle = root / version
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    files = manifest['files']
    if manifest.get('protocol') != 1 or hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest() != version:
        raise ValueError('Baseline runtime manifest is invalid')
    actual = {}
    package = bundle / 'reticle'
    if package.is_symlink():
        raise ValueError('Baseline runtime cannot be a symlink')
    for path in package.rglob('*'):
        if path.is_symlink():
            raise ValueError('Baseline runtime cannot contain symlinks')
        if path.is_file() and path.suffix == '.py':
            actual[path.relative_to(package).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != files:
        raise ValueError('Baseline runtime changed; cannot start the saved supervisor')
    sys.path.insert(0, str(bundle))
    from reticle import interactive
    from reticle.cli import main as cli_main
    if state.get('initial_source'):
        # Preserve private .env lookup locations; the file itself is never bundled.
        interactive.ROOT = Path(state['initial_source'])
    options = sys.argv[1:]
    if '--resume' not in options:
        options.extend(['--resume', str(root.parent)])
    if '--runtime-updates' not in options:
        options.append('--runtime-updates')
    cli_main(['chat', *options])


if __name__ == '__main__':
    main()
