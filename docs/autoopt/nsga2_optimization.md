# NSGA-II Optimization — Auto-Opt

## Baseline (git HEAD)

| N=10 | N=32 | N=50 | N=100 |
|------|------|------|-------|
| 59.0us avg | 528.5us avg | 239.0us avg | 674.0us avg |

## Optimization Applied

- Module-level constant `_FITNESS_DIMS` (tuple vs per-call list alloc in `_crowding_distance`)
- Used by `_crowding_distance()` for 6-objective iteration

## Results (bit-exact verified)

| N=10 | N=32 | N=50 | N=100 |
|------|------|------|-------|
| 58.5us avg | 528.5us avg | 234.2us avg | 666.2us avg |

Verification:
- Golden test: Pareto frontier + crowding distances identical
- Regression: +0.7% (within 2% threshold)
- Tests: 1114/1114 pass
