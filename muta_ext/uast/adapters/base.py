"""Base adapter interface for parsing source to CoreUAST."""
from abc import ABC, abstractmethod
from typing import Optional


class BaseAdapter(ABC):
    """Abstract base for language adapters."""

    @abstractmethod
    def parse_to_uast(self, source: str) -> "CoreUAST":
        """Parse source code to CoreUAST representation."""
        raise NotImplementedError

    @abstractmethod
    def can_parse(self, source: str) -> bool:
        """Check if this adapter can handle the source."""
        raise NotImplementedError

    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language this adapter handles."""
        raise NotImplementedError