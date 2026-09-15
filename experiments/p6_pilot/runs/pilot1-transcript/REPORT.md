# P6 pilot run: pilot1-transcript

- Arm: `bounded-transcript-v1`; protocol `b9b409abdb36`; runner v1; source `{'commit': '70b15f14e27112f5faac695ffda09452a47a8383', 'tracked_changes': False}`
- Models: qwen/qwen3.5-9b, google/gemma-4-26b-a4b-it:free, nvidia/nemotron-3-super-120b-a12b:free
- Provider routing: `"unpinned (not recorded)"`
- Tasks: tomlkit-549, humanize-329, sqlparse-865
- Limits: 25 model calls/run, 80000 context bytes, 8192 max output tokens, total HTTP attempt cap 250
- Runs recorded: 9 of 9 planned

## Runs

| task | model | stop | model calls | tool calls | acceptance | fail-to-pass | pass-to-pass | failing f2p/p2p | paging calls | repeated calls | no-tool replies | HTTP attempts | HTTP errors | prompt tok | completion tok | cost (reported) | missing usage |
|---|---|---|---:|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| tomlkit-549 | qwen/qwen3.5-9b | model_call_limit | 25 | 31 | rejected | fail | pass | 1/0 | 0 | 10 | 1 | 26 | 1 | 154698 | 2602 | $0.0170 | 0 |
| humanize-329 | qwen/qwen3.5-9b | model_call_limit | 25 | 23 | rejected | fail | pass | 6/0 | 0 | 7 | 2 | 25 | 0 | 133757 | 3563 | $0.0141 | 0 |
| sqlparse-865 | qwen/qwen3.5-9b | model_call_limit | 25 | 25 | rejected | fail | pass | 1/0 | 0 | 11 | 0 | 25 | 0 | 116868 | 1844 | $0.0121 | 0 |
| tomlkit-549 | google/gemma-4-26b-a4b-it:free | model_error | 1 | 0 | rejected | fail | pass | 1/0 | 0 | 0 | 0 | 4 | 4 | 0 | 0 | $0.0000 | 0 |
| humanize-329 | google/gemma-4-26b-a4b-it:free | model_error | 2 | 1 | rejected | fail | pass | 6/0 | 0 | 0 | 0 | 6 | 5 | 1163 | 25 | $0.0000 | 0 |
| sqlparse-865 | google/gemma-4-26b-a4b-it:free | model_error | 1 | 0 | rejected | fail | pass | 1/0 | 0 | 0 | 0 | 4 | 4 | 0 | 0 | $0.0000 | 0 |
| tomlkit-549 | nvidia/nemotron-3-super-120b-a12b:free | model_call_limit | 25 | 25 | rejected | fail | pass | 1/0 | 0 | 0 | 0 | 31 | 0 | 144763 | 4175 | $0.0000 | 6 |
| humanize-329 | nvidia/nemotron-3-super-120b-a12b:free | model_call_limit | 25 | 25 | rejected | fail | pass | 6/0 | 0 | 1 | 0 | 30 | 0 | 131718 | 6229 | $0.0000 | 5 |
| sqlparse-865 | nvidia/nemotron-3-super-120b-a12b:free | model_call_limit | 25 | 25 | rejected | fail | pass | 1/0 | 0 | 0 | 0 | 35 | 0 | 114574 | 2385 | $0.0000 | 10 |

## Totals by model

| model | runs | accepted | rejected | other | HTTP attempts | HTTP errors | prompt tok | completion tok | reasoning tok | cost (reported) | responses missing cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| qwen/qwen3.5-9b | 3 | 0 | 3 | 0 | 76 | 1 | 405323 | 8009 | 2733 | $0.0432 | 0 |
| google/gemma-4-26b-a4b-it:free | 3 | 0 | 3 | 0 | 14 | 13 | 1163 | 25 | 0 | $0.0000 | 0 |
| nvidia/nemotron-3-super-120b-a12b:free | 3 | 0 | 3 | 0 | 96 | 0 | 391055 | 12789 | 8546 | $0.0000 | 21 |

## Provider errors (HTTP errors and error bodies)

- tomlkit-549__qwen_qwen3.5-9b: HTTP 502: {"error":{"message":"Provider returned error","code":502,"metadata":{"raw":"{\"code\":50507,\"message\":\"Request failed: Unknown error.\",\"data\":null}","prov
- tomlkit-549__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- tomlkit-549__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- tomlkit-549__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- tomlkit-549__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- humanize-329__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- humanize-329__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- humanize-329__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- humanize-329__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- humanize-329__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- sqlparse-865__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- sqlparse-865__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- sqlparse-865__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- sqlparse-865__google_gemma-4-26b-a4b-it_free: HTTP 429: {"error":{"message":"Provider returned error","code":429,"metadata":{"raw":"google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream. Please retry sh
- tomlkit-549__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
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
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}
- sqlparse-865__nvidia_nemotron-3-super-120b-a12b_free: HTTP None: {"message": "Upstream error from Nvidia: Service temporarily overloaded", "code": 502, "metadata": {"error_type": "provider_unavailable"}}

Generated by `report.py` from config.json, calls.jsonl, and results.jsonl only.
