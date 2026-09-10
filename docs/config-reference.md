# Configuration Reference

> Este documento cubre la sección **`uast`** (motor de representación y mutación).
> El resto de secciones se declaran en `config_loader.py::_DEFAULTS`, que es la
> fuente de verdad de los valores por defecto aplicados por `apply_defaults()`.

Todas las claves pueden fijarse en el fichero YAML de configuración, o
sobreescribirse por CLI (`python mutalambda_cli.py run …`) y por variables de
entorno. Precedencia: **kwargs de la CLI > sección YAML > variable de entorno >
valor por defecto**.

## `uast` — motor UAST

```yaml
uast:
  engine: legacy            # legacy | v2
  shadow: false             # true = parsea con ambos motores y compara
  shadow_mode: exact        # exact | subset
  verify: true              # verificación tras cada nanopass
  strict: false             # true = InvalidIR en vez de rollback
  arena: true               # arena (slab de ids + parent pointers)
  extended_dialect: false   # dialecto extendido (comparaciones reales)
  use_uast: false           # bandera histórica del motor legacy
  supported_languages: [python, rust, cpp, go]
```

| Clave | Tipo | Valores | Defecto | Efecto |
|-------|------|---------|---------|--------|
| `engine` | string | `legacy`, `v2` | `legacy` | Motor activo. `v2` activa el motor in-situ; `legacy` es el camino original (rollback = volver a `legacy`). |
| `shadow` | bool | `true`, `false` | `false` | Parsea con ambos motores y compara el `canonical_digest`; registra `uast2.shadow.*`. Nunca falla: los errores del motor legacy se contabilizan como `legacy_errors`. |
| `shadow_mode` | string | `exact`, `subset` | `exact` | `exact` exige paridad estructural; `subset` compara solo los nodos que ambos motores modelan (para el dialecto extendido). |
| `verify` | bool | `true`, `false` | `true` | Ejecuta las guardas (estructura, esquema, parent links, validador legacy, sanidad numérica, seguridad) tras cada nanopass; con rollback atómico del run si algo falla. |
| `strict` | bool | `true`, `false` | `false` | En lugar de rollback, lanza `InvalidIR` al detectar un IR inválido. |
| `arena` | bool | `true`, `false` | `true` | Mantiene el slab de nodos (ids estables + `_parent`/`_slot`) que hace O(1) el `replace()` y habilita el Merkle incremental. |
| `extended_dialect` | bool | `true`, `false` | `false` | Baja constructos que la IR base no modela (comparaciones, `BoolOp`, `AugAssign`) a nodos v2 en vez de a `Opaque`. |
| `use_uast` | bool | `true`, `false` | `false` | Bandera histórica del motor legacy (compatibilidad hacia atrás). |
| `supported_languages` | list | `python`, `rust`, `cpp`, `go` | `[python]` | Lenguajes admitidos por la configuración. |

### Variables de entorno

| Variable | Valores | Efecto |
|----------|---------|--------|
| `MUTALAMBDA_UAST_ENGINE` | `legacy`, `v2` | Igual que `uast.engine` (la CLI y el YAML tienen prioridad). |
| `MUTALAMBDA_UAST_SHADOW` | `1`, `0`, `true`, `false` | Igual que `uast.shadow`. |

### Validación

`config_loader.validate_config()` rechaza valores fuera de rango con mensajes
explícitos:

- `uast.engine must be 'legacy' or 'v2'`
- `uast.shadow_mode must be 'exact' or 'subset'`
- `uast.shadow must be a boolean`
- `uast.supported_languages must be a list`

### Equivalencias en la CLI

| Clave | Bandera de `run` |
|-------|------------------|
| `uast.engine` | `--uast-engine {legacy,v2}` |
| `uast.shadow` | `--uast-shadow` |
| `uast.verify` | `--uast-verify` |
| `uast.strict` | `--uast-strict` |
| `uast.arena` | `--uast-arena` |
| `uast.extended_dialect` | `--uast-extended` |

### Diagnóstico

```bash
python mutalambda_cli.py uast2 check examples --json   # paridad + métricas uast2.*
```

Métricas expuestas: `uast2.shadow.parses`, `uast2.shadow.nodes`,
`uast2.shadow.mismatches`, `uast2.shadow.legacy_errors`, `uast2.pipeline.runs`,
`uast2.pipeline.failed_runs`.

Más contexto: [docs/uast2.md](uast2.md).
