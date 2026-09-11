"""Tests for the optimization flag layer (Fase 0, regla 6)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import optimization_flags as oflags
from optimization_flags import (
    OptimizationFlags,
    default_config_path,
    get_optimization_flags,
    load_optimization_config,
    reset_optimization_flags,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in list(__import__("os").environ):
        if name.startswith("MUTALAMBDA_OPT_"):
            monkeypatch.delenv(name)
    reset_optimization_flags()
    yield
    reset_optimization_flags()


def test_defaults_present():
    flags = load_optimization_config(path=Path("/nonexistent/optimization.yaml"))
    assert flags.enabled("cost_ledger.enabled") is True
    assert flags.get("checkpoint.every") == 5
    assert flags.get("fitness_cache.backend") == "sqlite"
    assert flags.enabled("headroom.enabled") is False  # Fase 1 stays off until setup
    assert flags.enabled("economic_gate.enabled") is False
    assert flags.enabled("pareto_archive.enabled") is False


def test_repo_config_file_is_picked_up():
    """config/optimization.yaml at the repo root feeds the loader."""
    path = default_config_path()
    assert path.exists(), "repo must ship config/optimization.yaml"
    flags = load_optimization_config()
    assert flags.source == str(path)
    assert flags.get("checkpoint.every") == 5
    assert flags.get("headroom.batching.batch_size") == 5
    assert flags.get("profiling_filter.sandbox_top_pct") == 20.0


def test_explicit_yaml_file_loading(tmp_path: Path):
    p = tmp_path / "opt.yaml"
    p.write_text(
        textwrap.dedent(
            """
            optimization:
              cost_ledger:
                enabled: false
                gpu_hour_usd: 1.25
              economic_gate:
                enabled: true
            """
        ),
        encoding="utf-8",
    )
    flags = load_optimization_config(path=p)
    assert flags.source == str(p)
    assert flags.enabled("cost_ledger.enabled") is False
    assert flags.get("cost_ledger.gpu_hour_usd") == 1.25
    assert flags.enabled("economic_gate.enabled") is True
    # Untouched keys keep their defaults (deep merge).
    assert flags.get("checkpoint.every") == 5


def test_bare_section_yaml_accepted(tmp_path: Path):
    """A file without the top-level `optimization:` wrapper also works."""
    p = tmp_path / "bare.yaml"
    p.write_text("cost_ledger:\n  enabled: false\n", encoding="utf-8")
    flags = load_optimization_config(path=p)
    assert flags.enabled("cost_ledger.enabled") is False


def test_env_override_bool(monkeypatch):
    monkeypatch.setenv("MUTALAMBDA_OPT_COST_LEDGER__ENABLED", "0")
    flags = load_optimization_config()
    assert flags.enabled("cost_ledger.enabled") is False
    monkeypatch.setenv("MUTALAMBDA_OPT_COST_LEDGER__ENABLED", "1")
    flags = load_optimization_config()
    assert flags.enabled("cost_ledger.enabled") is True


def test_env_override_scalar(monkeypatch):
    monkeypatch.setenv("MUTALAMBDA_OPT_CHECKPOINT__EVERY", "7")
    flags = load_optimization_config()
    assert flags.get("checkpoint.every") == 7


def test_env_override_nested_key(monkeypatch):
    """Nested paths: MUTALAMBDA_OPT_HEADROOM__SMART_CRUSHER__ENABLED."""
    monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__SMART_CRUSHER__ENABLED", "1")
    flags = load_optimization_config()
    assert flags.enabled("headroom.smart_crusher.enabled") is True
    # Siblings stay untouched.
    assert flags.enabled("headroom.ast_stubs.enabled") is False
    assert flags.get("headroom.batching.batch_size") == 5


def test_env_config_path_pointer(monkeypatch, tmp_path: Path):
    p = tmp_path / "custom.yaml"
    p.write_text("checkpoint:\n  every: 9\n", encoding="utf-8")
    monkeypatch.setenv("MUTALAMBDA_OPT_CONFIG", str(p))
    flags = load_optimization_config()
    assert flags.get("checkpoint.every") == 9


def test_singleton_caching_and_reset():
    first = get_optimization_flags()
    second = get_optimization_flags()
    assert first is second
    reset_optimization_flags()
    third = get_optimization_flags()
    assert third is not first


def test_missing_key_returns_default():
    flags = OptimizationFlags({"a": {"b": 1}}, source="t")
    assert flags.get("a.b") == 1
    assert flags.get("a.c", 42) == 42
    assert flags.get("x.y.z", "dflt") == "dflt"
    assert flags.enabled("a.b") is True
    assert flags.enabled("nope") is False
    assert flags.section("a") == {"b": 1}
    assert flags.section("nope") == {}
