"""Candidate execution backends for MutaLambda evaluation.

Security model
--------------
- AST scanning is an early filter, not a security boundary.
- SubprocessRunner is for local development only.
- ContainerRunner is the recommended isolation boundary when Docker/Podman
  is available (network=none, read-only rootfs, dropped capabilities).
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import math
import warnings
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from mutalambda.code_hash import stable_code_hash
from mutalambda.comparison import COMPARATORS, compare_values, register_predicate
from mutalambda.fitness_vector import FitnessVector
from mutalambda.models import EvalResult

logger = logging.getLogger("MutaLambda")


# Whether the local SubprocessRunner has been used. We warn (once) that it is
# not a real sandbox, unless the caller explicitly opts in via env var.
_LOCAL_RUNNER_WARNED = False

# compare_values / stable_code_hash: see comparison.py and code_hash.py


def tests_hash(test_cases: List[Dict]) -> str:
    payload = json.dumps(test_cases, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── AST early filter (SecurityVisitor) ────────────────────────────────────────
#
# Security model
# --------------
# AST scanning is an *early filter*, not a full sandbox boundary. The real
# boundary is the CandidateRunner (subprocess ulimits / container
# namespace isolation).  The visitor is intentionally *conservative*: it
# errs on the side of blocking candidate code that looks like a sandbox
# escape, and surfaces detailed findings (with source positions) so callers
# can decide how to react (reject, log, or escalate).
#
# It is designed to defeat the classic textual evasion tricks:
#   * getattr(__builtins__, "exec"/"eval"/...)
#   * import os as _o ; _o.system(...)          (alias of a forbidden module)
#   * f = exec ; f("...")                       (alias of a forbidden call)
#   * chr(...) string reconstruction of dangerous call names
#   * __import__("os"), importlib.import_module("os")

from dataclasses import dataclass


# Modules whose import would grant filesystem / network / process-control
# capability. ``sys`` and ``json`` are intentionally allowed — candidates
# (and the generated harness) legitimately use them.
_FORBIDDEN_IMPORTS = frozenset({
    "os",
    "subprocess",
    "socket",
    "pathlib",
    "shutil",
    "ctypes",
    "multiprocessing",
    "importlib",
    "http",
    "urllib",
    "requests",
    "ftplib",
    "pickle",
    "marshal",
    "shelve",
    "pty",
    "commands",
})

# Calls that are inherently dynamic / unsafe regardless of argument.
_FORBIDDEN_DYNAMIC_CALLS = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
    "vars",
    "dir",
    "breakpoint",
})

# Attribute calls on specific module objects that are known escape hatches.
_FORBIDDEN_ATTR_CALLS = {
    ("os", "system"), ("os", "popen"), ("os", "exec"), ("os", "execv"),
    ("os", "execve"), ("os", "execvpe"), ("os", "execvp"),
    ("os", "spawn"), ("os", "spawnl"), ("os", "spawnle"),
    ("os", "fork"), ("os", "kill"),
    ("subprocess", "Popen"), ("subprocess", "call"), ("subprocess", "check_call"),
    ("subprocess", "check_output"), ("subprocess", "run"), ("subprocess", "getoutput"),
    ("shutil", "rmtree"), ("shutil", "remove"), ("shutil", "move"), ("shutil", "copy"),
    ("shutil", "copyfile"), ("shutil", "copytree"),
    ("importlib", "import_module"),
    ("pickle", "loads"), ("pickle", "load"), ("pickle", "dumps"),
    ("marshal", "loads"), ("marshal", "load"),
    ("ctypes", "cdll"), ("ctypes", "pythonapi"),
    ("pathlib", "Path"),
}

# Names that should never be reachable from candidate code.
_SENSITIVE_NAMES = frozenset({
    "__builtins__", "__import__", "__globals__", "__locals__",
    "globals", "locals",
})


@dataclass
class SecurityFinding:
    """A single security finding with source position for reporting."""

    kind: str
    message: str
    lineno: int = 0
    col: int = 0

    def __str__(self) -> str:
        return self.message


class SecurityVisitor(ast.NodeVisitor):
    """AST visitor that flags sandbox-escape primitives.

    The visitor performs a *bounded* local dataflow analysis: it records
    simple ``name = <forbidden>`` assignments so that indirect usage such as
    ``f = exec ; f("...")`` is caught, and it flags any reference to
    ``__builtins__`` or use of ``getattr`` (the canonical attribute-lookup
    escape vector).  It is still not a full dataflow / points-to analysis,
    so the subprocess / container boundary remains authoritative.
    """

    def __init__(self) -> None:
        self.findings: List[SecurityFinding] = []
        # Names bound to a forbidden dynamic call, e.g. ``f = exec``.
        self._call_aliases: Dict[str, str] = {}
        # Names bound to a forbidden module, e.g. ``m = os`` (rare but possible).
        self._module_aliases: Dict[str, str] = {}

    # ── helpers ───────────────────────────────────────────────────────────

    def _add(self, kind: str, message: str, node: ast.AST) -> None:
        self.findings.append(
            SecurityFinding(
                kind=kind,
                message=message,
                lineno=getattr(node, "lineno", 0),
                col=getattr(node, "col_offset", 0),
            )
        )

    @staticmethod
    def _module_root(node: ast.AST) -> Optional[str]:
        """Resolve the root module name for an import alias target."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return SecurityVisitor._module_root(node.value)
        return None

    # ── visit methods ─────────────────────────────────────────────────────

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _FORBIDDEN_IMPORTS:
                self._add("forbidden_import", f"import:{root}", node)
            # Track aliases: ``import os as _o`` -> _o bound to os
            if root in _FORBIDDEN_IMPORTS and alias.asname:
                self._module_aliases[alias.asname] = root
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".")[0]
            if root in _FORBIDDEN_IMPORTS:
                self._add("forbidden_import", f"import_from:{root}", node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # Detect ``f = exec`` / ``g = eval`` / ``h = compile``
        if isinstance(node.value, ast.Name) and node.value.id in _FORBIDDEN_DYNAMIC_CALLS:
            alias = node.value.id
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._call_aliases[target.id] = alias
                    self._add("dynamic_alias", f"alias_of_forbidden:{alias}", node)
        # Detect ``m = os`` style alias of a forbidden module
        if isinstance(node.value, ast.Name) and node.value.id in self._module_aliases.values():
            pass  # already tracked via import alias handling
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _SENSITIVE_NAMES and isinstance(node.ctx, ast.Load):
            self._add("sensitive_name", f"sensitive_name:{node.id}", node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # ``__builtins__.exec`` / ``getattr(__builtins__, ...)`` style access
        if isinstance(node.value, ast.Name) and node.value.id == "__builtins__":
            self._add("dunder_access", f"access:__builtins__", node)
        owner = self._module_root(node.value)
        key = (owner, node.attr) if owner else (None, node.attr)
        if key in _FORBIDDEN_ATTR_CALLS:
            if owner:
                self._add("forbidden_attr_call", f"call:{owner}.{node.attr}", node)
            else:
                self._add("forbidden_attr_call", f"call:{node.attr}", node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Direct dynamic call: eval(...), exec(...)
        if isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_DYNAMIC_CALLS:
                self._add("forbidden_call", f"call:{node.func.id}", node)
            # Indirection: previously assigned alias ``f = exec ; f(...)``
            if node.func.id in self._call_aliases:
                real = self._call_aliases[node.func.id]
                self._add("forbidden_call", f"call_via_alias:{real}", node)
        # getattr(...) — canonical escape vector (getattr(__builtins__, "exec"))
        if isinstance(node.func, ast.Name) and node.func.id == "getattr":
            self._add("getattr_call", "getattr_call", node)
        # open(...) of any kind — candidates should never do file I/O
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            self._add("forbidden_call", "call:open", node)
        # chr(...) — string reconstruction of dangerous call names
        if isinstance(node.func, ast.Name) and node.func.id == "chr":
            self._add("chr_call", "chr_call", node)
        # module.method attribute calls captured by visit_Attribute already,
        # but also catch bare module calls resolved through aliases.
        if isinstance(node.func, ast.Attribute):
            owner = self._module_root(node.func.value)
            if owner:
                key = (owner, node.func.attr)
                if key in _FORBIDDEN_ATTR_CALLS:
                    self._add("forbidden_attr_call", f"call:{owner}.{node.func.attr}", node)
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        # ``**{**}`` unpacking not relevant; placeholder for future hooks.
        self.generic_visit(node)


def scan_findings(code: str) -> List[SecurityFinding]:
    """Parse ``code`` and return detailed :class:`SecurityFinding` list.

    Returns an empty list for syntax errors (a syntax error means the code
    cannot be executed as Python, so it is not an escape risk *per se*; the
    caller's syntax check should reject it). Use :func:`scan_code_security`
    if you want a ``syntax_error:`` entry instead.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    visitor = SecurityVisitor()
    visitor.visit(tree)
    return visitor.findings


def scan_code_security(code: str) -> List[str]:
    """Early AST security filter for candidate code.

    Returns human-readable finding strings (legacy prefix format preserved
    for backward compatibility) suitable for logging / rejection messages.
    This is an early filter, **not** a sandbox boundary — the real boundary
    is :class:`CandidateRunner` (subprocess ulimits / container isolation).
    """
    findings: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax_error:{exc}"]

    visitor = SecurityVisitor()
    visitor.visit(tree)
    seen: set[str] = set()
    for f in visitor.findings:
        if f.message not in seen:
            seen.add(f.message)
            findings.append(f.message)
    return findings


def _set_memory_limit(memory_mb: int) -> None:
    if memory_mb <= 0:
        return
    limit_bytes = int(memory_mb * 1024 * 1024)
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard == resource.RLIM_INFINITY or hard < 0 or hard > limit_bytes:
        hard = limit_bytes
    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, hard))


def build_wrapper_source(
    code_path: str,
    *,
    allow_expression_eval: bool = False,
) -> str:
    """Build the evaluation wrapper executed in the isolated process/container."""
    allow_expr = "True" if allow_expression_eval else "False"
    return "\n".join(
        [
            "import json",
            "import math",
            "import sys",
            "",
            f"CODE_PATH = {code_path!r}",
            f"ALLOW_EXPRESSION_EVAL = {allow_expr}",
            "",
            "def _load_namespace(path):",
            "    namespace = {'__name__': '__mutalambda_candidate__', '__file__': path}",
            "    with open(path, 'r', encoding='utf-8') as src:",
            "        source = src.read()",
            "    exec(compile(source, path, 'exec'), namespace, namespace)",
            "    return namespace",
            "",
            "def _compare(got, expected, comparison='equal'):",
            "    comparison = (comparison or 'equal').lower()",
            "    if comparison == 'equal':",
            "        return got == expected",
            "    if comparison == 'float_close':",
            "        try:",
            "            return math.isclose(float(got), float(expected), rel_tol=1e-9, abs_tol=1e-12)",
            "        except Exception:",
            "            return False",
            "    if comparison == 'array_allclose':",
            "        try:",
            "            import numpy as np",
            "            return bool(np.allclose(np.asarray(got), np.asarray(expected)))",
            "        except Exception:",
            "            return False",
            "    if comparison == 'contains':",
            "        try:",
            "            return expected in got",
            "        except TypeError:",
            "            return False",
            "    return got == expected",
            "",
            "def _run_case(namespace, tc):",
            "    if not isinstance(tc, dict):",
            "        raise TypeError('test case must be a dict')",
            "    if 'function' in tc:",
            "        fn_name = tc['function']",
            "        fn = namespace.get(fn_name)",
            "        if not callable(fn):",
            "            raise NameError(f'Function not found or not callable: {fn_name}')",
            "        args = tc.get('args', [])",
            "        kwargs = tc.get('kwargs', {})",
            "        return fn(*args, **kwargs)",
            "    if 'expression' in tc or 'assert' in tc:",
            "        if not ALLOW_EXPRESSION_EVAL:",
            "            raise RuntimeError(",
            "                'expression/assert tests require allow_expression_eval=True (dev mode)'",
            "            )",
            "        key = 'expression' if 'expression' in tc else 'assert'",
            "        value = eval(tc[key], namespace, namespace)",
            "        return bool(value) if key == 'assert' else value",
            "    raise KeyError(\"test case must define 'function' (preferred), or expression/assert in dev mode\")",
            "",
            "def _evaluate(namespace, test_cases):",
            "    if not test_cases:",
            "        return {'passed': 0, 'total': 1, 'details': [], 'error': 'no_tests'}",
            "    total = len(test_cases)",
            "    passed = 0",
            "    details = []",
            "    for idx, tc in enumerate(test_cases):",
            "        try:",
            "            got = _run_case(namespace, tc)",
            "            if 'expected' in tc:",
            "                ok = _compare(got, tc.get('expected'), tc.get('comparison', 'equal'))",
            "            else:",
            "                ok = bool(got)",
            "            if ok:",
            "                passed += 1",
            "            details.append({'index': idx, 'ok': bool(ok)})",
            "        except Exception as exc:",
            "            details.append({'index': idx, 'ok': False, 'error': str(exc)[:200]})",
            "    return {'passed': passed, 'total': total, 'details': details}",
            "",
            "def _main():",
            "    raw = sys.stdin.read() or '[]'",
            "    try:",
            "        test_cases = json.loads(raw)",
            "    except Exception:",
            "        test_cases = []",
            "    if not isinstance(test_cases, list):",
            "        test_cases = []",
            "    try:",
            "        namespace = _load_namespace(CODE_PATH)",
            "    except Exception as exc:",
            "        report = {'passed': 0, 'total': max(1, len(test_cases)), 'details': [], 'load_error': str(exc)[:200]}",
            "        print(json.dumps(report, ensure_ascii=False))",
            "        return 1",
            "    report = _evaluate(namespace, test_cases)",
            "    print(json.dumps(report, ensure_ascii=False))",
            "    return 0 if report.get('passed', 0) >= report.get('total', 1) and report.get('total', 0) > 0 else 1",
            "",
            "if __name__ == '__main__':",
            "    raise SystemExit(_main())",
            "",
        ]
    )


def _metrics_from_report(
    code: str,
    elapsed: float,
    peak_mb: float,
    report: Dict[str, Any],
    returncode: int,
) -> EvalResult:
    passed = int(report.get("passed", 0))
    total = max(1, int(report.get("total", 1)))
    correctness = passed / max(total, 1)
    if report.get("error") == "no_tests":
        correctness = 0.0
        passed = 0
        total = 1

    num_tests = max(1, total)
    throughput = num_tests / max(elapsed, 1e-9)
    code_kb = max(1.0, len(code.encode("utf-8")) / 1024.0)
    try:
        tree = ast.parse(code)
        decision_points = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler, ast.BoolOp))
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                decision_points += len(node.orelse) > 0
        cyclomatic = 1 + decision_points
    except SyntaxError:
        cyclomatic = 1
    parsimony = 1.0 / (1.0 + cyclomatic / code_kb)

    fitness = FitnessVector(
        correctness=correctness,
        latency_p50=elapsed,
        latency_p99=elapsed,
        throughput=throughput,
        memory_peak_mb=peak_mb,
        parsimony=parsimony,
    )
    metrics: Dict[str, float] = {
        "latency": elapsed,
        "latency_p50": elapsed,
        "latency_p99": elapsed,
        "throughput": throughput,
        "memory_peak_mb": peak_mb,
        "parsimony": parsimony,
        "correctness": correctness,
        "cyclomatic_complexity": float(cyclomatic),
        "code_kb": code_kb,
        "tests_passed": float(passed),
        "tests_total": float(total),
    }
    return EvalResult(
        fitness=fitness,
        passed=(passed >= total and returncode == 0 and total > 0 and report.get("error") != "no_tests"),
        metrics=metrics,
        stdout="",
        stderr="",
        timed_out=False,
    )


def _timeout_result(timeout_sec: float) -> EvalResult:
    return EvalResult(
        fitness=FitnessVector(
            correctness=0.0,
            latency_p50=timeout_sec,
            latency_p99=timeout_sec,
            throughput=0.0,
            memory_peak_mb=float("inf"),
            parsimony=0.0,
        ),
        passed=False,
        metrics={"latency": timeout_sec, "correctness": 0.0, "error": "TimeoutExpired"},
        stdout="",
        stderr="[TIMEOUT]",
        timed_out=True,
    )


def _error_result(timeout_sec: float, error_str: str) -> EvalResult:
    return EvalResult(
        fitness=FitnessVector(
            correctness=0.0,
            latency_p50=timeout_sec,
            latency_p99=timeout_sec,
            throughput=0.0,
            memory_peak_mb=float("inf"),
            parsimony=0.0,
        ),
        passed=False,
        metrics={"latency": timeout_sec, "correctness": 0.0, "error": error_str[:200]},
        stdout="",
        stderr=error_str,
        timed_out="timeout" in error_str.lower(),
    )


def _parse_report(stdout: str, test_cases: List[Dict], returncode: int) -> Dict[str, Any]:
    lines = stdout.strip().split("\n")
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    if not test_cases and returncode == 0:
        # Untested candidates are never auto-correct under the remediation policy.
        return {"passed": 0, "total": 1, "details": [], "error": "no_tests"}
    raise ValueError("No valid JSON line found in subprocess stdout")


@runtime_checkable
class CandidateRunner(Protocol):
    """Protocol for isolated candidate execution."""

    def run(self, code: str, test_cases: list[dict]) -> EvalResult: ...


@dataclass
class SubprocessRunner:
    """Local development runner (subprocess + memory limit). Not a full sandbox.

    .. warning::
        The subprocess runner is **not** a real sandbox boundary. It relies only
        on ``RLIMIT_AS`` / timeout limits. For untrusted candidate code, prefer
        ``runner_mode="container"`` (Docker/Podman with ``--network=none``,
        read-only rootfs, ``--cap-drop=ALL``).
    """

    timeout_sec: float = 10.0
    memory_mb: int = 256
    allow_expression_eval: bool = False
    enforce_ast_scan: bool = True

    def __post_init__(self) -> None:
        global _LOCAL_RUNNER_WARNED
        if os.environ.get("MUTALAMBDA_UNSAFE_LOCAL") == "1":
            return
        if not _LOCAL_RUNNER_WARNED:
            _LOCAL_RUNNER_WARNED = True
            warnings.warn(
                "SubprocessRunner provides RLIMIT/timeout isolation only and is NOT a "
                "full sandbox. For untrusted code set runner_mode='container' "
                "(Docker/Podman: network=none, read-only rootfs, --cap-drop=ALL). "
                "Set MUTALAMBDA_UNSAFE_LOCAL=1 to silence this warning.",
                RuntimeWarning,
                stacklevel=2,
            )

    def run(self, code: str, test_cases: list[dict]) -> EvalResult:
        if self.enforce_ast_scan:
            findings = scan_code_security(code)
            if findings:
                return _error_result(self.timeout_sec, f"security_scan:{','.join(findings)}")

        tmp_path: Optional[str] = None
        wrapper_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(code)
                tmp_path = f.name
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(build_wrapper_source(tmp_path, allow_expression_eval=self.allow_expression_eval))
                wrapper_path = f.name

            preexec_fn = (lambda: _set_memory_limit(self.memory_mb)) if self.memory_mb > 0 else None
            start = time.perf_counter()
            proc = subprocess.run(
                [sys.executable, wrapper_path],
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                input=json.dumps(test_cases),
                preexec_fn=preexec_fn,
            )
            elapsed = time.perf_counter() - start
            try:
                usage = resource.getrusage(resource.RUSAGE_CHILDREN)
                peak_kb = float(usage.ru_maxrss)
                if sys.platform == "darwin":
                    peak_kb /= 1024.0
                peak_mb = peak_kb / 1024.0
            except (AttributeError, ValueError):
                peak_mb = 0.0
            try:
                report = _parse_report(proc.stdout, test_cases, proc.returncode)
            except Exception:
                report = {"passed": 0, "total": max(1, len(test_cases)), "details": []}
            result = _metrics_from_report(code, elapsed, peak_mb, report, proc.returncode)
            result.stdout = proc.stdout[:2000]
            result.stderr = proc.stderr[:2000]
            return result
        except subprocess.TimeoutExpired:
            return _timeout_result(self.timeout_sec)
        except Exception as exc:
            return _error_result(self.timeout_sec, str(exc)[:2000])
        finally:
            for path in (tmp_path, wrapper_path):
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass


@dataclass
class ContainerRunner:
    """Docker/Podman-backed runner with restrictive defaults.

    Requires a local container engine. Falls back is not automatic — callers
    should choose SubprocessRunner explicitly for local/dev mode.
    """

    timeout_sec: float = 10.0
    memory_mb: int = 256
    cpus: float = 0.5
    pids_limit: int = 64
    image: str = "python:3.11-slim"
    engine: Optional[str] = None  # docker | podman | auto
    allow_expression_eval: bool = False
    enforce_ast_scan: bool = True

    def _resolve_engine(self) -> str:
        if self.engine and self.engine != "auto":
            if shutil.which(self.engine):
                return self.engine
            raise RuntimeError(f"Container engine not found: {self.engine}")
        for name in ("docker", "podman"):
            if shutil.which(name):
                return name
        raise RuntimeError("No container engine found (docker/podman)")

    def run(self, code: str, test_cases: list[dict]) -> EvalResult:
        if self.enforce_ast_scan:
            findings = scan_code_security(code)
            if findings:
                return _error_result(self.timeout_sec, f"security_scan:{','.join(findings)}")

        workdir = tempfile.mkdtemp(prefix="mutalambda_c_")
        code_path = os.path.join(workdir, "candidate.py")
        wrapper_path = os.path.join(workdir, "wrapper.py")
        try:
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(code)
            # Inside the container the workdir is mounted at /work
            with open(wrapper_path, "w", encoding="utf-8") as f:
                f.write(
                    build_wrapper_source(
                        "/work/candidate.py",
                        allow_expression_eval=self.allow_expression_eval,
                    )
                )

            engine = self._resolve_engine()
            mem = f"{max(16, int(self.memory_mb))}m"
            cmd = [
                engine,
                "run",
                "--rm",
                "-i",
                "--network=none",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                f"--pids-limit={self.pids_limit}",
                f"--cpus={self.cpus}",
                f"--memory={mem}",
                "--user",
                "65534:65534",
                "-v",
                f"{workdir}:/work:ro",
                self.image,
                "python",
                "/work/wrapper.py",
            ]
            start = time.perf_counter()
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec + 5.0,
                input=json.dumps(test_cases),
            )
            elapsed = time.perf_counter() - start
            try:
                report = _parse_report(proc.stdout, test_cases, proc.returncode)
            except Exception:
                report = {
                    "passed": 0,
                    "total": max(1, len(test_cases)),
                    "details": [],
                    "load_error": (proc.stderr or proc.stdout)[:200],
                }
            result = _metrics_from_report(code, elapsed, float(self.memory_mb), report, proc.returncode)
            result.stdout = proc.stdout[:2000]
            result.stderr = proc.stderr[:2000]
            return result
        except subprocess.TimeoutExpired:
            return _timeout_result(self.timeout_sec)
        except Exception as exc:
            return _error_result(self.timeout_sec, str(exc)[:2000])
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


@dataclass
class MicroVMRunner:
    """Placeholder for non-trusted workloads. Not implemented in this release."""

    timeout_sec: float = 10.0

    def run(self, code: str, test_cases: list[dict]) -> EvalResult:
        # Explicit stub (FIX 2.4): reserved for Firecracker/Cloud Hypervisor path.
        raise NotImplementedError(
            "MicroVMRunner is not implemented in this release; "
            "use runner_mode='container' or 'subprocess'."
        )


def create_runner(
    mode: str = "subprocess",
    *,
    timeout_sec: float = 10.0,
    memory_mb: int = 256,
    allow_expression_eval: bool = False,
    enforce_ast_scan: bool = True,
) -> CandidateRunner:
    """Factory for candidate runners.

    Modes: subprocess | container | microvm
    """
    mode = (mode or "subprocess").lower()
    if mode in {"subprocess", "local", "dev"}:
        return SubprocessRunner(
            timeout_sec=timeout_sec,
            memory_mb=memory_mb,
            allow_expression_eval=allow_expression_eval,
            enforce_ast_scan=enforce_ast_scan,
        )
    if mode in {"container", "docker", "podman"}:
        return ContainerRunner(
            timeout_sec=timeout_sec,
            memory_mb=memory_mb,
            allow_expression_eval=allow_expression_eval,
            enforce_ast_scan=enforce_ast_scan,
            engine="auto" if mode == "container" else mode,
        )
    if mode in {"microvm", "vm"}:
        return MicroVMRunner(timeout_sec=timeout_sec)
    raise ValueError(f"Unknown runner mode: {mode!r}")
