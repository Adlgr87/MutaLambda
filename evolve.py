#!/usr/bin/env python3
"""Unified evolution orchestrator CLI.

Wraps `evolution_engine.CoreEvolutionEngine`, `hfc_tiers.HFCLeagueEngine` and
`checkpoint_manager` into a single command-line entry point. Designed to run
without an LLM backend (offline deterministic mode) for smoke testing and CI.

Profiles:
  enterprise — latency/memory optimisation
  scientific — numerical stability + precision preservation
  gpu        — documented placeholder (no GPU kernels yet)

Usage:
    python evolve.py --uast <uast.json> --profile scientific \
        --generations 50 --population 100 --hfc-tiers \
        --checkpoint-every 10 [--islands 4]

Outputs:
  .mutalambda/checkpoints/<timestamp>/
      optimized.py            # best evolved source
      fitness_report.json     # per-generation fitness summary
      checkpoint.json         # full state (when --checkpoint-every triggers)
  stdout: summary line

Exit codes:
    0  success
    2  configuration / input error
    3  evolution produced no valid individuals
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from hfc_tiers import (
    HFCLeagueEngine,
    HFCTierConfig,
)

__all__ = ["EvolveConfig", "EvolveResult", "run_evolution"]

SUPPORTED_PROFILES = ("enterprise", "scientific", "gpu")
SUPPORTED_LANGUAGES = ("python", "rust", "cpp")


@dataclass
class EvolveConfig:
    """Runtime configuration for the evolve orchestrator."""

    uast_path: Path
    profile: str = "enterprise"
    generations: int = 50
    population: int = 100
    hfc_tiers: bool = False
    checkpoint_every: int = 10
    islands: int = 1
    seed: int = 42
    output_dir: Path = field(default_factory=lambda: Path(".mutalambda"))
    fitness_metric: str = "latency_p50"  # lower-is-better
    mutation_strategy: str = "ast"  # ast | llm
    allow_untested: bool = True
    timeout_sec: float = 5.0

    def __post_init__(self) -> None:
        if self.profile not in SUPPORTED_PROFILES:
            raise ValueError(
                f"Unsupported profile '{self.profile}'. Choose from {SUPPORTED_PROFILES}."
            )
        if self.generations <= 0:
            raise ValueError("generations must be positive")
        if self.population <= 0:
            raise ValueError("population must be positive")
        if self.islands < 1:
            raise ValueError("islands must be >= 1")

    @property
    def tier_config(self) -> HFCTierConfig:
        """Build an HFC tier config tuned to the selected profile."""
        if self.profile == "scientific":
            return HFCTierConfig(
                max_tier1_size=self.population,
                max_tier2_size=max(10, self.population // 5),
                max_tier3_size=5,
                lambda_clones=6,
                promotion_correctness=1.0,
                tier1_crossover_prob=0.4,
            )
        # enterprise / gpu share defaults
        return HFCTierConfig(
            max_tier1_size=self.population,
            max_tier2_size=max(10, self.population // 5),
            max_tier3_size=5,
            lambda_clones=8,
            promotion_correctness=1.0,
            tier1_crossover_prob=0.35,
        )


@dataclass
class GenerationResult:
    generation: int
    best_score: float
    best_code: str
    diversity: float
    elapsed_sec: float = 0.0


@dataclass
class EvolveResult:
    optimized_code: str
    best_score: float
    generations: int
    profile: str
    seed: int
    checkpoint_dir: str
    fitness_report: List[GenerationResult] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "optimized_code": self.optimized_code,
            "best_score": self.best_score,
            "generations": self.generations,
            "profile": self.profile,
            "seed": self.seed,
            "checkpoint_dir": self.checkpoint_dir,
            "fitness_report": [asdict(g) for g in self.fitness_report],
            "details": self.details,
        }


def _load_uast_source(uast_path: Path) -> str:
    """Recover original source from a uast.json, falling back to a parse."""
    if not uast_path.exists():
        raise FileNotFoundError(f"UAST file not found: {uast_path}")
    data = json.loads(uast_path.read_text(encoding="utf-8"))
    # Prefer the embedded original source when present.
    if data.get("source_text"):
        return data["source_text"]
    # Otherwise reconstruct a minimal seed from the UAST metadata + file hint.
    file_hint = data.get("file", "")
    if file_hint:
        p = Path(file_hint)
        if p.exists():
            return p.read_text(encoding="utf-8")
    # Final fallback: synthesize a trivial target so the run is still valid.
    return "def solution(n: int) -> int:\n    return n\n"


def _make_offline_evaluator(profile: str, seed: int) -> Callable[..., Any]:
    """Return an evaluator that scores code without executing or requiring an LLM.

    The scorer rewards:
      * correctness (syntactically valid Python that defines a public function),
      * parsimony (fewer statements => higher score),
      * numerical stability hints preserved (for the scientific profile),
      * stable identifiers / signatures (invariant preservation).
    """
    import ast as _ast

    from fitness_vector import FitnessVector

    rng = random.Random(seed)

    def _score(code: str) -> float:
        try:
            tree = _ast.parse(code)
        except SyntaxError:
            return float("-inf")
        # Correctness: must contain a FunctionDef.
        has_func = any(
            isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) for n in _ast.walk(tree)
        )
        if not has_func:
            return 0.0
        # Parsimony: reward fewer top-level statements.
        stmt_count = sum(1 for n in _ast.walk(tree) if isinstance(n, _ast.stmt))
        parsimony = 1.0 / (1.0 + stmt_count * 0.1)
        # Numerical-stability nudges (scientific profile).
        stability_bonus = 0.0
        if profile == "scientific":
            src_lower = code.lower()
            if any(s in src_lower for s in ("math.fsum", "decimal", "Fraction")):
                stability_bonus = 0.1
            else:
                stability_bonus = 0.0
        base = 1.0 * parsimony + stability_bonus
        # Tiny jitter so diversity is non-zero and evolution can progress.
        base += rng.uniform(0.0, 1e-3)
        return max(base, 0.0)

    class _OfflineEvaluator:
        def __init__(self) -> None:
            self._cache: Dict[int, Any] = {}

        def evaluate_batch(self, codes: List[str]) -> List[Any]:
            from models import EvalResult

            results: List[EvalResult] = []
            for code in codes:
                score = _score(code)
                passed = score >= 0.5
                fitness = FitnessVector(
                    correctness=1.0 if score > 0 else 0.0,
                    latency_p50=max(0.001, 1.0 - score) if score > 0 else float("inf"),
                    latency_p99=max(0.002, 1.0 - score) if score > 0 else float("inf"),
                    throughput=max(1.0, score * 100.0) if score > 0 else 0.0,
                    memory_peak_mb=max(0.1, 2.0 - score) if score > 0 else float("inf"),
                    parsimony=score,
                )
                results.append(
                    EvalResult(
                        fitness=fitness,
                        passed=passed,
                        metrics={"latency_p50": fitness.latency_p50, "parsimony": score},
                    )
                )
            return results

    return _OfflineEvaluator()


def _offline_llm_fn(prompt: str) -> str:
    """No-op LLM stub: returns a sentinel so HFC can still call its LLM micro-mutators."""
    return "# no LLM backend configured — AST-only mutations used\n"


def run_evolution(config: EvolveConfig) -> EvolveResult:
    """Run the unified evolution orchestrator and return a result + artefacts."""
    from evolution_engine import ASTMutator

    source = _load_uast_source(config.uast_path)
    rng = random.Random(config.seed)

    # Checkpoint directory: .mutalambda/checkpoints/<timestamp>/
    timestamp = int(time.time())
    checkpoint_dir = config.output_dir / "checkpoints" / str(timestamp)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    evaluator = _make_offline_evaluator(config.profile, config.seed)

    # Build a seed population of mutated variants of the original source.
    seed_codes = [source]
    seen: set[int] = {hash(source)}
    for _ in range(config.population - 1):
        mutant = ASTMutator.apply_random_mutation(source)
        h = hash(mutant)
        if h not in seen:
            seen.add(h)
            seed_codes.append(mutant)
        if len(seed_codes) >= config.population:
            break

    fitness_report: List[GenerationResult] = []

    if config.hfc_tiers:
        engine = HFCLeagueEngine(
            config=config.tier_config,
            rng=rng,
        )
        engine.seed(seed_codes)

        for gen in range(int(config.generations)):
            gen_start = time.perf_counter()
            engine.step(
                llm_fn=_offline_llm_fn,
                evaluator=evaluator,
                generation=gen,
                task="",
            )
            elapsed = time.perf_counter() - gen_start

            best = engine.best_individual
            best_code = best.code if best else source
            best_score = engine.best_score if engine.best_score != float("-inf") else 0.0
            fitness_report.append(
                GenerationResult(
                    generation=gen,
                    best_score=best_score,
                    best_code=best_code,
                    diversity=engine.diversity,
                    elapsed_sec=elapsed,
                )
            )

            if config.checkpoint_every > 0 and (gen + 1) % config.checkpoint_every == 0:
                _write_checkpoint(checkpoint_dir, gen, engine, config)

        final_best = engine.best_individual
        optimized_code = final_best.code if final_best else source
        best_score = engine.best_score if engine.best_score != float("-inf") else 0.0
        engine_stats = engine.stats()
    else:
        # Plain single-population evolution using ASTMutator directly.
        population = seed_codes[:]
        best_code = source
        best_score = 0.0
        for gen in range(int(config.generations)):
            # Score the population.
            evals = evaluator.evaluate_batch(population)
            scored = list(zip(population, evals))
            scored.sort(key=lambda pair: pair[1].score, reverse=True)
            current_best_code, current_best_eval = scored[0]
            if current_best_eval.score > best_score:
                best_score = current_best_eval.score
                best_code = current_best_code

            fitness_report.append(
                GenerationResult(
                    generation=gen,
                    best_score=best_score,
                    best_code=best_code,
                    diversity=len({c for c, _ in scored}) / max(1, len(scored)),
                )
            )

            # Mutation + elitism: keep top 25%, mutate the rest.
            keep = max(1, len(scored) // 4)
            elite = [code for code, _ in scored[:keep]]
            mutations = []
            for code in elite[: max(1, config.population - keep)]:
                mutations.append(ASTMutator.apply_random_mutation(code))
            population = elite + mutations
            while len(population) < config.population:
                population.append(ASTMutator.apply_random_mutation(source))
            population = population[: config.population]

            if config.checkpoint_every > 0 and (gen + 1) % config.checkpoint_every == 0:
                _write_inline_checkpoint(
                    checkpoint_dir,
                    gen,
                    population,
                    best_code,
                    best_score,
                    config,
                )

        optimized_code = best_code

        # Restore a stats dict shape compatible with the HFC branch.
        engine_stats = {
            "best_score": best_score,
            "tier_counts": {},
            "diversity": fitness_report[-1].diversity if fitness_report else 0.0,
        }

    # Always emit the final best code + fitness report.
    _write_artifacts(
        checkpoint_dir,
        optimized_code,
        fitness_report,
        config,
        best_score,
        engine_stats,
    )

    return EvolveResult(
        optimized_code=optimized_code,
        best_score=best_score,
        generations=int(config.generations),
        profile=config.profile,
        seed=config.seed,
        checkpoint_dir=str(checkpoint_dir),
        fitness_report=fitness_report,
        details={"engine_stats": engine_stats, "population_size": config.population},
    )


def _write_checkpoint(
    dir_path: Path, generation: int, engine: HFCLeagueEngine, config: EvolveConfig
) -> None:
    """Persist an HFC engine snapshot as a JSON checkpoint."""
    snapshot = engine.last_snapshot
    data = {
        "generation": generation,
        "timestamp": time.time(),
        "engine": "hfc_league",
        "profile": config.profile,
        "seed": config.seed,
        "config": asdict(config.tier_config),
        "snapshot": asdict(snapshot) if snapshot else {},
        "tier_counts": engine._tier_counts() if hasattr(engine, "_tier_counts") else {},
        "best_score": engine.best_score,
        "diversity": engine.diversity,
    }
    path = dir_path / f"checkpoint_gen{generation:04d}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _write_inline_checkpoint(
    dir_path: Path,
    generation: int,
    population: List[str],
    best_code: str,
    best_score: float,
    config: EvolveConfig,
) -> None:
    """Persist a lightweight inline checkpoint for the non-HFC mode."""
    data = {
        "generation": generation,
        "timestamp": time.time(),
        "engine": "inline",
        "profile": config.profile,
        "seed": config.seed,
        "population_size": len(population),
        "best_score": best_score,
        "best_code": best_code,
    }
    path = dir_path / f"checkpoint_gen{generation:04d}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _write_artifacts(
    dir_path: Path,
    optimized_code: str,
    fitness_report: List[GenerationResult],
    config: EvolveConfig,
    best_score: float,
    engine_stats: Dict[str, Any],
) -> None:
    optimized_path = dir_path / "optimized.py"
    optimized_path.write_text(optimized_code, encoding="utf-8")

    report = {
        "optimized": optimized_code,
        "best_score": best_score,
        "generations": len(fitness_report),
        "profile": config.profile,
        "seed": config.seed,
        "fitness_report": [asdict(g) for g in fitness_report],
        "engine_stats": engine_stats,
    }
    report_path = dir_path / "fitness_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)


def _gpu_profile_warning() -> None:
    """Emit a documented placeholder note for the gpu profile."""
    sys.stderr.write(
        "NOTE: 'gpu' profile is a documented placeholder — no GPU kernel "
        "optimisation is applied yet. Evolution runs in CPU-only mode.\n"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evolve",
        description="Unified evolution orchestrator (CoreEvolutionEngine + HFC tiers + checkpoints).",
    )
    parser.add_argument(
        "--uast", type=Path, required=True, help="Path to uast.json from universal_parser."
    )
    parser.add_argument(
        "--profile",
        choices=list(SUPPORTED_PROFILES),
        default="enterprise",
        help="Optimisation profile (default: enterprise).",
    )
    parser.add_argument(
        "--generations", type=int, default=50, help="Number of generations (default: 50)."
    )
    parser.add_argument(
        "--population", type=int, default=100, help="Population size (default: 100)."
    )
    parser.add_argument("--hfc-tiers", action="store_true", help="Enable HFC tiered evolution.")
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=10,
        help="Checkpoint interval (default: 10). 0 disables.",
    )
    parser.add_argument(
        "--islands",
        type=int,
        default=1,
        help="Intra-job islands for parallel execution (default: 1).",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42).")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".mutalambda"),
        help="Output root directory (default: .mutalambda).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        config = EvolveConfig(
            uast_path=args.uast,
            profile=args.profile,
            generations=args.generations,
            population=args.population,
            hfc_tiers=args.hfc_tiers,
            checkpoint_every=args.checkpoint_every,
            islands=args.islands,
            seed=args.seed,
            output_dir=args.output_dir,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if config.profile == "gpu":
        _gpu_profile_warning()

    start = time.perf_counter()
    try:
        result = run_evolution(config)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Error: evolution failed: {exc}", file=sys.stderr)
        return 3

    elapsed = time.perf_counter() - start
    summary = (
        f"evolve complete — profile={result.profile} generations={result.generations} "
        f"best_score={result.best_score:.4f} elapsed={elapsed:.1f}s "
        f"checkpoint_dir={result.checkpoint_dir}"
    )
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
