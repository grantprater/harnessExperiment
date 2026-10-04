"""Reticle-style post-edit checks as Claude Code command hooks.

Stdlib only, Python 3.10+. Two entry points (first argv element):

  post-tool-use   PostToolUse hook for Edit|Write|MultiEdit. Runs the project's
                  fixed check after a source-changing edit and returns the rendered
                  observation as hookSpecificOutput.additionalContext.
  invalidate      PreCompact / SessionStart(compact) hook. Marks the session's
                  delta baseline as no longer in the model's context.

A project opts in with .claude/reticle-checks.json; without it every entry point
exits 0 with no output. This runs the project's own command as trusted code; it is
not isolation against hostile programs.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

VERSION = 'reticle-checks-v1'
CONFIG_REL = Path('.claude') / 'reticle-checks.json'
STATE_REL = Path('.claude') / 'reticle-checks'
MODES = ('full', 'selective', 'delta')
EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
PRUNE_DIRS = {'.git', '.hg', '.svn', '.claude', '__pycache__', 'node_modules', '.venv',
              'venv', '.tox', '.nox', '.mypy_cache', '.pytest_cache', '.ruff_cache'}
DEFAULTS = {'timeout_s': 60, 'mode': 'selective', 'full_cap_bytes': 8000,
            'max_visible_chars': 9000, 'priority': 'below_normal', 'env': {},
            'max_changed_fraction': 0.25}
# Reticle's traceback rule: keep whole when <= 14 lines, else first 4 + last 9.
TRACE_KEEP_WHOLE, TRACE_HEAD, TRACE_TAIL = 14, 4, 9
FAILING = ('failed', 'error', 'unexpected_success', 'xpass')
SKIPPED = ('skipped', 'xfail')


# ---------------------------------------------------------------- config / paths

class ConfigError(ValueError):
    pass


def find_project_root(cwd, env_project_dir=None):
    """Nearest directory (cwd upward, then CLAUDE_PROJECT_DIR) holding the config."""
    candidates = []
    if cwd:
        here = Path(cwd)
        candidates += [here, *here.parents]
    if env_project_dir:
        candidates.append(Path(env_project_dir))
    for candidate in candidates:
        if (candidate / CONFIG_REL).is_file():
            return candidate
    return None


def load_config(root):
    try:
        raw = json.loads((Path(root) / CONFIG_REL).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ConfigError(f'cannot read {CONFIG_REL.as_posix()}: {exc}') from exc
    if not isinstance(raw, dict):
        raise ConfigError('config must be a JSON object')
    config = {**DEFAULTS, **raw}
    command = config.get('command')
    if (not isinstance(command, list) or not command
            or not all(isinstance(part, str) and part for part in command)):
        raise ConfigError('"command" must be a non-empty list of strings (an argv)')
    globs = config.get('source_globs')
    if not isinstance(globs, list) or not globs or not all(isinstance(g, str) and g for g in globs):
        raise ConfigError('"source_globs" must be a non-empty list of glob strings')
    excludes = config.setdefault('exclude_globs', [])
    if not isinstance(excludes, list) or not all(isinstance(g, str) for g in excludes):
        raise ConfigError('"exclude_globs" must be a list of glob strings')
    if config['mode'] not in MODES:
        raise ConfigError(f'"mode" must be one of {", ".join(MODES)}')
    for key in ('timeout_s', 'full_cap_bytes', 'max_visible_chars'):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError(f'"{key}" must be a positive number')
    fraction = config['max_changed_fraction']
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 <= fraction <= 1:
        raise ConfigError('"max_changed_fraction" must be between 0 and 1')
    if config['priority'] not in ('normal', 'below_normal', 'idle'):
        raise ConfigError('"priority" must be normal, below_normal or idle')
    if not isinstance(config['env'], dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in config['env'].items()):
        raise ConfigError('"env" must map strings to strings')
    return config


def glob_to_regex(pattern):
    """Translate a slash glob (`*`, `?`, `**`, `[...]`) to a compiled regex."""
    i, out = 0, []
    while i < len(pattern):
        if pattern.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
        elif pattern.startswith('**', i):
            out.append('.*')
            i += 2
        elif pattern[i] == '*':
            out.append('[^/]*')
            i += 1
        elif pattern[i] == '?':
            out.append('[^/]')
            i += 1
        elif pattern[i] == '[':
            end = pattern.find(']', i + 1)
            if end == -1:
                out.append(re.escape('['))
                i += 1
            else:
                body = pattern[i + 1:end].replace('\\', '\\\\')
                if body.startswith('!'):
                    body = '^' + body[1:]
                out.append(f'[{body}]')
                i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    flags = re.IGNORECASE if os.name == 'nt' else 0
    return re.compile('(?:' + ''.join(out) + r')\Z', flags)


def _matches(rel, includes, excludes):
    return any(r.match(rel) for r in includes) and not any(r.match(rel) for r in excludes)


def source_files(root, config):
    """Sorted posix relative paths of files the source globs select."""
    includes = [glob_to_regex(g) for g in config['source_globs']]
    excludes = [glob_to_regex(g) for g in config.get('exclude_globs', [])]
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE_DIRS)
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, '/')
            if _matches(rel, includes, excludes):
                found.append(rel)
    return sorted(found)


def relative_source_path(root, file_path, config):
    """The edited file's posix path relative to root when it is a source, else None."""
    if not file_path:
        return None
    try:
        path = Path(file_path)
        if not path.is_absolute():
            path = Path(root) / path
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    except ValueError:  # different drive on Windows
        return None
    rel = rel.replace(os.sep, '/')
    if rel == '..' or rel.startswith('../'):
        return None
    if any(part in PRUNE_DIRS for part in rel.split('/')[:-1]):
        return None
    includes = [glob_to_regex(g) for g in config['source_globs']]
    excludes = [glob_to_regex(g) for g in config.get('exclude_globs', [])]
    return rel if _matches(rel, includes, excludes) else None


def source_fingerprint(root, config):
    values = {}
    for rel in source_files(root, config):
        try:
            values[rel] = hashlib.sha256((Path(root) / rel).read_bytes()).hexdigest()
        except OSError:
            values[rel] = None
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def session_dir(root, session_id):
    safe = re.sub(r'[^A-Za-z0-9_.-]', '_', str(session_id or ''))[:128].strip('.') or 'unknown-session'
    return Path(root) / STATE_REL / safe


# ---------------------------------------------------------------- state / journal

def load_state(sdir):
    try:
        value = json.loads((sdir / 'state.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(sdir, state):
    sdir.mkdir(parents=True, exist_ok=True)
    tmp = sdir / 'state.json.tmp'
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding='utf-8')
    os.replace(tmp, sdir / 'state.json')


def journal(sdir, row):
    sdir.mkdir(parents=True, exist_ok=True)
    with open(sdir / 'events.jsonl', 'a', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(row, sort_keys=True) + '\n')


def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='milliseconds')


class SessionLock:
    """Directory lock: PostToolUse fires concurrently for parallel tool calls."""

    def __init__(self, sdir, wait_s, stale_s):
        self.path, self.wait_s, self.stale_s = sdir / 'lock', wait_s, stale_s
        self.held = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                os.mkdir(self.path)
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale_s:
                        os.rmdir(self.path)
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    return self
                time.sleep(0.1)

    def __exit__(self, *exc):
        if self.held:
            try:
                os.rmdir(self.path)
            except OSError:
                pass


# ---------------------------------------------------------------- running

def _kill_tree(process):
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                           capture_output=True, timeout=10)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.kill()
    except OSError:
        pass


def run_command(root, config):
    """Run the configured argv; returns {rc, output, timed_out, launch_error, duration_s}."""
    argv = [sys.executable if part == '{python}' else part for part in config['command']]
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', **config['env']}
    kwargs = {}
    if os.name == 'nt':
        flags = 0x08000000  # CREATE_NO_WINDOW
        flags |= {'normal': 0, 'below_normal': 0x4000, 'idle': 0x40}[config['priority']]
        kwargs['creationflags'] = flags
    else:
        kwargs['start_new_session'] = True
        increment = {'normal': 0, 'below_normal': 10, 'idle': 19}[config['priority']]
        if increment:
            kwargs['preexec_fn'] = lambda: os.nice(increment)
    started = time.monotonic()
    try:
        process = subprocess.Popen(argv, cwd=str(root), env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    except OSError as exc:
        return {'rc': None, 'output': '', 'timed_out': False,
                'launch_error': f'{type(exc).__name__}: {exc}',
                'duration_s': round(time.monotonic() - started, 4)}
    try:
        data, _ = process.communicate(timeout=config['timeout_s'])
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        try:
            data, _ = process.communicate(timeout=10)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            data = b''
        timed_out = True
    return {'rc': process.returncode, 'output': (data or b'').decode('utf-8', 'replace'),
            'timed_out': timed_out, 'launch_error': None,
            'duration_s': round(time.monotonic() - started, 4)}


# ---------------------------------------------------------------- parsing

UNITTEST_LINE = re.compile(
    r'^(?P<name>\w+) \((?P<cls>[\w.]+)\)(?: \[[^\]]*\]| \(.*\))?(?P<rest>.*)$')
UNITTEST_RESULT = re.compile(
    r' \.\.\. (?P<res>ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)\s*$')
UNITTEST_RAN = re.compile(r'^Ran (\d+) tests? in ', re.M)
UNITTEST_BLOCK = re.compile(r'^(FAIL|ERROR|UNEXPECTED SUCCESS): (\w+) \(([\w.]+)\)')
# Node ids contain "::" or name a file (collection errors); excludes unittest's "FAILED (failures=1)".
PYTEST_SUMMARY = re.compile(
    r'^(PASSED|FAILED|ERROR|XFAIL|XPASS) ([^\s(]\S*(?:::|\.py)\S*)(?: - (.*))?$')
PYTEST_SKIPPED = re.compile(r'^SKIPPED \[(\d+)\] ')
PYTEST_COUNTS = re.compile(r'(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)')
PYTEST_HEADER = re.compile(r'^_{3,} (.+?) _{3,}$')
PYTEST_SECTION = re.compile(r'^={3,} (.+?) ={3,}$')
UNITTEST_OUTCOME = {'ok': 'passed', 'FAIL': 'failed', 'ERROR': 'error',
                    'expected failure': 'xfail', 'unexpected success': 'unexpected_success'}


def _unittest_id(name, cls):
    return cls if cls.endswith('.' + name) else f'{cls}.{name}'


def parse_unittest(output):
    results, order = {}, []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        head = UNITTEST_LINE.match(line)
        if not head:
            continue
        result = UNITTEST_RESULT.search(line)
        if not result and index + 1 < len(lines):  # docstring line carries the result
            result = UNITTEST_RESULT.search(lines[index + 1])
        if not result:
            continue
        res = result.group('res')
        outcome = 'skipped' if res.startswith('skipped') else UNITTEST_OUTCOME[res]
        test_id = _unittest_id(head.group('name'), head.group('cls'))
        if test_id not in results:
            order.append(test_id)
        results[test_id] = outcome
    traces = {}
    i = 0
    while i < len(lines):
        if re.fullmatch(r'={40,}', lines[i]) and i + 1 < len(lines):
            block = UNITTEST_BLOCK.match(lines[i + 1])
            if block:
                kind, name, cls = block.groups()
                test_id = _unittest_id(name, cls)
                j = i + 2
                while j < len(lines) and not re.fullmatch(r'-{40,}', lines[j]):
                    j += 1
                body, j = [], j + 1
                while j < len(lines):
                    if re.fullmatch(r'={40,}', lines[j]):
                        break
                    if (re.fullmatch(r'-{40,}', lines[j]) and j + 1 < len(lines)
                            and UNITTEST_RAN.match(lines[j + 1])):
                        break
                    body.append(lines[j])
                    j += 1
                while body and not body[-1].strip():
                    body.pop()
                traces.setdefault(test_id, '\n'.join(body))
                if test_id not in results:
                    order.append(test_id)
                    results[test_id] = {'FAIL': 'failed', 'ERROR': 'error'}.get(kind, 'unexpected_success')
                i = j
                continue
        i += 1
    ran = UNITTEST_RAN.search(output)
    tests_run = int(ran.group(1)) if ran else (len(results) if results else None)
    recognised = bool(results) or ran is not None or 'NO TESTS RAN' in output
    return {'runner': 'unittest' if recognised else None, 'results': results, 'order': order,
            'traces': traces, 'tests_run': tests_run}


def parse_pytest(output):
    results, order, skipped = {}, [], 0
    lines = output.splitlines()
    for line in lines:
        summary = PYTEST_SUMMARY.match(line)
        if summary:
            kind, test_id = summary.group(1), summary.group(2)
            outcome = {'PASSED': 'passed', 'FAILED': 'failed', 'ERROR': 'error',
                       'XFAIL': 'xfail', 'XPASS': 'xpass'}[kind]
            if test_id not in results:
                order.append(test_id)
            # A test can fail in call and error in teardown; keep the failing outcome.
            if results.get(test_id) not in FAILING:
                results[test_id] = outcome
            continue
        skip = PYTEST_SKIPPED.match(line)
        if skip:
            skipped += int(skip.group(1))
    counts = {}
    session = 'test session starts' in output
    for line in reversed(lines):
        section = PYTEST_SECTION.match(line.strip())
        if section and PYTEST_COUNTS.search(section.group(1)) or line.strip().startswith('no tests ran'):
            for number, word in PYTEST_COUNTS.findall(line):
                key = 'error' if word.startswith('error') else word
                counts[key] = counts.get(key, 0) + int(number)
            break
    traces = {}
    current, body, in_section = None, [], False
    def flush():
        if current is not None:
            while body and not body[-1].strip():
                body.pop()
            traces.setdefault(current, '\n'.join(body))
    for line in lines:
        section = PYTEST_SECTION.match(line)
        if section:
            flush()
            current, body = None, []
            in_section = section.group(1).strip() in ('FAILURES', 'ERRORS')
            continue
        if not in_section:
            continue
        header = PYTEST_HEADER.match(line)
        if header:
            flush()
            current, body = header.group(1), []
            continue
        if current is not None:
            body.append(line)
    flush()
    mapped = {}
    for test_id in order:
        tail = test_id.split('::', 1)[1].replace('::', '.') if '::' in test_id else test_id
        for name in (tail, f'ERROR at setup of {tail}', f'ERROR at teardown of {tail}',
                     f'ERROR collecting {test_id}'):
            if name in traces:
                mapped[test_id] = traces[name]
                break
    recognised = bool(results) or session or bool(counts)
    if results:
        tests_run = sum(1 for o in results.values()) + skipped
    elif counts:
        tests_run = sum(v for k, v in counts.items() if k != 'deselected')
    else:
        tests_run = 0 if 'no tests ran' in output else None
    return {'runner': 'pytest' if recognised else None, 'results': results, 'order': order,
            'traces': mapped, 'tests_run': tests_run, 'skipped': skipped, 'counts': counts}


def parse_output(output):
    pytest = parse_pytest(output)
    if pytest['runner'] and (pytest['results'] or 'test session starts' in output):
        return pytest
    unit = parse_unittest(output)
    if unit['runner']:
        return unit
    if pytest['runner']:
        return pytest
    return {'runner': None, 'results': {}, 'order': [], 'traces': {}, 'tests_run': None}


def classify(run, parsed):
    """Status from the run and the parse: passed, failed, timeout, error, no_tests."""
    if run['launch_error']:
        return 'error'
    if run['timed_out']:
        return 'timeout'
    results = parsed['results']
    failing = [t for t in parsed['order'] if results.get(t) in FAILING]
    if parsed['runner']:
        nonskipped = [t for t, o in results.items() if o not in SKIPPED]
        counts = parsed.get('counts') or {}
        if failing or counts.get('failed') or counts.get('error'):
            return 'failed'
        no_run = parsed['tests_run'] == 0 or (results and not nonskipped)
        if not results and counts and not (counts.get('passed') or counts.get('xpassed')):
            no_run = True
        if no_run or (run['rc'] == 5 and not results):
            return 'no_tests'
        return 'passed' if run['rc'] == 0 else 'failed'
    if run['rc'] == 5 or 'NO TESTS RAN' in run['output']:
        return 'no_tests'
    return 'passed' if run['rc'] == 0 else 'failed'


# ---------------------------------------------------------------- rendering

def excerpt_trace(trace):
    lines = trace.splitlines()
    if len(lines) <= TRACE_KEEP_WHOLE:
        return lines
    return [*lines[:TRACE_HEAD], f'[{len(lines) - TRACE_HEAD - TRACE_TAIL} traceback lines omitted; see full log]',
            *lines[-TRACE_TAIL:]]


def head_tail(text, head=10, tail=30):
    lines = text.rstrip('\n').splitlines()
    if len(lines) <= head + tail:
        return lines
    return [*lines[:head], f'[{len(lines) - head - tail} output lines omitted; see full log]', *lines[-tail:]]


def cap_bytes(text, cap):
    data = text.encode('utf-8')
    if len(data) <= cap:
        return text, 0
    head_n, tail_n = int(cap * 0.3), cap - int(cap * 0.3)
    head = data[:head_n].decode('utf-8', 'ignore')
    tail = data[-tail_n:].decode('utf-8', 'ignore')
    if '\n' in head:
        head = head[:head.rfind('\n') + 1]
    if '\n' in tail:
        tail = tail[tail.find('\n') + 1:]
    omitted = len(data) - len(head.encode()) - len(tail.encode())
    return head, omitted, tail


def header(check):
    parts = [f"Post-edit check {check['status']}"]
    if check['status'] == 'stale':
        parts[0] += f" (underlying result {check['underlying_status']}; source changed while the check ran, so this is not evidence about the current source)"
    if check['tests_run'] is not None:
        parts.append(f"tests={check['tests_run']}")
    if check['results']:
        parts.append(f"failing={len(check['failing'])}")
    parts += [f"trigger={check['trigger']}", f"source={check['source_before'][:12]}",
              f"check #{check['number']}"]
    return '; '.join(parts)


def _failure_details(check):
    out = []
    for test_id in check['failing']:
        out.append(f"{check['results'][test_id].upper()}: {test_id}")
        trace = check['traces'].get(test_id)
        out += excerpt_trace(trace) if trace else ['(no traceback found in the output)']
    return out


def render_selective(check):
    head = header(check) + '; mode=selective.'
    status = check['underlying_status']
    if status == 'passed':
        return [head]
    if status == 'timeout':
        return [head, f"The check timed out after {check['timeout_s']} s. Output tail:",
                *head_tail(check['output'], 0, 15)]
    if status == 'error':
        return [head, check['error_message']]
    if status == 'no_tests':
        return [head, 'No non-skipped tests ran. Output tail:', *head_tail(check['output'], 0, 15)]
    if check['failing']:
        return [head, *_failure_details(check)]
    return [head, f"Exit code {check['rc']}; no per-test results were parsed. Output excerpt:",
            *head_tail(check['output'])]


def render_full(check, cap):
    head = header(check) + f'; mode=full (output shown whole up to {cap} bytes).'
    if check['underlying_status'] == 'error':
        return [head, check['error_message']]
    capped = cap_bytes(check['output'], cap)
    if len(capped) == 2:
        return [head, capped[0].rstrip('\n')]
    first, omitted, last = capped
    return [head, first.rstrip('\n'),
            f'[... {omitted} bytes omitted from the middle (full-mode cap {cap} bytes); see full log ...]',
            last.rstrip('\n')]


def render_delta(check, baseline):
    before, after = baseline['results'], check['results']
    was_failing = {t for t, o in before.items() if o in FAILING}
    now_failing = [t for t in check['failing']]
    newly_failing = [t for t in now_failing if t not in was_failing]
    newly_passing = [t for t in sorted(was_failing) if t in after and after[t] not in FAILING]
    removed = [t for t in sorted(before) if t not in after]
    still = [t for t in now_failing if t in was_failing]
    out = [header(check) + f"; mode=delta (relative to check #{baseline['number']}; "
           f"changed {check['changed']}/{check['union']} test ids)."]
    if newly_failing:
        out.append(f'Newly failing ({len(newly_failing)}):')
        for test_id in newly_failing:
            out.append(f"{after[test_id].upper()}: {test_id}")
            trace = check['traces'].get(test_id)
            out += excerpt_trace(trace) if trace else ['(no traceback found in the output)']
    else:
        out.append('Newly failing: none.')
    out.append(f"Newly passing ({len(newly_passing)}): {', '.join(newly_passing)}" if newly_passing
               else 'Newly passing: none.')
    if removed:
        out.append(f"No longer reported ({len(removed)}): {', '.join(removed)}")
    out.append(f"Still failing: {len(still)} (as reported in check #{baseline['number']}).")
    return out


def bound_visible(lines, log_line, limit):
    """Keep additionalContext under Claude Code's 10,000-character cap; log line last."""
    body = '\n'.join(lines)
    if len(body) + len(log_line) + 1 > limit:
        room = max(200, limit - len(log_line) - 120)
        keep_head = room // 3
        body = (body[:keep_head] + f'\n[... {len(body) - room} characters omitted to fit the '
                f'hook context limit; see full log ...]\n' + body[-(room - keep_head):])
    return body + '\n' + log_line


# ---------------------------------------------------------------- hooks

def _out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=True))
    sys.stdout.flush()


def edited_path(payload):
    tool_input = payload.get('tool_input') or {}
    response = payload.get('tool_response')
    for value in (tool_input.get('file_path'), tool_input.get('notebook_path'),
                  response.get('filePath') if isinstance(response, dict) else None):
        if isinstance(value, str) and value:
            return value
    return None


def post_tool_use(payload, env=os.environ):
    if payload.get('tool_name') not in EDIT_TOOLS:
        return None
    root = find_project_root(payload.get('cwd'), env.get('CLAUDE_PROJECT_DIR'))
    if root is None:
        return None
    try:
        config = load_config(root)
    except ConfigError as exc:
        return {'systemMessage': f'reticle-checks: config ignored: {exc}'}
    trigger = relative_source_path(root, edited_path(payload), config)
    if trigger is None:
        return None
    session_id = payload.get('session_id') or 'unknown-session'
    sdir = session_dir(root, session_id)
    wait = config['timeout_s'] * 2 + 30
    with SessionLock(sdir, wait, config['timeout_s'] + 120) as lock:
        base_row = {'version': VERSION, 'session_id': session_id, 'ts': now_iso(),
                    'tool_use_id': payload.get('tool_use_id'), 'tool_name': payload.get('tool_name'),
                    'trigger_file': trigger, 'mode': config['mode']}
        if not lock.held:
            journal(sdir, {**base_row, 'kind': 'skip', 'reason': 'lock_timeout'})
            return None
        state = load_state(sdir)
        before = source_fingerprint(root, config)
        if before == state.get('last_fingerprint'):
            journal(sdir, {**base_row, 'kind': 'skip', 'reason': 'source_unchanged'})
            return None
        return _check(root, config, sdir, state, before, trigger, base_row)


def _check(root, config, sdir, state, before, trigger, base_row):
    number = int(state.get('check_count', 0)) + 1
    run = run_command(root, config)
    after = source_fingerprint(root, config)
    parsed = parse_output(run['output'])
    underlying = classify(run, parsed)
    status = 'stale' if before != after else underlying
    results = parsed['results'] if underlying in ('passed', 'failed') else {}
    check = {'status': status, 'underlying_status': underlying, 'number': number,
             'trigger': trigger, 'source_before': before, 'results': results,
             'failing': [t for t in parsed['order'] if results.get(t) in FAILING],
             'traces': parsed['traces'], 'tests_run': parsed['tests_run'],
             'output': run['output'], 'rc': run['rc'], 'timeout_s': config['timeout_s'],
             'error_message': f"Check execution error: {run['launch_error']}"}
    log_path = sdir / f'check-{number:04d}.log'
    meta = {'version': VERSION, 'check': number, 'status': status, 'underlying_status': underlying,
            'runner': parsed['runner'], 'command': config['command'], 'cwd': str(root),
            'exit_code': run['rc'], 'timed_out': run['timed_out'], 'launch_error': run['launch_error'],
            'duration_s': run['duration_s'], 'tests_run': parsed['tests_run'],
            'source_before': before, 'source_after': after, 'trigger_file': trigger,
            'results': parsed['results']}
    full = json.dumps(meta, indent=1, sort_keys=True) + '\n---- output ----\n' + run['output']
    sdir.mkdir(parents=True, exist_ok=True)
    log_path.write_text(full, encoding='utf-8', newline='\n')
    log_line = f'Full log: {log_path}'

    mode = config['mode']
    fallback = None
    changed_fraction = None
    if mode == 'full':
        lines, rendered = render_full(check, int(config['full_cap_bytes'])), 'full'
    else:
        lines, rendered = render_selective(check), 'selective'
        if mode == 'delta':
            baseline = state.get('baseline')
            if not baseline:
                fallback = 'no_baseline'
            elif not baseline.get('in_context', False):
                fallback = 'baseline_not_in_context'
            elif status not in ('passed', 'failed') or not results:
                fallback = 'status_not_comparable'
            else:
                union = set(baseline['results']) | set(results)
                changed = sum(1 for t in union if baseline['results'].get(t) != results.get(t))
                changed_fraction = changed / max(1, len(union))
                check.update(changed=changed, union=len(union))
                if changed_fraction > config['max_changed_fraction']:
                    fallback = 'changes_not_sparse'
                else:
                    candidate = render_delta(check, baseline)
                    if len('\n'.join(candidate).encode()) >= len('\n'.join(lines).encode()):
                        fallback = 'delta_not_smaller'
                    else:
                        lines, rendered = candidate, 'delta'
    visible = bound_visible(lines, log_line, int(config['max_visible_chars']))

    state.update(check_count=number, last_fingerprint=before)
    if status in ('passed', 'failed') and results:
        state['baseline'] = {'number': number, 'results': results, 'in_context': True}
    save_state(sdir, state)
    journal(sdir, {**base_row, 'kind': 'check', 'check_number': number, 'rendered_as': rendered,
                   'status': status, 'underlying_status': underlying, 'runner': parsed['runner'],
                   'tests_run': parsed['tests_run'], 'failing': len(check['failing']),
                   'duration_s': run['duration_s'], 'full_bytes': len(full.encode('utf-8')),
                   'visible_bytes': len(visible.encode('utf-8')), 'log_path': str(log_path),
                   'source_before': before, 'source_after': after,
                   'delta_fallback': (fallback is not None) if mode == 'delta' else None,
                   'delta_fallback_reason': fallback, 'changed_fraction': changed_fraction,
                   'visible_text': visible})
    return {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': visible}}


def invalidate(payload, env=os.environ):
    root = find_project_root(payload.get('cwd'), env.get('CLAUDE_PROJECT_DIR'))
    if root is None:
        return None
    session_id = payload.get('session_id') or 'unknown-session'
    sdir = session_dir(root, session_id)
    if not sdir.is_dir():
        return None
    event = payload.get('hook_event_name') or 'unknown'
    why = payload.get('trigger') or payload.get('source') or ''
    with SessionLock(sdir, 30, 300):
        state = load_state(sdir)
        baseline = state.get('baseline')
        had = bool(baseline and baseline.get('in_context'))
        if baseline:
            baseline['in_context'] = False
            save_state(sdir, state)
        journal(sdir, {'version': VERSION, 'kind': 'baseline_invalidated', 'ts': now_iso(),
                       'session_id': session_id, 'reason': f'{event}:{why}'.rstrip(':'),
                       'had_baseline_in_context': had})
    return None  # SessionStart adds plain stdout to context, so print nothing.


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else 'post-tool-use'
    try:
        payload = json.loads(sys.stdin.buffer.read().decode('utf-8') or '{}')
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    handler = {'post-tool-use': post_tool_use, 'invalidate': invalidate}.get(command)
    if handler is None:
        sys.stderr.write(f'reticle-checks: unknown entry point {command!r}\n')
        return 0
    result = handler(payload)
    if result is not None:
        _out(result)
    return 0


if __name__ == '__main__':
    sys.exit(main())
