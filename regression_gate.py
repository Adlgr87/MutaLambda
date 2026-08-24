#!/usr/bin/env python3
"""Regression gate for optimised-vs-baseline comparison metrics.

Consumes a ``comparison.json`` document produced by the comparison phase
(Mann-Whitney U test on baseline vs. optimised benchmark samples) and decides
whether the optimised result passes the configured improvement / regression
thresholds.

Behaviour:
  * In the full optimization pipeline the gate is **strict**: exits non-zero
    when regression exceeds the threshold and improvement is below the floor.
  * When ``--pr-annotation`` is set (the PR-gate context) the gate never
    blocks — it only emits an annotation and exits 0 so PRs are not blocked
    by optimisation results that are still experimental.

Usage:
    python regression_gate.py comparison.json \
        --min-improvement 5 --max-regression 2 \
        [--pr-annotation] [--threshold-metric latency_p50]

Exit codes:
    0  gate passed (or non-blocking PR annotation)
    1  gate failed: regression exceeds threshold and improvement below floor
    2  argument / parse error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = ["GateResult", "GateConfig", "evaluate_gate", "run_gate"]

# Metrics where "lower is better" (latency, memory). Everything else higher-is-better.
LOWER_IS_BETTER_METRICS = {"latency_p50", "latency_p99", "memory_peak_mb"}


@dataclass
class GateConfig:
    min_improvement_pct: float = 5.0
    max_regression_pct: float = 2.0
    threshold_metric: str = "latency_p50"
    pr_annotation: bool = False


@dataclass
class GateResult:
    passed: bool
    message: str
    improvement_pct: float = 0.0
    regression_pct: float = 0.0
    metric: str = ""
    blocking: bool = True
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "message": self.message,
            "improvement_pct": self.improvement_pct,
            "regression_pct": self.regression_pct,
            "metric": self.metric,
            "blocking": self.blocking,
            "details": self.details,
        }


def _extract_samples(comparison: Dict[str, Any], key: str) -> Optional[List[float]]:
    """Pull a sample list from the comparison document.

    Supports both flat metric dicts and nested ``{baseline, optimized}`` shapes.
    """
    metric_section = comparison.get("metrics", comparison)
    entry = metric_section.get(key) if isinstance(metric_section, dict) else None
    if not entry:
        return None
    if isinstance(entry, list):
        return entry
    if isinstance(entry, dict):
        # Prefer explicit samples; fall back to p50 if samples absent.
        samples = entry.get("samples", entry.get("samples_baseline_opt"))
        if samples and isinstance(samples, dict):
            # {baseline: [...], optimized: [...]}
            return samples.get("optimized") or samples.get("baseline")
        if isinstance(samples, list):
            return samples
        return entry.get("p50") or entry.get("median")
    return None


def _percentile(values: List[float], pct: float = 50.0) -> float:
    if not values:
        return float("inf")
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    k = (len(data) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(data) - 1)
    if f == c:
        return data[f]
    d0 = data[f] * (c - k)
    d1 = data[c] * (k - f)
    return d0 + d1


def _mann_whitney_significance(comparison: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract the statistical test result for the chosen metric, if present."""
    stats = comparison.get("statistical_test", comparison.get("mann_whitney", {}))
    if isinstance(stats, dict):
        return stats
    return None


def evaluate_gate(comparison: Dict[str, Any], config: GateConfig) -> GateResult:
    """Evaluate the gate against a parsed comparison document."""
    metric = config.threshold_metric
    samples_opt = _extract_samples(comparison, metric)
    samples_base = _extract_samples(comparison, f"{metric}_baseline")

    # Try the structured comparison shape first.
    stats = (
        comparison.get("comparison", {}) if isinstance(comparison.get("comparison"), dict) else {}
    )
    baseline_val = stats.get("baseline", {}).get(metric)
    optimized_val = stats.get("optimized", {}).get(metric)

    if baseline_val is None and samples_base:
        baseline_val = _percentile(samples_base)
    if optimized_val is None and samples_opt:
        optimized_val = _percentile(samples_opt)

    # Fall back to direct metric lookup.
    if baseline_val is None:
        flat = comparison.get("metrics", {})
        baseline_val = (
            flat.get("baseline", {}).get(metric) if isinstance(flat.get("baseline"), dict) else None
        )
    if optimized_val is None:
        optimized_val = (
            comparison.get("metrics", {}).get("optimized", {}).get(metric)
            if isinstance(comparison.get("metrics", {}).get("optimized"), dict)
            else None
        )

    if baseline_val is None and optimized_val is None:
        # No metric data at all — in PR annotation mode we pass (non-blocking).
        return GateResult(
            passed=config.pr_annotation,
            message=f"metric '{metric}' not found in comparison; non-blocking in PR mode",
            metric=metric,
            blocking=not config.pr_annotation,
            details={"missing_metric": True},
        )

    if baseline_val is None or optimized_val is None or baseline_val == 0:
        return GateResult(
            passed=config.pr_annotation,
            message=f"insufficient data for metric '{metric}' (baseline={baseline_val}, optimized={optimized_val})",
            metric=metric,
            blocking=not config.pr_annotation,
            details={
                "baseline": baseline_val,
                "optimized": optimized_val,
                "insufficient_data": True,
            },
        )

    lower_is_better = metric in LOWER_IS_BETTER_METRICS
    if lower_is_better:
        # Improvement = how much faster/smaller the optimised version is.
        improvement_pct = (baseline_val - optimized_val) / baseline_val * 100.0
        regression_pct = (optimized_val - baseline_val) / baseline_val * 100.0
    else:
        improvement_pct = (optimized_val - baseline_val) / baseline_val * 100.0
        regression_pct = (baseline_val - optimized_val) / baseline_val * 100.0

    # Statistical significance (best effort).
    significance = _mann_whitney_significance(comparison)
    significant = bool(significance.get("significant", True)) if significance else True

    blocking = not config.pr_annotation
    if not significant:
        msg = (
            f"no statistically significant difference for '{metric}' "
            f"(improvement={improvement_pct:.2f}%). "
            f"Gate passes without meeting improvement floor."
        )
        return GateResult(
            passed=True,
            message=msg,
            improvement_pct=improvement_pct,
            regression_pct=regression_pct,
            metric=metric,
            blocking=blocking,
            details={"significant": significant, "improvement_pct": improvement_pct},
        )

    # Strict gate: regression must stay under the cap AND improvement meet the floor.
    if regression_pct > config.max_regression_pct:
        msg = (
            f"REGRESSION: {metric} regressed by {regression_pct:.2f}% "
            f"(max allowed {config.max_regression_pct:.2f}%). "
            f"Improvement {improvement_pct:.2f}% (min required {config.min_improvement_pct:.2f}%)."
        )
        return GateResult(
            passed=False,
            message=msg,
            improvement_pct=improvement_pct,
            regression_pct=regression_pct,
            metric=metric,
            blocking=blocking,
            details={
                "significant": significant,
                "regression_exceeds_threshold": True,
            },
        )

    if improvement_pct >= config.min_improvement_pct:
        msg = (
            f"PASS: {metric} improved by {improvement_pct:.2f}% "
            f"(min {config.min_improvement_pct:.2f}%), regression {regression_pct:.2f}% "
            f"(max {config.max_regression_pct:.2f}%)."
        )
        return GateResult(
            passed=True,
            message=msg,
            improvement_pct=improvement_pct,
            regression_pct=regression_pct,
            metric=metric,
            blocking=blocking,
            details={"significant": significant},
        )

    # Improvement below floor but no regression → still pass (no regression).
    msg = (
        f"PASS (improvement below floor): {metric} improved {improvement_pct:.2f}% "
        f"(floor {config.min_improvement_pct:.2f}%) with no regression "
        f"({regression_pct:.2f}%)."
    )
    return GateResult(
        passed=True,
        message=msg,
        improvement_pct=improvement_pct,
        regression_pct=regression_pct,
        metric=metric,
        blocking=blocking,
        details={"significant": significant, "below_floor": True},
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regression_gate",
        description="Evaluate a comparison.json against improvement/regression thresholds.",
    )
    parser.add_argument(
        "comparison", type=Path, help="Path to comparison.json produced by the comparison phase."
    )
    parser.add_argument(
        "--min-improvement",
        type=float,
        default=5.0,
        help="Minimum required improvement percentage (lower-is-better metrics).",
    )
    parser.add_argument(
        "--max-regression",
        type=float,
        default=2.0,
        help="Maximum allowed regression percentage before failing the gate.",
    )
    parser.add_argument(
        "--threshold-metric",
        default="latency_p50",
        help="Metric used for the gate decision (default: latency_p50).",
    )
    parser.add_argument(
        "--pr-annotation",
        action="store_true",
        help="Non-blocking mode: emit annotation, never exit non-zero (PR-gate context).",
    )
    return parser


def run_gate(comparison_path: Path, config: GateConfig) -> GateResult:
    if not comparison_path.exists():
        return GateResult(
            passed=False,
            message=f"comparison file not found: {comparison_path}",
            blocking=not config.pr_annotation,
        )
    try:
        with open(comparison_path, "r", encoding="utf-8") as f:
            comparison = json.load(f)
    except json.JSONDecodeError as exc:
        return GateResult(
            passed=False,
            message=f"invalid JSON in {comparison_path}: {exc}",
            blocking=not config.pr_annotation,
        )
    return evaluate_gate(comparison, config)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = GateConfig(
        min_improvement_pct=args.min_improvement,
        max_regression_pct=args.max_regression,
        threshold_metric=args.threshold_metric,
        pr_annotation=args.pr_annotation,
    )

    result = run_gate(args.comparison, config)

    # PR-gate annotation: print a structured annotation and never block.
    annotation_kind = "warning" if not result.passed else "notice"
    print(
        f"::{annotation_kind} file={args.comparison}::{result.message}"
        if args.pr_annotation
        else result.message
    )
    print(f"gate_result={json.dumps(result.to_dict())}")

    if args.pr_annotation:
        return 0
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
