"""Tests for the Fase-3 Economic Headroom Gate (O5) + hypervolume."""

from __future__ import annotations

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from economic_gate import (  # noqa: E402
    EconomicHeadroomGate,
    MAX_HYPERVOLUME,
    _hv2,
    _hv3,
    fitness_objectives,
    hypervolume,
)


class FV:
    def __init__(self, c, lat, mem):
        self.correctness = c
        self.latency_p50 = lat
        self.memory_peak_mb = mem


# ── hypervolume correctness ─────────────────────────────────────────────────


def test_hv2_exact_cases() -> None:
    assert abs(_hv2([(2, 3)], (0, 0)) - 6.0) < 1e-12
    assert abs(_hv2([(1, 4), (4, 1)], (0, 0)) - 7.0) < 1e-12
    assert abs(_hv2([(1, 4), (4, 1), (2, 3)], (0, 0)) - 9.0) < 1e-12
    assert abs(_hv2([(1, 1), (2, 2), (3, 3)], (0, 0)) - 9.0) < 1e-12  # nested
    assert _hv2([], (0, 0)) == 0.0


def test_hv3_exact_cases() -> None:
    assert abs(_hv3([(1, 1, 1)], (0, 0, 0)) - 1.0) < 1e-12
    assert abs(_hv3([(2, 1, 1), (1, 2, 1)], (0, 0, 0)) - 3.0) < 1e-12
    # inclusion-exclusion by hand: 3×0.5 − 3×0.125 + 0.125
    assert abs(_hv3([(2, .5, .5), (.5, 2, .5), (.5, .5, 2)], (0, 0, 0)) - 1.25) < 1e-12
    # dominated points must not change the volume
    assert abs(_hv3([(1, 1, 1), (.5, 1, 1), (1, .5, 1), (1, 1, .5)], (0, 0, 0)) - 1.0) < 1e-12
    assert _hv3([], (0, 0, 0)) == 0.0


def test_hv3_matches_grid_integration() -> None:
    rng = random.Random(7)
    pts = [
        (rng.choice((1, 2, 3)), rng.choice((0.5, 1, 2)), rng.choice((0.5, 1.5, 2)))
        for _ in range(12)
    ]
    exact = _hv3(pts, (0, 0, 0))
    n, dx = 60, 3.2 / 60
    vol = 0.0
    for i in range(n):
        for j in range(n):
            for k in range(n):
                x, y, z = (i + 0.5) * dx, (j + 0.5) * dx, (k + 0.5) * dx
                if any(p[0] >= x and p[1] >= y and p[2] >= z for p in pts):
                    vol += dx ** 3
    assert abs(exact - vol) / vol < 0.03


def test_hypervolume_normalized_range_and_worst_filtering() -> None:
    fvs = [FV(1.0, 100, 10), FV(0.9, 50, 20), FV(1.0, float("inf"), 10)]
    h = hypervolume(fvs)
    assert 0.0 < h <= 1.0
    # worst vectors (inf latency) are ignored
    assert hypervolume([FV(1.0, float("inf"), 10)]) == 0.0
    # raw scale is consistent with the normalised one
    raw = hypervolume(fvs, normalize=False)
    assert abs(h * MAX_HYPERVOLUME - raw) < 1e-9


def test_fitness_objectives_negation() -> None:
    o = fitness_objectives(FV(0.8, 100.0, 32.0))
    assert o == (0.8, -100.0, -32.0)
    assert fitness_objectives(FV(0.8, float("inf"), 1.0)) is None


# ── the gate ────────────────────────────────────────────────────────────────


def test_gate_stops_after_consecutive_stall() -> None:
    g = EconomicHeadroomGate(delta_h_threshold=0.005, stall_generations=5)
    decisions = []
    for gen in range(8):
        d = g.observe(gen, 0.5)
        decisions.append(d)
        if d.stop:  # the engine breaks here
            break
    assert decisions[4].stop is False
    assert decisions[5].stop is True
    assert decisions[5].reason == "stall"
    assert g.stop_reason == "stall"
    assert g.stopped_at_generation == 5


def test_gate_large_first_delta_does_not_stall() -> None:
    g = EconomicHeadroomGate(delta_h_threshold=0.005, stall_generations=5)
    d0 = g.observe(0, 0.9)  # first ΔH = HV itself
    assert d0.delta_h == pytest.approx(0.9)
    assert d0.stop is False


def test_gate_improving_front_never_stalls() -> None:
    g = EconomicHeadroomGate(delta_h_threshold=0.005, stall_generations=5)
    hv = 0.1
    for gen in range(30):
        hv += 0.02
        d = g.observe(gen, hv)
        assert d.stop is False
    assert g.stop_reason is None


def test_gate_recover_from_stall() -> None:
    g = EconomicHeadroomGate(delta_h_threshold=0.005, stall_generations=5)
    hv = 0.5
    g.observe(0, hv)  # first ΔH = HV itself → no stall
    for gen in range(1, 5):
        g.observe(gen, hv + 1e-6)
    assert g._stall_count == 4
    g.observe(5, hv + 0.5)  # big jump resets
    assert g._stall_count == 0


def test_gate_cost_criterion_stops_when_gpu_outweighs_savings() -> None:
    # 180 s/gen on a $0.5/h GPU = $0.025/gen; 30 planned → remaining cost
    # quickly exceeds a $0.10/h production saving budget.
    g = EconomicHeadroomGate(
        delta_h_threshold=0.5,  # stall can never trigger here
        stall_generations=100,
        gpu_hour_usd=0.5,
        production_cpu_savings_hour_usd=0.10,
        gpu_seconds_per_generation=180.0,
        total_planned_generations=30,
    )
    d = g.observe(0, 0.5)
    assert d.stop is True
    assert d.reason == "cost_exceeds_savings"
    assert g.stop_reason == "cost_exceeds_savings"


def test_gate_cost_criterion_inactive_without_gpu_cost() -> None:
    g = EconomicHeadroomGate(
        delta_h_threshold=0.5,
        stall_generations=100,
        gpu_seconds_per_generation=0.0,  # CPU-only: criterion off
        production_cpu_savings_hour_usd=0.10,
        total_planned_generations=30,
    )
    for gen in range(5):
        d = g.observe(gen, 0.5)
        assert d.stop is False


class _FakeLedger:
    def __init__(self) -> None:
        self.events = []

    def log_event(self, kind, extra=None):
        self.events.append((kind, extra))


def test_gate_logs_stop_event_to_ledger() -> None:
    ledger = _FakeLedger()
    g = EconomicHeadroomGate(delta_h_threshold=0.005, stall_generations=3, ledger=ledger)
    for gen in range(4):
        g.observe(gen, 0.5)
    assert len(ledger.events) == 1
    kind, extra = ledger.events[0]
    assert kind == "economic_gate_stop"
    assert extra["reason"] == "stall"
    assert extra["generation"] == 3


def test_gate_summary_serializable() -> None:
    import json

    g = EconomicHeadroomGate(delta_h_threshold=0.005, stall_generations=2)
    g.observe(0, 0.9)
    g.observe(1, 0.9001)
    g.observe(2, 0.9002)
    blob = json.dumps(g.summary())
    assert "stop_reason" in blob and "history" in blob
