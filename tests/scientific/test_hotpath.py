"""Tests para hot-path detection (HP-01 a HP-07)."""
import pytest
from muta_ext.scientific.hotpath import profile_code, profile_workload
from muta_ext.scientific.hotpath_types import ProfileConfig


def workload_slow():
    """Workload que toma tiempo significativo."""
    total = 0
    for i in range(20000):
        total += i * i
    return total


def workload_fast():
    """Workload rápido."""
    return sum(i * 0.5 for i in range(100))


class TestHotPath:
    """Tests para profile_code."""

    def test_hp01_dominant(self):
        hp = profile_code("workload_slow", workload_slow, min_cumulative_pct=1.0)
        assert len(hp) >= 1

    def test_hp02_threshold(self):
        hp1 = profile_code("workload_slow", workload_slow, min_cumulative_pct=1.0)
        hp50 = profile_code("workload_slow", workload_slow, min_cumulative_pct=50.0)
        assert len(hp50) <= len(hp1)

    def test_hp03_none(self):
        hp = profile_code("workload_fast", workload_fast, min_cumulative_pct=99.0)
        assert len(hp) == 0

    def test_hp04_entry(self):
        hp = profile_code("workload_slow", workload_slow, min_cumulative_pct=1.0)
        assert any(h.is_entry for h in hp if h.function_name == "workload_slow")

    def test_hp05_disabled(self):
        hp = profile_code("w", workload_slow, profiler="none")
        assert len(hp) == 0

    def test_hp06_exception(self):
        def fail():
            raise ValueError("boom")

        with pytest.raises(RuntimeError):
            profile_code("fail", fail)

    def test_hp07_determinism(self):
        hp1 = profile_code("workload_slow", workload_slow, min_cumulative_pct=1.0)
        hp2 = profile_code("workload_slow", workload_slow, min_cumulative_pct=1.0)
        if hp1 and hp2:
            assert hp1[0].function_name == hp2[0].function_name


class TestProfileWorkload:
    """Tests para profile_workload."""

    def test_config_enabled(self):
        r = profile_workload("w", workload_slow, ProfileConfig(min_cumulative_pct=1.0))
        assert r.has_hot_paths

    def test_config_disabled(self):
        r = profile_workload("w", workload_slow, ProfileConfig(enabled=False))
        assert not r.has_hot_paths

    def test_error_graceful(self):
        def broken():
            raise ValueError

        r = profile_workload("b", broken, ProfileConfig())
        assert r.error is not None