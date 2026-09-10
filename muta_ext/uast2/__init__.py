#!/usr/bin/env python3
"""UAST v2 — mutable, efficient, verifiable AST for MutaLambda.

Parallel engine next to the frozen ``muta_ext.uast`` package: nothing here is
imported unless you ask for it, and the default engine stays ``legacy`` until the
``uast.engine: v2`` flag is turned on.

Quick tour::

    from muta_ext.uast2 import parse_to_uast, walk, NodeTransformer, verify

    document = parse_to_uast("def f(x):\\n    return x + 1\\n")   # mutable tree
    document.emit()                                            # back to source
    document.canonical_hash()                                  # stable structure hash
    document.merkle_hash()                                     # incremental digest
    report = verify.verify_tree(document)                      # diagnostics

Module map:

============================ ==================================================
``core``                     ``UASTNode`` + 23 node classes + ``CoreUAST``
``arena``                    slab allocator, parent pointers, O(1) replace
``merkle``                   incremental hashing (hash only the dirty path)
``visitor``                  ``walk`` / ``NodeVisitor`` / ``NodeTransformer`` / ``dump``
``convert``                  ``legacy_to_v2`` / ``v2_to_legacy`` (bidirectional)
``adapters``                 Python (native, locations) + Rust/C++/Go (reused)
``emitters``                 emits through the frozen per-language emitters
``passes``                   ``Pass`` / ``Pipeline`` / ``Diagnostic`` + rollback
``verify``                   structural, schema, math and security gates
``mutators``                 in-place mutation passes (folding, swaps, bounds)
``serialize``                flat-slab msgpack (JSON fallback, zlib optional)
``shadow``                   dual-engine comparison that never breaks a run
``engine``                   feature flag, one ``parse`` entry point
``metrics``                  dependency-free counters for CLI/CI reporting
============================ ==================================================
"""

from __future__ import annotations

from muta_ext.uast2.arena import Arena, assign_parents, clone_tree, prepare
from muta_ext.uast2.adapters import get_adapter_v2, parse_to_arena, parse_to_uast
from muta_ext.uast2.convert import legacy_to_v2, to_legacy, to_v2, v2_to_legacy
from muta_ext.uast2.core import (
    NODE_REGISTRY,
    BinaryOp,
    Break,
    Call,
    Comment,
    CoreUAST,
    ExceptClause,
    FieldDef,
    For,
    Function,
    Identifier,
    If,
    LiteralNode,
    Match,
    MatchArm,
    Node,
    Opaque,
    ParallelFor,
    Reference,
    Return,
    StructDef,
    TryExcept,
    TypeAnnotation,
    UASTNode,
    UnaryOp,
    While,
    Assign,
    child_kinds,
    node_class,
    required_fields,
    walk,
)
from muta_ext.uast2.emitters import emit, get_emitter_v2
from muta_ext.uast2.engine import (
    EngineConfig,
    engine_metrics,
    is_v2,
    mutate,
    parse,
    resolve_engine_config,
    verify_document,
)
from muta_ext.uast2.merkle import (
    invalidate_up,
    node_digest,
    recompute_all,
    root_digest,
)
from muta_ext.uast2.mutators import (
    CommutativeSwapPass,
    ConstantFoldingPass,
    LegacyMutatorPass,
    NegateConditionPass,
    RangeBoundPass,
    default_mutators,
)
from muta_ext.uast2.passes import (
    Diagnostic,
    InvalidIR,
    MutationPass,
    Pass,
    Pipeline,
    PipelineResult,
)
from muta_ext.uast2 import serialize, shadow, verify
from muta_ext.uast2.serialize import dump, dumps, load, loads
from muta_ext.uast2.shadow import canonical_digest, run_shadow_suite, shadow_parse
from muta_ext.uast2.visitor import NodeTransformer, NodeVisitor, dump as dump_tree
from muta_ext.uast2.verify import default_pipeline, default_verifiers

__all__ = [
    # core
    "UASTNode",
    "CoreUAST",
    "Node",
    "NODE_REGISTRY",
    "node_class",
    "required_fields",
    "child_kinds",
    "walk",
    "LiteralNode",
    "Identifier",
    "BinaryOp",
    "UnaryOp",
    "Call",
    "Assign",
    "If",
    "For",
    "While",
    "Return",
    "Function",
    "ParallelFor",
    "Comment",
    "Opaque",
    "Break",
    "TryExcept",
    "ExceptClause",
    "StructDef",
    "FieldDef",
    "TypeAnnotation",
    "MatchArm",
    "Match",
    "Reference",
    # arena / hashing
    "Arena",
    "assign_parents",
    "prepare",
    "clone_tree",
    "invalidate_up",
    "node_digest",
    "root_digest",
    "recompute_all",
    # visitors
    "NodeVisitor",
    "NodeTransformer",
    "dump_tree",
    # conversion / adapters / emitters
    "legacy_to_v2",
    "v2_to_legacy",
    "to_v2",
    "to_legacy",
    "get_adapter_v2",
    "parse_to_uast",
    "parse_to_arena",
    "emit",
    "get_emitter_v2",
    # passes / verification / mutation
    "Pass",
    "MutationPass",
    "Pipeline",
    "PipelineResult",
    "Diagnostic",
    "InvalidIR",
    "default_pipeline",
    "default_verifiers",
    "ConstantFoldingPass",
    "CommutativeSwapPass",
    "RangeBoundPass",
    "NegateConditionPass",
    "LegacyMutatorPass",
    "default_mutators",
    # serialization
    "dumps",
    "loads",
    "dump",
    "load",
    "serialize",
    # shadow / engine
    "shadow_parse",
    "run_shadow_suite",
    "canonical_digest",
    "EngineConfig",
    "resolve_engine_config",
    "parse",
    "mutate",
    "verify_document",
    "is_v2",
    "engine_metrics",
    # submodules
    "shadow",
    "verify",
]

__version__ = "2.0.0"
