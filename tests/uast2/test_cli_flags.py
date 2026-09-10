#!/usr/bin/env python3
"""CLI surface: feature flags on ``run`` and the ``uast2 check`` shadow command."""

import pytest

click_testing = pytest.importorskip("click.testing")

from click.testing import CliRunner  # noqa: E402

import mutalambda_cli  # noqa: E402


@pytest.fixture()
def runner():
    return CliRunner()


class TestRunFlags:
    def test_run_help_exposes_the_uast_flags(self, runner):
        result = runner.invoke(mutalambda_cli.cli, ["run", "--help"])
        assert result.exit_code == 0
        for flag in (
            "--uast-engine",
            "--uast-shadow",
            "--uast-verify",
            "--uast-arena",
            "--uast-extended",
            "--uast-strict",
        ):
            assert flag in result.output

    def test_uast_overrides_are_merged_into_the_config(self, monkeypatch):
        """The CLI flags reach the ``uast`` section without touching anything else."""
        from cli.main import MutaLambdaCLI

        instance = MutaLambdaCLI()
        instance.config_manager.load = lambda path: {  # type: ignore[assignment]
            "uast": {"engine": "legacy", "shadow": False},
            "evolution": {"generations": 1},
        }
        captured = {}

        def fake_prepare(**kwargs):
            captured["config"] = instance.current_config
            return False  # stop right after config merging

        instance._prepare_target = fake_prepare  # type: ignore[assignment]
        assert (
            instance.run_evolution(
                config_path="ignored.yaml",
                uast_overrides={"engine": "v2", "shadow": True},
            )
            is False
        )
        assert captured["config"]["uast"] == {
            "engine": "v2",
            "shadow": True,  # merged flags win
        }
        assert captured["config"]["evolution"] == {"generations": 1}

    def test_none_overrides_leave_the_section_untouched(self):
        from cli.main import MutaLambdaCLI

        instance = MutaLambdaCLI()
        instance.config_manager.load = lambda path: {"uast": {"engine": "legacy"}}  # type: ignore[assignment]
        captured = {}

        def fake_prepare(**kwargs):
            captured["config"] = instance.current_config
            return False

        instance._prepare_target = fake_prepare  # type: ignore[assignment]
        instance.run_evolution(
            config_path="ignored.yaml",
            uast_overrides={"engine": None, "shadow": None, "arena": None},
        )
        assert captured["config"]["uast"] == {"engine": "legacy"}


class TestUast2CheckCommand:
    def test_check_runs_over_examples(self, runner):
        result = runner.invoke(mutalambda_cli.cli, ["uast2", "check", "examples"])
        assert result.exit_code == 0, result.output
        assert "UAST v2 shadow" in result.output
        assert "DIFF" not in result.output

    def test_check_supports_json_output(self, runner):
        result = runner.invoke(
            mutalambda_cli.cli, ["uast2", "check", "examples", "--json-output"]
        )
        assert result.exit_code == 0, result.output
        assert '"mismatches": 0' in result.output.replace("'", '"')

    def test_check_without_targets_fails_cleanly(self, runner, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(mutalambda_cli.cli, ["uast2", "check", str(empty)])
        assert result.exit_code == 1

    def test_check_reports_mismatches_with_exit_code_2(self, runner, tmp_path):
        """A syntax-error file is reported (engine error), never a crash."""
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n", encoding="utf-8")
        result = runner.invoke(mutalambda_cli.cli, ["uast2", "check", str(bad)])
        assert result.exit_code == 2
        assert "ERR" in result.output


class TestUast2ParseAndMutate:
    """The engine must be usable end-to-end straight from the CLI."""

    SOURCE = (
        "def f(n):\n"
        "    total = 0\n"
        "    for i in range(0, n):\n"
        "        total = total + 2 * 3\n"
        "    return total\n"
    )

    @pytest.fixture()
    def target(self, tmp_path):
        path = tmp_path / "demo.py"
        path.write_text(self.SOURCE, encoding="utf-8")
        return path

    def test_parse_renders_tree_and_hash(self, runner, target):
        result = runner.invoke(mutalambda_cli.cli, ["uast2", "parse", str(target)])
        assert result.exit_code == 0, result.output
        assert "Function(" in result.output
        assert "canonical_hash=" in result.output

    def test_parse_json_is_structured(self, runner, target):
        result = runner.invoke(
            mutalambda_cli.cli, ["uast2", "parse", str(target), "--json-output"]
        )
        assert result.exit_code == 0, result.output
        assert '"nodes"' in result.output and '"tree"' in result.output
        import json

        payload = json.loads(result.output)
        assert payload["nodes"] > 0
        assert payload["canonical_hash"]

    def test_parse_reports_syntax_errors_without_crashing(self, runner, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def broken(:\n", encoding="utf-8")
        result = runner.invoke(mutalambda_cli.cli, ["uast2", "parse", str(bad)])
        assert result.exit_code == 1
        assert "Error de parseo" in result.output

    def test_mutate_writes_valid_python(self, runner, target, tmp_path):
        import ast

        out = tmp_path / "mutated.py"
        result = runner.invoke(
            mutalambda_cli.cli,
            ["uast2", "mutate", str(target), "--seed", "42", "--output", str(out)],
        )
        assert result.exit_code == 0, result.output
        mutated = out.read_text(encoding="utf-8")
        ast.parse(mutated)
        assert mutated != self.SOURCE  # the nanopasses actually changed something

    def test_mutate_stdout_is_pure_code(self, runner, target):
        import ast

        result = runner.invoke(
            mutalambda_cli.cli, ["uast2", "mutate", str(target), "--seed", "7", "--json"]
        )
        assert result.exit_code == 0, result.output
        import json

        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert sum(payload["mutations"].values()) >= 1
        ast.parse(payload["mutated_source"])

    def test_mutate_default_verification_does_not_roll_back(self, runner, target):
        """Regression: math fidelity must not veto intentional mutations."""
        result = runner.invoke(
            mutalambda_cli.cli, ["uast2", "mutate", str(target), "--seed", "42", "--json"]
        )
        import json

        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["rolled_back"] == []
