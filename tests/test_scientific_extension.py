import pytest

from muta_ext.config.scientific_extension import EvolutionaryExtensionConfig
from muta_ext.evaluation.numerical_health import evaluate_numerical_health
from muta_ext.diagnostics.tipping import detect_tipping


def test_numerical_health_disabled_returns_neutral():
    cfg = EvolutionaryExtensionConfig(enable_numerical_health=False)
    h = evaluate_numerical_health(
        "def f(a, b):\n    return a / b",
        config=cfg,
    )
    assert h.is_stable is True
    assert h.score == pytest.approx(1.0)
    assert h.has_division is False


def test_numerical_health_enabled_detects_division():
    cfg = EvolutionaryExtensionConfig(enable_numerical_health=True)
    h = evaluate_numerical_health(
        "def f(a, b):\n    return a / b",
        config=cfg,
    )
    assert h.has_division is True
    # Con división simple, los umbrales actuales pueden mantener estabilidad.
    assert h.score < 1.0


def test_tipping_detection_disabled_returns_empty():
    cfg = EvolutionaryExtensionConfig(enable_tipping_detection=False)
    series = [1.0, 2.0, 1.0, 10.0, 1.0, 2.0, 1.0, 2.0]
    events = detect_tipping(
        series,
        window=5,
        n_deviations=2.0,
        config=cfg,
    )
    assert events == []


def test_tipping_detection_enabled_runs():
    cfg = EvolutionaryExtensionConfig(enable_tipping_detection=True)
    series = [
        10.0, 10.5, 9.8, 10.2, 10.1, 9.9, 10.3, 10.0,
        3.0, 2.5, 2.8, 3.2, 2.9, 3.1, 2.7,
    ]
    events = detect_tipping(
        series,
        window=7,
        n_deviations=2.0,
        min_magnitude=0.3,
        config=cfg,
    )
    assert isinstance(events, list)
    # Si hay eventos, deben incluir metadata mínima requerida.
    for ev in events:
        assert isinstance(ev.metadata, dict)
        assert ev.metadata.get("detector") == "MAD"
        assert "deviation" in ev.metadata
        assert "timestamp" in ev.metadata


def test_adaptive_solver_flag_off_degrades_safely():
    # "OFF" debe conservar comportamiento neutral/estable para entradas simples.
    cfg = EvolutionaryExtensionConfig(enable_numerical_health=True, enable_adaptive_solver=False)
    h = evaluate_numerical_health(
        "def f(a, b):\n    return a / b",
        config=cfg,
    )
    assert isinstance(h.score, float)
    assert h.has_division is True


def test_adaptive_solver_flag_on_runs_and_never_crashes():
    cfg = EvolutionaryExtensionConfig(enable_numerical_health=True, enable_adaptive_solver=True)
    h = evaluate_numerical_health(
        "def f(a, b):\n    return a + b + a + b",
        config=cfg,
    )
    assert isinstance(h.score, float)
    assert 0.0 <= h.score <= 1.0
