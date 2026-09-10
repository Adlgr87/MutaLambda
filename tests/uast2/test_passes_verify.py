#!/usr/bin/env python3
"""Nanopass pipeline, diagnostics and verification passes."""

import pytest

from muta_ext.uast2 import core as v2
from muta_ext.uast2.adapters import parse_to_uast
from muta_ext.uast2.passes import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Diagnostic,
    InvalidIR,
    MutationPass,
    Pass,
    Pipeline,
)
from muta_ext.uast2.verify import (
    ChildSchemaVerify,
    LegacyValidatorVerify,
    MathFidelityVerify,
    NumericSanityVerify,
    ParentLinkVerify,
    SecurityGate,
    StructuralVerify,
    default_verifiers,
    verify_tree,
)

SOURCE = """def f(x):
    y = x + 1
    return y
"""


class TestDiagnostics:
    def test_to_dict_and_str(self):
        node = v2.Identifier(name="x", lineno=3)
        diagnostic = Diagnostic(SEVERITY_ERROR, "boom", "p", node, code="c1")
        assert diagnostic.is_error and diagnostic.node_id is None
        assert diagnostic.to_dict()["node_type"] == "Identifier"
        assert "line 3" in str(diagnostic)

    def test_severities(self):
        assert not Diagnostic(SEVERITY_WARNING, "w").is_error
        assert not Diagnostic("info", "i").is_error


class TestStructuralVerify:
    def test_clean_tree_is_valid(self):
        assert StructuralVerify().verify(parse_to_uast(SOURCE)) == []

    def test_missing_required_field_is_reported(self):
        document = v2.CoreUAST(body=[v2.Return(value=None), v2.BinaryOp(op="+")])
        messages = [d.message for d in StructuralVerify().verify(document)]
        assert any("BinaryOp.op" not in m and "BinaryOp.left" in m for m in messages)
        assert any("required but None" in m for m in messages)

    def test_empty_opaque_is_an_error(self):
        document = v2.CoreUAST(body=[v2.Opaque(original_text="", lang="python")])
        diags = StructuralVerify().verify(document)
        assert diags and diags[0].code == "empty_opaque"

    def test_negative_line_number(self):
        document = v2.CoreUAST(body=[v2.Break(lineno=-2)])
        assert StructuralVerify().verify(document)[0].code == "bad_location"

    def test_shared_node_is_reported(self):
        shared = v2.Identifier(name="x")
        document = v2.CoreUAST(
            body=[v2.BinaryOp(left=shared, op="+", right=v2.Identifier(name="y")), shared]
        )
        codes = {diag.code for diag in StructuralVerify().verify(document)}
        assert "cycle_or_share" in codes


class TestSchemaAndParents:
    def test_child_schema_flags_wrong_kind(self):
        document = v2.CoreUAST(body=[v2.UnaryOp(op="-", operand="not-a-node")])
        diags = ChildSchemaVerify().verify(document)
        assert diags and diags[0].code == "child_schema"

    def test_child_schema_accepts_single_node_for_nodelist(self):
        document = v2.CoreUAST(
            body=[v2.Assign(target=v2.Identifier(name="x"), value=v2.LiteralNode(value=1))]
        )
        assert ChildSchemaVerify().verify(document) == []

    def test_parent_link_verify_detects_stale_links(self):
        document = parse_to_uast(SOURCE)
        inner = document.body[0].body[0].value
        inner._parent = document.body[0]  # deliberately wrong
        diags = ParentLinkVerify().verify(document)
        assert diags and diags[0].code == "stale_parent_link"

    def test_parent_link_verify_ignores_unprepared_trees(self):
        document = parse_to_uast(SOURCE, prepare=False)
        assert ParentLinkVerify().verify(document) == []


class TestLegacyValidatorBridge:
    def test_opaque_downgraded_to_warning(self):
        document = v2.CoreUAST(body=[v2.Opaque(original_text="??", lang="python")])
        diags = LegacyValidatorVerify().verify(document)
        assert diags and all(d.severity == SEVERITY_WARNING for d in diags)

    def test_clean_document_has_no_diagnostics(self):
        assert LegacyValidatorVerify().verify(parse_to_uast(SOURCE)) == []


class TestNumericAndSecurity:
    def test_non_finite_literal(self):
        document = v2.CoreUAST(body=[v2.Return(value=v2.LiteralNode(value=float("inf")))])
        assert NumericSanityVerify().verify(document)[0].code == "non_finite_literal"

    def test_division_by_literal_zero_is_warning(self):
        document = v2.CoreUAST(
            body=[
                v2.BinaryOp(
                    left=v2.Identifier(name="x"), op="/", right=v2.LiteralNode(value=0)
                )
            ]
        )
        diags = NumericSanityVerify().verify(document)
        assert diags and diags[0].severity == SEVERITY_WARNING

    def test_banned_call_is_error(self):
        document = v2.CoreUAST(
            body=[
                v2.Call(func=v2.Identifier(name="eval"), args=[v2.Identifier(name="x")])
            ]
        )
        diags = SecurityGate().verify(document)
        assert any(d.code == "banned_call" and d.is_error for d in diags)

    def test_security_passes_clean_code(self):
        assert SecurityGate().verify(parse_to_uast(SOURCE)) == []

    def test_source_level_filter_reuse(self):
        document = parse_to_uast(SOURCE)
        diags = SecurityGate(source="import os\nos.system('rm -rf /')\n").verify(document)
        assert any(d.is_error for d in diags)


class TestMathFidelity:
    def test_disabled_without_reference_source(self):
        assert MathFidelityVerify().verify(parse_to_uast(SOURCE)) == []

    def test_equivalent_program_passes(self):
        source = "def f(x):\n    return x + 1\n"
        document = parse_to_uast(source)
        assert MathFidelityVerify(original_source=source).verify(document) == []

    def test_changed_arithmetic_is_flagged(self):
        source = "def f(x):\n    return x + 1\n"
        document = parse_to_uast(source)
        document.body[0].body[0].value.right.value = 999
        diags = MathFidelityVerify(original_source=source).verify(document)
        assert diags  # either an error or an "unavailable" warning, but never silent

    def test_unsupported_language_warns(self):
        diags = MathFidelityVerify(original_source="x", language="rust").verify(
            parse_to_uast("x = 1\n")
        )
        assert diags and diags[0].code == "unsupported_language"


class _AddComment(MutationPass):
    """Valid mutating pass (used to test rollback granularity)."""

    name = "add_comment"

    def run(self, root, arena=None):
        root.body.append(v2.Comment(text="marker", position="before"))
        self._record()


class _Explode(MutationPass):
    name = "explode"

    def run(self, root, arena=None):
        raise RuntimeError("kaboom")


class _BreakIR(MutationPass):
    name = "break_ir"

    def run(self, root, arena=None):
        root.body.append(v2.BinaryOp(op="+"))


class TestPipeline:
    def test_runs_passes_and_collects_diagnostics(self):
        document = parse_to_uast(SOURCE)
        pipeline = Pipeline(default_verifiers())
        result = pipeline.run(document)
        assert result.ok and result.passes_run
        assert pipeline.last_result is result

    def test_strict_mode_raises_and_rolls_back(self):
        document = parse_to_uast(SOURCE)
        before = document.canonical_hash()
        pipeline = Pipeline([StructuralVerify(), _BreakIR()], strict=True)
        with pytest.raises(InvalidIR) as excinfo:
            pipeline.run(document)
        assert excinfo.value.pass_name == "break_ir"
        assert document.canonical_hash() == before  # rolled back

    def test_non_strict_rolls_back_and_logs(self, caplog):
        document = parse_to_uast(SOURCE)
        before = document.canonical_hash()
        pipeline = Pipeline([StructuralVerify(), _BreakIR()], strict=False, rollback=True)
        result = pipeline.run(document)
        assert "break_ir" in result.rolled_back
        assert document.canonical_hash() == before
        assert result.ok  # rollback removed the invalid state

    def test_pass_crash_is_contained(self):
        document = parse_to_uast(SOURCE)
        pipeline = Pipeline([_Explode()], strict=False, rollback=True)
        result = pipeline.run(document)
        assert result.aborted_at == "explode"
        assert "pass crashed" in result.errors[0].message
        assert not result.ok

    def test_run_level_rollback_is_atomic(self):
        document = parse_to_uast(SOURCE)
        before = document.canonical_hash()
        pipeline = Pipeline([StructuralVerify(), _AddComment(), _BreakIR()], strict=False)
        result = pipeline.run(document)
        # _AddComment was valid but the run is atomic: everything reverts.
        assert result.rolled_back == ["add_comment", "break_ir"]
        assert document.canonical_hash() == before
        assert type(document.body[-1]).__name__ != "Comment"

    def test_per_pass_rollback_keeps_valid_mutations(self):
        document = parse_to_uast(SOURCE)
        pipeline = Pipeline([StructuralVerify(), _AddComment(), _BreakIR()], rollback="pass")
        result = pipeline.run(document)
        assert result.rolled_back == ["break_ir"]
        assert type(document.body[-1]).__name__ == "Comment"
        assert StructuralVerify().verify(document) == []

    def test_rollback_disabled_keeps_invalid_state(self):
        document = parse_to_uast(SOURCE)
        pipeline = Pipeline([StructuralVerify(), _BreakIR()], rollback=False)
        result = pipeline.run(document)
        assert result.rolled_back == []
        assert not result.ok  # the damage is visible to the caller

    def test_verify_only(self):
        document = v2.CoreUAST(body=[v2.Opaque(original_text="", lang="python")])
        pipeline = Pipeline(default_verifiers())
        diags = pipeline.verify_only(document)
        assert any(d.code == "empty_opaque" for d in diags)

    def test_add_and_len_and_names(self):
        pipeline = Pipeline().add(StructuralVerify())
        assert len(pipeline) == 1 and pipeline.names() == ["structural"]

    def test_result_to_dict(self):
        payload = Pipeline([]).run(parse_to_uast(SOURCE)).to_dict()
        assert payload["ok"] is True and isinstance(payload["passes_run"], list)


class TestVerifyTreeHelper:
    def test_default_verifiers_run(self):
        document = parse_to_uast(SOURCE)
        assert verify_tree(document) == []
        assert StructuralVerify in [type(p) for p in default_verifiers(document)]
