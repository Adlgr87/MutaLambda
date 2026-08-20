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
from typing import List, Dict, Optional, Callable, Any
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

exec(open("{script_path}").read())

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.dump_stats('/tmp/mutalambda_profile.prof')
stats.print_stats(20)
"""

        result = subprocess.run(
            [sys.executable, '-c', profiler_script],
            capture_output=True, text=True, timeout=60
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
        stats.sort_stats('cumulative')

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

    def _analyze_function(self, node: ast.FunctionDef, full_code: str, 
                          profile_data: Dict = None) -> Optional[Hotspot]:
        """Analyze a single function for optimization potential."""
        lines = full_code.splitlines()
        func_lines = lines[node.lineno - 1:node.end_lineno]
        func_code = '
'.join(func_lines)

        # Generate optimization hint
        hint = self._generate_hint(node, func_code)

        # Estimate time from profile or use heuristics
        cumulative_time = 0.0
        call_count = 0
        if profile_data and node.name in profile_data:
            cumulative_time = profile_data[node.name].get('cumulative', 0.0)
            call_count = profile_data[node.name].get('calls', 0)
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
            hints.append(f"Tiene bucles anidados (profundidad {loop_depth}) que pueden vectorizarse con NumPy")

        # Check for list operations
        if 'append' in code:
            hints.append("Usa list.append en bucle - pre-asignación o list comprehension puede ser más rápido")

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
                call_str = ast.unparse(child) if hasattr(ast, 'unparse') else str(child)
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
            if 'ncalls' in line and 'tottime' in line:
                in_data = True
                continue
            if in_data and line.strip() and not line.startswith(' '):
                break
            if in_data and line.strip():
                parts = line.split()
                if len(parts) >= 6:
                    try:
                        # Parse function location
                        func_info = ' '.join(parts[5:])
                        if ':' in func_info:
                            file_path, rest = func_info.split(':', 1)
                            func_name = rest.split('(')[0] if '(' in rest else rest

                            hotspot = Hotspot(
                                name=func_name.strip(),
                                file=file_path,
                                line_start=0,
                                line_end=0,
                                cumulative_time=float(parts[3]) if len(parts) > 3 else 0.0,
                                call_count=int(parts[0].split('/')[0]) if parts[0] != '1' else 1,
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

        return '
'.join(report)
