"""Fixed bootstrap for a versioned worker. Protocol uses stdin/stdout, never credentials.

Run this file directly, before importing any reticle package. The supervisor selects
the bundle. Each worker handles one complete user turn and then exits.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


PROTOCOL_OUT = sys.stdout
PROTOCOL_IN = sys.stdin


def send(value):
    PROTOCOL_OUT.write(json.dumps(value, ensure_ascii=False) + '\n')
    PROTOCOL_OUT.flush()


def receive():
    line = PROTOCOL_IN.readline()
    if not line:
        raise EOFError('Supervisor disconnected')
    return json.loads(line)


def error_data(exc):
    result = {'message': str(exc), 'type': type(exc).__name__}
    if type(exc).__name__ == 'TaskBudgetExhausted':
        result.update(resource=exc.resource, requested=exc.requested, remaining=exc.remaining)
    return result


def raise_error(data):
    from reticle.runtime.budgets import TaskBudgetExhausted
    from reticle.runtime.controller import ModelClientError
    if data.get('type') == 'TaskBudgetExhausted':
        raise TaskBudgetExhausted(data['resource'], data['requested'], data['remaining'])
    raise ModelClientError(data.get('message', 'Supervisor request failed'))


class TerminalStream:
    encoding = 'utf-8'

    def isatty(self):
        return False

    def write(self, text):
        if text:
            send({'kind': 'terminal', 'text': text})
        return len(text)

    def flush(self):
        pass


class BrokerClient:
    def __init__(self, attempt_aware):
        self.reports_provider_attempts = attempt_aware

    def complete(self, messages, tools, *, attempts=None):
        from reticle.runtime.controller import ModelResponse
        send({'kind': 'model', 'messages': messages, 'tools': tools, 'attempt_aware': attempts is not None})
        while True:
            response = receive()
            if response['kind'] in ('attempt_begin', 'attempt_finish'):
                try:
                    if attempts is None:
                        raise RuntimeError('No provider attempt recorder for this request')
                    value = (attempts.begin(response.get('metadata')) if response['kind'] == 'attempt_begin'
                             else attempts.finish(response['attempt_id'], **response['arguments']))
                    send({'kind': 'attempt_result', 'value': value})
                except Exception as exc:
                    send({'kind': 'attempt_result', 'error': error_data(exc)})
                continue
            if response.get('error'):
                raise_error(response['error'])
            if response['kind'] != 'model_result':
                raise RuntimeError('Unexpected broker response')
            return ModelResponse(response['message'], response.get('usage'), response.get('metadata') or {})


class UpgradeClient:
    def request(self, source_root, reason):
        send({'kind': 'activate', 'source_root': source_root, 'reason': reason})
        result = receive()
        if result.get('error'):
            raise ValueError(result['error']['message'])
        if result['kind'] != 'activation_result':
            raise RuntimeError('Unexpected activation response')
        return result['version']


def validate(config):
    """Import/API checks, session compatibility on a copy, and a real offline controller smoke test."""
    from reticle.runtime.session import LocalRuntime
    from reticle.runtime.contracts import TaskEnvelope
    from reticle.runtime.controller import AgentController, AgentLimits, ModelResponse
    from reticle.context import PressureRecentContextPolicyV4
    import reticle.interactive as interactive
    if not callable(interactive.launch) or not callable(interactive.learning_tools):
        raise ValueError('Candidate is missing the interactive entry points')
    with tempfile.TemporaryDirectory(prefix='reticle-validation-') as directory:
        root = Path(directory)
        workspace = root / 'workspace'
        workspace.mkdir()
        source = Path(config['session'])
        clone = root / 'session'
        # Never open the live journal for writing during validation.
        shutil.copytree(source, clone, ignore=shutil.ignore_patterns(
            'runtime-updates', 'provider', 'calls.jsonl', 'writer.lock', 'writer-owner.json'))
        saved = json.loads((clone / 'session.json').read_text(encoding='utf-8'))
        saved['workspace_root'] = str(workspace)
        (clone / 'session.json').write_text(json.dumps(saved), encoding='utf-8')
        LocalRuntime(clone)
        runtime = LocalRuntime(root / 'smoke', workspace)
        class SmokeClient:
            def complete(self, messages, tools):
                return ModelResponse({'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'smoke-finish', 'type': 'function', 'function': {
                        'name': 'finish', 'arguments': '{"summary":"runtime smoke check"}'}}]})
        options = argparse.Namespace(**config['args'])
        if getattr(options, 'extension_library', None):
            # Validate an absolute custom library under the cloned smoke workspace.
            original_workspace = Path(json.loads((source / 'session.json').read_text(encoding='utf-8'))['workspace_root'])
            library = (original_workspace / options.extension_library).resolve()
            options.extension_library = str(workspace / library.relative_to(original_workspace))
        if getattr(options, 'style_profile', None):
            # Pin data is copied explicitly; smoke checks never use/edit the live target.
            original_workspace = Path(json.loads((source / 'session.json').read_text(encoding='utf-8'))['workspace_root'])
            profile = original_workspace / options.style_profile
            target = workspace / 'style-target.json'
            shutil.copyfile(profile, target)
            options.style_profile = str(target)
        tools, _, _, _ = interactive.learning_tools(runtime, options, interpreter=config['interpreter'])
        tools.quiet = True
        tools.runtime_updates = UpgradeClient()
        names = [s['function']['name'] for s in tools.schemas()]
        if 'activate_runtime' not in names:
            raise ValueError('Candidate removed the runtime activation interface')
        result = AgentController(runtime, TaskEnvelope('runtime-smoke', 'Finish the smoke check.',
                                 budgets={'model_responses': 1, 'model_attempts': 1, 'tool_actions': 1}),
                                 tools, SmokeClient(), AgentLimits(1, 120000),
                                 policy=PressureRecentContextPolicyV4(),
                                 expose_usage=getattr(options, 'model_usage', False)).run()
        if result.stop_reason != 'finish_requested':
            raise ValueError('Candidate controller failed the offline smoke check')


def main():
    config = receive()
    sys.path.insert(0, config['bundle'])
    os.environ['RETICLE_RUNTIME_VERSION'] = config['version']
    sys.stdout = TerminalStream()
    try:
        validate(config)
        send({'kind': 'ready', 'protocol': 1, 'version': config['version']})
        command = receive()
        if command['kind'] == 'close':
            return 0
        if command['kind'] != 'run':
            raise ValueError('Expected a user-turn command')
        import reticle.interactive as interactive
        broker = BrokerClient(config['attempt_aware'])
        interactive.connection = lambda args, session=None: broker
        original_tools = interactive.learning_tools
        def learning_tools(*args, **kwargs):
            tools, reasoning, library, knowledge = original_tools(*args, **kwargs)
            tools.runtime_updates = UpgradeClient()
            return tools, reasoning, library, knowledge
        interactive.learning_tools = learning_tools
        args = argparse.Namespace(**config['args'])
        args.prompt = command['prompt']
        args.resume = config['session']
        args.session_dir = None
        args.once = True
        args.runtime_updates = False
        args._runtime_worker = True
        code = interactive.launch(args)
        send({'kind': 'done', 'exit_code': code})
        return code
    except Exception as exc:
        send({'kind': 'error', 'error': error_data(exc)})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
