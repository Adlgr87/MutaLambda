# TODO - Massive → MutaLambda (Segura) | Fase ítem (1) Compresión de Estados

## Plan de trabajo (opt-in, sin romper comportamiento actual)
1. Revisar cómo se decide cuándo resucitar ramas y si existe ya un punto de extensión para compresión.
2. Actualizar `muta_ext/lineage/compression.py` para:
   - soportar zlib + diffs AST (sin placeholders),
   - reconstruir código exacto al descomprimir (`decompress_node()`).
3. Integrar compresión de forma **opt-in**:
   - actualizar `muta_lambda.py` en `_resurrect_branch()` para que, **solo si el compresor está activado**, use `LineageCompressor.decompress_node(node.id)` (fallback si falla).
   - evitar cambios en runs normales/tests cuando está OFF.
4. Agregar tests nuevos:
   - roundtrip: comprimir/descomprimir preserva código exacto,
   - resurrección: `_resurrect_branch()` usa el código del nodo resucitado cuando compresión ON y fallback cuando no.
5. Ejecutar `pytest -q` y corregir cualquier regresión.

## Hecho
- (pendiente)
