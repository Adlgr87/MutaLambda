"""Integration tests: fitness cache inside the evolution engine (Fase 0, A2).

Acceptance: cache hit rate >= 20% on a representative run, and the lever is
fully disable-able via config/optimization.yaml (regla 6).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from evolve import EvolveConfig, run_evolution
from universal_parser import emit_uast_dict

SAMPLE_PYTHON = '''"""Example target."""


def solution(n: int) -> int:
    """Sum of 1..n."""
    total = 0
    i = 1
    while i <= n:
        total = total + i
        i = i + 1
    return total
'''


@pytest.fixture(autouse=True)
def _clean_opt_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MUTALAMBDA_OPT_"):
            monkeypatch.delenv(name)
    from optimization_flags import reset_optimization_flags

    reset_optimization_flags()
    yield
    reset_optimization_flags()


@pytest.fixture
def uast_json(tmp_path: Path) -> Path:
    from muta_ext.uast.adapters import get_adapter

    uast = get_adapter("python").parse_to_uast(SAMPLE_PYTHON)
    payload = emit_uast_dict(uast, source=SAMPLE_PYTHON)
    path = tmp_path / "uast.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestFitnessCacheInEvolution:
    def test_hfc_run_cache_hit_rate_at_least_20_percent(self, uast_json: Path, tmp_path: Path):
        cfg = EvolveConfig(
            uast_path=uast_json,
            profile="scientific",
            generations=4,
            population=8,
            hfc_tiers=True,
            checkpoint_every=0,
            seed=42,
            output_dir=tmp_path,
        )
        result = run_evolution(cfg)
        stats = result.fitness_cache_stats
        assert stats is not None, "fitness cache should be active by default"
        assert stats["backend"] == "sqlite"
        assert stats["hits"] + stats["misses"] > 0
        # Acceptance gate: hit rate >= 20%.
        assert stats["hit_rate"] >= 0.20, f"hit rate {stats['hit_rate']:.2%} < 20%"

    def test_inline_run_produces_cache_stats(self, uast_json: Path, tmp_path: Path):
        cfg = EvolveConfig(
            uast_path=uast_json,
            profile="enterprise",
            generations=5,
            population=6,
            hfc_tiers=False,
            checkpoint_every=0,
            seed=1,
            output_dir=tmp_path,
        )
        result = run_evolution(cfg)
        stats = result.fitness_cache_stats
        assert stats is not None
        assert stats["hits"] > 0  # survivors are re-scored across generations

    def test_cache_persists_to_output_dir(self, uast_json: Path, tmp_path: Path):
        cfg = EvolveConfig(
            uast_path=uast_json,
            profile="enterprise",
            generations=2,
            population=4,
            hfc_tiers=False,
            checkpoint_every=0,
            seed=3,
            output_dir=tmp_path,
        )
        result = run_evolution(cfg)
        assert result.fitness_cache_stats is not None
        # Cache file lives under the run's output dir (no cross-run leakage).
        assert Path(result.fitness_cache_stats["path"]).is_relative_to(tmp_path)

    def test_cache_disable_via_flag(self, uast_json: Path, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_OPT_FITNESS_CACHE__ENABLED", "0")
        cfg = EvolveConfig(
            uast_path=uast_json,
            profile="enterprise",
            generations=2,
            population=4,
            hfc_tiers=False,
            checkpoint_every=0,
            seed=3,
            output_dir=tmp_path,
        )
        result = run_evolution(cfg)
        assert result.fitness_cache_stats is None

    def test_json_backend_flag(self, uast_json: Path, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_OPT_FITNESS_CACHE__BACKEND", "json")
        cfg = EvolveConfig(
            uast_path=uast_json,
            profile="enterprise",
            generations=2,
            population=4,
            hfc_tiers=False,
            checkpoint_every=0,
            seed=3,
            output_dir=tmp_path,
        )
        result = run_evolution(cfg)
        assert result.fitness_cache_stats is not None
        assert result.fitness_cache_stats["backend"] == "json"
