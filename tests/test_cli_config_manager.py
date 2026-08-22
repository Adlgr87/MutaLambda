"""Tests for cli.config_manager (templates, validation, diagnostics, fixes)."""

import json

import pytest
import yaml

from cli.config_manager import ConfigManager


@pytest.fixture
def manager() -> ConfigManager:
    return ConfigManager()


@pytest.mark.root
class TestLoad:
    def test_load_yaml(self, manager, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump({"evolution": {"generations": 5}}), encoding="utf-8")
        assert manager.load(str(path)) == {"evolution": {"generations": 5}}

    def test_load_json(self, manager, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"evolution": {"generations": 7}}), encoding="utf-8")
        assert manager.load(str(path)) == {"evolution": {"generations": 7}}

    def test_load_unknown_suffix_falls_back_to_yaml(self, manager, tmp_path):
        path = tmp_path / "config.conf"
        path.write_text("evolution:\n  generations: 9\n", encoding="utf-8")
        assert manager.load(str(path)) == {"evolution": {"generations": 9}}

    def test_load_unknown_suffix_accepts_json(self, manager, tmp_path):
        path = tmp_path / "config.conf"
        path.write_text('{"evolution": {"generations": 11}}', encoding="utf-8")
        assert manager.load(str(path)) == {"evolution": {"generations": 11}}

    def test_missing_file_returns_empty_dict(self, manager, tmp_path):
        assert manager.load(str(tmp_path / "nope.yaml")) == {}

    def test_malformed_yaml_returns_empty_dict(self, manager, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("evolution: [unclosed\n", encoding="utf-8")
        assert manager.load(str(path)) == {}


@pytest.mark.root
class TestSaveAndRoundtrip:
    def test_save_yaml_roundtrip(self, manager, tmp_path):
        config = {"evolution": {"generations": 3, "num_islands": 2}}
        path = tmp_path / "out" / "config.yaml"
        manager.save(config, str(path))
        assert path.exists()
        assert manager.load(str(path)) == config

    def test_save_json_format(self, manager, tmp_path):
        config = {"evolution": {"generations": 3}}
        path = tmp_path / "config.json"
        manager.save(config, str(path), format="json")
        assert json.loads(path.read_text(encoding="utf-8")) == config

    def test_save_creates_parent_directories(self, manager, tmp_path):
        path = tmp_path / "a" / "b" / "c.yaml"
        manager.save({"evolution": {}}, str(path))
        assert path.exists()

    def test_save_failure_is_swallowed(self, manager, tmp_path):
        directory = tmp_path / "dir"
        directory.mkdir()
        # Writing over a directory raises; the manager reports instead of raising.
        manager.save({"evolution": {}}, str(directory))
        assert directory.is_dir()


@pytest.mark.root
class TestTemplates:
    @pytest.mark.parametrize(
        "name", ["basic", "advanced", "research", "quick", "production"]
    )
    def test_every_template_is_valid(self, manager, name):
        is_valid, errors = manager.validate(manager.templates[name])
        assert is_valid, errors

    @pytest.mark.parametrize(
        "name", ["basic", "advanced", "research", "quick", "production"]
    )
    def test_create_from_template(self, manager, name, tmp_path):
        path = tmp_path / f"{name}.yaml"
        assert manager.create_from_template(name, str(path)) is True
        assert manager.load(str(path)) == manager.templates[name]

    def test_unknown_template_is_rejected(self, manager, tmp_path):
        path = tmp_path / "x.yaml"
        assert manager.create_from_template("does-not-exist", str(path)) is False
        assert not path.exists()

    def test_get_default_returns_basic_copy(self, manager):
        default = manager.get_default()
        assert default == manager.templates["basic"]
        default["evolution"] = "clobbered"
        assert manager.templates["basic"]["evolution"] != "clobbered"


@pytest.mark.root
class TestValidate:
    def test_minimal_valid_config(self, manager):
        is_valid, errors = manager.validate({"evolution": {"generations": 10}})
        assert (is_valid, errors) == (True, [])

    def test_missing_evolution_section(self, manager):
        is_valid, errors = manager.validate({})
        assert is_valid is False
        assert "Missing required section: evolution" in errors

    @pytest.mark.parametrize(
        "evolution,expected",
        [
            ({"generations": 0}, "generations must be >= 1"),
            ({"num_islands": 0}, "num_islands must be >= 1"),
            ({"population_size": 1}, "population_size must be >= 2"),
        ],
    )
    def test_evolution_bounds(self, manager, evolution, expected):
        is_valid, errors = manager.validate({"evolution": evolution})
        assert is_valid is False
        assert expected in errors

    def test_invalid_topology(self, manager):
        is_valid, errors = manager.validate(
            {"evolution": {}, "migration": {"topology": "mesh"}}
        )
        assert is_valid is False
        assert any("topology must be one of" in e for e in errors)

    @pytest.mark.parametrize("rate", [-0.1, 1.5])
    def test_mutation_rate_bounds(self, manager, rate):
        is_valid, errors = manager.validate({"evolution": {}, "mutation": {"rate": rate}})
        assert is_valid is False
        assert "mutation rate must be between 0 and 1" in errors

    def test_crossover_rate_bounds(self, manager):
        is_valid, errors = manager.validate(
            {"evolution": {}, "mutation": {"crossover_rate": 2.0}}
        )
        assert is_valid is False
        assert "crossover_rate must be between 0 and 1" in errors

    def test_multiple_errors_are_collected(self, manager):
        is_valid, errors = manager.validate(
            {
                "evolution": {"generations": 0, "num_islands": 0},
                "mutation": {"rate": 5},
            }
        )
        assert is_valid is False
        assert len(errors) == 3


@pytest.mark.root
class TestDiagnostic:
    def _codes(self, manager, config):
        return {issue["code"] for issue in manager.diagnostic(config)}

    def test_healthy_config_has_no_issues(self, manager):
        config = {
            "sandbox": {"timeout_sec": 30.0},
            "evolution": {"population_size": 8, "generations": 100, "num_islands": 4},
            "migration": {"topology": "ring"},
            "checkpoint": {"interval": 10},
        }
        assert manager.diagnostic(config) == []

    def test_low_sandbox_timeout_flagged(self, manager):
        issues = manager.diagnostic({"sandbox": {"timeout_sec": 5.0}, "evolution": {"generations": 50}})
        codes = {i["code"] for i in issues}
        assert "sandbox.timeout" in codes

    def test_low_timeout_suggests_scientific_value(self, manager):
        (issue,) = [
            i
            for i in manager.diagnostic({"sandbox": {"timeout_sec": 5.0}, "evolution": {"generations": 50}})
            if i["code"] == "sandbox.timeout"
        ]
        assert issue["fix_value"] == 60.0
        assert issue["severity"] == "warning"

    def test_moderate_timeout_suggests_production_value(self, manager):
        (issue,) = [
            i
            for i in manager.diagnostic({"sandbox": {"timeout_sec": 10.0}, "evolution": {"generations": 50}})
            if i["code"] == "sandbox.timeout"
        ]
        assert issue["fix_value"] == 30.0

    def test_small_population_and_few_generations_flagged(self, manager):
        codes = self._codes(
            manager,
            {"sandbox": {"timeout_sec": 30.0}, "evolution": {"population_size": 2, "generations": 5}},
        )
        assert {"evolution.population", "evolution.generations"} <= codes

    def test_ring_topology_with_many_islands_flagged(self, manager):
        codes = self._codes(
            manager,
            {
                "sandbox": {"timeout_sec": 30.0},
                "evolution": {"num_islands": 12, "generations": 100, "population_size": 8},
                "migration": {"topology": "ring"},
            },
        )
        assert "migration.topology" in codes

    def test_high_checkpoint_interval_flagged(self, manager):
        codes = self._codes(
            manager,
            {
                "sandbox": {"timeout_sec": 30.0},
                "evolution": {"generations": 100, "population_size": 8},
                "checkpoint": {"interval": 200},
            },
        )
        assert "checkpoint.interval" in codes

    def test_null_sections_are_tolerated(self, manager):
        issues = manager.diagnostic(
            {"sandbox": None, "evolution": None, "migration": None, "checkpoint": None}
        )
        assert {i["code"] for i in issues} == {"sandbox.timeout"}

    def test_diagnostics_of_default_templates(self, manager):
        # The production preset is tuned and should raise no warnings.
        warnings = [
            i for i in manager.diagnostic(manager.templates["production"])
            if i["severity"] == "warning"
        ]
        assert warnings == []


@pytest.mark.root
class TestApplyFix:
    def test_fix_is_applied_to_existing_section(self, manager):
        config = {"sandbox": {"timeout_sec": 5.0}, "evolution": {"generations": 50}}
        (issue,) = [i for i in manager.diagnostic(config) if i["code"] == "sandbox.timeout"]
        assert manager.apply_fix(config, issue) is True
        assert config["sandbox"]["timeout_sec"] == issue["fix_value"]

    def test_fix_creates_missing_nested_section(self, manager):
        config = {}
        issue = {"fix_key": ("checkpoint", "interval"), "fix_value": 10}
        assert manager.apply_fix(config, issue) is True
        assert config == {"checkpoint": {"interval": 10}}

    def test_fix_replaces_non_dict_intermediate(self, manager):
        config = {"migration": "ring"}
        issue = {"fix_key": ("migration", "topology"), "fix_value": "fully_connected"}
        assert manager.apply_fix(config, issue) is True
        assert config == {"migration": {"topology": "fully_connected"}}

    def test_issue_without_fix_returns_false(self, manager):
        config = {"evolution": {"generations": 5}}
        issue = {"code": "evolution.generations", "message": "low"}
        assert manager.apply_fix(config, issue) is False
        assert config == {"evolution": {"generations": 5}}

    def test_applying_all_fixes_clears_fixable_issues(self, manager):
        config = {"sandbox": {"timeout_sec": 1.0}, "evolution": {"population_size": 2, "generations": 100}}
        for issue in manager.diagnostic(config):
            manager.apply_fix(config, issue)
        remaining = {i["code"] for i in manager.diagnostic(config)}
        assert remaining == set()


@pytest.mark.root
class TestMergeConfigs:
    def test_override_wins_for_scalars(self, manager):
        merged = manager.merge_configs({"a": 1, "b": 2}, {"b": 3})
        assert merged == {"a": 1, "b": 3}

    def test_nested_dicts_are_deep_merged(self, manager):
        base = {"evolution": {"generations": 50, "num_islands": 4}}
        override = {"evolution": {"generations": 100}}
        assert manager.merge_configs(base, override) == {
            "evolution": {"generations": 100, "num_islands": 4}
        }

    def test_base_is_not_mutated(self, manager):
        base = {"evolution": {"generations": 50}}
        manager.merge_configs(base, {"evolution": {"generations": 100}})
        assert base == {"evolution": {"generations": 50}}

    def test_dict_replaces_scalar(self, manager):
        assert manager.merge_configs({"a": 1}, {"a": {"b": 2}}) == {"a": {"b": 2}}


@pytest.mark.root
class TestDisplayHelpers:
    """Display helpers only render to the console; assert they stay exception-free."""

    def test_display_summary_handles_scalars_and_dicts(self, manager):
        manager.display_summary({"evolution": {"generations": 5}, "name": "run"})

    @pytest.mark.parametrize("fmt", ["yaml", "json", "table"])
    def test_display_full_formats(self, manager, fmt):
        manager.display_full({"evolution": {"generations": 5}}, format=fmt)

    def test_display_summary_from_file(self, manager, tmp_path):
        path = tmp_path / "config.yaml"
        manager.save({"evolution": {"generations": 5}}, str(path))
        manager.display_summary_from_file(str(path))

    def test_display_summary_from_missing_file_is_noop(self, manager, tmp_path):
        manager.display_summary_from_file(str(tmp_path / "missing.yaml"))
