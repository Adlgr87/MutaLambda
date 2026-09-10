"""Tests for the canonical-hash fitness cache (Fase 0, A2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fitness_cache import FitnessCache, canonical_code_hash, fitness_cache_key


# ── Canonical code hash ──────────────────────────────────────────────────────


def test_hash_stable_across_calls():
    code = "def f(x):\n    return x * 2\n"
    assert canonical_code_hash(code) == canonical_code_hash(code)
    assert canonical_code_hash(code).startswith("a:")
    assert len(canonical_code_hash(code)) == 2 + 64


def test_hash_ignores_whitespace_and_formatting():
    a = "def f(x):\n    return    x*2\n"
    b = "def f(x):\n    return x * 2\n\n\n"
    assert canonical_code_hash(a) == canonical_code_hash(b)


def test_hash_ignores_comments():
    a = "def f(x):\n    # double it\n    return x * 2\n"
    b = "def f(x):\n    return x * 2\n"
    assert canonical_code_hash(a) == canonical_code_hash(b)


def test_hash_differs_for_different_logic():
    a = "def f(x):\n    return x * 2\n"
    b = "def f(x):\n    return x * 3\n"
    assert canonical_code_hash(a) != canonical_code_hash(b)


def test_hash_unparseable_falls_back_to_raw():
    junk = "not python at all (((("
    h = canonical_code_hash(junk)
    assert h.startswith("r:")
    assert h != canonical_code_hash("def f():\n    pass\n")


def test_key_namespaces():
    code = "def f():\n    return 1\n"
    k1 = fitness_cache_key("enterprise:seed42", code)
    k2 = fitness_cache_key("scientific:seed42", code)
    k3 = fitness_cache_key("enterprise:seed42", code)
    assert k1 == k3
    assert k1 != k2


# ── sqlite backend ───────────────────────────────────────────────────────────


def test_sqlite_put_get_miss(tmp_path: Path):
    cache = FitnessCache(tmp_path / "fc.db", backend="sqlite", max_entries=10)
    try:
        assert cache.get("nope") is None
        cache.put("k1", {"score": 0.9, "ok": True})
        assert cache.get("k1") == {"score": 0.9, "ok": True}
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["puts"] == 1
        assert stats["hit_rate"] == 0.5
    finally:
        cache.close()


def test_sqlite_persistence_across_instances(tmp_path: Path):
    path = tmp_path / "fc.db"
    cache = FitnessCache(path, backend="sqlite")
    cache.put("persist-me", [1, 2, 3])
    cache.close()
    cache2 = FitnessCache(path, backend="sqlite")
    try:
        assert cache2.get("persist-me") == [1, 2, 3]
    finally:
        cache2.close()


def test_sqlite_eviction_bounded(tmp_path: Path):
    cache = FitnessCache(tmp_path / "fc.db", backend="sqlite", max_entries=5)
    try:
        for i in range(20):
            cache.put(f"k{i}", i)
        # Oldest evicted, newest retained.
        assert cache.get("k0") is None
        assert cache.get("k19") == 19
    finally:
        cache.close()


# ── json backend ─────────────────────────────────────────────────────────────


def test_json_backend_roundtrip(tmp_path: Path):
    cache = FitnessCache(tmp_path / "fc.json", backend="json", max_entries=10)
    cache.put("jk", {"fitness": {"correctness": 1.0}})
    assert cache.get("jk") == {"fitness": {"correctness": 1.0}}
    cache.close()
    assert (tmp_path / "fc.json").exists()
    cache2 = FitnessCache(tmp_path / "fc.json", backend="json")
    try:
        assert cache2.get("jk") == {"fitness": {"correctness": 1.0}}
    finally:
        cache2.close()


def test_json_backend_eviction(tmp_path: Path):
    cache = FitnessCache(tmp_path / "fc.json", backend="json", max_entries=3)
    try:
        for i in range(10):
            cache.put(f"j{i}", i)
        assert cache.get("j0") is None
        assert cache.get("j9") == 9
    finally:
        cache.close()


def test_unsupported_backend_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="unsupported"):
        FitnessCache(tmp_path / "x", backend="redis")
