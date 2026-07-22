"""Base emitter interface for emitting CoreUAST back to source."""
from abc import ABC, abstractmethod
from typing import Optional


class BaseEmitter(ABC):
    """Abstract base for language emitters."""

    @abstractmethod
    def emit(self, uast: "CoreUAST") -> str:
        """Emit CoreUAST back to source code."""
        raise NotImplementedError

    @abstractmethod
    def can_emit(self, uast: "CoreUAST") -> bool:
        """Check if this emitter can handle the UAST."""
        raise NotImplementedError

    @property
    @abstractmethod
    def language(self) -> str:
        """Return the language this emitter produces."""
        raise NotImplementedError