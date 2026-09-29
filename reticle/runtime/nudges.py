"""Harness messages the agent loop can inject between responses (agent-loop treatments, S6).

An intervention is asked after every response whose tool results (or the no-tool-call prompt) are in the
transcript; if it returns text, the controller appends it as a harness ("system") message after those results,
journals a ``harness_message`` event, and the next request carries it. The context manifest marks the message's
item with ``harness_message`` (name and version). No intervention runs unless one is passed to the controller.

``MidpointNudge`` (card 009's diagnostic-commitment idea, card 007's "budget exhausted without an edit"
mechanism): once per run, when the fraction of the response budget given (default one half) is spent and no
pre-existing source file has been edited (``reticle.runtime.source_edits``), it says so and asks for the single
most likely cause to be edited now and verified after. The text is fixed; only the share it names follows the
fraction ("Half" at 0.5).

``CommitmentNudge`` (card 021): once per run at the fraction, edits or not, it asks for a committed hypothesis and a
tested prediction through the commitment tools (``reticle.tools.commitment``), which the runner offers with it.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from reticle.runtime.session import LocalRuntime
from reticle.runtime.source_edits import SourceEditTracker


MIDPOINT_NUDGE_VERSION = "midpoint-nudge-v1"
MIDPOINT_NUDGE_TEMPLATE = (
    "{share} of the response budget is spent and no source file has been edited. "
    "State the single most likely cause and edit it now; verify after."
)


def midpoint_nudge_text(fraction: float = 0.5) -> str:
    return MIDPOINT_NUDGE_TEMPLATE.format(share="Half" if fraction == 0.5 else f"{fraction:.0%}")


class MidpointNudge:
    name = "midpoint"
    version = MIDPOINT_NUDGE_VERSION

    def __init__(self, tracker: SourceEditTracker, fraction: float = 0.5):
        if not 0 < fraction < 1:
            raise ValueError("the nudge fraction must be between 0 and 1")
        self.tracker, self.fraction = tracker, fraction
        self.text = midpoint_nudge_text(fraction)
        self.fired_after: Optional[int] = None
        self.edited_before: Optional[int] = None  # responses used when an edit was first seen, if before firing
        self._journal_checked = False

    def threshold(self, response_limit: int) -> int:
        """The number of responses after which the nudge is due."""
        return max(1, math.ceil(self.fraction * response_limit))

    def message_after_response(self, runtime: LocalRuntime, responses_used: int, response_limit: int) -> Optional[str]:
        if not self._journal_checked:  # once per run, also across controller invocations of one session
            self._journal_checked = True
            for event in runtime.journal.read_all():
                if event.kind == "harness_message" and event.payload.get("name") == self.name:
                    self.fired_after = event.payload.get("after_response")
        if self.fired_after is not None or self.edited_before is not None:
            return None
        if self.tracker.refresh() or self.tracker.edited:
            self.edited_before = responses_used
            return None
        if responses_used < self.threshold(response_limit) or responses_used >= response_limit:
            return None
        self.fired_after = responses_used
        return self.text

    def record(self) -> Dict[str, Any]:
        return {"fired": self.fired_after is not None, "after_response": self.fired_after,
                "edit_seen_after_response": self.edited_before, "fraction": self.fraction, "version": self.version}


# Card 021 (the owner's "intuition" idea, first form): at the fraction of the response budget, whether or not a source
# file was edited, ask the model to commit to its leading hypothesis and a concrete prediction, test the prediction,
# and record the outcome, through the commitment tools (reticle.tools.commitment). Unconditional, unlike the midpoint
# nudge, because the commitment is also the card's instrument: conditioning it on "no edit yet" would leave the
# prediction record missing exactly in the runs that had already committed to a fix.
COMMIT_NUDGE_VERSION = "commit-nudge-v1"
# The first draft ("... Commit to your leading hypothesis now: call commit_hypothesis ...") was ignored in both host
# smoke replies (experiments/session_harness/smoke-021-host/commit-reply, *-draft): the model kept exploring. v1 asks
# for the call in this reply, before any other tool call, and names what comes in the next reply.
COMMIT_NUDGE_TEMPLATE = (
    "{share} of the response budget is spent. This reply must start with a commit_hypothesis call, before any other "
    "tool call: the file, function, line and mechanism you believe cause the reported behavior, one specific "
    "observation you will make next (a command or a read), and exactly what it will show if you are right. Make "
    "that observation in the same reply. In your next reply, call record_observation with what it showed and "
    "whether it matched; if it did not, say what surprised you and revise the hypothesis. Then edit the most likely "
    "cause and verify the fix."
)


def commit_nudge_text(fraction: float = 0.5) -> str:
    return COMMIT_NUDGE_TEMPLATE.format(share="Half" if fraction == 0.5 else f"{fraction:.0%}")


class CommitmentNudge:
    """Once per run, when the fraction of the response budget is spent (edits or not), the commitment message."""

    name = "commit"
    version = COMMIT_NUDGE_VERSION

    def __init__(self, fraction: float = 0.5):
        if not 0 < fraction < 1:
            raise ValueError("the nudge fraction must be between 0 and 1")
        self.fraction = fraction
        self.text = commit_nudge_text(fraction)
        self.fired_after: Optional[int] = None
        self._journal_checked = False

    def threshold(self, response_limit: int) -> int:
        return max(1, math.ceil(self.fraction * response_limit))

    def message_after_response(self, runtime: LocalRuntime, responses_used: int, response_limit: int) -> Optional[str]:
        if not self._journal_checked:  # once per run, also across controller invocations of one session
            self._journal_checked = True
            for event in runtime.journal.read_all():
                if event.kind == "harness_message" and event.payload.get("name") == self.name:
                    self.fired_after = event.payload.get("after_response")
        if self.fired_after is not None:
            return None
        if responses_used < self.threshold(response_limit) or responses_used >= response_limit:
            return None
        self.fired_after = responses_used
        return self.text

    def record(self) -> Dict[str, Any]:
        return {"fired": self.fired_after is not None, "after_response": self.fired_after,
                "fraction": self.fraction, "version": self.version}
