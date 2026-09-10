#!/usr/bin/env python3
"""Fase 0 before/after measurement for the cost-optimization layer.

Runs the same representative evolution workload twice —
  BEFORE: all Fase 0 levers disabled (pre-change behaviour),
  AFTER :  all Fase 0 levers enabled (new defaults),
— and prints a comparison table plus a JSON artefact
(``reports/fase0_before_after.json``) with wall time, evaluation count,
fitness-cache hit rate and cost-ledger totals.

Usage:
    python bench_cost_ledger.py [--generations 12] [--population 24]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from universal_parser import emit_uast_dict  # noqa: E402

SAMPLE_PYTHON = '''"""Benchmark target: quadratic loop to optimize."""


def solution(n: int) -> int:
    """Sum of 1..n (quadratic loop)."""
    total = 0
    i = 1
    while i <= n:
        total = total + i
        i = i + 1
    return total
'''


def _make_uast(path: Path) -> Path:
    from muta_ext.uast.adapters import get_adapter

    uast = get_adapter("python").parse_to_uast(SAMPLE_PYTHON)
    payload = emit_uast_dict(uast, source=SAMPLE_PYTHON)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _set_levers(cost_ledger: bool, fitness_cache: bool, deterministic: bool) -> None:
    from optimization_flags import reset_optimization_flags

    os.environ["MUTALAMBDA_OPT_COST_LEDGER__ENABLED"] = "1" if cost_ledger else "0"
    os.environ["MUTALAMBDA_OPT_FITNESS_CACHE__ENABLED"] = "1" if fitness_cache else "0"
    os.environ["MUTALAMBDA_OPT_DETERMINISTIC_PROMPT__ENABLED"] = "1" if deterministic else "0"
    reset_optimization_flags()


def _run(label: str, uast: Path, generations: int, population: int) -> dict:
    from evolve import EvolveConfig, run_evolution
    from cost_ledger import get_cost_ledger, reset_cost_ledger

    reset_cost_ledger()
    out = Path(tempfile.mkdtemp(prefix=f"muta_f0_{label}_"))
    cfg = EvolveConfig(
        uast_path=uast,
        profile="scientific",
        generations=generations,
        population=population,
        hfc_tiers=True,
        checkpoint_every=5,
        seed=42,
        output_dir=out,
    )
    start = time.perf_counter()
    result = run_evolution(cfg)
    wall = time.perf_counter() - start
    ledger = get_cost_ledger()
    return {
        "label": label,
        "wall_sec": round(wall, 3),
        "best_score": round(float(result.best_score), 6),
        "generations": result.generations,
        "fitness_cache": result.fitness_cache_stats,
        "cost_ledger": ledger.totals() if ledger.enabled else None,
        "output_dir": str(out),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generations", type=int, default=12)
    parser.add_argument("--population", type=int, default=24)
    args = parser.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="muta_f0_uast_"))
    uast = _make_uast(tmp / "uast.json")

    _set_levers(cost_ledger=False, fitness_cache=False, deterministic=False)
    before = _run("before", uast, args.generations, args.population)

    _set_levers(cost_ledger=True, fitness_cache=True, deterministic=True)
    after = _run("after", uast, args.generations, args.population)

    report = {"workload": {"generations": args.generations, "population": args.population}, "before": before, "after": after}
    hit_rate = (after["fitness_cache"] or {}).get("hit_rate")
    speedup = before["wall_sec"] / after["wall_sec"] if after["wall_sec"] else 0.0
    report["delta"] = {
        "wall_time_reduction_pct": round((1.0 - after["wall_sec"] / before["wall_sec"]) * 100.0, 2)
        if before["wall_sec"]
        else 0.0,
        "speedup_x": round(speedup, 3),
        "cache_hit_rate": hit_rate,
        "cache_hit_gate_passed": bool(hit_rate is not None and hit_rate >= 0.20),
        "best_score_delta": round(float(after["best_score"]) - float(before["best_score"]), 6),
    }

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "fase0_before_after.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Dump the AFTER ledger to JSON (acceptance: dump_json válido).
    from cost_ledger import get_cost_ledger

    ledger_path = get_cost_ledger().dump_json(out_dir / "fase0_cost_ledger.json")

    print("=" * 72)
    print("MutaLambda — FASE 0 before/after (cost-optimization layer)")
    print("=" * 72)
    for run in (before, after):
        cache = run["fitness_cache"] or {}
        print(
            f"\n[{run['label']}] wall={run['wall_sec']}s best_score={run['best_score']} "
            f"gens={run['generations']} cache_hits={cache.get('hits', 0)} "
            f"cache_misses={cache.get('misses', 0)} hit_rate={cache.get('hit_rate', 0):.1%}"
        )
    d = report["delta"]
    print(
        f"\ndelta: wall -{d['wall_time_reduction_pct']}% (x{d['speedup_x']}), "
        f"cache hit rate {d['cache_hit_rate']:.1%} (gate >=20%: {'PASS' if d['cache_hit_gate_passed'] else 'FAIL'}), "
        f"Δbest_score={d['best_score_delta']:+.4f}"
    )
    print(f"\nartefacts: {out_path} | {ledger_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
