#!/usr/bin/env python3
"""Alias/Wrapper de `mutalambda_v2_patched.py`.

Fuente verdadera: `muta_lambda.py` (v2.1 optimizado).

Este archivo mantiene compatibilidad para:
  - `python mutalambda_v2_patched.py --test`
  - imports que usaban `mutalambda_v2_patched` como core
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import muta_lambda as core

# Reexports (compatibilidad)
EvolveConfig = core.EvolveConfig
MutaLambdaAgent = core.MutaLambdaAgent
run_full_test_suite = core.run_full_test_suite


def _demo_llm_fn(prompt: str) -> str:
    # Stub determinista compatible con el core.
    try:
        last_line = prompt.strip().splitlines()[-1]
        return core.ASTMutator.apply_random_mutation(last_line)
    except Exception:
        return "def solution():\n    return 42"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MutaLambda Agent (alias to muta_lambda.py)"
    )
    parser.add_argument("--islands", type=int, default=3)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--pop-size", type=int, default=6)
    parser.add_argument(
        "--topology",
        default="ring",
        choices=["ring", "fully_connected", "random"],
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
    args = parser.parse_args()

    logging.getLogger("MutaLambda").setLevel(args.log_level)

    if args.test:
        ok = run_full_test_suite()
        sys.exit(0 if ok else 1)

    seed = (
        "def compute_sum(n):\n"
        "    total = 0\n"
        "    for i in range(n):\n"
        "        total += i\n"
        "    return total\n"
    )

    cfg = EvolveConfig(
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
    )

    agent = MutaLambdaAgent(
        config=cfg,
        test_cases=[],
        llm_fn=_demo_llm_fn,
        timeout_sec=5.0,
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
