#!/usr/bin/env python3
"""Scoped verification (nanopass guards), touch log and hash-cache behaviour."""

import pytest

from muta_ext.uast2 import core as v2
from muta_ext.uast2.adapters import parse_to_uast
from muta_ext.uast2.merkle import begin_touch, end_touch, hash_stats, reset_hash_stats
from muta_ext.uast2.mutators import CommutativeSwapPass, ConstantFoldingPass, default_mutators
from muta_ext.uast2.passes import MutationPass, Pipeline
from muta_ext.uast2.verify import (
    ChildSchemaVerify,
    NumericSanityVerify,
    ParentLinkVerify,
    StructuralVerify,
    default_verifiers,
)

SOURCE = """def f(n):
    total = 0
    for i in range(0, n):
        total = total + 2 * 3
    if total > 4:
        total = total - 1
    return total
"""


def find(document, type_name):
    """First node of the given type (test helper)."""
    for node in document.walk():
        if type(node).__name__ == type_name:
            return node
    raise AssertionError(f"no {type_name} in document")


class TestTouchLog:
    def test_set_child_records_the_parent(self):
        from muta_ext.uast2.core import set_child

        document = parse_to_uast(SOURCE)
        assignment = find(document, "Assign")
        replacement = v2.LiteralNode(value=0)
        begin_touch()
        set_child(assignment, "value", replacement)
        touched = end_touch()
        assert touched and touched[0] is assignment

    def test_invalidate_up_records_topmost_node(self):
        document = parse_to_uast(SOURCE)
        document.merkle_hash()  # digests must exist for the chain to collapse
        leaf = find(document, "LiteralNode")
        begin_touch()
        leaf.invalidate_hash()
        touched = end_touch()
        assert touched and touched[0] is not leaf  # collapsed to the topmost ancestor
        # "topmost" means closer to the document root (smaller depth).
        assert degree_of(touched[0], document) < degree_of(leaf, document)

    def test_end_touch_disables_recording(self):
        parse_to_uast(SOURCE)
        end_touch()
        node = v2.LiteralNode(value=1)
        node.invalidate_hash()
        assert end_touch() == []

    def test_transformer_conservative_invalidation_is_not_recorded(self):
        document = parse_to_uast(SOURCE)
        begin_touch()
        for node in document.walk():
            node.invalidate_hash()
        touched = end_touch()
        # invalidate_hash() is an explicit call, so it *is* recorded; the
        # transformer's internal safety net (record=False) is not.
        assert touched


def degree_of(node, document):
    """Distance from the document root (0 for body items)."""
    depth = 0
    while node._parent is not None:
        node = node._parent
        depth += 1
    return depth


class TestScopedVerification:
    def test_scope_limits_the_checked_subtree(self):
        document = parse_to_uast(SOURCE)
        broken = v2.CoreUAST(body=[v2.BinaryOp(op="+")])  # invalid, not in scope
        diags = StructuralVerify().verify(document, [document.body[0]])
        assert diags == []
        assert StructuralVerify().verify(broken) != []

    def test_scope_is_honoured_by_every_cheap_verifier(self):
        """Each cheap verifier must look only inside the scope it is given."""
        # Structural: a required field is cleared inside the scope.
        document = parse_to_uast(SOURCE)
        function = document.body[0]
        target = find(document, "BinaryOp")
        target.left = None
        assert StructuralVerify().verify(document, [target])
        assert StructuralVerify().verify(document, [function.body[-1]]) == []

        # ChildSchema: a non-node lands in a node slot.
        document = parse_to_uast(SOURCE)
        function = document.body[0]
        target = find(document, "Assign")
        target.value = "not-a-node"
        assert ChildSchemaVerify().verify(document, [target])
        assert ChildSchemaVerify().verify(document, [function.body[-1]]) == []

        # ParentLink: a stale parent pointer inside the scope.
        document = parse_to_uast(SOURCE)
        function = document.body[0]
        target = find(document, "BinaryOp")
        target._parent = function.body[-1]
        assert ParentLinkVerify().verify(document, [target._parent._parent])
        assert ParentLinkVerify().verify(document, [function.body[-1]]) == []

        # NumericSanity: a non-finite literal inside the scope.
        document = parse_to_uast(SOURCE)
        function = document.body[0]
        target = find(document, "LiteralNode")
        target.value = float("inf")
        assert NumericSanityVerify().verify(document, [target])
        assert NumericSanityVerify().verify(document, [function.body[-1]]) == []

    def test_pipeline_scopes_guards_to_touched_nodes(self):
        document = parse_to_uast(SOURCE)
        seen = []
        original = Pipeline._scope_for

        def spy(self, touched, pass_):
            scope = original(self, touched, pass_)
            seen.append((pass_.name, None if scope is None else len(scope)))
            return scope

        Pipeline._scope_for = spy
        try:
            Pipeline(default_verifiers() + [CommutativeSwapPass(seed=3)]).run(document)
        finally:
            Pipeline._scope_for = original
        scoped = [size for name, size in seen if name == "commutative_swap"]
        assert scoped and all(size is not None for size in scoped)
        # The scope must be a small fraction of the document, not a full walk.
        assert max(scoped) < document.node_count()

    def test_pass_without_touch_log_falls_back_to_full_verification(self):
        document = parse_to_uast(SOURCE)

        class _Sneaky(MutationPass):
            name = "sneaky"

            def run(self, root, arena=None):
                # Mutates a required field directly without invalidating anything.
                find(root, "BinaryOp").left = None
                self._record()

        result = Pipeline([StructuralVerify(), _Sneaky()]).run(document)
        assert result.diagnostics["sneaky"]  # the guard caught it despite no touch log

    def test_guards_do_not_run_for_read_only_passes(self):
        document = parse_to_uast(SOURCE)
        pipeline = Pipeline([StructuralVerify()], rollback=True)
        result = pipeline.run(document)
        assert result.rolled_back == [] and result.ok


class TestCloneHashReuse:
    def test_clone_inherits_digests(self):
        document = parse_to_uast(SOURCE)
        document.merkle_hash()
        clone = document.clone()
        reset_hash_stats()
        assert clone.merkle_hash() == document.merkle_hash()
        # Only the root chain is touched, not the whole tree.
        assert hash_stats()["computed"] < clone.node_count()

    def test_edit_after_clone_only_rehashes_the_path(self):
        document = parse_to_uast(SOURCE)
        document.merkle_hash()
        clone = document.clone()
        leaf = find(clone, "Identifier")
        leaf.name = "renamed"
        leaf.invalidate_hash()
        reset_hash_stats()
        clone.merkle_hash()
        assert hash_stats()["computed"] <= 5

    def test_clone_is_independent_after_edit(self):
        document = parse_to_uast(SOURCE)
        document.merkle_hash()
        before = document.canonical_hash()
        clone = document.clone()
        leaf = find(clone, "Identifier")
        leaf.name = "renamed"
        leaf.invalidate_hash()
        clone.merkle_hash()
        assert document.canonical_hash() == before
        assert clone.canonical_hash() != before


class TestMutationPipelineIntegration:
    def test_default_mutator_pipeline_leaves_valid_ir(self):
        document = parse_to_uast(SOURCE)
        pipeline = Pipeline(default_verifiers() + default_mutators(seed=5))
        result = pipeline.run(document)
        assert result.ok, [diag.message for diag in result.errors]
        assert result.rolled_back == []
        assert sum(result.mutations.values()) >= 1
        import ast

        ast.parse(document.emit())

    def test_negate_condition_keeps_parent_links(self):
        document = parse_to_uast(SOURCE)

        class _Negate(MutationPass):
            name = "negate"

            def run(self, root, arena=None):
                from muta_ext.uast2.mutators import NegateConditionPass

                NegateConditionPass(rate=1.0).run(root, arena)

        result = Pipeline([StructuralVerify(), ParentLinkVerify(), _Negate()]).run(document)
        assert result.ok, [diag.message for diag in result.errors]
        if_node = next(
            node for node in document.walk() if type(node).__name__ == "If"
        )
        assert type(if_node.condition).__name__ == "UnaryOp"
        assert if_node.condition._parent is if_node
        assert if_node.condition.operand._parent is if_node.condition
