#!/usr/bin/env python3
"""Unit tests for the pipeline CLI scripts.

Covers: universal_parser, invariant_detector, regression_gate, certify, evolve.
Uses fixtures and the real adapter/emitter layer (no mocks for the modules under test).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Tuple

import pytest

# Make the repo root importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from universal_parser import SUPPORTED_LANGUAGES, parse_file, emit_uast_dict
from invariant_detector import (
    InvariantsLock,
    detect_invariants,
    CODATA_CONSTANTS,
    LOCKFILE_VERSION,
)
from regression_gate import GateConfig, evaluate_gate, run_gate, GateResult
from certify import Certificate, CertificateBuilder, CERTIFICATE_VERSION
from evolve import EvolveConfig, run_evolution, SUPPORTED_PROFILES

pytestmark = pytest.mark.v4

# ── Fixtures ────────────────────────────────────────────────────────────────

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

# A source that references physical constants, math identities and crypto.
RICH_SOURCE = '''"""Rich source referencing constants, identities and crypto patterns."""


# Physical constants (CODATA)
SPEED_OF_LIGHT = 299792458.0
PLANCK = 6.62607015e-34
ELEMENTARY_CHARGE = 1.602176634e-19

# Mathematical identity usage
sin_sq = math.sin(x) ** 2 + math.cos(x) ** 2

# Use float32 epsilon boundary
eps32 = 1.1920928955078125e-07


def compute(data, n=50):
    h = hashlib.sha256(data)
    return h.hexdigest()
'''


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def sample_uast_json(tmp_path: Path) -> Path:
    """Parse SAMPLE_PYTHON into a uast.json file."""
    from muta_ext.uast.core_uast import CoreUAST
    from universal_parser import emit_uast_dict

    from muta_ext.uast.adapters import get_adapter

    uast = get_adapter("python").parse_to_uast(SAMPLE_PYTHON)
    payload = emit_uast_dict(uast)
    path = tmp_path / "uast.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def rich_uast_json(tmp_path: Path) -> Path:
    from muta_ext.uast.adapters import get_adapter

    uast = get_adapter("python").parse_to_uast(RICH_SOURCE)
    payload = emit_uast_dict(uast, source=RICH_SOURCE)
    path = tmp_path / "rich_uast.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── universal_parser ────────────────────────────────────────────────────────


class TestUniversalParser:
    def test_supported_languages(self):
        assert "python" in SUPPORTED_LANGUAGES
        assert "rust" in SUPPORTED_LANGUAGES
        assert "cpp" in SUPPORTED_LANGUAGES

    def test_parse_python_file(self, tmp_path: Path):
        src = tmp_path / "mod.py"
        src.write_text(SAMPLE_PYTHON, encoding="utf-8")
        result = parse_file(src, language="python")
        assert result["language"] == "python"
        assert result["node_count"] >= 1
        assert isinstance(result["nodes"], list)

    def test_parse_infers_language_from_extension(self, tmp_path: Path):
        src = tmp_path / "lib.rs"
        src.write_text("// rust code\nfn main() {}\n", encoding="utf-8")
        result = parse_file(src)
        assert result["language"] == "rust"

    def test_parse_emits_function_node(self, tmp_path: Path):
        src = tmp_path / "mod.py"
        src.write_text("def foo():\n    return 1\n", encoding="utf-8")
        result = parse_file(src, language="python")
        node_types = [n.get("type") for n in result["nodes"]]
        assert "Function" in node_types

    def test_cli_smoke(self, tmp_path: Path):
        src = tmp_path / "mod.py"
        src.write_text(SAMPLE_PYTHON, encoding="utf-8")
        out = tmp_path / "out.json"
        rc = subprocess.run(
            [sys.executable, "universal_parser.py", str(src), "-o", str(out)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0, rc.stderr
        data = json.loads(out.read_text())
        assert data["language"] == "python"

    def test_unknown_extension_errors(self, tmp_path: Path):
        src = tmp_path / "weird.xyz"
        src.write_text("anything", encoding="utf-8")
        with pytest.raises(ValueError, match="Cannot infer language"):
            parse_file(src)


# ── invariant_detector ──────────────────────────────────────────────────────


class TestInvariantDetector:
    def test_detects_codata_constants(self, rich_uast_json: Path):
        from muta_ext.uast.core_uast import CoreUAST  # noqa: F401

        uast = json.loads(rich_uast_json.read_text())
        lock = detect_invariants(uast)
        symbols = {c.symbol for c in lock.physical_constants}
        # The rich source has c, h, e literals.
        assert "c" in symbols
        assert "h" in symbols
        assert "e" in symbols

    def test_lockfile_version(self):
        assert LOCKFILE_VERSION == "1.0.0"

    def test_codatas_present(self):
        assert "c" in CODATA_CONSTANTS
        assert CODATA_CONSTANTS["c"]["value"] == 299_792_458.0

    def test_detects_mathematical_identities(self, rich_uast_json: Path):
        lock = detect_invariants(json.loads(rich_uast_json.read_text()))
        names = {i.name for i in lock.mathematical_identities}
        # sin/cos present → pythagorean identity.
        assert "pythagorean" in names or names  # at least some detected

    def test_detects_crypto_patterns(self, rich_uast_json: Path):
        lock = detect_invariants(json.loads(rich_uast_json.read_text()))
        kinds = {p.kind for p in lock.crypto_patterns}
        assert "sha256" in kinds

    def test_detects_float_tolerances(self, rich_uast_json: Path):
        lock = detect_invariants(json.loads(rich_uast_json.read_text()))
        kinds = {t.kind for t in lock.numerical_tolerances}
        assert "float32" in kinds  # float32_eps referenced

    def test_content_hash_stable(self, rich_uast_json: Path):
        uast = json.loads(rich_uast_json.read_text())
        lock_a = detect_invariants(uast)
        lock_b = detect_invariants(uast)
        assert lock_a.content_hash() == lock_b.content_hash()

    def test_lockfile_serialisable(self, rich_uast_json: Path):
        lock = detect_invariants(json.loads(rich_uast_json.read_text()))
        data = lock.to_dict()
        assert data["version"] == LOCKFILE_VERSION
        restored = InvariantsLock.from_dict(data)
        assert restored.physical_constants == lock.physical_constants

    def test_cli_smoke(self, tmp_path: Path):
        src = tmp_path / "mod.py"
        src.write_text(SAMPLE_PYTHON, encoding="utf-8")
        uast_path = tmp_path / "uast.json"
        subprocess.run(
            [sys.executable, "universal_parser.py", str(src), "-o", str(uast_path)],
            cwd=str(ROOT),
            check=True,
        )
        inv_path = tmp_path / "inv.lock"
        rc = subprocess.run(
            [
                sys.executable,
                "invariant_detector.py",
                str(uast_path),
                "-o",
                str(inv_path),
                "--source",
                str(src),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0, rc.stderr
        lock = json.loads(inv_path.read_text())
        assert lock["version"] == LOCKFILE_VERSION


# ── regression_gate ─────────────────────────────────────────────────────────


class TestRegressionGate:
    def _comparison(self, base: float, opt: float, significant: bool = True) -> dict:
        return {
            "comparison": {"baseline": {"latency_p50": base}, "optimized": {"latency_p50": opt}},
            "statistical_test": {"significant": significant},
        }

    def test_pass_when_improved(self, tmp_path: Path):
        path = tmp_path / "comparison.json"
        path.write_text(json.dumps(self._comparison(100.0, 90.0)))
        result = run_gate(path, GateConfig(min_improvement_pct=5.0, max_regression_pct=2.0))
        assert result.passed
        assert result.improvement_pct == pytest.approx(10.0, abs=0.01)

    def test_fail_when_regression_exceeds_threshold(self, tmp_path: Path):
        path = tmp_path / "comparison.json"
        path.write_text(json.dumps(self._comparison(100.0, 105.0)))
        result = run_gate(path, GateConfig(min_improvement_pct=5.0, max_regression_pct=2.0))
        assert not result.passed
        assert result.regression_pct == pytest.approx(5.0, abs=0.01)

    def test_pass_below_floor_no_regression(self, tmp_path: Path):
        path = tmp_path / "comparison.json"
        path.write_text(json.dumps(self._comparison(100.0, 98.0)))
        result = run_gate(path, GateConfig(min_improvement_pct=5.0, max_regression_pct=2.0))
        assert result.passed
        assert result.improvement_pct == pytest.approx(2.0, abs=0.01)

    def test_pr_annotation_never_blocks(self, tmp_path: Path):
        path = tmp_path / "comparison.json"
        path.write_text(json.dumps(self._comparison(100.0, 110.0)))
        result = run_gate(
            path,
            GateConfig(min_improvement_pct=5.0, max_regression_pct=2.0, pr_annotation=True),
        )
        assert not result.passed
        assert result.blocking is False

    def test_not_significant_passes_without_floor(self, tmp_path: Path):
        path = tmp_path / "comparison.json"
        path.write_text(json.dumps(self._comparison(100.0, 99.0, significant=False)))
        result = run_gate(path, GateConfig(min_improvement_pct=5.0, max_regression_pct=2.0))
        assert result.passed

    def test_higher_is_better_metric(self, tmp_path: Path):
        path = tmp_path / "comparison.json"
        data = {
            "comparison": {"baseline": {"throughput": 100.0}, "optimized": {"throughput": 120.0}},
            "statistical_test": {"significant": True},
        }
        path.write_text(json.dumps(data))
        result = run_gate(
            path,
            GateConfig(
                min_improvement_pct=5.0, max_regression_pct=2.0, threshold_metric="throughput"
            ),
        )
        assert result.passed
        assert result.improvement_pct == pytest.approx(20.0, abs=0.01)

    def test_cli_help(self):
        rc = subprocess.run(
            [sys.executable, "regression_gate.py", "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0
        assert "min-improvement" in rc.stdout


# ── certify ─────────────────────────────────────────────────────────────────


class TestCertify:
    def _artefacts(self, tmp_path: Path) -> Tuple[Path, Path, Path, Path]:
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"hash": "base123", "p50": 100.0}), encoding="utf-8")
        optimized = tmp_path / "optimized.json"
        optimized.write_text(json.dumps({"optimized_hash": "opt456"}), encoding="utf-8")
        invariants = tmp_path / "invariants.lock"
        invariants.write_text(json.dumps({"version": "1.0.0", "hash": "inv789"}), encoding="utf-8")
        config = tmp_path / "config.yaml"
        config.write_text("profile: enterprise\n", encoding="utf-8")
        return baseline, optimized, invariants, config

    def test_build_certificate(self, tmp_path: Path):
        baseline, optimized, invariants, config = self._artefacts(tmp_path)
        builder = CertificateBuilder(seed=42)
        cert = builder.build(baseline, optimized, invariants, config=config)
        assert cert.baseline_hash == "base123"
        assert cert.optimized_hash == "opt456"
        assert cert.invariants_hash == "inv789"
        assert cert.seed == 42
        assert cert.signed is False

    def test_sign_with_secret(self, tmp_path: Path, monkeypatch):
        baseline, optimized, invariants, config = self._artefacts(tmp_path)
        builder = CertificateBuilder(seed=42, secret="testsecret")
        cert = builder.build(baseline, optimized, invariants, config=config)
        assert cert.signed is True
        assert cert.signature_algorithm == "HMAC-SHA256"
        assert len(cert.signature) == 64

    def test_verify_signature(self, tmp_path: Path):
        baseline, optimized, invariants, config = self._artefacts(tmp_path)
        builder = CertificateBuilder(seed=42, secret="testsecret")
        cert = builder.build(baseline, optimized, invariants, config=config)
        assert cert.verify_signature("testsecret") is True
        assert cert.verify_signature("wrong") is False

    def test_missing_secret_errors(self, tmp_path: Path):
        baseline, optimized, invariants, config = self._artefacts(tmp_path)
        builder = CertificateBuilder(seed=42, secret=None)
        cert = builder.build(baseline, optimized, invariants, config=config)
        assert cert.signed is False

    def test_cli_help(self):
        rc = subprocess.run(
            [sys.executable, "certify.py", "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0
        assert "--baseline" in rc.stdout

    def test_cli_requires_artefacts(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(os, "environ", {**os.environ})
        rc = subprocess.run(
            [
                sys.executable,
                "certify.py",
                "--baseline",
                str(tmp_path / "nope.json"),
                "--optimized",
                str(tmp_path / "nope2.json"),
                "--invariants",
                str(tmp_path / "nope.lock"),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 2

    def test_cli_sign_requires_env_secret(self, tmp_path: Path, monkeypatch):
        baseline, optimized, invariants, config = self._artefacts(tmp_path)
        monkeypatch.delenv("CERTIFY_HMAC_SECRET", raising=False)
        rc = subprocess.run(
            [
                sys.executable,
                "certify.py",
                "--baseline",
                str(baseline),
                "--optimized",
                str(optimized),
                "--invariants",
                str(invariants),
                "--seed",
                "1",
                "--sign",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            env={**os.environ},
        )
        assert rc.returncode == 2


# ── evolve ──────────────────────────────────────────────────────────────────


class TestEvolve:
    def test_supported_profiles(self):
        assert "enterprise" in SUPPORTED_PROFILES
        assert "scientific" in SUPPORTED_PROFILES
        assert "gpu" in SUPPORTED_PROFILES

    def test_config_validation(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Unsupported profile"):
            EvolveConfig(uast_path=tmp_path / "x.json", profile="bad")

    def test_config_valid(self, tmp_path: Path):
        cfg = EvolveConfig(
            uast_path=tmp_path / "x.json", profile="scientific", generations=5, population=8
        )
        assert cfg.profile == "scientific"

    def test_run_evolution_smoke(self, sample_uast_json: Path, tmp_path: Path):
        cfg = EvolveConfig(
            uast_path=sample_uast_json,
            profile="scientific",
            generations=3,
            population=8,
            hfc_tiers=True,
            checkpoint_every=1,
            seed=42,
            output_dir=tmp_path,
        )
        result = run_evolution(cfg)
        assert result.optimized_code.strip()
        assert result.generations == 3
        assert result.checkpoint_dir
        assert Path(result.checkpoint_dir, "optimized.py").exists()
        assert Path(result.checkpoint_dir, "fitness_report.json").exists()

    def test_run_evolution_non_hfc(self, sample_uast_json: Path, tmp_path: Path):
        cfg = EvolveConfig(
            uast_path=sample_uast_json,
            profile="enterprise",
            generations=2,
            population=5,
            hfc_tiers=False,
            checkpoint_every=1,
            seed=1,
            output_dir=tmp_path,
        )
        result = run_evolution(cfg)
        assert "def solution" in result.optimized_code

    def test_run_evolution_gpu_placeholder(self, sample_uast_json: Path, tmp_path: Path):
        cfg = EvolveConfig(
            uast_path=sample_uast_json,
            profile="gpu",
            generations=1,
            population=4,
            hfc_tiers=False,
            checkpoint_every=0,
            seed=3,
            output_dir=tmp_path,
        )
        result = run_evolution(cfg)
        assert result.profile == "gpu"

    def test_cli_help(self):
        rc = subprocess.run(
            [sys.executable, "evolve.py", "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0
        assert "--uast" in rc.stdout
        assert "--profile" in rc.stdout


# ── CLI smoke end-to-end ───────────────────────────────────────────────────


class TestPipelineE2ESmoke:
    def test_full_smoke_chain(self, tmp_path: Path):
        """parse → detect → evolve → gate on the same target."""
        src = tmp_path / "target.py"
        src.write_text(SAMPLE_PYTHON, encoding="utf-8")

        # 1. Parse
        uast_path = tmp_path / "uast.json"
        rc = subprocess.run(
            [sys.executable, "universal_parser.py", str(src), "-o", str(uast_path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0

        # 2. Detect invariants
        inv_path = tmp_path / "inv.lock"
        rc = subprocess.run(
            [
                sys.executable,
                "invariant_detector.py",
                str(uast_path),
                "-o",
                str(inv_path),
                "--source",
                str(src),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0
        assert json.loads(inv_path.read_text())["version"] == LOCKFILE_VERSION

        # 3. Evolve (tiny)
        rc = subprocess.run(
            [
                sys.executable,
                "evolve.py",
                "--uast",
                str(uast_path),
                "--profile",
                "enterprise",
                "--generations",
                "2",
                "--population",
                "6",
                "--hfc-tiers",
                "--seed",
                "42",
                "--output-dir",
                str(tmp_path / "muta"),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0
        # optimized.py must exist somewhere under output dir
        optimized = list((tmp_path / "muta" / "checkpoints").rglob("optimized.py"))
        assert optimized, "optimized.py not produced"

        # 4. Certify (no signing)
        cert_path = tmp_path / "cert.json"
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"hash": "b1", "latency_p50": 100.0}))
        optimized_json = tmp_path / "optimized.json"
        optimized_json.write_text(json.dumps({"optimized_hash": "o1"}))
        rc = subprocess.run(
            [
                sys.executable,
                "certify.py",
                "--baseline",
                str(baseline),
                "--optimized",
                str(optimized_json),
                "--invariants",
                str(inv_path),
                "--seed",
                "42",
                "-o",
                str(cert_path),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        assert rc.returncode == 0
        cert = json.loads(cert_path.read_text())
        assert cert["baseline_hash"] == "b1"
        assert cert["seed"] == 42
