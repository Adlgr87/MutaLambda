"""Cost ledger — single source of truth for optimization cost accounting.

Every cost-relevant event in MutaLambda is recorded here as a ledger entry:

* ``log_llm(...)``  — one LLM call (tokens + estimated USD).  Intercepted
  centrally inside the ``LLMBackend`` wrapper (rule 2: no scattered calls),
  so every provider path feeds the ledger.
* ``log_eval(...)`` — one evaluation episode (wall seconds, optional GPU
  seconds converted to USD at ``cost_ledger.gpu_hour_usd``).  Intercepted in
  ``EvaluationService.evaluate_batch`` (sandbox) and ``regression_gate``.
* ``log_event(...)`` — lever decisions (gate stop reasons, cache hits, bandit
  pulls) for the ROI report.

The ledger is a thread-safe in-process singleton.  ``dump_json(path)`` writes
a self-contained, schema-stable JSON document (``schema_version: 1``) that
``roi_report.json`` (Fase 3) aggregates.  It is pure observability: a
disabled flag or any internal error degrades to a no-op and NEVER breaks a
run.  All interception sites wrap the call in try/except as a second layer.

Acceptance hook (Fase 0): ``dump_json`` output must be valid JSON with
``totals`` matching the sum of its entries.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from optimization_flags import get_optimization_flags

__all__ = [
    "CostLedger",
    "get_cost_ledger",
    "record_llm_call",
    "record_eval",
    "record_event",
]

SCHEMA_VERSION = 1
DEFAULT_DUMP_RELPATH = Path(".mutalambda") / "cost_ledger.json"


class CostLedger:
    """Append-only, thread-safe cost ledger (singleton via ``get_cost_ledger``)."""

    def __init__(self, enabled: bool = True, gpu_hour_usd: float = 0.5) -> None:
        self._lock = threading.Lock()
        self._entries: List[Dict[str, Any]] = []
        self.enabled = enabled
        self.gpu_hour_usd = float(gpu_hour_usd)

    # ── Recording ────────────────────────────────────────────────────────
    def _append(self, entry_kind: str, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._entries.append({"ts": time.time(), "kind": entry_kind, **payload})

    def log_llm(
        self,
        *,
        kind: str = "llm_call",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        model: str = "",
        backend: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record one LLM call (intercepted in the LLM wrapper)."""
        self._append(
            "llm",
            {
                "call_kind": kind,
                "prompt_tokens": int(prompt_tokens),
                "completion_tokens": int(completion_tokens),
                "cost_usd": float(cost_usd),
                "model": model,
                "backend": backend,
                "extra": extra or {},
            },
        )

    def log_eval(
        self,
        *,
        kind: str = "eval",
        seconds: float = 0.0,
        gpu_seconds: float = 0.0,
        cost_usd: float = 0.0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record one evaluation episode.

        ``gpu_seconds`` is converted to USD at ``gpu_hour_usd`` and added to
        ``cost_usd`` so ``totals()`` always reports the true combined cost.
        """
        gpu_cost = float(gpu_seconds) / 3600.0 * self.gpu_hour_usd
        self._append(
            "eval",
            {
                "eval_kind": kind,
                "seconds": float(seconds),
                "gpu_seconds": float(gpu_seconds),
                "gpu_cost_usd": gpu_cost,
                "cost_usd": float(cost_usd) + gpu_cost,
                "extra": extra or {},
            },
        )

    def log_event(self, *, kind: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """Record a lever decision / decision reason (stop, flip, bandit...)."""
        self._append("event", {"event_kind": kind, "extra": extra or {}})

    # ── Aggregation ──────────────────────────────────────────────────────
    def entries(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._entries]

    def totals(self) -> Dict[str, Any]:
        llm_calls = 0
        prompt_tokens = 0
        completion_tokens = 0
        llm_cost = 0.0
        eval_count = 0
        eval_seconds = 0.0
        gpu_seconds = 0.0
        eval_cost = 0.0
        event_count = 0
        for entry in self.entries():
            kind = entry["kind"]
            if kind == "llm":
                llm_calls += 1
                prompt_tokens += entry.get("prompt_tokens", 0)
                completion_tokens += entry.get("completion_tokens", 0)
                llm_cost += entry.get("cost_usd", 0.0)
            elif kind == "eval":
                eval_count += 1
                eval_seconds += entry.get("seconds", 0.0)
                gpu_seconds += entry.get("gpu_seconds", 0.0)
                eval_cost += entry.get("cost_usd", 0.0)
            elif kind == "event":
                event_count += 1
        return {
            "llm": {
                "calls": llm_calls,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": round(llm_cost, 8),
            },
            "eval": {
                "count": eval_count,
                "seconds": round(eval_seconds, 6),
                "gpu_seconds": round(gpu_seconds, 6),
                "cost_usd": round(eval_cost, 8),
            },
            "events": event_count,
            "total_cost_usd": round(llm_cost + eval_cost, 8),
        }

    def dump_json(self, path: Optional[str | Path] = None) -> Path:
        """Write the ledger as a self-contained JSON document.

        Default path: ``cost_ledger.path`` flag, else ``.mutalambda/cost_ledger.json``.
        """
        if path is None:
            path = Path(get_optimization_flags().get("cost_ledger.path", "") or "")
            if not path:
                path = DEFAULT_DUMP_RELPATH
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": time.time(),
            "gpu_hour_usd": self.gpu_hour_usd,
            "totals": self.totals(),
            "entries": self.entries(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(document, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return path

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_ledger_singleton: Optional[CostLedger] = None
_ledger_lock = threading.Lock()


def _ledger_from_flags() -> CostLedger:
    flags = get_optimization_flags()
    return CostLedger(
        enabled=flags.enabled("cost_ledger.enabled", True),
        gpu_hour_usd=float(flags.get("cost_ledger.gpu_hour_usd", 0.5) or 0.5),
    )


def get_cost_ledger() -> CostLedger:
    """Process-wide ledger singleton (re-created after ``reset_cost_ledger``)."""
    global _ledger_singleton
    if _ledger_singleton is None:
        with _ledger_lock:
            if _ledger_singleton is None:
                _ledger_singleton = _ledger_from_flags()
    return _ledger_singleton


def reset_cost_ledger() -> None:
    """Drop the singleton (tests, or to re-read flags)."""
    global _ledger_singleton
    with _ledger_lock:
        _ledger_singleton = None


# ── Guarded interception helpers (never raise) ─────────────────────────────


def record_llm_call(
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
    model: str = "",
    backend: str = "",
    kind: str = "generate",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Ledger hook used by the LLM wrapper — swallows all errors."""
    try:
        ledger = get_cost_ledger()
        if not ledger.enabled:
            return
        ledger.log_llm(
            kind=kind,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            model=model,
            backend=backend,
            extra=extra,
        )
    except Exception:  # pragma: no cover - observability must not break runs
        pass


def record_eval(
    *,
    kind: str = "eval",
    seconds: float = 0.0,
    gpu_seconds: float = 0.0,
    cost_usd: float = 0.0,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Ledger hook used by evaluation / gate code — swallows all errors."""
    try:
        ledger = get_cost_ledger()
        if not ledger.enabled:
            return
        ledger.log_eval(
            kind=kind, seconds=seconds, gpu_seconds=gpu_seconds, cost_usd=cost_usd, extra=extra
        )
    except Exception:  # pragma: no cover - observability must not break runs
        pass


def record_event(kind: str, extra: Optional[Dict[str, Any]] = None) -> None:
    """Ledger hook for lever decisions — swallows all errors."""
    try:
        ledger = get_cost_ledger()
        if not ledger.enabled:
            return
        ledger.log_event(kind=kind, extra=extra)
    except Exception:  # pragma: no cover - observability must not break runs
        pass
