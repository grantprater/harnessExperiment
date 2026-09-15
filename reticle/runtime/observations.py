"""Shared full, region, outline, and search observation views."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import List, Optional

from reticle.runtime.session import LocalRuntime
from reticle.storage.artifacts import ArtifactEnvelope


OBSERVATION_MODES = {"full", "region", "outline", "search"}


@dataclass(frozen=True)
class ObservationView:
    source: str
    mode: str
    content: bytes
    raw_artifact: ArtifactEnvelope
    view_artifact: ArtifactEnvelope
    rendering: dict
    exact: bool

    def preview(self, limit: int = 2_000) -> str:
        text = self.content[:limit].decode("utf-8", errors="replace")
        if len(self.content) > limit:
            text += (
                f"\n[truncated: {len(self.content) - limit} bytes omitted; "
                f"exact view: {self.view_artifact.artifact_id}]"
            )
        return text


class ObservationService:
    def __init__(self, runtime: LocalRuntime):
        self.runtime = runtime

    def _source(self, source: str, source_kind: str) -> tuple[bytes, ArtifactEnvelope]:
        if source_kind == "workspace":
            observation, artifact = self.runtime.observe_file(source)
            return observation.content, artifact
        if source_kind == "artifact":
            read = self.runtime.scratch.read(source)
            return self.runtime.artifacts.read(read.artifact.artifact_id), read.artifact
        raise ValueError(f"Unsupported observation source kind: {source_kind}")

    @staticmethod
    def _outline(text: str) -> str:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return "\n".join(
                f"L{number}: {line.strip()}"
                for number, line in enumerate(text.splitlines(), 1)
                if line.lstrip().startswith(("#", "class ", "def ", "async def "))
            )
        entries: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                entries.append(f"L{node.lineno}: {kind} {node.name}")
        return "\n".join(sorted(entries, key=lambda entry: int(entry.split(":", 1)[0][1:])))

    def observe(
        self,
        source: str,
        mode: str = "full",
        *,
        source_kind: str = "workspace",
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        query: Optional[str] = None,
    ) -> ObservationView:
        if mode not in OBSERVATION_MODES:
            raise ValueError(f"Unsupported observation mode: {mode}")
        raw, raw_artifact = self._source(source, source_kind)
        text = raw.decode("utf-8", errors="replace")
        rendering = {"method": mode, "source_kind": source_kind}
        exact = mode == "full"
        if mode == "full":
            rendered = raw
        elif mode == "region":
            lines = text.splitlines(keepends=True)
            start = start_line or 1
            end = end_line if end_line is not None else len(lines)
            if start < 1 or end < start or end > len(lines):
                raise ValueError(f"Invalid line region L{start}-L{end} for {len(lines)} lines")
            rendered = "".join(lines[start - 1:end]).encode("utf-8")
            rendering.update({"start_line": start, "end_line": end})
        elif mode == "outline":
            rendered = self._outline(text).encode("utf-8")
        else:
            if not query:
                raise ValueError("Search observations require a non-empty query")
            matches = [
                f"L{number}: {line}"
                for number, line in enumerate(text.splitlines(), 1)
                if query in line
            ]
            rendered = "\n".join(matches).encode("utf-8")
            rendering["query"] = query
        if exact:
            view_artifact = raw_artifact
        else:
            event_id = self.runtime.journal.new_event_id()
            view_artifact = self.runtime.artifacts.put(
                rendered,
                "text/plain; charset=utf-8",
                event_id,
                parent_artifact_ids=[raw_artifact.artifact_id],
                labels=["observation-view", mode, source],
            )
            self.runtime.journal.append(
                "observation_view",
                {
                    "source_artifact_id": raw_artifact.artifact_id,
                    "view_artifact": view_artifact.to_dict(),
                    "rendering": rendering,
                },
                event_id=event_id,
            )
        return ObservationView(
            source, mode, rendered, raw_artifact, view_artifact, rendering, exact
        )
