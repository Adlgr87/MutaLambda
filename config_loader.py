"""
Config loader — YAML/TOML declarative configuration for MutaLambda.

Provides validation and conversion to EvolveConfig dataclass.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# YAML is optional — fallback gracefully
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


# ── Schema validation ───────────────────────────────────────────────

_REQUIRED_KEYS: Dict[str, list] = {
    "evolution": ["num_islands", "generations", "topology"],
    "population": ["size", "top_k", "migration_interval"],
    "sandbox": ["timeout_sec"],
    "checkpoint": ["interval", "dir"],
}

_VALID_VALUES: Dict[str, list] = {
    "evolution.topology": ["ring", "fully_connected", "random", "mesh"],
    "logging.level": ["DEBUG", "INFO", "WARNING", "ERROR"],
}

_DEFAULTS: Dict[str, Any] = {
    "evolution.num_islands": 4,
    "evolution.generations": 50,
    "evolution.topology": "ring",
    "evolution.early_stop_patience": 15,
    "evolution.early_stop_delta": 0.001,
    "evolution.novelty_alpha": 0.15,
    "population.size": 8,
    "population.top_k": 3,
    "population.migration_interval": 10,
    "population.migrants_per_island": 2,
    "sandbox.timeout_sec": 10.0,
    "sandbox.max_workers": 4,
    "archive.enabled": True,
    "archive.max_size": 10000,
    "archive.prune_threshold": 50,
    "archive.embedder_model": "all-MiniLM-L6-v2",
    "prompt_evolution.enabled": True,
    "prompt_evolution.pop_size": 6,
    "prompt_evolution.elite_frac": 0.5,
    "checkpoint.interval": 10,
    "checkpoint.dir": "checkpoints",
    "checkpoint.save_archive": True,
    "checkpoint.save_prompts": True,
    "logging.level": "INFO",
    "logging.log_file": None,
    "reproducibility.seed": None,
    "reproducibility.track_git_commit": True,
}


def _get_nested(cfg: Dict, path: str, default: Any = None) -> Any:
    """Get value from nested dict by dot-separated path."""
    keys = path.split(".")
    val: Any = cfg
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k, default)
        else:
            return default
        if val is None:
            return default
    return val


def _set_nested(cfg: Dict, path: str, value: Any) -> None:
    """Set value in nested dict, creating intermediate dicts as needed."""
    keys = path.split(".")
    d = cfg
    for k in keys[:-1]:
        if k not in d or not isinstance(d[k], dict):
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value


def validate_config(raw: Dict[str, Any]) -> list:
    """
    Validate raw config dict against schema.

    Returns list of error messages (empty = valid).
    """
    errors: list = []

    # Check required top-level sections
    for section, keys in _REQUIRED_KEYS.items():
        if section not in raw:
            errors.append(f"Missing required section: '{section}'")
            continue
        for key in keys:
            if key not in raw.get(section, {}):
                errors.append(f"Missing required key: '{section}.{key}'")

    # Check valid values
    for path, valid in _VALID_VALUES.items():
        val = _get_nested(raw, path)
        if val is not None and val not in valid:
            errors.append(
                f"Invalid value for '{path}': '{val}'. "
                f"Must be one of {valid}"
            )

    # Numeric bounds
    alpha = _get_nested(raw, "evolution.novelty_alpha")
    if alpha is not None and not (0.0 <= alpha <= 1.0):
        errors.append("evolution.novelty_alpha must be between 0.0 and 1.0")

    pop_size = _get_nested(raw, "population.size", 8)
    top_k = _get_nested(raw, "population.top_k", 3)
    if top_k > pop_size:
        errors.append("population.top_k must be ≤ population.size")

    return errors


def apply_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing values with defaults from the schema."""
    cfg = raw.copy() if raw else {}
    for path, default in _DEFAULTS.items():
        if _get_nested(cfg, path) is None:
            _set_nested(cfg, path, default)
    return cfg


def load_yaml(path: str | Path) -> Dict[str, Any]:
    """
    Load and validate a YAML configuration file.

    Raises ValueError on validation errors.
    """
    if yaml is None:
        raise ImportError(
            "YAML support requires PyYAML: pip install pyyaml"
        )

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError(f"Empty config file: {path}")

    # Apply defaults
    cfg = apply_defaults(raw)

    # Validate
    errors = validate_config(cfg)
    if errors:
        raise ValueError(
            "Config validation failed:\n  - " + "\n  - ".join(errors)
        )

    return cfg