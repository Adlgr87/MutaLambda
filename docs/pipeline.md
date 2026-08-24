# MutaLambda 2.0 Optimization Pipeline — Wire Contract

This document is the single source of truth for the artifact schemas exchanged
between the pipeline CLI modules and the GitHub Actions workflows. Each CLI is
importable as a Python module and side-effect-free at import time (see
*Module conventions*).

## Module map

| Phase | CLI module                       | Produces                        | Consumes                          |
|-------|----------------------------------|---------------------------------|-----------------------------------|
| 0     | (lint gate) `.github/workflows/mutalambda-pr-gate.yml` | PR status                | —                                 |
| 1     | `universal_parser.py`            | `uast.json`                     | source file                       |
| 1     | `invariant_detector.py`          | `invariants.lock`               | `uast.json` + source              |
| 2     | `benchmarking.py`                | `baseline.json`                 | source / callable                 |
| 3     | `evolve.py`                      | `optimized.py` + `fitness_report.json` + checkpoints | `uast.json`                       |
| 4     | `ast_math_verifier.py` + `property_testing.py` | `verification.json`     | baseline + optimized source       |
| 5     | `comparison.py` + `scipy`        | `comparison.json`               | baseline + optimized benchmarks   |
| 5     | `regression_gate.py`             | exit code 0/1                   | `comparison.json`                 |
| 6     | `interpretability.py`            | `optimized_report.md` + `sarif.json` | optimized code + metrics      |
| 7     | `certify.py`                     | `certificate.json`              | `baseline.json`, optimized, `invariants.lock` |

## Artifact contracts

### `uast.json` — CoreUAST document (produced by `universal_parser.py`)

```json
{
  "version": "1.0.0",            // reserved for future schema versions
  "file": "examples/target.py",
  "language": "python",
  "metadata": { "source_hash": "..." },
  "source_text": "...",          // embedded original source (optional)
  "node_count": 5,
  "nodes": [
    {
      "type": "Function",
      "name": "solution",
      "depth": 0,
      "line": 4,
      "end_line": 11,
      "children": [
        { "type": "Identifier", "name": "solution", "depth": 1, "line": 4, "end_line": 4 },
        { "type": "Assign", "name": null, "depth": 1, "line": 7, "end_line": 7, "children": [...] }
      ]
    }
  ]
}
```

**Field notes**
- `node.type` mirrors the CoreUAST `__type__` tag (e.g. `Function`, `Assign`,
  `BinaryOp`, `Call`, `Identifier`, `LiteralNode`, `If`, `For`, `While`, `Return`).
- `node.line` / `node.end_line` come from the adapter's `location` mapping where
  available; `null` when the adapter does not attach line info.
- The full CoreUAST tree is serialised via `CoreUAST.to_dict()` inside each node
  descriptor's `children`, so round-tripping through `CoreUAST.from_dict()` is
  possible.

### `invariants.lock` — invariant lockfile (produced by `invariant_detector.py`)

Versioned, content-addressed. The `invariants_hash` field is printed to stdout
and consumed by `certify.py`.

```json
{
  "version": "1.0.0",
  "source_hash": "<sha256 of source>",
  "file": "examples/target.py",
  "language": "python",
  "physical_constants": [
    {
      "symbol": "c",
      "value": 299792458.0,
      "unit": "m/s",
      "uncertainty": 0.0,
      "description": "speed of light",
      "matches": ["299792458.0"]
    }
  ],
  "mathematical_identities": [
    { "name": "add_identity", "description": "x + 0 = x", "matched_keywords": ["+", "0"], "confidence": 0.67 }
  ],
  "numerical_tolerances": [
    { "kind": "float32", "lower_bound": 0.0, "upper_bound": 1.1920928955078125e-07, "description": "..." }
  ],
  "crypto_patterns": [
    { "kind": "sha256", "description": "...", "matched_keywords": ["hashlib.sha256"] }
  ]
}
// invariants_hash = sha256(canonical(sorted(json above)))
```

### `comparison.json` — benchmark comparison (produced by the comparison phase)

```json
{
  "function": "solution",
  "metrics": {
    "baseline":   { "p50": 100.0, "samples": [...10 values...] },
    "optimized":  { "p50": 90.0,  "samples": [...10 values...] }
  },
  "comparison": {
    "baseline":   { "latency_p50": 100.0 },
    "optimized":  { "latency_p50": 90.0 }
  },
  "statistical_test": {
    "method": "mann-whitney-u",
    "statistic": 32.0,
    "pvalue": 0.013,
    "significant": true
  }
}
```

**`regression_gate.py` consumption rules**
- Reads `comparison.comparison.{baseline,optimized}.<metric>` for the threshold
  metric (default `latency_p50`).
- Falls back to `metrics.baseline.p50` if the structured `comparison` block is
  absent.
- `statistical_test.significant` (default `true`) gates whether the improvement
  floor is enforced: when not significant, the gate passes regardless of the
  improvement floor.
- `lower_is_better` metrics: `latency_p50`, `latency_p99`, `memory_peak_mb`.
  All others are higher-is-better.
- Exit 0 if `regression_pct <= max_regression` (or `--pr-annotation`);
  exit 1 only when regression exceeds the threshold **and** the gate is strict.

### `fitness_report.json` — per-generation fitness (produced by `evolve.py`)

```json
{
  "optimized": "def solution(n):\n    ...\n",
  "best_score": 0.9988,
  "generations": 5,
  "profile": "scientific",
  "seed": 42,
  "fitness_report": [
    { "generation": 0, "best_score": 0.98, "best_code": "...", "diversity": 0.875 }
  ],
  "engine_stats": { "best_score": 0.9988, "tier_counts": {...}, "diversity": 0.5 }
}
```

### `certificate.json` — reproducibility certificate (produced by `certify.py`)

```json
{
  "version": "1.0.0",
  "baseline_hash": "<sha256 or extracted hash>",
  "optimized_hash": "<sha256 or extracted hash>",
  "invariants_hash": "<sha256 of invariants.lock payload>",
  "seed": 42,
  "config_hash": "<sha256 of config.yaml>",
  "signature_algorithm": "HMAC-SHA256",
  "signature": "<hex hmac>",   // empty when --sign is omitted
  "signed": true,
  "details": {}
}
```

- `baseline_hash` / `optimized_hash` are extracted from an explicit `hash` /
  `optimized_hash` field if present, otherwise fall back to the SHA-256 of the
  raw file contents.
- `invariants_hash` is taken from an `invariants_hash` / `hash` field if present,
  otherwise recomputed as SHA-256 over the canonicalised lockfile payload.
- `verify_signature(secret)` checks the HMAC against the recomputed MAC.

## CLI entry points

All scripts live in the repository root and accept `--help`. They are
side-effect-free at import time (heavy imports are deferred to function bodies).

| Script                  | Key flags                                                                 |
|-------------------------|---------------------------------------------------------------------------|
| `universal_parser.py`   | `<file> --lang {python,rust,cpp} -o uast.json`                            |
| `invariant_detector.py` | `<uast.json> -o invariants.lock [--source file]`                          |
| `evolve.py`             | `--uast <file> --profile {enterprise,scientific,gpu} --generations N --population M [--hfc-tiers --checkpoint-every K --islands I --seed S --output-dir D]` |
| `regression_gate.py`    | `<comparison.json> --min-improvement PCT --max-regression PCT [--threshold-metric M --pr-annotation]` |
| `certify.py`            | `--baseline X --optimized Y --invariants Z --seed S [--config C --sign -o certificate.json]` |

## Module conventions

- **No hard imports at module load.** Each script defers imports of `muta_ext`,
  `evolution_engine`, `hfc_tiers`, `checkpoint_manager`, `fitness_vector`,
  `models`, `code_hash`, `ast_math_verifier`, `property_testing`,
  `interpretability`, `comparison`, `api_fingerprint`, `benchmarking`, and
  `ci_integration` into the function bodies that need them. This keeps `import
  <script>` cheap and side-effect free.
- **Exit codes:** `0` success, `1` gate failure, `2` argument/input error,
  `3` evolution produced no valid individuals (evolve.py).
- **Python 3.10+** with type hints; `dataclasses` for all structured payloads.

## Cache key contract (workflow)

The optimization pipeline computes its cache key as:

```
mutalambda-uast-${source_sha16}-${UAST_SCHEMA_VERSION}
```

where `source_sha16` is the first 16 hex chars of the SHA-256 of the target
source file's contents and `UAST_SCHEMA_VERSION` defaults to `1`. This is
recomputed in the `fingerprint` job and passed via job outputs, **not** via
`github.sha` (the latter never invalidates on semantic source changes).

## Island / HFC model

Evolution runs as **intra-job islands**. A single `evolve` job runs
`evolve.py --islands N` which dispatches `N` independent populations inside
the process. The HFC league engine performs real migration between tiers
(laboratory → factory → elite). There is **no** GitHub Actions matrix for
islands — the matrix would multiply CI minutes without adding migration
fidelity (see `PLANS/PIPELINE_2_0_LANDING_PLAN.md`, FASE 3).

## Verification

Run locally:

```bash
python -m pytest tests/test_pipeline_scripts.py -v
python universal_parser.py examples/target.py -o /tmp/test_uast.json
python invariant_detector.py /tmp/test_uast.json -o /tmp/test_inv.lock --source examples/target.py
python regression_gate.py --help
python certify.py --help
python evolve.py --help
```
