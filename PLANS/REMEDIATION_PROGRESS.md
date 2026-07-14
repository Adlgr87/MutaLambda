# MutaLambda remediation progress

**Branch:** `maintenance/mutalambda-v4`  
**PR:** https://github.com/Adlgr87/MutaLambda/pull/3  
**Baseline:** `26ed630` · **Tests:** 155 → **189 passed**

## Completed

| Tranche | Scope |
|---------|--------|
| 1 | Runners, EvaluationService, step_generation, CLI, packaging/CI |
| 2 | Benchmarks p50/p95/p99, API fingerprint, differential, migration barriers |
| 3 | EventBus, core resume, LLM retries/budget/structured/replay |
| 4 | MassiveTargetAdapter + operator bandit |

## MASSIVE adapter usage

```python
from massive_adapter import MassiveTargetAdapter

# Local stand-in (CI-friendly)
adapter = MassiveTargetAdapter(
    source_file="examples/massive/group_cohesion_target.py",
    entrypoint="calculate_group_cohesion",
    tests_file="examples/massive/group_cohesion_tests.json",
)
pkg = adapter.promotion_package(candidate_code)
assert pkg["promotable"]

# Real MASSIVE tree
adapter = MassiveTargetAdapter.from_massive_utility_logic(
    "/path/to/MASSIVE",
    tests_file="examples/massive/group_cohesion_tests.json",
    entrypoint="calculate_group_cohesion",
)
```

## Still open / later

- Wire bandit rewards from Island workflow end-to-end (hooks exist)
- Semantic archive dedupe threshold path
- Container runner in CI
- Full promotion pipeline with human review gates

## Verify

```bash
pytest tests/ -q
MUTALAMBDA_E2E_SERIAL=1 python tests/e2e_tests.py --fast --serial
```
