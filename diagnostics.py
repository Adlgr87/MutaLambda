"""
Diagnostics — Advanced metrics for deep analysis (opt-in via --advanced-diagnostics).

Moved from core fitness to keep selective pressure strong with 3 objectives.
Activated only when detailed analysis is needed.
"""

from __future__ import annotations

import ast
import time
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Callable
import sys


@dataclass
class AdvancedMetrics:
    """Extended fitness metrics for diagnostics mode."""

    # Latency distribution
    latency_p50: float = 0.0
    latency_p90: float = 0.0
    latency_p99: float = 0.0
    latency_std: float = 0.0

    # Memory
    memory_peak_mb: float = 0.0
    memory_avg_mb: float = 0.0

    # Throughput
    throughput_ops_sec: float = 0.0

    # Code complexity (Parsimony)
    ast_node_count: int = 0
    cyclomatic_complexity: int = 0
    lines_of_code: int = 0

    @property
    def parsimony_score(self) -> float:
        """Higher = simpler code. Based on cyclomatic complexity per KB."""
        if self.lines_of_code == 0:
            return 0.0
        kb = self.lines_of_code / 1024
        return 1.0 / (1.0 + self.cyclomatic_complexity / max(kb, 0.001))

    def to_dict(self) -> Dict[str, float]:
        return {
            "latency_p50_ms": self.latency_p50,
            "latency_p90_ms": self.latency_p90,
            "latency_p99_ms": self.latency_p99,
            "latency_std_ms": self.latency_std,
            "memory_peak_mb": self.memory_peak_mb,
            "memory_avg_mb": self.memory_avg_mb,
            "throughput_ops_sec": self.throughput_ops_sec,
            "ast_nodes": self.ast_node_count,
            "cyclomatic": self.cyclomatic_complexity,
            "loc": self.lines_of_code,
            "parsimony": self.parsimony_score,
        }


class ASTAnalyzer:
    """Static analysis of Python AST for complexity metrics."""

    @staticmethod
    def count_nodes(tree: ast.AST) -> int:
        """Count total AST nodes."""
        return sum(1 for _ in ast.walk(tree))

    @staticmethod
    def cyclomatic_complexity(tree: ast.AST) -> int:
        """Estimate cyclomatic complexity."""
        complexity = 1  # Base complexity
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.For, 
                                 ast.ExceptHandler, ast.With,
                                 ast.comprehension)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
        return complexity

    @staticmethod
    def has_io_calls(tree: ast.AST) -> bool:
        """Detect I/O operations in AST."""
        io_functions = {'open', 'read', 'write', 'print', 'input',
                       'socket', 'requests', 'urllib'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in io_functions:
                        return True
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in io_functions:
                        return True
        return False

    @staticmethod
    def has_nested_loops(tree: ast.AST, max_depth: int = 2) -> bool:
        """Check for nested loops up to max_depth."""
        def _check_depth(node, depth=0):
            if depth >= max_depth:
                return True
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.For, ast.While)):
                    if _check_depth(child, depth + 1):
                        return True
                else:
                    if _check_depth(child, depth):
                        return True
            return False

        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While)):
                if _check_depth(node, 0):
                    return True
        return False


class BenchmarkProfiler:
    """Statistical profiling for latency distribution."""

    def __init__(self, samples: int = 10):
        self.samples = samples

    def profile(self, func: Callable, *args, **kwargs) -> Dict[str, float]:
        """Run function multiple times and collect timing statistics."""
        times = []
        for _ in range(self.samples):
            start = time.perf_counter()
            func(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000  # ms
            times.append(elapsed)

        times.sort()
        n = len(times)

        return {
            "p50": times[n // 2],
            "p90": times[int(n * 0.9)],
            "p99": times[int(n * 0.99)] if n >= 100 else times[-1],
            "std": statistics.stdev(times) if n > 1 else 0.0,
            "mean": statistics.mean(times),
            "min": times[0],
            "max": times[-1],
        }


def compute_advanced_metrics(code: str, func: Optional[Callable] = None) -> AdvancedMetrics:
    """Compute all advanced metrics for a code snippet."""
    metrics = AdvancedMetrics()

    # AST analysis
    try:
        tree = ast.parse(code)
        analyzer = ASTAnalyzer()
        metrics.ast_node_count = analyzer.count_nodes(tree)
        metrics.cyclomatic_complexity = analyzer.cyclomatic_complexity(tree)
        metrics.lines_of_code = len(code.strip().splitlines())
    except SyntaxError:
        pass

    # Runtime profiling (if function provided)
    if func is not None:
        profiler = BenchmarkProfiler()
        try:
            stats = profiler.profile(func)
            metrics.latency_p50 = stats["p50"]
            metrics.latency_p90 = stats["p90"]
            metrics.latency_p99 = stats["p99"]
            metrics.latency_std = stats["std"]
        except Exception:
            pass

    return metrics
