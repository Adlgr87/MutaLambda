"""Shared non-magic constants (FIX 3.5 subset — high-traffic values only)."""

from __future__ import annotations

from typing import Final

# Hashing
HASH_ALGORITHM: Final[str] = "sha256"
CODE_HASH_HEX_LENGTH: Final[int] = 64

# Comparison defaults
FLOAT_REL_TOL: Final[float] = 1e-9
FLOAT_ABS_TOL: Final[float] = 1e-12

# Checkpoints
DEFAULT_CHECKPOINT_INTERVAL: Final[int] = 10
CORE_CHECKPOINT_FORMAT: Final[str] = "mutalambda-core-json"
CORE_CHECKPOINT_VERSION: Final[str] = "4.0.0"

# Logging
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
ROOT_LOGGER_NAME: Final[str] = "MutaLambda"

# Evolution defaults (high-traffic)
DEFAULT_NUM_ISLANDS: Final[int] = 4
DEFAULT_GENERATIONS: Final[int] = 50
DEFAULT_POPULATION_SIZE: Final[int] = 8
MIN_POPULATION_SIZE: Final[int] = 2
DEFAULT_TOP_K: Final[int] = 3
DEFAULT_MIGRATION_INTERVAL: Final[int] = 10
DEFAULT_SANDBOX_TIMEOUT_SEC: Final[float] = 10.0
DEFAULT_SANDBOX_WORKERS: Final[int] = 4
DEFAULT_ARCHIVE_DEDUPE_SIMILARITY: Final[float] = 0.98
DEFAULT_NOVELTY_ALPHA: Final[float] = 0.15
