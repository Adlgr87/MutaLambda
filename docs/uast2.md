# UAST v2 — Motor de mutación in-situ

UAST v2 es el motor de representación y mutación de código de nueva generación de
MutaLambda. Vive **en paralelo** al motor legacy (`muta_ext/uast/`), que queda
congelado, y se activa con una única bandera de configuración:

```yaml
uast:
  engine: v2      # "legacy" (por defecto) | "v2"
  shadow: true    # opcional: compara ambos motores sin cambiar el resultado
```

El valor por defecto sigue siendo `legacy`: actualizar MutaLambda **no cambia el
comportamiento** de ningún pipeline existente. El rollback consiste en volver a
poner `engine: legacy` — no hay migración de datos, ni cambios de formato de
checkpoint, ni de API pública del pipeline evolutivo.

## 1. Objetivos de diseño

| Objetivo | Cómo se consigue |
|----------|------------------|
| Mutación **in-situ** (sin reconstruir el árbol) | Nodos con `__slots__` + slab de arena; los nanopasses escriben en el slot y el árbol se re-parenta solo |
| Verificación **proporcional** a la mutación | Log de "touched nodes" + guardas *scoped*: cada nanopass re-verifica solo el subárbol que tocó (≈27× más barato) |
| Hashes **incrementales** | Merkle por nodo con caché de planos; una hoja editada re-hashea solo su camino (≈40× más rápido que el hash completo) |
| **Fidelidad semántica** | Verificadores (estructura, esquema, parent links, validador legacy, sanidad numérica, seguridad, math fidelity) tras cada nanopass, con rollback atómico por defecto |
| Serialización **plana y rápida** | msgpack + slab de referencias enteras: ~4.0× más rápido y ~0.44× el tamaño del JSON legacy (sin comprimir) |
| Diseño **dialect-friendly** | Los nodos son neutrales; los dialectos (p. ej. `extended_dialect`) bajan constructos específicos del lenguaje a la IR común |
| Sin romper nada | Convertidores bidireccionales `legacy_to_v2` / `v2_to_legacy`; interfaz `CoreUAST` estable (`.body`, `.language`, `.metadata`, `.canonical_hash()`, `.to_dict()`, `.from_dict()`) |

## 2. Arquitectura

```
muta_ext/uast2/
├── core.py        UASTNode (_fields + __slots__), 23 clases espejo del legacy,
│                  child_kinds/required_fields/walk, CoreUAST (body/language/
│                  metadata/engine), clone()/prepare()/canonical_hash()/merkle_hash()
├── arena.py       Slab de nodos + ids estables, assign_parents(), clone_tree(),
│                  replace_node(), allocate_all(), stats()
├── merkle.py      Digest por nodo, caché de planos, invalidate_up(), begin_touch()/
│                  end_touch(), hash_stats()
├── visitor.py     walk(), NodeVisitor, NodeTransformer (in-situ), dump()
├── convert.py     legacy_to_v2() / v2_to_legacy() (preserva tag y location)
├── adapters.py    PythonAdapterV2 (stdlib ast + coordenadas), Rust/Cpp/Go sobre
│                  los adaptadores legacy, get_adapter_v2(), parse_to_uast()
├── emitters.py    EmitterWrapperV2, emit(), emit_from_uast()
├── passes.py      Pass (run/verify), MutationPass, Pipeline (strict, rollback,
│                  guards scoped), Diagnostic, InvalidIR
├── verify.py      Structural/ChildSchema/ParentLink/LegacyValidator/NumericSanity/
│                  SecurityGate/MathFidelity + verify_tree()/default_verifiers()
├── mutators.py    ConstantFolding, CommutativeSwap, RangeBound, NegateCondition,
│                  LegacyMutatorPass (+ default_mutators(), available_legacy_mutators())
├── serialize.py   Formato plano msgpack (`mutalambda.uast2` v1) + JSON, zlib opcional
├── shadow.py      shadow_parse(), run_shadow_suite(), ShadowResult, métricas
├── engine.py      EngineConfig, resolve_engine_config(), parse()/parse_to_v2(),
│                  to_v2()/to_legacy()/emit()/mutate()/verify_document()
└── metrics.py     Contadores internos (uast2.*)
```

### 2.1 Nodos y arena

Los 23 tipos de nodo replican **el mismo nombre y el mismo orden de campos** que el
motor legacy, con `__slots__` para evitar el `__dict__` por nodo:

```python
from muta_ext.uast2 import core as v2

doc = v2.CoreUAST(body=[v2.Function(name=v2.Identifier(name="f"))])
doc.prepare()                      # arena + parent pointers (idempotente)
identifier = doc.body[0].name
identifier.name = "g"              # mutación in-situ
identifier.invalidate_hash()       # invalida solo su camino (Merkle)
print(doc.merkle_hash())
```

`Arena` asigna ids estables por documento y `assign_parents()` (plan-cacheado)
enlaza `_parent`/`_slot` en una sola pasada. `node.replace(new)` es O(1): reescribe
el slot del padre y re-parenta.

### 2.2 Hashes incrementales

- `canonical_hash()` es **estructural**: ignora ids, parents y coordenadas. Es el
  hash con el que se comparan motores y con el que se indexa la caché de fitness.
- `merkle_hash()` es el hash barato: un nodo limpio reutiliza su digest; tras
  `invalidate_up()` solo se recalculan los nodos sucios (camino hasta la raíz).
- `clone()` hereda los digests de la estructura (son puros), así que
  *clonar + editar una hoja* cuesta O(profundidad), no O(tamaño del árbol).

### 2.3 Nanopasses y verificación

Un `Pass` es una reescritura atómica con su verificador:

```python
from muta_ext.uast2.passes import MutationPass, Pipeline
from muta_ext.uast2.verify import default_verifiers

class DoubleLiteral(MutationPass):
    name = "double_literal"
    preserves_math = False          # cambia la aritmética a propósito

    def run(self, root, arena=None):
        for node in root.walk():
            if type(node).__name__ == "LiteralNode" and isinstance(node.value, int):
                node.value *= 2
                node.invalidate_hash()
                self._record()       # registra 1 mutación

result = Pipeline(default_verifiers(document) + [DoubleLiteral()]).run(document)
assert result.ok
```

Reglas del contrato:

- `run()` muta in-situ; `verify()` **nunca** muta.
- El pipeline mantiene un *touch log* (topmost node de cada invalidación) y pasa
  ese scope a las guardas baratas: `StructuralVerify`, `ChildSchemaVerify`,
  `ParentLinkVerify` y `NumericSanityVerify` verifican solo lo tocado
  (`per_pass_guard = True`).
- Las guardas caras (`LegacyValidatorVerify`, `SecurityGate`, `MathFidelityVerify`)
  se ejecutan **una vez** por documento (`per_pass_guard = False`), para que el
  coste siga siendo proporcional.
- `rollback=True` (por defecto) toma **un** snapshot antes del primer nanopass
  mutante: si algo falla, el documento vuelve exactamente al estado inicial
  (rollback atómico del run). `rollback="pass"` revierte solo el pase que falló;
  `rollback=False` desactiva la red de seguridad (solo para benchmarks).
- `strict=True` lanza `InvalidIR` en vez de hacer rollback.
- Si un pase declara mutaciones pero el touch log está vacío (reconstruye el
  árbol entero), la guarda verifica **todo** el documento, nunca un scope vacío.
- `preserves_math=True` (por defecto) hace que `MathFidelityVerify` se aplique;
  los mutadores que cambian la aritmética a propósito (constant folding, range
  bound, negate condition, mutadores legacy) lo declaran en falso, de modo que la
  fidelidad semántica nunca veta una mutación intencionada.

### 2.4 Serialización

```python
from muta_ext.uast2.serialize import dumps, loads

blob = dumps(document, compress=True)     # zlib opcional
copy = loads(blob, arena=None)            # ids 0..n-1 si se pide arena
```

Formato `mutalambda.uast2` v1: cabecera de 4 bytes (LE) + meta JSON
(`format`/`codec`/`compressed`) + cuerpo msgpack (o JSON) con un slab plano:
`roots`, `fields` (tipo → nombres de campo) y `nodes` (`{t,f,p,l[,tag]}`).
`loads()` lanza `SerializationError` ante entradas corruptas o de otra versión.

### 2.5 Convertidores (la pieza de reutilización)

```python
from muta_ext.uast2.convert import legacy_to_v2, v2_to_legacy

v2_doc = legacy_to_v2(legacy_uast)      # tag y location se conservan
legacy = v2_to_legacy(v2_doc)           # canonical_hash idéntico al original
```

Esto es lo que permite reutilizar **sin tocar** adaptadores, emisores, mutadores
y validadores legacy: `v2_to_legacy()` da la vista que esperan, y
`legacy_to_v2(on_unknown="opaque")` absorbe constructos que la IR v2 aún no
modela (nodos `Opaque` con `original_text`, nunca se pierde código).

### 2.6 Sombras (shadow) y paridad

Con `uast.shadow: true` (o `--uast-shadow`) el engine parsea con **ambos** motores,
compara `canonical_digest` y registra métricas (`uast2.shadow.parses`,
`uast2.shadow.nodes`, `uast2.shadow.mismatches`, `uast2.shadow.legacy_errors`).

```bash
python mutalambda_cli.py uast2 check examples          # exit 0 = paridad, 2 = diff
python mutalambda_cli.py uast2 check examples --json   # informe + métricas
```

La comparación nunca falla: un error del motor legacy se reporta como `ERR` del
fichero, no como excepción.

## 3. Uso desde la CLI

```bash
# Parsear con v2 (árbol + canonical_hash)
python mutalambda_cli.py uast2 parse examples/target.py

# Mutar in-situ y emitir el código mutado
python mutalambda_cli.py uast2 mutate examples/target.py --seed 42 --output mutado.py

# Todo el pipeline con la bandera puesta
python mutalambda_cli.py run --target examples/target.py --uast-engine v2 --uast-verify

# Paridad legacy vs v2 sobre un directorio
python mutalambda_cli.py uast2 check examples --mode exact
```

| Bandera de `run` | Sección YAML | Efecto |
|------------------|--------------|--------|
| `--uast-engine {legacy,v2}` | `uast.engine` | Motor activo |
| `--uast-shadow` | `uast.shadow` | Parsea con ambos y compara |
| `--uast-verify` | `uast.verify` | Verificación tras cada nanopass |
| `--uast-strict` | `uast.strict` | `InvalidIR` en vez de rollback |
| `--uast-arena` | `uast.arena` | Slab de ids/parents activado |
| `--uast-extended` | `uast.extended_dialect` | Dialecto extendido |
| — | `uast.shadow_mode` | `exact` (paridad) o `subset` (dialecto extendido) |

Precedencia de resolución: **kwargs explícitos > sección de config > variables de
entorno (`MUTALAMBDA_UAST_ENGINE`, `MUTALAMBDA_UAST_SHADOW`) > valor por defecto**.

## 4. Uso desde Python

```python
from muta_ext.uast2.engine import parse, mutate, verify_document, emit

doc = parse(source, engine="v2", language="python")   # engine="legacy" por defecto
result = mutate(doc, seed=42, verify=True, original_source=source)
if result.ok:
    print(emit(doc))
else:
    for diag in result.errors:
        print(diag.severity, diag.pass_name, diag.message)
```

`parse()` devuelve siempre un `CoreUAST` compatible con el resto del sistema
(`.body`, `.language`, `.metadata`, `.canonical_hash()`, `.to_dict()`,
`.from_dict()`), por lo que `evolution_engine`, `island`, `checkpoint_manager`
y `sandbox` funcionan sin cambios. `checkpoint_manager` sólo añade un campo
opcional `engine: "v2"` cuando la bandera está activa; el formato msgpack existente
no cambia.

## 5. Benchmarks y puertas de calidad

`bench_uast2.py` compara legacy vs v2 sobre un workload de ~7 KB / 24 funciones /
1177 nodos y falla (exit 1) si alguna puerta no se cumple:

```bash
python bench_uast2.py --reps 3                 # informe + gates
python bench_uast2.py --reps 3 --json out.json # resultados crudos
python bench_uast2.py --phase6                 # además, bench_phase6 end-to-end
```

Resultado de referencia (`python bench_uast2.py --reps 3 --phase6`, 2026-09-10):

| Área | legacy | v2 | Métrica |
|------|--------|----|---------|
| Parse (solo estructura) | 3.30 ms | 3.13 ms | **0.95×** |
| Parse (+ parents + coordenadas) | 3.30 ms | 3.74 ms | 1.13× (extra: lo que legacy no guarda) |
| Roundtrip serialización (raw) | 26.5 ms | 6.6 ms | **4.03× más rápido** |
| Roundtrip serialización (zlib) | 27.8 ms | 7.7 ms | **3.60× más rápido** |
| Payload crudo | 95.6 KB | 42.3 KB | **0.44×** |
| Hash completo | 2.42 ms | 2.93 ms | 0.83× |
| Hash incremental (hoja editada) | — | 73 µs | **40.3× vs hash completo** |
| Clonar + re-hashear (un candidato) | 7.57 ms | 1.38 ms | **5.5×** |
| Clonar + editar + re-hashear | — | 1.41 ms | **5.4×** |
| Guardas scoped vs verificación completa | — | 5.70 ms → 213 µs | **26.7×** |
| RAM por documento | 157 KB | 212 KB | 1.35× (~180 vs 133 B/nodo) |
| `bench_phase6` end-to-end | ~1.19–1.33 s | 1.22 s (min) | sin regresión |
| Paridad shadow sobre `examples/` | — | — | **0 diffs / 0 errores** |

Notas honestas:

- v2 guarda *más* información que legacy (parent pointers + coordenadas de origen),
  por eso el parse con parents+coords es ~1.13× y la RAM ~1.35×. Con
  `with_locations=False` el parseo queda en ~0.95×, a la par o mejor.
- El hash completo de v2 es ligeramente más lento que `canonical_hash()` legacy
  (un volcado JSON sin caché); la ventaja está en el camino incremental, que es lo
  que usa el bucle evolutivo. En el coste por candidato el documento padre
  conserva sus digests Merkle (así lo mantiene el motor) y el legacy no tiene
  caché alguna: de ahí el 5.5×.
- El tamaño con zlib no es comparable (msgpack comprime peor que el JSON legacy,
  que ya sale muy comprimido); la puerta que se mide es el payload **crudo**.
- El arnés pausa el recolector de basura mientras mide (ambos motores asignan un
  árbol por llamada) para que las cifras no dependan del historial de asignación.

## 6. Cómo extender

1. **Añadir un nanopass**: hereda de `MutationPass`, implementa `run()`, llama a
   `self._record()` por mutación y `invalidate_hash()`/`set_child()` al escribir.
   Si cambia la aritmética, declara `preserves_math = False`.
2. **Añadir un verificador**: hereda de `Pass` con `mutating = False` y devuelve
   `Diagnostic`s. Usa `scope` (si lo ignoras, verifica el documento entero) y pon
   `per_pass_guard = False` si es caro.
3. **Añadir un dialecto**: amplía `PythonAdapterV2` (o un adaptador nuevo) y baja
   el constructo a la IR común; en modo `subset` los nodos extra se admiten como
   formas más ricas del mismo significado.
4. **Reutilizar un mutador legacy**: `LegacyMutatorPass.from_registry("LoopBoundMutator")`.

## 7. Estado y hoja de ruta

- **Fase 1 (núcleo)** ✅ — nodos, visitantes, convertidores, adaptadores, `CoreUAST`.
- **Fase 2 (rendimiento)** ✅ — arena + ids, parent/slot, Merkle incremental,
  serialización plana, propagación de coordenadas.
- **Fase 3 (nanopasses)** ✅ — `Pass`/`Pipeline`/`Diagnostic`, guardas scoped,
  rollback atómico, verificación de fidelidad semántica.
- **Graduación** (pendiente, opt-in): conectar el engine v2 a
  `evolution_engine`/`island` como motor único. Hoy se usa a través de
  `muta_ext.uast2.engine` y de la bandera `uast.engine`, sin tocar el pipeline
  evolutivo.
