# UAST language templates — design sketches, not loadable config

These four files used to live in `muta_ext/uast/config/`, where they looked like
runtime configuration. They are not: **no code reads this directory**, and the
directory was not even listed in `pyproject.toml` `packages`, so it was never
installed with the wheel either. They sat in a limbo between "config" and
"example".

They were moved here rather than deleted, because their *content* is accurate:
every handler class they name exists, and every mutator class they list exists.
What does not exist is a loader.

## What is actually wired

Only `BaseLanguageHandler` subclasses accept a `config` dict, and they read
exactly three keys:

| Key | Read by | Default |
|---|---|---|
| `compile_timeout_sec` | `CppHandler`, `RustHandler` | `30` |
| `run_timeout_sec` | `CppHandler`, `RustHandler` | `10` |
| `sanitizers` | `CppHandler`, `RustHandler` | `False` |

Coverage per file:

| File | Keys | Keys a handler can consume |
|---|---|---|
| `cpp_template.yaml` | 17 | 3 |
| `rust_template.yaml` | 14 | 3 |
| `python_uast_template.yaml` | 9 | 0 |
| `go_config.yaml` | 8 | 0 |

## Why the rest does not load

The remaining keys (`generations`, `population_size`, `islands`,
`mutation_rate`, `cache_enabled`, …) are written in a **flat, pre-v5
vocabulary**. The current schema (`mutalambda_config.muta_config.MutaLambdaConfig`)
is sectioned, so the equivalents are:

| Template key | Current location |
|---|---|
| `generations` | `evolution.generations` |
| `population_size` | `population.size` |
| `islands` | `population.num_islands` |
| `mutation_rate` | `evolution.mutation_rate` |
| `cache_enabled` | `sandbox.cache_enabled` |
| `use_uast` | `uast.use_uast` |

None of the 48 keys across the four files validates against `MutaLambdaConfig`.

## Using them

To actually drive a handler, pass the supported subset directly:

```python
import yaml
from muta_ext.uast.handlers.cpp_handler import CppHandler

cfg = yaml.safe_load(open("examples/configs/uast/cpp_template.yaml"))
handler = CppHandler(config=cfg)   # reads the three keys above, ignores the rest
```

For evolution settings use a real preset instead — `presets/quick.yaml`,
`presets/production.yaml`, `presets/scientific.yaml`, `presets/numpy.yaml` — all
of which are validated by `tests/test_config_single_source.py`.

## If you want them to become real presets

Two pieces are missing, and both are deliberate scope, not oversight:

1. a loader that maps a language template onto `MutaLambdaConfig` (the flat →
   sectioned translation in the table above), and
2. a `package-data` entry plus `importlib.resources` access so the files ship
   with the wheel.

Until both exist, these stay examples.
