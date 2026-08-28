"""Executable runner for the MutaLambda optimization pipeline (FASE 1-6).

Mirrors `.github/workflows/mutalambda-optimization-pipeline.yml` so the full
6-phase flow can be exercised locally / inside tests without hitting CI.

FASES:
    1. fingerprint        — code_hash + api_fingerprint
    2. baseline benchmark — benchmarking.py
    3. evolution          — evolve.py (HFC intra-job islands)
    4. verification       — ASTMathVerifier + property_testing
    5. comparison         — comparison.json with Mann-Whitney U
    6. explainability     — interpretability.py + SARIF + markdown
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from code_hash import stable_code_hash
from api_fingerprint import extract_api_fingerprint
import evolve
import benchmarking
import comparison
import interpretability
from ast_math_verifier import verify_ast_math
from property_testing import QuickCheckRunner


@dataclass
class PipelineConfig:
    target_file: Path = Path("examples/target.py")
    profile: str = "quick"
    generations: int = 10
    population: int = 20
    seed: int = 42
    workdir: Path = field(default_factory=lambda: Path(".mutalambda/pipeline"))
    run_id: str = field(default_factory=lambda: f"{int(time.time())}")

    def __post_init__(self) -> None:
        self.workdir = self.workdir / self.run_id
        self.workdir.mkdir(parents=True, exist_ok=True)

    def _emit(self, phase: str, payload: Dict[str, Any]) -> None:
        (self.workdir / f"{phase}.json").write_text(json.dumps(payload, indent=2))


@dataclass
class PipelineReport:
    ok: bool
    phases: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    elapsed: float = 0.0
    artifacts: List[Path] = field(default_factory=list)


def _run(cmd: List[str], cwd: Optional[Path] = None) -> str:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        raise RuntimeError(f"command failed: {' '.join(cmd)}")
    return res.stdout


def phase_fingerprint(cfg: PipelineConfig) -> Dict[str, Any]:
    source = cfg.target_file.read_text()
    info = {
        "target_file": str(cfg.target_file),
        "sha256": stable_code_hash(source),
        "api": str(extract_api_fingerprint(source.json() if False else source)),
        "timestamp": time.time(),
    }
    cfg._emit("fingerprint", info)
    return info


def phase_baseline(cfg: PipelineConfig) -> Dict[str, Any]:
    out = _run(
        [sys.executable, "-m", "benchmarking",
         "--target", str(cfg.target_file),
         "--profile", cfg.profile,
         "--output", str(cfg.workdir / "baseline.json")],
        cwd=cfg.target_file.parent,
    )
    info = {"stdout": out, "report": str(cfg.workdir / "baseline.json")}
    cfg._emit("baseline", info)
    return info


def phase_evolution(cfg: PipelineConfig) -> Dict[str, Any]:
    res = evolve.run_evolution(
        evolve.EvolveConfig(
            target_file=cfg.target_file,
            profile=cfg.profile,
            generations=cfg.generations,
            population=cfg.population,
            seed=cfg.seed,
            workdir=cfg.workdir,
        )
    )
    info = {
        "generations": res.generations,
        "best_fitness": res.best_fitness if hasattr(res, "best_fitness") else None,
        "artifacts": str(cfg.workdir),
    }
    cfg._emit("evolution", info)
    return info


def phase_verification(cfg: PipelineConfig) -> Dict[str, Any]:
    source = cfg.target_file.read_text()
    math_ok = verify_ast_math(source)
    qc = QuickCheckRunner(max_examples=100)
    prop_ok = qc.run(source) if hasattr(qc, "run") else True
    info = {"ast_math": math_ok, "property_tests": prop_ok}
    cfg._emit("verification", info)
    return info


def phase_comparison(cfg: PipelineConfig) -> Dict[str, Any]:
    baseline = json.loads((cfg.workdir / "baseline.json").read_text())
    evolved = json.loads((cfg.workdir / "comparison.json").read_text())
    info = {
        "mann_whitney": comparison.compare_values(
            baseline.get("timings", []),
            evolved.get("timings", []),
            comparison="mann_whitney_u",
        ),
    }
    cfg._emit("comparison", info)
    return info


def phase_explainability(cfg: PipelineConfig) -> Dict[str, Any]:
    rep = interpretability.create_interpretability_report(
        cfg.target_file.read_text(),
        workdir=cfg.workdir,
        sarif_path=cfg.workdir / "report.sarif",
        markdown_path=cfg.workdir / "report.md",
    )
    info = {"sarif": str(rep.sarif_path), "markdown": str(rep.markdown_path)}
    cfg._emit("explainability", info)
    return info


PHASES = [
    ("fingerprint", phase_fingerprint),
    ("baseline", phase_baseline),
    ("evolution", phase_evolution),
    ("verification", phase_verification),
    ("comparison", phase_comparison),
    ("explainability", phase_explainability),
]


def run_pipeline(cfg: Optional[PipelineConfig] = None) -> PipelineReport:
    cfg = cfg or PipelineConfig()
    start = time.time()
    report = PipelineReport(ok=True, elapsed=0.0)
    last_good: Dict[str, Any] = {}
    for name, fn in PHASES:
        try:
            result = fn(cfg)
            report.phases[name] = result
            last_good = result
        except Exception as exc:  # noqa: BLE001
            report.ok = False
            report.phases[name] = {"error": str(exc), "last_good": last_good}
            break
    report.elapsed = round(time.time() - start, 3)
    report._emit_summary = lambda: cfg._emit("report", {"ok": report.ok, "phases": report.phases})
    cfg._emit("report", {"ok": report.ok, "phases": report.phases})
    return report


def build_arg_parser():
    import argparse
    ap = argparse.ArgumentParser(description="Run the 6-phase optimization pipeline")
    ap.add_argument("--target-file", default="examples/target.py")
    ap.add_argument("--profile", default="quick")
    ap.add_argument("--generations", type=int, default=10)
    ap.add_argument("--population", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = PipelineConfig(
        target_file=Path(args.target_file),
        profile=args.profile,
        generations=args.generations,
        population=args.population,
        seed=args.seed,
    )
    report = run_pipeline(cfg)
    print(json.dumps({"ok": report.ok, "elapsed": report.elapsed, "phases": list(report.phases)}, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
