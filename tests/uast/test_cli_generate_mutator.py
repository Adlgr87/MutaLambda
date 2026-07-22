from cli.main import MutaLambdaCLI
from muta_ext.uast.mutators.llm_generator import GeneratedMutatorResult


def test_generate_mutator_dry_run_does_not_write(monkeypatch, tmp_path):
    cli = MutaLambdaCLI()
    monkeypatch.setattr(
        cli,
        "_resolve_llm_mutator_settings",
        lambda: {
            "enabled": True,
            "provider": "openai",
            "mutator_model": "gpt-4o-mini",
            "mutator_temperature": 0.1,
            "mutator_max_tokens": 1400,
            "mutator_timeout_sec": 60.0,
        },
    )
    monkeypatch.setattr(cli, "_generated_mutator_dir", lambda: tmp_path / "generated")
    monkeypatch.setattr(
        "muta_ext.uast.mutators.llm_generator.generate_mutator",
        lambda **_: GeneratedMutatorResult(
            code="def mutate(node, **kwargs):\n    return node\n",
            provider="openai",
            model="gpt-4o-mini",
            system_prompt="s",
            user_prompt="u",
        ),
    )

    ok = cli.generate_mutator("rename x", lang="python", dry_run=True)
    assert ok is True
    assert list((tmp_path / "generated").glob("*.py")) == []


def test_generate_mutator_writes_file_when_enabled(monkeypatch, tmp_path):
    cli = MutaLambdaCLI()
    monkeypatch.setattr(
        cli,
        "_resolve_llm_mutator_settings",
        lambda: {
            "enabled": True,
            "provider": "openai",
            "mutator_model": "gpt-4o-mini",
            "mutator_temperature": 0.1,
            "mutator_max_tokens": 1400,
            "mutator_timeout_sec": 60.0,
        },
    )
    out_dir = tmp_path / "generated"
    monkeypatch.setattr(cli, "_generated_mutator_dir", lambda: out_dir)
    monkeypatch.setattr(
        "muta_ext.uast.mutators.llm_generator.generate_mutator",
        lambda **_: GeneratedMutatorResult(
            code="def mutate(node, **kwargs):\n    return node\n",
            provider="openai",
            model="gpt-4o-mini",
            system_prompt="s",
            user_prompt="u",
        ),
    )

    ok = cli.generate_mutator("rename x", lang="python", name="rename_x", dry_run=False)
    assert ok is True
    out_file = out_dir / "rename_x.py"
    assert out_file.exists()
    assert "def mutate" in out_file.read_text(encoding="utf-8")


def test_generate_mutator_feature_flag_off(monkeypatch):
    cli = MutaLambdaCLI()
    monkeypatch.setattr(cli, "_resolve_llm_mutator_settings", lambda: {"enabled": False})

    ok = cli.generate_mutator("rename x", lang="python", dry_run=True)
    assert ok is False

