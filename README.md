# Reticle: The Cognitive Harness Framework

Reticle is a durable session runtime for coding agents: the session records what happened,
context is a replaceable, per-invocation view over that history, the harness policy decides
how to continue, and actual execution happens in a separate, swappable backend (trusted-local
or a pinned, network-isolated OCI image). Harness policies (context management, tool
interfaces, continuation logic) are compared against each other through short, discriminating
experiments rather than folded permanently into the runtime. See
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) section 1 for the full objective and
operating rule.

## Documents

- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) - the current plan and work ledger.
- [IMPLEMENTATION_PLAN_CRITIQUE.md](IMPLEMENTATION_PLAN_CRITIQUE.md) - the current critique.
- [experiments/REGISTER.md](experiments/REGISTER.md) - the experiment register.
- [Evidence ontology experiment](experiments/neurosymbolic/README.md) - optional structured memory and advisory symbolic reasoning, fixtures, and comparison protocol.
- [experiments/session_harness/](experiments/session_harness/) - run cards, reports, and
  delivery records.

Earlier, superseded planning documents (the pre-September-15 prototype README,
`ARCHITECTURE.md`, `ACTIVE_EPISTEMIC_BOARD.md`, and the 2026-09-14 plan) are kept for history
in [archive/docs/](archive/docs/). The harness's self-refactoring loop, retired for
optimizing a complexity metric rather than task outcomes, is described in
[archive/RETIRED.md](archive/RETIRED.md).

## Current empirical status

Four live E3 repair-control runs on `sqlparse-865` with weak free models produced no accepted
repair (each stopped on rate limits, response budgets, or a failed fail-to-pass test); toolset
v3 passed its offline gates (244 tests, 4 OCI skipped). A positive control with a capable
model is the next step.

## Running the tests

Test interpreter: `C:\Users\grant\harnessExperiment\.runtime\test-venv\Scripts\python.exe`.
Run from the repo root:

```
python -m unittest discover -s tests -q
```

## Running the pilot runner

### ChatGPT subscription provider (experimental)

The current pilot runner can use your ChatGPT plan while Reticle keeps control of
the agent loop, context policy, and local tools. This uses the official open-source
[ChatGPT plan authorization flow](https://developers.openai.com/siwc/token-sharing-open-source)
and the public Responses API. It does not read or reuse Codex's login files.

From this worktree in PowerShell:

```powershell
python -m venv .runtime/subscription-venv
& ./.runtime/subscription-venv/Scripts/python.exe -m pip install -e '.[subscription]'
& ./.runtime/subscription-venv/Scripts/python.exe -m reticle.cognitive.chatgpt_auth login
& ./.runtime/subscription-venv/Scripts/python.exe -m reticle.cognitive.chatgpt_auth models
# Replace ACCOUNT_MODEL_SLUG with a slug returned by the models command.
& ./.runtime/subscription-venv/Scripts/python.exe -m reticle.cognitive.chatgpt_auth smoke --model ACCOUNT_MODEL_SLUG
& ./.runtime/subscription-venv/Scripts/python.exe experiments/subscription_smoke.py --model ACCOUNT_MODEL_SLUG
& ./.runtime/subscription-venv/Scripts/python.exe experiments/p6_pilot/run_pilot.py --client chatgpt-subscription --models ACCOUNT_MODEL_SLUG --tasks humanize-329 --run-name subscription-control --max-calls-per-run 10 --max-total-calls 10 --dry-run
```

Remove `--dry-run` to run the task. The smoke check uses at most two inference
requests; the pilot's campaign and durable task attempt budgets remain enforced.
`experiments/subscription_smoke.py` separately exercises the full Reticle controller
and its real write/read/finish tools in a fresh workspace, with a five-attempt cap.
Its session journal, requests, and verification report remain under `.runtime`.
Complete browser sign-in yourself and allow plan usage for **Reticle Harness**.
Run login again to reauthorize the current registration, or use `login --new-account`
to register a different account/workspace. Only one registration is active at a
time. `--no-browser` prints a fresh authorization URL for manual opening.

Credentials are stored outside the repository under `%LOCALAPPDATA%/reticle/chatgpt`
on Windows, encrypted with user-scoped DPAPI. Run authentication and the pilot
as the same Windows user. Unix storage is `~/.config/reticle/chatgpt` with private
file permissions. Refreshes are serialized; rotating tokens are saved atomically.
API keys and `.env` provider settings are not used by this provider. You can
disconnect Reticle or adjust its usage allowance in ChatGPT Settings.

Usage shares your existing ChatGPT plan limits. USD billing is unknown, rather
than reported as zero; `--cost-ceiling-usd` is rejected for this route. The
[subscription preview](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
requires streaming, `store: false`, and client-supplied history. It does not support
an output-token cap, so `--max-tokens` is not sent. Inference attempts are not
automatically retried after a stream failure, since they may have consumed usage.
The adapter translates Reticle's system messages to developer messages and groups
its function tools in a namespace. Hosted tools are not enabled. This integration
is for the current pilot runner; the older `reticle run` CLI uses its existing client.

Offline protocol tests:

```powershell
& ./.runtime/subscription-venv/Scripts/python.exe -m unittest discover -s tests -p test_chatgpt_subscription.py -v
```

From the repo root (see the docstring at the top of
[experiments/p6_pilot/run_pilot.py](experiments/p6_pilot/run_pilot.py) for client, backend,
and arm options):

```
python experiments/p6_pilot/run_pilot.py --client gold --run-name gold-check
python experiments/p6_pilot/run_pilot.py --client openrouter --models qwen/qwen3.5-9b \
    --provider qwen/qwen3.5-9b=venice --tasks humanize-329 --run-name pilot-a \
    --max-total-calls 30 --dry-run
```
