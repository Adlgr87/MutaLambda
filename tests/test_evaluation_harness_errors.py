"""Harness faults must never be laundered into fitness scores.

The distinction this module defends:

* A candidate that crashes, loops forever or fails its security scan has been
  *evaluated*. ``SubprocessRunner.run`` catches that internally and returns an
  ``EvalResult`` with ``passed=False``. That is a verdict and it is cacheable.
* The evaluation harness itself dying (broken pool, pickling failure, import
  error in a worker) means the candidate was *never evaluated*. Its quality is
  unknown. Scoring it as "worst" and caching that verdict silently deletes
  viable genomes from the population for the rest of the run, because the cache
  key (code + tests + env) is stable.

Before these tests, the pool error path conflated the two: every exception
became ``FitnessVector.worst()`` and was written straight into the cache.
"""

from __future__ import annotations

import logging
import pickle
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool

import pytest

from mutalambda_core.evaluation_service import (
    EvaluationService,
    WorkerFailure,
    _pool_worker,
)

GOOD_CODE = "def f():\n    return 1\n"
TESTS = [{"function": "f", "args": [], "expected": 1}]


class _ScriptedPool:
    """Executor stub whose first N jobs die from an injected harness fault."""

    def __init__(self, exc, fail_first=1, fail_mode="raise"):
        self.exc = exc
        self.fail_first = fail_first
        self.fail_mode = fail_mode
        self.calls = 0

    def submit(self, fn, args):
        fut: Future = Future()
        self.calls += 1
        if self.calls <= self.fail_first:
            if self.fail_mode == "raise":
                fut.set_exception(self.exc)
            else:  # worker returned a captured failure instead of raising
                # Raise and catch for real so the exception carries a genuine
                # __traceback__, exactly as it would inside a live worker.
                try:
                    raise self.exc
                except type(self.exc) as caught:
                    fut.set_result(WorkerFailure.from_exception(caught))
        else:
            fut.set_result(fn(args))
        return fut


@pytest.fixture
def svc():
    s = EvaluationService(test_cases=list(TESTS), max_workers=2, cache_enabled=True)
    yield s
    s.shutdown()


# ── The worker contract ────────────────────────────────────────────────────


def test_worker_returns_failure_object_instead_of_raising(monkeypatch):
    """An exception in the worker body comes back as data, with a traceback."""

    def boom(*_a, **_k):
        raise RuntimeError("simulated harness explosion")

    monkeypatch.setattr(
        "mutalambda_core.evaluation_service.SubprocessRunner", boom
    )
    out = _pool_worker((GOOD_CODE, TESTS, 5.0, 256, False, True))

    assert isinstance(out, WorkerFailure)
    assert out.exc_type == "RuntimeError"
    assert "simulated harness explosion" in out.exc_message
    # The child traceback must survive, otherwise the operator is debugging blind.
    assert "Traceback" in out.traceback_text
    assert "simulated harness explosion" in out.traceback_text


def test_worker_failure_is_picklable():
    """It has to cross a process boundary, so it must survive pickling."""
    wf = WorkerFailure.from_exception(ValueError("x" * 50))
    assert pickle.loads(pickle.dumps(wf)) == wf


def test_worker_returns_evalresult_for_a_crashing_candidate():
    """Candidate faults are verdicts, NOT harness failures."""
    out = _pool_worker(("def f():\n    raise ZeroDivisionError()\n", TESTS, 5.0, 256, False, True))
    assert not isinstance(out, WorkerFailure)
    assert out.passed is False


# ── The parent contract ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc",
    [
        BrokenProcessPool("worker terminated abruptly"),
        ConnectionResetError("transport died"),
        OSError("too many open files"),
        pickle.PicklingError("cannot pickle result"),
        RuntimeError("unexpected harness bug"),
    ],
    ids=["broken-pool", "conn-reset", "oserror", "pickling", "generic"],
)
def test_transient_harness_fault_is_retried_not_scored(svc, monkeypatch, exc):
    """Good code must survive a one-off infrastructure fault."""
    pool = _ScriptedPool(exc, fail_first=1)
    monkeypatch.setattr(EvaluationService, "_get_ready_pool", lambda self: pool)

    result = svc.evaluate_batch([GOOD_CODE])[0]

    assert result.passed is True, f"{type(exc).__name__} was scored instead of retried"
    assert "evaluation_error" not in result.metrics
    assert svc.harness_stats() == {"harness_failures": 1, "harness_recoveries": 1}


def test_worker_captured_failure_is_also_retried(svc, monkeypatch):
    """The returned-WorkerFailure path gets the same treatment as a raise."""
    pool = _ScriptedPool(RuntimeError("worker body blew up"), fail_first=1, fail_mode="return")
    monkeypatch.setattr(EvaluationService, "_get_ready_pool", lambda self: pool)

    result = svc.evaluate_batch([GOOD_CODE])[0]

    assert result.passed is True
    assert svc.harness_stats()["harness_recoveries"] == 1


def test_infra_failure_is_never_cached(svc, monkeypatch):
    """Regression: a transient fault used to condemn good code for the whole run.

    The cache key is code+tests+env, so one cached infrastructure error made the
    candidate permanently unevaluatable — it could never win selection again.
    """
    pool = _ScriptedPool(BrokenProcessPool("died"), fail_first=1)
    monkeypatch.setattr(EvaluationService, "_get_ready_pool", lambda self: pool)
    # Also break the serial retry so the first batch ends genuinely unevaluated.
    monkeypatch.setattr(svc, "harness_retries", 0)

    first = svc.evaluate_batch([GOOD_CODE])[0]
    assert first.metrics.get("evaluation_error") == 1.0

    # Pool is healthy again; the same code must be re-evaluated, not served
    # from a poisoned cache entry.
    monkeypatch.undo()
    second = svc.evaluate_batch([GOOD_CODE])[0]

    assert second.passed is True, "cache served a stale infrastructure failure"
    assert "evaluation_error" not in second.metrics


def test_unrecoverable_failure_is_flagged_not_silently_worst(svc, monkeypatch):
    """When every retry fails, say so in machine-readable form."""
    pool = _ScriptedPool(BrokenProcessPool("permanently dead"), fail_first=99)
    monkeypatch.setattr(EvaluationService, "_get_ready_pool", lambda self: pool)

    def always_broken(*_a, **_k):
        raise OSError("serial retry also unavailable")

    monkeypatch.setattr(
        "mutalambda_core.evaluation_service.SubprocessRunner", always_broken
    )

    result = svc.evaluate_batch([GOOD_CODE])[0]

    # Flagged as "never measured", distinct from "measured and bad".
    assert result.metrics["evaluation_error"] == 1.0
    assert result.passed is False
    assert svc.harness_stats()["harness_recoveries"] == 0


def test_a_crashing_candidate_is_not_flagged_as_harness_error(svc):
    """The inverse guard: genuinely bad code must stay a normal verdict."""
    result = svc.evaluate_batch(["def f():\n    raise ZeroDivisionError()\n"])[0]

    assert result.passed is False
    assert "evaluation_error" not in result.metrics, "candidate fault misread as infra fault"
    assert svc.harness_stats()["harness_failures"] == 0


def test_crashing_candidate_cannot_outrank_a_correct_one(svc):
    """A candidate that crashes must never look 'faster' than one that works."""
    good, bad = svc.evaluate_batch([GOOD_CODE, "def f():\n    raise RuntimeError()\n"])

    assert good.passed and not bad.passed
    assert good.score > bad.score
    assert bad.fitness.latency_p50 >= good.fitness.latency_p50 or bad.score <= -1.0


def test_full_traceback_reaches_the_log(svc, monkeypatch, caplog):
    """The operator must get the child traceback, not a one-line summary."""
    pool = _ScriptedPool(RuntimeError("deep failure"), fail_first=1, fail_mode="return")
    monkeypatch.setattr(EvaluationService, "_get_ready_pool", lambda self: pool)

    with caplog.at_level(logging.ERROR, logger="MutaLambda"):
        svc.evaluate_batch([GOOD_CODE])

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "Evaluation harness failed" in logged
    assert "deep failure" in logged
    assert "Traceback" in logged, "traceback was discarded"


def test_partial_batch_failure_isolates_the_affected_candidate(svc, monkeypatch):
    """One bad worker must not take down its whole batch."""
    pool = _ScriptedPool(BrokenProcessPool("one worker died"), fail_first=1)
    monkeypatch.setattr(EvaluationService, "_get_ready_pool", lambda self: pool)

    codes = [GOOD_CODE, "def f():\n    return 1  # variant\n", "def f():\n    return 1  # v2\n"]
    results = svc.evaluate_batch(codes)

    assert len(results) == 3
    assert all(r is not None for r in results)
    assert all(r.passed for r in results), "a pool glitch leaked into sibling candidates"
    assert svc.harness_stats()["harness_failures"] == 1
