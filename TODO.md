# TODO — MutaLambda (A+B+C)

## Objetivo del entregable
Unificar el core para eliminar divergencias y hacer el repo presentable y testeable, manteniendo arquitectura multi-proceso del evaluator.

## Plan por pasos
- [x] Confirmación de fuente verdadera: usar `muta_lambda.py` como core principal (v2.1).
- [ ] Paso 1: Convertir `mutalambda_v2_patched.py` en wrapper/alias hacia `muta_lambda.py` (eliminar divergencias).
- [ ] Paso 2: Ajustar `e2e_tests.py`/imports si hace falta para que apunten al core unificado.
- [ ] Paso 3: Actualizar README para aclarar entrypoints y que `mutalambda_v2_patched.py` es alias.
- [ ] Paso 4: Ejecutar tests:
  - [ ] `python muta_lambda.py --test`
  - [ ] `python e2e_tests.py --fast`
- [ ] Paso 5: Revisar import/execution opcional de `app.py` y `document_intelligence.py` (asegurar que no rompen).
