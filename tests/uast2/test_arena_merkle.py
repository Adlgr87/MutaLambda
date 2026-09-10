#!/usr/bin/env python3
"""Arena slab, parent pointers and incremental Merkle hashing."""

import pytest

from muta_ext.uast2 import core as v2
from muta_ext.uast2.adapters import parse_to_uast
from muta_ext.uast2.arena import Arena, assign_parents, clone_tree, prepare, replace_node
from muta_ext.uast2.merkle import (
    hash_stats,
    invalidate_subtree,
    node_digest,
    recompute_all,
    reset_hash_stats,
    root_digest,
)
from muta_ext.uast2.visitor import NodeTransformer


def sample_tree():
    return parse_to_uast("def f(x):\n    y = x + 1\n    return y\n", prepare=True)


class TestArena:
    def test_allocate_assigns_sequential_ids(self):
        document = sample_tree()
        arena = Arena()
        allocated = arena.allocate_all(document)
        assert allocated == document.node_count()
        assert [node._id for node in document.walk()] == list(range(document.node_count()))
        assert all(arena.get(node._id) is node for node in document.walk())

    def test_allocate_all_is_idempotent(self):
        document = sample_tree()
        arena = Arena()
        first = arena.allocate_all(document)
        second = arena.allocate_all(document)
        assert first > 0 and second == 0
        assert arena.stats()["slots"] == first

    def test_release_and_recycle(self):
        document = sample_tree()
        arena = Arena()
        arena.allocate_all(document)
        victim = document.body[0]
        arena.release(victim)
        assert victim._id is None
        assert arena.stats()["free"] == 1
        fresh = v2.Break()
        arena.alloc(fresh)
        assert arena.stats()["recycled"] == 1
        assert arena.get(fresh._id) is fresh

    def test_release_subtree_and_compact(self):
        document = sample_tree()
        arena = Arena()
        arena.allocate_all(document)
        function = document.body[0]
        released = arena.release_subtree(function)
        assert released == document.node_count()
        assert arena.compact() > 0
        assert arena.stats()["live"] == 0

    def test_stats_and_contains(self):
        document = sample_tree()
        arena = Arena()
        arena.allocate_all(document)
        stats = arena.stats()
        assert stats["live"] == stats["allocations"] == document.node_count()
        assert document.body[0] in arena
        assert v2.Break() not in arena

    def test_assign_parents_returns_link_count(self):
        document = v2.CoreUAST(
            body=[v2.Return(value=v2.BinaryOp(left=v2.Identifier(name="a"), op="+", right=v2.Identifier(name="b")))]
        )
        links = assign_parents(document)
        assert links == 3  # Return.value, BinaryOp.left, BinaryOp.right
        inner = document.body[0].value
        assert inner.left._parent is inner and inner.left._slot == "left"
        assert document.body[0]._parent is None  # body roots have no parent

    def test_prepare_with_arena(self):
        document = sample_tree()
        arena = Arena()
        returned = prepare(document, arena)
        assert returned is document
        assert document.prepared is True
        assert len(arena) == document.node_count()
        assert document.body[0]._parent is None

    def test_replace_node_keeps_arena_consistent(self):
        document = sample_tree()
        arena = Arena()
        document.prepare(arena)
        target = document.body[0].body[0].value.left  # Identifier x
        replacement = v2.Identifier(name="z")
        replace_node(target, replacement, arena=arena)
        assert document.body[0].body[0].value.left is replacement
        assert replacement._parent is document.body[0].body[0].value
        assert arena.get(replacement._id) is replacement

    def test_clone_tree_is_independent(self):
        document = sample_tree()
        clone = clone_tree(document.body[0])
        assert clone is not document.body[0]
        assert clone.body[0]._parent is clone
        # Mutating the copy must not touch the original.
        clone.body[0].value.left.name = "changed"
        assert document.body[0].body[0].value.left.name == "x"


class TestMerkle:
    def setup_method(self):
        reset_hash_stats()

    def test_digest_stable_and_cached(self):
        document = sample_tree()
        first = root_digest(document)
        computed_after_first = hash_stats()["computed"]
        second = root_digest(document)
        assert first == second
        # Nothing is recomputed when the tree is untouched (root digest is cached).
        assert hash_stats()["computed"] == computed_after_first

    def test_incremental_matches_full_recompute(self):
        document = sample_tree()
        incremental = root_digest(document)
        assert incremental == recompute_all(document)

    def test_edit_invalidates_only_ancestors(self):
        document = sample_tree()
        before = root_digest(document)
        target = document.body[0].body[0].value.left
        target.name = "renamed"
        target.invalidate_hash()
        assert target._hash is None
        for ancestor in (document.body[0].body[0].value, document.body[0].body[0]):
            assert ancestor._hash is None
        assert root_digest(document) != before
        assert root_digest(document) == root_digest(document.clone())

    def test_transformer_invalidates_through_parents(self):
        document = sample_tree()
        before = root_digest(document)

        class Rename(NodeTransformer):
            def visit_Identifier(self, node):
                node.name = node.name.upper()
                node.invalidate_hash()
                return node

        Rename().transform(document)
        assert root_digest(document) != before

    def test_clone_has_same_digest(self):
        document = sample_tree()
        clone = document.clone()
        assert root_digest(clone) == root_digest(document)
        assert clone.canonical_hash() == document.canonical_hash()

    def test_invalidate_subtree(self):
        document = sample_tree()
        root_digest(document)
        assert invalidate_subtree(document.body[0]) > 0

    def test_node_digest_bytes(self):
        digest = node_digest(v2.Identifier(name="x"))
        assert isinstance(digest, bytes) and len(digest) == 32


class TestCloneCorrectness:
    """`clone()` must be a faithful copy (digests, parents, cold/warm paths)."""

    SOURCE = "def f(n):\n    total = 0\n    for i in range(0, n):\n        total = total + i * 2\n    return total\n"

    def test_clone_is_prepared_and_has_no_stale_links(self):
        document = parse_to_uast(self.SOURCE)
        clone = document.clone()
        assert clone.prepared is True
        for node in clone.walk():
            if node._parent is not None:
                assert node._slot is not None
        assert clone.canonical_hash() == document.canonical_hash()

    def test_clone_of_unhashed_parent_still_hashes_correctly(self):
        document = parse_to_uast(self.SOURCE)  # never hashed: all digests are None
        clone = document.clone()
        assert clone.merkle_hash() == document.merkle_hash()

    def test_clone_does_not_alias_mutable_scalar_fields(self):
        document = parse_to_uast(self.SOURCE)
        literal = next(node for node in document.walk() if type(node).__name__ == "LiteralNode")
        literal.value = [1, 2, 3]  # literal list value (mutated as a whole below)
        clone = document.clone()
        clone_literal = next(node for node in clone.walk() if type(node).__name__ == "LiteralNode")
        clone_literal.value.append(4)
        assert literal.value == [1, 2, 3]

    def test_clone_keeps_sharing_inside_a_subtree(self):
        """Sharing is copied as sharing inside a subtree (roots are independent)."""
        shared = v2.Identifier(name="x")
        document = v2.CoreUAST(body=[v2.BinaryOp(left=shared, op="+", right=shared)])
        clone = document.clone()
        assert clone.body[0].left is clone.body[0].right is not shared

    def test_clone_detaches_body_roots(self):
        document = parse_to_uast(self.SOURCE)
        clone = document.clone()
        for root in clone.body:
            assert root._parent is None and root._slot is None
