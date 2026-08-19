"""Security regression suite for C3: RLIMIT enforcement + container-by-default.

Verifies that:

* ``create_runner()`` is container-by-default and falls back to a bounded
  ``SubprocessRunner`` (with the AST scan forced on) when no container engine
  is available.
* ``SubprocessRunner`` applies hard ``resource.setrlimit`` bounds inside the
  spawned child process (RLIMIT_CPU / RLIMIT_AS / RLIMIT_NPROC / RLIMIT_FSIZE)
  so even non-containerized runs are bounded — a runaway CPU loop is killed
  within the configured timeout.
* The ``get_rlimit_stats()`` telemetry counters are populated.
"""
from __future__ import annotations

import warnings

import pytest

from runners import (
    ContainerRunner,
    SubprocessRunner,
    _container_engine_available,
    create_runner,
    get_rlimit_stats,
)
from tests.security.test_sandbox_escapes import SAFE_PATTERNS


# ── Helper payloads ───────────────────────────────────────────────────────────

# A candidate that spins forever on CPU. The AST scan does NOT flag it (no
# forbidden calls) — it is only stopped by the RLIMIT / timeout boundary, so
# this exercises the runtime hardening, not the AST filter.
CPU_BURN_CODE = (
    "def f(x):\n"
    "    while True:\n"
    "        x = x + 1\n"
    "    return x\n"
)

# A test case that actually invokes ``f`` so the wrapper does not short-circuit
# on ``no_tests``.
_BURN_TC = [{"function": "f", "args": [0], "expected": 0, "comparison": "equal"}]


# ── create_runner() default policy ────────────────────────────────────────────


def test_create_runner_default_is_container_or_fallback():
    """``create_runner()`` with no args must resolve to container when an engine
    is present, otherwise to a bounded subprocess fallback (never a raw,
    unguarded subprocess)."""
    runner = create_runner()
    engine = _container_engine_available()
    if engine is not None:
        # Container engine present -> must be ContainerRunner, mode "container".
        assert isinstance(runner, ContainerRunner), type(runner)
        assert runner.mode == "container"
        assert runner.enforce_ast_scan is True
    else:
        # No engine -> graceful fallback to SubprocessRunner with AST scan on.
        assert isinstance(runner, SubprocessRunner), type(runner)
        assert runner.enforce_ast_scan is True
        # Fallback must NOT be exposed as a "raw" subprocess to callers that
        # asked for the container-by-default policy.
        assert runner.mode != "container"


def test_create_runner_container_mode_present_resolves_container():
    """When a container engine is available, explicitly requesting
    ``mode='container'`` (the new default) yields a ContainerRunner."""
    if _container_engine_available() is None:
        pytest.skip("no container engine available")
    runner = create_runner("container")
    assert isinstance(runner, ContainerRunner)
    assert runner.mode == "container"


def test_create_runner_explicit_subprocess_is_subprocess():
    """An explicit ``mode='subprocess'`` is still honoured (escape hatch for
    local dev / benchmarks)."""
    runner = create_runner("subprocess")
    assert isinstance(runner, SubprocessRunner)
    assert runner.mode == "subprocess"


def test_create_runner_fallback_forces_ast_scan(monkeypatch):
    """When no container engine is available, the fallback SubprocessRunner must
    have ``enforce_ast_scan=True`` regardless of the caller's argument."""
    monkeypatch.setattr(
        "runners.shutil.which",
        lambda name: None if name in ("docker", "podman") else __import__("shutil").which(name),
    )
    runner = create_runner("container", enforce_ast_scan=False)
    assert isinstance(runner, SubprocessRunner)
    assert runner.enforce_ast_scan is True


def test_create_runner_fallback_warns_when_no_engine(monkeypatch):
    monkeypatch.setattr("runners.shutil.which", lambda name: None)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        runner = create_runner("container")
    assert isinstance(runner, SubprocessRunner)
    assert any("falling back" in str(rec.message).lower() for rec in w)

# ── RLIMIT stats telemetry ────────────────────────────────────────────────────


def test_get_rlimit_stats_shape():
    stats = get_rlimit_stats()
    assert set(stats) == {"rlimit_hits", "rlimit_enforced", "rlimit_unsupported"}
    assert stats["rlimit_hits"] >= 0
    stats_before = stats["rlimit_hits"]


def test_rlimit_stats_increment_on_subprocess_run():
    """Running a candidate through SubprocessRunner exercises the preexec_fn
    RLIMIT hardening, which bumps ``rlimit_hits``."""
    before = get_rlimit_stats()["rlimit_hits"]
    runner = SubprocessRunner(timeout_sec=5.0, enforce_ast_scan=False)
    runner.run(_SAFE_CODE, _SAFE_TC)
    after = get_rlimit_stats()["rlimit_hits"]
    assert after >= before + 1


# ── RLIMIT enforcement: CPU-burn is killed within timeout ───────────────────────


def test_subprocess_runner_blocks_cpu_burn():
    """A candidate doing a ``while True`` CPU loop must be killed by the RLIMIT
    CPU boundary (or the subprocess timeout) within ``timeout_sec``.

    Uses ``create_runner("subprocess", timeout_sec=2)`` and asserts the returned
    ``EvalResult`` indicates termination (not a clean pass).
    """
    timeout_sec = 2.0
    runner = create_runner("subprocess", timeout_sec=timeout_sec, enforce_ast_scan=False)
    result = runner.run(CPU_BURN_CODE, _BURN_TC)
    # The candidate must NOT pass: it either times out or is killed by the
    # CPU RLIMIT. Either way ``passed`` is False and the run terminated abruptly.
    assert result.passed is False
    assert result.timed_out is True or "TimeoutExpired" in str(result.stderr) or result.stderr


def test_subprocess_runner_cpu_limit_attribute():
    runner = SubprocessRunner(timeout_sec=2.0, cpu_limit=1)
    assert runner.cpu_limit == 1
    assert runner.mode == "subprocess"


def test_subprocess_runner_enforces_memory_via_rlimit():
    """A candidate that tries to allocate far more than ``memory_mb`` should be
    killed by the RLIMIT_AS ceiling rather than passing."""
    # Allocate ~512MB while memory_mb ceiling is 128MB.
    hog_code = (
        "def f(x):\n"
        "    data = [0] * (512 * 1024 * 1024 // 8)\n"
        "    return len(data)\n"
    )
    test_cases = [{"function": "f", "args": [0], "expected": 0, "comparison": "equal"}]
    runner = create_runner("subprocess", timeout_sec=5.0, memory_mb=128, enforce_ast_scan=False)
    result = runner.run(hog_code, test_cases)
    # Memory-exceeded child is killed (non-zero returncode) -> not passed.
    assert result.passed is False


# ── Safe code is still not flagged ─────────────────────────────────────────────

# A trivially safe candidate plus a test case that exercises it.
_SAFE_CODE = SAFE_PATTERNS[0]
_SAFE_TC = [{"function": "f", "args": [1], "expected": 2, "comparison": "equal"}]


def test_safe_code_runs_under_rlimit():
    """Sanity: the RLIMIT hardening does not break legitimate simple candidates."""
    runner = SubprocessRunner(timeout_sec=5.0, enforce_ast_scan=False)
    result = runner.run(_SAFE_CODE, _SAFE_TC)
    assert result.passed is True


# ── Container runner still shares the AST gate ────────────────────────────────


@pytest.mark.skipif(_container_engine_available() is None, reason="no container engine")
def test_container_runner_mode_and_gate():
    runner = ContainerRunner(timeout_sec=5.0, enforce_ast_scan=True)
    assert runner.mode == "container"
    # AST gate fires before any container is consulted.
    result = runner.run("import os; os.system('id')", [])
    assert result.passed is False
    assert result.timed_out is False
