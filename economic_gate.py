"""Economic Headroom Gate (FASE 3 — O5) + 3-D hypervolume.

The gate watches the evolution's *economics*, not just its fitness:

  * **stall criterion** — if the hypervolume improvement ``ΔH`` stays below
    ``delta_h_threshold`` for ``stall_generations`` consecutive generations,
    the run is stopped: more generations would burn budget without buying
    Pareto progress.
  * **cost criterion** — if the estimated GPU cost of the *remaining*
    generations exceeds the production CPU savings the candidate would
    deliver (``production_cpu_savings_hour_usd`` > 0), the run is stopped:
    continuing costs more than the optimisation is worth.

Every stop decision is logged to the cost ledger (``log_event``) so the
roi_report can show *why* the run stopped.

The hypervolume is computed over the non-dominated front in the 3 dominance
objectives of :class:`FitnessVector` — (correctness, −latency_p50,
−memory_peak_mb), all "greater is better" — against the reference point
(0, −REF_LATENCY_MS, −REF_MEMORY_MB), the "worst acceptable" point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from fitness_vector import REF_LATENCY_MS, REF_MEMORY_MB

__all__ = [
    "GateDecision",
    "EconomicHeadroomGate",
    "MAX_HYPERVOLUME",
    "REFERENCE",
    "fitness_objectives",
    "hypervolume",
]

# Reference point: worst *acceptable* point.  Points that fail to dominate it
# (e.g. latency > REF_LATENCY_MS) are discarded from the front.
REFERENCE: Tuple[float, float, float] = (0.0, -REF_LATENCY_MS, -REF_MEMORY_MB)

# Volume of the ideal box — the normalisation constant so that the
# hypervolume lives in [0, 1] (ΔH thresholds become scale-free).
MAX_HYPERVOLUME: float = 1.0 * REF_LATENCY_MS * REF_MEMORY_MB


def fitness_objectives(fv) -> Optional[Tuple[float, float, float]]:
    """(correctness, −latency_p50, −memory_peak_mb) or None when the vector
    is worst/undefined (infinite latency/memory)."""
    try:
        c = float(fv.correctness)
        lat = float(fv.latency_p50)
        mem = float(fv.memory_peak_mb)
    except Exception:
        return None
    if math.isinf(lat) or math.isinf(mem):
        return None
    return (c, -lat, -mem)


# ── exact hypervolume (sweep formulation) ───────────────────────────────────


def _hv2(points: List[Tuple[float, float]], ref: Tuple[float, float]) -> float:
    """Exact 2-D hypervolume (x-sweep).  Dominated points are harmless: the
    running max absorbs them.

    Sort by x descending; for the slab (x_{i+1}, x_i] the covered height is
    max{y : point with x >= x_i}.  Plus the final slab [ref_x, x_n].
    """
    if not points:
        return 0.0
    pts = sorted(points, key=lambda p: (-p[0], -p[1]))
    vol = 0.0
    max_y = ref[1]
    for i, (x, y) in enumerate(pts):
        left = pts[i + 1][0] if i + 1 < len(pts) else ref[0]
        if y > max_y:
            max_y = y
        if left >= x:
            continue
        vol += (x - left) * (max_y - ref[1])
    return max(0.0, vol)


def _hv3(points: List[Tuple[float, float, float]], ref: Tuple[float, float, float]) -> float:
    """Exact 3-D hypervolume via x-sweep (verified against manual
    inclusion-exclusion cases in tests/test_economic_gate.py).

    Partition x at the point abscissas: for the slab (x_{i+1}, x_i] the
    cross-section is the 2-D HV of the active points {q : q.x >= x_i} over
    the (y, z) axes.  O(n² log n) — fine for Pareto fronts.
    """
    if not points:
        return 0.0
    pts = sorted(points, key=lambda p: (-p[0], -p[1], -p[2]))
    vol = 0.0
    for i, p in enumerate(pts):
        left = pts[i + 1][0] if i + 1 < len(pts) else ref[0]
        if left >= p[0]:
            continue
        active = pts[: i + 1]
        section = _hv2([(q[1], q[2]) for q in active], (ref[1], ref[2]))
        vol += (p[0] - left) * section
    return max(0.0, vol)


def hypervolume(
    fitnesses: Sequence,
    ref: Optional[Tuple[float, float, float]] = None,
    *,
    normalize: bool = True,
) -> float:
    """Hypervolume of the non-dominated front of *fitnesses*.

    Accepts any objects exposing FitnessVector-like attributes
    (``correctness``, ``latency_p50``, ``memory_peak_mb``).  Worst/undefined
    vectors (infinite latency/memory) are ignored.  Deterministic.

    ``normalize=True`` (default) divides by the ideal-box volume so the
    result is in [0, 1] — the units the EconomicHeadroomGate's ΔH threshold
    assumes.
    """
    ref = ref or REFERENCE
    pts: List[Tuple[float, float, float]] = []
    for fv in fitnesses:
        o = fitness_objectives(fv)
        if o is None:
            continue
        if o[0] > ref[0] and o[1] > ref[1] and o[2] > ref[2]:
            pts.append(o)
    if not pts:
        return 0.0
    # Non-dominated filter (3-D, greater-is-better).
    front: List[Tuple[float, float, float]] = []
    for a in pts:
        dominated = False
        for b in pts:
            if b is a:
                continue
            if b[0] >= a[0] and b[1] >= a[1] and b[2] >= a[2] and (
                b[0] > a[0] or b[1] > a[1] or b[2] > a[2]
            ):
                dominated = True
                break
        if not dominated:
            front.append(a)
    hv = _hv3(front, ref)
    return hv / MAX_HYPERVOLUME if normalize else hv


# ── the gate ────────────────────────────────────────────────────────────────


@dataclass
class GateDecision:
    stop: bool
    reason: str  # "continue" | "stall" | "cost_exceeds_savings"
    delta_h: float = 0.0
    stall_count: int = 0
    hypervolume: float = 0.0
    gpu_cost_usd: float = 0.0
    est_remaining_cost_usd: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "stop": self.stop,
            "reason": self.reason,
            "delta_h": round(self.delta_h, 6),
            "stall_count": self.stall_count,
            "hypervolume": round(self.hypervolume, 6),
            "gpu_cost_usd": round(self.gpu_cost_usd, 8),
            "est_remaining_cost_usd": round(self.est_remaining_cost_usd, 8),
        }


class EconomicHeadroomGate:
    """O5: stop evolution when it stops being economically sensible.

    Feed the per-generation hypervolume with :meth:`observe`; the gate
    returns a :class:`GateDecision`.  ``gpu_seconds_per_generation`` is the
    cost model for the cost criterion (0 on CPU-only runs → criterion
    inactive, which is the honest default).
    """

    def __init__(
        self,
        *,
        delta_h_threshold: float = 0.005,
        stall_generations: int = 5,
        gpu_hour_usd: float = 0.5,
        production_cpu_savings_hour_usd: float = 0.0,
        gpu_seconds_per_generation: float = 0.0,
        total_planned_generations: int = 0,
        ledger=None,
    ) -> None:
        self.delta_h_threshold = float(delta_h_threshold)
        self.stall_generations = int(stall_generations)
        self.gpu_hour_usd = float(gpu_hour_usd)
        self.production_cpu_savings_hour_usd = float(production_cpu_savings_hour_usd)
        self.gpu_seconds_per_generation = float(gpu_seconds_per_generation)
        self.total_planned_generations = int(total_planned_generations)
        self.ledger = ledger
        self._last_hv: Optional[float] = None
        self._stall_count = 0
        self.history: List[GateDecision] = []
        self.stop_reason: Optional[str] = None
        self.stopped_at_generation: Optional[int] = None

    # ── economics ─────────────────────────────────────────────────────────
    def _gpu_cost_per_gen(self) -> float:
        return self.gpu_seconds_per_generation / 3600.0 * self.gpu_hour_usd

    def _est_remaining_cost(self, generation: int) -> float:
        remaining = max(0, self.total_planned_generations - generation - 1)
        return remaining * self._gpu_cost_per_gen()

    # ── main loop hook ────────────────────────────────────────────────────
    def observe(self, generation: int, hypervolume: float) -> GateDecision:
        """Feed the generation's hypervolume; returns the stop decision."""
        delta_h = float(hypervolume) - (self._last_hv or 0.0)
        self._last_hv = float(hypervolume)

        stall = delta_h < self.delta_h_threshold
        self._stall_count = self._stall_count + 1 if stall else 0

        decision = GateDecision(
            stop=False,
            reason="continue",
            delta_h=delta_h,
            stall_count=self._stall_count,
            hypervolume=float(hypervolume),
            gpu_cost_usd=self._gpu_cost_per_gen(),
            est_remaining_cost_usd=self._est_remaining_cost(generation),
        )

        if self._stall_count >= self.stall_generations:
            decision.stop = True
            decision.reason = "stall"
        elif (
            self.production_cpu_savings_hour_usd > 0.0
            and self._est_remaining_cost(generation) > self.production_cpu_savings_hour_usd
        ):
            decision.stop = True
            decision.reason = "cost_exceeds_savings"

        self.history.append(decision)
        if decision.stop:
            self.stop_reason = decision.reason
            self.stopped_at_generation = generation
            self._log_event(
                "economic_gate_stop",
                {
                    "generation": generation,
                    "reason": decision.reason,
                    "delta_h": round(delta_h, 6),
                    "hypervolume": round(hypervolume, 6),
                    "est_remaining_cost_usd": round(decision.est_remaining_cost_usd, 8),
                },
            )
        return decision

    def _log_event(self, kind: str, extra: Dict) -> None:
        if self.ledger is not None:
            try:
                self.ledger.log_event(kind=kind, extra=extra)
            except Exception:
                pass

    def summary(self) -> Dict:
        return {
            "enabled": True,
            "delta_h_threshold": self.delta_h_threshold,
            "stall_generations": self.stall_generations,
            "gpu_seconds_per_generation": self.gpu_seconds_per_generation,
            "production_cpu_savings_hour_usd": self.production_cpu_savings_hour_usd,
            "stop_reason": self.stop_reason,
            "stopped_at_generation": self.stopped_at_generation,
            "final_hypervolume": self._last_hv,
            "history": [d.to_dict() for d in self.history],
        }
