# Phase 2 — Estructuración del Debate & Síntesis de Hallazgos

## Equipo de Agentes

| Rol | Agente | Provider/Model | Output |
|-----|--------|----------------|--------|
| Coordinador | (Sistema) | — | Votación ponderada, priorización |
| Arquitecto | Arquitecto | Ollama/gemma4:31b-cloud | 5 CRÍTICOS arquitectónicos |
| Devil's Advocate | Devil's Advocate | Ollama/gemma4:31b-cloud | 30 findings (F1–F30) |
| Investigador | Investigador | Ollama/gemma4:31b-cloud | Tech landscape 2025-2026 |
| Científico | Científico | Ollama/gemma4:31b-cloud | Matriz de madurez científica |

## Hallazgos Consolidados

### 5 CRÍTICOS del Arquitecto
| ID | Título | Evidence | Impact |
|----|--------|----------|--------|
| CRIT-1 | Fragile packaging (`py-modules` manual sync) | `pyproject.toml:67-116` | High |
| CRIT-2 | No unified production API/service layer | `app.py:1-12`, CLI-only | Medium |
| CRIT-3 | Obs. gaps (no Prometheus/OTel, no health endpoints) | `PRODUCTION_CHECKLIST.md:141` | Medium |
| CRIT-4 | Sandbox defaults to subprocess (security) | `PRODUCTION_CHECKLIST.md:130` | High |
| CRIT-5 | CLI doc inconsistency (`explain` vs `explain-run`) | `AGENTS.md:61` vs `mutalambda_cli.py:687` | Low/Medium |

### Top Kill-Switches (Devil's Advocate)
| Finding | Severity | Category |
|---------|----------|----------|
| F1: RCE via `exec()` | 🔴 Critical | Security |
| F5: `eval()` in evaluation wrappers | 🔴 Critical | Security |
| F7: RCE via `exec(open(path).read())` | 🔴 Critical | Security |
| F8: Unseeded `random.Random()` | 🟠 High | Reproducibility |
| F9: Global `random` functions | 🟠 High | Reproducibility |
| F13: Silent `except: pass` in EventBus | 🟠 High | Correctness |
| F19: `time.sleep` blocking in CommandQueue | 🟠 High | Performance |
| F22: Sync network I/O (`requests`) | 🟠 High | Performance |
| F23: O(N²) in project_optimizer | 🟡 Medium | Performance |

## Ponderación de Intervenciones

Voto ponderado: Arquitecto 30% / Devil's Advocate 30% / QA 15% / Científico 15% / Investigador 10%

### Prioridad 1 (CRÍTICOs — implementar ahora)
1. **F5** — Replace `eval()` in `runners.py:378` with `ast.literal_eval` (30 min, safety)
2. **F1/F7** — Harden `exec` in `runners.py:336` and `hotspot_profiler.py:76` (5 min each — add try/except + logging)
3. **F13** — Replace `except: pass` in `event_bus.py:77` with `logger.exception` (5 min, debuggability)
4. **F19** — Replace `time.sleep` with `threading.Event.wait()` in `event_bus.py:156` (10 min, perf)

### Prioridad 2 (High — implementar en esta sesión)
5. **F8/F9** — Wire `rng_session.py` RNGSession into evolution_engine.py + muta_ext (30 min, reproducibility — Científico P0)
6. **CRIT-5** — Fix CLI doc inconsistency `explain` → `explain-run` in AGENTS.md (2 min, docs)

### Prioridad 3 (Medium — backlog)
- F22: Migrate `requests` → `httpx` async (needs async refactor)
- F23: Index-based lookup in `project_optimizer.py:112`
- F24-26: Dockerfile healthcheck + tmpfs fix + HOME dir
- CRIT-1: Migrate to src/ layout (major refactor)
- CRIT-2/CRIT-3: FastAPI service layer + Prometheus metrics (Phase 2 roadmap)

### Prioridad 4 (Low — deferred)
- F3/F4/F6/F10-F12/F14-F16/F18/F20/F21/F27-F30: Various low/medium severity issues

## Gap de Cobertura de Tests

El Científico reporta que:
- NSGA-II: High coverage ✅ (50 tests)
- CheckpointManager: Medium coverage — format overhead noted
- HFC Tiers: Medium coverage — memoization risk (F8/F9 findings validan esto)

## Recomendaciones Estratégicas (Investigador)

1. **Semantic Guardrails**: Integrate `ast-grep` + Tree-sitter for mutation validation
2. **GPU-Fitness Layer**: JAX-vectorized evaluation for parallel candidate scoring
3. **Project-Aware Context**: 1M+ token windows via DeepSeek-V3/OpenRouter

---

## Decisión del Coordinador

**Implementar Priority 1 + Priority 2 (6 fixes) hoy**, dejando Priority 3+ en backlog. Esto cierra los 3 kill-switches críticos de seguridad (F1/F5/F7 — 2 de ellos son RCE), el colapso de reproducibilidad (F8/F9), y el problema de debuggabilidad (F13). El rendimiento de thread-bloqueo (F19) también es rápido.

Estos 6 fixes representan **~1.5 horas de trabajo** con impacto crítico de seguridad y reproducibilidad.