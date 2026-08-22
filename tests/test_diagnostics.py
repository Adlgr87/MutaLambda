"""Tests for diagnostics (advanced metrics, AST analysis, profiling)."""

import ast

import pytest

from diagnostics import (
    AdvancedMetrics,
    ASTAnalyzer,
    BenchmarkProfiler,
    compute_advanced_metrics,
)


@pytest.mark.root
class TestAdvancedMetrics:
    def test_parsimony_zero_without_code(self):
        assert AdvancedMetrics().parsimony_score == 0.0

    def test_parsimony_decreases_with_complexity(self):
        simple = AdvancedMetrics(lines_of_code=100, cyclomatic_complexity=1)
        complex_ = AdvancedMetrics(lines_of_code=100, cyclomatic_complexity=50)
        assert 0.0 < complex_.parsimony_score < simple.parsimony_score <= 1.0

    def test_to_dict_contains_all_keys(self):
        metrics = AdvancedMetrics(
            latency_p50=1.0,
            latency_p90=2.0,
            latency_p99=3.0,
            latency_std=0.5,
            memory_peak_mb=10.0,
            memory_avg_mb=5.0,
            throughput_ops_sec=42.0,
            ast_node_count=7,
            cyclomatic_complexity=3,
            lines_of_code=4,
        )
        data = metrics.to_dict()
        assert data["latency_p50_ms"] == 1.0
        assert data["ast_nodes"] == 7
        assert data["cyclomatic"] == 3
        assert data["loc"] == 4
        assert data["throughput_ops_sec"] == 42.0
        assert data["parsimony"] == metrics.parsimony_score


@pytest.mark.root
class TestASTAnalyzerCounting:
    def test_count_nodes_grows_with_code_size(self):
        small = ASTAnalyzer.count_nodes(ast.parse("x = 1\n"))
        large = ASTAnalyzer.count_nodes(ast.parse("x = 1\ny = x + 2\nz = y * 3\n"))
        assert small >= 1
        assert large > small

    def test_cyclomatic_base_complexity_is_one(self):
        assert ASTAnalyzer.cyclomatic_complexity(ast.parse("x = 1\n")) == 1

    def test_cyclomatic_counts_branches_and_loops(self):
        code = (
            "def f(n):\n"
            "    for i in range(n):\n"
            "        if i:\n"
            "            while i:\n"
            "                i -= 1\n"
            "    return n\n"
        )
        assert ASTAnalyzer.cyclomatic_complexity(ast.parse(code)) == 4

    def test_cyclomatic_counts_boolop_operands(self):
        code = "def f(a, b, c):\n    return a and b and c\n"
        # BoolOp with 3 values contributes 2
        assert ASTAnalyzer.cyclomatic_complexity(ast.parse(code)) == 3

    def test_cyclomatic_counts_comprehension_and_handler(self):
        code = (
            "def f(xs):\n"
            "    try:\n"
            "        return [x for x in xs]\n"
            "    except ValueError:\n"
            "        return []\n"
        )
        assert ASTAnalyzer.cyclomatic_complexity(ast.parse(code)) == 3


@pytest.mark.root
class TestASTAnalyzerDetection:
    @pytest.mark.parametrize(
        "code",
        [
            "print('hi')\n",
            "f = open('x')\n",
            "data = handle.read()\n",
            "handle.write(payload)\n",
            "urllib(url)\n",
        ],
    )
    def test_detects_io_calls(self, code):
        assert ASTAnalyzer.has_io_calls(ast.parse(code)) is True

    def test_pure_computation_has_no_io(self):
        code = "def f(n):\n    return sum(i * i for i in range(n))\n"
        assert ASTAnalyzer.has_io_calls(ast.parse(code)) is False

    def test_detects_loops_nested_beyond_max_depth(self):
        code = (
            "def f(n):\n"
            "    for i in range(n):\n"
            "        for j in range(n):\n"
            "            for k in range(n):\n"
            "                pass\n"
        )
        assert ASTAnalyzer.has_nested_loops(ast.parse(code)) is True

    def test_single_loop_is_not_nested(self):
        code = "def f(n):\n    for i in range(n):\n        pass\n"
        assert ASTAnalyzer.has_nested_loops(ast.parse(code)) is False

    def test_two_loop_levels_stay_within_default_depth(self):
        code = (
            "def f(n):\n"
            "    for i in range(n):\n"
            "        for j in range(n):\n"
            "            pass\n"
        )
        assert ASTAnalyzer.has_nested_loops(ast.parse(code)) is False

    def test_max_depth_one_flags_two_loop_levels(self):
        code = (
            "def f(n):\n"
            "    for i in range(n):\n"
            "        while n:\n"
            "            n -= 1\n"
        )
        assert ASTAnalyzer.has_nested_loops(ast.parse(code), max_depth=1) is True

    def test_loop_free_code_is_not_nested(self):
        assert ASTAnalyzer.has_nested_loops(ast.parse("x = 1\n")) is False


@pytest.mark.root
class TestBenchmarkProfiler:
    def test_profile_returns_ordered_statistics(self):
        profiler = BenchmarkProfiler(samples=5)
        calls = []
        stats = profiler.profile(lambda: calls.append(1))

        assert len(calls) == 5
        assert set(stats) == {"p50", "p90", "p99", "std", "mean", "min", "max"}
        assert stats["min"] <= stats["p50"] <= stats["max"]
        assert stats["p99"] == stats["max"]  # fewer than 100 samples

    def test_profile_single_sample_has_zero_std(self):
        stats = BenchmarkProfiler(samples=1).profile(lambda: None)
        assert stats["std"] == 0.0
        assert stats["min"] == stats["max"]

    def test_profile_forwards_arguments(self):
        seen = []
        profiler = BenchmarkProfiler(samples=2)
        profiler.profile(lambda a, b=None: seen.append((a, b)), 1, b=2)
        assert seen == [(1, 2), (1, 2)]


@pytest.mark.root
class TestComputeAdvancedMetrics:
    def test_static_metrics_from_code(self):
        code = "def f(n):\n    if n:\n        return 1\n    return 0\n"
        metrics = compute_advanced_metrics(code)
        assert metrics.lines_of_code == 4
        assert metrics.ast_node_count > 0
        assert metrics.cyclomatic_complexity == 2
        assert metrics.latency_p50 == 0.0

    def test_invalid_syntax_yields_empty_static_metrics(self):
        metrics = compute_advanced_metrics("def f(:\n")
        assert metrics.ast_node_count == 0
        assert metrics.lines_of_code == 0
        assert metrics.cyclomatic_complexity == 0

    def test_runtime_metrics_populated_when_func_given(self):
        metrics = compute_advanced_metrics("x = 1\n", func=lambda: sum(range(100)))
        assert metrics.latency_p50 > 0.0
        assert metrics.latency_p90 >= metrics.latency_p50

    def test_failing_func_does_not_raise(self):
        def boom():
            raise RuntimeError("nope")

        metrics = compute_advanced_metrics("x = 1\n", func=boom)
        assert metrics.latency_p50 == 0.0
        assert metrics.ast_node_count > 0
