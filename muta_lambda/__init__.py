"""
MutaLambda Agent — slim orchestrator after module extraction.

The large implementation has been split into focused modules:
- [`llm_backend.py`](llm_backend.py:1) for LLM adapters
- [`models.py`](models.py:1) for core dataclasses and LineageGraph
- [`evolution_engine.py`](evolution_engine.py:1) for AST mutation and prompt contracts
- [`island.py`](island.py:1) for Island evolution
- [`migration.py`](migration.py:1) for MigrationBus
- [`sandbox.py`](sandbox.py:1) for hard-limited subprocess evaluation
- [`archive.py`](archive.py:1) for SolutionArchive
- [`prompt_evolver.py`](prompt_evolver.py:1) for basic prompt evolution
"""

from __future__ import annotations

import ast
import copy
import json
import logging
import os
from pathlib import Path
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

import numpy as np

from fitness_vector import FitnessVector
from hfc_tiers import HFCTierConfig, HFCLeagueEngine
from island_evolution import IslandPool, IslandDiversity, IslandSnapshot

# Phase 6.5: keep heavy / optional deps out of the module-import path so that
# importing `muta_lambda` (e.g. under pytest) does not double-spawn the worker
# pool or pay the faiss / sentence-transformers startup cost. They are bound
# lazily on first use instead of at import time.
faiss = None  # type: ignore[assignment]
SentenceTransformer = None  # type: ignore[assignment,misc]

# ─── Logging global ───────────────────────────────────────────────────────────
_LOG_LEVEL = os.environ.get("MUTALAMBDA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MutaLambda")

PROJECT_NAME = "MutaLambda"

# ─── Re-exported modules/classes for backward-compatible imports ─────────────
from archive import SolutionArchive
from evolution_engine import ASTMutator, CodeRegion, CoreEvolutionEngine
from mutation_filters import run_all_filters, _filter_mutant, ProfileMode
from island import Island
from llm_backend import LLMBackend, _resolve_llm_backend
from migration import MigrationBus
from models import (
    ArchivedSolution,
    EvalResult,
    Individual,
    IslandConfig,
    LineageGraph,
    LineageNode,
    PromptGenome,
)
from prompt_evolver import PromptEvolver
from sandbox import SandboxEvaluator
from extensions import ExtensionRegistry, ExtensionContext
from rng_session import RNGSession
from event_bus import (
    EventBus,
    CommandQueue,
    GENERATION_STARTED,
    GENERATION_COMPLETED,
    CHECKPOINT_SAVED,
    RUN_STARTED,
    RUN_COMPLETED,
    MIGRATION_APPLIED,
)
from workflow_protocol import ProtocolTrace


# ── EvolveConfig + tipos relacionados (extracted to muta_lambda/config.py, Phase 2A) ──
# Re-exportados para que ``from muta_lambda import EvolveConfig,
# EarlyStopMonitor, GenerationResult`` siga funcionando.
from muta_lambda.config import (  # noqa: F401
    EvolveConfig,
    EarlyStopMonitor,
    GenerationResult,
)




# ── Re-export MutaLambdaAgent from the dedicated ``agent`` module ────────
# (Phase 2B extraction). The class plus its helper methods live in
# ``muta_lambda/agent.py``; it is imported *after* all of the symbols above
# have been bound so that ``agent.py`` can resolve them via
# ``from muta_lambda import ...`` without a circular-import error.
from muta_lambda.agent import MutaLambdaAgent  # noqa: E402,F401


# ── Re-export MutaLambdaSession from the dedicated ``session`` module ─────
# (Phase 2C extraction). Imported *after* ``MutaLambdaAgent`` is bound so that
# ``session.py`` can resolve its ``"MutaLambdaAgent"`` type-hint via
# ``from muta_lambda import ...`` without a circular-import error.
from muta_lambda.session import MutaLambdaSession  # noqa: E402,F401


# ── CLI entry points (Phase 2D extraction) ──
# ``main()``, ``run_full_test_suite()``, ``_demo_llm_fn`` now live in
# ``muta_lambda/cli/entrypoints.py``. Re-exported for backward compat.
from cli.entrypoints import main, run_full_test_suite, _demo_llm_fn  # noqa: E402,F401

__all__ = [  # noqa: C800
    # Configuration
    "EvolveConfig", "EarlyStopMonitor", "GenerationResult",
    # Core types
    "Individual", "LineageGraph", "LineageNode", "PromptGenome",
    "EvalResult", "IslandConfig", "ArchivedSolution",
    # Modules
    "Island", "MigrationBus", "SandboxEvaluator", "SolutionArchive",
    "ASTMutator", "CodeRegion", "CoreEvolutionEngine",
    "LLMBackend", "_resolve_llm_backend",
    "PromptEvolver", "ProfileMode",
    "run_all_filters", "_filter_mutant",
    # Event bus
    "EventBus", "CommandQueue",
    "RUN_STARTED", "RUN_COMPLETED", "GENERATION_STARTED",
    "GENERATION_COMPLETED", "CHECKPOINT_SAVED", "MIGRATION_APPLIED",
    # Extensions
    "ExtensionRegistry", "ExtensionContext", "RNGSession", "ProtocolTrace",
    "IslandPool", "IslandDiversity", "IslandSnapshot",
    "HFCLeagueEngine", "HFCTierConfig",
    # Top-level classes
    "MutaLambdaAgent", "MutaLambdaSession",
    # CLI
    "main", "run_full_test_suite",
]

if __name__ == "__main__":
    main()
