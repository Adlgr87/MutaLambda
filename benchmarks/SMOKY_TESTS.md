# EffiBench Smoke Tests

## Prerequisites

```bash
# EffiBench dataset (1000 tasks, 891 convertible)
# Download from: https://huggingface.co/datasets/ktd-prime/EffiBench
# Place at: /tmp/effibench_train.parquet

# Install pyarrow
pip install pyarrow
```

## Smoke Test Commands

### Baseline-only (correctness + timing verification)
```bash
MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/effibench_harness.py --smoke --tasks 20 --baseline-only
# Expected: SMOKE PASS
```

### Identity mode (ratio = 1.0, correctness gating)
```bash
MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/effibench_harness.py --smoke --tasks 10
# Expected: SMOKE PASS, median_ratio_to_canonical = 1.0
```

### LLM mode (requires Ollama)
```bash
MUTALAMBDA_UNSAFE_LOCAL=1 python benchmarks/effibench_harness.py --smoke --tasks 8 --llm
# Expected: SMOKE PASS, llm_correctness_rate reported
```

## Exit Codes
- `0` = SMOKE PASS
- `1` = SMOKE FAIL

## Reproducibility
All runs report:
- 5-run medians (P50) with std
- `ratio_to_canonical` (baseline = canonical = 1.0)
- Correctness gating: speedup only counted for 100% test pass
- Full diff + msgpack artifact in report

## Baseline Reference (from /tmp/effibench_train.parquet)
- Longest Substring: p50=38.81ms, mem=30.4MB, 100/100 tests
- Median of Two Sorted Arrays: p50=39.27ms, mem=30.4MB
- Search Insert Position: p50=680.69ms, mem=36.4MB (outlier)

Tag: `v0.1-effibench-smoke` (commit `3a5f80c`)
