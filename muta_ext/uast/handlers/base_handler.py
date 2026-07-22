#!/usr/bin/env python3
"""Base language handler interface for UAST multi-language support."""
from abc import ABC, abstractmethod
from typing import Any, Optional

from muta_ext.uast.core_uast import CoreUAST


class BaseLanguageHandler(ABC):
    """Interface for language handlers. All language adapters 
    must implement this to integrate with the evolution system."""

    @abstractmethod
    def parse(self, source: str) -> CoreUAST:
        """Parse source code to CoreUAST."""
        ...

    @abstractmethod
    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST back to source code."""
        ...

    @abstractmethod
    def validate_syntax(self, source: str) -> tuple[bool, str]:
        """Validate syntax without compilation."""
        ...

    @abstractmethod
    def compile(self, source: str, output_path: str) -> tuple[bool, str]:
        """Compile source to binary."""
        ...

    @abstractmethod
    def run_tests(self, source: str, test_source: str) -> tuple[bool, str, float]:
        """Run tests on compiled source."""
        ...

    @abstractmethod
    def benchmark(self, binary_path: str, iterations: int = 1000) -> dict:
        """Run benchmark on compiled binary."""
        ...

    @abstractmethod
    def roundtrip(self, source: str) -> str:
        """Parse → CoreUAST → Emit roundtrip."""
        ...