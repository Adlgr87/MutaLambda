#!/usr/bin/env python3
"""Tests for CI/CD integration in MutaLambda."""
import pytest
import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import json
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from mutalambda.muta_ext.ci_integration import (
    PerformanceBaseline,
    RegressionDetector,
    PRAnalyzer,
    FunctionBaseline,
    RegressionResult,
    create_ci_pipeline
)


class TestPerformanceBaseline:
    """Test baseline management."""

    def test_register_baseline(self):
        """Test registering a performance baseline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PerformanceBaseline(storage_dir=tmpdir)
            
            manager.register_baseline(
                file_path="/path/to/main.go",
                function_name="sort_data",
                language="go",
                fitness={"latency_p50": 100.0, "memory_peak_mb": 50.0},
                code="func sort_data() {}",
                commit_hash="abc123",
                branch="main"
            )
            
            baseline = manager.get_baseline("/path/to/main.go", "sort_data")
            assert baseline is not None
            assert baseline.function_name == "sort_data"
            assert baseline.language == "go"
            assert baseline.commit_hash == "abc123"

    def test_get_baseline_not_found(self):
        """Test getting non-existent baseline."""
        manager = PerformanceBaseline()
        baseline = manager.get_baseline("/nonexistent.go", "func")
        assert baseline is None

    def test_list_baselines(self):
        """Test listing all baselines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PerformanceBaseline(storage_dir=tmpdir)
            
            manager.register_baseline(
                file_path="/path/to/a.go",
                function_name="func_a",
                language="go",
                fitness={"latency_p50": 100.0},
                code="code_a",
                commit_hash="hash1"
            )
            manager.register_baseline(
                file_path="/path/to/b.go",
                function_name="func_b",
                language="go",
                fitness={"latency_p50": 200.0},
                code="code_b",
                commit_hash="hash2"
            )
            
            baselines = manager.list_baselines()
            assert len(baselines) == 2

    def test_list_baselines_with_filter(self):
        """Test filtering baselines by file pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = PerformanceBaseline(storage_dir=tmpdir)
            
            manager.register_baseline(
                file_path="/path/to/a.go",
                function_name="func_a",
                language="go",
                fitness={"latency_p50": 100.0},
                code="code_a",
                commit_hash="hash1"
            )
            manager.register_baseline(
                file_path="/other/b.go",
                function_name="func_b",
                language="go",
                fitness={"latency_p50": 200.0},
                code="code_b",
                commit_hash="hash2"
            )
            
            filtered = manager.list_baselines(file_pattern="path/to")
            assert len(filtered) == 1
            assert "a.go" in filtered[0].file_path


class TestRegressionDetector:
    """Test regression detection."""

    def test_no_regression(self):
        """Test when there's no regression."""
        detector = RegressionDetector(threshold=0.1)
        
        baseline = FunctionBaseline(
            function_name="test_func",
            file_path="/path/to/test.go",
            language="go",
            baseline_fitness={"latency_p50": 100.0},
            baseline_code="code",
            recorded_at=datetime.now().isoformat(),
            commit_hash="hash",
            branch="main"
        )
        
        current_fitness = {"latency_p50": 90.0}  # Better!
        
        result = detector.detect_regression(baseline, current_fitness)
        assert result.regression_detected is False
        assert result.severity == "minor"

    def test_minor_regression(self):
        """Test detecting minor regression."""
        detector = RegressionDetector(threshold=0.1)
        
        baseline = FunctionBaseline(
            function_name="test_func",
            file_path="/path/to/test.go",
            language="go",
            baseline_fitness={"latency_p50": 100.0},
            baseline_code="code",
            recorded_at=datetime.now().isoformat(),
            commit_hash="hash",
            branch="main"
        )
        
        current_fitness = {"latency_p50": 105.0}  # 5% worse
        
        result = detector.detect_regression(baseline, current_fitness)
        assert result.regression_detected is True
        assert result.severity == "minor"

    def test_major_regression(self):
        """Test detecting major regression."""
        detector = RegressionDetector(threshold=0.1, critical_threshold=0.3)
        
        baseline = FunctionBaseline(
            function_name="test_func",
            file_path="/path/to/test.go",
            language="go",
            baseline_fitness={"latency_p50": 100.0},
            baseline_code="code",
            recorded_at=datetime.now().isoformat(),
            commit_hash="hash",
            branch="main"
        )
        
        current_fitness = {"latency_p50": 125.0}  # 25% worse
        
        result = detector.detect_regression(baseline, current_fitness)
        assert result.regression_detected is True
        assert result.severity in ["major", "critical"]

    def test_critical_regression(self):
        """Test detecting critical regression."""
        detector = RegressionDetector(threshold=0.1, critical_threshold=0.3)
        
        baseline = FunctionBaseline(
            function_name="test_func",
            file_path="/path/to/test.go",
            language="go",
            baseline_fitness={"latency_p50": 100.0},
            baseline_code="code",
            recorded_at=datetime.now().isoformat(),
            commit_hash="hash",
            branch="main"
        )
        
        current_fitness = {"latency_p50": 150.0}  # 50% worse
        
        result = detector.detect_regression(baseline, current_fitness)
        assert result.regression_detected is True
        assert result.severity == "critical"


class TestPRAnalyzer:
    """Test PR analysis functionality."""

    @patch('mutalambda.muta_ext.ci_integration.subprocess.run')
    def test_analyze_pr_no_regressions(self, mock_subprocess):
        """Test PR analysis with no regressions."""
        mock_subprocess.return_value = MagicMock(
            stdout="file1.go\nfile2.go\n",
            returncode=0
        )
        
        baselines = PerformanceBaseline()
        detector = RegressionDetector()
        analyzer = PRAnalyzer(baselines, detector)
        
        # Mock the measurement to return better performance
        with patch.object(analyzer, '_measure_current_performance') as mock_measure:
            mock_measure.return_value = {"latency_p50": 50.0}  # Better than baseline
            
            result = analyzer.analyze_pr(
                pr_number=42,
                branch="feature-branch",
                base_branch="main"
            )
            
            assert result.pr_number == 42
            assert result.branch == "feature-branch"
            assert result.overall_status in ["pass", "warning", "fail"]

    def test_pr_analysis_result_structure(self):
        """Test PR analysis result structure."""
        result = RegressionResult(
            function_name="test_func",
            file_path="/path/to/test.go",
            regression_detected=True,
            degradation_percentage=25.0,
            severity="major",
            suggestion="Review algorithm",
            baseline_fitness={"latency_p50": 100.0},
            current_fitness={"latency_p50": 125.0}
        )
        
        assert result.regression_detected is True
        assert result.degradation_percentage == 25.0
        assert result.severity == "major"


class TestCIIntegration:
    """Integration tests for CI functionality."""

    def test_create_ci_pipeline(self):
        """Test CI pipeline creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Change to temp directory
            original_cwd = Path.cwd()
            try:
                import os
                os.chdir(tmpdir)
                
                # Initialize git repo
                subprocess.run(["git", "init"], capture_output=True)
                subprocess.run(["git", "config", "user.email", "test@test.com"], capture_output=True)
                subprocess.run(["git", "config", "user.name", "Test User"], capture_output=True)
                
                result = create_ci_pipeline(repo_path=tmpdir)
                
                assert result is not None
                assert hasattr(result, 'overall_status')
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
