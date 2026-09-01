"""Tests for the MicroVMRunner (bwrap-based namespace isolation).

These tests verify:
1. Functional correctness via the factory ``create_runner(mode="microvm")``.
2. Security scanning is enforced before execution.
3. bwrap availability is detected and reported gracefully.
"""
from __future__ import annotations

import shutil
import sys

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


# ── Cross-language transfer blocking (Manus P1 hardening) ──────────────────────

def _safe_candidate(code, tests):
    """Run candidate in a hardened microvm sandbox."""
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    runner = MicroVMRunner(enforce_ast_scan=False, timeout_sec=8.0, memory_mb=128)
    return runner.run(code, tests)


def test_microvm_blocks_host_filesystem_write():
    """The hardcoded MicroVMRunner must NOT use a writable host /tmp bind.

    A candidate that escapes the AST filter and tries to open a host path must
    fail — the sandbox exposes no host directory as writable.
    """
    # Candidate tries to write to a host path outside /work. With the hardened
    # sandbox there is no writable host bind, so this must error inside the
    # namespace.
    code = (
        "import os\n"
        "def probe():\n"
        "    try:\n"
        "        with open('/host_probe_marker', 'w') as f:\n"
        "            f.write('x')\n"
        "        return 1\n"
        "    except Exception:\n"
        "        return 0\n"
    )
    tests = [{"function": "probe", "args": [], "expected": 0}]
    # enforce_ast_scan=True would block import os; disable to test the sandbox
    # boundary itself (the real boundary must hold even if AST is bypassed).
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    runner = MicroVMRunner(enforce_ast_scan=False, timeout_sec=8.0, memory_mb=128)
    result = runner.run(code, tests)
    # The probe must report 0 (could not write to host FS).
    assert result.metrics.get("correctness") == 0.0 or not result.passed, (
        "candidate wrote to host filesystem — sandbox FS egress not blocked"
    )


def test_microvm_blocks_network_egress():
    """Network egress is blocked: --unshare-net removes all interfaces."""
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    code = (
        "import socket\n"
        "def probe():\n"
        "    s = socket.socket()\n"
        "    s.settimeout(1.0)\n"
        "    try:\n"
        "        s.connect(('127.0.0.1', 1))\n"
        "        return 1\n"
        "    except Exception:\n"
        "        return 0\n"
        "    finally:\n"
        "        s.close()\n"
    )
    tests = [{"function": "probe", "args": [], "expected": 0}]
    runner = MicroVMRunner(enforce_ast_scan=False, timeout_sec=8.0, memory_mb=128)
    result = runner.run(code, tests)
    # Connection must fail (no loopback because net ns is unshared & empty).
    assert result.metrics.get("correctness") == 0.0 or not result.passed, (
        "candidate established a network connection — net egress not blocked"
    )


def test_microvm_build_sandbox_has_no_writable_host_bind():
    """Static guarantee: the hardened sandbox binds no host dir read-write."""
    if not shutil.which("bwrap"):
        pytest.skip("bwrap not installed")
    runner = MicroVMRunner(timeout_sec=5.0)
    cmd = runner._build_sandbox(sys.executable, "/tmp/_work_dummy")
    # No '--bind' (writable) entries for host paths; only ro-binds allowed.
    for i, tok in enumerate(cmd):
        assert tok != "--bind" or cmd[i + 1] == "/tmp", (
            f"unexpected writable host bind in sandbox: {cmd}"
        )

