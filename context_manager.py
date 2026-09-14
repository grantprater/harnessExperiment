"""Context Evaporator & Epistemic Working Memory Manager.

Implements Pillar III from ARCHITECTURE.md:
1. Predictive Coding & Epistemic Commitments:
   - Tracks predictions made before state inspections and tool actuations.
2. Zero-Surprise Evaporation:
   - When an exploratory read confirms a negative hypothesis or matches prediction,
     the multi-thousand-token tool payload is evaporated into a 1-line belief update.
3. Dead-End & False-Lead Pruning:
   - Zero-match searches, discarded candidate files, and exploratory dead ends
     are compacted to prevent context pollution.
4. Active Working-Memory Compactor:
   - Keeps working memory crisp and bounded across long multi-turn trajectories.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class EpistemicCommitment:
    step: int
    intent: str
    expected_delta: str
    tool: str
    args: Dict[str, Any]
    observed_result: str = ""
    surprise_detected: bool = False
    distilled_belief: str = ""


class WorkingMemoryManager:
    """Manages conversational context with active evaporation and pruning."""

    def __init__(self, max_working_tokens: int = 24000):
        self.max_working_tokens = max_working_tokens
        self.messages: List[Dict[str, Any]] = []
        self.commitments: List[EpistemicCommitment] = []
        self.evaporated_token_savings: int = 0

    def add_system(self, content: str):
        self.messages.append({"role": "system", "content": content})

    def add_user(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: Optional[str], tool_calls: Optional[List[Dict[str, Any]]] = None):
        msg: Dict[str, Any] = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def record_commitment(self, intent: str, expected_delta: str, tool: str, args: Dict[str, Any]) -> EpistemicCommitment:
        step = len(self.commitments) + 1
        commit = EpistemicCommitment(
            step=step,
            intent=intent,
            expected_delta=expected_delta,
            tool=tool,
            args=args
        )
        self.commitments.append(commit)
        return commit

    def add_tool_result(
        self,
        tool_call_id: str,
        tool_name: str,
        raw_output: str,
        can_evaporate: bool = False,
        evaporation_summary: Optional[str] = None
    ):
        """Append a tool observation, optionally evaporating large payload if predicted."""
        output_len = len(raw_output)

        if can_evaporate and output_len > 300:
            summary = evaporation_summary or f"[Evaporated {tool_name} observation: {output_len} chars -> state confirmed]"
            saved = output_len - len(summary)
            self.evaporated_token_savings += max(0, saved // 4)
            self.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": summary
            })
        else:
            self.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": raw_output
            })

    def evaporate_turn(self, message_index: int, summary: str) -> bool:
        """Evaporate an earlier tool observation into a compact summary."""
        if message_index < 0 or message_index >= len(self.messages):
            return False

        target = self.messages[message_index]
        if target.get("role") != "tool":
            return False

        old_len = len(target.get("content", ""))
        target["content"] = f"[Evaporated: {summary}]"
        new_len = len(target["content"])
        self.evaporated_token_savings += max(0, (old_len - new_len) // 4)
        return True

    def prune_dead_ends(self) -> int:
        """Scan tool history and compact unhelpful search/inspection dead ends."""
        pruned_count = 0
        for i, msg in enumerate(self.messages):
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                # Pattern: Empty search matches
                if "Matches: 0;" in content or "0 matches" in content:
                    if len(content) > 120:
                        self.evaporate_turn(i, "Search yielded 0 matches across repository.")
                        pruned_count += 1
                # Pattern: Out-of-mode errors or invalid range attempts
                elif "ValueError: Observation not available in assigned mode" in content:
                    if len(content) > 100:
                        self.evaporate_turn(i, "Action rejected: tool unavailable in active mode.")
                        pruned_count += 1
        return pruned_count

    def get_messages_for_llm(self) -> List[Dict[str, Any]]:
        """Return the current pruned and compacted messages."""
        return list(self.messages)

    def stats(self) -> Dict[str, Any]:
        raw_chars = sum(len(m.get("content", "")) for m in self.messages)
        return {
            "total_messages": len(self.messages),
            "current_char_count": raw_chars,
            "approx_current_tokens": raw_chars // 4,
            "evaporated_tokens_saved": self.evaporated_token_savings,
            "commitments_recorded": len(self.commitments)
        }
