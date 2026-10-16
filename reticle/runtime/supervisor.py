"""Stable terminal and provider broker for opt-in, trusted runtime updates.

Workers write the session only while running a turn. The supervisor writes activation
events only before dispatch or after worker exit, reopening the journal each time.
"""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from time import monotonic
from uuid import uuid4

from reticle.runtime.budgets import TaskBudgetExhausted
from reticle.runtime.controller import ModelClientError
from reticle.runtime.ownership import SessionWriterLock
from reticle.runtime.session import LocalRuntime
from reticle.runtime.upgrades import RuntimeBundles
from reticle.runtime.telemetry import write_usage_report


def error_data(exc):
    result = {'type': type(exc).__name__, 'message': str(exc)}
    if isinstance(exc, TaskBudgetExhausted):
        result.update(resource=exc.resource, requested=exc.requested, remaining=exc.remaining)
    return result


class RuntimeWorker:
    def __init__(self, bundles, version, session, args, attempt_aware=False):
        bundles.verify(version)
        bundles.verify(bundles.state['baseline'])
        bootstrap = bundles.path(bundles.state['baseline']) / 'reticle/runtime/live_worker.py'
        environment = {k: v for k, v in os.environ.items()
                       if not k.upper().endswith(('_KEY', '_TOKEN', '_SECRET'))}
        environment['PYTHONIOENCODING'] = 'utf-8'
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        self.process = subprocess.Popen(
            [sys.executable, '-B', str(bootstrap)], cwd=bundles.path(version), env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.inbox = queue.Queue()
        self.diagnostics = deque(maxlen=20)
        def reader():
            try:
                for line in self.process.stdout:
                    self.inbox.put(json.loads(line))
            except Exception as exc:
                self.inbox.put({'kind': 'error', 'error': error_data(exc)})
            finally:
                self.inbox.put({'kind': 'eof'})
        def errors():
            for line in self.process.stderr:
                self.diagnostics.append(line.rstrip())
        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=errors, daemon=True).start()
        worker_args = {**vars(args), 'usage_report': None}
        self.send({'bundle': str(bundles.path(version)), 'version': version, 'session': str(session),
                   'args': worker_args, 'attempt_aware': attempt_aware, 'interpreter': sys.executable})

    def send(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def receive(self, timeout=600):
        try:
            value = self.inbox.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError('Runtime worker did not respond before its deadline') from None
        if value['kind'] == 'eof':
            raise RuntimeError('Runtime worker exited unexpectedly' +
                               (': ' + '\n'.join(self.diagnostics) if self.diagnostics else ''))
        if value['kind'] == 'error':
            raise RuntimeError(value['error']['message'])
        return value

    def ready(self):
        # Validation is bounded, and never sends a model request.
        deadline = monotonic() + 30
        while True:
            value = self.receive(timeout=max(0, deadline-monotonic()))
            if value['kind'] == 'terminal':
                continue
            if value['kind'] != 'ready' or value.get('protocol') != 1:
                raise RuntimeError('Runtime worker failed its readiness handshake')
            return value

    def close(self):
        try:
            if self.process.poll() is None:
                self.send({'kind': 'close'})
            self.process.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
        finally:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()


class BrokerAttempts:
    """Run provider callbacks against the worker's existing durable attempt ledger."""
    def __init__(self, worker, budget):
        self.worker = worker
        self.budget = budget

    def call(self, value):
        self.worker.send(value)
        result = self.worker.receive()
        if result['kind'] != 'attempt_result':
            raise RuntimeError('Unexpected provider accounting response')
        error = result.get('error')
        if error:
            if error['type'] == 'TaskBudgetExhausted':
                raise TaskBudgetExhausted(error['resource'], error['requested'], error['remaining'])
            raise ModelClientError(error['message'])
        return result.get('value')

    def begin(self, metadata=None):
        remaining = self.budget['limit'] - self.budget['used']
        if remaining <= 0:
            raise TaskBudgetExhausted('model_attempts', 1, remaining)
        self.budget['used'] += 1
        return self.call({'kind': 'attempt_begin', 'metadata': metadata})

    def finish(self, attempt_id, **arguments):
        return self.call({'kind': 'attempt_finish', 'attempt_id': attempt_id, 'arguments': arguments})


class RuntimeSupervisor:
    def __init__(self, session, workspace, args, client, initial_source):
        self.session = Path(session).resolve()
        self.workspace = Path(workspace).resolve()
        self.args, self.client = args, client
        self.bundles = RuntimeBundles(self.session, initial_source)

    def record(self, kind, payload):
        # No worker is dispatching at this boundary. Avoid stale journal sequence counters.
        with SessionWriterLock(self.session).acquire('runtime-supervisor'):
            LocalRuntime(self.session).journal.append(kind, payload)

    def start(self, version):
        worker = RuntimeWorker(self.bundles, version, self.session, self.args,
                               getattr(self.client, 'reports_provider_attempts', False))
        try:
            ready = worker.ready()
            if ready['version'] != version:
                raise RuntimeError('Worker loaded a different runtime version')
            return worker
        except BaseException:
            worker.close()
            raise

    def stage(self, source_root, reason=''):
        source = Path(source_root).resolve()
        source.relative_to(self.workspace)
        version = self.bundles.snapshot(source)
        worker = self.start(version)
        worker.close()
        self.bundles.queue(version, reason)
        return version

    def select_worker(self):
        pending = self.bundles.state.get('pending')
        if pending:
            if any(s.classification == 'unknown_external_outcome' and not s.replay_safe
                   for s in LocalRuntime(self.session).recovery.pending_operations):
                raise RuntimeError('Runtime activation is deferred until unfinished external effects are reconciled')
            try:
                worker = self.start(pending)
            except Exception as exc:
                self.bundles.reject_pending()
                self.record('runtime_activation_rejected', {'version': pending, 'error': str(exc)})
                print(f'Runtime update rejected; keeping {self.bundles.state["active"][:12]}: {exc}')
            else:
                previous = self.bundles.state['active']
                reason = self.bundles.state.get('pending_reason', '')
                try:
                    self.bundles.promote()
                    self.record('runtime_activated', {'version': pending, 'previous': previous, 'reason': reason})
                except BaseException:
                    worker.close()
                    raise
                print(f'Runtime activated: {pending[:12]}')
                return worker
        active = self.bundles.state['active']
        try:
            return self.start(active)
        except Exception as exc:
            fallback = self.bundles.state.get('previous') or self.bundles.state['baseline']
            if fallback == active:
                raise
            worker = self.start(fallback)
            try:
                self.bundles.state.update(active=fallback, previous=None)
                self.bundles.save()
                self.record('runtime_rolled_back', {'version': active, 'fallback': fallback, 'error': str(exc)})
            except BaseException:
                worker.close()
                raise
            print(f'Runtime startup failed; restored {fallback[:12]}: {exc}')
            return worker

    def run_turn(self, prompt):
        # Failure before dispatch can fall back. Failure after dispatch never replays a turn.
        worker = None
        dispatched = False
        model_requests = 0
        attempt_budget = {'used': 0, 'limit': self.args.max_steps}
        attempt_aware = getattr(self.client, 'reports_provider_attempts', False) is True
        try:
            worker = self.select_worker()
            worker.send({'kind': 'run', 'prompt': prompt})
            dispatched = True
            while True:
                event = worker.receive()
                kind = event['kind']
                if kind == 'terminal':
                    print(event['text'], end='', flush=True)
                elif kind == 'model':
                    model_requests += 1
                    if model_requests > self.args.max_steps:
                        raise RuntimeError('Runtime worker exceeded the supervisor model-response limit')
                    if event['attempt_aware'] is not attempt_aware:
                        raise RuntimeError('Worker/provider attempt-accounting contract does not match')
                    request_bytes = len(json.dumps({'messages': event['messages'], 'tools': event['tools']},
                                        sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))
                    if request_bytes > self.args.max_context_bytes:
                        raise RuntimeError('Runtime worker exceeded the supervisor context limit')
                    try:
                        if not attempt_aware:
                            attempt_budget['used'] += 1
                        options = {'attempts': BrokerAttempts(worker, attempt_budget)} if attempt_aware else {}
                        response = self.client.complete(event['messages'], event['tools'], **options)
                        worker.send({'kind': 'model_result', 'message': response.message,
                                     'usage': response.usage, 'metadata': response.metadata})
                    except Exception as exc:
                        worker.send({'kind': 'model_result', 'error': error_data(exc)})
                elif kind == 'activate':
                    try:
                        version = self.stage(event['source_root'], event.get('reason', ''))
                        worker.send({'kind': 'activation_result', 'version': version})
                    except Exception as exc:
                        worker.send({'kind': 'activation_result', 'error': error_data(exc)})
                elif kind == 'done':
                    return event['exit_code']
                else:
                    raise RuntimeError(f'Unexpected runtime worker message: {kind}')
        except BaseException:
            if worker:
                worker.close()
            if dispatched:
                self.record('runtime_worker_interrupted', {'version': self.bundles.state['active'],
                            'replay': False, 'reason': 'Worker failed or was interrupted after turn dispatch'})
            raise
        finally:
            if worker:
                worker.close()
            if self.args.usage_report:
                write_usage_report(LocalRuntime(self.session), self.args.usage_report)


def launch_supervised(args):
    from reticle.interactive import ROOT, connection, execution_config, selected_model, usage_summary
    workspace = Path(args.dir).resolve()
    if args.resume:
        session = Path(args.resume).resolve()
        if not (session / 'session.json').is_file():
            raise ValueError('Saved session was not found: ' + str(session))
        workspace = Path(json.loads((session / 'session.json').read_text(encoding='utf-8'))['workspace_root'])
    else:
        session = Path(args.session_dir).resolve() if args.session_dir else workspace / '.reticle' / uuid4().hex[:12]
        if session.exists():
            raise ValueError('Session already exists; use --resume.')
    if not workspace.is_dir():
        raise ValueError('Workspace does not exist: ' + str(workspace))
    backend, _ = execution_config(args)
    client = connection(args, session)
    LocalRuntime(session, workspace)
    # This lock prevents two supervisors from racing over activation state; the worker
    # separately holds the existing session writer lock during each controller invocation.
    with SessionWriterLock(session / 'runtime-updates').acquire('terminal-supervisor'):
        supervisor = RuntimeSupervisor(session, workspace, args, client, ROOT)
        print(f'Reticle | {args.client} | {selected_model(args)} | {workspace}')
        print(f'Session: {session}')
        print(f'Execution: {backend.name}. Runtime updates enabled; /help lists commands.')
        print(f'Runtime: {supervisor.bundles.state["active"][:12]}')
        print(f'Recovery launcher: {supervisor.bundles.root / "resume.py"}')
        prompt, code = args.prompt, 0
        while True:
            if prompt is None:
                try:
                    prompt = input('\nreticle> ').strip()
                except (EOFError, KeyboardInterrupt):
                    print('\nSession saved.')
                    break
            if prompt in ('/exit', '/quit'):
                break
            if prompt == '/help':
                print('/exit  Quit\n/session  Show session path\n/usage  Show tokens\n'
                      '/runtime  Show active and pending versions\n/reload  Validate workspace harness and queue activation')
            elif prompt == '/session':
                print(session)
            elif prompt == '/usage':
                usage = [e.payload.get('usage') for e in LocalRuntime(session).journal.read_all() if e.kind == 'model_call']
                print('Session: ' + usage_summary(usage))
            elif prompt == '/runtime':
                print(json.dumps(supervisor.bundles.state, indent=2))
            elif prompt == '/reload':
                try:
                    version = supervisor.stage(workspace, 'Terminal /reload')
                    print(f'Runtime {version[:12]} validated and queued for the next user turn.')
                except Exception as exc:
                    print(f'Runtime update rejected: {exc}')
            elif prompt:
                try:
                    code = supervisor.run_turn(prompt)
                except KeyboardInterrupt:
                    print('\nInterrupted. Session saved; unfinished actions are not replayed automatically.')
                    return 130
                if args.once:
                    break
                # Preserve the existing stop on ambiguous external effects.
                if any(not s.replay_safe and s.classification == 'unknown_external_outcome'
                       for s in LocalRuntime(session).recovery.pending_operations):
                    break
            prompt = None
        return code
