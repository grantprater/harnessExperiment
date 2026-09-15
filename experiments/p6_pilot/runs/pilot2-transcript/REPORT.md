# P6 pilot run: pilot2-transcript

- Arm: `bounded-transcript-v2`; protocol `f955736eb747`; runner v2; source `{'commit': 'f6723d350098626a5e5e20bb4a955a68b70734ae', 'tracked_changes': False}`
- Models: qwen/qwen3.5-9b, google/gemma-4-26b-a4b-it, nvidia/nemotron-3-super-120b-a12b:free
- Provider routing: `{"qwen/qwen3.5-9b": {"order": ["venice"], "allow_fallbacks": false, "require_parameters": true}, "google/gemma-4-26b-a4b-it": {"order": ["deepinfra"], "allow_fallbacks": false, "require_parameters": true}, "nvidia/nemotron-3-super-120b-a12b:free": {"order": ["nvidia"], "allow_fallbacks": false, "require_parameters": true}}`
- Tasks: tomlkit-549, humanize-329, sqlparse-865
- Limits: 25 model calls/run, 80000 context bytes, 8192 max output tokens, total HTTP attempt cap 250
- Runs recorded: 9 of 9 planned

## Runs

| task | model | stop | model calls | tool calls | acceptance | fail-to-pass | pass-to-pass | failing f2p/p2p | paging calls | repeated calls | no-tool replies | HTTP attempts | HTTP errors | prompt tok | completion tok | cost (reported) | missing usage |
|---|---|---|---:|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| tomlkit-549 | qwen/qwen3.5-9b | model_error | 19 | 18 | rejected | fail | pass | 1/0 | 0 | 1 | 0 | 42 | 24 | 74470 | 1483 | $0.0077 | 0 |
| humanize-329 | qwen/qwen3.5-9b | finish_requested | 12 | 9 | rejected | pass | fail | 0/15 | 0 | 2 | 3 | 31 | 19 | 60588 | 29091 | $0.0104 | 0 |
| sqlparse-865 | qwen/qwen3.5-9b | model_call_limit | 25 | 25 | rejected | fail | pass | 1/0 | 0 | 16 | 0 | 47 | 22 | 128326 | 2999 | $0.0133 | 0 |
| tomlkit-549 | google/gemma-4-26b-a4b-it | model_call_limit | 25 | 25 | rejected | fail | pass | 1/0 | 0 | 3 | 0 | 25 | 0 | 124083 | 2370 | $0.0095 | 0 |
| humanize-329 | google/gemma-4-26b-a4b-it | model_call_limit | 25 | 25 | rejected | fail | pass | 6/0 | 1 | 15 | 0 | 25 | 0 | 117357 | 1830 | $0.0088 | 0 |
| sqlparse-865 | google/gemma-4-26b-a4b-it | model_call_limit | 25 | 25 | rejected | fail | pass | 1/0 | 1 | 11 | 0 | 25 | 0 | 138278 | 3470 | $0.0109 | 0 |
| tomlkit-549 | nvidia/nemotron-3-super-120b-a12b:free | model_error | 15 | 14 | rejected | fail | pass | 1/0 | 0 | 0 | 0 | 19 | 0 | 60509 | 2088 | $0.0000 | 5 |
| humanize-329 | nvidia/nemotron-3-super-120b-a12b:free | model_call_limit | 25 | 25 | rejected | fail | fail | 6/70 | 0 | 4 | 0 | 33 | 0 | 335261 | 14552 | $0.0000 | 8 |
| sqlparse-865 | nvidia/nemotron-3-super-120b-a12b:free | pilot_call_budget_exhausted |  |  | rejected | fail | pass | 1/0 | 0 | 0 | 0 | 3 | 0 | 4454 | 139 | $0.0000 | 1 |

## Totals by model

| model | runs | accepted | rejected | other | HTTP attempts | HTTP errors | prompt tok | completion tok | reasoning tok | cost (reported) | responses missing cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| qwen/qwen3.5-9b | 3 | 0 | 3 | 0 | 120 | 65 | 263384 | 33573 | 30167 | $0.0314 | 0 |
| google/gemma-4-26b-a4b-it | 3 | 0 | 3 | 0 | 75 | 0 | 379718 | 7670 | 0 | $0.0292 | 0 |
| nvidia/nemotron-3-super-120b-a12b:free | 3 | 0 | 3 | 0 | 55 | 0 | 400224 | 16779 | 13392 | $0.0000 | 14 |

## Provider errors (HTTP errors and error bodies)

- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- humanize-329__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- sqlparse-865__qwen_qwen3.5-9b: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"qwen/qwen3.5-9b is temporarily rate-limited upstream. Please retry shortly, or add y
- tomlkit-549__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- tomlkit-549__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- tomlkit-549__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- tomlkit-549__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- tomlkit-549__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- humanize-329__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- humanize-329__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- humanize-329__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- humanize-329__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- humanize-329__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- humanize-329__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- humanize-329__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- humanize-329__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}

Generated by `report.py` from config.json, calls.jsonl, and results.jsonl only.
