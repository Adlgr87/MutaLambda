# MutaLambda remediation progress

**Branch:** `maintenance/mutalambda-v4`  
**Baseline commit:** `26ed6309f163baca2b47708a5fab915eb4b0f9b8`  
**Baseline tests:** 155 passed  

## Done in this tranche

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

## Still open (next tranches)

- Real percentile benchmarks (p50/p95/p99 samples)
- API fingerprint gate
- Differential testing + Hypothesis
- Migration generation barriers (structured phases)
- Unified core resume + EventBus dashboard
- Island failure propagation (`IslandFailure`)
- MASSIVE adapter (`MassiveTargetAdapter`)
- LLM retries / budget / structured responses
- Operator bandit + semantic archive dedupe

## Verification commands

```bash
pytest tests/ -q
python cli.py --help
python cli.py config create --output /tmp/t.yaml --template basic
python cli.py config validate --path /tmp/t.yaml
python cli.py doctor
MUTALAMBDA_E2E_SERIAL=1 python tests/e2e_tests.py --fast
python scripts/generate_status_report.py --skip-tests
```
