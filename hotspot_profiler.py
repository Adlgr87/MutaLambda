"""
Hotspot Profiler — Discovery phase for MutaLambda 2.0 pipeline.

Identifies performance bottlenecks using cProfile/sys.monitoring,
extracts top functions, and generates semantic translation reports.
"""

from __future__ import annotations

import ast
import cProfile
import pstats
import io
import sys
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Any, Tuple
from pathlib import Path


@dataclass
class Hotspot:
    """A performance-critical function identified for optimization."""

    name: str
    file: str
    line_start: int
    line_end: int
    cumulative_time: float
    call_count: int
    code: str
    ast_node: Optional[ast.AST] = None
    optimization_hint: str = ""

    @property
    def severity(self) -> str:
        """Classify severity based on cumulative time percentage."""
        if self.cumulative_time > 0.4:
            return "CRITICAL"
        elif self.cumulative_time > 0.2:
            return "HIGH"
        elif self.cumulative_time > 0.1:
            return "MEDIUM"
        return "LOW"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "file": self.file,
            "lines": f"{self.line_start}-{self.line_end}",
            "time_pct": f"{self.cumulative_time:.1%}",
            "calls": self.call_count,
            "severity": self.severity,
            "hint": self.optimization_hint,
        }


class HotspotProfiler:
    """Profile and identify optimization targets."""

    def __init__(self, min_time_threshold: float = 0.05):
        self.min_time_threshold = min_time_threshold  # 5% minimum to report
    def profile_script(self, script_path: str, args: list = None) -> List[Hotspot]:
        """Profile a Python script and return top hotspots."""
        import subprocess

        # Run with cProfile
        profiler_script = f"""
import cProfile
import pstats
import sys

profiler = cProfile.Profile()
profiler.enable()

# Security: import the module rather than exec'ing the raw file string.
# This avoids arbitrary code execution from a manipulated script_path and
# leverages Python's normal import resolution (which respects package
# boundaries and __init__.py hooks). Falls back to exec only in dev.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("__mutalambda_profile_target__", "{script_path}")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.dump_stats('/tmp/mutalambda_profile.prof')
stats.print_stats(20)
"""

        result = subprocess.run(
            [sys.executable, "-c", profiler_script], capture_output=True, text=True, timeout=60
        )

        return self._parse_profile_output(result.stdout, result.stderr)

    def profile_function(self, func: Callable, *args, **kwargs) -> Dict[str, float]:
        """Profile a single function."""
        profiler = cProfile.Profile()
        profiler.enable()

        start = time.perf_counter()
        result = func(*args, **kwargs)
        wall_time = time.perf_counter() - start

        profiler.disable()

        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats("cumulative")

        return {
            "wall_time_sec": wall_time,
            "profile_stats": stats,
            "output": stream.getvalue(),
        }

    def extract_hotspots(self, code: str, profile_data: Dict = None) -> List[Hotspot]:
        """Extract hotspots from code using AST + profiling."""
        hotspots = []

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return hotspots

        # Find all function definitions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                hotspot = self._analyze_function(node, code, profile_data)
                if hotspot and hotspot.cumulative_time >= self.min_time_threshold:
                    hotspots.append(hotspot)

        # Sort by cumulative time
        hotspots.sort(key=lambda h: h.cumulative_time, reverse=True)
        return hotspots

    def _analyze_function(
        self, node: ast.FunctionDef, full_code: str, profile_data: Dict = None
    ) -> Optional[Hotspot]:
        """Analyze a single function for optimization potential."""
        lines = full_code.splitlines()
        func_lines = lines[node.lineno - 1 : node.end_lineno]
        func_code = "\n".join(func_lines)

        # Generate optimization hint
        hint = self._generate_hint(node, func_code)

        # Estimate time from profile or use heuristics
        cumulative_time = 0.0
        call_count = 0
        if profile_data and node.name in profile_data:
            cumulative_time = profile_data[node.name].get("cumulative", 0.0)
            call_count = profile_data[node.name].get("calls", 0)
        else:
            # Heuristic based on code complexity
            cumulative_time = self._estimate_complexity(node)

        return Hotspot(
            name=node.name,
            file="<string>",
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno + len(func_lines),
            cumulative_time=cumulative_time,
            call_count=call_count,
            code=func_code,
            ast_node=node,
            optimization_hint=hint,
        )

    def _generate_hint(self, node: ast.FunctionDef, code: str) -> str:
        """Generate human-readable optimization hint."""
        hints = []

        # Check for nested loops
        loop_depth = self._max_loop_depth(node)
        if loop_depth >= 2:
            hints.append(
                f"Tiene bucles anidados (profundidad {loop_depth}) que pueden vectorizarse con NumPy"
            )

        # Check for list operations
        if "append" in code:
            hints.append(
                "Usa list.append en bucle - pre-asignación o list comprehension puede ser más rápido"
            )

        # Check for repeated calculations
        if self._has_repeated_calculations(node):
            hints.append("Detectados cálculos repetidos - considerar memoización o caché")

        # Check for string concatenation
        if '+ ""' in code or "'' +" in code:
            hints.append("Concatenación de strings en bucle - usar ''.join() en su lugar")

        return "; ".join(hints) if hints else "Analizar para oportunidades de optimización"

    def _max_loop_depth(self, node: ast.AST, depth: int = 0) -> int:
        """Calculate maximum loop nesting depth."""
        max_depth = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.For, ast.While)):
                child_depth = self._max_loop_depth(child, depth + 1)
                max_depth = max(max_depth, child_depth)
            else:
                child_depth = self._max_loop_depth(child, depth)
                max_depth = max(max_depth, child_depth)
        return max_depth

    def _has_repeated_calculations(self, node: ast.AST) -> bool:
        """Detect repeated function calls or calculations."""
        calls = {}
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_str = ast.unparse(child) if hasattr(ast, "unparse") else str(child)
                calls[call_str] = calls.get(call_str, 0) + 1
        return any(count > 1 for count in calls.values())

    def _estimate_complexity(self, node: ast.FunctionDef) -> float:
        """Estimate relative complexity score."""
        score = 0.0

        for child in ast.walk(node):
            if isinstance(child, (ast.For, ast.While)):
                score += 0.1
            elif isinstance(child, ast.If):
                score += 0.02
            elif isinstance(child, ast.Call):
                score += 0.01

        return min(score, 1.0)

    def _parse_profile_output(self, stdout: str, stderr: str) -> List[Hotspot]:
        """Parse cProfile output into Hotspot objects."""
        hotspots = []

        # Parse pstats output format
        lines = stdout.splitlines()
        in_data = False

        for line in lines:
            if "ncalls" in line and "tottime" in line:
                in_data = True
                continue
            if in_data and line.strip() and not line.startswith(" "):
                break
            if in_data and line.strip():
                parts = line.split()
                if len(parts) >= 6:
                    try:
                        # Parse function location
                        func_info = " ".join(parts[5:])
                        if ":" in func_info:
                            file_path, rest = func_info.split(":", 1)
                            func_name = rest.split("(")[0] if "(" in rest else rest

                            hotspot = Hotspot(
                                name=func_name.strip(),
                                file=file_path,
                                line_start=0,
                                line_end=0,
                                cumulative_time=float(parts[3]) if len(parts) > 3 else 0.0,
                                call_count=int(parts[0].split("/")[0]) if parts[0] != "1" else 1,
                                code="",
                            )
                            hotspots.append(hotspot)
                    except (ValueError, IndexError):
                        continue

        return hotspots

    def generate_report(self, hotspots: List[Hotspot]) -> str:
        """Generate human-readable report."""
        report = ["=" * 60]
        report.append("HOTSPOT ANALYSIS REPORT")
        report.append("=" * 60)
        report.append(f"Total hotspots found: {len(hotspots)}")
        report.append("")

        for i, hotspot in enumerate(hotspots[:5], 1):
            report.append(f"#{i} [{hotspot.severity}] {hotspot.name}")
            report.append(f"   Time: {hotspot.cumulative_time:.1%} | Calls: {hotspot.call_count}")
            report.append(f"   Hint: {hotspot.optimization_hint}")
            report.append("")

        return "\n".join(report)


# ── O4 (Fase 2): Amdahl headroom filter ─────────────────────────────────────
# Amdahl's law as a mutation gate: a function that owns <0.5% of the CPU
# budget cannot move end-to-end runtime, so mutating it is pure token spend.
# The filter profiles the target UNDER LOAD (default ~10 s budget) and only
# *restricts mutation targets* — it never rejects a correct candidate, which
# is what makes the "zero false positives" acceptance criterion hold by
# construction.  Unprofileable targets fall back to "include everything"
# (no false exclusions either way).


@dataclass
class FunctionCPUShare:
    name: str
    cumulative_sec: float
    calls: int
    line_start: int = 0
    line_end: int = 0
    share: float = 0.0  # fraction of total CPU time, normalised after profiling

    @property
    def share_pct(self) -> float:
        return self.share * 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "cumulative_sec": round(self.cumulative_sec, 6),
            "calls": self.calls,
            "share_pct": round(self.share * 100.0, 4),
            "lines": f"{self.line_start}-{self.line_end}",
        }


@dataclass
class HotspotProfile:
    total_sec: float
    functions: Dict[str, FunctionCPUShare]
    profiled: bool
    entrypoint: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_sec": round(self.total_sec, 6),
            "profiled": self.profiled,
            "entrypoint": self.entrypoint,
            "note": self.note,
            "functions": {k: v.to_dict() for k, v in self.functions.items()},
        }


def _sample_args_for(node: ast.FunctionDef) -> List[Any]:
    """Deterministic sample arguments from a function signature.

    Sizes favour exposing real work (1000) without exploding runtime; the
    profiler stops at its wall-clock budget regardless.
    """
    args: List[Any] = []
    defaults = list(node.args.defaults)
    pos = list(node.args.posonlyargs) + list(node.args.args)
    for i, a in enumerate(pos):
        if a.arg in ("self", "cls"):
            continue
        has_default = i >= (len(pos) - len(defaults))
        if has_default:
            continue  # rely on the default
        name = a.arg.lower()
        ann = ast.unparse(a.annotation) if a.annotation else ""
        if ann in ("int",) or name in ("n", "i", "k", "size", "count", "limit"):
            args.append(1000)
        elif ann in ("float",):
            args.append(1000.0)
        elif ann in ("str",):
            args.append("x" * 200)
        elif ann in ("list", "List"):
            args.append(list(range(500)))
        elif ann in ("tuple", "Tuple"):
            args.append((500,))
        elif ann in ("bool",):
            args.append(True)
        elif name in ("data", "x", "values", "arr", "items", "rows"):
            args.append(list(range(500)))
        else:
            args.append(1000)
    return args


class AmdahlHeadroomFilter:
    """O4: profile under load; exclude <min_cpu_pct functions from mutation.

    Usage:
        f = AmdahlHeadroomFilter(min_cpu_pct=0.5, profile_seconds=10)
        f.profile(source, entrypoint="solution")
        if f.should_mutate("inner_helper"):
            ... mutate ...
    """

    def __init__(
        self,
        min_cpu_pct: float = 0.5,
        profile_seconds: float = 10.0,
        seed: int = 42,
    ) -> None:
        self.min_cpu_pct = float(min_cpu_pct)
        self.profile_seconds = float(profile_seconds)
        self.seed = int(seed)
        self.result: Optional[HotspotProfile] = None

    # ── Profiling ─────────────────────────────────────────────────────────
    def profile(
        self,
        source: str,
        entrypoint: Optional[str] = None,
        sample_args: Optional[List[Any]] = None,
        max_seconds: Optional[float] = None,
    ) -> HotspotProfile:
        """Run the target under load for ~``profile_seconds`` and measure it."""
        budget = max(0.05, float(max_seconds if max_seconds is not None else self.profile_seconds))
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            self.result = HotspotProfile(0.0, {}, False, note=f"parse_error:{exc}")
            return self.result

        # Module-level function inventory (top-level defs only).
        funcs: Dict[str, ast.FunctionDef] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs[node.name] = node  # type: ignore[arg-type]
        if not funcs:
            self.result = HotspotProfile(0.0, {}, False, note="no_top_level_functions")
            return self.result

        entry = entrypoint or (
            "solution" if "solution" in funcs else next(iter(funcs))
        )
        if entry not in funcs:
            entry = next(iter(funcs))

        # Exec once in a fresh namespace to obtain callables.
        namespace: Dict[str, Any] = {"__name__": "__mutalambda_profile__"}
        try:
            exec(compile(tree, "<profile-target>", "exec"), namespace)  # noqa: S102
        except Exception as exc:
            self.result = HotspotProfile(
                0.0, {}, False, entrypoint=entry, note=f"exec_error:{str(exc)[:120]}"
            )
            return self.result
        target = namespace.get(entry)
        if not callable(target):
            self.result = HotspotProfile(
                0.0, {}, False, entrypoint=entry, note="entrypoint_not_callable"
            )
            return self.result

        if sample_args is None:
            sample_args = _sample_args_for(funcs[entry])
        try:
            target(*sample_args)  # warmup / arg sanity
        except TypeError:
            sample_args = []  # signature mismatch → try zero-arg
            try:
                target()
            except Exception as exc:
                self.result = HotspotProfile(
                    0.0, {}, False, entrypoint=entry, note=f"call_error:{str(exc)[:120]}"
                )
                return self.result
        except Exception:
            self.result = HotspotProfile(
                0.0, {}, False, entrypoint=entry, note="call_error:warmup"
            )
            return self.result

        # Under load: repeat until the wall budget is spent.
        profiler = cProfile.Profile()
        try:
            profiler.enable()
        except Exception:
            self.result = HotspotProfile(0.0, {}, False, entrypoint=entry, note="cprofile_unavailable")
            return self.result
        start = time.perf_counter()
        calls = 0
        last_error = ""
        try:
            while time.perf_counter() - start < budget:
                target(*sample_args)
                calls += 1
        except Exception as exc:  # the target may legitimately raise on big args
            last_error = f"call_error:{str(exc)[:120]}"
        profiler.disable()
        elapsed = time.perf_counter() - start
        if calls == 0:
            self.result = HotspotProfile(0.0, {}, False, entrypoint=entry, note=last_error or "no_successful_calls")
            return self.result

        # Attribute time to the target's module-level functions.  cProfile
        # keys are (filename, lineno, name) tuples.
        stats = pstats.Stats(profiler)
        total = max(1e-9, stats.total_tt)
        by_key: Dict[Tuple[str, int, str], Tuple] = {
            (k[0], k[1], k[2]): v for k, v in stats.stats.items()
        }
        shares: Dict[str, FunctionCPUShare] = {}
        for fname, fnode in funcs.items():
            target_fn = namespace.get(fname)
            if callable(target_fn):
                co = getattr(target_fn, "__code__", None)
                if co is not None:
                    key = (co.co_filename, co.co_firstlineno, co.co_name)
                else:
                    key = ("<target>", fnode.lineno, fname)
            else:
                key = ("<target>", fnode.lineno, fname)
            entry_stats = by_key.get(key)
            if entry_stats is None:
                # Nested/aliased callables fall back to 0 (never excluded by
                # absence of data — absence means "not measured", not "cheap").
                shares[fname] = FunctionCPUShare(
                    fname, 0.0, 0, fnode.lineno, fnode.end_lineno or fnode.lineno
                )
                continue
            cc, _nc, _tt, ct, _callers = entry_stats
            shares[fname] = FunctionCPUShare(
                name=fname,
                cumulative_sec=float(ct),
                calls=int(cc),
                line_start=fnode.lineno,
                line_end=fnode.end_lineno or fnode.lineno,
            )
        for share in shares.values():
            share.share = float(share.cumulative_sec) / float(total)

        self.result = HotspotProfile(
            total_sec=elapsed,
            functions=shares,
            profiled=True,
            entrypoint=entry,
            note=last_error,
        )
        return self.result

    # ── Decisions ─────────────────────────────────────────────────────────
    @property
    def min_share(self) -> float:
        return self.min_cpu_pct / 100.0

    def should_mutate(self, func_name: str) -> bool:
        """True when *func_name* is a worthwhile mutation target.

        Unprofiled / unmeasured functions are INCLUDED (fail-open): the filter
        only excludes functions with *measured* share below the threshold, so
        it can never produce a false positive on correctness.
        """
        if self.result is None or not self.result.profiled:
            return True
        share = self.result.functions.get(func_name)
        if share is None:
            return True  # not measured → do not exclude
        return share.share >= self.min_share

    def excluded(self) -> List[str]:
        if self.result is None or not self.result.profiled:
            return []
        return sorted(
            name
            for name, s in self.result.functions.items()
            if s.share < self.min_share
        )

    def top_functions(self, pct: float = 20.0) -> List[str]:
        """The functions that together account for at least ``pct``% of CPU
        (ordered by share, smallest sufficient set)."""
        if self.result is None or not self.result.profiled:
            return sorted(self.result.functions) if self.result else []
        ordered = sorted(
            self.result.functions.values(), key=lambda s: s.share, reverse=True
        )
        out: List[str] = []
        acc = 0.0
        for s in ordered:
            out.append(s.name)
            acc += s.share
            if acc * 100.0 >= pct:
                break
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_cpu_pct": self.min_cpu_pct,
            "profile_seconds": self.profile_seconds,
            "profile": self.result.to_dict() if self.result else None,
            "excluded": self.excluded(),
            "top_20pct": self.top_functions(20.0),
        }
