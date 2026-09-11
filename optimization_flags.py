"""Optimization-lever flags for the MutaLambda cost-optimization layer.

Single, dependency-light loader for ``config/optimization.yaml``.  Every
lever added by the Headroom cost layer MUST be toggleable through this file
(rule 6), so all feature flags live here with a stable dotted path, e.g.
``cost_ledger.enabled`` or ``headroom.batching.enabled``.

Resolution order (first wins):
    1. Environment variables ``MUTALAMBDA_OPT_<SECTION>__<KEY>`` (the double
       underscore separates section from key, e.g.
       ``MUTALAMBDA_OPT_COST_LEDGER__ENABLED=0``).
    2. The YAML file — ``MUTALAMBDA_OPT_CONFIG`` path, else the repository
       ``config/optimization.yaml`` when present, else the built-in defaults.
    3. Built-in defaults (``DEFAULTS`` below).

Typical use::

    from optimization_flags import get_optimization_flags
    flags = get_optimization_flags()
    if flags.enabled("fitness_cache.enabled"):
        ...
    every = flags.get("checkpoint.every", 5)

The singleton is cached per-process; tests should call
``reset_optimization_flags()`` (and re-set env vars) between scenarios.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, Optional

__all__ = [
    "DEFAULTS",
    "OptimizationFlags",
    "get_optimization_flags",
    "load_optimization_config",
    "reset_optimization_flags",
    "default_config_path",
]

ENV_CONFIG_PATH = "MUTALAMBDA_OPT_CONFIG"
ENV_PREFIX = "MUTALAMBDA_OPT_"

#: Repo-relative default location of the optimization flag file.
_DEFAULT_CONFIG_RELPATH = Path("config") / "optimization.yaml"


def default_config_path() -> Path:
    """Locate ``config/optimization.yaml`` relative to this file's repo root."""
    return Path(__file__).resolve().parent / _DEFAULT_CONFIG_RELPATH


# Built-in fallback — mirrors config/optimization.yaml. Phase 0 levers are
# ON by default (observability + determinism + caching, all reversible);
# Phase 1-3 levers are OFF until their setup/acceptance is complete.
DEFAULTS: Dict[str, Dict[str, Any]] = {
    "cost_ledger": {
        "enabled": True,
        "path": "",
        "gpu_hour_usd": 0.5,
    },
    "checkpoint": {
        "every": 5,
    },
    "fitness_cache": {
        "enabled": True,
        "backend": "sqlite",
        "path": ".mutalambda/fitness_cache.db",
        "max_entries": 100000,
    },
    "deterministic_prompt": {
        "enabled": True,
    },
    "headroom": {
        "enabled": False,
        "package": "headroom-ai",
        "smart_crusher": {"enabled": False, "max_traceback_chars": 4000, "max_log_lines": 80},
        "ast_stubs": {"enabled": False, "retrieve_tool": True},
        "json_schema_output": {"enabled": False, "max_tokens": 2048},
        "batching": {"enabled": False, "batch_size": 5},
        "bandit": {"enabled": False, "ucb_c": 1.414},
    },
    "profiling_filter": {
        "enabled": False,
        "profile_seconds": 10,
        "min_cpu_pct": 0.5,
        "nanopass_check": {"enabled": False},
        "test_subset": {"enabled": False, "by_coverage": True, "max_tests": 0},
        "sandbox_top_pct": 20.0,
    },
    "economic_gate": {
        "enabled": False,
        "delta_h_threshold": 0.005,
        "stall_generations": 5,
        "gpu_hour_usd": 0.5,
        "production_cpu_savings_hour_usd": 0.0,
    },
    "bandit_reward_usd": {
        "enabled": False,
    },
    "pareto_archive": {
        "enabled": False,
        "dir": "pareto_archive",
        "warm_start": True,
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* onto *base* (dicts merge, scalars replace)."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _parse_scalar(raw: str) -> Any:
    low = raw.strip().lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _apply_env_overrides(data: Dict[str, Any]) -> Dict[str, Any]:
    """Apply ``MUTALAMBDA_OPT_<SECTION>__<KEY>`` environment overrides.

    ``__`` (double underscore) is the path separator, so nested keys work:
    ``MUTALAMBDA_OPT_HEADROOM__SMART_CRUSHER__ENABLED=1`` sets
    ``headroom.smart_crusher.enabled``.  Single underscores are part of
    names.
    """
    for name, raw in os.environ.items():
        if not name.startswith(ENV_PREFIX) or name == ENV_CONFIG_PATH:
            continue
        rest = name[len(ENV_PREFIX):]
        parts = [p.strip().lower() for p in rest.split("__")]
        parts = [p for p in parts if p]
        if len(parts) < 2:
            continue
        section, *key_path = parts
        node = data
        if not isinstance(node.get(section), dict):
            node[section] = {}
        node = node[section]
        for part in key_path[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[key_path[-1]] = _parse_scalar(raw)
    return data


def _load_yaml_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        import yaml
    except ImportError:  # pragma: no cover - yaml is a core dependency
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        import logging

        logging.getLogger("MutaLambda").warning(
            "optimization config %s unreadable (%s); using defaults", path, exc
        )
        return None
    if not isinstance(data, dict):
        return None
    # Accept both a top-level "optimization:" wrapper and a bare section map.
    if "optimization" in data and isinstance(data["optimization"], dict):
        data = data["optimization"]
    return data


class OptimizationFlags:
    """Immutable-ish view over the merged optimization flag tree."""

    def __init__(self, data: Dict[str, Any], source: str = "defaults") -> None:
        self._data = data
        self.source = source

    # ── Accessors ────────────────────────────────────────────────────────
    def get(self, dotted_path: str, default: Any = None) -> Any:
        """Fetch a value by dotted path, e.g. ``"cost_ledger.enabled"``."""
        node: Any = self._data
        for part in dotted_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def enabled(self, dotted_path: str, default: bool = False) -> bool:
        """Convenience boolean accessor: truthy flag values → ``True``."""
        value = self.get(dotted_path, default)
        if isinstance(value, bool):
            return value
        return bool(value)

    def section(self, name: str) -> Dict[str, Any]:
        value = self._data.get(name, {})
        return value if isinstance(value, dict) else {}

    def as_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self._data)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"OptimizationFlags(source={self.source!r})"


_flags_singleton: Optional[OptimizationFlags] = None


def load_optimization_config(path: Optional[str | Path] = None) -> OptimizationFlags:
    """Load flags from defaults ← YAML file ← environment overrides.

    ``path`` pins the YAML file explicitly; otherwise the repository
    ``config/optimization.yaml`` is used when it exists.
    """
    data = copy.deepcopy(DEFAULTS)
    source = "defaults"

    candidates = []
    if path is not None:
        candidates.append(Path(path))
    else:
        env_path = os.getenv(ENV_CONFIG_PATH)
        if env_path:
            candidates.append(Path(env_path))
        default_path = default_config_path()
        if default_path.exists():
            candidates.append(default_path)

    for candidate in candidates:
        file_data = _load_yaml_file(candidate)
        if file_data is not None:
            data = _deep_merge(data, file_data)
            source = str(candidate)
            break

    data = _apply_env_overrides(data)
    return OptimizationFlags(data, source=source)


def get_optimization_flags() -> OptimizationFlags:
    """Cached per-process flags (reload only after ``reset_optimization_flags``)."""
    global _flags_singleton
    if _flags_singleton is None:
        _flags_singleton = load_optimization_config()
    return _flags_singleton


def reset_optimization_flags() -> None:
    """Drop the cached singleton (used by tests after mutating env vars)."""
    global _flags_singleton
    _flags_singleton = None
