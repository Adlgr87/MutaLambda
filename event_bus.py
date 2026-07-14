"""Event bus for evolution observability (ML-UI04).

The dashboard and CLI consume events; they should not inspect mutable
island populations directly during a live run.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

# Canonical event names (workflow §12)
GENERATION_STARTED = "GenerationStarted"
CANDIDATE_GENERATED = "CandidateGenerated"
CANDIDATE_EVALUATED = "CandidateEvaluated"
CANDIDATE_PROMOTED = "CandidatePromoted"
CANDIDATE_REJECTED = "CandidateRejected"
MIGRATION_APPLIED = "MigrationApplied"
CHECKPOINT_SAVED = "CheckpointSaved"
GENERATION_COMPLETED = "GenerationCompleted"
LLM_CALL = "LLMCall"
RUN_STARTED = "RunStarted"
RUN_COMPLETED = "RunCompleted"
ISLAND_FAILED = "IslandFailed"
COMMAND = "Command"  # pause / resume / stop / inject_hint / ...


@dataclass(frozen=True)
class EvolutionEvent:
    """Immutable event envelope."""

    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    run_id: str = ""
    generation: int = -1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "generation": self.generation,
        }


EventHandler = Callable[[EvolutionEvent], None]


class EventBus:
    """Thread-safe pub/sub bus with a bounded in-memory history."""

    def __init__(self, history_size: int = 2000):
        self._lock = threading.RLock()
        self._handlers: List[EventHandler] = []
        self._history: Deque[EvolutionEvent] = deque(maxlen=max(1, history_size))
        self._counts: Dict[str, int] = {}

    def subscribe(self, handler: EventHandler) -> None:
        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        with self._lock:
            self._handlers = [h for h in self._handlers if h is not handler]

    def publish(self, event: EvolutionEvent) -> None:
        with self._lock:
            self._history.append(event)
            self._counts[event.name] = self._counts.get(event.name, 0) + 1
            handlers = list(self._handlers)
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                # Never let a consumer crash the evolution loop.
                pass

    def emit(
        self,
        name: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        run_id: str = "",
        generation: int = -1,
    ) -> EvolutionEvent:
        event = EvolutionEvent(
            name=name,
            payload=dict(payload or {}),
            run_id=run_id,
            generation=generation,
        )
        self.publish(event)
        return event

    def history(
        self,
        name: Optional[str] = None,
        *,
        limit: int = 100,
    ) -> List[EvolutionEvent]:
        with self._lock:
            items = list(self._history)
        if name:
            items = [e for e in items if e.name == name]
        if limit > 0:
            items = items[-limit:]
        return items

    def counts(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self._counts.clear()


class CommandQueue:
    """Thread-safe control channel for pause/resume/stop/HITL (ML-UI03)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._commands: Deque[Dict[str, Any]] = deque()
        self.paused: bool = False
        self.stop_requested: bool = False

    def push(self, command: str, **payload: Any) -> None:
        with self._lock:
            cmd = {"command": command, **payload}
            if command == "pause":
                self.paused = True
            elif command == "resume":
                self.paused = False
            elif command == "stop":
                self.stop_requested = True
            self._commands.append(cmd)

    def drain(self) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._commands)
            self._commands.clear()
            return items

    def wait_if_paused(self, poll_sec: float = 0.05) -> None:
        while True:
            with self._lock:
                if not self.paused or self.stop_requested:
                    return
            time.sleep(poll_sec)
