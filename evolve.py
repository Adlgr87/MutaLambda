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
import os
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
    mutation_strategy: str = "ast"  # ast | llm | auto (FASE 3: bandit resuelve)
    allow_untested: bool = True
    # FASE 3 (A5): warm-start from the pareto archive (same API signature).
    # Disable per run with --no-warm-start.
    warm_start: bool = True
    timeout_sec: float = 5.0
    # Fase 0 (A5): path to a prior checkpoint JSON to resume from.  When set,
    # evolution continues from that checkpoint's generation with its
    # population (see ``--resume-from`` in the CLI).
    resume_from: Optional[str] = None

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
        if self.mutation_strategy not in ("ast", "llm", "auto"):
            raise ValueError(
                f"Unsupported mutation_strategy '{self.mutation_strategy}'. "
                "Choose from ast | llm | auto."
            )

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
    # Fase 0 (A2): fitness-cache hit/miss stats for this run (None when the
    # cache was disabled by config/optimization.yaml).
    fitness_cache_stats: Optional[Dict[str, Any]] = None

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
            "fitness_cache_stats": self.fitness_cache_stats,
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


# ── Fase 0 (A2): canonical-hash fitness cache ───────────────────────────────


def _serialize_eval_result(result: Any) -> Dict[str, Any]:
    """Serialize an ``EvalResult`` (dataclass) to a JSON-safe dict."""
    data = asdict(result)
    return data


def _restore_eval_result(data: Dict[str, Any]) -> Any:
    """Rebuild an ``EvalResult`` from its JSON-safe dict form."""
    from fitness_vector import FitnessVector
    from models import EvalResult

    payload = dict(data)
    fitness = payload.pop("fitness", None)
    return EvalResult(fitness=FitnessVector(**fitness), **payload)


class CachedBatchEvaluator:
    """Memoizes ``evaluate_batch`` results by canonical code hash (A2).

    Transparent duck-type wrapper: exposes ``evaluate_batch`` and
    ``cache_stats`` (the HFC engine already probes for ``cache_stats``) and
    forwards everything else to the wrapped evaluator.  Scores are stored per
    run namespace (profile + seed) so different scorers never cross-contaminate.
    """

    def __init__(self, base: Any, cache: Any, namespace: str) -> None:
        self._base = base
        self._cache = cache
        self.namespace = namespace

    def evaluate_batch(self, codes: List[str]) -> List[Any]:
        from fitness_cache import fitness_cache_key

        if not codes:
            return []
        out: List[Optional[Any]] = [None] * len(codes)
        pending: List[tuple] = []
        for i, code in enumerate(codes):
            key = fitness_cache_key(self.namespace, code)
            hit = self._cache.get(key)
            if hit is not None:
                out[i] = _restore_eval_result(hit)
            else:
                pending.append((i, code, key))
        if pending:
            fresh = self._base.evaluate_batch([code for _, code, _ in pending])
            for (i, code, key), result in zip(pending, fresh):
                out[i] = result
                try:
                    self._cache.put(key, _serialize_eval_result(result))
                except (TypeError, ValueError):
                    pass  # non-serializable result — skip memoization for it
        return out  # type: ignore[return-value]

    def cache_stats(self) -> Dict[str, Any]:
        """Combined view: inner service cache + canonical-hash cache."""
        inner = self._base.cache_stats() if hasattr(self._base, "cache_stats") else {}
        outer = self._cache.stats()
        combined = dict(outer)
        combined["inner"] = inner
        return combined

    def __getattr__(self, name: str) -> Any:
        # Forward unknown attributes (runner_mode, timeout_sec, ...) to base.
        return getattr(self._base, name)


def _make_fitness_cache(config: EvolveConfig) -> Optional[Any]:
    """Open the fitness cache when enabled by config/optimization.yaml."""
    from optimization_flags import get_optimization_flags

    flags = get_optimization_flags()
    if not flags.enabled("fitness_cache.enabled", True):
        return None
    from fitness_cache import FitnessCache

    path = Path(str(flags.get("fitness_cache.path", ".mutalambda/fitness_cache.db")))
    if not path.is_absolute():
        path = config.output_dir / "fitness_cache" / path.name
    return FitnessCache(
        path=path,
        backend=str(flags.get("fitness_cache.backend", "sqlite")),
        max_entries=int(flags.get("fitness_cache.max_entries", 100000) or 100000),
        namespace=f"{config.profile}:seed{config.seed}",
    )


def _top_up_population(
    population: List[str], source: str, size: int, rng: random.Random
) -> List[str]:
    """Dedupe *population* and pad toward *size* with fresh source mutants.

    Bounded: never loops forever when the target source yields duplicate
    mutants (the evolution loop itself re-pads each generation).
    """
    from evolution_engine import ASTMutator

    out: List[str] = []
    seen: set = set()
    for code in population:
        h = hash(code)
        if h not in seen:
            seen.add(h)
            out.append(code)
    target = max(1, size)
    attempts = 0
    while len(out) < target and attempts < 200:
        attempts += 1
        mutant = ASTMutator.apply_random_mutation(source)
        h = hash(mutant)
        if h not in seen:
            seen.add(h)
            out.append(mutant)
    return out[:target]


def _load_resume_checkpoint(path: str | Path) -> Optional[Dict[str, Any]]:
    """Load a checkpoint JSON for ``--resume-from`` (inline or HFC flavour)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"resume checkpoint not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "generation" not in data:
        raise ValueError(f"not a MutaLambda checkpoint: {path}")
    data.setdefault("population", [])
    data.setdefault("best_code", "")
    data.setdefault("best_score", 0.0)
    return data


def run_evolution(config: EvolveConfig) -> EvolveResult:
    """Run the unified evolution orchestrator and return a result + artefacts."""
    from evolution_engine import ASTMutator

    source = _load_uast_source(config.uast_path)
    rng = random.Random(config.seed)

    # Checkpoint directory: .mutalambda/checkpoints/<timestamp>/
    timestamp = int(time.time())
    checkpoint_dir = config.output_dir / "checkpoints" / str(timestamp)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # ── A5: resume from a prior checkpoint (``--resume-from``) ────────────
    start_gen = 0
    resumed_from: Optional[int] = None
    best_score = 0.0
    best_code = source
    if config.resume_from:
        ckpt = _load_resume_checkpoint(config.resume_from)
        population_from_ckpt = [c for c in ckpt.get("population") or [] if isinstance(c, str) and c.strip()]
        if population_from_ckpt:
            # A checkpoint at generation N captures the state AFTER N, so the
            # resumed run continues from N + 1.
            resumed_from = int(ckpt.get("generation", 0))
            start_gen = max(0, resumed_from + 1)
            seed_codes = _top_up_population(
                population_from_ckpt, source, config.population, rng
            )
            best_score = float(ckpt.get("best_score", 0.0) or 0.0)
            best_code = str(ckpt.get("best_code") or "") or source
        else:
            raise ValueError(
                f"checkpoint {config.resume_from} carries no population to resume from"
            )

    # ── A2: fitness cache by canonical hash ───────────────────────────────
    fitness_cache = _make_fitness_cache(config)
    if fitness_cache is not None:
        evaluator = _make_offline_evaluator(config.profile, config.seed)
        evaluator = CachedBatchEvaluator(
            evaluator, fitness_cache, namespace=f"{config.profile}:seed{config.seed}"
        )
    else:
        evaluator = _make_offline_evaluator(config.profile, config.seed)

    # ── FASE 2 (O6/A4): tiered evaluation ladder, flag-gated ──────────────
    # profiling_filter.enabled (config/optimization.yaml) ⇒ N1 nanopass
    # (<1 ms) → N2 minimal test subset → N3 top-20 % sandbox.  Zero
    # behaviour change when the flag is off.
    try:
        from tiered_evaluator import TieredOfflineEvaluator, tiering_active
        if tiering_active():
            evaluator = TieredOfflineEvaluator(source, evaluator)
    except Exception:
        pass  # the ladder must never take the pipeline down

    # ── FASE 3 (O5/A5): economic gate + pareto archive, flag-gated ─────────
    gate = None
    archive = None
    warm_start_info: Dict[str, Any] = {"used": False}
    stop_reason = "completed"
    stop_generation: Optional[int] = None
    strategy_note = config.mutation_strategy
    final_hv = 0.0
    try:
        from optimization_flags import get_optimization_flags

        _f3 = get_optimization_flags()
        if _f3.enabled("economic_gate.enabled"):
            from cost_ledger import get_cost_ledger
            from economic_gate import EconomicHeadroomGate

            gate = EconomicHeadroomGate(
                delta_h_threshold=float(_f3.get("economic_gate.delta_h_threshold", 0.005)),
                stall_generations=int(_f3.get("economic_gate.stall_generations", 5)),
                gpu_hour_usd=float(_f3.get("economic_gate.gpu_hour_usd", 0.5)),
                production_cpu_savings_hour_usd=float(
                    _f3.get("economic_gate.production_cpu_savings_hour_usd", 0.0)
                ),
                gpu_seconds_per_generation=float(
                    _f3.get("economic_gate.gpu_seconds_per_generation", 0.0)
                ),
                total_planned_generations=int(config.generations),
                ledger=get_cost_ledger(),
            )
        if _f3.enabled("pareto_archive.enabled"):
            from pareto_archive import ParetoArchive

            archive = ParetoArchive(_f3.get("pareto_archive.dir", "pareto_archive"))
    except Exception:
        pass  # levers must never take the pipeline down

    # FASE 3 A3: "auto" resolves to llm when a backend is reachable
    # (an API key is configured), else ast.  The bandit (island flow)
    # applies the real-$ reward when bandit_reward_usd.enabled.
    if config.mutation_strategy == "auto":
        resolved = "ast"
        try:
            if os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
                resolved = "llm"
        except Exception:
            resolved = "ast"
        strategy_note = f"auto→{resolved}"

    if not config.resume_from:
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

        # FASE 3 (A5): warm-start — a prior best for the SAME public API
        # replaces one random mutant in the seed population.  The archive
        # code is evaluated like any other individual (it is never trusted
        # blindly).  --no-warm-start disables this *read* only; the run
        # still stores its best for future runs.
        if archive is not None and config.warm_start:
            try:
                entry = archive.lookup(source)
                if entry and isinstance(entry.get("code"), str) and entry["code"].strip():
                    archived_code = entry["code"]
                    if archived_code not in seed_codes:
                        seed_codes[-1] = archived_code
                    warm_start_info = {
                        "used": True,
                        "signature_hit": True,
                        "archived_generation": entry.get("generation"),
                        "archived_score": entry.get("score"),
                        "profile": entry.get("profile", ""),
                    }
            except Exception:
                warm_start_info = {"used": False, "error": "archive_lookup_failed"}

    fitness_report: List[GenerationResult] = []

    if config.hfc_tiers:
        engine = HFCLeagueEngine(
            config=config.tier_config,
            rng=rng,
        )
        engine.seed(seed_codes)

        for gen in range(start_gen, int(config.generations)):
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

        # FASE 3 (A5/O5): final hypervolume over the tiers' fitness vectors.
        try:
            from economic_gate import hypervolume as _hv_fn

            final_hv = _hv_fn(
                [
                    ind.fitness
                    for ind in (engine.tier1 + engine.tier2 + engine.tier3)
                    if getattr(ind, "fitness", None) is not None
                ]
            )
        except Exception:
            final_hv = 0.0
    else:
        # Plain single-population evolution using ASTMutator directly.
        population = seed_codes[:]
        if resumed_from is None:
            best_code = source
            best_score = 0.0
        for gen in range(start_gen, int(config.generations)):
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

            # FASE 3 (O5): economic gate over the population hypervolume.
            if gate is not None:
                from economic_gate import hypervolume as _hv_fn

                final_hv = _hv_fn([ev.fitness for ev in evals])
                _decision = gate.observe(gen, final_hv)
                if _decision.stop:
                    stop_reason = _decision.reason
                    stop_generation = gen
                    break

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

        # FASE 3 (A5/O5): final population hypervolume (always — the
        # roi_report reports it; one extra cached evaluation at the end).
        try:
            from economic_gate import hypervolume as _hv_fn

            final_hv = _hv_fn([ev.fitness for ev in evaluator.evaluate_batch(population)])
        except Exception:
            final_hv = float(getattr(gate, "final_hypervolume", None) or 0.0) if gate else 0.0
        if archive is not None:
            try:
                archive.store(
                    source,
                    optimized_code,
                    fitness={"best_score": best_score},
                    score=best_score,
                    hypervolume=final_hv,
                    generation=len(fitness_report) - 1,
                    profile=config.profile,
                )
            except Exception:
                warm_start_info["store_error"] = "archive_store_failed"

        # Restore a stats dict shape compatible with the HFC branch.
        engine_stats = {
            "best_score": best_score,
            "tier_counts": {},
            "diversity": fitness_report[-1].diversity if fitness_report else 0.0,
        }

    # A2: freeze and close the fitness cache before writing artefacts.
    cache_stats_snapshot: Optional[Dict[str, Any]] = None
    if fitness_cache is not None:
        cache_stats_snapshot = fitness_cache.stats()
        fitness_cache.close()

    # Always emit the final best code + fitness report.
    _write_artifacts(
        checkpoint_dir,
        optimized_code,
        fitness_report,
        config,
        best_score,
        engine_stats,
    )

    # FASE 3 (A5): roi_report.json — total cost, levers, stop reason, HV.
    roi_path = _write_roi_report(
        checkpoint_dir,
        config,
        generations_run=len(fitness_report),
        best_score=best_score,
        final_hv=final_hv,
        stop_reason=stop_reason,
        stop_generation=stop_generation,
        gate_summary=gate.summary() if gate is not None else None,
        warm_start=warm_start_info,
        strategy_note=strategy_note,
        cache_stats=cache_stats_snapshot,
    )

    return EvolveResult(
        optimized_code=optimized_code,
        best_score=best_score,
        generations=len(fitness_report),
        profile=config.profile,
        seed=config.seed,
        checkpoint_dir=str(checkpoint_dir),
        fitness_report=fitness_report,
        details={
            "engine_stats": engine_stats,
            "population_size": config.population,
            "resumed_from_generation": resumed_from,
            "resumed_at_generation": start_gen if resumed_from is not None else None,
            "resume_source": config.resume_from,
            "stop_reason": stop_reason,
            "stop_generation": stop_generation,
            "final_hypervolume": final_hv,
            "warm_start": warm_start_info,
            "roi_report": str(roi_path) if roi_path else None,
        },
        fitness_cache_stats=cache_stats_snapshot,
    )


def _write_roi_report(
    dir_path: Path,
    config: "EvolveConfig",
    *,
    generations_run: int,
    best_score: float,
    final_hv: float,
    stop_reason: str,
    stop_generation: Optional[int],
    gate_summary: Optional[Dict[str, Any]],
    warm_start: Dict[str, Any],
    strategy_note: str,
    cache_stats: Optional[Dict[str, Any]],
) -> Optional[Path]:
    """FASE 3 (A5): write roi_report.json for the run.  Never raises."""
    try:
        from cost_ledger import get_cost_ledger

        cost = get_cost_ledger().totals()
    except Exception:
        cost = {"total_cost_usd": 0.0}
    levers: Dict[str, Any] = {}
    try:
        from optimization_flags import get_optimization_flags

        flags = get_optimization_flags()
        levers = {
            "fase0": {
                "cost_ledger": flags.enabled("cost_ledger.enabled"),
                "fitness_cache": flags.enabled("fitness_cache.enabled"),
                "deterministic_prompt": flags.enabled("deterministic_prompt.enabled"),
                "checkpoint_every": flags.get("checkpoint.every", 5),
            },
            "fase1_headroom": {
                sub: flags.enabled(f"headroom.{sub}.enabled")
                for sub in (
                    "smart_crusher",
                    "ast_stubs",
                    "json_schema_output",
                    "batching",
                    "bandit",
                )
            },
            "fase2_profiling_filter": flags.enabled("profiling_filter.enabled"),
            "fase3": {
                "economic_gate": flags.enabled("economic_gate.enabled"),
                "bandit_reward_usd": flags.enabled("bandit_reward_usd.enabled"),
                "pareto_archive": flags.enabled("pareto_archive.enabled"),
                "warm_start_enabled": config.warm_start,
            },
        }
    except Exception:
        levers = {}
    report = {
        "profile": config.profile,
        "mutation_strategy": config.mutation_strategy,
        "strategy_resolved": strategy_note,
        "generations_planned": config.generations,
        "generations_run": generations_run,
        "stop_reason": stop_reason,
        "stop_generation": stop_generation,
        "best_score": best_score,
        "final_hypervolume": final_hv,
        "cost": cost,
        "levers": levers,
        "economic_gate": gate_summary,
        "warm_start": warm_start,
        "fitness_cache": cache_stats,
    }
    try:
        path = dir_path / "roi_report.json"
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return path
    except Exception:
        return None


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
        # A5 (resume): persist the full population so --resume-from can
        # continue the exact same evolutionary line.
        "best_code": engine.best_individual.code if engine.best_individual else "",
        "population": [ind.code for ind in (engine.tier1 + engine.tier2 + engine.tier3)],
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
        # A5 (resume): full population so --resume-from continues the line.
        "population": list(population),
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
        default=None,
        help=(
            "Checkpoint interval in generations (default: optimization.checkpoint.every "
            "from config/optimization.yaml, typically 5). 0 disables."
        ),
    )
    parser.add_argument(
        "--resume-from",
        type=str,
        default=None,
        help=(
            "Path to a prior checkpoint JSON (checkpoint_genNNNN.json) to resume "
            "evolution from its generation and population."
        ),
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
    parser.add_argument(
        "--mutation-strategy",
        choices=["ast", "llm", "auto"],
        default="ast",
        help=(
            "Mutation strategy (default: ast). 'auto' (FASE 3) resolves to "
            "llm when an API key is configured and lets the operator bandit "
            "use real-$ rewards from the cost ledger "
            "(bandit_reward_usd.enabled)."
        ),
    )
    parser.add_argument(
        "--no-warm-start",
        action="store_false",
        dest="warm_start",
        help="FASE 3 (A5): disable warm-start from the pareto archive.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # A5: default checkpoint cadence comes from config/optimization.yaml
    # (checkpoint.every, typically 5) unless the caller pinned a value.
    if args.checkpoint_every is None:
        from optimization_flags import get_optimization_flags

        args.checkpoint_every = int(get_optimization_flags().get("checkpoint.every", 5) or 5)

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
            resume_from=args.resume_from,
            mutation_strategy=args.mutation_strategy,
            warm_start=args.warm_start,
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
