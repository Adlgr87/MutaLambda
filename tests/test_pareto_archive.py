"""Tests for the Fase-3 Pareto Archive (A5) + run_evolution integration
(economic gate early-stop, warm-start, roi_report)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimization_flags import reset_optimization_flags  # noqa: E402
from pareto_archive import ParetoArchive, signature_hash  # noqa: E402

SOURCE_A = '''def process(data, k=32):
    total = 0
    for i in range(len(data)):
        total = total + data[i] * 2
    return total
'''

# Same public API, different body constant → "similar function".
SOURCE_B = '''def process(data, k=32):
    total = 0
    for i in range(len(data)):
        total = total + data[i] * 3
    return total
'''

# Different public API.
SOURCE_C = '''def other(data):
    return sum(data)
'''

SIMILAR_WHITESPACE = '''def process(data, k=32):
    total = 0
    for i in range(len(data)):
        total = total + data[i] * 2
    return total


# trailing comment
'''


# ── signature hash ──────────────────────────────────────────────────────────


def test_signature_hash_same_api_same_hash() -> None:
    assert signature_hash(SOURCE_A) == signature_hash(SOURCE_B)
    assert signature_hash(SOURCE_A) == signature_hash(SIMILAR_WHITESPACE)


def test_signature_hash_different_api_different_hash() -> None:
    assert signature_hash(SOURCE_A) != signature_hash(SOURCE_C)


# ── store / lookup ──────────────────────────────────────────────────────────


def test_store_lookup_roundtrip(tmp_path) -> None:
    ar = ParetoArchive(tmp_path / "arch")
    sig = ar.store(SOURCE_A, "def process(data, k=32):\n    return 0\n",
                   score=0.9, hypervolume=0.7, generation=12, profile="enterprise")
    entry = ar.lookup(SOURCE_B)  # same API → hit
    assert entry is not None
    assert entry["code"] == "def process(data, k=32):\n    return 0\n"
    assert entry["signature_hash"] == sig
    assert entry["generation"] == 12
    assert ar.lookup(SOURCE_C) is None  # different API → miss


def test_store_replaces_previous_entry(tmp_path) -> None:
    ar = ParetoArchive(tmp_path / "arch")
    ar.store(SOURCE_A, "code_v1", score=0.5)
    ar.store(SOURCE_A, "code_v2", score=0.9)
    entry = ar.lookup(SOURCE_A)
    assert entry["code"] == "code_v2"
    assert len(ar.list_entries()) == 1


def test_list_and_clear(tmp_path) -> None:
    ar = ParetoArchive(tmp_path / "arch")
    ar.store(SOURCE_A, "code_a", score=0.5)
    ar.store(SOURCE_C, "code_c", score=0.7)
    entries = ar.list_entries()
    assert {e["code"] for e in entries} == {"code_a", "code_c"}
    ar.clear()
    assert ar.lookup(SOURCE_A) is None
    assert ar.list_entries() == []


# ── run_evolution integration ───────────────────────────────────────────────


def _write_uast(tmp_path: Path, source: str) -> Path:
    p = tmp_path / "uast.json"
    p.write_text(json.dumps({"source_text": source}), encoding="utf-8")
    return p


def _f3_env(monkeypatch, tmp_path: Path, *, gate: bool = True, archive: bool = True) -> None:
    monkeypatch.setenv("MUTALAMBDA_OPT_ECONOMIC_GATE__ENABLED", "1" if gate else "0")
    monkeypatch.setenv("MUTALAMBDA_OPT_PARETO_ARCHIVE__ENABLED", "1" if archive else "0")
    monkeypatch.setenv("MUTALAMBDA_OPT_PARETO_ARCHIVE__DIR", str(tmp_path / "arch"))
    monkeypatch.setenv("MUTALAMBDA_OPT_FITNESS_CACHE__ENABLED", "0")
    monkeypatch.setenv("MUTALAMBDA_OPT_CHECKPOINT__EVERY", "0")
    reset_optimization_flags()


def test_run_evolution_gate_stops_early(monkeypatch, tmp_path) -> None:
    from evolve import EvolveConfig, run_evolution

    _f3_env(monkeypatch, tmp_path, gate=True, archive=False)
    uast = _write_uast(tmp_path, SOURCE_A)
    res = run_evolution(
        EvolveConfig(uast_path=uast, generations=40, population=16, seed=42,
                     output_dir=tmp_path / "out")
    )
    assert res.details["stop_reason"] == "stall"
    assert res.generations < 40
    assert res.details["stop_generation"] is not None
    roi = json.loads((Path(res.checkpoint_dir) / "roi_report.json").read_text())
    assert roi["economic_gate"]["stop_reason"] == "stall"
    assert roi["generations_run"] == res.generations
    assert 0.0 < roi["final_hypervolume"] <= 1.0


def test_run_evolution_no_gate_runs_full_and_completes(monkeypatch, tmp_path) -> None:
    from evolve import EvolveConfig, run_evolution

    _f3_env(monkeypatch, tmp_path, gate=False, archive=False)
    uast = _write_uast(tmp_path, SOURCE_A)
    res = run_evolution(
        EvolveConfig(uast_path=uast, generations=12, population=12, seed=42,
                     output_dir=tmp_path / "out")
    )
    assert res.generations == 12
    assert res.details["stop_reason"] == "completed"
    roi = json.loads((Path(res.checkpoint_dir) / "roi_report.json").read_text())
    assert roi["economic_gate"] is None
    assert roi["levers"]["fase3"]["economic_gate"] is False


def test_warm_start_second_run_hits_archive(monkeypatch, tmp_path) -> None:
    from evolve import EvolveConfig, run_evolution

    _f3_env(monkeypatch, tmp_path, gate=True, archive=True)
    uast = _write_uast(tmp_path, SOURCE_A)

    r1 = run_evolution(
        EvolveConfig(uast_path=uast, generations=40, population=16, seed=42,
                     output_dir=tmp_path / "out1")
    )
    assert r1.details["warm_start"]["used"] is False

    # Same API (different body constant) → warm-start hit.
    uast_b = tmp_path / "uast_b.json"
    uast_b.write_text(json.dumps({"source_text": SOURCE_B}), encoding="utf-8")
    r2 = run_evolution(
        EvolveConfig(uast_path=uast_b, generations=40, population=16, seed=42,
                     output_dir=tmp_path / "out2")
    )
    ws = r2.details["warm_start"]
    assert ws["used"] is True
    assert ws["signature_hit"] is True
    assert ws["archived_score"] is not None
    # The archived individual seeds run 2: its best must reach at least the
    # archived score immediately (generation 0 or 1).
    first = r2.fitness_report[0].best_score
    assert first >= ws["archived_score"] * 0.99


def test_warm_start_disabled_by_flag(monkeypatch, tmp_path) -> None:
    from evolve import EvolveConfig, run_evolution

    _f3_env(monkeypatch, tmp_path, gate=False, archive=True)
    uast = _write_uast(tmp_path, SOURCE_A)
    r1 = run_evolution(
        EvolveConfig(uast_path=uast, generations=8, population=10, seed=42,
                     output_dir=tmp_path / "out1")
    )
    r2 = run_evolution(
        EvolveConfig(uast_path=uast, generations=8, population=10, seed=42,
                     warm_start=False, output_dir=tmp_path / "out2")
    )
    assert r1.details["warm_start"]["used"] is False
    assert r2.details["warm_start"]["used"] is False


def test_roi_report_documents_levers_and_cost(monkeypatch, tmp_path) -> None:
    from evolve import EvolveConfig, run_evolution

    _f3_env(monkeypatch, tmp_path, gate=True, archive=True)
    uast = _write_uast(tmp_path, SOURCE_A)
    res = run_evolution(
        EvolveConfig(uast_path=uast, generations=40, population=16, seed=42,
                     output_dir=tmp_path / "out")
    )
    roi = json.loads((Path(res.checkpoint_dir) / "roi_report.json").read_text())
    for key in ("profile", "mutation_strategy", "generations_planned",
                "generations_run", "stop_reason", "stop_generation",
                "best_score", "final_hypervolume", "cost", "levers",
                "economic_gate", "warm_start"):
        assert key in roi
    assert roi["cost"]["total_cost_usd"] >= 0.0
    assert roi["levers"]["fase3"]["economic_gate"] is True
    assert roi["levers"]["fase3"]["pareto_archive"] is True
    assert res.details["roi_report"] is not None


def test_mutation_strategy_auto_resolves_to_ast_without_keys(monkeypatch, tmp_path) -> None:
    from evolve import EvolveConfig, run_evolution

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _f3_env(monkeypatch, tmp_path, gate=False, archive=False)
    uast = _write_uast(tmp_path, SOURCE_A)
    res = run_evolution(
        EvolveConfig(uast_path=uast, generations=6, population=8, seed=42,
                     mutation_strategy="auto", output_dir=tmp_path / "out")
    )
    roi = json.loads((Path(res.checkpoint_dir) / "roi_report.json").read_text())
    assert roi["strategy_resolved"].startswith("auto→")


def test_evolve_config_rejects_bad_strategy() -> None:
    from evolve import EvolveConfig

    with pytest.raises(ValueError):
        EvolveConfig(uast_path=Path("x.json"), mutation_strategy="quantum")


def test_astmutator_survives_ifexp_targets() -> None:
    """Regression: conditional expressions (ast.IfExp) carry `body` fields
    that are expressions, not statement lists.  The body-walking mutators
    used to crash with TypeError on such targets."""
    import random

    from evolution_engine import ASTMutator

    target = (
        "def apply_all(data, k=32):\n"
        "    a = sum(data)\n"
        "    b = len(data)\n"
        "    c = clip(a / b if b else a, 0, 100)\n"
        "    d = c if c > 1 else 0\n"
        "    return d\n"
    )
    for seed in range(20):
        random.seed(seed)
        out = ASTMutator.apply_random_mutation(target)  # must not raise
        assert isinstance(out, str) and out.strip()
