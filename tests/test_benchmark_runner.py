"""Tests for benchmark runner (FASE 6)."""

import json
import pytest
import numpy as np
from pathlib import Path

from benchmark_runner import BenchmarkRunner, BenchmarkConfig, BenchmarkResult, run_phase6_benchmark


class TestBenchmarkResult:
    def test_to_dict(self):
        r = BenchmarkResult(
            benchmark_name="test",
            method="cpu",
            duration_sec=1.5,
            score=0.95,
            throughput=100.0,
            memory_mb=50.0,
            success=True,
        )
        d = r.to_dict()
        assert d["benchmark_name"] == "test"
        assert d["duration_sec"] == 1.5
        assert d["success"] is True

    def test_to_json(self):
        r = BenchmarkResult(
            benchmark_name="test",
            method="cpu",
            duration_sec=1.0,
            score=1.0,
            throughput=50.0,
            memory_mb=0.0,
            success=True,
        )
        d = json.loads(r.to_json())
        assert d["benchmark_name"] == "test"


class TestBenchmarkRunner:
    def setup_method(self):
        self.runner = BenchmarkRunner(BenchmarkConfig(
            num_repeats=1,
            num_generations=2,
            population_size=4,
            report_dir="/tmp/mutalambda_test_reports",
        ))

    def test_run_benchmark_cpu(self):
        pop = np.random.randn(4, 5)

        def fitness(ind):
            return float(np.sum(ind ** 2))

        result = self.runner.run_benchmark("sphere", fitness, pop, method="cpu")
        assert result.success
        assert result.duration_sec > 0
        assert result.score < float("inf")

    def test_run_benchmark_fails_gracefully(self):
        pop = np.random.randn(2, 3)

        def bad_fitness(ind):
            raise ValueError("intentional error")

        result = self.runner.run_benchmark("bad", bad_fitness, pop, method="cpu")
        assert not result.success
        assert result.error is not None
        assert "intentional error" in result.error

    def test_compute_statistics(self):
        results = [
            BenchmarkResult("t", "cpu", 1.0, 0.5, 50.0, 0.0, True),
            BenchmarkResult("t", "cpu", 1.2, 0.6, 45.0, 0.0, True),
            BenchmarkResult("t", "cpu", 0.9, 0.4, 55.0, 0.0, True),
        ]
        stats = self.runner._compute_statistics("test", results)
        assert stats["num_runs"] == 3
        assert stats["successful_runs"] == 3
        assert "duration_mean" in stats

    def test_generate_report(self):
        pop = np.random.randn(4, 5)

        def fitness(ind):
            return float(np.sum(ind ** 2))

        self.runner.run_benchmark("sphere", fitness, pop, method="cpu")
        report_path = self.runner.generate_report()
        assert report_path.exists()
        data = json.loads(report_path.read_text())
        assert "results" in data
        assert "summary" in data

    def test_print_report(self, capsys):
        pop = np.random.randn(4, 5)

        def fitness(ind):
            return float(np.sum(ind ** 2))

        self.runner.run_benchmark("sphere", fitness, pop, method="cpu")
        self.runner.print_report()
        captured = capsys.readouterr()
        assert "MutaLambda Benchmark Report" in captured.out


class TestPhase6Benchmark:
    def test_run_phase6(self, tmp_path):
        config = BenchmarkConfig(
            num_generations=2,
            population_size=4,
            num_repeats=1,
            report_dir=str(tmp_path / "reports"),
        )
        runner = BenchmarkRunner(config)
        runner = run_phase6_benchmark(
            num_generations=2,
            population_size=4,
            num_repeats=1,
            cpu_only=True,
        )
        assert len(runner._results) > 0
        assert runner._results[0].success
