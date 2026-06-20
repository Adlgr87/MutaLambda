"""
Tests for config_loader (YAML validation) and checkpoint_manager.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config_loader import (
    validate_config,
    apply_defaults,
    load_yaml,
    _get_nested,
)
from muta_lambda import EvolveConfig


class TestConfigValidation:
    """Unit tests for YAML schema validation."""

    def test_valid_minimal_config(self):
        cfg = apply_defaults({
            "evolution": {
                "num_islands": 4,
                "generations": 50,
                "topology": "ring",
            },
            "population": {
                "size": 8,
                "top_k": 3,
                "migration_interval": 10,
            },
            "sandbox": {
                "timeout_sec": 10.0,
            },
        })
        errors = validate_config(cfg)
        assert errors == []

    def test_missing_section(self):
        cfg = {"evolution": {"num_islands": 4}}
        errors = validate_config(cfg)
        assert any("population" in e for e in errors)
        assert any("sandbox" in e for e in errors)

    def test_invalid_topology(self):
        cfg = apply_defaults({
            "evolution": {"num_islands": 2, "generations": 10, "topology": "star"},
            "population": {"size": 5, "top_k": 2, "migration_interval": 5},
            "sandbox": {"timeout_sec": 5.0},
        })
        errors = validate_config(cfg)
        assert any("topology" in e for e in errors)

    def test_top_k_exceeds_population(self):
        cfg = apply_defaults({
            "evolution": {"num_islands": 2, "generations": 10, "topology": "ring"},
            "population": {"size": 4, "top_k": 10, "migration_interval": 5},
            "sandbox": {"timeout_sec": 5.0},
        })
        errors = validate_config(cfg)
        assert any("top_k" in e.lower() for e in errors)

    def test_novelty_alpha_out_of_bounds(self):
        cfg = apply_defaults({
            "evolution": {
                "num_islands": 2,
                "generations": 10,
                "topology": "ring",
                "novelty_alpha": 2.5,
            },
            "population": {"size": 5, "top_k": 2, "migration_interval": 5},
            "sandbox": {"timeout_sec": 5.0},
        })
        errors = validate_config(cfg)
        assert any("novelty_alpha" in e for e in errors)

    def test_apply_defaults_fills_missing(self):
        cfg = apply_defaults({
            "evolution": {"num_islands": 2, "generations": 10, "topology": "ring"},
            "population": {"size": 5, "top_k": 2, "migration_interval": 5},
            "sandbox": {"timeout_sec": 5.0},
        })
        assert _get_nested(cfg, "checkpoint.interval") == 10
        assert _get_nested(cfg, "archive.enabled") is True
        assert _get_nested(cfg, "logging.level") == "INFO"

    def test_defaults_do_not_overwrite_explicit(self):
        cfg = apply_defaults({
            "evolution": {"num_islands": 2, "generations": 10, "topology": "ring"},
            "population": {"size": 5, "top_k": 2, "migration_interval": 5},
            "sandbox": {"timeout_sec": 5.0},
            "checkpoint": {"interval": 5},
        })
        assert _get_nested(cfg, "checkpoint.interval") == 5

    def test_get_nested_deep_path(self):
        cfg = {"a": {"b": {"c": 42}}}
        assert _get_nested(cfg, "a.b.c") == 42
        assert _get_nested(cfg, "a.b.x") is None
        assert _get_nested(cfg, "x.y.z", default=0) == 0


class TestEvolveConfigFromYaml:
    """Integration: YAML → EvolveConfig."""

    def test_from_yaml_creates_valid_config(self, tmp_path):
        yaml_content = """
evolution:
  num_islands: 4
  generations: 30
  topology: mesh
  early_stop_patience: 10
  novelty_alpha: 0.2
population:
  size: 10
  top_k: 4
  migration_interval: 8
  migrants_per_island: 3
sandbox:
  timeout_sec: 15.0
  max_workers: 6
archive:
  enabled: true
  max_size: 5000
prompt_evolution:
  enabled: true
  pop_size: 8
  elite_frac: 0.6
checkpoint:
  interval: 5
  dir: custom_ckpts
logging:
  level: DEBUG
llm:
  backend: openai
  model: gpt-test
  timeout_sec: 12.0
  temperature: 0.4
reproducibility:
  seed: 42
hfc:
  enabled: true
  lambda_clones: 4
  tier1_size: 20
  tier2_size: 10
  tier3_size: 3
"""
        yaml_path = tmp_path / "test_config.yaml"
        yaml_path.write_text(yaml_content)

        # Only test if PyYAML is available
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")

        config = EvolveConfig.from_yaml(str(yaml_path))
        assert config.num_islands == 4
        assert config.generations == 30
        assert config.topology == "mesh"
        assert config.novelty_alpha == 0.2
        assert config.population_size == 10
        assert config.top_k == 4
        assert config.migration_interval == 8
        assert config.migrants_per_island == 3
        assert config.early_stop_patience == 10
        assert config.checkpoint_dir == "custom_ckpts"
        assert config.checkpoint_interval == 5
        assert config.archive_solutions is True
        assert config.prompt_evolution is True
        assert config.llm_backend == "openai"
        assert config.llm_model == "gpt-test"
        assert config.llm_timeout_sec == 12.0
        assert config.llm_temperature == 0.4
        assert config.prompt_pop_size == 8
        assert config.prompt_elite_frac == 0.6
        assert config.hfc_enabled is True
        assert config.hfc_lambda_clones == 4
        assert config.hfc_tier1_size == 20
        assert config.hfc_tier2_size == 10
        assert config.hfc_tier3_size == 3
 
    def test_llm_validation(self):
        cfg = apply_defaults({
            "evolution": {"num_islands": 2, "generations": 10, "topology": "ring"},
            "population": {"size": 5, "top_k": 2, "migration_interval": 5},
            "sandbox": {"timeout_sec": 5.0},
            "llm": {
                "backend": "not-a-provider",
                "timeout_sec": 0,
                "temperature": 3.0,
            },
            "prompt_evolution": {
                "pop_size": 0,
                "elite_frac": 1.5,
            },
        })
        errors = validate_config(cfg)
        assert any("llm.backend" in e for e in errors)
        assert any("llm.timeout_sec" in e for e in errors)
        assert any("llm.temperature" in e for e in errors)
        assert any("prompt_evolution.pop_size" in e for e in errors)
        assert any("prompt_evolution.elite_frac" in e for e in errors)

    def test_hfc_validation(self):
        cfg = apply_defaults({
            "evolution": {"num_islands": 2, "generations": 10, "topology": "ring"},
            "population": {"size": 5, "top_k": 2, "migration_interval": 5},
            "sandbox": {"timeout_sec": 5.0},
            "hfc": {
                "lambda_clones": -1,
                "tier1_size": 0,
                "promotion_correctness": 1.5,
            },
        })
        errors = validate_config(cfg)
        assert any("hfc.lambda_clones" in e for e in errors)
        assert any("hfc.tier1_size" in e for e in errors)
        assert any("hfc.promotion_correctness" in e for e in errors)


class TestCheckpointBasic:
    """Basic checkpoint structure (without agent instantiation)."""

    def test_serialise_deserialise(self):
        from checkpoint_manager import Checkpoint, _serialise_checkpoint

        cp = Checkpoint(
            generation=5,
            config_hash="abc123",
            git_commit="deadbeef",
            best_score=0.95,
            best_code="def f(): pass",
        )
        data = _serialise_checkpoint(cp)
        assert data["generation"] == 5
        assert data["config_hash"] == "abc123"
        assert data["best_score"] == 0.95
