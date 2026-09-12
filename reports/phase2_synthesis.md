# Phase 2 — Síntesis del Debate Estructurado (MutaLambda v2)

## Equipo de Agentes (4 paralelos)

| Rol | Agente | Provider/Model | Output |
|-----|--------|----------------|--------|
| Arquitecto | `gemma4:31b-cloud` | Ollama | 5 CRÍTICOS arquitectónicos + orchestrator audit |
| Devil's Advocate | `gemma4:31b-cloud` | Ollama | 25 findings (F1-F25) deep audit |
| Investigador | `gemma4:31b-cloud` | Ollama | Tech landscape 2025-2026 |
| Científico | `gemma4:31b-cloud` | Ollama | 7 engine maturity matrix + P0-P2 |

## Consolidación de Findings

### 🔴 CRÍTICOS de Seguridad (Devil's Advocate)
| # | Finding | Evidence | Fix |
|---|---------|----------|-----|
| F1 | Subprocess injection risk | `muta_ext/uast/emitters/*.py` dynamic cmd | Sanitizar comandos |
| F2 | Insecure sandbox boundary | `runners.py:554` "not real sandbox" | Container mode default |
| F3 | Pickle deserialization RCE | `ray_scheduler.py` pickle.loads | Validar buffers |
| F4 | Tainted command execution | `workflow/optimization_pipeline.py` dynamic cmd | Sanitizar |
| F5 | LSP server exposure | `lsp/server.py` daemon thread | Review file access |

### 🔄 Reproducibility (Devil's Advocate v2)
| # | Finding | Evidence | Fix |
|---|---------|----------|-----|
| F6 | Global RNG contamination | `rng_session.py:38` random.seed() global | Local Random instances |
| F7 | Non-deterministic mutations | `random.choice/shuffle` global calls | RNGSession stream wiring |
| F8 | FP non-associativity | NSGA-II fitness aggregations | Sorted key summation |
| F9 | Set/dict iteration | `uast2/passes.py` set logic | Sort scope_ids |
| F10 | GPU non-determinism | `gpu_optimizer.py:349` np.random.choice | Seeded Generator |

### 💀 Kill-Switches & DoS (Devil's Advocate v2)
| # | Finding | Evidence | Fix |
|---|---------|----------|-----|
| F11 | Infinite loop risk | `while True` in nsga2, event_bus | Add timeout/heartbeat |
| F12 | Unbounded memory/worker | ProcessPoolExecutor OOM | Memory limit per worker |
| F13 | Cache race conditions | Cross-process cache write | fcntl lock |
| F14 | ThreadPool saturation | No semaphore in island_evolution | Add semaphore |
| F15 | Blocking EventBus | Lock during dispatch | Async dispatch |

### 🛠 Correctness (Devil's Advocate)
| # | Finding | Evidence | Fix |
|---|---------|----------|-----|
| F18 | NaN propagation | `fitness_vector.py` no NaN checks | Guard in comparison |
| F19 | id() reuse issue | `uast2/serialize.py` id(node) keys | Stable hashes |
| F29 | Unsafe float cast | `runners.py:320` `float(got)` | try/except wrap |

### 5 CRÍTICOS del Arquitecto (v2 deep analysis)
| ID | Título | Evidence | Impact |
|----|--------|----------|--------|
| CRIT-1 | Orchestrator Degeneration | `llm_orchestrator.py:_dispatch()` — multilayer/massive → run_scalar_simulation | 🔴 High |
| CRIT-2 | Micro-Massive stub | `micro_massive` directs to /ui/ Streamlit (eliminado) | 🔴 High |
| CRIT-3 | UAST Fragmentation | `uast/` + `uast2/` coexistence, import orphans | 🟠 Medium |
| CRIT-4 | Rust underutilization | `rust_core/` has 3 helpers, no full engine | 🟡 Low |
| CRIT-5 | CLI doc inconsistency | `explain` vs `explain-run` | ✅ Already fixed |

## Científico Recommendations
- **P0**: ProcessPool picklability + RNGSession full integration
- **P1**: AST deep-copy optimization (surgical node replacement)
- **P2**: Dynamic tiering + semantic distance in IslandPool

## Investigador Strategic Recommendations
1. **GPU-fitness layer**: JAX-vectorized evaluation (N>10K populations)
2. **Reasoning-based mutation**: CoT trajectories via DeepSeek-V3
3. **Semantic guardrails**: ast-grep + Tree-sitter validation
4. **MicroVMs for safety**: Firecracker for candidate execution (F1-F3 security)

## Priorización Ponderada

**Votación**: Arquitecto 25% / Devil's Advocate 35% / Científico 15% / Investigador 15% / QA 10%

### Priority 1 (implementar esta sesión — ~2 horas)

| # | Fix | Category | Severity | Risk |
|---|-----|----------|----------|------|
| 1 | Replace global `random.seed()` with local `random.Random` instances | Repro | 🟠 High | Bajo |
| 2 | Wire RNGSession into ALL stochastic modules (evolution_engine, gpu_optimizer, etc.) | Repro | 🟠 High | Bajo |
| 3 | Add NaN guard in NSGA-II fitness comparison | Correctness | 🟡 Medium | Bajo |
| 4 | Add timeout/heartbeat to `while True` loops in event_bus | DoS | 🟡 Medium | Bajo |
| 5 | Add `logger.exception` for silent except in event_bus (F13 from v1 — already done, verify) | Debug | 🟠 High | Bajo |
| 6 | Replace `id(node)` with stable code hash in uast2/serialize.py | Correctness | 🟡 Medium | Medio |
| 7 | Wrap `float(got)` with try/except in runners.py | Correctness | 🟡 Medium | Bajo |
| 8 | CRIT-5: CLI doc fix (already done) | Docs | 🔵 Low | Bajo |

### Priority 2 (deferred — needs infra refactor)
- F1-F4: Sandbox hardening (container mode default, cmd sanitization)
- F8/F9: FP non-associativity, set sorting
- F11: Worker memory limits
- CRIT-1: Orchestrator degneration (needs MassiveSimEngine dispatch wiring)
- CRIT-2: Micro-massive stub (needs integration refactor)
- CRIT-3: UAST fragmentation cleanup
- CRIT-4: Rust full-engine migration

## Decisión del Coordinador

**Foco Priority 1 — 8 fixes rápidos** que cierran:
- 🔴 2 reproducibility kill-switches (F6, F7 — global RNG)
- 🟡 1 NaN poisoning vulnerability (F18)
- 🟡 1 infinite loop DoS (F11)
- 🟡 2 correctness issues (F19, F29)
- 🔵 1 doc inconsistency (CRIT-5, already done)

**Estimado: ~2-3 horas, alto impacto/costo.**