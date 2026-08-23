"""``rosetta`` — Tier 2, experimental. Does the optimization *port*?

The claim being tested: because MutaLambda mutates a language-agnostic UAST
rather than Python text, an optimization discovered in Python should survive
emission to Rust and C++ and still be faster there. Nobody in the
OpenEvolve/CodeEvolve line does this, so if it holds it is a genuine
differentiator — and if it does not hold, that is worth knowing before it ends
up on a slide.

Status: **experimental**, and the honesty rules for it are strict.

* A task is only included when the same problem exists in Python *and* at
  least one of Rust/C++ in the cached Rosetta corpus, with a shared, checkable
  I/O contract (stdin → stdout).
* The Python-side speedup and the emitted-language speedup are reported as
  *separate* numbers. A ported optimization that does not reproduce the gain
  is reported as a negative result, not dropped.
* Emission failures count as failures, not skips: "the emitter could not
  produce compilable Rust for 40% of tasks" is exactly the finding a reader
  needs.

Right now the adapter builds the Python side and records the parallel
implementations for the cross-language phase; wiring the UAST emitters
(``muta_ext.uast.emitters``) into the run loop is the remaining work, tracked
in docs/BENCHMARKS.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from bench.datasets import DatasetUnavailable, require
from bench.spec import BenchTask, Workload
from bench.suites._common import limited

SUITE = "rosetta"
TIER = "tier2"
DATASET = "rosetta"

LANG_DIRS = {"python": "Python", "rust": "Rust", "cpp": "C++"}


def _tasks_with_parallel_impls(root: Path, wanted: int) -> List[Dict[str, str]]:
    """Find problems implemented in Python and at least one systems language."""
    lang_root = root / "Lang"
    if not lang_root.exists():
        raise DatasetUnavailable(
            f"Rosetta cache at {root} has no Lang/ directory; re-fetch with "
            "python scripts/fetch_bench_datasets.py rosetta"
        )
    python_tasks = {p.name: p for p in (lang_root / "Python").iterdir()} \
        if (lang_root / "Python").exists() else {}
    out: List[Dict[str, str]] = []
    for name, pydir in sorted(python_tasks.items()):
        entry: Dict[str, str] = {"task": name}
        py_files = sorted(pydir.rglob("*.py"))
        if not py_files:
            continue
        entry["python"] = py_files[0].read_text(encoding="utf-8", errors="ignore")
        for lang, dirname in (("rust", "Rust"), ("cpp", "C++")):
            ldir = lang_root / dirname / name
            if ldir.exists():
                files = sorted(list(ldir.rglob("*.rs")) + list(ldir.rglob("*.cpp")))
                if files:
                    entry[lang] = files[0].read_text(encoding="utf-8", errors="ignore")
        if "rust" in entry or "cpp" in entry:
            out.append(entry)
        if len(out) >= wanted:
            break
    return out


def load_tasks(limit: Optional[int] = None) -> List[BenchTask]:
    root = require(DATASET, SUITE)
    found = _tasks_with_parallel_impls(root, wanted=(limit or 25))
    if not found:
        raise DatasetUnavailable(
            "no Rosetta problems found with both a Python and a Rust/C++ implementation"
        )
    tasks: List[BenchTask] = []
    for entry in found:
        name = entry["task"].replace(" ", "_")
        tasks.append(BenchTask(
            task_id=f"rosetta/{name}",
            suite=SUITE, tier=TIER,
            language="python",
            source_code=entry["python"],
            entrypoint="main",
            workload=Workload(calls=[], warmups=1, samples=5, timeout_sec=60.0),
            metadata={
                "source": "Rosetta Code (GNU FDL 1.2)",
                "parallel_implementations": [k for k in ("rust", "cpp") if k in entry],
                "rust": entry.get("rust", ""),
                "cpp": entry.get("cpp", ""),
                "needs_io_contract": True,
                "status": "experimental: cross-language emission not yet wired",
            },
        ))
    usable = [t for t in tasks if t.workload.calls and t.visible_tests]
    if not usable:
        raise DatasetUnavailable(
            "rosetta suite is experimental: the cached problems have no machine-checkable\n"
            "  I/O contract yet, so no task can be measured honestly. See the module\n"
            "  docstring and docs/BENCHMARKS.md for what is missing."
        )
    return limited(usable, limit)
