#!/usr/bin/env python3
"""In-situ mutators, the shadow harness and the engine entry point."""

import pytest

from muta_ext.uast2 import core as v2
from muta_ext.uast2.adapters import parse_to_uast
from muta_ext.uast2.engine import (
    EngineConfig,
    engine_metrics,
    is_v2,
    mutate,
    parse,
    parse_to_v2,
    resolve_engine_config,
    to_legacy,
    to_v2,
    verify_document,
)
from muta_ext.uast2.mutators import (
    ConstantFoldingPass,
    CommutativeSwapPass,
    LegacyMutatorPass,
    NegateConditionPass,
    RangeBoundPass,
    available_legacy_mutators,
    default_mutators,
)
from muta_ext.uast2.passes import Pipeline
from muta_ext.uast2.shadow import (
    ShadowResult,
    canonical_digest,
    compare,
    run_shadow_suite,
    shadow_parse,
    shadow_stats,
)
from muta_ext.uast2.verify import ChildSchemaVerify, StructuralVerify

SOURCE = """def f(n):
    total = 0
    for i in range(0, n):
        total = total + 2 * 3
    return total
"""


class TestConstantFolding:
    def test_folds_literal_binary_op(self):
        document = parse_to_uast(SOURCE)
        result = Pipeline([StructuralVerify(), ConstantFoldingPass()]).run(document)
        assert result.mutations["constant_folding"] >= 1
        assert "6" in document.emit()

    def test_repeated_run_is_idempotent(self):
        document = parse_to_uast(SOURCE)
        first = Pipeline([ConstantFoldingPass()]).run(document).mutations["constant_folding"]
        second = Pipeline([ConstantFoldingPass()]).run(document).mutations["constant_folding"]
        assert first >= 1 and second == 0

    def test_keeps_tree_valid(self):
        document = parse_to_uast(SOURCE)
        ConstantFoldingPass().run(document)
        assert StructuralVerify().verify(document) == []
        assert ChildSchemaVerify().verify(document) == []


class TestCommutativeSwap:
    def test_swap_is_semantically_neutral_and_reversible(self):
        document = parse_to_uast("def f(a, b):\n    return a + b\n")
        before = document.emit()
        result = Pipeline([StructuralVerify(), CommutativeSwapPass(seed=1)]).run(document)
        assert result.mutations["commutative_swap"] == 1
        after = document.emit()
        assert "+" in after and after != before
        Pipeline([CommutativeSwapPass(seed=1)]).run(document)
        assert document.emit() == before  # swapping twice restores the program

    def test_ignores_non_commutative_ops(self):
        document = parse_to_uast("def f(a, b):\n    return a - b\n")
        assert Pipeline([CommutativeSwapPass()]).run(document).mutations["commutative_swap"] == 0


class TestRangeBound:
    def test_shifts_bounds_and_stays_aligned(self):
        document = parse_to_uast("for i in range(0, n):\n    x = i\n")
        result = Pipeline([StructuralVerify(), RangeBoundPass(seed=3)]).run(document)
        assert result.mutations["range_bound"] == 1
        emitted = document.emit()
        assert "range(" in emitted and "n" in emitted
        import ast

        ast.parse(emitted)


class TestNegateCondition:
    def test_negates_once(self):
        document = parse_to_uast("if a > 1:\n    x = 1\n")
        result = Pipeline([StructuralVerify(), NegateConditionPass(rate=1.0)]).run(document)
        assert result.mutations["negate_condition"] == 1
        assert "not" in document.emit()


class TestLegacyMutatorBridge:
    def test_registry_is_exposed(self):
        names = available_legacy_mutators()
        assert "LoopBoundMutator" in names and "BaseMutator" in names and len(names) >= 5

    def test_legacy_mutator_runs_on_v2_tree(self):
        document = parse_to_uast(SOURCE)
        pass_ = LegacyMutatorPass.from_registry("LoopBoundMutator")
        result = Pipeline([StructuralVerify(), pass_]).run(document)
        assert result.passes_run == ["structural", "legacy_LoopBoundMutator"]
        assert StructuralVerify().verify(document) == []

    def test_unknown_mutator_is_rejected(self):
        with pytest.raises(ValueError):
            LegacyMutatorPass.from_registry("DoesNotExistMutator")

    def test_default_mutators_build_a_pipeline(self):
        pipeline = Pipeline(default_mutators(seed=7))
        assert pipeline.names() == [
            "constant_folding",
            "commutative_swap",
            "range_bound",
            "negate_condition",
        ]
        assert pipeline.run(parse_to_uast(SOURCE)).ok


class TestShadow:
    def test_digest_is_metadata_independent(self):
        document = parse_to_uast("x = 1\n")
        document.metadata["noise"] = "id-based"
        assert canonical_digest(document) == canonical_digest(parse_to_uast("x = 1\n"))

    def test_compare_equal_for_same_structure(self):
        source = "def f(x):\n    return x + 1\n"
        result = shadow_parse(source)
        assert isinstance(result, ShadowResult)
        assert result.equal and result.differences == []
        assert result.legacy_nodes == result.v2_nodes > 0

    def test_compare_detects_difference(self):
        from muta_ext.uast.adapters.python_adapter import parse_to_uast as legacy_parse

        legacy_doc = legacy_parse("x = 1\n")
        v2_doc = parse_to_uast("y = 2\n")
        result = compare(legacy_doc, v2_doc)
        assert not result.equal and result.differences

    def test_no_file_fails(self, tmp_path):
        good = tmp_path / "good.py"
        bad = tmp_path / "bad.py"
        good.write_text("x = 1\n", encoding="utf-8")
        bad.write_text("def broken(:\n", encoding="utf-8")
        report = run_shadow_suite([good, bad])
        assert report["files"] == 2 and report["errors"] == 1 and report["mismatches"] == 0

    def test_stats_counters(self):
        before = shadow_stats().get("uast2.shadow.parses", 0)
        shadow_parse("x = 1\n")
        after = shadow_stats()
        assert after.get("uast2.shadow.parses", 0) == before + 1  # one comparison
        assert after.get("uast2.shadow.nodes", 0) > 0


class TestEngineConfig:
    def test_default_is_legacy(self):
        config = EngineConfig()
        assert config.engine == "legacy" and config.shadow is False

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_UAST_ENGINE", "v2")
        monkeypatch.setenv("MUTALAMBDA_UAST_SHADOW", "1")
        config = resolve_engine_config()
        assert config.engine == "v2" and config.shadow is True

    def test_explicit_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_UAST_ENGINE", "v2")
        assert resolve_engine_config({"uast": {"engine": "legacy"}}).engine == "legacy"

    def test_invalid_engine_rejected(self):
        with pytest.raises(ValueError):
            EngineConfig(engine="v9")

    def test_defaults_from_document(self):
        assert resolve_engine_config(v2.CoreUAST(body=[])).engine == "legacy"


class TestEngineEntryPoints:
    def test_parse_returns_legacy_by_default(self):
        from muta_ext.uast.core_uast import CoreUAST as LegacyCoreUAST

        document = parse(SOURCE)
        assert isinstance(document, LegacyCoreUAST)
        assert not is_v2(document)

    def test_parse_returns_v2_with_flag(self):
        document = parse(SOURCE, config=EngineConfig(engine="v2"))
        assert is_v2(document) and document.node_count() > 5
        assert document.prepared

    def test_shadow_parse_still_returns_legacy(self):
        from muta_ext.uast.core_uast import CoreUAST as LegacyCoreUAST

        document = parse(SOURCE, config=EngineConfig(engine="legacy", shadow=True))
        assert isinstance(document, LegacyCoreUAST)
        assert shadow_stats().get("uast2.shadow.parses", 0) >= 2

    def test_explicit_engine_argument(self):
        assert is_v2(parse(SOURCE, engine="v2"))

    def test_converters(self):
        legacy_document = parse(SOURCE)
        v2_document = to_v2(legacy_document)
        assert v2_document.canonical_hash() == parse_to_v2(SOURCE).canonical_hash()
        assert not is_v2(to_legacy(v2_document))
        assert to_legacy(v2_document).canonical_hash  # legacy CLI-facing object

    def test_mutate_entry_point(self):
        before = engine_metrics().get("uast2.pipeline.runs", 0)
        result = mutate(SOURCE, seed=11, config=EngineConfig(engine="v2"))
        assert result.ok
        assert result.passes_run[0] == "structural"
        assert any(count >= 0 for count in result.mutations.values())
        assert engine_metrics()["uast2.pipeline.runs"] == before + 1

    def test_verify_document(self):
        document = parse_to_v2(SOURCE)
        assert verify_document(document).ok
        assert verify_document(document).errors == []
        # Legacy input is converted internally so both engines share the gate.
        assert verify_document(parse(SOURCE)).ok


class TestMathFidelityContract:
    """`preserves_math` keeps the fidelity gate honest without vetoing mutations."""

    SOURCE = (
        "def f(n):\n"
        "    total = 0\n"
        "    for i in range(0, n):\n"
        "        total = total + 2 * 3\n"
        "    return total\n"
    )

    def test_intentional_mutators_are_not_blocked_by_math_fidelity(self):
        result = mutate(self.SOURCE, seed=42, verify=True, original_source=self.SOURCE)
        assert result.ok, [diag.message for diag in result.errors]
        assert result.rolled_back == []
        assert sum(result.mutations.values()) >= 1

    def test_preserving_mutator_is_still_held_to_arithmetic(self):
        from muta_ext.uast2.passes import MutationPass
        from muta_ext.uast2.verify import StructuralVerify

        class _Drift(MutationPass):
            name = "drift"  # preserves_math defaults to True

            def run(self, root, arena=None):
                for node in root.walk():
                    if type(node).__name__ == "LiteralNode" and node.value == 3:
                        node.value = 999
                        node.invalidate_hash()
                        self._record()

        result = mutate(
            self.SOURCE,
            passes=[_Drift()],
            verify=True,
            original_source=self.SOURCE,
        )
        assert not result.ok
        assert any(diag.code == "math_mismatch" for diag in result.errors)
        assert result.rolled_back == ["drift"]

    def test_commutative_swap_alone_still_passes_math_fidelity(self):
        from muta_ext.uast2.mutators import CommutativeSwapPass

        passes = [CommutativeSwapPass(rate=1.0, seed=5)]
        result = mutate(
            self.SOURCE, passes=passes, verify=True, original_source=self.SOURCE
        )
        assert result.ok, [diag.message for diag in result.errors]

    def test_pipeline_reports_math_mismatch_before_other_gates(self):
        from muta_ext.uast2.mutators import ConstantFoldingPass
        from muta_ext.uast2.passes import Pipeline
        from muta_ext.uast2.verify import MathFidelityVerify, StructuralVerify

        document = parse_to_uast(self.SOURCE)
        pipeline = Pipeline(
            [
                StructuralVerify(),
                ConstantFoldingPass(),
                MathFidelityVerify(original_source=self.SOURCE),
            ]
        )
        result = pipeline.run(document)
        # ConstantFolding changes the literal multiset on purpose; an explicit
        # final math gate must catch it and roll the whole run back.
        assert not result.ok
        assert any(diag.code == "math_mismatch" for diag in result.errors)
