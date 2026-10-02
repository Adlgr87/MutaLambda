"""The same default must never be typed twice.

Before the v5 scrutiny pass the evolution defaults existed in FOUR places with
no link between them:

  1. ``mutalambda_core.constants``        (DEFAULT_*, read by nobody but one)
  2. ``mutalambda_config.config_loader``  (``_DEFAULTS`` YAML layer)
  3. ``mutalambda_config.muta_config``    (Pydantic ``Field(...)``)
  4. ``muta_lambda.config.EvolveConfig``  (dataclass)

They happened to agree, but nothing enforced it. These tests make
``constants.py`` the single source of truth and fail loudly on drift.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from muta_lambda import EvolveConfig
from mutalambda_config.config_loader import apply_defaults
from mutalambda_config.muta_config import MutaLambdaConfig
from mutalambda_core import constants as C


@pytest.fixture(scope="module")
def yaml_defaults() -> dict:
    return apply_defaults({})


@pytest.fixture(scope="module")
def pydantic_defaults() -> MutaLambdaConfig:
    return MutaLambdaConfig()


@pytest.fixture(scope="module")
def dataclass_defaults() -> EvolveConfig:
    return EvolveConfig()


# constant | yaml dotted path | pydantic attribute path | EvolveConfig field
MATRIX = [
    ("DEFAULT_NUM_ISLANDS", "evolution.num_islands", "evolution.num_islands", "num_islands"),
    ("DEFAULT_GENERATIONS", "evolution.generations", "evolution.generations", "generations"),
    ("DEFAULT_TOPOLOGY", "evolution.topology", "evolution.topology", "topology"),
    (
        "DEFAULT_EARLY_STOP_PATIENCE",
        "evolution.early_stop_patience",
        "evolution.early_stop_patience",
        "early_stop_patience",
    ),
    (
        "DEFAULT_EARLY_STOP_DELTA",
        "evolution.early_stop_delta",
        "evolution.early_stop_delta",
        "early_stop_delta",
    ),
    ("DEFAULT_NOVELTY_ALPHA", "evolution.novelty_alpha", "evolution.novelty_alpha", "novelty_alpha"),
    ("DEFAULT_POPULATION_SIZE", "population.size", "population.size", "population_size"),
    ("DEFAULT_TOP_K", "population.top_k", "population.top_k", "top_k"),
    (
        "DEFAULT_MIGRATION_INTERVAL",
        "population.migration_interval",
        "population.migration_interval",
        "migration_interval",
    ),
    (
        "DEFAULT_MIGRANTS_PER_ISLAND",
        "population.migrants_per_island",
        "population.migrants_per_island",
        "migrants_per_island",
    ),
    ("DEFAULT_CHECKPOINT_INTERVAL", "checkpoint.interval", "checkpoint.interval", "checkpoint_interval"),
    ("DEFAULT_CHECKPOINT_DIR", "checkpoint.dir", "checkpoint.dir", "checkpoint_dir"),
    ("DEFAULT_HFC_TIER1_SIZE", "hfc.tier1_size", None, "hfc_tier1_size"),
    ("DEFAULT_HFC_TIER2_SIZE", "hfc.tier2_size", None, "hfc_tier2_size"),
    ("DEFAULT_HFC_TIER3_SIZE", "hfc.tier3_size", None, "hfc_tier3_size"),
    ("DEFAULT_HFC_LAMBDA_CLONES", "hfc.lambda_clones", None, "hfc_lambda_clones"),
]


def _dig(obj, dotted: str):
    for part in dotted.split("."):
        obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
    return obj


@pytest.mark.parametrize("const,yaml_path,pyd_path,dc_field", MATRIX, ids=[m[0] for m in MATRIX])
def test_default_has_one_canonical_value(
    const, yaml_path, pyd_path, dc_field, yaml_defaults, pydantic_defaults, dataclass_defaults
):
    canonical = getattr(C, const)

    assert _dig(yaml_defaults, yaml_path) == canonical, (
        f"config_loader._DEFAULTS[{yaml_path!r}] drifted from constants.{const}"
    )
    if pyd_path is not None:
        assert _dig(pydantic_defaults, pyd_path) == canonical, (
            f"MutaLambdaConfig.{pyd_path} drifted from constants.{const}"
        )
    assert getattr(dataclass_defaults, dc_field) == canonical, (
        f"EvolveConfig.{dc_field} drifted from constants.{const}"
    )


def test_sandbox_defaults_agree(yaml_defaults, pydantic_defaults):
    assert yaml_defaults["sandbox"]["timeout_sec"] == C.DEFAULT_SANDBOX_TIMEOUT_SEC
    assert pydantic_defaults.sandbox.timeout_sec == C.DEFAULT_SANDBOX_TIMEOUT_SEC
    assert yaml_defaults["sandbox"]["max_workers"] == C.DEFAULT_SANDBOX_WORKERS
    assert pydantic_defaults.sandbox.max_workers == C.DEFAULT_SANDBOX_WORKERS


def test_archive_dedupe_default_agrees(pydantic_defaults):
    assert pydantic_defaults.archive.dedupe_similarity == C.DEFAULT_ARCHIVE_DEDUPE_SIMILARITY


def test_canonical_hfc_tiers_are_strictly_decreasing():
    assert C.DEFAULT_HFC_TIER1_SIZE > C.DEFAULT_HFC_TIER2_SIZE > C.DEFAULT_HFC_TIER3_SIZE > 0


# ---------------------------------------------------------------------------
# Bounds that Field() cannot express (cross-section / untyped dict blocks)
# ---------------------------------------------------------------------------


def test_default_config_round_trips_to_evolve_config():
    evolve = MutaLambdaConfig().to_evolve_config()
    assert evolve.num_islands == C.DEFAULT_NUM_ISLANDS
    assert evolve.population_size == C.DEFAULT_POPULATION_SIZE
    assert evolve.top_k == C.DEFAULT_TOP_K


def test_top_k_cannot_exceed_population():
    with pytest.raises(ValidationError, match="top_k must be <="):
        MutaLambdaConfig(population={"size": 4, "top_k": 9})


@pytest.mark.parametrize(
    "hfc",
    [
        {"enabled": True, "tier1_size": 10, "tier2_size": 50, "tier3_size": 5},  # not decreasing
        {"enabled": True, "tier1_size": 50, "tier2_size": 50, "tier3_size": 10},  # equal tiers
        {"enabled": True, "tier1_size": 100, "tier2_size": 50, "tier3_size": 0},  # non-positive
        {"enabled": True, "lambda_clones": 0},  # no clones -> no work
    ],
)
def test_invalid_hfc_tiers_are_rejected(hfc):
    with pytest.raises(ValidationError):
        MutaLambdaConfig(hfc=hfc)


def test_valid_hfc_tiers_accepted():
    cfg = MutaLambdaConfig(hfc={"enabled": True, "tier1_size": 80, "tier2_size": 40, "tier3_size": 8})
    assert cfg.to_evolve_config().hfc_tier1_size == 80


def test_hfc_tiers_not_validated_when_disabled():
    """Disabled HFC must not block a config that merely carries stale keys."""
    cfg = MutaLambdaConfig(hfc={"enabled": False, "tier1_size": 1, "tier2_size": 99})
    assert cfg.to_evolve_config().hfc_enabled is False


@pytest.mark.parametrize("llm", [{"timeout_sec": 0}, {"mutator_timeout_sec": 0}])
def test_non_positive_llm_timeouts_rejected(llm):
    with pytest.raises(ValidationError):
        MutaLambdaConfig(llm=llm)
