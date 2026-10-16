"""OpenAI-compatible chat-completions connection; credentials stay out of journals."""
import json
import urllib.error
import urllib.request

from reticle.runtime.controller import ModelClientError, ModelResponse


class ApiClient:
    reports_provider_attempts = True

    def __init__(self, key, model, base_url, max_tokens=4096, timeout=300, provider=None):
        self.key, self.model, self.base_url = key, model, base_url.rstrip('/')
        self.max_tokens, self.timeout, self.provider = max_tokens, timeout, provider

    def complete(self, messages, tools, *, attempts=None):
        body = dict(model=self.model, messages=messages, tools=tools,
                    tool_choice='auto', max_tokens=self.max_tokens)
        if self.provider:
            body['provider'] = {'order': [self.provider], 'allow_fallbacks': False}
        attempt_id = attempts.begin({'provider': 'api', 'model': self.model}) if attempts else None
        request = urllib.request.Request(
            self.base_url + '/chat/completions', data=json.dumps(body).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
            message = data['choices'][0]['message']
            if not isinstance(message, dict):
                raise ValueError('Invalid assistant message')
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            # Avoid echoing provider bodies or request headers that could contain secrets.
            detail = f'HTTP {exc.code}' if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
            if attempts:
                attempts.finish(attempt_id, outcome='api_error', cost=None, metadata={'error': detail})
            raise ModelClientError('API request failed: ' + detail) from None
        return ModelResponse(message, data.get('usage'), {'model': data.get('model'), 'provider': 'api'})
