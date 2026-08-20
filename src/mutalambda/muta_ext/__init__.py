"""MutaLambda Extensions — optional evolutionary modules."""

from __future__ import annotations

__all__ = [
    "advanced_selection",
    "dialectic_engine",
    "pattern_memory",
    "scientific",
    "spatial_topology",
    "thc_engine",
    "uast",
]

# v4.0 public API
__version__ = "4.0.0"

__all_extra_v4 = [
    # Core
    "MutaLambdaOptimizer",
    # UAST
    "CoreUAST", "Function", "Node",
    "get_adapter", "PythonAdapter", "RustAdapter", "CppAdapter", "GoAdapter",
    "get_emitter", "PythonEmitter", "RustEmitter", "CppEmitter", "GoEmitter",
    "get_handler", "PythonHandler", "RustHandler", "CppHandler", "GoHandler",
    # Project optimizer
    "ProjectAnalyzer", "analyze_project",
    # Explainable optimizer
    "ExplainableOptimizer", "ExplanationGenerator", "OptimizationType", "RiskLevel",
    # CI/CD
    "PerformanceBaseline", "RegressionDetector", "PRAnalyzer",
    "create_ci_pipeline", "register_baseline_from_ci",
    # Config
    "MutaLambdaConfig",
]


def __getattr__(name: str):
    """Lazy attribute access so importing muta_ext does not load heavy engines."""
    # v4.0 lazy imports
    if name in __all_extra_v4:
        import importlib
        if name == "MutaLambdaOptimizer":
            mod = importlib.import_module("mutalambda.muta_ext.optimizer")
        elif name in ("CoreUAST", "Function", "Node"):
            mod = importlib.import_module("mutalambda.muta_ext.uast.core_uast")
        elif name == "get_adapter":
            mod = importlib.import_module("mutalambda.muta_ext.uast.adapters")
        elif name in ("PythonAdapter", "RustAdapter", "CppAdapter", "GoAdapter"):
            mod = importlib.import_module("mutalambda.muta_ext.uast.adapters")
        elif name == "get_emitter":
            mod = importlib.import_module("mutalambda.muta_ext.uast.emitters")
        elif name in ("PythonEmitter", "RustEmitter", "CppEmitter", "GoEmitter"):
            mod = importlib.import_module("mutalambda.muta_ext.uast.emitters")
        elif name == "get_handler":
            mod = importlib.import_module("mutalambda.muta_ext.uast.handlers")
        elif name in ("PythonHandler", "RustHandler", "CppHandler", "GoHandler"):
            mod = importlib.import_module("mutalambda.muta_ext.uast.handlers")
        elif name in ("ProjectAnalyzer", "analyze_project"):
            mod = importlib.import_module("mutalambda.muta_ext.project_optimizer")
        elif name in ("ExplainableOptimizer", "ExplanationGenerator", "OptimizationType", "RiskLevel"):
            mod = importlib.import_module("mutalambda.muta_ext.explainable_optimizer")
        elif name in ("PerformanceBaseline", "RegressionDetector", "PRAnalyzer",
                      "create_ci_pipeline", "register_baseline_from_ci"):
            mod = importlib.import_module("mutalambda.muta_ext.ci_integration")
        elif name == "MutaLambdaConfig":
            mod = importlib.import_module("mutalambda.muta_ext.config")
        else:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        return getattr(mod, name)

    if name in __all__:
        import importlib
        return importlib.import_module(f"muta_ext.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
