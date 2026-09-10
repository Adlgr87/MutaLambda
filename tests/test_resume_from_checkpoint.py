"""Tests for checkpoint resume (``--resume-from``) and checkpoint cadence (Fase 0, A5)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evolve import EvolveConfig, run_evolution
from universal_parser import emit_uast_dict

ROOT = Path(__file__).resolve().parent.parent

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


def _latest_checkpoint(checkpoint_dir: Path) -> Path:
    files = sorted(Path(checkpoint_dir).glob("checkpoint_gen*.json"))
    assert files, "expected checkpoints to be written"
    return files[-1]


class TestResume:
    def test_checkpoints_carry_population(self, uast_json: Path, tmp_path: Path):
        cfg = EvolveConfig(
            uast_path=uast_json,
            profile="enterprise",
            generations=3,
            population=5,
            hfc_tiers=False,
            checkpoint_every=1,
            seed=7,
            output_dir=tmp_path,
        )
        result = run_evolution(cfg)
        ckpt = json.loads(_latest_checkpoint(result.checkpoint_dir).read_text(encoding="utf-8"))
        assert ckpt["population"], "checkpoint must persist its population for resume"
        assert ckpt["best_code"].strip()
        assert ckpt["generation"] == 2  # 0-based index of the last completed gen

    def test_resume_inline_continues_evolution(self, uast_json: Path, tmp_path: Path):
        cfg1 = EvolveConfig(
            uast_path=uast_json,
            profile="enterprise",
            generations=5,
            population=6,
            hfc_tiers=False,
            checkpoint_every=1,
            seed=42,
            output_dir=tmp_path / "run1",
        )
        r1 = run_evolution(cfg1)
        assert r1.generations == 5

        ckpt_path = _latest_checkpoint(r1.checkpoint_dir)
        cfg2 = EvolveConfig(
            uast_path=uast_json,
            profile="enterprise",
            generations=9,
            population=6,
            hfc_tiers=False,
            checkpoint_every=1,
            seed=42,
            output_dir=tmp_path / "run2",
            resume_from=str(ckpt_path),
        )
        r2 = run_evolution(cfg2)
        # Resumed at generation 5, ran 5..8 → 4 generations executed.
        assert r2.generations == 4
        assert r2.details["resumed_from_generation"] == 4
        assert r2.details["resumed_at_generation"] == 5
        # The best can only improve when continuing a line.
        assert r2.best_score >= r1.best_score - 1e-9
        assert r2.optimized_code.strip()
        # Checkpointing continued under the new run's dir.
        assert _latest_checkpoint(r2.checkpoint_dir).exists()

    def test_resume_hfc_path(self, uast_json: Path, tmp_path: Path):
        cfg1 = EvolveConfig(
            uast_path=uast_json,
            profile="scientific",
            generations=4,
            population=8,
            hfc_tiers=True,
            checkpoint_every=2,
            seed=42,
            output_dir=tmp_path / "run1",
        )
        r1 = run_evolution(cfg1)
        ckpt_path = _latest_checkpoint(r1.checkpoint_dir)
        data = json.loads(ckpt_path.read_text(encoding="utf-8"))
        assert data["population"], "HFC checkpoint must persist population"

        cfg2 = EvolveConfig(
            uast_path=uast_json,
            profile="scientific",
            generations=8,
            population=8,
            hfc_tiers=True,
            checkpoint_every=2,
            seed=42,
            output_dir=tmp_path / "run2",
            resume_from=str(ckpt_path),
        )
        r2 = run_evolution(cfg2)
        assert r2.generations == 8 - data["generation"] - 1
        assert r2.optimized_code.strip()

    def test_resume_missing_checkpoint_raises(self, uast_json: Path, tmp_path: Path):
        cfg = EvolveConfig(
            uast_path=uast_json,
            profile="enterprise",
            generations=2,
            population=4,
            resume_from=str(tmp_path / "nope.json"),
            output_dir=tmp_path,
        )
        with pytest.raises(FileNotFoundError):
            run_evolution(cfg)

    def test_resume_without_population_rejected(self, uast_json: Path, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"generation": 3, "population": []}), encoding="utf-8")
        cfg = EvolveConfig(
            uast_path=uast_json,
            profile="enterprise",
            generations=5,
            population=4,
            resume_from=str(bad),
            output_dir=tmp_path,
        )
        with pytest.raises(ValueError, match="no population"):
            run_evolution(cfg)


class TestResumeCLI:
    def _uast(self, tmp_path: Path) -> Path:
        from muta_ext.uast.adapters import get_adapter

        uast = get_adapter("python").parse_to_uast(SAMPLE_PYTHON)
        payload = emit_uast_dict(uast, source=SAMPLE_PYTHON)
        p = tmp_path / "uast.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_cli_help_exposes_resume_from(self):
        rc = subprocess.run(
            [sys.executable, "evolve.py", "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0
        assert "--resume-from" in rc.stdout
        assert "--checkpoint-every" in rc.stdout

    def test_cli_checkpoint_every_defaults_to_flag_value(self, uast_json: Path, tmp_path: Path):
        """Without --checkpoint-every the cadence comes from config/optimization.yaml (5)."""
        out1 = tmp_path / "cli1"
        rc = subprocess.run(
            [
                sys.executable,
                "evolve.py",
                "--uast",
                str(uast_json),
                "--profile",
                "enterprise",
                "--generations",
                "6",
                "--population",
                "4",
                "--output-dir",
                str(out1),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0, rc.stderr
        cks = sorted(out1.glob("checkpoints/*/checkpoint_gen*.json"))
        # Cadence 5, 6 generations (0..5) → checkpoint only at gen 4 (gen+1=5).
        assert len(cks) == 1

    def test_cli_end_to_end_resume(self, uast_json: Path, tmp_path: Path):
        out1 = tmp_path / "cli1"
        rc = subprocess.run(
            [
                sys.executable,
                "evolve.py",
                "--uast",
                str(uast_json),
                "--profile",
                "enterprise",
                "--generations",
                "4",
                "--population",
                "4",
                "--checkpoint-every",
                "2",
                "--output-dir",
                str(out1),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0, rc.stderr
        ckpts = sorted(out1.glob("checkpoints/*/checkpoint_gen*.json"))
        assert ckpts, "expected checkpoints from first CLI run"
        ckpt = ckpts[-1]
        data = json.loads(ckpt.read_text(encoding="utf-8"))

        out2 = tmp_path / "cli2"
        rc2 = subprocess.run(
            [
                sys.executable,
                "evolve.py",
                "--uast",
                str(uast_json),
                "--profile",
                "enterprise",
                "--generations",
                "8",
                "--population",
                "4",
                "--checkpoint-every",
                "2",
                "--resume-from",
                str(ckpt),
                "--output-dir",
                str(out2),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc2.returncode == 0, rc2.stderr
        # Ran generations data.generation+1 .. 7.
        expected = 8 - data["generation"] - 1
        report2 = json.loads(next(out2.glob("checkpoints/*/fitness_report.json")).read_text(encoding="utf-8"))
        assert report2["generations"] == expected
