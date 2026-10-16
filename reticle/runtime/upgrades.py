"""Content-addressed harness snapshots and durable activation state.

Checksums detect changes; they are not an OS security boundary against trusted code.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from reticle.storage.artifacts import atomic_write_json


PROTECTED_FILES = {
    '_schema.py', 'runtime/contracts.py', 'runtime/session.py', 'runtime/events.py',
    'runtime/budgets.py', 'runtime/ownership.py', 'runtime/workspace.py',
    'runtime/upgrades.py', 'runtime/supervisor.py', 'runtime/live_worker.py',
    'runtime/resume_bootstrap.py',
    'runtime/telemetry.py',
    'runtime/decision_state.py',
    'runtime/extensions.py', 'tools/extensions.py',
    'runtime/style.py', 'tools/style.py',
    'cognitive/chatgpt_auth.py', 'cognitive/chatgpt_subscription.py',
}
PROTECTED_PREFIXES = ('storage/', 'execution/', 'providers/')
SKIP_DIRECTORIES = {'__pycache__', 'node_modules', '.git', '.venv', '.reticle', '.runtime'}


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def package_sources(package):
    if package.is_symlink():
        raise ValueError('Harness snapshots cannot contain symlinks')
    for directory, children, names in os.walk(package):
        children[:] = sorted(name for name in children if name not in SKIP_DIRECTORIES)
        if any((Path(directory) / name).is_symlink() for name in children):
            raise ValueError('Harness snapshots cannot contain symlinks')
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix != '.py':
                continue
            if path.is_symlink():
                raise ValueError('Harness snapshots cannot contain symlinks')
            yield path


class RuntimeBundles:
    def __init__(self, session, initial_source):
        self.root = Path(session).resolve() / 'runtime-updates'
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / 'state.json'
        if self.state_path.is_file():
            self.state = json.loads(self.state_path.read_text(encoding='utf-8'))
            if self.state.get('protocol') != 1:
                raise ValueError('Unsupported runtime activation protocol')
            for field in ('baseline', 'active', 'previous', 'pending'):
                if self.state.get(field):
                    self.path(self.state[field])
            # Pending/active failures are handled by the supervisor's fallback protocol.
            self.verify(self.state['baseline'])
        else:
            initial = self.snapshot(initial_source)
            self.state = {'protocol': 1, 'baseline': initial, 'active': initial,
                          'previous': None, 'pending': None, 'initial_source': str(Path(initial_source).resolve())}
            self.save()
        launcher = self.root / 'resume.py'
        if not launcher.is_file():
            launcher.write_bytes((self.path(self.state['baseline']) / 'reticle/runtime/resume_bootstrap.py').read_bytes())

    def save(self):
        atomic_write_json(self.state_path, self.state)

    def path(self, version):
        if not isinstance(version, str) or len(version) != 64 or any(c not in '0123456789abcdef' for c in version):
            raise ValueError('Invalid runtime version')
        return self.root / version

    def verify(self, version):
        root = self.path(version)
        manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('protocol') != 1 or manifest.get('version') != version:
            raise ValueError('Runtime manifest protocol or version does not match')
        files = manifest['files']
        if _digest(json.dumps(files, sort_keys=True).encode()) != version:
            raise ValueError('Runtime manifest does not match its version')
        actual = {}
        for path in package_sources(root / 'reticle'):
            actual[path.relative_to(root / 'reticle').as_posix()] = _digest(path.read_bytes())
        if actual != files:
            raise ValueError(f'Runtime bundle changed after staging: {version}')
        return files

    def snapshot(self, source_root):
        package = Path(source_root).resolve() / 'reticle'
        if not (package / '__init__.py').is_file():
            raise ValueError('source_root must contain a reticle package')
        contents = {}
        for path in package_sources(package):
            path.resolve().relative_to(package)
            relative = path.relative_to(package).as_posix()
            raw = path.read_bytes()
            compile(raw, relative, 'exec')
            contents[relative] = raw
        files = {name: _digest(raw) for name, raw in contents.items()}
        if hasattr(self, 'state'):
            baseline = self.verify(self.state['baseline'])
            protected = set(PROTECTED_FILES) | {name for name in baseline if name.startswith(PROTECTED_PREFIXES)}
            protected |= {name for name in files if name.startswith(PROTECTED_PREFIXES)}
            changed = sorted(name for name in protected if files.get(name) != baseline.get(name))
            if changed:
                raise ValueError('Protected runtime files changed: ' + ', '.join(changed))
        version = _digest(json.dumps(files, sort_keys=True).encode())
        destination = self.path(version)
        if destination.exists():
            self.verify(version)
            return version
        staging = self.root / ('.staging-' + uuid4().hex)
        try:
            for name, raw in contents.items():
                target = staging / 'reticle' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            atomic_write_json(staging / 'manifest.json', {'protocol': 1, 'version': version, 'files': files})
            staging.rename(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return version

    def queue(self, version, reason=''):
        self.verify(version)
        self.state['pending'] = version
        self.state['pending_reason'] = reason
        self.save()

    def promote(self):
        version = self.state.get('pending')
        if version:
            self.verify(version)
            if version != self.state['active']:
                self.state['previous'] = self.state['active']
            self.state['active'] = version
            self.state['pending'] = None
            self.save()
        return self.state['active']

    def reject_pending(self):
        self.state['pending'] = None
        self.save()
