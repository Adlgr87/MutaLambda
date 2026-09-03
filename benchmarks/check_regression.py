#!/usr/bin/env python3
"""Check benchmark results against baseline for regression (D7).

Reads results/ JSON files and compares speedup values against the previous
run stored in results/baseline.json (if present). Reports any target whose
speedup dropped by more than the threshold (default 10%).

Exit codes:
  0 = no regression, 1 = regression detected, 2 = error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_results(results_dir: Path) -> dict[str, dict]:
    """Load per-target result dicts from the results directory."""
    current: dict[str, dict] = {}
    for f in results_dir.glob("*.json"):
        if f.name == "baseline.json":
            continue
        try:
            data = json.loads(f.read_text())
            target = data.get("target", f.stem)
            current[target] = data
        except Exception as exc:
            print(f"  WARN: could not parse {f}: {exc}", file=sys.stderr)
    return current


def check_regression(results_dir: Path, threshold: float = 0.10) -> int:
    baseline_path = results_dir / "baseline.json"
    current = load_results(results_dir)

    if not current:
        print("ERROR: no benchmark results found.", file=sys.stderr)
        return 2

    if not baseline_path.exists():
        # First run — save as baseline
        baseline = {k: {"speedup": v["speedup"], "median_ms": v["baseline"]["median_s"] * 1000}
                    for k, v in current.items()}
        baseline_path.write_text(json.dumps(baseline, indent=2))
        print(f"No baseline found. Saved {len(baseline)} targets as baseline.")
        print("All targets:")
        for k, v in sorted(current.items()):
            speedup = v.get("speedup", float("nan"))
            print(f"  {k}: speedup={speedup:.4f} correct={v.get('correct', '?')}")
        return 0

    baseline = json.loads(baseline_path.read_text())
    regressions = []
    print("Regression check (threshold=%.0f%%):" % (threshold * 100))
    for target, result in sorted(current.items()):
        cur_speedup = result.get("speedup", 1.0)
        base_speedup = baseline.get(target, {}).get("speedup", cur_speedup)
        correct = result.get("correct", False)

        if base_speedup > 0 and cur_speedup < base_speedup * (1 - threshold):
            regressions.append((target, base_speedup, cur_speedup))
            print(f"  ⚠ {target}: speedup dropped {base_speedup:.2f}× → {cur_speedup:.2f}× (CORRECT={correct})")
        elif cur_speedup < 1.0 and correct:
            print(f"  ✗ {target}: slower {cur_speedup:.2f}× (CORRECT={correct})")
        else:
            print(f"  ✓ {target}: speedup={cur_speedup:.2f}× correct={correct}")

    if regressions:
        print(f"\nREGRESSION: {len(regressions)} target(s) dropped speed by >{threshold*100:.0f}%")
        return 1
    print("\nNo regression detected.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Check benchmark regression")
    parser.add_argument("--results", type=Path, default=Path("results"), help="Results directory")
    parser.add_argument("--threshold", type=float, default=0.10, help="Speedup drop threshold (default 0.10)")
    args = parser.parse_args()

    sys.exit(check_regression(args.results, args.threshold))


if __name__ == "__main__":
    main()