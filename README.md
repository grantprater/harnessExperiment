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

From the repo root (see the docstring at the top of
[experiments/p6_pilot/run_pilot.py](experiments/p6_pilot/run_pilot.py) for client, backend,
and arm options):

```
python experiments/p6_pilot/run_pilot.py --client gold --run-name gold-check
python experiments/p6_pilot/run_pilot.py --client openrouter --models qwen/qwen3.5-9b \
    --provider qwen/qwen3.5-9b=venice --tasks humanize-329 --run-name pilot-a \
    --max-total-calls 30 --dry-run
```
