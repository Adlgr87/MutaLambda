"""MutaLambda CLI package."""

# Single source of truth: pyproject.toml ([project] version).
try:
    from importlib.metadata import version as _version

    __version__ = _version("mutalambda")
except Exception:  # paquete no instalado (uso desde el arbol fuente)
    __version__ = "4.0.0"

from cli.main import MutaLambdaCLI, InteractiveREPL
from cli.animator import RetroAnimator
from cli.config_manager import ConfigManager
from cli.checkpoint_manager import CheckpointManager

__all__ = [
    "MutaLambdaCLI",
    "InteractiveREPL",
    "RetroAnimator",
    "ConfigManager",
    "CheckpointManager",
]
