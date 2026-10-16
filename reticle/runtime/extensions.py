"""Versioned, opt-in Python extensions executed through the configured backend.

Bundles and schemas are data in the controller. Generated code only runs in child
processes. Trusted-local remains trusted code, not a security sandbox.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
from uuid import uuid4

from reticle.execution import ExecutionRequest
from reticle.runtime.ownership import SessionWriterLock
from reticle.storage.artifacts import atomic_write_json


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def is_number(value):
    return (isinstance(value, int) and not isinstance(value, bool)
            or isinstance(value, float) and math.isfinite(value))


def check_schema(schema, depth=0):
    """Deliberately small JSON Schema subset; reject unsupported constraints."""
    if depth > 20 or not isinstance(schema, dict):
        raise ValueError('Invalid or excessively nested parameter schema')
    allowed = {'type', 'description', 'enum', 'properties', 'required', 'additionalProperties',
               'items', 'minimum', 'maximum', 'minItems', 'maxItems', 'minLength', 'maxLength'}
    if set(schema) - allowed:
        raise ValueError('Unsupported schema keywords: ' + ', '.join(sorted(set(schema) - allowed)))
    kind = schema.get('type')
    if not isinstance(kind, str) or kind not in {'object', 'array', 'string', 'integer', 'number', 'boolean', 'null'}:
        raise ValueError('Every schema node requires a supported type')
    relevant = {'object': {'properties', 'required', 'additionalProperties'}, 'array': {'items', 'minItems', 'maxItems'},
                'string': {'minLength', 'maxLength'}, 'integer': {'minimum', 'maximum'},
                'number': {'minimum', 'maximum'}}.get(kind, set())
    if set(schema) - relevant - {'type', 'description', 'enum'}:
        raise ValueError('Schema constraint does not apply to its type')
    if 'description' in schema and not isinstance(schema['description'], str):
        raise ValueError('Schema description must be a string')
    if 'enum' in schema and (not isinstance(schema['enum'], list) or not schema['enum']):
        raise ValueError('enum must be a nonempty list')
    if kind == 'object':
        properties = schema.get('properties', {})
        required = schema.get('required', [])
        if not isinstance(properties, dict) or not isinstance(required, list) or any(
                not isinstance(name, str) or name not in properties for name in required):
            raise ValueError('Invalid properties or required fields')
        if schema.get('additionalProperties', False) is not False:
            raise ValueError('Extension objects require additionalProperties=false')
        schema['additionalProperties'] = False
        for value in properties.values():
            check_schema(value, depth + 1)
    if kind == 'array':
        check_schema(schema.get('items'), depth + 1)
    for key in ('minimum', 'maximum', 'minItems', 'maxItems', 'minLength', 'maxLength'):
        if key in schema:
            value = schema[key]
            if not is_number(value):
                raise ValueError('Invalid numeric schema constraint')
            if key not in ('minimum', 'maximum') and (not isinstance(value, int) or value < 0):
                raise ValueError('Length constraints must be nonnegative integers')
    for lower, upper in (('minimum', 'maximum'), ('minItems', 'maxItems'), ('minLength', 'maxLength')):
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            raise ValueError('Schema minimum exceeds maximum')


def check_arguments(value, schema, path='$'):
    kind = schema['type']
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'boolean': isinstance(value, bool), 'null': value is None,
             'integer': isinstance(value, int) and not isinstance(value, bool),
             'number': is_number(value)}[kind]
    if not valid:
        raise ValueError(f'{path} must be {kind}')
    if 'enum' in schema and canonical(value) not in [canonical(v) for v in schema['enum']]:
        raise ValueError(f'{path} is outside enum')
    if kind == 'object':
        properties = schema.get('properties', {})
        if set(value) - set(properties) or set(schema.get('required', [])) - set(value):
            raise ValueError(f'{path} has unknown or missing required fields')
        for key, item in value.items():
            check_arguments(item, properties[key], f'{path}.{key}')
    if kind == 'array':
        for index, item in enumerate(value):
            check_arguments(item, schema['items'], f'{path}[{index}]')
    measured = len(value) if kind in ('string', 'array') else value
    keys = ('minLength', 'maxLength') if kind == 'string' else ('minItems', 'maxItems') if kind == 'array' else ('minimum', 'maximum')
    if kind in ('string', 'array', 'integer', 'number'):
        if ((keys[0] in schema and measured < schema[keys[0]])
                or (keys[1] in schema and measured > schema[keys[1]])):
            raise ValueError(f'{path} violates bounds')


# No reticle import in the child; works with local and OCI Python interpreters.
RUNNER = r'''
import hashlib, importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
files = json.loads(sys.argv[2])
for name, expected in files.items():
    path = root / name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Extension bundle integrity check failed: ' + name)
manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
filename, function = manifest['entrypoint'].split(':')
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location('reticle_generated_extension', root / filename)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
execute = getattr(module, function)
if not callable(execute):
    raise ValueError('Extension entrypoint must be callable')
mode = sys.argv[3]
if mode == 'validate':
    for case in manifest['smoke_tests']:
        result = execute(case['arguments'], {'workspace': str(pathlib.Path.cwd()), 'validation': True})
        json.dumps(result, allow_nan=False)
        if 'expected' in case and json.dumps(result, sort_keys=True, allow_nan=False) != json.dumps(case['expected'], sort_keys=True, allow_nan=False):
            raise ValueError('Extension smoke test result did not match expected')
    result = {'validated': True}
else:
    result = execute(json.loads(sys.argv[4]), {'workspace': str(pathlib.Path.cwd()), 'validation': False})
print('\nRETICLE_EXTENSION_RESULT=' + json.dumps(result, allow_nan=False))
'''


class ExtensionRegistry:
    def __init__(self, runtime, backend, interpreter, library=None):
        self.runtime, self.backend, self.interpreter = runtime, backend, interpreter
        selected = Path(library) if library else Path('.reticle/extensions')
        self.root = (runtime.workspace.root / selected).resolve()
        self.root.relative_to(runtime.workspace.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / 'state.json'
        self.frozen = {}
        self.task_id = None

    def state(self):
        value = json.loads(self.state_path.read_text(encoding='utf-8')) if self.state_path.exists() else {'protocol': 1, 'tools': {}}
        if not isinstance(value, dict) or value.get('protocol') != 1 or not isinstance(value.get('tools'), dict):
            raise ValueError('Unsupported extension registry state')
        for name, entry in value['tools'].items():
            if not isinstance(name, str) or not re.fullmatch(r'ext_[a-z][a-z0-9_]{0,55}', name) or not isinstance(entry, dict):
                raise ValueError('Invalid extension registry entry')
            for key in ('active', 'previous', 'pending'):
                if entry.get(key) is not None:
                    self.bundle(entry[key])
        return value

    def bundle(self, version):
        if not isinstance(version, str) or not re.fullmatch('[a-f0-9]{64}', version):
            raise ValueError('Invalid extension version')
        return self.root / 'bundles' / version

    def verify(self, version):
        root = self.bundle(version)
        metadata = json.loads((root / 'bundle.json').read_text(encoding='utf-8'))
        files = metadata['files']
        if digest(canonical(files)) != version:
            raise ValueError('Extension manifest hash mismatch')
        for name, expected in files.items():
            path = root / name
            if Path(name).is_absolute() or '..' in Path(name).parts or path.resolve().is_relative_to(root) is False:
                raise ValueError('Invalid extension file path')
            if path.is_symlink() or digest(path.read_bytes()) != expected:
                raise ValueError('Extension changed after staging')
        actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
        if actual != set(files) | {'bundle.json'}:
            raise ValueError('Unexpected files in extension bundle')
        manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        self.validate_manifest(manifest)
        return manifest, files

    @staticmethod
    def validate_manifest(manifest):
        if not isinstance(manifest, dict) or set(manifest) - {'name', 'description', 'parameters', 'entrypoint', 'smoke_tests', 'timeout_seconds'}:
            raise ValueError('Unknown extension manifest fields')
        if not isinstance(manifest.get('name'), str) or not re.fullmatch(r'ext_[a-z][a-z0-9_]{0,55}', manifest['name']):
            raise ValueError('Extension names must start with ext_ and use lowercase letters, digits, underscores')
        if not isinstance(manifest.get('description'), str) or not manifest['description'].strip():
            raise ValueError('Extension description is required')
        check_schema(manifest.get('parameters'))
        if manifest['parameters']['type'] != 'object':
            raise ValueError('Tool parameters must be an object')
        entry = manifest.get('entrypoint', '')
        if not isinstance(entry, str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*\.py:[a-zA-Z_][a-zA-Z0-9_]*', entry):
            raise ValueError('entrypoint must be a top-level Python file:function')
        timeout = manifest.get('timeout_seconds', 30)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 600:
            raise ValueError('timeout_seconds must be between 0 and 600')
        cases = manifest.get('smoke_tests')
        if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
            raise ValueError('Supply 1 to 20 smoke_tests')
        for case in cases:
            if not isinstance(case, dict) or set(case) - {'arguments', 'expected'} or 'arguments' not in case:
                raise ValueError('Each smoke test needs arguments and optional expected')
            check_arguments(case['arguments'], manifest['parameters'])
        canonical(manifest)

    def request(self, version, mode, arguments=None, *, root=None, workspace=None):
        manifest, files = self.verify(version)
        workspace = workspace or self.runtime.workspace.root
        root = root or self.bundle(version)
        return ExecutionRequest(
            command=[self.interpreter, '-B', '-c', RUNNER, root.relative_to(workspace).as_posix(),
                     canonical(files).decode(), mode, json.dumps(arguments)],
            working_directory=workspace, workspace_root=workspace,
            timeout_seconds=manifest.get('timeout_seconds', 30), output_limit_bytes=2_000_000,
            environment={'PYTHONIOENCODING': 'utf-8'}, mutates_workspace=mode != 'validate',
            writable_mount=True)

    def validate(self, version):
        self.verify(version)
        with tempfile.TemporaryDirectory(prefix='reticle-extension-') as directory:
            workspace = Path(directory).resolve()
            copy = workspace / 'bundle'
            shutil.copytree(self.bundle(version), copy)
            execution = self.backend.run(self.request(version, 'validate', root=copy, workspace=workspace))
        if execution.status != 'success':
            details = execution.stderr.decode('utf-8', errors='replace')[-2000:]
            raise ValueError(f'Extension validation {execution.status}: {details or execution.diagnostic}')
        if not execution.stdout.rstrip().endswith(b'RETICLE_EXTENSION_RESULT={"validated": true}'):
            raise ValueError('Extension validation returned no completion marker')

    def stage(self, source):
        source = Path(source).resolve()
        source.relative_to(self.runtime.workspace.root)
        if source == self.root or source.is_relative_to(self.root) or self.root.is_relative_to(source):
            raise ValueError('Extension source and library must be separate directories')
        if not source.is_dir():
            raise ValueError('Extension source must be a directory')
        contents = {}
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise ValueError('Extension bundles cannot contain symlinks')
            if path.is_file():
                if '__pycache__' in path.parts:
                    continue
                name = path.relative_to(source).as_posix()
                if name == 'bundle.json':
                    raise ValueError('bundle.json is reserved')
                contents[name] = path.read_bytes()
                if len(contents) > 100 or sum(map(len, contents.values())) > 10_000_000:
                    raise ValueError('Extension bundle exceeds 100 files or 10 MB')
                if path.suffix == '.py':
                    try:
                        compile(contents[name], name, 'exec')
                    except SyntaxError as exc:
                        raise ValueError(f'Extension syntax error in {name}: {exc}') from exc
        manifest = json.loads(contents.get('manifest.json', b'{}').decode('utf-8'))
        self.validate_manifest(manifest)
        if manifest['entrypoint'].split(':')[0] not in contents:
            raise ValueError('Extension entrypoint file is missing')
        # Store the normalized schema as part of the versioned bundle.
        contents['manifest.json'] = canonical(manifest)
        files = {name: digest(data) for name, data in contents.items()}
        version = digest(canonical(files))
        with SessionWriterLock(self.root).acquire('extension-stage-' + uuid4().hex):
            destination = self.bundle(version)
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.parent / ('.staging-' + uuid4().hex)
                try:
                    for name, data in contents.items():
                        path = temporary / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                    atomic_write_json(temporary / 'bundle.json', {'files': files})
                    temporary.rename(destination)
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
            self.validate(version)
            state = self.state()
            entry = state['tools'].setdefault(manifest['name'], {'active': None, 'previous': None, 'pending': None})
            entry['pending'] = version
            atomic_write_json(self.state_path, state)
        self.runtime.journal.append('extension_staged', {'name': manifest['name'], 'version': version, 'task_id': self.task_id})
        return {'name': manifest['name'], 'version': version, 'status': 'queued', 'activation': 'next user turn'}

    def begin_turn(self, task_id):
        self.task_id = task_id
        frozen = {}
        from reticle.context import TranscriptStore
        messages = TranscriptStore(self.runtime).load()
        completed = {m.get('tool_call_id') for m in messages if m.get('role') == 'tool'}
        unfinished = any(call.get('id') not in completed for m in messages
                         if m.get('role') == 'assistant' for call in m.get('tool_calls', []))
        recovering = unfinished or bool(self.runtime.recovery.pending_operations)
        snapshots = [e.payload for e in self.runtime.journal.read_all() if e.kind == 'extension_turn_snapshot']
        recovery_versions = snapshots[-1]['versions'] if snapshots else {}
        with SessionWriterLock(self.root).acquire('extension-activate-' + uuid4().hex):
            state = self.state()
            deferred = recovering
            for name, entry in sorted(state['tools'].items()):
                pending = entry.get('pending')
                if pending and not deferred:
                    try:
                        self.validate(pending)
                        if self.verify(pending)[0]['name'] != name:
                            raise ValueError('Extension name changed')
                        if pending != entry.get('active'):
                            entry['previous'], entry['active'] = entry.get('active'), pending
                        self.runtime.journal.append('extension_activated', {'name': name, 'version': pending, 'task_id': task_id})
                    except (ValueError, OSError, KeyError, TypeError) as exc:
                        self.runtime.journal.append('extension_rejected', {'name': name, 'version': pending, 'error': str(exc)})
                    entry['pending'] = None
                active = recovery_versions.get(name) if recovering else entry.get('active')
                if not active:
                    continue
                try:
                    self.validate(active)
                    manifest, _ = self.verify(active)
                    if manifest['name'] != name:
                        raise ValueError('Extension name mismatch')
                except (ValueError, OSError, KeyError, TypeError):
                    if recovering:
                        # Never replay an old action against a different implementation.
                        self.runtime.journal.append('extension_recovery_unavailable', {'name': name, 'version': active})
                        continue
                    previous = entry.get('previous')
                    entry['active'] = None
                    if previous:
                        try:
                            self.validate(previous)
                            manifest, _ = self.verify(previous)
                            if manifest['name'] != name:
                                raise ValueError('Extension name mismatch')
                            entry['active'] = previous
                        except (ValueError, OSError, KeyError, TypeError):
                            pass
                    self.runtime.journal.append('extension_rolled_back', {'name': name, 'version': entry['active'], 'failed_version': active})
                    active = entry['active']
                    if not active:
                        continue
                frozen[name] = {'version': active, 'manifest': manifest}
            atomic_write_json(self.state_path, state)
        self.frozen = frozen
        self.runtime.journal.append('extension_turn_snapshot', {'task_id': task_id, 'versions': self.versions()})

    def versions(self):
        return {name: entry['version'] for name, entry in self.frozen.items()}

    def schemas(self):
        return [{'type': 'function', 'function': {'name': name,
                'description': entry['manifest']['description'], 'parameters': entry['manifest']['parameters']}}
                for name, entry in sorted(self.frozen.items())]

    def list(self):
        return {'available_this_turn': self.versions(), 'registry': self.state()['tools']}

    def rollback(self, name):
        with SessionWriterLock(self.root).acquire('extension-rollback-' + uuid4().hex):
            state = self.state()
            entry = state['tools'].get(name)
            if not entry or not entry.get('previous'):
                raise ValueError('No previous extension version to restore')
            self.validate(entry['previous'])
            entry['pending'] = entry['previous']
            atomic_write_json(self.state_path, state)
        self.runtime.journal.append('extension_rollback_queued', {'name': name, 'version': entry['previous'], 'task_id': self.task_id})
        return {'name': name, 'version': entry['previous'], 'status': 'queued', 'activation': 'next user turn'}
