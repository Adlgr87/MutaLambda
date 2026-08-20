"""Centralized logging helpers for MutaLambda (FIX 2.3).

Does not force a global reconfiguration of all modules; provides a single
factory so new code uses a consistent logger name hierarchy.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

ROOT_LOGGER_NAME = "MutaLambda"


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a child logger under the MutaLambda hierarchy.

    Args:
        name: Module or component name. If it already starts with
            ``MutaLambda``, it is used as-is. ``None`` → root project logger.
    """
    if not name or name == ROOT_LOGGER_NAME:
        return logging.getLogger(ROOT_LOGGER_NAME)
    if name.startswith(ROOT_LOGGER_NAME + ".") or name == ROOT_LOGGER_NAME:
        return logging.getLogger(name)
    # Prefer short component names: get_logger("sandbox") → MutaLambda.sandbox
    if name.startswith("muta_") or "/" in name or name.endswith(".py"):
        # __name__ style: muta_lambda / path — use last segment
        short = name.replace("\\", "/").split("/")[-1].removesuffix(".py")
        return logging.getLogger(f"{ROOT_LOGGER_NAME}.{short}")
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str | Path] = None,
) -> None:
    """Configure root MutaLambda logging once (safe to call multiple times)."""
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Avoid duplicate handlers on re-entry
    if logger.handlers:
        return
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    logger.addHandler(console)
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    # Env override used elsewhere
    env_level = os.environ.get("MUTALAMBDA_LOG_LEVEL")
    if env_level:
        logger.setLevel(getattr(logging, env_level.upper(), logging.INFO))
