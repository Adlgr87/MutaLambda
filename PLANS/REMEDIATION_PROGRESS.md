# MutaLambda remediation progress

**Branch:** `maintenance/mutalambda-v4`  
**PR:** https://github.com/Adlgr87/MutaLambda/pull/3  
**Baseline commit:** `26ed6309f163baca2b47708a5fab915eb4b0f9b8`  
**Tests:** 155 → 167 → 176 → **184 passed**

## Tranche 1 — blockers (done)

Runners, EvaluationService, step_generation, CLI target/tests, JSON checkpoints, packaging/CI.

## Tranche 2 — correctness / concurrency (done)

Benchmarks p50/p95/p99, API fingerprint, differential testing, migration barriers, IslandFailure.

## Tranche 3 — resume / events / LLM (done)

| Slice | Items | Status |
|-------|-------|--------|
| 14-event-bus | `EventBus` + `CommandQueue` (pause/resume/stop/hint) | done |
| 15-dashboard | `integrate_hitl` consumes events / control queue | done |
| 16-core-resume | Full JSON resume: gen, early-stop, global best, CLI core path | done |
| 17-session | `MutaLambdaSession` context manager | done |
| 18-llm-policy | retries/backoff, budget, circuit breaker, structured parse, replay log | done |

## Still open

- Operator bandit + semantic archive dedupe
- MASSIVE adapter (`MassiveTargetAdapter`)
- Container runner in CI (rootless)
- Micro-optimizations / Rust-GPU experiments

## Verification

```bash
pytest tests/ -q
MUTALAMBDA_E2E_SERIAL=1 python tests/e2e_tests.py --fast --serial
python cli.py doctor
```
