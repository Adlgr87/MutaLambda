"""Tests for the MicroVMRunner (bwrap-based namespace isolation).

These tests verify:
1. Functional correctness via the factory ``create_runner(mode="microvm")``.
2. Security scanning is enforced before execution.
3. bwrap availability is detected and reported gracefully.
"""
from __future__ import annotations

import shutil

import pytest

from runners import MicroVMRunner, EvalResult, create_runner, scan_code_security


@pytest.fixture
def microvm_factory():
    return lambda **kw: create_runner(mode="microvm", timeout_sec=5.0, **kw)


@pytest.fixture
def simple_tests():
    return [{"function": "add", "args": [2, 3], "expected": 5}]


# ── Functional correctness ────────────────────────────────────────────────────

def test_microvm_runner_basic_pass(simple_tests):
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    code = "def add(a, b):\n    return a + b\n"
    result = MicroVMRunner(timeout_sec=5.0, enforce_ast_scan=False).run(code, simple_tests)
    assert result.passed == 1
    assert result.metrics.get("correctness") == 1.0


def test_microvm_runner_factory(microvm_factory, simple_tests):
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    runner = microvm_factory(enforce_ast_scan=False)
    code = "def add(a, b):\n    return a + b\n"
    result = runner.run(code, simple_tests)
    assert isinstance(result, EvalResult)
    assert result.passed == 1


def test_microvm_runner_quick_task():
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    runner = MicroVMRunner(timeout_sec=5.0, enforce_ast_scan=False)
    code = "def quick():\n    return 42\n"
    tests = [{"function": "quick", "args": [], "expected": 42}]
    result = runner.run(code, tests)
    assert result.passed == 1


# ── Security scanning ─────────────────────────────────────────────────────────

def test_microvm_runner_blocks_import_os(simple_tests):
    """AST scan must block dangerous code before execution."""
    runner = MicroVMRunner(enforce_ast_scan=True, timeout_sec=5.0)
    code = "import os\n" + "def add(a, b):\n    return a + b\n"
    result = runner.run(code, simple_tests)
    assert "security_scan" in result.stderr or "security" in (result.stderr or "").lower()


def test_microvm_runner_blocks_exec(simple_tests):
    """AST scan must block exec() calls."""
    runner = MicroVMRunner(enforce_ast_scan=True, timeout_sec=5.0)
    code = 'def add(a, b):\n    exec("import os")\n    return a + b\n'
    result = runner.run(code, simple_tests)
    assert "security_scan" in result.stderr or "security" in (result.stderr or "").lower()


def test_microvm_runner_ast_scan_disabled_allows(simple_tests):
    """With enforce_ast_scan=False, safe code should execute via bwrap."""
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    runner = MicroVMRunner(enforce_ast_scan=False, timeout_sec=5.0)
    code = "def add(a, b):\n    return a + b\n"
    result = runner.run(code, simple_tests)
    assert result.passed == 1


# ── bwrap availability ────────────────────────────────────────────────────────

def test_microvm_runner_bwrap_missing():
    """When bwrap is missing, runner should return graceful error."""
    runner = MicroVMRunner(timeout_sec=5.0)
    # The __post_init__ warns but doesn't raise. We test that the runner
    # handles bwrap not found gracefully via the FileNotFoundError path.
    # We simulate by patching the bwrap command to a non-existent path.
    import runners
    original_build = runner._build_sandbox
    def fake_build(python_bin):
        cmd = original_build(python_bin)
        cmd[0] = "/nonexistent/bwrap"  # Simulate bwrap missing
        return cmd
    runner._build_sandbox = fake_build
    code = "def f(): pass\n"
    tests = [{"function": "f", "args": [], "expected": None}]
    result = runner.run(code, tests)
    # Should hit FileNotFoundError for bwrap
    assert "bwrap" in result.stderr.lower() or result.stdout == ""


# ── Integration with existing patterns ────────────────────────────────────────

def test_microvm_runner_passes_expressions(simple_tests):
    """MicroVMRunner should handle expression-based tests like SubprocessRunner."""
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    runner = MicroVMRunner(enforce_ast_scan=False, timeout_sec=5.0)
    code = "def multiply(x, y):\n    return x * y\n"
    tests = [{"function": "multiply", "args": [3, 7], "expected": 21}]
    result = runner.run(code, tests)
    assert result.passed == 1
    assert result.metrics.get("correctness") == 1.0


def test_microvm_runner_multiple_test_cases():
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    runner = MicroVMRunner(enforce_ast_scan=False, timeout_sec=5.0)
    code = "def factorial(n):\n    return 1 if n < 2 else n * factorial(n-1)\n"
    tests = [
        {"function": "factorial", "args": [0], "expected": 1},
        {"function": "factorial", "args": [1], "expected": 1},
        {"function": "factorial", "args": [5], "expected": 120},
    ]
    result = runner.run(code, tests)
    assert result.metrics["tests_passed"] == 3.0
    assert result.metrics["correctness"] == 1.0


# ── EvaluationService integration (Manus P1 observability) ──────────────────────

def test_evaluation_service_last_mode_microvm_serial():
    """Manus P1: EvaluationService.last_mode reflects the active runner/serial mode."""
    from evaluation_service import EvaluationService
    svc = EvaluationService(
        test_cases=[{"function": "add", "args": [1, 1], "expected": 2}],
        runner_mode="microvm",
        timeout_sec=3.0,
        max_workers=1,
    )
    # Trigger evaluate_batch (single code forces serial microvm path).
    svc.evaluate_batch(["def add(a,b): return a+b"])
    assert svc.last_mode is not None
    assert "microvm" in svc.last_mode, f"expected microvm in mode, got {svc.last_mode!r}"


def test_evaluation_service_last_mode_cache_only():
    """Manus P1: when all results are cached, last_mode='cache-only'."""
    from evaluation_service import EvaluationService
    svc = EvaluationService(
        test_cases=[{"function": "add", "args": [1, 1], "expected": 2}],
        runner_mode="subprocess",
        timeout_sec=3.0,
        max_workers=4,
        cache_enabled=True,
    )
    code = "def add(a,b): return a+b"
    svc.evaluate_batch([code])  # populate cache
    svc.evaluate_batch([code])  # second pass: all cached
    assert svc.last_mode == "cache-only"


def test_evaluation_service_last_mode_pool_parallel():
    """Manus P1: subprocess mode with multiple workers sets parallel mode tag."""
    from evaluation_service import EvaluationService
    svc = EvaluationService(
        test_cases=[{"function": "add", "args": [1, 1], "expected": 2}],
        runner_mode="subprocess",
        timeout_sec=3.0,
        max_workers=2,
        cache_enabled=False,
    )
    svc.evaluate_batch(["def add(a,b): return a+b"])
    assert svc.last_mode and svc.last_mode.startswith("pool-parallel")

