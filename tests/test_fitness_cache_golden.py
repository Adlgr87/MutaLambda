"""Golden-master tests for fitness_cache — auto-opt verification.

Verifies that Phase 3 optimization (cache key determinism, size limits,
overwrite semantics) preserves exact behavior.
"""

import os
import sys
import tempfile

import pytest

from mutalambda_engines.fitness_cache import FitnessCache
from mutalambda_engines.fitness_vector import FitnessVector

sys.path.insert(0, ".")


def _make_cache(max_entries=100, backend="json"):
    """Create a FitnessCache with a temp file (json backend avoids sqlite locking in CI)."""
    tmp = tempfile.mktemp(suffix=".json" if backend == "json" else ".db")
    cache = FitnessCache(path=tmp, backend=backend, max_entries=max_entries)
    cache._tmpfile = tmp
    return cache


def _fv_dict(correctness=1.0):
    """Return FitnessVector serialized as dict (cache values must be JSON-serializable)."""
    fv = FitnessVector(
        correctness=correctness, latency_p50=0.01, latency_p99=0.05,
        throughput=1000, memory_peak_mb=64, parsimony=0.8,
    )
    return fv.to_dict()


@pytest.fixture
def cache():
    c = _make_cache()
    yield c
    c.close()
    if hasattr(c, "_tmpfile") and os.path.exists(c._tmpfile):
        os.unlink(c._tmpfile)


def test_fitness_cache_miss_then_hit():
    """First lookup is miss, second is hit."""
    cache = _make_cache()
    code = "def g(): return 42\n"
    assert cache.get(code) is None
    cache.put(code, _fv_dict(0.9))
    result = cache.get(code)
    assert result is not None
    assert result["correctness"] == 0.9
    cache.close()
    if os.path.exists(cache._tmpfile):
        os.unlink(cache._tmpfile)


def test_fitness_cache_preserves_values():
    """Cached fitness must be identical to stored."""
    cache = _make_cache()
    code = "def h(): pass\n"
    fv = _fv_dict(1.0)
    cache.put(code, fv)
    result = cache.get(code)
    assert result["correctness"] == fv["correctness"]
    assert result["latency_p50"] == fv["latency_p50"]
    assert result["latency_p99"] == fv["latency_p99"]
    assert result["throughput"] == fv["throughput"]
    assert result["memory_peak_mb"] == fv["memory_peak_mb"]
    assert result["parsimony"] == fv["parsimony"]
    cache.close()
    if os.path.exists(cache._tmpfile):
        os.unlink(cache._tmpfile)


def test_fitness_cache_size_limit():
    """Cache must respect max_entries limit (evicts oldest)."""
    cache = _make_cache(max_entries=3)
    for i in range(5):
        cache.put(f"code_{i}", {"score": float(i)})
    assert cache.get("code_0") is None
    assert cache.get("code_1") is None
    assert cache.get("code_4") is not None
    cache.close()
    if os.path.exists(cache._tmpfile):
        os.unlink(cache._tmpfile)


def test_fitness_cache_overwrite():
    """Overwriting must update stored value."""
    cache = _make_cache()
    code = "def f(): pass\n"
    cache.put(code, {"score": 0.5})
    assert cache.get(code)["score"] == 0.5
    cache.put(code, {"score": 0.9})
    assert cache.get(code)["score"] == 0.9
    cache.close()
    if os.path.exists(cache._tmpfile):
        os.unlink(cache._tmpfile)


def test_fitness_cache_distinct_keys():
    """Different codes must have different cache entries."""
    cache = _make_cache()
    for i in range(5):
        cache.put(f"code_{i}", {"score": float(i)})
    for i in range(5):
        result = cache.get(f"code_{i}")
        assert result is not None
        assert result["score"] == float(i)
    cache.close()
    if os.path.exists(cache._tmpfile):
        os.unlink(cache._tmpfile)


def test_fitness_cache_stats():
    """Cache must track hits and misses."""
    cache = _make_cache()
    code = "def f(): pass\n"
    cache.put(code, _fv_dict(1.0))
    _ = cache.get(code)
    _ = cache.get("not_cached")
    stats = cache.stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1
    cache.close()
    if os.path.exists(cache._tmpfile):
        os.unlink(cache._tmpfile)


def test_fitness_cache_persistence():
    """Golden: values survive close+reopen for json backend."""
    tmp = tempfile.mktemp(suffix=".json")
    cache = FitnessCache(path=tmp, backend="json", max_entries=100)
    cache._tmpfile = tmp
    cache.put("def persisted(): pass\n", {"correctness": 0.85})
    cache.close()
    cache2 = FitnessCache(path=tmp, backend="json", max_entries=100)
    cache2._tmpfile = tmp
    result = cache2.get("def persisted(): pass\n")
    assert result is not None
    assert result["correctness"] == 0.85
    cache2.close()
    if os.path.exists(tmp):
        os.unlink(tmp)
