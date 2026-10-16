# Autumn 10k policy comparison

The sweep finished in 26 minutes 49 seconds. No usable pair met the 10,000-token
soft target. Three attempts generated visually acceptable pairs and passed the
independent file/palette checks; their total reported tokens were 175,192,
200,356 and 217,024. Each still reached the model-call limit on at least one task.

Six attempts encountered model-service errors. The original adapter logged only
`Subscription stream failed: error`, so the saved evidence does not establish
whether these were quota, capacity, request-validation or another service error.
All three pressure-v4 trials were affected, making policy rankings unreliable.
No policy is promoted from this comparison.

| Attempt | Policy | Total input + output tokens | Pair visually accepted | Model tasks finished |
| --- | --- | ---: | --- | --- |
| variant-00-trial-01 | minimal | 217,024 | yes | no |
| variant-01-trial-00 | decision | 175,192 | yes | no |
| variant-00-trial-00 | minimal | 200,356 | yes | no |
| variant-01-trial-01 | decision | unknown (incomplete reporting) | no | no |
| variant-02-trial-01 | pressure-v4 | unknown (incomplete reporting) | no | no |
| variant-02-trial-00 | pressure-v4 | unknown (incomplete reporting) | no | no |
| variant-01-trial-02 | decision | unknown (incomplete reporting) | no | no |
| variant-00-trial-02 | minimal | unknown (incomplete reporting) | no | no |
| variant-02-trial-02 | pressure-v4 | unknown (incomplete reporting) | no | no |

## What the trace shows

The useful trials frequently reread STYLE.md, the pinned style profile and the
same generation sources; they repeatedly searched history or fetched truncated
pages. Several did so even after generating the requested asset or passing its
palette check. Compact observations alone did not eliminate unnecessary model
round trips. Context loss and repeated restoration are plausible contributors,
but this comparison does not isolate their effects.

The soft target was visible to the model, not enforced as a hard provider-token
budget. Generating under 10k remains unproven. A next policy trial should retain
completion/check evidence in compact task state, distinguish retrieval from
progress, avoid duplicate reads while files are unchanged, and expose fewer tool
schemas. Add checkpoint-based compaction as a separate cache-friendly treatment.

## Reporting and review

`gallery.html` shows generated images. `evaluation.json` in each attempt records
assistant visual review under the fixed cozy-autumn-visual-v1 rubric. Composition
was allowed to vary. Missing pairs were rejected. These are separate judgments
from automated palette checks and model finish declarations, not human review.

`comparison-reviewed.json` adds those reviews and correctly distinguishes model
task completion from runner completion. The original progress, summaries,
comparison, usage, prompts and generated assets remain unchanged. Unknown failed
request usage is not replaced with zero, so aggregate tokens per accepted attempt
remain unknown where reporting is incomplete.

Future runner results now mark model-call-limit stops incomplete and stop a trial
on a model-service error. The subscription adapter now preserves known error codes
and numeric reset fields, including UTC timestamps with seconds, while excluding
raw error messages. These changes were tested offline; no additional model trial
has been launched.
