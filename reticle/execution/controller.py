"""Journaled execution dispatch with read concurrency and serialized mutation."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import threading
from typing import Optional
from uuid import uuid4

from reticle.execution.backends import ExecutionRequest, ExecutionResult
from reticle.runtime.contracts import ToolResultEnvelope
from reticle.runtime.session import LocalRuntime


@dataclass(frozen=True)
class ExecutionRecord:
    execution: ExecutionResult
    tool_result: ToolResultEnvelope


class _ReadWriteGate:
    def __init__(self):
        self.condition = threading.Condition()
        self.readers = 0
        self.writer = False
        self.waiting_writers = 0

    def enter(self, mutating: bool) -> None:
        with self.condition:
            if mutating:
                self.waiting_writers += 1
                try:
                    while self.writer or self.readers:
                        self.condition.wait()
                    self.writer = True
                finally:
                    self.waiting_writers -= 1
            else:
                while self.writer or self.waiting_writers:
                    self.condition.wait()
                self.readers += 1

    def exit(self, mutating: bool) -> None:
        with self.condition:
            if mutating:
                self.writer = False
            else:
                self.readers -= 1
            self.condition.notify_all()


class ExecutionController:
    """Record intent/outcome and keep mutations exclusive for one workspace."""

    _gates = {}
    _gates_lock = threading.Lock()

    @classmethod
    def _gate_for(cls, runtime: LocalRuntime) -> _ReadWriteGate:
        key = str(runtime.session_dir)
        with cls._gates_lock:
            return cls._gates.setdefault(key, _ReadWriteGate())

    @classmethod
    @contextmanager
    def workspace_boundary(cls, runtime: LocalRuntime, mutating: bool):
        gate = cls._gate_for(runtime)
        gate.enter(mutating)
        try:
            yield
        finally:
            gate.exit(mutating)

    def __init__(self, runtime: LocalRuntime, backend):
        self.runtime = runtime
        self.backend = backend
        self._gate = self._gate_for(runtime)

    def execute(
        self,
        request: ExecutionRequest,
        *,
        operation_id: Optional[str] = None,
        call_id: Optional[str] = None,
        cancellation_event: Optional[threading.Event] = None,
    ) -> ExecutionRecord:
        operation_id = operation_id or f"exec-{uuid4().hex}"
        call_id = call_id or f"call-{uuid4().hex}"
        self.runtime.begin_action(
            operation_id,
            "execute",
            {
                "command": request.command,
                "backend": self.backend.name,
                "mutates_workspace": request.mutates_workspace,
            },
        )
        self._gate.enter(request.mutates_workspace)
        try:
            before = self.runtime.workspace.revision()
            self.runtime.mark_action_dispatched(
                operation_id, "workspace_mutation" if request.mutates_workspace else "read_only"
            )
            execution = self.backend.run(request, cancellation_event)
            after = self.runtime.workspace.revision()
            tool_result = self.runtime.record_tool_result(
                operation_id=operation_id,
                call_id=call_id,
                status=execution.status,
                workspace_revision_before=before,
                workspace_revision_after=after,
                stdout=execution.stdout,
                stderr=execution.stderr,
                exit_code=execution.exit_code,
                duration_ms=execution.duration_ms,
                error_kind=execution.error_kind,
                retry_hint=(
                    "Retry only after changing the program, limits, or environment"
                    if execution.status in {"error", "timeout"} else None
                ),
            )
            return ExecutionRecord(execution, tool_result)
        finally:
            self._gate.exit(request.mutates_workspace)
