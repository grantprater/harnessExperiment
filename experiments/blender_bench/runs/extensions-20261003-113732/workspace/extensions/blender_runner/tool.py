import subprocess
from pathlib import Path

BLENDER = 'C:/Program Files/Blender Foundation/Blender 5.0/blender.exe'


def execute(arguments, context):
    workspace = Path(context['workspace']).resolve()
    script = (workspace / arguments['script']).resolve()
    if not script.is_relative_to(workspace):
        raise ValueError('Script must be inside the workspace')
    command = [BLENDER, '--background', '--factory-startup', '--python-exit-code', '1', '--python', str(script)]
    if arguments.get('args'):
        command.extend(['--', *arguments['args']])
    if context.get('validation') or arguments.get('dry_run', False):
        return {'flags': command[1:6], 'script': script.relative_to(workspace).as_posix(), 'args': arguments.get('args', [])}
    if not script.is_file():
        raise FileNotFoundError(str(script))
    result = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=arguments.get('timeout_seconds', 240))
    return {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
