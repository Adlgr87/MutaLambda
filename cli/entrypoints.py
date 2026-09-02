"""CLI entry points for MutaLambda (Phase 2D extraction).

Extracted from ``muta_lambda/__init__.py`` so the package ``__init__``
becomes a slim re-export layer (Phase 2E).

Functions
---------
run_full_test_suite : intégrated smoke-test runner used by ``--test``.
_demo_llm_fn         : simulated LLM for demos (no real model needed).
main                 : argparse CLI entry point (``python -m muta_lambda``).
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import sys
from pathlib import Path
from typing import Callable, List, Tuple

from muta_lambda import (
    ASTMutator,
    EvolveConfig,
    MutaLambdaAgent,
    Individual,
)

# ---------------------------------------------------------------------------
# Integrated test suite (``--test`` flag)
# ---------------------------------------------------------------------------


def run_full_test_suite() -> bool:
    """Suite integrada mínima para el CLI --test."""
    import traceback

    passed: List[str] = []
    failed: List[Tuple[str, str]] = []

    def test(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            passed.append(name)
            print(f"  [PASS] {name}")
        except Exception as exc:
            tb = traceback.format_exc().splitlines()[-1]
            failed.append((name, tb))
            print(f"  [FAIL] {name} — {tb}")

    def t_ast_mutations_valid():
        code = "def f(x):\n    total = 0\n    for i in range(x):\n        total += i\n    return total\n"
        for _ in range(200):
            ast.parse(ASTMutator.apply_random_mutation(code))

    def t_llm_mutation_accepts_valid_code():
        from muta_lambda import CoreEvolutionEngine

        engine = CoreEvolutionEngine()
        result = engine.mutate_with_llm(
            code="def f(x):\n    return x + 1\n",
            score=1.0,
            error_info="",
            llm_fn=lambda _prompt: "def f(x):\n    return x * 2\n",
        )
        ast.parse(result)

    def t_diversity_not_placeholder():
        from island_evolution import IslandPool

        pool = IslandPool()
        fake_islands = []
        for idx in range(2):
            fake = type("FakeIsland", (), {"population": []})()
            fake.population = [Individual(code=f"def f{idx}(): return {idx}")]
            fake_islands.append(fake)
        diversity = pool.get_cross_island_diversity(fake_islands)
        assert 0.0 < diversity < 1.0, f"Expected diversity in (0,1), got {diversity}"

    print("\n" + "=" * 60)
    print("SUITE DE TESTS — MutaLambda Agent (modular)")
    print("=" * 60)
    test("ast_mutations_valid", t_ast_mutations_valid)
    test("llm_mutation_accepts_valid_code", t_llm_mutation_accepts_valid_code)
    test("cross_island_diversity_not_placeholder", t_diversity_not_placeholder)

    print("\n" + "-" * 60)
    total = len(passed) + len(failed)
    print(f"Resultado: {len(passed)}/{total} tests pasaron")
    if failed:
        print("\nFallidos:")
        for name, err in failed:
            print(f"  ✗ {name}: {err}")
    print("=" * 60 + "\n")
    return len(failed) == 0


# ---------------------------------------------------------------------------
# Simulated LLM for demos
# ---------------------------------------------------------------------------


def _demo_llm_fn(prompt: str) -> str:
    """LLM simulado para demostración: aplica micro-mutaciones al código."""
    lines = prompt.split("\n")
    code_lines = [
        l
        for l in lines
        if l.strip() and not l.startswith(("You are", "Task:", "Improve", "Return", "Instructions:"))
    ]
    code = "\n".join(code_lines).strip()
    if not code:
        return "def solution():\n    return 42"
    mutated = ASTMutator.apply_random_mutation(code)
    return mutated


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

__all__ = ["main", "run_full_test_suite", "_demo_llm_fn"]


def main() -> None:
    """Demo/CLI: ejecuta MutaLambda con un LLM simulado o corre los tests."""
    parser = argparse.ArgumentParser(description="MutaLambda Agent modular")
    parser.add_argument("--islands", type=int, default=3)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--pop-size", type=int, default=6)
    parser.add_argument(
        "--topology",
        default="ring",
        choices=["ring", "fully_connected", "random", "mesh"],
    )
    parser.add_argument(
        "--novelty-alpha",
        type=float,
        default=0.15,
        help="Peso del bonus de novedad en el score (0.0–1.0)",
    )
    parser.add_argument("--early-stop-patience", type=int, default=15)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Ejecutar suite de tests integrada y salir",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Ruta a archivo YAML de configuración",
    )
    parser.add_argument(
        "--resume",
        type=str,
        default=None,
        help="Ruta a checkpoint para reanudar evolución",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Activar dashboard de consola HITL",
    )
    parser.add_argument(
        "--hint",
        type=str,
        default=None,
        help="Inyectar código como hint experto en una isla",
    )
    parser.add_argument(
        "--hfc-enabled",
        action="store_true",
        help="Activar evolución por ligas HFC",
    )
    parser.add_argument(
        "--hfc-lambda-clones",
        type=int,
        default=8,
        help="Clones bacterianos por individuo Tier2",
    )
    # MutaLambda 2.0 Progressive Pipeline
    parser.add_argument(
        "--optimize",
        type=str,
        default=None,
        help="Path to Python script to optimize (progressive pipeline)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="auto",
        choices=["auto", "fast", "deep"],
        help="Optimization mode (default: auto)",
    )
    parser.add_argument(
        "--advanced-diagnostics",
        action="store_true",
        help="Enable advanced metrics (P99, throughput, parsimony)",
    )
    parser.add_argument(
        "--min-improvement",
        type=float,
        default=0.15,
        help="Minimum improvement threshold (default: 0.15)",
    )

    args = parser.parse_args()

    logging.getLogger("MutaLambda").setLevel(args.log_level)

    if args.test:
        ok = run_full_test_suite()
        sys.exit(0 if ok else 1)

    if args.config:
        config = EvolveConfig.from_yaml(args.config)
        from config_loader import load_yaml  # noqa: F401

        agent_kwargs = {"config": config}
    else:
        seed = (
            "def compute_sum(n):\n"
            "    total = 0\n"
            "    for i in range(n):\n"
            "        total += i\n"
            "    return total\n"
        )

        config = EvolveConfig(
            num_islands=args.islands,
            generations=args.generations,
            seed_codes=[seed],
            topology=args.topology,
            population_size=args.pop_size,
            top_k=max(2, args.pop_size // 3),
            archive_solutions=False,
            prompt_evolution=False,
            novelty_alpha=args.novelty_alpha,
            early_stop_patience=args.early_stop_patience,
            hfc_enabled=args.hfc_enabled,
            hfc_lambda_clones=args.hfc_lambda_clones,
        )
        config.sandbox_timeout = 5.0
        config.sandbox_workers = 4
        agent_kwargs = {"config": config}

    # MutaLambda 2.0 Progressive Pipeline
    if args.optimize:
        from progressive_pipeline import ProgressivePipeline

        script_path = Path(args.optimize)
        if not script_path.exists():
            print(f"Error: File not found: {script_path}")
            sys.exit(1)

        code = script_path.read_text()
        print(f"\n🧬 MutaLambda 2.0 — Progressive Optimization Pipeline")
        print(f"   Target: {script_path}")
        print(f"   Mode: {args.mode}")
        print(f"   Advanced Diagnostics: {args.advanced_diagnostics}")
        print()

        pipeline = ProgressivePipeline(
            llm_fn=_demo_llm_fn,
            min_improvement=args.min_improvement,
        )

        result = pipeline.run(code, mode=args.mode)
        print(result.summary())

        if result.success and result.optimized_code:
            print("\n" + "=" * 60)
            print("OPTIMIZED CODE:")
            print("=" * 60)
            print(result.optimized_code)

        sys.exit(0 if result.success else 1)

    if args.resume:
        from checkpoint_manager import resume_agent

        agent = resume_agent(
            args.resume,
            config,
            test_cases=[],
            llm_fn=_demo_llm_fn,
        )
        best = agent.run(task="Continue evolution from checkpoint")
    else:
        agent = MutaLambdaAgent(
            config=config,
            llm_fn=_demo_llm_fn,
            test_cases=[],
            timeout_sec=getattr(config, "sandbox_timeout", 5.0),
        )
        best = agent.run(task="Optimize a sum function for correctness and speed")

    print("\n" + "=" * 60)
    print("BEST SOLUTION FOUND:")
    print("=" * 60)
    print(best.code)
    print(f"\nScore: {best.score:.4f}")
    print("\nMetrics:", json.dumps(agent.get_metrics(), indent=2, default=str))


if __name__ == "__main__":
    main()