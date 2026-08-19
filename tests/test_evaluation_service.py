"""Tests for EvaluationService HFC cache hit/miss instrumentation."""

from __future__ import annotations

import pytest

from evaluation_service import EvaluationService

GOOD_CODE = "def f(x):\n    return x + 1\n"
TESTS = [{"function": "f", "args": [1], "expected": 2, "comparison": "equal"}]


@pytest.fixture
def svc() -> EvaluationService:
    return EvaluationService(
        test_cases=TESTS,
        timeout_sec=5.0,
        max_workers=1,
        cache_enabled=True,
        runner_mode="subprocess",
    )


def test_cache_stats_initial(svc):
    """Counters start at zero."""
    stats = svc.cache_stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["hit_rate"] == 0.0
    assert stats["size"] == 0


def test_cache_miss_increments(svc):
    """First evaluation of a code is a miss."""
    svc.evaluate_batch([GOOD_CODE])
    stats = svc.cache_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 0
    assert stats["hit_rate"] == 0.0


def test_cache_hit_increments(svc):
    """Repeated evaluation of cached code is a hit."""
    svc.evaluate_batch([GOOD_CODE])  # miss
    svc.evaluate_batch([GOOD_CODE])  # hit
    stats = svc.cache_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 1
    assert stats["hit_rate"] == 0.5


def test_cache_hit_rate_mixed(svc):
    """Multiple hits and misses produce correct rate."""
    svc.evaluate_batch([GOOD_CODE])        # miss (1)
    svc.evaluate_batch([GOOD_CODE])        # hit  (1)
    svc.evaluate_batch([GOOD_CODE])        # hit  (2)
    svc.evaluate_batch(["def f(x):\n    return x\n"])  # miss (2)
    stats = svc.cache_stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 2
    assert stats["hit_rate"] == 0.5
    assert stats["size"] == 2


def test_cache_disabled_does_not_increment(svc):
    """With cache_enabled=False, no hits/misses recorded."""
    svc.cache_enabled = False
    svc.evaluate_batch([GOOD_CODE])
    stats = svc.cache_stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["hit_rate"] == 0.0


def test_invalidate_resets_counters(svc):
    """invalidate() (no code) clears cache and resets counters."""
    svc.evaluate_batch([GOOD_CODE])        # miss
    svc.evaluate_batch([GOOD_CODE])        # hit
    svc.invalidate()
    stats = svc.cache_stats()
    assert stats["size"] == 0
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["hit_rate"] == 0.0


def test_invalidate_single_entry_keeps_counters(svc):
    """invalidate(code) removes entry but does NOT reset counters."""
    svc.evaluate_batch([GOOD_CODE])        # miss
    svc.evaluate_batch([GOOD_CODE])        # hit
    svc.invalidate(GOOD_CODE)
    stats = svc.cache_stats()
    # Counters preserved; entry removed.
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["size"] == 0


def test_hit_rate_with_only_hits(svc):
    """hit_rate == 1.0 when all accesses are hits."""
    svc.evaluate_batch([GOOD_CODE])        # miss
    svc.evaluate_batch([GOOD_CODE])        # hit
    svc.evaluate_batch([GOOD_CODE])        # hit
    stats = svc.cache_stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 2 / 3


def test_multiple_distinct_codes(svc):
    """Each distinct code is a separate miss."""
    codes = [
        "def f(x):\n    return x + 1\n",
        "def f(x):\n    return x + 2\n",
        "def f(x):\n    return x + 3\n",
    ]
    svc.evaluate_batch(codes)
    stats = svc.cache_stats()
    assert stats["misses"] == 3
    assert stats["hits"] == 0
    assert stats["size"] == 3

    # Re-evaluate all: 3 hits.
    svc.evaluate_batch(codes)
    stats = svc.cache_stats()
    assert stats["misses"] == 3
    assert stats["hits"] == 3
    assert stats["hit_rate"] == 0.5
