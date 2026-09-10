"""Fase 1 — Headroom cost layer: LLM pipeline facade.

Composes the levers into one safe path for LLM-driven mutation/redesign:

    O1  compress error/traceback blocks before prompt assembly,
    O3  stub large function bodies + bounded headroom_retrieve round trips,
    A1  JSON-schema structured output (op_type/location/unified_diff/rationale)
        with one repair round, per-op diff application, and a legacy fallback
        (free-prose code extraction) so a run is NEVER broken,
    A3  batching (N mutations per single call) + stats for the cost-aware
        bandit (reward = Δfitness / tokens).

Every stage is flag-gated (config/optimization.yaml):
    headroom.json_schema_output.enabled   → A1 structured contract
    headroom.ast_stubs.enabled            → O3 stubs + retrieval tool
    headroom.smart_crusher.enabled        → O1 trace compression
    headroom.batching.enabled/size        → A3 batching
With all flags off, :func:`llm_mutation_candidate` reproduces the legacy
behaviour exactly (prompt → free-prose code → extraction).

Every call is recorded in the cost ledger as a ``headroom_llm`` event with
before/after token estimates and op outcomes (rule 4).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

__all__ = [
    "HeadroomStats",
    "headroom_available",
    "llm_mutation_candidate",
    "llm_redesign_candidate",
]

LLMFn = Callable[[str], str]

MAX_RETRIEVAL_ROUNDS = 2


def headroom_available() -> bool:
    """True when the ``headroom`` package can be imported."""
    try:
        import headroom  # noqa: F401

        return True
    except Exception:
        return False


@dataclass
class HeadroomStats:
    mode: str = "legacy"
    prompt_chars: int = 0
    response_chars: int = 0
    tokens_in_est: int = 0
    tokens_out_est: int = 0
    ops_requested: int = 1
    ops_total: int = 0
    ops_applied: int = 0
    ops_failed: int = 0
    retrieval_rounds: int = 0
    schema_valid: bool = False
    repaired: bool = False
    fallback: bool = False
    trace_ratio: float = 1.0
    stub_count: int = 0
    extras: Dict[str, Any] = field(default_factory=dict)

    @property
    def tokens_total(self) -> int:
        return self.tokens_in_est + self.tokens_out_est

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "mode": self.mode,
            "prompt_chars": self.prompt_chars,
            "response_chars": self.response_chars,
            "tokens_in_est": self.tokens_in_est,
            "tokens_out_est": self.tokens_out_est,
            "ops_requested": self.ops_requested,
            "ops_total": self.ops_total,
            "ops_applied": self.ops_applied,
            "ops_failed": self.ops_failed,
            "retrieval_rounds": self.retrieval_rounds,
            "schema_valid": self.schema_valid,
            "repaired": self.repaired,
            "fallback": self.fallback,
            "trace_ratio": round(self.trace_ratio, 4),
            "stub_count": self.stub_count,
        }
        d.update(self.extras)
        return d


def _flags():
    from optimization_flags import get_optimization_flags

    return get_optimization_flags()


def _estimate_tokens(text: str) -> int:
    try:
        from llm_backend import _estimate_tokens as _est

        return _est(text or "")
    except Exception:
        return max(1, len(text or "") // 4)


def _trace_ratio(text: str, compressed: str) -> float:
    if not text:
        return 1.0
    return len(compressed) / len(text)


def _retrieval_loop(llm_fn: LLMFn, prompt: str, store: Any, stats: HeadroomStats) -> str:
    """Bounded headroom_retrieve tool loop (O3), provider-agnostic."""
    from ast_stubs import parse_retrieve_calls, render_retrievals

    text = llm_fn(prompt)
    for _ in range(MAX_RETRIEVAL_ROUNDS):
        ids = parse_retrieve_calls(text)
        if not ids:
            return text
        stats.retrieval_rounds += 1
        retrieved = render_retrievals(store, ids)
        if not retrieved:
            return text
        text = llm_fn(prompt + retrieved + "\nCONTINUE: produce the final answer now.")
    return text


def _schema_call(
    llm_fn: LLMFn,
    prompt: str,
    stats: HeadroomStats,
    *,
    store: Any = None,
) -> tuple:
    """A1: structured call with one repair round.

    Returns ``(ops, raw_text)`` — *raw_text* is the last model response
    (kept for the legacy extraction safety net without an extra call).
    """
    from structured_ops import build_repair_prompt, parse_ops

    text = _retrieval_loop(llm_fn, prompt, store, stats) if store is not None else llm_fn(prompt)
    stats.response_chars += len(text)
    stats.tokens_out_est += _estimate_tokens(text)
    ops, errors = parse_ops(text)
    if errors:
        # Single repair round — never more (cost discipline).
        stats.repaired = True
        repair_prompt = build_repair_prompt(errors, prompt)
        stats.tokens_in_est += _estimate_tokens(repair_prompt)
        text = llm_fn(repair_prompt)
        stats.response_chars += len(text)
        stats.tokens_out_est += _estimate_tokens(text)
        ops, errors = parse_ops(text)
    stats.schema_valid = not errors and bool(ops)
    return ops, text


def _legacy_extract(llm_fn: LLMFn, prompt: str, engine: Any, stats: HeadroomStats) -> Optional[str]:
    """Pre-Fase-1 behaviour: free-prose prompt → code extraction."""
    text = llm_fn(prompt)
    stats.response_chars += len(text)
    stats.tokens_out_est += _estimate_tokens(text)
    code = engine.extract_valid_code(text)
    if code is None:
        stats.fallback = True
    return code


def llm_mutation_candidate(
    *,
    engine: Any,
    code: str,
    score: float,
    error_info: str = "",
    llm_fn: LLMFn,
    n: Optional[int] = None,
    stats_sink: Optional[Dict[str, Any]] = None,
) -> Any:
    """Produce a mutated candidate via the Headroom pipeline (or legacy path).

    Returns ``(candidate_code, stats_dict)``-ish via ``stats_sink``; the
    return value is the candidate code (str) or None when nothing valid came
    out of the LLM (callers apply their own fallbacks — e.g. AST mutation).
    """
    from ast_stubs import RETRIEVE_PROTOCOL_NOTE, stubify
    from structured_ops import apply_ops, build_schema_prompt
    from trace_compressor import get_trace_compressor

    flags = _flags()
    stats = HeadroomStats(mode="legacy")
    schema_on = flags.enabled("headroom.json_schema_output.enabled", False)
    stubs_on = flags.enabled("headroom.ast_stubs.enabled", False)
    crusher_on = flags.enabled("headroom.smart_crusher.enabled", False)
    batching_on = flags.enabled("headroom.batching.enabled", False)
    if n is None:
        n = int(flags.get("headroom.batching.batch_size", 5) or 5) if batching_on else 1

    t0 = time.perf_counter()

    # ── O1: compress the error block ─────────────────────────────────────
    region = engine._top_region(code)
    if crusher_on and error_info:
        record = get_trace_compressor().compress(error_info)
        compressed_error = record.text
        stats.trace_ratio = record.ratio
    else:
        compressed_error = error_info

    # ── O3: stub large bodies ────────────────────────────────────────────
    store = None
    if stubs_on:
        from ast_stubs import StubStore

        store = StubStore()
        stubbed, store, refs = stubify(code, store)
        stats.stub_count = len(refs)
        prompt_code = stubbed
    else:
        prompt_code = code

    if schema_on:
        # ── A1 (+O3 tool loop, +A3 batching) ────────────────────────────
        stats.mode = "schema"
        extra_rules = ""
        if store is not None and stats.stub_count:
            extra_rules = f"\n{RETRIEVE_PROTOCOL_NOTE}"
        if n > 1:
            extra_rules += (
                f"\n- Produce exactly {n} INDEPENDENT alternative ops (one per "
                "distinct improvement idea); each must be independently applicable."
            )
        prompt = build_schema_prompt(
            mode="HEURISTIC_MUTATION",
            code=prompt_code,
            score=score,
            error_block=compressed_error,
            n=n,
            extra_rules=extra_rules,
        )
        stats.prompt_chars = len(prompt)
        stats.tokens_in_est = _estimate_tokens(prompt)
        stats.ops_requested = n
        ops, raw_text = _schema_call(llm_fn, prompt, stats, store=store)
        stats.ops_total = len(ops)

        candidate: Optional[str] = None
        if ops:
            # With batching, prefer the highest-confidence op that applies;
            # apply the rest as extra attempts only if the first fails.
            for op in sorted(ops, key=lambda o: o.confidence, reverse=True):
                new_code, applied, failed = apply_ops(code, [op])
                stats.ops_applied += len(applied)
                stats.ops_failed += len(failed)
                if applied:
                    candidate = new_code
                    break
        if candidate is None:
            # Safety net: the model may have returned code despite the
            # contract — legacy extraction on the raw response (no extra call).
            stats.fallback = True
            candidate = engine.extract_valid_code(raw_text)
        _record_stats(stats, t0, error_info)
        if stats_sink is not None:
            stats_sink.update(stats.to_dict())
        return candidate

    # ── Legacy path (flags off) — byte-for-byte old behaviour ────────────
    prompt = engine.build_mutation_prompt(code, region, score, compressed_error)
    stats.prompt_chars = len(prompt)
    stats.tokens_in_est = _estimate_tokens(prompt)
    candidate = _legacy_extract(llm_fn, prompt, engine, stats)
    _record_stats(stats, t0, error_info)
    if stats_sink is not None:
        stats_sink.update(stats.to_dict())
    return candidate


def llm_redesign_candidate(
    *,
    engine: Any,
    code: str,
    score: float,
    task: str = "",
    llm_fn: LLMFn,
    stats_sink: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Redesign variant of the pipeline (schema mode when the flag is on)."""
    flags = _flags()
    if not flags.enabled("headroom.json_schema_output.enabled", False):
        return engine.redesign_with_llm(code, score, task, llm_fn)

    from ast_stubs import RETRIEVE_PROTOCOL_NOTE, StubStore, stubify
    from structured_ops import apply_ops, build_schema_prompt

    stats = HeadroomStats(mode="schema-redesign")
    t0 = time.perf_counter()
    store = StubStore()
    stubbed, store, refs = stubify(code, store)
    stats.stub_count = len(refs)
    extra_rules = f"\n{RETRIEVE_PROTOCOL_NOTE}" if stats.stub_count else ""
    prompt = build_schema_prompt(
        mode="RADICAL_REDESIGN",
        code=stubbed,
        score=score,
        task=task,
        n=1,
        extra_rules=extra_rules,
    )
    stats.prompt_chars = len(prompt)
    stats.tokens_in_est = _estimate_tokens(prompt)
    ops, raw_text = _schema_call(llm_fn, prompt, stats, store=store)
    stats.ops_total = len(ops)
    candidate: Optional[str] = None
    for op in ops:
        new_code, applied, failed = apply_ops(code, [op])
        stats.ops_applied += len(applied)
        stats.ops_failed += len(failed)
        if applied:
            candidate = new_code
            break
    if candidate is None:
        stats.fallback = True
        candidate = engine.extract_valid_code(raw_text)
    _record_stats(stats, t0, "")
    if stats_sink is not None:
        stats_sink.update(stats.to_dict())
    return candidate


def _record_stats(stats: HeadroomStats, t0: float, error_info: str) -> None:
    try:
        from cost_ledger import record_event

        d = stats.to_dict()
        d["wall_sec"] = round(time.perf_counter() - t0, 4)
        record_event("headroom_llm", d)
    except Exception:  # pragma: no cover - observability only
        pass
