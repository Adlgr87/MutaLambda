# MutaLambda optimization workflow checklist

Source: `PLANS/OPTIMIZATION_WORKFLOW.md`  
Branch: `maintenance/mutalambda-opt-v1` · PR: https://github.com/Adlgr87/MutaLambda/pull/4  

Layout: flat modules (`code_hash.py`, …) — no `mutalambda/core/` rewrite.

## FASE 1 — Críticas ✅

| ID | Item | Estado |
|----|------|--------|
| 1.1 | `stable_code_hash` único | ✅ `code_hash.py` |
| 1.2 | `Checkpoint` → `CheckpointData` | ✅ + alias BC |
| 1.3 | bare `except:` | ✅ CLI config |

## FASE 2 — Alta

| ID | Item | Estado |
|----|------|--------|
| 2.1 | RNG centralizado | ✅ streams por isla/migración/agente vía `RNGSession` + `Island.rng` |
| 2.2 | `compare_values` | ✅ `comparison.py` |
| 2.3 | Logging factory | ✅ `logging_setup.py` |
| 2.4 | Métodos con `pass` | ✅ inventario: CLI groups `pass` son Click; Protocol `...` OK; `MicroVMRunner` → `NotImplementedError` |
| 2.5 | `sys.path` | ✅ fallback solo ImportError |
| 2.6 | YAML Pydantic | ✅ `MutaLambdaConfig` (v4) |
| 2.7 | `except Exception` | 🟡 high-traffic paths afinados (archive, ckpt RNG, git, pkg version) |

## FASE 3–4

⬜ legacy clean, mass rename, test consolidation — post-merge opcional

## Verificación

```text
pytest tests/ -q  → 189 passed
```
