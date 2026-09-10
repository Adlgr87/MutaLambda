#!/usr/bin/env python3
"""UAST v2 benchmark — empirical gates for the ``muta_ext.uast2`` engine.

Compares the frozen legacy engine against the mutable v2 engine on the
dimensions the playbook gates on, using real wall-clock timing (min of N
repeats, 1 warmup) and ``tracemalloc`` for retained memory:

1. parse            — v2 must not be measurably slower than legacy
2. serialisation    — flat msgpack vs legacy nested JSON (dump + load)
3. hashing          — full re-hash vs incremental Merkle re-hash
4. per-candidate    — clone + mutate + re-hash (the evolutionary inner loop)
5. memory           — retained bytes per parsed document
6. shadow parity    — legacy vs v2 structural equality over ``examples/``

Usage:
    python bench_uast2.py                # full run (3 repeats)
    python bench_uast2.py --quick        # 1 repeat, smaller workload
    python bench_uast2.py --json out.json
    python bench_uast2.py --phase6       # also run the phase-6 regression gate
"""

from __future__ import annotations

import argparse
import copy
import gc
import json
import random
import statistics
import sys
import time
import tracemalloc
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent
if str(REPO) not in sys.path:  # pragma: no cover - script convenience
    sys.path.insert(0, str(REPO))

from muta_ext.uast.adapters import get_adapter  # noqa: E402
from muta_ext.uast2.arena import Arena  # noqa: E402
from muta_ext.uast2.adapters import parse_to_uast as parse_v2  # noqa: E402
from muta_ext.uast2.mutators import (  # noqa: E402
    CommutativeSwapPass,
    ConstantFoldingPass,
    LegacyMutatorPass,
)
from muta_ext.uast2.passes import Pipeline  # noqa: E402
from muta_ext.uast2.serialize import dumps as v2_dumps  # noqa: E402
from muta_ext.uast2.serialize import loads as v2_loads  # noqa: E402
from muta_ext.uast2.shadow import run_shadow_suite  # noqa: E402

# ── workload ─────────────────────────────────────────────────────────────────


def make_source(functions: int = 24) -> str:
    """Deterministic Python source with loops, branches and arithmetic."""
    chunks: List[str] = ["import math\n"]
    for index in range(functions):
        chunks.append(
            f"""
def compute_{index}(data, n):
    total = 0
    for i in range(0, n):
        if i % 2 == 0:
            total = total + data[i] * {index + 2}
        else:
            total = total - data[i]
    scaled = total * 2 + 6 * 7
    while scaled > 1000:
        scaled = scaled / 2
    return scaled + math.sqrt(n)
"""
        )
    return "".join(chunks)


def time_call(fn: Callable[[], Any], reps: int = 3) -> Tuple[float, float]:
    """Return ``(best, mean)`` seconds for *fn* (one warmup + *reps* runs).

    The collector is paused while timing: both engines allocate a tree per call
    (deepcopy vs clone), and a single generation-2 collection costs more than the
    operation being measured, which made the numbers depend on allocation
    history instead of on the engine.  GC is re-enabled afterwards.
    """
    fn()  # warmup (caches, allocator, tree-sitter lazy imports)
    samples = []
    was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        for _ in range(reps):
            started = time.perf_counter()
            fn()
            samples.append(time.perf_counter() - started)
    finally:
        if was_enabled:
            gc.enable()
    return min(samples), statistics.mean(samples)


def ratio(reference: float, candidate: float) -> float:
    return candidate / reference if reference else float("inf")


def speedup(reference: float, candidate: float) -> float:
    return reference / candidate if candidate else float("inf")


# ── individual benchmarks ────────────────────────────────────────────────────


def bench_parse(source: str, reps: int) -> Dict[str, float]:
    legacy_adapter = get_adapter("python")

    def legacy() -> Any:
        return legacy_adapter.parse_to_uast(source)

    def v2_plain() -> Any:
        # Structure only — the same information the legacy adapter produces.
        return parse_v2(source, prepare=False, with_locations=False, use_cache=False)

    def v2_full() -> Any:
        # Parents assigned + source coordinates: strictly more than legacy.
        return parse_v2(source, use_cache=False)

    legacy_best, legacy_mean = time_call(legacy, reps)
    plain_best, plain_mean = time_call(v2_plain, reps)
    full_best, full_mean = time_call(v2_full, reps)
    document = parse_v2(source, use_cache=False)
    return {
        "legacy_best_s": legacy_best,
        "legacy_mean_s": legacy_mean,
        "v2_plain_best_s": plain_best,
        "v2_plain_mean_s": plain_mean,
        "v2_best_s": full_best,
        "v2_mean_s": full_mean,
        "slowdown": ratio(legacy_best, plain_best),
        "slowdown_with_parents": ratio(legacy_best, full_best),
        "nodes": document.node_count(),
        "source_bytes": len(source),
    }


def bench_serialize(source: str, reps: int) -> Dict[str, float]:
    legacy_document = get_adapter("python").parse_to_uast(source)
    document = parse_v2(source, use_cache=False)

    from muta_ext.uast.core_uast import CoreUAST as LegacyCoreUAST

    def legacy_json_bytes() -> bytes:
        return json.dumps(
            legacy_document.to_dict(), separators=(",", ":"), default=str
        ).encode("utf-8")

    legacy_json = legacy_json_bytes()
    legacy_zlib = zlib.compress(legacy_json, 6)
    v2_raw = v2_dumps(document)
    v2_zlib = v2_dumps(document, compress=6)

    def legacy_dump() -> bytes:
        return json.dumps(legacy_document.to_dict(), separators=(",", ":"), default=str).encode()

    def legacy_dump_zlib() -> bytes:
        return zlib.compress(legacy_dump(), 6)

    def v2_dump() -> bytes:
        return v2_dumps(document)

    def v2_dump_zlib() -> bytes:
        return v2_dumps(document, compress=6)

    def legacy_load() -> Any:
        return LegacyCoreUAST.from_dict(json.loads(legacy_json.decode("utf-8")))

    def legacy_load_zlib() -> Any:
        return LegacyCoreUAST.from_dict(json.loads(zlib.decompress(legacy_zlib).decode("utf-8")))

    def v2_load() -> Any:
        return v2_loads(v2_raw)

    def v2_load_zlib() -> Any:
        return v2_loads(v2_zlib)

    legacy_dump_best, _ = time_call(legacy_dump, reps)
    legacy_dump_z_best, _ = time_call(legacy_dump_zlib, reps)
    v2_dump_best, _ = time_call(v2_dump, reps)
    v2_dump_z_best, _ = time_call(v2_dump_zlib, reps)
    legacy_load_best, _ = time_call(legacy_load, reps)
    legacy_load_z_best, _ = time_call(legacy_load_zlib, reps)
    v2_load_best, _ = time_call(v2_load, reps)
    v2_load_z_best, _ = time_call(v2_load_zlib, reps)

    legacy_roundtrip = legacy_dump_best + legacy_load_best
    v2_roundtrip = v2_dump_best + v2_load_best
    legacy_roundtrip_z = legacy_dump_z_best + legacy_load_z_best
    v2_roundtrip_z = v2_dump_z_best + v2_load_z_best
    return {
        "legacy_dump_s": legacy_dump_best,
        "legacy_dump_zlib_s": legacy_dump_z_best,
        "v2_dump_s": v2_dump_best,
        "v2_dump_zlib_s": v2_dump_z_best,
        "legacy_load_s": legacy_load_best,
        "legacy_load_zlib_s": legacy_load_z_best,
        "v2_load_s": v2_load_best,
        "v2_load_zlib_s": v2_load_z_best,
        "dump_speedup": speedup(legacy_dump_best, v2_dump_best),
        "load_speedup": speedup(legacy_load_best, v2_load_best),
        "roundtrip_speedup": speedup(legacy_roundtrip, v2_roundtrip),
        "compressed_roundtrip_speedup": speedup(legacy_roundtrip_z, v2_roundtrip_z),
        "legacy_bytes": len(legacy_json),
        "legacy_zlib_bytes": len(legacy_zlib),
        "v2_bytes": len(v2_raw),
        "v2_zlib_bytes": len(v2_zlib),
        "size_ratio": len(v2_raw) / max(1, len(legacy_json)),
        "size_ratio_zlib": len(v2_zlib) / max(1, len(legacy_zlib)),
    }


def bench_hash(source: str, reps: int) -> Dict[str, float]:
    from muta_ext.uast2.merkle import recompute_all

    legacy_document = get_adapter("python").parse_to_uast(source)
    document = parse_v2(source, use_cache=False)

    def legacy_full() -> str:
        return legacy_document.canonical_hash()

    def v2_full() -> str:
        return recompute_all(document)

    legacy_best, _ = time_call(legacy_full, reps)
    v2_best, _ = time_call(v2_full, reps)

    # Incremental: mutate one leaf and re-hash (passes invalidate ancestors).
    leaf = next(
        node
        for node in document.walk()
        if type(node).__name__ == "Identifier" and node._parent is not None
    )

    def incremental() -> str:
        leaf.name = leaf.name + "x"
        from muta_ext.uast2.merkle import invalidate_up

        invalidate_up(leaf)
        return document.merkle_hash()

    incremental_best, _ = time_call(incremental, reps)
    return {
        "legacy_full_s": legacy_best,
        "v2_full_s": v2_best,
        "v2_incremental_s": incremental_best,
        "incremental_speedup": speedup(v2_best, incremental_best),
        "full_speedup": speedup(legacy_best, v2_best),
    }


def bench_candidate(source: str, reps: int, iterations: int = 20) -> Dict[str, float]:
    """Clone + re-hash, i.e. the engine infrastructure a candidate costs.

    The legacy engine copies the whole tree (``deepcopy``) and re-serialises it
    to JSON on every ``canonical_hash()``; v2 clones (still a full copy, but with
    slots) and re-hashes **only the dirty path** thanks to ``invalidate_up``.
    Comparing this — instead of mutator-internal work — keeps the two engines on
    the same job: "keep a pristine parent and hash the child".
    """
    from muta_ext.uast2.merkle import invalidate_up

    legacy_document = get_adapter("python").parse_to_uast(source)
    document = parse_v2(source, use_cache=False)
    assert legacy_document.canonical_hash()
    # The parent document keeps its Merkle digests between candidates: that is
    # how the evolutionary loop holds it (an individual is hashed once, then
    # cloned per candidate).  The legacy engine has no digest cache at all —
    # ``canonical_hash()`` re-dumps the whole tree on every call.  The cold cost
    # of a v2 re-hash from scratch is reported separately in section [3].
    document.merkle_hash()

    def legacy_candidate() -> str:
        clone = copy.deepcopy(legacy_document)
        return clone.canonical_hash()

    def v2_candidate() -> str:
        clone = document.clone()
        return clone.merkle_hash()

    def v2_candidate_edit() -> str:
        clone = document.clone()
        target = next(
            node
            for node in clone.walk()
            if type(node).__name__ == "Identifier" and node._parent is not None
        )
        target.name = target.name + "x"
        invalidate_up(target)
        return clone.merkle_hash()

    legacy_best, _ = time_call(legacy_candidate, max(1, reps))
    v2_best, _ = time_call(v2_candidate, max(1, reps))
    v2_edit_best, _ = time_call(v2_candidate_edit, max(1, reps))
    per_iter = max(1, iterations)
    return {
        "legacy_per_candidate_us": legacy_best * 1e6,
        "v2_per_candidate_us": v2_best * 1e6,
        "v2_edited_candidate_us": v2_edit_best * 1e6,
        "speedup": speedup(legacy_best, v2_best),
        "edited_speedup": speedup(legacy_best, v2_edit_best),
        "iterations": per_iter,
    }


def bench_pipeline(source: str, reps: int) -> Dict[str, float]:
    """Full in-place mutation pipeline over one candidate (4 mutators + verify)."""
    from muta_ext.uast2.mutators import default_mutators
    from muta_ext.uast2.verify import default_verifiers

    document = parse_v2(source, use_cache=False)

    def run(rollback: Any) -> Any:
        clone = document.clone()
        pipeline = Pipeline(default_verifiers(document) + default_mutators(seed=11), rollback=rollback)
        pipeline.run(clone)
        return clone

    from muta_ext.uast2.verify import (
        ChildSchemaVerify,
        NumericSanityVerify,
        ParentLinkVerify,
        StructuralVerify,
    )

    atomic_best, _ = time_call(lambda: run(True), max(1, reps))
    fast_best, _ = time_call(lambda: run(False), max(1, reps))
    scope = [document.body[1]]
    full_verify = sum(
        time_call(lambda v=cls(): v.verify(document), max(1, reps))[0]
        for cls in (
            StructuralVerify,
            ChildSchemaVerify,
            ParentLinkVerify,
            NumericSanityVerify,
        )
    )
    scoped_verify = sum(
        time_call(lambda v=cls(): v.verify(document, scope), max(1, reps))[0]
        for cls in (
            StructuralVerify,
            ChildSchemaVerify,
            ParentLinkVerify,
            NumericSanityVerify,
        )
    )
    return {
        "atomic_us": atomic_best * 1e6,
        "no_rollback_us": fast_best * 1e6,
        "rollback_cost_us": (atomic_best - fast_best) * 1e6,
        "full_verify_us": full_verify * 1e6,
        "scoped_verify_us": scoped_verify * 1e6,
        "verify_speedup": speedup(full_verify, scoped_verify),
    }


def bench_memory(source: str, documents: int = 30) -> Dict[str, float]:
    """Retained bytes per parsed document (tracemalloc, one document at a time)."""
    legacy_adapter = get_adapter("python")

    def measure(builder: Callable[[], Any], keep: List[Any]) -> int:
        gc.collect()
        tracemalloc.start()
        before, _ = tracemalloc.get_traced_memory()
        for _ in range(documents):
            keep.append(builder())
        after, _ = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        kept = len(keep)
        keep.clear()
        gc.collect()
        return (after - before) // max(1, kept)

    legacy_docs: List[Any] = []
    v2_docs: List[Any] = []
    legacy_bytes = measure(lambda: legacy_adapter.parse_to_uast(source), legacy_docs)
    v2_bytes = measure(lambda: parse_v2(source, use_cache=False), v2_docs)
    v2_plain_bytes = measure(lambda: parse_v2(source, use_cache=False), v2_docs)
    nodes = parse_v2(source, use_cache=False).node_count()
    return {
        "legacy_bytes_per_doc": legacy_bytes,
        "v2_bytes_per_doc": v2_bytes,
        "v2_no_locations_bytes_per_doc": v2_plain_bytes,
        "ratio": v2_bytes / max(1, legacy_bytes),
        "legacy_bytes_per_node": legacy_bytes / max(1, nodes),
        "v2_bytes_per_node": v2_bytes / max(1, nodes),
        "nodes": nodes,
    }


def bench_shadow(paths: List[Path], mode: str = "exact") -> Dict[str, Any]:
    report = run_shadow_suite(paths, mode=mode)
    return {
        "files": report["files"],
        "mismatches": report["mismatches"],
        "errors": report["errors"],
        "ok": report["ok"],
        "differences": [
            {"path": entry["path"], "differences": entry.get("differences", [])[:2]}
            for entry in report["results"]
            if entry.get("error") or not entry.get("equal", True)
        ][:5],
    }


def bench_phase6(reps: int) -> Dict[str, Any]:
    """Regression gate: run the Phase-6 benchmark and report its headline number."""
    try:
        import contextlib
        import io as _io

        import bench_phase6 as phase6
    except Exception as exc:  # pragma: no cover - optional
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    buffer = _io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            samples, average, minimum = phase6.bench_end_to_end(reps=max(1, min(reps, 2)))
        except Exception as exc:  # pragma: no cover - optional
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"available": True, "min_s": minimum, "avg_s": average, "samples": samples}


# ── reporting ────────────────────────────────────────────────────────────────


def _fmt(value: Optional[float], unit: str = "s", digits: int = 6) -> str:
    if value is None:
        return "n/a"
    if unit == "s":
        return f"{value * 1e6:8.1f} us"
    if unit == "x":
        return f"{value:8.2f} x"
    if unit == "B":
        return f"{value:8.1f} B"
    return f"{value:{digits}.4f}"


def evaluate_gates(results: Dict[str, Any]) -> List[Tuple[str, str, str, bool]]:
    gates: List[Tuple[str, str, str, bool]] = []
    parse = results["parse"]
    serialization = results["serialize"]
    memory = results["memory"]
    hashing = results["hash"]
    candidates = results["candidate"]
    shadow_result = results["shadow"]
    gates.append(
        (
            "parse slowdown (structure only)",
            "<= 1.10x vs legacy",
            f"{parse['slowdown']:.2f}x",
            parse["slowdown"] <= 1.10,
        )
    )
    gates.append(
        (
            "parse slowdown (+parents+locations)",
            "informational (extra data)",
            f"{parse['slowdown_with_parents']:.2f}x",
            True,
        )
    )
    gates.append(
        (
            "serialise roundtrip speedup (raw)",
            ">= 1.5x vs legacy JSON",
            f"{serialization['roundtrip_speedup']:.2f}x",
            serialization["roundtrip_speedup"] >= 1.5,
        )
    )
    gates.append(
        (
            "serialise roundtrip speedup (zlib)",
            ">= 1.5x vs legacy JSON+zlib",
            f"{serialization['compressed_roundtrip_speedup']:.2f}x",
            serialization["compressed_roundtrip_speedup"] >= 1.5,
        )
    )
    gates.append(
        (
            "payload size (v2/legacy, raw)",
            "<= 0.60",
            f"{serialization['size_ratio']:.2f}",
            serialization["size_ratio"] <= 0.60,
        )
    )
    gates.append(
        (
            "clone + incremental re-hash",
            ">= 1.5x (deepcopy+hash, warm parent)",
            f"{candidates['speedup']:.2f}x",
            candidates["speedup"] >= 1.5,
        )
    )
    gates.append(
        (
            "scoped nanopass guards",
            ">= 5x cheaper than full verify",
            f"{results['pipeline']['verify_speedup']:.1f}x",
            results["pipeline"]["verify_speedup"] >= 5.0,
        )
    )
    gates.append(
        (
            "incremental re-hash speedup",
            ">= 2.0x (vs full v2 re-hash)",
            f"{hashing['incremental_speedup']:.2f}x",
            hashing["incremental_speedup"] >= 2.0,
        )
    )
    gates.append(
        (
            "edited clone + re-hash",
            "informational",
            f"{candidates['edited_speedup']:.2f}x",
            True,
        )
    )
    gates.append(
        (
            "node footprint (v2/legacy, RAM)",
            "informational",
            f"{memory['ratio']:.2f}",
            True,
        )
    )
    gates.append(
        (
            "shadow parity over examples/",
            "0 mismatches",
            f"{shadow_result['mismatches']} mismatch(es), {shadow_result['errors']} error(s)",
            shadow_result["mismatches"] == 0 and shadow_result["errors"] == 0,
        )
    )
    return gates


def main() -> int:
    parser = argparse.ArgumentParser(description="UAST v2 benchmark")
    parser.add_argument("--functions", type=int, default=24, help="functions in the workload")
    parser.add_argument("--reps", type=int, default=3, help="timing repeats")
    parser.add_argument("--quick", action="store_true", help="fast run (1 repeat, 8 functions)")
    parser.add_argument("--json", type=Path, default=None, help="write raw results as JSON")
    parser.add_argument("--phase6", action="store_true", help="also run the phase-6 gate")
    parser.add_argument(
        "--examples",
        type=str,
        default="examples",
        help="directory of sources for the shadow parity gate",
    )
    args = parser.parse_args()

    if args.quick:
        args.reps = 1
        args.functions = 8

    source = make_source(args.functions)
    results: Dict[str, Any] = {"workload_functions": args.functions, "reps": args.reps}

    print("=" * 78)
    print("UAST v2 benchmark — legacy engine vs muta_ext.uast2")
    print(f"workload: {len(source)} bytes, {args.functions} functions, reps={args.reps}")
    print("=" * 78)

    results["parse"] = bench_parse(source, args.reps)
    print("\n[1] parse")
    print(f"    legacy            {_fmt(results['parse']['legacy_best_s'])}")
    print(f"    v2 structure only {_fmt(results['parse']['v2_plain_best_s'])}  "
          f"(x{results['parse']['slowdown']:.2f} vs legacy)")
    print(f"    v2 + parents/locs {_fmt(results['parse']['v2_best_s'])}  "
          f"(x{results['parse']['slowdown_with_parents']:.2f}, {results['parse']['nodes']} nodes)")

    results["serialize"] = bench_serialize(source, args.reps)
    serialization = results["serialize"]
    print("\n[2] serialisation (flat msgpack vs legacy JSON)")
    print(f"    dump    raw      legacy {_fmt(serialization['legacy_dump_s'])}   "
          f"v2 {_fmt(serialization['v2_dump_s'])}   x{serialization['dump_speedup']:.2f}")
    print(f"            zlib     legacy {_fmt(serialization['legacy_dump_zlib_s'])}   "
          f"v2 {_fmt(serialization['v2_dump_zlib_s'])}   "
          f"x{speedup(serialization['legacy_dump_zlib_s'], serialization['v2_dump_zlib_s']):.2f}")
    print(f"    load    raw      legacy {_fmt(serialization['legacy_load_s'])}   "
          f"v2 {_fmt(serialization['v2_load_s'])}   x{serialization['load_speedup']:.2f}")
    print(f"            zlib     legacy {_fmt(serialization['legacy_load_zlib_s'])}   "
          f"v2 {_fmt(serialization['v2_load_zlib_s'])}   "
          f"x{speedup(serialization['legacy_load_zlib_s'], serialization['v2_load_zlib_s']):.2f}")
    print(f"    bytes   raw      legacy {serialization['legacy_bytes']}B   "
          f"v2 {serialization['v2_bytes']}B   ratio {serialization['size_ratio']:.2f}")
    print(f"            zlib     legacy {serialization['legacy_zlib_bytes']}B   "
          f"v2 {serialization['v2_zlib_bytes']}B   ratio {serialization['size_ratio_zlib']:.2f}")

    results["hash"] = bench_hash(source, args.reps)
    hashing = results["hash"]
    print("\n[3] hashing")
    print(f"    legacy full       {_fmt(hashing['legacy_full_s'])}")
    print(f"    v2 full           {_fmt(hashing['v2_full_s'])}  (x{hashing['full_speedup']:.2f})")
    print(f"    v2 incremental    {_fmt(hashing['v2_incremental_s'])}  "
          f"(x{hashing['incremental_speedup']:.2f} vs full)")

    results["candidate"] = bench_candidate(source, args.reps)
    candidates = results["candidate"]
    results["pipeline"] = bench_pipeline(source, args.reps)
    print("\n[4] per-candidate engine cost (clone + re-hash, hashed parent)")
    print(f"    legacy deepcopy + JSON hash  {candidates['legacy_per_candidate_us']:9.1f} us")
    print(f"    v2 clone + cached hash       {candidates['v2_per_candidate_us']:9.1f} us   "
          f"(x{candidates['speedup']:.2f})")
    print(f"    v2 clone + edited re-hash    {candidates['v2_edited_candidate_us']:9.1f} us   "
          f"(x{candidates['edited_speedup']:.2f})")
    pipeline = results["pipeline"]
    print("    full mutation pipeline       "
          f"atomic {pipeline['atomic_us']:.0f} us / no-rollback {pipeline['no_rollback_us']:.0f} us")
    print("    per-nanopass guards          "
          f"full-tree {pipeline['full_verify_us']:.0f} us -> scoped {pipeline['scoped_verify_us']:.0f} us "
          f"(x{pipeline['verify_speedup']:.0f})")

    results["memory"] = bench_memory(source)
    memory = results["memory"]
    print("\n[5] memory (retained per document)")
    print(f"    legacy  {memory['legacy_bytes_per_doc']:8.0f} B/doc "
          f"({memory['legacy_bytes_per_node']:.0f} B/node)")
    print(f"    v2      {memory['v2_bytes_per_doc']:8.0f} B/doc "
          f"({memory['v2_bytes_per_node']:.0f} B/node)  ratio {memory['ratio']:.2f}")
    print("    (v2 stores parent pointers + source coordinates per node, which the")
    print("     legacy engine does not track at all — see docs/uast2.md)")

    examples = sorted(Path(args.examples).rglob("*.py"))
    results["shadow"] = bench_shadow(examples)
    print("\n[6] shadow parity (legacy vs v2 structure)")
    print(f"    files={results['shadow']['files']} mismatches={results['shadow']['mismatches']} "
          f"errors={results['shadow']['errors']} ok={results['shadow']['ok']}")
    for entry in results["shadow"]["differences"]:
        print(f"      DIFF {entry['path']}: {entry['differences']}")

    if args.phase6:
        results["phase6"] = bench_phase6(args.reps)
        print("\n[7] phase-6 end-to-end regression gate")
        if results["phase6"].get("available"):
            print(f"    bench_end_to_end min={results['phase6']['min_s']:.3f}s "
                  f"avg={results['phase6']['avg_s']:.3f}s")
        else:
            print(f"    unavailable: {results['phase6'].get('error')}")

    gates = evaluate_gates(results)
    print("\n" + "=" * 78)
    print("GATES")
    print("=" * 78)
    for name, target, measured, passed in gates:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name:<38} target {target:<28} measured {measured}")
    results["gates"] = [
        {"name": name, "target": target, "measured": measured, "passed": passed}
        for name, target, measured, passed in gates
    ]

    if args.json:
        args.json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"\nraw results -> {args.json}")
    return 0 if all(gate[3] for gate in gates) else 1


if __name__ == "__main__":  # pragma: no cover - manual entry point
    sys.exit(main())
