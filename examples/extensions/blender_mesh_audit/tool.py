"""Blender audit adapter with a real, temporary-workspace smoke fixture."""
import json
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4


def blender_path():
    executable = shutil.which('blender')
    installed = Path(r'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe')
    if executable:
        return executable
    if installed.is_file():
        return str(installed)
    raise FileNotFoundError('Blender is unavailable in the configured execution environment')


def execute(arguments, context):
    workspace = Path(context['workspace']).resolve()
    script = Path(__file__).with_name('mesh_audit.py')
    executable = blender_path()
    if context['validation']:
        code = ("import importlib.util; "
                f"s=importlib.util.spec_from_file_location('audit',{str(script)!r}); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                "r=m.audit_scene(); assert r['passed'],r; print('RETICLE_AUDIT_SMOKE_OK')")
        process = subprocess.run([executable, '--background', '--factory-startup', '--disable-autoexec',
                                  '--python-exit-code', '1', '--python-expr', code],
                                 capture_output=True, timeout=60, cwd=workspace)
        if process.returncode or b'RETICLE_AUDIT_SMOKE_OK' not in process.stdout:
            raise RuntimeError('Blender mesh-audit smoke check failed: ' + process.stderr.decode(errors='replace')[-2000:])
        return {'validation': 'passed', 'fixture': 'closed cube'}
    asset = (workspace / arguments['blend_file']).resolve()
    asset.relative_to(workspace)
    if asset.suffix.lower() != '.blend' or not asset.is_file():
        raise ValueError('blend_file must be an existing .blend file within the workspace')
    report_path = workspace / '.reticle/mesh-audit' / (uuid4().hex + '.json')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    options = {'require_closed': arguments.get('require_closed', True)}
    if 'objects' in arguments:
        options['object_names'] = arguments['objects']
    process = subprocess.run([executable, '--background', '--disable-autoexec', str(asset),
                              '--python-exit-code', '1', '--python', str(script),
                              '--', str(report_path), json.dumps(options)],
                             capture_output=True, timeout=100, cwd=workspace)
    if process.returncode or not report_path.is_file():
        raise RuntimeError('Blender mesh audit failed: ' + process.stderr.decode(errors='replace')[-2000:])
    report = json.loads(report_path.read_text(encoding='utf-8'))
    return {'complete': report['complete'], 'passed': report['passed'], 'summary': report['summary'],
            'report_path': report_path.relative_to(workspace).as_posix(),
            'object_findings': [{'object': row['object'],
                                 'source_errors': row['source']['errors'],
                                 'evaluated_errors': row['evaluated']['errors'],
                                 'source_examples': row['source']['examples'],
                                 'evaluated_examples': row['evaluated']['examples'],
                                 'modifier_warnings': row['modifier_warnings']}
                                for row in report['objects']
                                if row['source']['errors'] or row['evaluated']['errors'] or row['modifier_warnings']],
            'overlaps': {stage: {**data, 'pairs': data['pairs'][:20]}
                         for stage, data in report['overlaps'].items()}}
