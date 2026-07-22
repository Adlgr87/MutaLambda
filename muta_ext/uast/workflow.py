#!/usr/bin/env python3
"""UAST mutation workflow orchestration."""
import logging
import random
from typing import Optional

from muta_ext.uast.core_uast import CoreUAST, Node
from muta_ext.uast.adapters import get_adapter
from muta_ext.uast.emitters import PythonEmitter
from muta_ext.uast.mutators.base_mutator import (
    BaseMutator, SwapConditionMutator, NegateConditionMutator,
    LoopBoundMutator, ReorderStatementsMutator, InlineVariableMutator
)

_logger = logging.getLogger(__name__)

# Default mutators available
_DEFAULT_MUTATORS = {
    "SwapConditionMutator": SwapConditionMutator,
    "NegateConditionMutator": NegateConditionMutator,
    "LoopBoundMutator": LoopBoundMutator,
    "ReorderStatementsMutator": ReorderStatementsMutator,
    "InlineVariableMutator": InlineVariableMutator,
}


class UASTWorkflow:
    """Orchestrate UAST-based mutation workflow."""

    def __init__(self, use_uast: bool = False, mutator_names: Optional[list[str]] = None, seed: Optional[int] = None):
        self.use_uast = use_uast
        self._adapter_registry = {}
        self._emitter = PythonEmitter()
        self._mutator_names = mutator_names or list(_DEFAULT_MUTATORS.keys())
        self._seed = seed
        self._rng = random.Random(seed) if seed is not None else random.Random()

    def _get_mutator(self, name: str) -> Optional[BaseMutator]:
        """Get a mutator instance by name."""
        mutator_cls = _DEFAULT_MUTATORS.get(name)
        if mutator_cls is None:
            _logger.warning(f"Unknown mutator: {name}")
            return None
        return mutator_cls()

    def parse(self, source: str, language: str = "python") -> CoreUAST:
        """Parse source to CoreUAST."""
        adapter = get_adapter(language)
        if not adapter.can_parse(source):
            raise ValueError(f"Cannot parse {language} source")
        return adapter.parse_to_uast(source)

    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST back to source."""
        return self._emitter.emit(uast)

    def mutate(self, uast: CoreUAST, mutator_name: Optional[str] = None) -> CoreUAST:
        """Apply mutation to CoreUAST.
        
        Returns a NEW mutated UAST (immutability preserved).
        If mutation fails, returns the original unchanged.
        """
        mutator_names = [mutator_name] if mutator_name else self._mutator_names
        
        # Select a random mutator
        chosen_name = self._rng.choice(mutator_names)
        mutator = self._get_mutator(chosen_name)
        
        if mutator is None:
            _logger.warning(f"No mutator found for {chosen_name}")
            return uast
        
        try:
            mutated = mutator.mutate(uast, self._rng)
            # Verify mutation actually changed something
            if mutated is not None and mutated != uast:
                return mutated
            return uast
        except Exception as e:
            _logger.warning(f"Mutation {chosen_name} failed: {e}")
            return uast

    def process(self, source: str, language: str = "python") -> str:
        """Full parse → mutate → emit cycle."""
        uast = self.parse(source, language)
        mutated = self.mutate(uast)
        return self.emit(mutated)


# Convenience function
def process_with_uast(source: str, language: str = "python", use_uast: bool = False) -> str:
    """Process source through UAST workflow (or bypass if use_uast=False)."""
    workflow = UASTWorkflow(use_uast=use_uast)
    return workflow.process(source, language)