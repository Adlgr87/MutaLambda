#!/usr/bin/env python3
"""Fase 2 acceptance measurement: O4 Amdahl filter + O6 tiered ladder (N1/N2/N3)
+ A4 coverage-guided minimal test subset.

Two configurations run over the SAME deterministic mutant batch:

  BEFORE — naive full evaluation: every mutant pays a full subprocess run of
           the complete test suite (no tiering, no subset).
  AFTER  — tiered ladder: N1 in-memory nanopass (<1 ms) rejects the broken
           majority; N2 runs the coverage-guided minimal test subset
           in-process (pure) or hardened subprocess (I/O); only the top
           ~20 % of N2 survivors pay the full-sandbox N3 cost.

Gates (Fase 2 acceptance):
  * <= 20 % of the mutants touch N3
  * zero false positives in the filter (no correct variant rejected)
  * N1 mean latency < 1 ms
  * evaluation time per mutant reduced >= 60 % vs naive

Also reported (honesty, not gated): wrong-answer detection rate at each
configuration, subset size, per-tier wall times.

Usage:  python bench_headroom_fase2.py
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MUTALAMBDA_UNSAFE_LOCAL", "1")  # hardened subprocess is the sandbox here

SEED = 42
N_MUTANTS = 120
SANDBOX_TOP_PCT = 20.0
# Estimated $ per full sandbox evaluation (12-test subprocess run, CPU tier).
USD_PER_FULL_EVAL = 0.0005


# ── Workload: deterministic target + full declarative suite ────────────────

TARGET = '''"""Signal helpers (deterministic reference)."""
import math


def clip(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def norm(data):
    total = 0
    for i in range(len(data)):
        total = total + data[i] * data[i]
    return math.sqrt(total)


def smooth(data, k=3):
    out = []
    for i in range(0, len(data), k):
        chunk = data[i:i + k]
        s = 0
        for j in range(len(chunk)):
            s = s + chunk[j]
        out.append(s / len(chunk))
    return out


def process(data, k=32):
    v = norm(data)
    m = smooth(data, k)
    return clip(v + m[0] if m else v, 0.0, 1e9)
'''

TESTS = [
    {"function": "clip", "args": [5, 0, 10], "expected": 5, "comparison": "equal"},
    {"function": "clip", "args": [-3, 0, 10], "expected": 0, "comparison": "equal"},
    {"function": "clip", "args": [42, 0, 10], "expected": 10, "comparison": "equal"},
    {"function": "norm", "args": [[3, 4]], "expected": 5.0, "comparison": "equal"},
    {"function": "norm", "args": [[1, 0, 0]], "expected": 1.0, "comparison": "equal"},
    {"function": "norm", "args": [[]], "expected": 0.0, "comparison": "equal"},
    {"function": "smooth", "args": [[1, 2, 3], 3], "expected": [2.0], "comparison": "equal"},
    {"function": "smooth", "args": [[2, 4], 2], "expected": [3.0], "comparison": "equal"},
    {"function": "smooth", "args": [[1, 1, 1, 1], 2], "expected": [1.0, 1.0], "comparison": "equal"},
    {"function": "process", "args": [[1, 2, 3], 3], "expected": None, "comparison": "equal"},
    {"function": "process", "args": [[], 4], "expected": None, "comparison": "equal"},
    {"function": "process", "args": [[0.5, 0.5, 0.5], 2], "expected": None, "comparison": "equal"},
]


def _compute_expected() -> None:
    """Fill the process expected values by executing the reference target."""
    ns: dict = {}
    exec(compile(TARGET, "<bench-target>", "exec"), ns)  # noqa: S102
    TESTS[9]["expected"] = ns["process"]([1, 2, 3], 3)
    TESTS[10]["expected"] = ns["process"]([], 4)
    TESTS[11]["expected"] = ns["process"]([0.5, 0.5, 0.5], 2)


# ── Deterministic mutant factory ────────────────────────────────────────────


def _mutant(index: int, rng: random.Random) -> tuple[str, str]:
    """Return (code, label).  Labels: correct|wrong|api_break|syntax|io."""
    kind = (
        "correct" if index < 80
        else "api_break" if index < 95
        else "syntax" if index < 105
        else "wrong" if index < 115
        else "io"
    )
    code = TARGET
    if kind == "api_break":
        code = code.replace("def process", "def procesX")
    elif kind == "syntax":
        code = code.replace("def clip", "def clip(", 1)
    elif kind == "wrong":
        # perturb one sqrt-summand → real behavioural change
        code = code.replace("total = total + data[i] * data[i]",
                            "total = total + data[i] * data[i] + 1")
    elif kind == "io":
        code = code.replace('"""Signal helpers (deterministic reference)."""\n',
                            '"""Signal helpers (deterministic reference)."""\nimport os\n')
    else:
        r = rng.random()
        if r < 0.30:
            code = code.replace("total = total + data[i] * data[i]",
                                "total += data[i] * data[i]")
        elif r < 0.55:
            code = code.replace("s = s + chunk[j]", "s += chunk[j]")
        elif r < 0.70:
            code = code.replace("    return clip(v + m[0] if m else v, 0.0, 1e9)",
                                "    result = v + m[0] if m else v\n    return clip(result, 0.0, 1e9)")
        elif r < 0.85:
            code = code + "\n# deterministic variant " + str(index) + "\n"
        else:
            code = code.replace("if x < lo:", "if not (lo <= x):")
    return code, kind


# ── Configurations ──────────────────────────────────────────────────────────


def run_before(codes: list[str]) -> dict:
    """Naive: full subprocess evaluation for every mutant, full suite."""
    from runners import SubprocessRunner

    runner = SubprocessRunner(timeout_sec=10.0, memory_mb=256)
    t0 = time.perf_counter()
    results = []
    per_mutant: list[float] = []
    for code in codes:
        t1 = time.perf_counter()
        ev = runner.run(code, TESTS)
        per_mutant.append((time.perf_counter() - t1) * 1e3)
        m = ev.metrics or {}
        results.append({
            "passed": bool(ev.passed),
            "score": float(m.get("correctness", 0.0)),
        })
    wall = time.perf_counter() - t0
    return {
        "wall_ms": wall * 1e3,
        "per_mutant_ms": sum(per_mutant) / len(per_mutant),
        "full_sandbox_evals": len(codes),
        "results": results,
        "usd_est": len(codes) * USD_PER_FULL_EVAL,
    }


def run_after(codes: list[str]) -> dict:
    """Tiered ladder: N1 → N2 (subset, in-process) → N3 (top 20 % sandbox)."""
    from tiered_evaluator import TieredEvaluator

    te = TieredEvaluator(
        TARGET, TESTS,
        sandbox_top_pct=SANDBOX_TOP_PCT,
        subset_coverage_guided=True,
        n2_timeout_sec=5.0,
    )
    t0 = time.perf_counter()
    results = te.evaluate_batch(codes)
    wall = time.perf_counter() - t0
    stats = te.stats()
    n3_count = sum(1 for r in results if r.tier == "n3")
    return {
        "wall_ms": wall * 1e3,
        "per_mutant_ms": wall * 1e3 / len(codes),
        "full_sandbox_evals": n3_count,
        "results": [
            {"passed": bool(r.passed), "score": float(r.score), "tier": r.tier,
             "n1_ms": r.n1_ms, "n2_ms": r.n2_ms, "n3_ms": r.n3_ms}
            for r in results
        ],
        "usd_est": n3_count * USD_PER_FULL_EVAL,
        "stats": stats,
    }


# ── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    _compute_expected()
    rng = random.Random(SEED)
    mutants = [_mutant(i, random.Random(SEED + i)) for i in range(N_MUTANTS)]
    codes = [c for c, _ in mutants]
    labels = [l for _, l in mutants]

    print("Fase 2 — tiered evaluation ladder: before/after")
    print(f"  mutants: {N_MUTANTS} | seed: {SEED} | sandbox top: {SANDBOX_TOP_PCT:.0f}%")
    counts: dict[str, int] = {}
    for l in labels:
        counts[l] = counts.get(l, 0) + 1
    print(f"  composition: {counts}")

    print("  running BEFORE (naive full subprocess eval) ...")
    before = run_before(codes)
    print("  running AFTER (N1 → N2 subset → N3 top-20%) ...")
    after = run_after(codes)

    # ── metrics ────────────────────────────────────────────────────────────
    correct_idx = [i for i, l in enumerate(labels) if l == "correct"]
    wrong_idx = [i for i, l in enumerate(labels) if l == "wrong"]

    fp_before = sum(1 for i in correct_idx if not before["results"][i]["passed"])
    fp_after = sum(1 for i in correct_idx if not after["results"][i]["passed"])
    n1_fp = sum(
        1 for i in correct_idx if after["results"][i]["tier"] == "n1_reject"
    )
    wrong_caught_before = sum(1 for i in wrong_idx if not before["results"][i]["passed"])
    wrong_caught_after = sum(1 for i in wrong_idx if not after["results"][i]["passed"])

    st = after["stats"]
    n3_count = st["n3_count"]
    n3_share = 100.0 * n3_count / N_MUTANTS
    time_reduction = 1.0 - (after["per_mutant_ms"] / before["per_mutant_ms"])
    n1_mean = st["n1_mean_ms"]

    gates = {
        "n3_share_le_20pct": n3_share <= 20.0 + 1e-9,
        "zero_false_positives": (fp_after == 0) and (n1_fp == 0),
        "n1_under_1ms": n1_mean < 1.0,
        "eval_time_per_mutant_minus_60pct": time_reduction >= 0.60,
    }

    report = {
        "phase": "fase2",
        "seed": SEED,
        "mutants": N_MUTANTS,
        "composition": counts,
        "before": {
            "wall_ms": round(before["wall_ms"], 2),
            "per_mutant_ms": round(before["per_mutant_ms"], 3),
            "full_sandbox_evals": before["full_sandbox_evals"],
            "usd_est": round(before["usd_est"], 6),
            "correct_rejected": fp_before,
        },
        "after": {
            "wall_ms": round(after["wall_ms"], 2),
            "per_mutant_ms": round(after["per_mutant_ms"], 3),
            "full_sandbox_evals": n3_count,
            "n3_share_pct": round(n3_share, 3),
            "usd_est": round(after["usd_est"], 6),
            "correct_rejected": fp_after,
            "n1_false_positives": n1_fp,
            "tier_breakdown": {
                t: sum(1 for r in after["results"] if r["tier"] == t)
                for t in ("n1_reject", "n2", "n3")
            },
            "subset_size": st["subset_size"],
            "subset_mode": st["subset_mode"],
            "n1_mean_ms": n1_mean,
            "n2_mean_ms": st["n2_mean_ms"],
            "n3_mean_ms": st["n3_mean_ms"],
        },
        "delta": {
            "per_mutant_ms": round(before["per_mutant_ms"] - after["per_mutant_ms"], 3),
            "per_mutant_reduction_pct": round(100.0 * time_reduction, 2),
            "sandbox_evals_saved": before["full_sandbox_evals"] - n3_count,
            "usd_saved_est": round(before["usd_est"] - after["usd_est"], 6),
        },
        "honesty": {
            "wrong_answer_detection_before_pct": round(100.0 * wrong_caught_before / max(1, len(wrong_idx)), 2),
            "wrong_answer_detection_after_pct": round(100.0 * wrong_caught_after / max(1, len(wrong_idx)), 2),
        },
        "gates": gates,
    }

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    (reports_dir / "fase2_before_after.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (reports_dir / "fase2_cost_ledger.json").write_text(
        json.dumps(
            {
                "ledger": [
                    {
                        "phase": "fase2",
                        "lever": "naive_full_eval",
                        "sandbox_evals": before["full_sandbox_evals"],
                        "usd_est": round(before["usd_est"], 6),
                        "wall_ms": round(before["wall_ms"], 2),
                    },
                    {
                        "phase": "fase2",
                        "lever": "tiered_ladder_n1_n2_n3",
                        "sandbox_evals": n3_count,
                        "usd_est": round(after["usd_est"], 6),
                        "wall_ms": round(after["wall_ms"], 2),
                        "n3_share_pct": round(n3_share, 3),
                    },
                ],
                "gpu_note": "CPU sandbox tier here; GPU $ accounting stays in cost_ledger.py",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # ── console report ─────────────────────────────────────────────────────
    print()
    print(f"  {'metric':34s} {'BEFORE':>14s} {'AFTER':>14s} {'Δ':>12s}")
    print(f"  {'wall time (ms)':34s} {before['wall_ms']:14.1f} {after['wall_ms']:14.1f} {100*(1-after['wall_ms']/before['wall_ms']):11.1f}%")
    print(f"  {'ms / mutant':34s} {before['per_mutant_ms']:14.2f} {after['per_mutant_ms']:14.2f} {100*(1-after['per_mutant_ms']/before['per_mutant_ms']):11.1f}%")
    print(f"  {'full sandbox evals':34s} {before['full_sandbox_evals']:14d} {n3_count:14d} {before['full_sandbox_evals']-n3_count:12d}")
    print(f"  {'correct candidates rejected':34s} {fp_before:14d} {fp_after:14d} {fp_before-fp_after:12d}")
    print(f"  {'wrong answers caught (honesty)':34s} "
          f"{100*wrong_caught_before/max(1,len(wrong_idx)):13.1f}% "
          f"{100*wrong_caught_after/max(1,len(wrong_idx)):13.1f}%")
    print()
    print(f"  tier breakdown: {report['after']['tier_breakdown']}")
    print(f"  N1 mean: {n1_mean:.3f} ms | N2 mean: {st['n2_mean_ms']:.2f} ms | "
          f"N3 mean: {st['n3_mean_ms']:.0f} ms | subset: {st['subset_size']}/{len(TESTS)} tests ({st['subset_mode']})")
    print()
    for gate, ok in gates.items():
        print(f"  gate {gate}: {'PASS' if ok else 'FAIL'}")

    print()
    print("artefacts: reports/fase2_before_after.json, reports/fase2_cost_ledger.json")
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
