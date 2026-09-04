# MutaLambda Benchmarks

Performance comparisons of MutaLambda against similar code optimization tools.

## Results Overview

| Tool                        | Tasks | Valid | Median Ratio | Mean Speedup | Opt%   | Correctness% |
|----------------------------|-------|-------|--------------|--------------|--------|--------------|
| MutaLambda (Phase 6)       | 2     | 2     | 1.0000       | 0.0000x      | 0.0%   | 100%         |
| GitHub Copilot (LLM stub)  | 2     | 2     | 0.9845       | 1.0724x      | 50.0%  | 100%         |
| CodeWhisperer (LLM stub)   | 2     | 2     | 0.9070       | 1.1026x      | 100%   | 100%         |

> Lower ratio = faster. Baseline = canonical solution (ratio = 1.0)

## Result Files

- `results_effibench.json` — EffiBench harness (1000 tasks, baseline metrics)
- `results_effibench_plus.json` — Extended EffiBench coverage report
- `results_eoh.json` — EOH (Evolution of Heuristics) benchmark
- `results_market_comparison.json` — Full market comparison leaderboard
- `results_final_baseline.json` — Final baseline benchmark run
- `results_market_comparison_final.json` — Final market comparison run

## Reproducing Benchmarks

See main [README.md](../README.md) for full reproduction instructions.

```bash
cd /path/to/MutaLambda
MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/effibench_harness.py --smoke
python benchmarks/market_comparison_harness.py --tools mutalambda copilot codewhisperer
```

Last updated: 2026-09-03