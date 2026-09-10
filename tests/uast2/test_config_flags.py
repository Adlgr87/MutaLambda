#!/usr/bin/env python3
"""The feature flag must be visible in every config surface and default to legacy."""

import pytest
import yaml

from config_loader import apply_defaults, load_yaml, validate_config
from muta_ext.uast2.engine import EngineConfig, resolve_engine_config
from muta_lambda.config import EvolveConfig


class TestConfigLoaderSurface:
    def test_defaults_are_legacy(self):
        defaults = apply_defaults({})["uast"]
        assert defaults["engine"] == "legacy"
        assert defaults["shadow"] is False
        assert defaults["shadow_mode"] == "exact"

    def test_yaml_roundtrip(self, tmp_path):
        path = tmp_path / "cfg.yaml"
        path.write_text(
            yaml.safe_dump({"uast": {"engine": "v2", "shadow": True, "shadow_mode": "subset"}}),
            encoding="utf-8",
        )
        raw = load_yaml(path)
        assert raw["uast"]["engine"] == "v2"
        assert validate_config(raw) == []

    @pytest.mark.parametrize(
        "section,message",
        [
            ({"engine": "v9"}, "uast.engine must be 'legacy' or 'v2'"),
            ({"shadow_mode": "loose"}, "uast.shadow_mode must be 'exact' or 'subset'"),
            ({"shadow": "yes-please"}, "uast.shadow must be a boolean"),
            ({"supported_languages": "python"}, "uast.supported_languages must be a list"),
        ],
    )
    def test_validation_rejects_bad_values(self, section, message):
        errors = validate_config({"uast": section})
        assert message in errors


class TestMutaLambdaConfigSurface:
    def test_pydantic_defaults(self):
        from muta_config import UASTSection

        section = UASTSection()
        assert section.engine == "legacy" and section.shadow is False

    def test_invalid_engine_rejected_by_pydantic(self):
        from muta_config import UASTSection

        with pytest.raises(Exception):
            UASTSection(engine="v3")

    def test_flags_flow_into_evolve_config(self, tmp_path):
        from muta_config import MutaLambdaConfig

        config = MutaLambdaConfig()
        assert config.uast.engine == "legacy"
        evolve = config.to_evolve_config()
        assert evolve.uast_engine == "legacy" and evolve.uast_shadow is False

        path = tmp_path / "v2.yaml"
        path.write_text(
            yaml.safe_dump({"uast": {"engine": "v2", "shadow": True, "verify": True}}),
            encoding="utf-8",
        )
        evolve_v2 = MutaLambdaConfig.from_yaml(str(path)).to_evolve_config()
        assert evolve_v2.uast_engine == "v2" and evolve_v2.uast_shadow is True


class TestEvolveConfigSurface:
    def test_defaults(self):
        config = EvolveConfig()
        assert config.uast_engine == "legacy"
        assert config.uast_shadow is False and config.uast_arena is False

    def test_yaml_values_reach_the_dataclass(self, tmp_path):
        path = tmp_path / "evolve.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "uast": {
                        "engine": "v2",
                        "shadow": True,
                        "extended_dialect": True,
                        "supported_languages": ["python"],
                    }
                }
            ),
            encoding="utf-8",
        )
        config = EvolveConfig.from_yaml(str(path))
        assert config.uast_engine == "v2"
        assert config.uast_shadow is True and config.uast_extended_dialect is True

    def test_engine_config_prefers_explicit_section(self):
        values = dict(apply_defaults({})["uast"])
        values.update(engine="v2", shadow=True)
        config = EvolveConfig(uast_engine=values["engine"], uast_shadow=values["shadow"])
        settings = resolve_engine_config(config)
        assert settings.engine == "v2" and settings.shadow is True

    def test_explicit_override_beats_config(self):
        settings = resolve_engine_config({"uast": {"engine": "v2"}}, engine="legacy")
        assert settings == EngineConfig(engine="legacy")
