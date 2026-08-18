#!/usr/bin/env python3
"""CI/CD Integration Module for MutaLambda Performance Regression Testing.

This module provides:
- Baseline fitness tracking per function
- Pull request analysis
- Performance regression detection
- Automated optimization suggestions for new code
"""
from __future__ import annotations
import os
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
import time
import subprocess

from muta_ext.uast.adapters import get_adapter
from muta_ext.optimizer import MutaLambdaOptimizer
from muta_ext.project_optimizer import ProjectAnalyzer


@dataclass
class FunctionBaseline:
    """Baseline performance metrics for a function."""
    function_name: str
    file_path: str
    language: str
    baseline_fitness: Dict[str, float]
    baseline_code: str
    recorded_at: str
    commit_hash: str
    branch: str


@dataclass
class RegressionResult:
    """Result of regression analysis."""
    function_name: str
    file_path: str
    regression_detected: bool
    degradation_percentage: float
    severity: str  # "critical", "major", "minor", "none"
    suggestion: str
    baseline_fitness: Dict[str, float]
    current_fitness: Dict[str, float]


@dataclass
class PRAnalysisResult:
    """Complete analysis result for a pull request."""
    pr_number: int
    branch: str
    base_branch: str
    functions_analyzed: int
    regressions_found: int
    critical_regressions: List[RegressionResult]
    warnings: List[RegressionResult]
    optimization_suggestions: List[Dict]
    overall_status: str  # "pass", "warning", "fail"
    report_url: Optional[str] = None


class PerformanceBaseline:
    """Manage performance baselines for functions."""

    def __init__(self, storage_dir: str = ".mutalambda/baselines"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, FunctionBaseline] = {}

    def _get_baseline_file(self, file_path: str, function_name: str) -> Path:
        """Get path to baseline file for a function."""
        safe_name = hashlib.md5(function_name.encode()).hexdigest()[:12]
        safe_path = hashlib.md5(file_path.encode()).hexdigest()[:12]
        return self.storage_dir / f"{safe_path}_{safe_name}.json"

    def register_baseline(
        self,
        file_path: str,
        function_name: str,
        language: str,
        fitness: Dict[str, float],
        code: str,
        commit_hash: str,
        branch: str = "main"
    ):
        """Register baseline metrics for a function."""
        baseline = FunctionBaseline(
            function_name=function_name,
            file_path=file_path,
            language=language,
            baseline_fitness=fitness,
            baseline_code=code,
            recorded_at=datetime.now().isoformat(),
            commit_hash=commit_hash,
            branch=branch
        )

        # Save to file
        baseline_file = self._get_baseline_file(file_path, function_name)
        with open(baseline_file, 'w') as f:
            json.dump(asdict(baseline), f, indent=2)

        # Update cache
        key = f"{file_path}:{function_name}"
        self._cache[key] = baseline

    def get_baseline(self, file_path: str, function_name: str) -> Optional[FunctionBaseline]:
        """Get baseline for a function."""
        key = f"{file_path}:{function_name}"
        if key in self._cache:
            return self._cache[key]

        # Load from file
        baseline_file = self._get_baseline_file(file_path, function_name)
        if baseline_file.exists():
            with open(baseline_file) as f:
                data = json.load(f)
            baseline = FunctionBaseline(**data)
            self._cache[key] = baseline
            return baseline

        return None

    def list_baselines(self, file_pattern: Optional[str] = None) -> List[FunctionBaseline]:
        """List all baselines, optionally filtered by file pattern."""
        baselines = list(self._cache.values())

        if file_pattern:
            baselines = [b for b in baselines if file_pattern in b.file_path]

        return baselines


class RegressionDetector:
    """Detect performance regressions using baselines."""

    def __init__(
        self,
        threshold: float = 0.1,
        critical_threshold: float = 0.5
    ):
        self.threshold = threshold  # 10% degradation = warning
        self.critical_threshold = critical_threshold  # 50% degradation = critical

    def detect_regression(
        self,
        baseline: FunctionBaseline,
        current_fitness: Dict[str, float]
    ) -> RegressionResult:
        """Detect if current fitness represents a regression."""
        max_degradation = 0.0
        degraded_metrics = []

        for metric, value in baseline.baseline_fitness.items():
            if metric in current_fitness and value > 0:
                current_value = current_fitness.get(metric, 0)
                # For latency/memory, lower is better
                # Positive degradation means current is worse than baseline
                degradation = (current_value - value) / value
                if degradation < 0:
                    degradation = 0
                if degradation > max_degradation:
                    max_degradation = degradation
                if degradation > 0:
                    degraded_metrics.append((metric, degradation * 100))

        # Determine severity
        if max_degradation >= self.critical_threshold:
            severity = "critical"
        elif max_degradation >= self.threshold:
            severity = "major"
        else:
            severity = "minor"

        # Generate suggestion
        suggestion = self._generate_suggestion(severity, degraded_metrics)

        return RegressionResult(
            function_name=baseline.function_name,
            file_path=baseline.file_path,
            regression_detected=max_degradation > 0,
            degradation_percentage=max_degradation * 100,
            severity=severity,
            suggestion=suggestion,
            baseline_fitness=baseline.baseline_fitness,
            current_fitness=current_fitness
        )

    def _generate_suggestion(self, severity: str, degraded_metrics: List[Tuple[str, float]]) -> str:
        """Generate optimization suggestion based on regression."""
        if severity == "critical":
            return "CRITICAL: Significant performance regression detected. Review algorithm complexity and consider reverting or optimizing."
        elif severity == "major":
            return "MAJOR: Performance degraded significantly. Consider using faster algorithms or reducing memory allocations."
        elif severity == "minor":
            return "MINOR: Slight performance degradation. Review hot paths and consider micro-optimizations."
        return "No critical issues detected."


class PRAnalyzer:
    """Analyze pull requests for performance regressions."""

    def __init__(
        self,
        baseline_manager: PerformanceBaseline,
        regression_detector: RegressionDetector,
        optimizer: Optional[MutaLambdaOptimizer] = None
    ):
        self.baselines = baseline_manager
        self.detector = regression_detector
        self.optimizer = optimizer or MutaLambdaOptimizer()

    def analyze_pr(
        self,
        pr_number: int,
        branch: str,
        base_branch: str = "main",
        repo_path: str = "."
    ) -> PRAnalysisResult:
        """Analyze a pull request for performance regressions."""
        # Get changed files
        changed_files = self._get_changed_files(repo_path, branch, base_branch)

        # Find functions in changed files
        functions_to_analyze = self._extract_functions(changed_files)

        regressions = []
        suggestions = []

        for func_info in functions_to_analyze:
            file_path = func_info['file']
            func_name = func_info['name']

            # Get baseline
            baseline = self.baselines.get_baseline(file_path, func_name)

            if baseline is None:
                # No baseline exists, skip or register new
                continue

            # Analyze current code
            try:
                current_fitness = self._measure_current_performance(file_path, func_name)
                result = self.detector.detect_regression(baseline, current_fitness)
                regressions.append(result)
            except Exception as e:
                print(f"Error analyzing {func_name}: {e}")

            # Generate optimization suggestions
            opt_suggestions = self._generate_optimization_suggestions(func_info)
            suggestions.extend(opt_suggestions)

        # Determine overall status
        critical_count = sum(1 for r in regressions if r.severity == "critical")
        major_count = sum(1 for r in regressions if r.severity == "major")

        if critical_count > 0:
            overall_status = "fail"
        elif major_count > 0:
            overall_status = "warning"
        else:
            overall_status = "pass"

        return PRAnalysisResult(
            pr_number=pr_number,
            branch=branch,
            base_branch=base_branch,
            functions_analyzed=len(functions_to_analyze),
            regressions_found=len(regressions),
            critical_regressions=[r for r in regressions if r.severity == "critical"],
            warnings=[r for r in regressions if r.severity == "major"],
            optimization_suggestions=suggestions,
            overall_status=overall_status
        )

    def _get_changed_files(self, repo_path: str, branch: str, base_branch: str) -> List[str]:
        """Get list of changed files in PR."""
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "diff", "--name-only", f"origin/{base_branch}...{branch}"],
                capture_output=True, text=True, check=True
            )
            return result.stdout.strip().split('\n')
        except subprocess.CalledProcessError as e:
            print(f"Git error: {e}")
            return []

    def _extract_functions(self, file_list: List[str]) -> List[Dict]:
        """Extract function information from changed files."""
        functions = []
        for file_path in file_list:
            if not os.path.exists(file_path):
                continue

            ext = Path(file_path).suffix
            language = self._ext_to_language(ext)
            if not language:
                continue

            try:
                with open(file_path) as f:
                    source = f.read()

                adapter = get_adapter(language)
                if adapter.can_parse(source):
                    uast = adapter.parse_to_uast(source)
                    for node in uast.body:
                        if hasattr(node, 'name'):
                            func_name = node.name.name if hasattr(node.name, 'name') else str(node.name)
                            functions.append({
                                'file': file_path,
                                'name': func_name,
                                'language': language
                            })
            except Exception as e:
                print(f"Error parsing {file_path}: {e}")

        return functions

    def _measure_current_performance(
        self, file_path: str, function_name: str
    ) -> Dict[str, float]:
        """Measure current performance of a function."""
        # This would run actual benchmarks
        # For now, return dummy values
        return {
            "latency_p50": 1.0,
            "latency_p99": 2.0,
            "memory_peak_mb": 0.5,
            "throughput": 1000.0
        }

    def _generate_optimization_suggestions(
        self, func_info: Dict
    ) -> List[Dict]:
        """Generate optimization suggestions for a function."""
        suggestions = []
        # Use optimizer to generate suggestions
        # This would integrate with the mutation engine
        return suggestions

    def _ext_to_language(self, ext: str) -> Optional[str]:
        """Map file extension to language."""
        mapping = {
            '.go': 'go',
            '.py': 'python',
            '.rs': 'rust',
            '.cpp': 'cpp',
            '.c': 'cpp',
        }
        return mapping.get(ext)


def create_ci_pipeline(
    repo_path: str = ".",
    pr_number: Optional[int] = None
) -> PRAnalysisResult:
    """Create a CI pipeline integration point."""
    baselines = PerformanceBaseline(f"{repo_path}/.mutalambda/baselines")
    detector = RegressionDetector()
    analyzer = PRAnalyzer(baselines, detector)

    # Get branch info from environment or arguments
    branch = os.environ.get("CI_COMMIT_BRANCH", "main")
    base_branch = os.environ.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "main")

    return analyzer.analyze_pr(
        pr_number=pr_number or 0,
        branch=branch,
        base_branch=base_branch,
        repo_path=repo_path
    )


def register_baseline_from_ci(
    file_path: str,
    function_name: str,
    language: str,
    fitness: Dict[str, float],
    code: str,
    commit_hash: str,
    branch: str = "main"
):
    """Register baseline during CI build."""
    baselines = PerformanceBaseline()
    baselines.register_baseline(
        file_path=file_path,
        function_name=function_name,
        language=language,
        fitness=fitness,
        code=code,
        commit_hash=commit_hash,
        branch=branch
    )
    print(f"Baseline registered for {function_name} in {file_path}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "register":
        # Register baseline mode
        if len(sys.argv) > 4:
            register_baseline_from_ci(
                sys.argv[2],  # file_path
                sys.argv[3],  # function_name
                sys.argv[4],  # language
                {"latency_p50": 1.0},  # fitness (from benchmark)
                "# code would be passed via stdin",
                os.environ.get("GIT_COMMIT", "unknown")
            )
    else:
        # Analyze mode
        result = create_ci_pipeline()
        print(json.dumps(asdict(result), indent=2, default=str))
