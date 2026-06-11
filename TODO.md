# TODO — MutaLambda (A+B+C)

## Objetivo del entregable
Mejorar el core para: (A) LLM agnóstico/configurable, (B) scoring menos tosco, (C) tests end-to-end reales (pipeline completo), manteniendo la arquitectura multi-proceso actual (ProcessPool en evaluator) y sin tocar paralelismo de islas todavía.

## Plan por pasos
- [ ] Paso 1: Modificar `LLMBackend`/factory en `mutalambda_v2_patched.py` para soportar backends agnósticos adicionales (OpenAI-compatible HTTP, Ollama HTTP, microsoft.cpp, huggingface-cli) y parametrización vía env vars.
- [ ] Paso 2: Integrar el backend real en `MutaLambdaAgent`/prompting para que deje de usar `_demo_llm_fn` por defecto en ejecuciones normales.
- [ ] Paso 3: Implementar scoring compuesto en `SandboxEvaluator` o en el nivel de `Island`/`Agent` (sin romper contractos). Añadir AST complexity y code-quality penalty.
- [ ] Paso 4: Añadir `e2e_tests.py` (o test runner dentro del core) con pipeline real usando `SandboxEvaluator` y migración/archivo en modo determinista con un LLM stub.
- [ ] Paso 5: Ejecutar `python mutalambda_v2_patched.py --test` y el nuevo E2E para validar que no se rompe nada.
- [ ] Paso 6: Actualizar README (opcional) con variables de entorno para LLM agnóstico y cómo correr E2E.

