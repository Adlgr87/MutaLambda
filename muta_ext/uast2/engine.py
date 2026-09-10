#!/usr/bin/env python3
"""Engine selection for UAST v2 — feature flag, shadow mode, one entry point.

This is the module the rest of the codebase is expected to talk to::

    from muta_ext.uast2 import engine

    config = engine.resolve_engine_config("config.yaml")     # uast.engine: v2
    document = engine.parse(source, config=config)           # v2 CoreUAST
    result = engine.mutate(document, seed=7)                 # in-place pipeline
    print(document.emit())

Behaviour is *unchanged* unless the flag is turned on: ``uast.engine`` defaults
to ``"legacy"`` and, in that mode, :func:`parse` returns exactly the object the
legacy adapter produces.  Rollback is a one-line config change.
"""

from __future__ import annotations

import os
import typing as T
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Optional, Union

from muta_ext.uast2 import core as v2
from muta_ext.uast2 import metrics
from muta_ext.uast2.passes import Pipeline, PipelineResult
from muta_ext.uast2.shadow import ShadowResult, shadow_parse

__all__ = [
    "EngineConfig",
    "resolve_engine_config",
    "parse",
    "parse_to_v2",
    "to_legacy",
    "to_v2",
    "is_v2",
    "emit",
    "mutate",
    "verify_document",
    "engine_metrics",
]

VALID_ENGINES = ("legacy", "v2")


@dataclass
class EngineConfig:
    """Resolved UAST engine settings."""

    engine: str = "legacy"
    shadow: bool = False
    verify: bool = False
    strict: bool = False
    arena: bool = False
    extended_dialect: bool = False
    shadow_mode: str = "exact"
    security_profile: str = "balanced"
    languages: T.List[str] = field(default_factory=lambda: ["python", "rust"])

    def __post_init__(self) -> None:
        if self.engine not in VALID_ENGINES:
            raise ValueError(
                f"uast.engine must be one of {VALID_ENGINES}, got {self.engine!r}"
            )

    @property
    def use_v2(self) -> bool:
        """True when the v2 engine is selected."""
        return self.engine == "v2"

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable view (used by CLI diagnostics)."""
        return {
            "engine": self.engine,
            "shadow": self.shadow,
            "verify": self.verify,
            "strict": self.strict,
            "arena": self.arena,
            "extended_dialect": self.extended_dialect,
            "shadow_mode": self.shadow_mode,
            "languages": list(self.languages),
        }


def _from_mapping(data: Dict[str, Any]) -> Dict[str, Any]:
    section = data.get("uast") if isinstance(data, dict) else None
    return section if isinstance(section, dict) else {}


def resolve_engine_config(
    config: Optional[Any] = None,
    engine: Optional[str] = None,
    shadow: Optional[bool] = None,
    verify: Optional[bool] = None,
    strict: Optional[bool] = None,
    arena: Optional[bool] = None,
    extended: Optional[bool] = None,
) -> EngineConfig:
    """Build an :class:`EngineConfig` from config objects, dicts, YAML or env vars.

    Accepted sources (first one wins per field):

    1. explicit keyword overrides,
    2. an ``EngineConfig`` / ``MutaLambdaConfig`` instance, ``dict`` or YAML path,
    3. environment (``MUTALAMBDA_UAST_ENGINE`` / ``MUTALAMBDA_UAST_SHADOW``),
    4. built-in defaults (``legacy``, no shadow).
    """
    if isinstance(config, EngineConfig):  # already resolved: only override fields
        overrides = {
            "engine": engine,
            "shadow": shadow,
            "verify": verify,
            "strict": strict,
            "arena": arena,
            "extended_dialect": extended,
        }
        return replace(
            config, **{key: value for key, value in overrides.items() if value is not None}
        )

    section: Dict[str, Any] = {}

    if config is not None:
        if isinstance(config, (str, Path)):
            from config_loader import load_yaml

            section = _from_mapping(load_yaml(config))
        elif isinstance(config, dict):
            section = _from_mapping(config)
        else:  # MutaLambdaConfig / EvolveConfig style objects
            uast = getattr(config, "uast", None)
            if uast is not None:
                if hasattr(uast, "model_dump"):
                    section = dict(uast.model_dump())
                elif hasattr(uast, "__dict__"):
                    section = dict(vars(uast))
                elif isinstance(uast, dict):
                    section = dict(uast)
            if not section:
                section = {
                    "engine": getattr(config, "uast_engine", None),
                    "shadow": getattr(config, "uast_shadow", None),
                    "verify": getattr(config, "uast_verify", None),
                    "strict": getattr(config, "uast_strict", None),
                    "supported_languages": getattr(
                        config, "uast_supported_languages", None
                    ),
                }
                section = {key: value for key, value in section.items() if value is not None}

    env_engine = os.environ.get("MUTALAMBDA_UAST_ENGINE")
    env_shadow = os.environ.get("MUTALAMBDA_UAST_SHADOW")

    resolved_engine = (
        engine
        or section.get("engine")
        or ("v2" if section.get("use_uast_v2") else None)
        or env_engine
        or "legacy"
    )
    resolved_shadow = shadow
    if resolved_shadow is None and "shadow" in section:
        resolved_shadow = bool(section.get("shadow"))
    if resolved_shadow is None and env_shadow is not None:
        resolved_shadow = env_shadow.strip().lower() in ("1", "true", "yes", "on")
    if resolved_shadow is None:
        resolved_shadow = False

    resolved_verify = verify if verify is not None else bool(section.get("verify", False))
    resolved_strict = strict if strict is not None else bool(section.get("strict", False))
    resolved_arena = arena if arena is not None else bool(section.get("arena", False))
    resolved_extended = (
        extended if extended is not None else bool(section.get("extended_dialect", False))
    )

    return EngineConfig(
        engine=str(resolved_engine),
        shadow=bool(resolved_shadow),
        verify=bool(resolved_verify),
        strict=bool(resolved_strict),
        arena=bool(resolved_arena),
        extended_dialect=bool(resolved_extended),
        shadow_mode=str(section.get("shadow_mode", "exact")),
        security_profile=str(section.get("security_profile", "balanced")),
        languages=list(section.get("supported_languages") or ["python", "rust"]),
    )


def parse(
    source: str,
    language: str = "python",
    config: Optional[Any] = None,
    engine: Optional[str] = None,
    shadow: Optional[bool] = None,
    extended: Optional[bool] = None,
    prepare: Optional[bool] = None,
    arena: Optional[Any] = None,
    verify: Optional[bool] = None,
    strict: Optional[bool] = None,
    original_source: Optional[str] = None,
) -> Any:
    """Parse *source* with the configured engine (legacy by default).

    Returns a legacy ``CoreUAST`` when ``engine == "legacy"`` (byte-for-byte the
    old behaviour) and a mutable :class:`muta_ext.uast2.core.CoreUAST` when
    ``engine == "v2"``.
    """
    settings = resolve_engine_config(
        config,
        engine=engine,
        shadow=shadow,
        verify=verify,
        strict=strict,
        arena=bool(arena) if arena else None,
        extended=extended,
    )

    if settings.shadow:
        # Never allowed to break the caller: shadow failures are metrics + logs.
        shadow_parse(source, language=language, mode=settings.shadow_mode, extended=extended)

    if not settings.use_v2:
        from muta_ext.uast.adapters import get_adapter

        document = get_adapter(language).parse_to_uast(source)
        metrics.incr("uast2.parse.legacy")
        if settings.verify:
            verify_document(
                document,
                strict=settings.strict,
                original_source=original_source,
                language=language,
                security_profile=settings.security_profile,
            )
        return document

    document = _parse_v2(
        source,
        language=language,
        extended=settings.extended_dialect if extended is None else extended,
        arena=arena,
        prepare=True if prepare is None else prepare,
    )
    metrics.incr("uast2.parse.v2")
    if settings.verify:
        verify_document(
            document,
            strict=settings.strict,
            original_source=original_source,
            language=language,
            security_profile=settings.security_profile,
        )
    return document


def _parse_v2(
    source: str,
    language: str,
    extended: bool,
    arena: Optional[Any],
    prepare: bool,
) -> v2.CoreUAST:
    from muta_ext.uast2.adapters import get_adapter_v2

    try:
        adapter = get_adapter_v2(language, extended=bool(extended))
    except TypeError:
        # Legacy-backed adapters (rust/cpp/go) take no dialect flag.
        adapter = get_adapter_v2(language)
    document = adapter.parse_to_uast(source)
    if prepare or arena is not None:
        document.prepare(arena)
    return document


def parse_to_v2(source: str, language: str = "python", **kwargs: Any) -> v2.CoreUAST:
    """Parse straight into v2 (bypassing the flag) — used by tests and tooling."""
    kwargs.pop("engine", None)
    document = parse(source, language=language, engine="v2", **kwargs)
    assert isinstance(document, v2.CoreUAST)
    return document


def to_v2(uast: Any) -> v2.CoreUAST:
    """Return a v2 document for *uast* (idempotent)."""
    if isinstance(uast, v2.CoreUAST):
        return uast
    from muta_ext.uast2.convert import legacy_to_v2

    converted = legacy_to_v2(uast)
    assert isinstance(converted, v2.CoreUAST)
    return converted


def to_legacy(uast: Any) -> Any:
    """Return a legacy document for *uast* (idempotent)."""
    if isinstance(uast, v2.CoreUAST):
        return uast.to_legacy()
    return uast


def is_v2(uast: Any) -> bool:
    """True when *uast* is a UAST v2 document."""
    return isinstance(uast, v2.CoreUAST)


def emit(uast: Any, language: Optional[str] = None) -> str:
    """Emit source for either representation."""
    from muta_ext.uast2.emitters import emit as emit_source

    return emit_source(uast, language)


def verify_document(
    uast: Any,
    strict: bool = False,
    original_source: Optional[str] = None,
    language: Optional[str] = None,
    security_profile: str = "balanced",
) -> PipelineResult:
    """Run the verification half of the default pipeline over *uast*."""
    from muta_ext.uast2.verify import default_verifiers, MathFidelityVerify

    document = to_v2(uast)
    if language is None:
        language = document.language
    passes = list(default_verifiers(document))
    passes.append(
        MathFidelityVerify(original_source=original_source, language=language or "python")
    )
    pipeline = Pipeline(passes, strict=strict, rollback=False)
    return pipeline.run(document)


def mutate(
    uast: Any,
    seed: Optional[int] = None,
    passes: Optional[T.Sequence[Any]] = None,
    strict: bool = False,
    verify: bool = True,
    original_source: Optional[str] = None,
    arena: Optional[Any] = None,
    config: Optional[Any] = None,
    language: str = "python",
) -> PipelineResult:
    """Run the in-place mutation pipeline over a v2 document (or raw source).

    Mutation is the primary use case of v2, so the document is converted when
    needed; the *same object* is mutated when it is already a v2 document.
    Passing a source string parses it first (honouring *config*).
    """
    from muta_ext.uast2.mutators import default_mutators
    from muta_ext.uast2.verify import default_verifiers

    if isinstance(uast, str):  # convenience: mutate straight from source
        settings = resolve_engine_config(config, engine="v2")
        document = parse(
            uast,
            engine="v2",
            language=language,
            prepare=True,
            extended=settings.extended_dialect,
            arena=arena,
            verify=settings.verify,
            strict=settings.strict,
            original_source=original_source,
        )
    else:
        document = to_v2(uast)
    if not getattr(document, "prepared", False):
        document.prepare(arena)
    pipeline = Pipeline([], strict=strict, rollback=True)
    if verify:
        pipeline.extend(default_verifiers(document))
    mutators = list(passes if passes is not None else default_mutators(seed=seed))
    pipeline.extend(mutators)
    # Only mutation sets that *claim* to preserve arithmetic are held to it;
    # otherwise the gate would veto every intentional mutation (constant
    # folding and bound tweaking change numbers by design).
    if verify and all(getattr(pass_, "preserves_math", True) for pass_ in mutators):
        from muta_ext.uast2.verify import MathFidelityVerify

        pipeline.add(
            MathFidelityVerify(original_source=original_source, language=document.language)
        )
    result = pipeline.run(document, arena)
    metrics.incr("uast2.pipeline.runs")
    if not result.ok:
        metrics.incr("uast2.pipeline.failed_runs")
    return result


def engine_metrics() -> Dict[str, float]:
    """Snapshot of every counter/gauge recorded by the v2 engine."""
    return metrics.snapshot()
