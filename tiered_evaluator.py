"""Tiered Evaluator (FASE 2 — O6 Nanopass + A4 coverage-driven selection).

Cost-aware evaluation ladder.  A candidate climbs the tiers only as far as
its cheap verdict allows:

    N1  In-memory "UAST nanopass" guard — must be < 1 ms.
        Single ``ast.parse`` + UAST-core semantic guard
        (muta_ext.uast2.verify, when the UAST engine is active) +
        :class:`api_fingerprint` strict compare vs the baseline + an in-tree
        security walk.  Rejects the broken 90% for ~zero cost.

    N2  Minimal test subset (A4) — in-process if the candidate is pure,
        hardened subprocess if it does I/O.  The subset is selected by
        greedy set cover over the functions each test exercises; when
        ``coverage`` is importable it is *coverage-guided*: the subset grows
        (most-uncovered-lines-first) until the target's line coverage
        plateaus.  Full suite, no container.

    N3  Full suite in Docker sandbox (fail-closed; hardened subprocess
        fallback when no container is available) + optional Ray profiling
        for distributed throughput.  Only the top ``sandbox_top_pct``% of N2
        survivors (by N2 score) pay this cost — the acceptance criterion
        "≤20 % de los mutantes tocan N3" holds by construction.

Zero false positives: N1 only rejects on provable violations (syntax,
security findings, API breakage); N2/N3 evaluate real behaviour.  A
functionally correct candidate that breaks no public API always passes N1
and can only be rejected by failing actual tests.
"""

from __future__ import annotations

import ast
import importlib.util
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from api_fingerprint import compare_api, extract_api_fingerprint
from code_hash import stable_code_hash
from comparison import compare_values
from optimization_flags import get_optimization_flags
from runners import SecurityVisitor

__all__ = [
    "NanopassResult",
    "n1_nanopass_check",
    "TestSubsetSelector",
    "detects_io",
    "eval_in_process",
    "TieredResult",
    "TieredEvaluator",
]

# ── N1: in-memory UAST nanopass guard (< 1 ms) ──────────────────────────────

# I/O / privileged call names that force the hardened-subprocess path.
_IO_NAMES = {
    "open", "input", "socket", "subprocess", "urllib", "requests",
    "shutil", "os.remove", "os.system", "os.unlink", "os.rmdir",
    "os.rename", "http.client", "httpx", "popen", "system",
}


@dataclass
class NanopassResult:
    passed: bool
    reason: str = ""
    api_compatible: Optional[bool] = None
    security_findings: List[str] = field(default_factory=list)
    missing_functions: List[str] = field(default_factory=list)
    uast2_checked: bool = False
    ms: float = 0.0
    budget_ms: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "api_compatible": self.api_compatible,
            "security_findings": list(self.security_findings),
            "missing_functions": list(self.missing_functions),
            "uast2_checked": self.uast2_checked,
            "ms": round(self.ms, 4),
            "within_budget": self.ms <= self.budget_ms,
        }


def _uast2_verify_available() -> bool:
    return importlib.util.find_spec("muta_ext") is not None


def _run_uast2_verify(code: str) -> Tuple[bool, List[str]]:
    """Run the UAST-core semantic guard over a freshly built document.

    Returns (ok, messages).  Any exception is treated as a soft pass with a
    note: N1 must never reject on infrastructure failure.
    """
    try:
        from muta_ext.uast2 import engine as uast2_engine
    except Exception:
        return True, []
    try:
        document = uast2_engine.parse_to_v2(code, language="python")
        result = uast2_engine.verify_document(
            document, strict=True, original_source=code, language="python"
        )
        ok = bool(getattr(result, "ok", True))
        msgs: List[str] = []
        diagnostics = getattr(result, "diagnostics", None)
        if diagnostics:
            for _pass, diags in diagnostics.items():
                msgs.extend(str(d) for d in (diags or [])[:4])
        return (ok, msgs)
    except Exception:
        return True, []  # infrastructure failure is never a rejection


def n1_nanopass_check(
    code: str,
    baseline_code: str,
    *,
    api_policy: str = "strict",
    use_uast2: bool = False,
    budget_ms: float = 1.0,
) -> NanopassResult:
    """Single-pass in-memory guard.  Budget: ``budget_ms`` (default 1.0)."""
    start = time.perf_counter()
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return NanopassResult(False, f"syntax_error:{str(exc)[:160]}", ms=(time.perf_counter() - start) * 1e3, budget_ms=budget_ms)

    # API compatibility vs baseline (the semantic core of the nanopass).
    try:
        baseline_fp = extract_api_fingerprint(baseline_code)
        candidate_fp = extract_api_fingerprint(code)
        api = compare_api(baseline_fp, candidate_fp, policy=api_policy)
    except Exception as exc:
        return NanopassResult(False, f"api_error:{str(exc)[:160]}", ms=(time.perf_counter() - start) * 1e3, budget_ms=budget_ms)
    if not api.compatible:
        missing = list(api.missing_functions)
        mismatch = list(api.signature_mismatches)
        detail = f"api_mismatch:missing={missing[:4]} mismatch={mismatch[:4]}"
        return NanopassResult(
            False, detail[:300], api_compatible=False, missing_functions=missing,
            ms=(time.perf_counter() - start) * 1e3, budget_ms=budget_ms,
        )

    # Security walk over the SAME parsed tree (no second parse).
    visitor = SecurityVisitor()
    visitor.visit(tree)
    findings: List[str] = []
    seen: set = set()
    for f in visitor.findings:
        if f.message not in seen:
            seen.add(f.message)
            findings.append(f.message)
    if findings:
        return NanopassResult(
            False, f"security:{findings[0]}", api_compatible=True, security_findings=findings,
            ms=(time.perf_counter() - start) * 1e3, budget_ms=budget_ms,
        )

    # UAST-core semantic guard (only when the UAST engine is active).
    uast2_ok, uast2_msgs = (True, [])
    uast2_used = False
    if use_uast2 and _uast2_verify_available():
        uast2_ok, uast2_msgs = _run_uast2_verify(code)
        uast2_used = True
        if not uast2_ok:
            return NanopassResult(
                False, f"uast2:{uast2_msgs[0][:160] if uast2_msgs else 'invalid'}",
                api_compatible=True, uast2_checked=True,
                ms=(time.perf_counter() - start) * 1e3, budget_ms=budget_ms,
            )

    return NanopassResult(
        True, "ok", api_compatible=True, uast2_checked=uast2_used,
        ms=(time.perf_counter() - start) * 1e3, budget_ms=budget_ms,
    )


# ── A4: coverage-guided minimal test subset ─────────────────────────────────


def _callee_names(test: Dict[str, Any]) -> List[str]:
    """Functions a declarative test exercises (top-level entry + helpers it
    references by name in its arguments/expected values is not statically
    knowable, so the entry point is the unit of coverage)."""
    out: List[str] = []
    fn = test.get("function")
    if isinstance(fn, str) and fn:
        out.append(fn)
    return out


def _defined_functions(source: str) -> Dict[str, int]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: Dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node.lineno
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{sub.name}"] = sub.lineno
    return out


def _line_coverage_of_run(code: str, test_cases: List[Dict[str, Any]]) -> set:
    """Lines of *code* executed while running *test_cases* in-process.

    Uses the stdlib ``trace`` module when available (no new dependency);
    falls back to "all lines" (no pruning possible, fail-safe).
    """
    try:
        import trace as _trace
    except Exception:
        return set(range(1, code.count("\n") + 2))
    ns: Dict[str, Any] = {"__name__": "__ml_subset__"}
    try:
        exec(compile(code, "<subset-probe>", "exec"), ns)
    except Exception:
        return set()
    tracer = _trace.Trace(count=False, trace=False)
    try:
        with tracer:
            for tc in test_cases:
                fn_name = tc.get("function")
                fn = ns.get(fn_name)
                if not callable(fn):
                    continue
                try:
                    fn(*tc.get("args", []))
                except Exception:
                    continue
    except Exception:
        return set()
    result = tracer.results()
    lines: set = set()
    for (filename, _), file_lines in (result.counts or {}).items():
        if filename != "<subset-probe>":
            continue
        lines.update(file_lines.keys())
    return lines or set()


def _greedy_set_cover(
    universe: List[str], sets: List[Tuple[int, set]]
) -> List[int]:
    """Greedy minimum set cover: pick the set covering the most uncovered."""
    remaining = set(universe)
    pool = list(sets)
    picked: List[int] = []
    while remaining and pool:
        best_idx, best_gain = -1, 0
        for i, (_, members) in enumerate(pool):
            gain = len(members & remaining)
            if gain > best_gain:
                best_idx, best_gain = i, gain
        if best_idx < 0:
            break
        picked.append(pool[best_idx][0])
        remaining -= pool[best_idx][1]
        pool.pop(best_idx)
    return picked


class TestSubsetSelector:
    """A4: pick the minimal test subset that covers the target's functions.

    * Static mode (default, zero extra dependencies): greedy set cover over
      the entry functions of the target; always keeps a test for the primary
      entry point and spreads the budget across the rest.
    * Coverage-guided mode (``coverage_guided=True`` and ``coverage`` or
      stdlib ``trace`` available): after a probe run, the subset grows
      most-uncovered-lines-first until line coverage plateaus — the classic
      A4 "coverage selection" loop, without a pytest dependency.
    """

    __test__ = False  # not a pytest class; named for the A4 spec

    def __init__(
        self,
        target_source: str,
        test_cases: List[Dict[str, Any]],
        *,
        coverage_guided: bool = False,
        max_tests: int = 0,
        seed: int = 42,
    ) -> None:
        self.target_source = target_source
        self.test_cases = list(test_cases)
        self.coverage_guided = coverage_guided
        self.max_tests = max_tests
        self.seed = seed
        self._selected: List[Dict[str, Any]] = []
        self._meta: Dict[str, Any] = {}

    # ── public ────────────────────────────────────────────────────────────
    def select(self) -> List[Dict[str, Any]]:
        if self._selected:
            return self._selected
        cases = self.test_cases
        if not cases:
            self._selected, self._meta = [], {"mode": "empty"}
            return self._selected

        defined = _defined_functions(self.target_source)
        entry_names = list(defined.keys())

        # Index each test by the functions it can reach.  A test "covers" its
        # entry function plus any helper whose name appears in the test body
        # (static, conservative).
        test_sets: List[Tuple[int, set]] = []
        for i, tc in enumerate(cases):
            members = set(_callee_names(tc))
            blob = str(tc)
            for name in defined:
                if name not in members and (name.split(".")[-1]) in blob:
                    members.add(name)
            test_sets.append((i, members))

        # Always keep at least one test per top-level entry function.
        must: set = set()
        for name in entry_names:
            for i, members in test_sets:
                if name in members:
                    must.add(i)
                    break
        if not must:
            must = {0}

        remaining = [i for i in range(len(cases)) if i not in must]
        cover_sets = [(i, members & set(entry_names)) for i, members in test_sets if i in remaining]
        uncovered = set(entry_names)
        for i in must:
            uncovered -= test_sets[i][1]
        extra = _greedy_set_cover(sorted(uncovered), cover_sets)
        picked = sorted(must | set(extra))
        if self.max_tests and len(picked) > self.max_tests:
            # Keep entry-point tests first, then the rest in original order.
            entry_first = sorted(picked, key=lambda i: (i not in must, i))
            picked = entry_first[: self.max_tests]

        if self.coverage_guided and len(picked) < len(cases):
            picked = self._grow_by_coverage(picked)

        self._selected = [cases[i] for i in picked]
        self._meta = {
            "mode": "coverage_guided" if self.coverage_guided else "static_set_cover",
            "total_tests": len(cases),
            "subset_size": len(self._selected),
            "defined_functions": entry_names,
        }
        return self._selected

    def meta(self) -> Dict[str, Any]:
        return dict(self._meta)

    # ── coverage-guided growth ────────────────────────────────────────────
    def _grow_by_coverage(self, picked: List[int]) -> List[int]:
        try:
            import trace as _trace
        except Exception:
            return sorted(picked)
        picked_set = set(picked)
        for _ in range(len(self.test_cases) - len(picked_set)):
            current_lines = _line_coverage_of_run(
                self.target_source, [self.test_cases[i] for i in picked_set]
            )
            best_i, best_gain = -1, 0
            for i in range(len(self.test_cases)):
                if i in picked_set:
                    continue
                lines = _line_coverage_of_run(
                    self.target_source, [self.test_cases[i]]
                )
                gain = len(lines - current_lines)
                if gain > best_gain:
                    best_i, best_gain = i, gain
            if best_i < 0:
                break
            picked_set.add(best_i)
            if best_gain == 0:
                break  # plateau: no further line coverage
        return sorted(picked_set)


# ── I/O detection + in-process evaluation (N2) ──────────────────────────────


_IO_MODULES = {"os", "socket", "subprocess", "urllib", "requests", "shutil", "http", "httpx"}


def _io_visitor():
    class _V(ast.NodeVisitor):
        def __init__(self) -> None:
            self.io = False

        def visit_Import(self, node: ast.Import):
            for a in node.names:
                if (a.name or "").split(".")[0] in _IO_MODULES:
                    self.io = True
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            if (node.module or "").split(".")[0] in _IO_MODULES:
                self.io = True
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            f = node.func
            name = ""
            if isinstance(f, ast.Name):
                name = f.id
            elif isinstance(f, ast.Attribute):
                base = f.value
                if isinstance(base, ast.Name):
                    name = f"{base.id}.{f.attr}"
            if name in _IO_NAMES or name.split(".")[-1] in ("open", "system", "popen"):
                self.io = True
            self.generic_visit(node)

    return _V


def detects_io(code: str) -> bool:
    """True when the candidate performs I/O or privileged operations.

    I/O candidates leave N2 in-process mode and are evaluated via the
    hardened subprocess runner (same semantics, separate address space).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return True  # unparseable → treat as unsafe, let N1 reject
    visitor = _io_visitor()
    v = visitor()
    v.visit(tree)
    return v.io


def _run_declarative_test(namespace: Dict[str, Any], tc: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(tc, dict):
        return False, "invalid_case"
    fn_name = tc.get("function")
    if not isinstance(fn_name, str):
        return False, "no_function"
    fn = namespace.get(fn_name)
    if not callable(fn):
        return False, f"missing_function:{fn_name}"
    args = tc.get("args", [])
    try:
        got = fn(*args)
    except Exception as exc:
        return False, f"raised:{type(exc).__name__}:{str(exc)[:100]}"
    expected = tc.get("expected", tc.get("output"))
    comparison = tc.get("comparison", "equal")
    try:
        ok = bool(compare_values(got, expected, comparison))
    except Exception as exc:
        return False, f"compare_error:{str(exc)[:80]}"
    return ok, "" if ok else "value_mismatch"


def eval_in_process(
    code: str,
    test_cases: List[Dict[str, Any]],
    *,
    timeout_sec: float = 5.0,
) -> Dict[str, Any]:
    """Execute a PURE candidate in-process against *test_cases*.

    Returns ``{passed, score, results, ms, error}``.  A wall-clock guard
    aborts runaway candidates; per-call CPU limits are N3's job (sandbox).
    """
    start = time.perf_counter()
    results: List[Dict[str, Any]] = []
    ns: Dict[str, Any] = {"__name__": "__ml_n2__"}
    try:
        exec(compile(code, "<n2-process>", "exec"), ns)
    except Exception as exc:
        return {
            "passed": False, "score": 0.0, "results": [],
            "ms": (time.perf_counter() - start) * 1e3,
            "error": f"exec:{type(exc).__name__}:{str(exc)[:120]}",
        }
    passed = 0
    for idx, tc in enumerate(test_cases):
        if time.perf_counter() - start > timeout_sec:
            results.append({"index": idx, "passed": False, "error": "timeout"})
            continue
        ok, err = _run_declarative_test(ns, tc)
        results.append({"index": idx, "passed": ok, "error": err})
        if ok:
            passed += 1
    total = len(test_cases) or 1
    return {
        "passed": passed == len(test_cases),
        "score": passed / total,
        "results": results,
        "ms": (time.perf_counter() - start) * 1e3,
        "error": "",
    }


# ── Tiered orchestration ────────────────────────────────────────────────────


@dataclass
class TieredResult:
    code: str
    code_hash: str
    passed: bool
    score: float
    tier: str  # "n1_reject" | "n2" | "n3"
    n1: Optional[NanopassResult] = None
    n2: Optional[Dict[str, Any]] = None
    n3: Optional[Dict[str, Any]] = None
    subset_size: int = 0
    used_io_subprocess: bool = False
    n1_ms: float = 0.0
    n2_ms: float = 0.0
    n3_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code_hash": self.code_hash,
            "passed": self.passed,
            "score": round(self.score, 4),
            "tier": self.tier,
            "subset_size": self.subset_size,
            "used_io_subprocess": self.used_io_subprocess,
            "n1_ms": round(self.n1_ms, 4),
            "n2_ms": round(self.n2_ms, 4),
            "n3_ms": round(self.n3_ms, 4),
            "n1": self.n1.to_dict() if self.n1 else None,
            "n2": {k: self.n2[k] for k in ("score", "passed", "error")} if self.n2 else None,
            "n3": self.n3,
        }


class TieredEvaluator:
    """O6: N1 nanopass → N2 minimal-subset → N3 top-20 % sandbox.

    Drop-in for engine evaluation: :meth:`evaluate_batch` accepts a list of
    candidate sources and returns one :class:`TieredResult` per candidate,
    in input order.
    """

    def __init__(
        self,
        baseline_source: str,
        test_cases: List[Dict[str, Any]],
        *,
        min_cpu_pct: float = 0.5,
        sandbox_top_pct: float = 20.0,
        n1_enabled: bool = True,
        n2_enabled: bool = True,
        n3_enabled: bool = True,
        use_uast2: bool = False,
        api_policy: str = "strict",
        subset_coverage_guided: bool = False,
        subset_max_tests: int = 0,
        n2_timeout_sec: float = 5.0,
        n3_runner: Optional[Any] = None,
        n3_use_ray: bool = False,
        seed: int = 42,
    ) -> None:
        self.baseline_source = baseline_source
        self.test_cases = list(test_cases)
        self.min_cpu_pct = float(min_cpu_pct)
        self.sandbox_top_pct = float(sandbox_top_pct)
        self.n1_enabled = n1_enabled
        self.n2_enabled = n2_enabled
        self.n3_enabled = n3_enabled
        self.use_uast2 = use_uast2
        self.api_policy = api_policy
        self.n2_timeout_sec = float(n2_timeout_sec)
        self.n3_runner = n3_runner
        self.n3_use_ray = n3_use_ray
        self.seed = seed
        self.selector = TestSubsetSelector(
            baseline_source, test_cases,
            coverage_guided=subset_coverage_guided, max_tests=subset_max_tests, seed=seed,
        )
        self._stats: Dict[str, Any] = {}
        self._last_run: List[TieredResult] = []

    # ── batch helper (duck-typed across runner flavors) ───────────────────
    @staticmethod
    def _batch_run(runner: Any, codes: List[str], test_cases: List[Dict[str, Any]]) -> List[Any]:
        fn = getattr(runner, "evaluate_batch", None)
        if callable(fn):
            return list(fn(codes, test_cases))
        return [runner.run(c, test_cases) for c in codes]

    @staticmethod
    def _eval_fraction(ev: Any) -> float:
        """Test-pass fraction from an EvalResult (metrics > weighted score)."""
        try:
            m = getattr(ev, "metrics", None) or {}
            if "correctness" in m:
                return float(m["correctness"])
            tp, tt = m.get("tests_passed"), m.get("tests_total")
            if tp is not None and tt:
                return float(tp) / float(tt)
        except Exception:
            pass
        try:
            return float(max(0.0, min(1.0, getattr(ev, "score", 0.0))))
        except Exception:
            return 0.0

    # ── N3 runner resolution (fail-closed) ────────────────────────────────
    def _resolve_n3_runner(self) -> Optional[Any]:
        if self.n3_runner is not None:
            return self.n3_runner
        if getattr(self, "_n3_runner", None) is not None:
            return self._n3_runner
        try:
            from runners import ContainerRunner, SubprocessRunner
        except Exception:
            return None
        try:
            import shutil
            if shutil.which("docker") or shutil.which("podman"):
                runner = ContainerRunner(timeout_sec=10.0, memory_mb=512)
                if runner.is_available():
                    self._n3_runner = runner
                    return runner
        except Exception:
            pass  # container unavailable → hardened subprocess (fail-closed)
        self._n3_runner = SubprocessRunner(timeout_sec=10.0, memory_mb=256)
        return self._n3_runner

    # ── public ────────────────────────────────────────────────────────────
    def evaluate_batch(self, codes: List[str]) -> List[TieredResult]:
        results: List[TieredResult] = []
        n1_pass: List[Tuple[int, str, NanopassResult]] = []
        t_start = time.perf_counter()

        for i, code in enumerate(codes):
            res = TieredResult(
                code=code,
                code_hash=stable_code_hash(code),
                passed=False,
                score=0.0,
                tier="pending",
            )
            if self.n1_enabled:
                n1 = n1_nanopass_check(code, self.baseline_source, api_policy=self.api_policy, use_uast2=self.use_uast2)
                res.n1 = n1
                res.n1_ms = n1.ms
                if not n1.passed:
                    res.tier = "n1_reject"
                    results.append(res)
                    continue
                n1_pass.append((i, code, n1))
            else:
                n1_pass.append((i, code, None))
            results.append(res)

        # N2: minimal subset, in-process (pure) or hardened subprocess (I/O).
        n2_scores: List[Tuple[int, float, TieredResult, Dict[str, Any], bool]] = []
        subset: List[Dict[str, Any]] = []
        if self.n2_enabled and n1_pass:
            subset = self.selector.select()
            for i, code, n1 in n1_pass:
                res = results[i]
                t0 = time.perf_counter()
                io = detects_io(code)
                if not io:
                    n2 = eval_in_process(code, subset, timeout_sec=self.n2_timeout_sec)
                else:
                    runner = self._resolve_n3_runner()
                    if runner is None:
                        n2 = {"passed": False, "score": 0.0, "results": [],
                               "ms": 0.0, "error": "no_runner"}
                    else:
                        t_run = time.perf_counter()
                        ev = runner.run(code, subset)
                        n2 = {
                            "passed": bool(getattr(ev, "passed", False)),
                            "score": self._eval_fraction(ev),
                            "results": [],
                            "ms": (time.perf_counter() - t_run) * 1e3,
                            "error": str(getattr(ev, "error", "")),
                        }
                res.n2 = n2
                res.n2_ms = (time.perf_counter() - t0) * 1e3
                res.subset_size = len(subset)
                res.used_io_subprocess = io
                res.score = n2["score"]
                if n2["passed"] and not self.n3_enabled:
                    res.passed = True
                    res.tier = "n2"
                elif self.n3_enabled:
                    n2_scores.append((i, n2["score"], res, n2, io))
                else:
                    res.passed = False
                    res.tier = "n2"
            self.selector.select()  # ensure meta populated

        # N3: only the top sandbox_top_pct% of N2 survivors.
        if self.n3_enabled and n2_scores:
            n2_scores.sort(key=lambda t: (-t[1], t[0]))
            top_k = max(1, math.floor(len(n2_scores) * self.sandbox_top_pct / 100.0))
            top = n2_scores[:top_k]
            rest = n2_scores[top_k:]
            for _, _, res, n2, _io in rest:
                res.passed = bool(n2["passed"])
                res.tier = "n2"
            runner = self._resolve_n3_runner()
            if runner is not None and top:
                t0 = time.perf_counter()
                top_codes = [codes[i] for i, _, _, _, _ in top]
                try:
                    if self.n3_use_ray:
                        evs = self._ray_evaluate(top_codes)
                    else:
                        evs = self._batch_run(runner, top_codes, self.test_cases)
                except Exception:
                    evs = None
                n3_ms = (time.perf_counter() - t0) * 1e3
                for (i, _score, res, _n2, _io), ev in zip(top, evs or []):
                    res.n3_ms = n3_ms / max(1, len(top))
                    if ev is None:
                        res.passed = False
                        res.tier = "n3"
                        res.n3 = {"passed": False, "score": 0.0, "error": "runner_unavailable"}
                        continue
                    res.n3 = {
                        "passed": bool(getattr(ev, "passed", False)),
                        "score": self._eval_fraction(ev),
                        "error": str(getattr(ev, "error", "")),
                    }
                    res.score = res.n3["score"]
                    res.passed = res.n3["passed"]
                    res.tier = "n3"
            else:
                for _, _, res, n2, _io in top:
                    res.passed = bool(n2["passed"])
                    res.tier = "n2"

        # N1-disabled path without N2: keep deterministic behaviour.
        for i, code, n1 in n1_pass:
            res = results[i]
            if res.tier == "pending":
                res.tier = "n1"
                res.passed = True
                res.score = 1.0

        # Stats for the cost ledger (rule 4: sin medición = no implementada).
        n1_rejected = sum(1 for r in results if r.tier == "n1_reject")
        n3_count = sum(1 for r in results if r.tier == "n3")
        total = len(results) or 1
        self._stats = {
            "total": len(results),
            "n1_rejected": n1_rejected,
            "n2_final": sum(1 for r in results if r.tier == "n2"),
            "n3_count": n3_count,
            "n3_pct": round(100.0 * n3_count / total, 3),
            "n1_mean_ms": round(sum(r.n1_ms for r in results) / total, 4),
            "n2_mean_ms": round(
                sum(r.n2_ms for r in results if r.n2 is not None) / max(1, sum(1 for r in results if r.n2 is not None)), 4
            ),
            "n3_mean_ms": round(
                sum(r.n3_ms for r in results if r.n3 is not None) / max(1, sum(1 for r in results if r.n3 is not None)), 4
            ),
            "subset_size": self.selector.meta().get("subset_size", 0),
            "subset_mode": self.selector.meta().get("mode", ""),
            "total_ms": (time.perf_counter() - t_start) * 1e3,
            "wall_ms": (time.perf_counter() - t_start) * 1e3,
        }
        self._last_run = results
        return results

    # ── N3 on Ray (optional, distributed throughput) ──────────────────────
    def _ray_evaluate(self, codes: List[str]) -> Optional[List[Any]]:
        """Run the N3 evaluations as Ray tasks; fall back to local batch."""
        runner = self._resolve_n3_runner()
        if runner is None:
            return None
        try:
            import ray  # type: ignore
        except Exception:
            return runner.evaluate_batch(codes, self.test_cases)
        try:
            import os
            if not ray.is_initialized():
                ray.init(
                    num_cpus=min(4, os.cpu_count() or 1),
                    include_dashboard=False,
                    ignore_reinit_error=True,
                    log_to_driver=False,
                )

            test_cases = list(self.test_cases)

            @ray.remote
            def _one(payload):
                idx, code = payload
                from runners import SubprocessRunner
                r = SubprocessRunner(timeout_sec=10.0, memory_mb=256)
                return idx, r.run(code, test_cases)

            refs = [_one.remote((i, c)) for i, c in enumerate(codes)]
            out = ray.get(refs)
            return [ev for _i, ev in sorted(out, key=lambda t: t[0])]
        except Exception:
            return self._batch_run(runner, codes, self.test_cases)

    # ── config wiring (rule 6: everything flag-gated) ─────────────────────
    @classmethod
    def from_flags(
        cls,
        baseline_source: str,
        test_cases: List[Dict[str, Any]],
        n3_runner: Optional[Any] = None,
    ) -> "TieredEvaluator":
        """Build a TieredEvaluator from ``config/optimization.yaml``."""
        flags = get_optimization_flags()
        e = lambda path: flags.enabled(f"profiling_filter.{path}")  # noqa: E731
        return cls(
            baseline_source,
            test_cases,
            min_cpu_pct=float(flags.get("profiling_filter.min_cpu_pct", 0.5)),
            sandbox_top_pct=float(flags.get("profiling_filter.sandbox_top_pct", 20.0)),
            n1_enabled=e("nanopass_check.enabled"),
            n2_enabled=e("test_subset.enabled"),
            n3_enabled=True,  # complement: only N2 survivors reach it (top pct)
            use_uast2=e("uast2_enabled"),
            api_policy=str(flags.get("profiling_filter.api_policy", "strict")),
            subset_coverage_guided=e("test_subset.by_coverage"),
            subset_max_tests=int(flags.get("profiling_filter.test_subset.max_tests", 0) or 0),
            n3_runner=n3_runner,
            n3_use_ray=e("ray_profile.enabled"),
        )

    def stats(self) -> Dict[str, Any]:
        return dict(self._stats)

    def results(self) -> List[TieredResult]:
        return list(self._last_run)


def tiering_active() -> bool:
    """True when the Fase-2 ladder should replace plain evaluation."""
    try:
        flags = get_optimization_flags()
        return flags.enabled("profiling_filter.enabled") and (
            flags.enabled("profiling_filter.nanopass_check.enabled")
            or flags.enabled("profiling_filter.test_subset.enabled")
        )
    except Exception:
        return False


class TieredOfflineEvaluator:
    """Drop-in adapter: wrap a callable evaluator (``code -> float``) with
    the tiered ladder.

    * With ``test_cases``: full ladder N1 → N2 (subset, in-process/subprocess)
      → N3 (hardened subprocess; ≤ ``sandbox_top_pct``% of survivors).
      Verdicts come from real execution; the wrapped scorer is used only as
      a tie-break fitness signal for N2-final candidates.
    * Without ``test_cases`` (pure offline heuristics): N1 guard + wrapped
      scorer; broken candidates (syntax / security / API break) are rejected
      for ~1 ms instead of being scored downstream.

    Exposes ``evaluate_batch(codes) -> List[EvalResult]`` and ``score(code)``,
    so it plugs into the existing engine duck-typing unchanged.
    """

    def __init__(
        self,
        baseline_source: str,
        wrapped: Any,
        test_cases: Optional[List[Dict[str, Any]]] = None,
        **tier_kwargs: Any,
    ) -> None:
        self.baseline_source = baseline_source
        self.wrapped = wrapped
        self.test_cases = list(test_cases) if test_cases else []
        self.tiered = TieredEvaluator(
            baseline_source, self.test_cases, **tier_kwargs
        ) if self.test_cases else None
        self._n1_only = self.tiered is None

    # ── helpers ───────────────────────────────────────────────────────────
    def _wrapped_score(self, code: str) -> float:
        """Score from a callable evaluator or an ``evaluate_batch`` object."""
        w = self.wrapped
        if callable(w):
            try:
                return float(w(code))
            except TypeError:
                pass
        evs = w.evaluate_batch([code])
        return float(getattr(evs[0], "score", 0.0) or 0.0)

    # ── duck-typed API ────────────────────────────────────────────────────
    def score(self, code: str) -> float:
        if self._n1_only:
            n1 = n1_nanopass_check(code, self.baseline_source)
            if not n1.passed:
                return float("-inf")
        return self._wrapped_score(code)

    def evaluate_batch(self, codes: List[str]) -> List[Any]:
        from models import EvalResult, FitnessVector

        if self.tiered is not None:
            tier_results = self.tiered.evaluate_batch(codes)
            out: List[Any] = []
            for tr in tier_results:
                if tr.tier == "n1_reject":
                    ev = EvalResult(passed=False)
                    ev.fitness = FitnessVector(correctness=0.0)
                elif tr.tier == "n3":
                    ev = EvalResult(passed=bool(tr.passed))
                    ev.fitness = FitnessVector(correctness=float(min(1.0, max(0.0, tr.score))))
                else:  # n2 (or n1 fallback): subset fraction is the verdict
                    ev = EvalResult(passed=bool(tr.passed))
                    ev.fitness = FitnessVector(
                        correctness=float(min(1.0, max(0.0, tr.score)))
                    )
                out.append(ev)
            return out

        out = []
        for code in codes:
            n1 = n1_nanopass_check(code, self.baseline_source)
            if not n1.passed:
                ev = EvalResult(passed=False)
                ev.fitness = FitnessVector(correctness=0.0)
                out.append(ev)
                continue
            s = self._wrapped_score(code)
            ev = EvalResult(passed=s != float("-inf") and s > 0.0)
            ev.fitness = FitnessVector(correctness=max(0.0, min(1.0, s)))
            out.append(ev)
        return out

    def stats(self) -> Dict[str, Any]:
        if self.tiered is not None:
            return self.tiered.stats()
        return {"n1_only": True, "baseline": stable_code_hash(self.baseline_source)}



