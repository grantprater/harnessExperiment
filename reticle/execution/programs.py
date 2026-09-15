"""Versioned program registration and worker-based invocation."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any, Dict, Optional

from reticle._schema import SCHEMA_VERSION
from reticle.execution.backends import ExecutionRequest, ExecutionResult, TrustedLocalBackend
from reticle.runtime.session import LocalRuntime
from reticle.runtime.contracts import ToolResultEnvelope
from reticle.execution.controller import ExecutionController


@dataclass(frozen=True)
class ProgramManifest:
    name: str
    entry_point: str
    source_artifact_id: str
    reference_version: int
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ProgramRegistry:
    """Registration parses source metadata but never evaluates generated code."""

    def __init__(self, runtime: LocalRuntime):
        self.runtime = runtime

    def register(
        self,
        name: str,
        source: str | bytes,
        entry_point: str,
        expected_version: Optional[int] = None,
    ) -> ProgramManifest:
        raw = source.encode("utf-8") if isinstance(source, str) else source
        tree = ast.parse(raw.decode("utf-8"), filename=f"{name}.py")
        definitions = {
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if entry_point not in definitions:
            raise ValueError(
                f"Source does not define top-level entry point '{entry_point}'; "
                f"found {sorted(definitions)}"
            )
        event_id = self.runtime.journal.new_event_id()
        source_artifact = self.runtime.artifacts.put(
            raw,
            "text/x-python; charset=utf-8",
            event_id,
            labels=["program-source", name, entry_point],
        )
        reference = self.runtime.artifacts.update_reference(
            f"programs/{name}", source_artifact.artifact_id, expected_version
        )
        manifest = ProgramManifest(
            name=name,
            entry_point=entry_point,
            source_artifact_id=source_artifact.artifact_id,
            reference_version=reference.version,
        )
        self.runtime.journal.append(
            "program_registered",
            {"manifest": manifest.to_dict()},
            event_id=event_id,
        )
        return manifest

    def resolve(self, name: str, entry_point: Optional[str] = None) -> ProgramManifest:
        reference = self.runtime.artifacts.get_reference(f"programs/{name}")
        if reference is None:
            raise KeyError(f"Unknown program: {name}")
        source = self.runtime.artifacts.get_envelope(reference.artifact_id)
        candidates = [
            event.payload["manifest"] for event in self.runtime.journal.read_all()
            if event.kind == "program_registered"
            and event.payload["manifest"]["name"] == name
            and event.payload["manifest"]["source_artifact_id"] == source.artifact_id
        ]
        if not candidates:
            raise RuntimeError(f"Program manifest unavailable: {name}")
        value = candidates[-1]
        manifest = ProgramManifest(**value)
        if entry_point is not None and manifest.entry_point != entry_point:
            raise ValueError(
                f"Program '{name}' entry point is {manifest.entry_point}, not {entry_point}"
            )
        return manifest


@dataclass(frozen=True)
class ProgramRun:
    execution: ExecutionResult
    value: Any = None
    worker_error: Optional[Dict[str, Any]] = None
    tool_result: Optional[ToolResultEnvelope] = None


class ProgramRunner:
    def __init__(self, runtime: LocalRuntime, backend=None):
        self.runtime = runtime
        self.backend = backend or TrustedLocalBackend()
        self.registry = ProgramRegistry(runtime)

    def run(
        self,
        name: str,
        arguments: Dict[str, Any],
        timeout_seconds: float = 30,
        output_limit_bytes: int = 1_000_000,
    ) -> ProgramRun:
        manifest = self.registry.resolve(name)
        source = self.runtime.artifacts.read(manifest.source_artifact_id)
        isolated = bool(getattr(self.backend, "host_isolation", False))
        temp_parent = self.runtime.workspace.root if isolated else None
        temp_prefix = ".reticle-program-" if isolated else "reticle-program-"
        with tempfile.TemporaryDirectory(prefix=temp_prefix, dir=temp_parent) as temp_name:
            temp = Path(temp_name)
            source_path = temp / "program.py"
            result_path = temp / "result.json"
            source_path.write_bytes(source)
            worker_path = Path(__file__).with_name("worker.py")
            if isolated:
                staged_worker_path = temp / "worker.py"
                shutil.copyfile(worker_path, staged_worker_path)
                relative_temp = temp.relative_to(self.runtime.workspace.root)
                container_temp = PurePosixPath("/workspace") / relative_temp.as_posix()
                executable = "python"
                command_worker_path = container_temp / "worker.py"
                command_source_path = container_temp / "program.py"
                command_result_path = container_temp / "result.json"
            else:
                executable = __import__("sys").executable
                command_worker_path = worker_path
                command_source_path = source_path
                command_result_path = result_path
            request = ExecutionRequest(
                command=[
                    executable,
                    str(command_worker_path),
                    "--source", str(command_source_path),
                    "--entry-point", manifest.entry_point,
                    "--arguments", json.dumps(arguments),
                    "--result", str(command_result_path),
                ],
                working_directory=self.runtime.workspace.root,
                timeout_seconds=timeout_seconds,
                output_limit_bytes=output_limit_bytes,
                mutates_workspace=True,
            )
            record = ExecutionController(self.runtime, self.backend).execute(request)
            execution = record.execution
            tool_result = record.tool_result
            worker_result = None
            if result_path.exists():
                worker_result = json.loads(result_path.read_text(encoding="utf-8"))
            if worker_result and worker_result.get("status") == "success":
                return ProgramRun(
                    execution, value=worker_result.get("value"), tool_result=tool_result
                )
            return ProgramRun(execution, worker_error=worker_result, tool_result=tool_result)
