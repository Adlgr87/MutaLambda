"""Integrity gates: make a reported speedup hard to fake.

The failure mode this module exists for: a benchmark run that reports "8.4x
faster, 100% tests pass" because the candidate memoised the benchmark inputs,
hardcoded the expected outputs, deleted work that the visible tests never
exercise, or tampered with the clock.

Every task gets a verdict:

``clean``     — counted in the headline numbers.
``suspect``   — reported, excluded from headline numbers, reason published.
``rejected``  — treated as a failure (no speedup credit at all).

The checks are deliberately conservative and *explainable*: each one returns a
human-readable reason string that goes straight into the published report.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence, Set

from bench.spec import BenchTask

CLEAN = "clean"
NOTE = "note"        # published, but does not disqualify the result
SUSPECT = "suspect"  # published, excluded from headline aggregates
REJECTED = "rejected"

# NOTE shares CLEAN's severity on purpose: a genuinely large algorithmic win
# (an O(n) loop replaced by a closed form) must not be punished for being
# large. It gets a visible footnote and the held-out tests still decide.
_SEVERITY_ORDER = {CLEAN: 0, NOTE: 0, SUSPECT: 1, REJECTED: 2}

# Modules a candidate has no business importing in a pure-compute benchmark.
_FORBIDDEN_MODULES: Set[str] = {
    "socket", "http", "urllib", "urllib2", "urllib3", "requests", "ftplib",
    "smtplib", "telnetlib", "subprocess", "multiprocessing", "shutil",
    "ctypes", "signal", "resource", "gc", "pty", "fcntl", "mmap",
    "importlib", "pickle", "shelve", "dbm", "sqlite3", "tempfile", "pathlib",
}
# Timing / measurement surface. Touching it during a *timed* benchmark is
# either a bug or an attack on the measurement itself.
_CLOCK_ATTACK: Set[str] = {"time", "timeit", "datetime", "sys", "threading", "atexit"}

_DANGEROUS_CALLS: Set[str] = {
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "globals", "locals", "vars", "setattr", "delattr", "memoryview",
}

_MEMO_DECORATORS = {"lru_cache", "cache", "cached_property", "memoize"}


@dataclass
class Finding:
    check: str
    verdict: str
    reason: str
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IntegrityReport:
    verdict: str = CLEAN
    findings: List[Finding] = field(default_factory=list)
    checks_run: List[str] = field(default_factory=list)

    def add(self, finding: Optional[Finding]) -> None:
        if finding is None:
            return
        self.findings.append(finding)
        if _SEVERITY_ORDER[finding.verdict] > _SEVERITY_ORDER[self.verdict]:
            self.verdict = finding.verdict

    @property
    def clean(self) -> bool:
        return self.verdict == CLEAN

    @property
    def counted(self) -> bool:
        """Only clean results feed the headline aggregate."""
        return self.verdict == CLEAN

    def reasons(self) -> List[str]:
        return [f"{f.check}: {f.reason}" for f in self.findings]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "checks_run": self.checks_run,
            "findings": [f.to_dict() for f in self.findings],
        }


# ── individual checks ──────────────────────────────────────────────────────

def check_parses(code: str) -> Optional[Finding]:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return Finding("parses", REJECTED, "candidate does not parse", str(exc)[:200])
    return None


def check_forbidden_imports(code: str) -> Optional[Finding]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    hits: List[str] = []
    clock: List[str] = []
    for node in ast.walk(tree):
        names: List[str] = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        for n in names:
            if n in _FORBIDDEN_MODULES:
                hits.append(n)
            elif n in _CLOCK_ATTACK:
                clock.append(n)
    if hits:
        return Finding(
            "forbidden_imports", REJECTED,
            "imports modules outside the compute sandbox",
            ", ".join(sorted(set(hits))),
        )
    if clock:
        return Finding(
            "clock_surface", SUSPECT,
            "imports timing/interpreter modules inside a timed candidate",
            ", ".join(sorted(set(clock))),
        )
    return None


def check_dangerous_calls(code: str) -> Optional[Finding]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    hits: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name in _DANGEROUS_CALLS:
                hits.append(str(name))
            if isinstance(fn, ast.Attribute) and name in {"settrace", "setprofile", "setrecursionlimit"}:
                hits.append(f"sys.{name}")
    if hits:
        return Finding(
            "dangerous_calls", REJECTED,
            "uses dynamic-execution or I/O primitives",
            ", ".join(sorted(set(hits))),
        )
    return None


def _literal_values(tree: ast.AST) -> List[Any]:
    out: List[Any] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
            out.append(node.value)
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            try:
                out.append(ast.literal_eval(node))
            except (ValueError, SyntaxError):
                pass
        elif isinstance(node, ast.Dict):
            try:
                out.append(ast.literal_eval(node))
            except (ValueError, SyntaxError):
                pass
    return out


def _flatten(value: Any) -> List[Any]:
    if isinstance(value, dict):
        out: List[Any] = []
        for k, v in value.items():
            out.extend(_flatten(k))
            out.extend(_flatten(v))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for v in value:
            out.extend(_flatten(v))
        return out
    return [value]


def check_hardcoded_answers(
    code: str,
    baseline_code: str,
    tests: Sequence[Dict[str, Any]],
    *,
    min_hits: int = 3,
) -> Optional[Finding]:
    """Detect a lookup table built out of the visible expected outputs.

    Only literals that are *new* relative to the baseline count, so a task
    whose reference solution legitimately contains a constant table is not
    penalised.
    """
    expected: List[Any] = []
    for tc in tests:
        if "expected" in tc:
            expected.extend(_flatten(tc["expected"]))
    interesting = {
        v for v in expected
        if not isinstance(v, bool) and (
            (isinstance(v, (int, float)) and abs(v) > 2) or (isinstance(v, str) and len(v) > 2)
        )
    }
    if len(interesting) < min_hits:
        return None
    try:
        cand_lits = set(_flatten(_literal_values(ast.parse(code))))
        base_lits = set(_flatten(_literal_values(ast.parse(baseline_code))))
    except (SyntaxError, TypeError):
        return None
    new_lits = {v for v in cand_lits if v not in base_lits}
    matched = interesting & new_lits
    if len(matched) >= min_hits:
        return Finding(
            "hardcoded_answers", REJECTED,
            f"{len(matched)} expected outputs appear as new literals in the candidate",
            ", ".join(repr(v)[:24] for v in sorted(matched, key=repr)[:8]),
        )
    return None


def check_memoization(code: str, baseline_code: str) -> Optional[Finding]:
    """Cross-call caching is legitimate optimisation *and* a benchmark hazard.

    We do not reject it — we flag it so the runner re-measures with rotated
    inputs, and the report says so out loud.
    """
    try:
        tree = ast.parse(code)
        base = ast.parse(baseline_code)
    except SyntaxError:
        return None

    def memo_names(t: ast.AST) -> Set[str]:
        found: Set[str] = set()
        for node in ast.walk(t):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    n = getattr(dec, "id", None) or getattr(dec, "attr", None)
                    if isinstance(dec, ast.Call):
                        n = getattr(dec.func, "id", None) or getattr(dec.func, "attr", None)
                    if n in _MEMO_DECORATORS:
                        found.add(f"{n}@{node.name}")
        return found

    new = memo_names(tree) - memo_names(base)
    if new:
        return Finding(
            "cross_call_memoization", SUSPECT,
            "candidate added cross-call caching; timing must use rotated inputs",
            ", ".join(sorted(new)),
        )
    return None


def check_entrypoint_preserved(code: str, task: BenchTask) -> Optional[Finding]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == task.entrypoint:
            return None
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == task.entrypoint:
                    return None
    return Finding(
        "entrypoint_preserved", REJECTED,
        f"entrypoint '{task.entrypoint}' is missing from the candidate",
    )


def check_holdout(holdout: Dict[str, Any], *,
                  correctness_via_invariants: bool = False) -> Optional[Finding]:
    """The decisive check: unseen inputs must still produce correct results.

    Heuristic-discovery tasks (tier 3) have no fixed expected output — a better
    heuristic is *supposed* to return something different. There, feasibility
    invariants are the correctness contract, and a missing held-out split is
    declared rather than silently tolerated.
    """
    total = int(holdout.get("tests_total") or 0)
    passed = int(holdout.get("tests_passed") or 0)
    if total == 0:
        if correctness_via_invariants:
            return None
        return Finding(
            "holdout", SUSPECT, "no held-out tests available for this task",
        )
    if passed < total:
        return Finding(
            "holdout", REJECTED,
            f"held-out tests fail ({passed}/{total})",
            "; ".join(str(f) for f in (holdout.get("failures") or [])[:3]),
        )
    return None


def check_measurement_stability(
    optimized: Dict[str, Any], *, max_rel_std: float = 0.25
) -> Optional[Finding]:
    mean = optimized.get("latency_ms_mean") or 0.0
    std = optimized.get("latency_ms_std") or 0.0
    if mean and mean != float("inf") and std / mean > max_rel_std:
        return Finding(
            "measurement_stability", SUSPECT,
            f"cross-run std is {100.0 * std / mean:.1f}% of the mean (noisy machine)",
        )
    return None


def check_warm_cache_anomaly(optimized: Dict[str, Any]) -> Optional[Finding]:
    """First sample far slower than steady state ⇒ something was cached."""
    first = optimized.get("first_sample_ms")
    steady = optimized.get("steady_p50_ms")
    if not first or not steady or steady <= 0:
        return None
    if first / steady > 20.0:
        return Finding(
            "warm_cache_anomaly", SUSPECT,
            f"first sample is {first / steady:.1f}x the steady-state p50 "
            "(results likely cached across samples)",
        )
    return None


def check_trivial_speedup(baseline: Dict[str, Any], optimized: Dict[str, Any]) -> Optional[Finding]:
    """Implausible speedups get flagged rather than celebrated."""
    b = baseline.get("latency_ms_mean") or 0.0
    o = optimized.get("latency_ms_mean") or 0.0
    if not b or not o or o <= 0 or b == float("inf"):
        return None
    if b / o > 100.0:
        return Finding(
            "large_speedup", NOTE,
            f"{b / o:.0f}x speedup — large enough to deserve a manual look at the "
            "diff; held-out tests and invariants passed",
        )
    return None


def check_no_op(code: str, task: BenchTask) -> Optional[Finding]:
    """Entrypoint that ignores its arguments or returns a constant."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == task.entrypoint:
            body = [n for n in node.body if not isinstance(n, ast.Expr) or
                    not isinstance(getattr(n, "value", None), ast.Constant)]
            if len(body) == 1 and isinstance(body[0], ast.Return):
                val = body[0].value
                if val is None or isinstance(val, ast.Constant):
                    return Finding(
                        "no_op_entrypoint", REJECTED,
                        "entrypoint returns a constant and ignores its inputs",
                    )
    return None


# ── orchestration ──────────────────────────────────────────────────────────

def evaluate_integrity(
    task: BenchTask,
    candidate_code: str,
    *,
    holdout: Dict[str, Any],
    baseline: Dict[str, Any],
    optimized: Dict[str, Any],
) -> IntegrityReport:
    """Run every gate and return the combined verdict."""
    report = IntegrityReport()
    report.checks_run = [
        "parses", "forbidden_imports", "dangerous_calls", "entrypoint_preserved",
        "no_op_entrypoint", "hardcoded_answers", "cross_call_memoization",
        "holdout", "warm_cache_anomaly", "measurement_stability",
        "large_speedup",
    ]
    report.add(check_parses(candidate_code))
    if report.verdict == REJECTED:
        return report
    report.add(check_forbidden_imports(candidate_code))
    report.add(check_dangerous_calls(candidate_code))
    report.add(check_entrypoint_preserved(candidate_code, task))
    report.add(check_no_op(candidate_code, task))
    report.add(check_hardcoded_answers(candidate_code, task.source_code, task.all_tests))
    report.add(check_memoization(candidate_code, task.source_code))
    report.add(check_holdout(
        holdout,
        correctness_via_invariants=(task.metadata or {}).get("correctness_via") == "invariants",
    ))
    report.add(check_warm_cache_anomaly(optimized))
    report.add(check_measurement_stability(optimized))
    report.add(check_trivial_speedup(baseline, optimized))
    return report


def strip_markdown_fences(text: str) -> str:
    """LLM hygiene: unwrap ```python fences before anything else looks at it."""
    m = re.search(r"```(?:python|py|cpp|c\+\+|rust)?\s*\n(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


# ── native (C++) variant ───────────────────────────────────────────────────

_CPP_FORBIDDEN = (
    r"\bsystem\s*\(", r"#include\s*<fstream>", r"\bfopen\s*\(", r"\bpopen\s*\(",
    r"#include\s*<thread>", r"\bstd::this_thread::sleep", r"\bexecve\s*\(",
    r"#include\s*<chrono>",
)


def check_cpp_source(code: str) -> List[Finding]:
    """Regex-level gates for the C++ path (PIE).

    A full C++ parse is out of scope; these catch the cheats that actually
    happen: shelling out, reading the expected-output files, forking work onto
    threads that the timer never sees, and clock tampering.
    """
    found: List[Finding] = []
    for pattern in _CPP_FORBIDDEN:
        if re.search(pattern, code):
            severity = SUSPECT if "chrono" in pattern or "thread" in pattern else REJECTED
            found.append(Finding(
                "cpp_forbidden_construct", severity,
                f"candidate uses a construct barred in this benchmark: {pattern}",
            ))
    if "int main" not in code:
        found.append(Finding("entrypoint_preserved", REJECTED,
                             "C++ candidate has no main()"))
    return found


def check_cpp_hardcoded(code: str, tests: Sequence[Dict[str, str]],
                        *, min_hits: int = 2) -> Optional[Finding]:
    """Expected stdout pasted into the program as a string literal."""
    hits = 0
    samples: List[str] = []
    for tc in tests:
        expected = (tc.get("expected_stdout") or "").strip()
        if len(expected) < 4:
            continue
        first_line = expected.splitlines()[0].strip()
        if len(first_line) >= 4 and f'"{first_line}"' in code:
            hits += 1
            samples.append(first_line[:24])
    if hits >= min_hits:
        return Finding("hardcoded_answers", REJECTED,
                       f"{hits} expected outputs appear verbatim in the source",
                       ", ".join(samples[:5]))
    return None


def evaluate_integrity_native(
    task: BenchTask,
    candidate_code: str,
    *,
    holdout: Dict[str, Any],
    baseline: Dict[str, Any],
    optimized: Dict[str, Any],
) -> IntegrityReport:
    report = IntegrityReport()
    report.checks_run = [
        "cpp_forbidden_construct", "entrypoint_preserved", "hardcoded_answers",
        "holdout", "measurement_stability", "large_speedup",
    ]
    for finding in check_cpp_source(candidate_code):
        report.add(finding)
    report.add(check_cpp_hardcoded(
        candidate_code, (task.metadata or {}).get("native_tests") or []))
    report.add(check_holdout(holdout))
    report.add(check_measurement_stability(optimized, max_rel_std=0.35))
    report.add(check_trivial_speedup(baseline, optimized))
    return report
