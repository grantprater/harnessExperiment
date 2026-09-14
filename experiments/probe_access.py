"""Check configured model access without printing credentials."""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

config = {}
for line in (Path(__file__).resolve().parents[1] / '.env').read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        config[key.strip().removeprefix('$env:')] = value.strip().strip('\"\'')
base = config['LLM_BASE_URL'].rstrip('/')
headers = {'Authorization': 'Bearer ' + config['LLM_API_KEY']}
try:
    req = urllib.request.Request(base + '/models', headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        models = json.load(response)['data']
    matches = [m['id'] for m in models if 'luna' in m['id'].lower() or m['id'] == config['LLM_MODEL']]
    print(json.dumps({'available_matches': matches, 'configured_model': config['LLM_MODEL']}))
    model = sys.argv[1] if len(sys.argv) > 1 else config['LLM_MODEL']
    body = {'model': model, 'messages': [{'role': 'user', 'content': 'Reply with OK.'}], 'max_tokens': 32}
    req = urllib.request.Request(base + '/chat/completions', data=json.dumps(body).encode(), headers={**headers, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as response:
        data = json.load(response)
    print(json.dumps({'requested_model': model, 'returned_model': data.get('model'), 'usage': data.get('usage'), 'has_choices': bool(data.get('choices')), 'error': data.get('error')}))
except urllib.error.HTTPError as error:
    print('HTTP status:', error.code)
    try:
        details = json.load(error).get('error', {})
        print(json.dumps({'message': details.get('message'), 'code': details.get('code')}))
    except Exception:
        pass
    sys.exit(1)
except Exception as error:
    print(type(error).__name__ + ': ' + str(error))
    sys.exit(1)
