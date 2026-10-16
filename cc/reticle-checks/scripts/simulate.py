"""Offline driver: feed a crafted hook payload to reticle_checks.py, print what it returns.

No model, no Claude Code. Examples (from a project with .claude/reticle-checks.json):

  python simulate.py edit calc.py                 # PostToolUse for Edit of calc.py
  python simulate.py edit calc.py --mode delta    # override the config's mode for this run
  python simulate.py compact                      # PreCompact (baseline invalidation)

The hook script runs as a subprocess with the JSON on stdin, exactly as Claude Code
would spawn it; --mode works by writing a temporary copy of the config and restoring it.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

HOOK = Path(__file__).with_name('reticle_checks.py')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('event', choices=['edit', 'write', 'compact', 'session-compact'])
    parser.add_argument('path', nargs='?')
    parser.add_argument('--session', default='simulated-session')
    parser.add_argument('--cwd', default=os.getcwd())
    parser.add_argument('--mode', choices=['full', 'selective', 'delta'])
    parser.add_argument('--raw', action='store_true', help='print the raw hook stdout')
    args = parser.parse_args()
    cwd = str(Path(args.cwd).resolve())
    base = {'session_id': args.session, 'cwd': cwd, 'transcript_path': '',
            'permission_mode': 'default'}
    if args.event in ('edit', 'write'):
        if not args.path:
            parser.error('edit/write need a path')
        file_path = str((Path(cwd) / args.path).resolve())
        tool = 'Edit' if args.event == 'edit' else 'Write'
        tool_input = ({'file_path': file_path, 'old_string': '', 'new_string': ''} if tool == 'Edit'
                      else {'file_path': file_path, 'content': ''})
        payload = {**base, 'hook_event_name': 'PostToolUse', 'tool_name': tool,
                   'tool_input': tool_input, 'tool_response': {'filePath': file_path},
                   'tool_use_id': 'toolu_simulated'}
        entry = 'post-tool-use'
    elif args.event == 'compact':
        payload = {**base, 'hook_event_name': 'PreCompact', 'trigger': 'manual',
                   'custom_instructions': None}
        entry = 'invalidate'
    else:
        payload = {**base, 'hook_event_name': 'SessionStart', 'source': 'compact'}
        entry = 'invalidate'

    config_path = Path(cwd) / '.claude' / 'reticle-checks.json'
    original = config_path.read_text(encoding='utf-8') if args.mode and config_path.is_file() else None
    try:
        if original is not None:
            config_path.write_text(json.dumps({**json.loads(original), 'mode': args.mode}, indent=2),
                                   encoding='utf-8')
        done = subprocess.run([sys.executable, str(HOOK), entry], input=json.dumps(payload).encode(),
                              capture_output=True, cwd=cwd)
    finally:
        if original is not None:
            config_path.write_text(original, encoding='utf-8')
    out = done.stdout.decode('utf-8', 'replace')
    if done.stderr:
        sys.stderr.write(done.stderr.decode('utf-8', 'replace'))
    if args.raw or not out.strip():
        print(out if out.strip() else f'(no output; exit {done.returncode})')
        return done.returncode
    value = json.loads(out)
    context = value.get('hookSpecificOutput', {}).get('additionalContext')
    print(context if context is not None else json.dumps(value, indent=2))
    return done.returncode


if __name__ == '__main__':
    sys.exit(main())
