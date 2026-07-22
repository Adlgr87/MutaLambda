"""UAST mutation workflow orchestration."""
from typing import Optional

from muta_ext.uast.core_uast import CoreUAST, Node
from muta_ext.uast.adapters import get_adapter
from muta_ext.uast.emitters import PythonEmitter


class UASTWorkflow:
    """Orchestrate UAST-based mutation workflow."""

    def __init__(self, use_uast: bool = False):
        self.use_uast = use_uast
        self._adapter_registry = {}
        self._emitter = PythonEmitter()

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
        """Apply mutation to CoreUAST."""
        # Phase 2: Apply mutators to UAST
        # For now, just return the original (placeholder)
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