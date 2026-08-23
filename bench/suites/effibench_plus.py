"""``effibench-plus`` — Tier 2. Optimize the code, keep the physics.

The differentiator claim: a generic optimizer (Copilot, CodeGuru, a one-shot
LLM) will happily replace a numerically-stable accumulation with a faster one
that drifts, or drop a clamp that no unit test covers. MutaLambda's Scientific
Mode says it will not.

That claim only means something if it is measured on the *same* tasks with the
*same* budget, so this suite is EffiBench tasks plus a layer of conservation
properties, attached from a spec file so the invariants are auditable and
reviewable independently of the code.

Spec file
---------
``$MUTALAMBDA_BENCH_CACHE/effibench/_invariants.json`` (or ``--spec``):

    {
      "effibench/1234": {
        "invariants": ["finite", "non_negative", "determinism"],
        "params": {"bounded": {"low": 0.0, "high": 1.0}}
      }
    }

Tasks without an entry get the default probe set: ``finite`` + ``determinism``
— the two properties that hold for *every* deterministic numeric routine and
that a careless optimizer still manages to break (NaN from a fused reduction,
set iteration order leaking into the output).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from bench.datasets import dataset_path
from bench.spec import BenchTask
from bench.suites import effibench as _effibench
from bench.suites._common import limited

SUITE = "effibench-plus"
TIER = "tier2"
DATASET = "effibench"

DEFAULT_INVARIANTS = ["finite", "determinism"]


def _load_spec(spec_path: Optional[str]) -> Dict[str, Dict]:
    path = Path(spec_path) if spec_path else dataset_path(DATASET) / "_invariants.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_tasks(limit: Optional[int] = None, spec: Optional[str] = None) -> List[BenchTask]:
    base = _effibench.load_tasks(limit=limit)
    overrides = _load_spec(spec)
    out: List[BenchTask] = []
    for task in base:
        entry = overrides.get(task.task_id, {})
        task.suite = SUITE
        task.tier = TIER
        task.invariants = list(entry.get("invariants") or DEFAULT_INVARIANTS)
        params = entry.get("params")
        if params:
            task.metadata.setdefault("invariant_params", {}).update(params)
        task.metadata["invariant_source"] = "spec" if entry else "default"
        out.append(task)
    return limited(out, limit)
