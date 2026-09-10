"""Tests for A1 — JSON-schema structured output + diff application (Fase 1)."""

from __future__ import annotations

import ast
import json

import pytest

from structured_ops import (
    OP_TYPES,
    ProposedOp,
    apply_ops,
    apply_unified_diff,
    build_repair_prompt,
    build_schema_prompt,
    extract_json_object,
    parse_ops,
    validate_ops,
)

SOURCE = """def solution(n: int) -> int:
    total = 0
    i = 1
    while i <= n:
        total = total + i
        i = i + 1
    return total
"""

VALID_DIFF = (
    "@@ -1,7 +1,4 @@\n"
    " def solution(n: int) -> int:\n"
    "-    total = 0\n"
    "-    i = 1\n"
    "-    while i <= n:\n"
    "-        total = total + i\n"
    "-        i = i + 1\n"
    "-    return total\n"
    "+    return n * (n + 1) // 2\n"
)


class TestSchemaPrompt:
    def test_prompt_is_deterministic_and_strict(self):
        p1 = build_schema_prompt(mode="HEURISTIC_MUTATION", code=SOURCE, score=0.5, n=1)
        p2 = build_schema_prompt(mode="HEURISTIC_MUTATION", code=SOURCE, score=0.5, n=1)
        assert p1 == p2  # byte-identical for identical inputs (O2)
        assert "JSON object only" in p1
        assert "No prose" in p1
        assert '"op_type"' in p1
        assert all(t in p1 for t in OP_TYPES)
        assert "SOURCE" in p1 and "def solution" in p1

    def test_prompt_requests_batch_n(self):
        p = build_schema_prompt(mode="HEURISTIC_MUTATION", code=SOURCE, n=5)
        assert "exactly 5 object(s)" in p

    def test_repair_prompt_carries_errors(self):
        p = build_repair_prompt(['missing non-empty "ops" array'], "ORIGINAL PROMPT")
        assert "REJECTED" in p
        assert "missing non-empty" in p
        assert "ORIGINAL PROMPT" in p


class TestExtractionValidation:
    def _valid_payload(self, n=1):
        return {
            "ops": [
                {
                    "op_type": "replace_function_body",
                    "location": "def solution(n: int)",
                    "unified_diff": VALID_DIFF,
                    "rationale": "Closed form.",
                    "confidence": 0.9,
                }
                for _ in range(n)
            ]
        }

    def test_valid_payload(self):
        ops, errors = parse_ops(json.dumps(self._valid_payload()))
        assert errors == []
        assert len(ops) == 1
        assert ops[0].op_type == "replace_function_body"
        assert ops[0].confidence == 0.9

    def test_fence_wrapped_json_accepted(self):
        text = "```json\n" + json.dumps(self._valid_payload()) + "\n```"
        ops, errors = parse_ops(text)
        assert errors == [] and len(ops) == 1

    def test_prose_around_json_accepted(self):
        text = "Here you go:\n" + json.dumps(self._valid_payload()) + "\nDone."
        ops, errors = parse_ops(text)
        assert errors == [] and len(ops) == 1

    def test_no_json_rejected(self):
        ops, errors = parse_ops("I improved the loop, here is the code:\n```python\nprint(1)\n```")
        assert ops == []
        assert errors

    def test_bad_op_type_rejected(self):
        payload = self._valid_payload()
        payload["ops"][0]["op_type"] = "explode"
        ops, errors = parse_ops(json.dumps(payload))
        assert ops == []
        assert any("op_type" in e for e in errors)

    def test_missing_diff_rejected(self):
        payload = self._valid_payload()
        del payload["ops"][0]["unified_diff"]
        ops, errors = parse_ops(json.dumps(payload))
        assert ops == []
        assert any("unified_diff" in e for e in errors)

    def test_bare_op_object_tolerated(self):
        op = self._valid_payload()["ops"][0]
        ops, errors = parse_ops(json.dumps(op))
        assert errors == [] and len(ops) == 1

    def test_bare_list_tolerated(self):
        ops, errors = parse_ops(json.dumps(self._valid_payload()["ops"]))
        assert errors == [] and len(ops) == 1

    def test_batch_n_parsed(self):
        ops, errors = parse_ops(json.dumps(self._valid_payload(n=5)))
        assert errors == [] and len(ops) == 5


class TestUnifiedDiffApply:
    def test_apply_valid_diff(self):
        out = apply_unified_diff(SOURCE, VALID_DIFF)
        assert out is not None
        ast.parse(out)
        assert "return n * (n + 1) // 2" in out
        assert "while i <= n" not in out
        # semantics preserved
        ns = {}
        exec(out, ns)
        assert ns["solution"](10) == 55

    def test_insert_helper(self):
        diff = (
            "@@ -1,1 +1,4 @@\n"
            "+\n"
            "+def _half(n):\n"
            "+    return n // 2\n"
            " def solution(n: int) -> int:\n"
        )
        out = apply_unified_diff(SOURCE, diff)
        assert out is not None
        ast.parse(out)
        assert "def _half" in out
        ns = {}
        exec(out, ns)
        assert ns["_half"](7) == 3

    def test_drift_tolerated(self):
        # Diff claims the hunk starts at line 1 but the real function starts at 3.
        prefixed = "# header comment\n# second comment\n" + SOURCE
        diff = (
            "@@ -1,7 +1,6 @@\n"
            " def solution(n: int) -> int:\n"
            "-    total = 0\n"
            "-    i = 1\n"
            "-    while i <= n:\n"
            "-        total = total + i\n"
            "-        i = i + 1\n"
            "     return total\n"
            "+    return n * (n + 1) // 2\n"
        )
        out = apply_unified_diff(prefixed, diff)
        assert out is not None
        ast.parse(out)
        assert "return n * (n + 1) // 2" in out
        assert "# header comment" in out

    def test_loose_diff_without_headers(self):
        diff = (
            " def solution(n: int) -> int:\n"
            "-    total = 0\n"
            "+     total = 1\n"
        )
        out = apply_unified_diff(SOURCE, diff)
        assert out is not None
        assert "total = 1" in out

    def test_mismatch_rejected(self):
        diff = (
            "@@ -1,3 +1,3 @@\n"
            " def nosuchfunction(n):\n"
            "-     x = 1\n"
            "+     x = 2\n"
        )
        assert apply_unified_diff(SOURCE, diff) is None

    def test_empty_diff_rejected(self):
        assert apply_unified_diff(SOURCE, "") is None
        assert apply_unified_diff(SOURCE, "--- a/x\n+++ b/x\n") is None


class TestApplyOps:
    def test_ops_pipeline_validates_python(self):
        op = ProposedOp(
            op_type="replace_function_body",
            location="def solution",
            unified_diff=VALID_DIFF,
            confidence=0.9,
        )
        code, applied, failed = apply_ops(SOURCE, [op])
        assert applied == ["def solution"]
        assert failed == []
        ast.parse(code)

    def test_broken_op_rejected_without_crash(self):
        bad = ProposedOp(
            op_type="refactor",
            location="def solution",
            unified_diff=(
                " def solution(n: int) -> int:\n"
                "-    total = 0\n"
                "+     return :(((\n"  # invalid python after apply
            ),
        )
        code, applied, failed = apply_ops(SOURCE, [bad])
        assert applied == []
        assert failed == ["def solution"]
        assert code == SOURCE  # source untouched when the op fails

    def test_mixed_ops_first_fails_second_applies(self):
        bad = ProposedOp("refactor", "nope", "@@ -9,1 +9,1 @@\n def nosuch:\n- x\n+ y\n")
        good = ProposedOp(
            "replace_function_body",
            "def solution",
            VALID_DIFF,
        )
        code, applied, failed = apply_ops(SOURCE, [bad, good])
        assert len(applied) == 1
        assert len(failed) == 1
        ast.parse(code)
