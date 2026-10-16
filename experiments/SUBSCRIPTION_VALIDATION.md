# ChatGPT subscription integration validation

Date: 2026-10-01. Branch: `experiment/chatgpt-subscription`.

The harness registered **Reticle Harness** through the official dynamic public-client
OAuth flow. Identity signature, issuer, audience, expiry, nonce, and plan scope were
validated. Windows user-scoped DPAPI encryption was verified by a write/decrypt
round trip, with no plaintext credential value in the stored bytes.

Live checks using the account's available `gpt-5.6-sol` model:

- Direct adapter: `ping` function call, local result, and follow-up acknowledgment passed.
- Full Reticle controller: wrote `ready.txt`, read it back, and called `finish`.
  Independent file-content check passed (`subscription-ok` followed by one LF).
  Three model responses, three provider attempts, and three tool actions; no errors,
  pending budget reservations, or outstanding operations in the task budget report.
  Reported usage: 3,634 input tokens and 84 output tokens. No provider-reported USD cost.

The live route sends completed output items through `response.output_item.done`
but may leave the terminal `response.completed.output` array empty. The adapter
now assembles those completed items and waits for the terminal success event before
exposing tool calls. A regression test covers this observed behavior.

Offline validation: 8 subscription tests, 21 pilot-guard tests, and 5 controller tests
passed. `git diff --check` passed. The broad suite ran 437 tests before the additional
stream-envelope regression test, with four skips and two failures outside changed code:

- `test_native_control.NativeControlTests.test_a_failed_init_check_kills_the_cli_at_once`:
  CLI wall time was 60.1 seconds against a less-than-45-second assertion.
- `test_run_card.ExpansionTests.test_treatment_cards_plan_the_runner_hashes_and_keep_the_incumbent`,
  card 013: its stored status is `completed`, while the test expects no execution blockers.

The integration does not change those tests or historical experiment cards. No repair
benchmark was run. Session evidence and raw request/response logs for the live control
are in the ignored `.runtime/subscription-smoke-*` directory. Tokens are stored only
in protected application storage outside the repository.
