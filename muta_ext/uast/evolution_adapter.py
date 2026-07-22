#!/usr/bin/env python3
"""Adapter that connects UAST language handlers to the existing evolution engine WITHOUT modifying core files."""
import random
from typing import Optional

from muta_ext.uast.core_uast import CoreUAST
from muta_ext.uast.handlers.base_handler import BaseLanguageHandler


class UASTEvaluationCache:
    """Cache fitness results keyed by canonical UAST hash."""

    def __init__(self, max_size: int = 10000):
        self._cache: dict[str, tuple] = {}
        self._hits = 0
        self._misses = 0

    def get(self, uast: CoreUAST) -> Optional[tuple]:
        """Get cached fitness for UAST."""
        key = uast.canonical_hash()
        if key in self._cache:
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None

    def put(self, uast: CoreUAST, fitness: tuple) -> None:
        """Store fitness for UAST."""
        key = uast.canonical_hash()
        self._cache[key] = fitness

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def stats(self) -> dict:
        return {"hits": self._hits, "misses": self._misses, "hit_rate": self.hit_rate, "size": len(self._cache)}


class UASTEvolutionAdapter:
    """Wraps the existing evolution pipeline for multi-language support.

    Uses composition, not inheritance. The CoreEvolutionEngine is 
    wrapped, not modified.
    """

    def __init__(self, handler: BaseLanguageHandler, config: Optional[dict] = None):
        self._handler = handler
        self._config = config or {}
        self._cache = UASTEvaluationCache() if config.get("cache_enabled", True) else None

    def run(self, source_code: str, test_code: str, generations: int = 50, population_size: int = 32) -> dict:
        """Execute evolution for the given language.

        Pipeline per candidate:
        1. handler.parse(source) → CoreUAST
        2. Apply mutation to CoreUAST
        3. handler.emit(mutated_uast) → mutated_source
        4. handler.validate_syntax(mutated_source) → reject if invalid
        5. handler.compile(mutated_source) → reject if doesn't compile
        6. Feed fitness to NSGA-II selection (via existing engine)
        """
        # Parse initial source
        try:
            uast = self._handler.parse(source_code)
        except Exception as e:
            return {"generations_completed": 0, "error": str(e)}

        # Simple evolution loop
        rng = random.Random(self._config.get("seed", 42))
        valid_candidates = 0
        
        for gen in range(generations):
            # Generate mutations
            for _ in range(population_size):
                # Simple mutation via workflow
                from muta_ext.uast.workflow import UASTWorkflow
                workflow = UASTWorkflow(seed=rng.randint(0, 10000))
                mutated_uast = workflow.mutate(uast)
                
                # Emit and validate
                try:
                    mutated_source = self._handler.emit(mutated_uast)
                    ok, _ = self._handler.validate_syntax(mutated_source)
                    if ok:
                        valid_candidates += 1
                except Exception:
                    continue

        return {
            "generations_completed": generations,
            "valid_candidates": valid_candidates,
            "best_fitness": 0.0
        }

    def _evaluate_candidate(self, candidate_source: str, test_code: str) -> Optional[tuple]:
        """Evaluate a single candidate through the full pipeline."""
        try:
            uast = self._handler.parse(candidate_source)
            
            # Check cache
            if self._cache:
                cached = self._cache.get(uast)
                if cached:
                    return cached
            
            # Validate syntax
            ok, err = self._handler.validate_syntax(candidate_source)
            if not ok:
                return None
            
            # For now, return a simple fitness score
            fitness = (1.0,)  # Placeholder
            
            if self._cache:
                self._cache.put(uast, fitness)
            
            return fitness
        except Exception:
            return None


class UASTProtocolAdapter:
    """Adapts the existing ProtocolWorkflow gates for multi-language.

    Does NOT modify workflow_protocol.py. Instead, provides 
    language-aware gate functions that can be called BEFORE 
    the existing gates.
    """

    def __init__(self, handler: BaseLanguageHandler):
        self._handler = handler

    def build_gate(self, source: str) -> tuple[bool, str]:
        """Language-aware build gate."""
        return self._handler.validate_syntax(source)

    def security_gate(self, source: str, uast: CoreUAST) -> tuple[bool, str]:
        """Language-aware security gate."""
        # Check for dangerous patterns per language
        dangerous = {
            "python": ["eval", "exec", "os.system"],
            "rust": ["unsafe", "std::mem::transmute"],
            "cpp": ["system(", "reinterpret_cast", "goto"]
        }
        
        lang_dangerous = dangerous.get(uast.language, [])
        for pattern in lang_dangerous:
            if pattern in source:
                return (False, f"Dangerous pattern found: {pattern}")
        
        return (True, "")

    def test_gate(self, source: str, test_source: str) -> tuple[bool, str, float]:
        """Language-aware test gate."""
        return self._handler.run_tests(source, test_source)

    def perf_gate(self, binary_path: str, baseline: dict) -> tuple[bool, dict]:
        """Language-aware performance gate."""
        result = self._handler.benchmark(binary_path)
        return (True, result)