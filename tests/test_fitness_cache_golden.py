"""Golden-master tests for fitness_cache — auto-opt verification."""
import sys, tempfile
sys.path.insert(0, ".")

from mutalambda_engines.fitness_cache import FitnessCache
from mutalambda_engines.fitness_vector import FitnessVector

def _make_cache(max_entries=100):
    tmp = tempfile.mktemp(suffix=".db")
    return FitnessCache(path=tmp, backend="sqlite", max_entries=max_entries)

def _fv_dict(correctness=1.0):
    fv = FitnessVector(correctness=correctness, latency_p50=0.01, latency_p99=0.05,
                       throughput=1000, memory_peak_mb=64, parsimony=0.8)
    return fv.to_dict()

def test_fv_dict_roundtrip():
    """FitnessVector to_dict must include correctness and latency_p50."""
    fv = FitnessVector(correctness=0.9999, latency_p50=0.0123, latency_p99=0.0456,
                       throughput=4242.0, memory_peak_mb=128.5, parsimony=0.7777)
    d = fv.to_dict()
    assert d["correctness"] == 0.9999
    assert d["latency_p50"] == 0.0123
    assert d["memory_peak_mb"] == 128.5

def test_fitness_cache_miss_then_hit():
    cache = _make_cache()
    code = "def g(): return 42\n"
    assert cache.get(code) is None
    cache.put(code, _fv_dict(0.9))
    result = cache.get(code)
    assert result is not None
    assert result["correctness"] == 0.9

def test_fitness_cache_size_limit():
    cache = _make_cache(max_entries=3)
    for i in range(5):
        cache.put(f"code_{i}", {"score": float(i)})
    assert cache.get("code_4") is not None

def test_fitness_cache_overwrite():
    cache = _make_cache()
    code = "def f(): pass\n"
    cache.put(code, {"score": 0.5})
    assert cache.get(code)["score"] == 0.5
    cache.put(code, {"score": 0.9})
    assert cache.get(code)["score"] == 0.9

def test_fitness_cache_distinct_keys():
    cache = _make_cache()
    for i in range(5):
        cache.put(f"code_{i}", {"score": float(i)})
    for i in range(5):
        result = cache.get(f"code_{i}")
        assert result is not None
        assert result["score"] == float(i)

def test_fitness_cache_stats():
    cache = _make_cache()
    code = "def f(): pass\n"
    cache.put(code, _fv_dict(1.0))
    _ = cache.get(code)  # hit
    _ = cache.get("not_cached")  # miss
    stats = cache.stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1

def test_fitness_cache_to_dict_roundtrip():
    cache = _make_cache()
    code = "x = 1 + 1\n"
    val = _fv_dict(0.85)
    cache.put(code, val)
    result = cache.get(code)
    assert result == val
