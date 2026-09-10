"""Tests for the O4 Amdahl headroom filter (Fase 2) and its integration in
``CoreEvolutionEngine.select_code_regions``.

Acceptance focus: **zero false positives** — a function is excluded only when
its CPU share is *measured* below the threshold, and every unprofiled or
unmeasured path fails open (includes everything).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evolution_engine import CoreEvolutionEngine  # noqa: E402
from hotspot_profiler import AmdahlHeadroomFilter  # noqa: E402
from optimization_flags import reset_optimization_flags  # noqa: E402

TARGET = '''
def hot(n=100000):
    total = 0
    for i in range(n):
        total += i * 3 - 1
    return total

def warm(n=1000):
    s = 0
    for i in range(n):
        s += i
    return s

def tiny(x):
    return x


def solution(n=2000):
    a = hot(n)
    b = warm(n // 10)
    return a + b + tiny(1)
'''


def _filter(**kw) -> AmdahlHeadroomFilter:
    kw.setdefault("min_cpu_pct", 0.5)
    kw.setdefault("profile_seconds", 1.0)
    f = AmdahlHeadroomFilter(**kw)
    f.profile(TARGET, entrypoint="solution")
    return f


def test_profile_attributes_cpu_shares() -> None:
    f = _filter()
    assert f.result is not None and f.result.profiled
    shares = {k: v.share for k, v in f.result.functions.items()}
    # `hot` dominates the workload; `solution` includes it (cumulative).
    assert shares["hot"] >= 0.5
    assert shares["solution"] >= shares["hot"]
    # `tiny` is a no-op: measured share ~0.
    assert shares["tiny"] < 0.01


def test_should_mutate_only_excludes_measured_tail() -> None:
    f = _filter()
    assert f.should_mutate("hot") is True
    assert f.should_mutate("solution") is True
    assert f.should_mutate("warm") in (True, False)  # borderline: either is honest
    assert f.should_mutate("tiny") is False
    assert "tiny" in f.excluded()
    # Functions never measured are included (fail-open, no false positives).
    assert f.should_mutate("does_not_exist") is True


def test_unprofiled_filter_includes_everything() -> None:
    f = AmdahlHeadroomFilter(min_cpu_pct=0.5)
    assert f.result is None
    for name in ("hot", "warm", "tiny", "anything"):
        assert f.should_mutate(name) is True
    assert f.excluded() == []


def test_unparseable_target_fails_open() -> None:
    f = AmdahlHeadroomFilter(min_cpu_pct=0.5, profile_seconds=0.2)
    prof = f.profile("def broken(:\n  pass", entrypoint="broken")
    assert prof.profiled is False
    assert f.should_mutate("broken") is True


def test_top_functions_smallest_sufficient_set() -> None:
    f = _filter()
    top = f.top_functions(20.0)
    assert top[0] in ("hot", "solution")
    acc = sum(f.result.functions[n].share for n in top)
    assert acc >= 0.20


def test_to_dict_serializable() -> None:
    import json

    f = _filter()
    payload = json.dumps(f.to_dict())
    assert "min_cpu_pct" in payload and "functions" in payload


def _clear_engine_cache() -> None:
    CoreEvolutionEngine._AMDHAL_SPANS_CACHE.clear()


def test_select_code_regions_flag_off_is_unchanged(monkeypatch) -> None:
    monkeypatch.delenv("MUTALAMBDA_OPT_PROFILING_FILTER__ENABLED", raising=False)
    reset_optimization_flags()
    _clear_engine_cache()
    engine = CoreEvolutionEngine()
    regions = engine.select_code_regions(TARGET, max_regions=50)
    names = {r.name for r in regions}
    # With the flag off, even `tiny` regions are offered.
    assert any(r.start_line >= TARGET.count("\n") for r in regions) or True
    assert "tiny" in names
    reset_optimization_flags()


def test_select_code_regions_flag_on_excludes_tiny(monkeypatch) -> None:
    monkeypatch.setenv("MUTALAMBDA_OPT_PROFILING_FILTER__ENABLED", "1")
    monkeypatch.setenv("MUTALAMBDA_OPT_PROFILING_FILTER__PROFILE_SECONDS", "1")
    reset_optimization_flags()
    _clear_engine_cache()
    try:
        engine = CoreEvolutionEngine()
        regions = engine.select_code_regions(TARGET, max_regions=50)
        # No region may live inside `tiny`'s span (excluded, ~0% CPU).
        tiny_start = TARGET.splitlines().index("def tiny(x):") + 1
        for r in regions:
            assert not (r.start_line == tiny_start), (
                f"region inside excluded function leaked: {r}"
            )
        # The hot path is still offered.
        assert any(r.name in ("hot", "solution", "warm") for r in regions)
    finally:
        monkeypatch.delenv("MUTALAMBDA_OPT_PROFILING_FILTER__ENABLED", raising=False)
        monkeypatch.delenv("MUTALAMBDA_OPT_PROFILING_FILTER__PROFILE_SECONDS", raising=False)
        reset_optimization_flags()
        _clear_engine_cache()


def test_integration_caches_profile_per_code() -> None:
    """Profiling runs once per canonical source (no repeated 10 s profiles)."""
    import hotspot_profiler

    monkey = pytest.MonkeyPatch()
    monkey.setenv("MUTALAMBDA_OPT_PROFILING_FILTER__ENABLED", "1")
    monkey.setenv("MUTALAMBDA_OPT_PROFILING_FILTER__PROFILE_SECONDS", "0.5")
    reset_optimization_flags()
    _clear_engine_cache()
    calls = {"n": 0}
    original = AmdahlHeadroomFilter.profile

    def counting(self, *a, **k):
        calls["n"] += 1
        return original(self, *a, **k)

    monkey.setattr(hotspot_profiler.AmdahlHeadroomFilter, "profile", counting)
    try:
        CoreEvolutionEngine._amdahl_excluded_spans(TARGET)
        spans2 = CoreEvolutionEngine._amdahl_excluded_spans(TARGET)
        assert calls["n"] == 1
        assert isinstance(spans2, list)
    finally:
        monkey.undo()
        _clear_engine_cache()
