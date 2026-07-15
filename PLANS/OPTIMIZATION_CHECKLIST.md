# MutaLambda optimization workflow checklist

Source: `PLANS/OPTIMIZATION_WORKFLOW.md`  
Branch: `maintenance/mutalambda-opt-v1`  
Layout note: repo uses **flat modules** (not `mutalambda/core/…`); fixes land as
`code_hash.py`, `comparison.py`, `logging_setup.py`, `constants.py` to match CLAUDE.md surgical style.

## FASE 1 — Críticas

| ID | Item | Estado | Artefacto |
|----|------|--------|-----------|
| 1.1 | `stable_code_hash` único | ✅ | `code_hash.py` (+ reexport `models`/`runners`) |
| 1.2 | `Checkpoint` → `CheckpointData` | ✅ | `checkpoint_manager.py` (+ alias BC) |
| 1.3 | bare `except:` | ✅ | `cli/config_manager.py` (+ git except más específico en core) |

## FASE 2 — Alta (parcial en este slice)

| ID | Item | Estado | Artefacto |
|----|------|--------|-----------|
| 2.1 | RNG centralizado | 🟡 | ya existía `rng_session.py` (remediación v4); migración masiva `random.` diferida |
| 2.2 | `compare_values` consolidado | ✅ | `comparison.py` |
| 2.3 | Logging centralizado | ✅ | `logging_setup.py` (factory; no reescribe 75 módulos) |
| 2.4 | Métodos con `pass` | ⬜ | inventario + NotImplementedError en slice siguiente |
| 2.5 | `sys.path` hacks | ✅ | `cli.py` / `e2e_tests.py` con fallback solo si ImportError |
| 2.6 | Validación YAML Pydantic | ✅ | ya `muta_config.MutaLambdaConfig` (v4) |
| 2.7 | `except Exception` genéricos | 🟡 | git save path afinado; resto selectivo |

## FASE 3–4

Diferidas (legacy clean, naming mass rename, test consolidation, magic constants full scan).

## Verificación

```bash
pytest tests/ -q   # 189 passed (esta tranche)
rg -n "def stable_code_hash" --glob '*.py'   # solo code_hash.py
```
