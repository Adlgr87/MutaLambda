"""Base emitter interface for emitting CoreUAST back to source."""
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from muta_ext.uast.core_uast import CoreUAST


def format_source(code: str, command: List[str], timeout: float = 10) -> str:
    """Run an external formatter over ``code``, returning ``code`` unchanged on failure.

    The formatter is skipped when its executable is not on PATH.
    """
    if not command or not shutil.which(command[0]):
        return code
    try:
        result = subprocess.run(
            command,
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return code


class BaseEmitter(ABC):
    """Abstract base for language emitters."""

    #: Language this emitter produces.
    language: str = ""

    #: External formatter invoked on emitted source (empty disables formatting).
    formatter_command: List[str] = []

    @abstractmethod
    def emit(self, uast: "CoreUAST") -> str:
        """Emit CoreUAST back to source code."""
        raise NotImplementedError

    def can_emit(self, uast: "CoreUAST") -> bool:
        """Check if this emitter can handle the UAST."""
        return uast.language == self.language

    def _format(self, code: str) -> str:
        """Format emitted source with the language formatter, if available."""
        return format_source(code, self.formatter_command)
