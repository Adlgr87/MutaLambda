# Changelog

## 2026-09-10 — UAST v2 (motor de mutación in-situ)

**Añadido**

- Paquete nuevo `muta_ext/uast2/`: nodos con `__slots__` espejo del esquema legacy,
  arena de nodos con ids estables y parent pointers, hashing Merkle incremental,
  serialización plana msgpack, nanopasses con verificación y rollback atómico.
- Bandera `uast.engine: legacy | v2` (por defecto **legacy**) más `uast.shadow`,
  `uast.verify`, `uast.strict`, `uast.arena`, `uast.extended_dialect` y
  `uast.shadow_mode`, con soporte en YAML, pydantic, `EvolveConfig` y CLI.
- CLI: grupo `uast2` con `check` (paridad legacy vs v2), `parse` (árbol +
  `canonical_hash`) y `mutate` (nanopasses + código mutado).
- Guardas *scoped*: la verificación posterior a cada nanopass se limita al
  subárbol tocado (**27.7× más barato** que verificar el documento completo).
- `bench_uast2.py`: arnés de puertas legacy vs v2 (parse, serialización, hashing,
  coste por candidato, guardas, memoria, paridad shadow, `bench_phase6`).
- Documentación: `docs/uast2.md` (guía completa), sección UAST en
  `docs/config-reference.md` y guía de activación en `docs/migration_guide.md`.
- 247 tests nuevos en `tests/uast2/` (suite total: **902 passed, 19 skipped**).

**Corregido**

- `muta_ext/uast/emitters/{python,cpp,rust}_emitter.py`: `For.iter` → `For.iterable`
  (el campo real del nodo) y unión de expresiones sin sangrado espurio en el
  emisor Python (15 puntos de expresión).

**Compatibilidad**

- Sin cambios de formato: los checkpoints msgpack siguen siendo válidos (solo se
  añade un campo opcional `engine`). El pipeline evolutivo, los adaptadores, los
  mutadores y los validadores legacy no se han modificado.
- Rollback del motor nuevo: volver a poner `uast.engine: legacy`.

## 404: Not Found

(Entradas anteriores: el histórico previo a 2026-09-10 no está disponible en este
árbol; consulta las releases en GitHub.)
