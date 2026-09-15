"""Diagnostic-only context policy replay at a durable event checkpoint."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Dict, List, Mapping, Optional

from reticle.context.baseline import BaselineContextPolicy, ContextPolicy, TranscriptStore
from reticle.runtime.contracts import TaskEnvelope
from reticle.runtime.session import LocalRuntime


@dataclass(frozen=True)
class PolicyComparison:
    name: str
    policy_version: str
    request_artifact_id: str
    request_hash: str
    request_bytes: int
    over_budget: bool
    visible_items: List[Dict[str, Any]]
    omitted_items: List[Dict[str, Any]]
    retrieval_entry_points: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContextComparison:
    checkpoint_sequence: int
    max_context_bytes: int
    transcript_messages: int
    policies: List[PolicyComparison]
    comparison_artifact_id: str
    scratch_state: str = "current_at_replay_time"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _retrieval_entry_points(
    policy: BaselineContextPolicy,
    transcript: List[Dict[str, Any]],
    omitted_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    omitted_units = {
        int(item["unit_index"])
        for item in omitted_items
        if item.get("kind") == "transcript_unit" and isinstance(item.get("unit_index"), int)
    }
    entries: List[Dict[str, Any]] = []
    for unit_index, unit in enumerate(policy._paired_units(transcript)):
        if unit_index not in omitted_units:
            continue
        for message in unit:
            if message.get("role") != "tool":
                continue
            output = message.get("_reticle_output")
            artifact_id = message.get("_reticle_artifact_id")
            entry: Dict[str, Any] = {"unit_index": unit_index}
            if isinstance(output, dict) and output.get("handle"):
                entry.update({
                    "output_handle": output["handle"],
                    "read": f'read_output(id="{output["handle"]}")',
                    "search": f'search_output(id="{output["handle"]}", query="...")',
                })
            if isinstance(artifact_id, str):
                entry["transcript_artifact_id"] = artifact_id
            entries.append(entry)
    return entries


def compare_context_at_checkpoint(
    runtime: LocalRuntime,
    task: TaskEnvelope,
    policies: Mapping[str, ContextPolicy],
    tools: List[Dict[str, Any]],
    max_context_bytes: int,
    *,
    checkpoint_sequence: Optional[int] = None,
) -> ContextComparison:
    """Replay policy rendering against one transcript cursor and persist the comparison.

    Rendering may append context-manifest evidence, but this function never calls a model or
    dispatches a tool. Current scratch pins are labeled as such because S2 owns full task-state
    checkpoint reconstruction.
    """
    if not policies:
        raise ValueError("At least one context policy is required")
    if checkpoint_sequence is None:
        checkpoint = runtime.load_checkpoint()
        if checkpoint is None:
            raise ValueError("A checkpoint is required for context comparison")
        checkpoint_sequence = int(checkpoint["last_event_sequence"])
    events = runtime.journal.read_all()
    latest = events[-1].sequence if events else 0
    if checkpoint_sequence < 0 or checkpoint_sequence > latest:
        raise ValueError(f"Checkpoint sequence {checkpoint_sequence} is outside journal range 0-{latest}")

    transcript = TranscriptStore(runtime).load(as_of_sequence=checkpoint_sequence)
    comparisons: List[PolicyComparison] = []
    for name, selected_policy in policies.items():
        built = selected_policy.build(runtime, task, transcript, tools, max_context_bytes)
        renderer = selected_policy if isinstance(selected_policy, BaselineContextPolicy) else BaselineContextPolicy()
        comparisons.append(PolicyComparison(
            name=name,
            policy_version=built.manifest.policy_version,
            request_artifact_id=built.manifest.materialized_request_artifact_id,
            request_hash=built.manifest.materialized_request_hash,
            request_bytes=built.manifest.request_bytes,
            over_budget=built.over_budget,
            visible_items=built.manifest.selected_items,
            omitted_items=built.manifest.omitted_items,
            retrieval_entry_points=_retrieval_entry_points(
                renderer, transcript, built.manifest.omitted_items
            ),
        ))

    payload_without_artifact = {
        "checkpoint_sequence": checkpoint_sequence,
        "max_context_bytes": max_context_bytes,
        "transcript_messages": len(transcript),
        "policies": [item.to_dict() for item in comparisons],
        "scratch_state": "current_at_replay_time",
    }
    event_id = runtime.journal.new_event_id()
    artifact = runtime.artifacts.put(
        json.dumps(payload_without_artifact, sort_keys=True, ensure_ascii=False).encode("utf-8"),
        "application/json",
        event_id,
        labels=["context-comparison", "controller-only"],
    )
    runtime.journal.append(
        "context_comparison",
        {"artifact_id": artifact.artifact_id, **payload_without_artifact},
        event_id=event_id,
    )
    return ContextComparison(
        checkpoint_sequence=checkpoint_sequence,
        max_context_bytes=max_context_bytes,
        transcript_messages=len(transcript),
        policies=comparisons,
        comparison_artifact_id=artifact.artifact_id,
    )
