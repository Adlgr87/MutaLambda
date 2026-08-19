"""Run REAL MutaLambda engine on 5 targets (skip-llm + numba/mypyc alternatives)."""
import sys, os
sys.path.insert(0, "/home/adlg/MutaLambda")
os.environ["MUTALAMBDA_LOG_LEVEL"] = "ERROR"
from benchmarks.harness import _load_targets, bench_one_target, RESULTS_BASE, get_git_sha, _env_info
import json

targets = _load_targets()
# Pick 5 diverse targets across tiers
pick = ["t1_compute_sum", "t1_fibonacci", "t2_radix_sort", "t2_histogram", "t3_confusion_matrix"]
results = []
for name in pick:
    mod = next(m for n, m in [(t[0], t[1]) for t in targets] if n == name)
    print(f"\n=== REAL MutaLambda on {name} (tier {mod.TIER}) ===", flush=True)
    r = bench_one_target(mod, name, use_real_mutalambda=True, skip_llm=True)
    if r:
        results.append(r)
        print(f"  speedup={r.speedup} verified={r.correctness.get('verified')} "
              f"mutation={r.mutation_applied}", flush=True)

# write a combined report
out = {"git_sha": get_git_sha(), "results": [
    {"target": r.target, "tier": r.tier, "speedup": r.speedup,
     "verified": r.correctness.get("verified"),
     "baseline_median_ms": round(r.baseline.median_s*1000, 4),
     "optimized_median_ms": round(r.optimized.median_s*1000, 4),
     "mutation": r.mutation_applied,
     "mann_whitney_p": r.statistics.get("mann_whitney_p"),
     "cliffs_delta": r.statistics.get("cliffs_delta")}
    for r in results
]}
(REPORTS := RESULTS_BASE / "latest")
REPORTS.mkdir(parents=True, exist_ok=True)
(REPORTS / "real_mutalambda_5targets.json").write_text(json.dumps(out, indent=2))
print("\nWrote real_mutalambda_5targets.json")
