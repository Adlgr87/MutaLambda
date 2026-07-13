"""
Config loader — YAML declarative configuration for MutaLambda.

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
    "evolution.topology": ["ring", "fully_connected", "random", "mesh", "spatial_grid"],
    "logging.level": ["DEBUG", "INFO", "WARNING", "ERROR"],
    "llm.backend": [
        "ollama",
        "openai",
        "anthropic",
        "openrouter",
        "mistral",
    ],
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
    "checkpoint.enabled": True,
    "checkpoint.dir": "checkpoints",
    "checkpoint.save_archive": True,
    "checkpoint.save_prompts": True,
    "workflow.enabled": True,
    "workflow.max_retries": 1,
    "workflow.correctness_threshold": 1.0,
    "workflow.require_score_improvement": False,
    "workflow.enforce_security": True,
    "workflow.trace_limit": 200,
    "logging.level": "INFO",
    "logging.log_file": None,
    "llm.backend": "ollama",
    "llm.model": "llama3.2:3b",
    "llm.timeout_sec": 60.0,
    "llm.temperature": 0.2,
    "reproducibility.seed": None,
    "reproducibility.track_git_commit": True,
    "hfc.enabled": False,
    "hfc.lambda_clones": 8,
    "hfc.tier1_size": 100,
    "hfc.tier2_size": 50,
    "hfc.tier3_size": 10,
    "hfc.top_down_distillation": True,
    "hfc.top_down_interval": 5,
    "hfc.promotion_correctness": 1.0,
    "thc.enabled": False,
    "thc.max_transfers_per_generation": 1,
    "thc.min_donor_score": 0.0,
    "thc.validate_in_sandbox": True,
    "advanced_selection.enabled": False,
    "advanced_selection.fitness_weight": 1.0,
    "advanced_selection.novelty_weight": 0.15,
    "advanced_selection.entropy_weight": 0.20,
    "advanced_selection.discovery_weight": 0.35,
    "dialectic.enabled": False,
    "dialectic.critique_intensity": "medium",
    "spatial.enabled": False,
    "spatial.neighborhood": "moore",
    "pattern_memory.enabled": False,
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

    prompt_pop_size = _get_nested(raw, "prompt_evolution.pop_size")
    if prompt_pop_size is not None and prompt_pop_size <= 0:
        errors.append("prompt_evolution.pop_size must be positive")

    elite_frac = _get_nested(raw, "prompt_evolution.elite_frac")
    if elite_frac is not None and not (0.0 <= elite_frac <= 1.0):
        errors.append("prompt_evolution.elite_frac must be between 0.0 and 1.0")

    llm_timeout = _get_nested(raw, "llm.timeout_sec")
    if llm_timeout is not None and llm_timeout <= 0:
        errors.append("llm.timeout_sec must be positive")

    llm_temperature = _get_nested(raw, "llm.temperature")
    if llm_temperature is not None and not (0.0 <= llm_temperature <= 2.0):
        errors.append("llm.temperature must be between 0.0 and 2.0")

    hfc_lambda = _get_nested(raw, "hfc.lambda_clones")
    if hfc_lambda is not None and hfc_lambda < 0:
        errors.append("hfc.lambda_clones must be non-negative")

    for path in ("hfc.tier1_size", "hfc.tier2_size", "hfc.tier3_size", "hfc.top_down_interval"):
        value = _get_nested(raw, path)
        if value is not None and value <= 0:
            errors.append(f"{path} must be positive")

    correctness = _get_nested(raw, "hfc.promotion_correctness")
    if correctness is not None and not (0.0 <= correctness <= 1.0):
        errors.append("hfc.promotion_correctness must be between 0.0 and 1.0")

    workflow_retries = _get_nested(raw, "workflow.max_retries")
    if workflow_retries is not None and workflow_retries < 0:
        errors.append("workflow.max_retries must be non-negative")

    workflow_threshold = _get_nested(raw, "workflow.correctness_threshold")
    if workflow_threshold is not None and not (0.0 <= workflow_threshold <= 1.0):
        errors.append("workflow.correctness_threshold must be between 0.0 and 1.0")

    workflow_trace_limit = _get_nested(raw, "workflow.trace_limit")
    if workflow_trace_limit is not None and workflow_trace_limit <= 0:
        errors.append("workflow.trace_limit must be positive")

    thc_transfers = _get_nested(raw, "thc.max_transfers_per_generation")
    if thc_transfers is not None and thc_transfers < 0:
        errors.append("thc.max_transfers_per_generation must be non-negative")

    for path in (
        "advanced_selection.fitness_weight",
        "advanced_selection.novelty_weight",
        "advanced_selection.entropy_weight",
        "advanced_selection.discovery_weight",
    ):
        value = _get_nested(raw, path)
        if value is not None and value < 0:
            errors.append(f"{path} must be non-negative")

    neighborhood = _get_nested(raw, "spatial.neighborhood")
    if neighborhood is not None and neighborhood not in ("moore", "von_neumann"):
        errors.append("spatial.neighborhood must be 'moore' or 'von_neumann'")

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
