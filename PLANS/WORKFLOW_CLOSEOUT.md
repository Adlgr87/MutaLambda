# Cierre del workflow de remediación MutaLambda

**Fecha:** 2026-07-14  
**Rama:** `maintenance/mutalambda-v4`  
**PR:** https://github.com/Adlgr87/MutaLambda/pull/3  
**HEAD verificado:** ver `git rev-parse HEAD` en el commit de cierre  

## Verificación final

| Check | Resultado |
|-------|-----------|
| `pytest tests/ -q` | **189 passed** |
| E2E `--fast --serial` | **OK** (good/bad/syntax_error completan) |
| `cli.py config validate --path config.yaml` | **OK** |
| `cli.py doctor -c config.yaml` | **OK** (container available, Pydantic valid) |
| `cli.py run --source examples/target.py --tests examples/target_tests.json -g 1` | **completa** (LLM Ollama puede 404 si el modelo no está; islas fallan de forma estructurada / circuit breaker) |
| `scripts/generate_status_report.py --skip-tests` | **OK** → `status_report.json` |

## Checklist §17

Bloqueadores 1–8 ✅ · Alta 9–15 ✅ · Media 16–20 ✅ · Final 21–22 ✅  
23–24 (micro-hotpaths / Rust-GPU) **fuera del camino base** — no bloquean cierre.

## Criterios §18

Cubiertos salvo matiz operativo:

- **Container:** disponible y documentado; default sigue `subprocess` para dev local.
- **MASSIVE:** proyecto externo; adapter produce patch + benchmark vía `promotion_package`.

## Cómo usar el camino base

```bash
# Validar entorno
python cli.py doctor -c config.yaml

# Corrida real con tests
python cli.py run \
  --source examples/target.py \
  --tests examples/target_tests.json \
  -g 20 -a none

# Aislamiento endurecido (Docker/Podman)
# En config.yaml: sandbox.runner: container

# Target externo (p.ej. pure functions de MASSIVE, otro clone)
python -c "
from massive_adapter import MassiveTargetAdapter
a = MassiveTargetAdapter(
    source_file='examples/massive/group_cohesion_target.py',
    entrypoint='calculate_group_cohesion',
    tests_file='examples/massive/group_cohesion_tests.json',
)
print(a.promotion_package(a.load_source())['promotable'])
"
```

## Nota LLM

Si Ollama responde 404 en `/api/generate`, instalar/pull el modelo de `config.yaml` (`llama3.2:3b`) o usar un `llm_fn` stub en API. El motor no se cae en silencio: `IslandFailure` + circuit breaker.
