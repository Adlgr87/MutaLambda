# MutaLambda remediation progress

**Branch:** `maintenance/mutalambda-v4`  
**PR:** https://github.com/Adlgr87/MutaLambda/pull/3  
**Baseline commit:** `26ed6309f163baca2b47708a5fab915eb4b0f9b8`  
**Baseline tests:** 155 passed → **176 passed** (after tranche 2)

## Tranche 1 — blockers (done)

| Slice | Items | Status |
|-------|-------|--------|
| 01-baseline-and-ci | CI CLI/E2E jobs, pyproject, status report script | done |
| 02-config-and-package | `pyproject.toml` extras, target/privacy YAML | done |
| 03-core-generation-api | `step_generation` / `GenerationResult` / CLI wiring | done |
| 04-evaluation-service | `EvaluationService` cache + lazy pool | done |
| 05-security-runners | `CandidateRunner`, `SubprocessRunner`, `ContainerRunner` | done |
| 06-correctness-tests | Declarative comparators; empty tests not auto-correct | done |
| 07-checkpoints | CLI checkpoints JSON (no pickle) | done |
| 08-cli-target | `--source` / `--tests` / `--allow-untested` / `doctor` | done |

## Tranche 2 — correctness / concurrency (done)

| Slice | Items | Status |
|-------|-------|--------|
| 09-benchmarks | `benchmarking.py` multi-sample p50/p95/p99 + CI | done |
| 10-api-fingerprint | `api_fingerprint.py` + optional `api_gate` | done |
| 11-differential | `differential.py` + optional `differential_gate` | done |
| 12-migration-barriers | Phase A/B/C/D + pending migrant queues | done |
| 13-island-failure | `IslandFailure` structured errors | done |

## Still open (next tranches)

- Unified core resume + EventBus dashboard
- LLM retries / budget / structured responses
- Operator bandit + semantic archive dedupe
- MASSIVE adapter (`MassiveTargetAdapter`)
- Real container CI job (rootless) when runners available

## Verification commands

```bash
pytest tests/ -q
python cli.py --help
python cli.py config create --output /tmp/t.yaml --template basic
python cli.py config validate --path /tmp/t.yaml
python cli.py doctor
MUTALAMBDA_E2E_SERIAL=1 python tests/e2e_tests.py --fast --serial
python scripts/generate_status_report.py --skip-tests
```
