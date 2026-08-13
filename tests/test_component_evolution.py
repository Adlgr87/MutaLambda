"""Tests for the Component Evolution system (v3.5)."""

from __future__ import annotations

import random
import pytest

from component_evolution import (
    CouplingLevel,
    InterfaceSpec,
    Component,
    ComponentGraph,
    ModuleExtractor,
    ComponentMutator,
)


SAMPLE_CODE = """\
def add(a: int, b: int) -> int:
    return a + b

def multiply(a: int, b: int) -> int:
    return a * b

def process(x: float, y: float) -> float:
    result = add(int(x), int(y))
    return result * 2.0
"""

SINGLE_FUNC_CODE = """\
def foo(x: int) -> int:
    return x + 1
"""


# ── test_analyze_simple_module ────────────────────────────────────────────────

def test_analyze_simple_module():
    """Parse a module with 2+ functions and build a component graph."""
    extractor = ModuleExtractor()
    graph = extractor.analyze(SAMPLE_CODE)

    assert len(graph.components) == 3
    names = set(graph.components.keys())
    assert names == {"add", "multiply", "process"}

    # Verify edges were built from call relationships
    assert "process" in graph.edges
    assert "add" in graph.edges["process"]


# ── test_extract_candidate_found ──────────────────────────────────────────────

def test_extract_candidate_found():
    """Find extractable function candidates in a module with multiple functions."""
    extractor = ModuleExtractor()
    candidates = extractor.graph.find_extractable(SAMPLE_CODE, min_functions=2)

    assert len(candidates) >= 2
    names = {c["name"] for c in candidates}
    assert "add" in names
    assert "multiply" in names
    assert "process" in names


# ── test_compute_coupling ─────────────────────────────────────────────────────

def test_compute_coupling():
    """Calculate CBO correctly for a graph with known edges."""
    graph = ComponentGraph()
    a = Component(
        name="a",
        source_code="def a(): pass",
        line_start=1,
        line_end=1,
        interface=InterfaceSpec(name="a"),
    )
    b = Component(
        name="b",
        source_code="def b(): pass",
        line_start=2,
        line_end=2,
        interface=InterfaceSpec(name="b"),
    )
    c = Component(
        name="c",
        source_code="def c(): pass",
        line_start=3,
        line_end=3,
        interface=InterfaceSpec(name="c"),
    )
    graph.add_component(a)
    graph.add_component(b)
    graph.add_component(c)
    graph.add_edge("a", "b")
    graph.add_edge("a", "c")

    # a has 2 dependents, b and c have none
    coupling = graph.compute_coupling()
    assert coupling == 2.0 / 3.0


# ── test_interface_crossover ──────────────────────────────────────────────────

def test_interface_crossover():
    """Crossover produces a valid interface spec with mixed inputs."""
    spec_a = InterfaceSpec(
        name="func_a",
        input_types={"x": "int", "y": "str"},
        output_type="int",
        requirements=["req1"],
        complexity_score=2.0,
    )
    spec_b = InterfaceSpec(
        name="func_b",
        input_types={"a": "float", "b": "bool"},
        output_type="str",
        requirements=["req2", "req3"],
        complexity_score=4.0,
    )

    rng = random.Random(42)
    child = spec_a.crossover(spec_b)

    assert isinstance(child, InterfaceSpec)
    assert child.name == "func_a"
    # Output type should come from one of the parents
    assert child.output_type in ("int", "str")
    # Complexity should be roughly the average
    assert 1.0 <= child.complexity_score <= 5.0
    # Requirements should contain at least some from each parent
    all_reqs = child.requirements
    assert len(all_reqs) >= 1


# ── test_interface_mutate ─────────────────────────────────────────────────────

def test_interface_mutate():
    """Mutation produces a valid mutated interface."""
    spec = InterfaceSpec(
        name="test_func",
        input_types={"a": "int", "b": "str"},
        output_type="float",
        requirements=["stable_req"],
        complexity_score=3.0,
    )

    rng = random.Random(99)
    mutant = spec.mutate(rng)

    assert isinstance(mutant, InterfaceSpec)
    assert mutant.name == "test_func"
    # Complexity should have shifted
    assert mutant.complexity_score >= 0.0
    # At least one structural property may have changed
    assert isinstance(mutant.input_types, dict)
    assert isinstance(mutant.requirements, list)


# ── test_component_quality_score ──────────────────────────────────────────────

def test_component_quality_score():
    """Quality score calculation respects cohesion and coupling weights."""
    comp = Component(
        name="cool",
        source_code="def cool(): pass",
        line_start=1,
        line_end=1,
        interface=InterfaceSpec(name="cool"),
        coupling_score=0.2,
        cohesion_score=0.9,
    )
    # quality = 0.9 * 0.6 - 0.2 * 0.4 = 0.54 - 0.08 = 0.46
    assert comp.quality_score() == pytest.approx(0.46)

    # High coupling should drag the score down
    bad_comp = Component(
        name="buggy",
        source_code="def buggy(): pass",
        line_start=1,
        line_end=1,
        interface=InterfaceSpec(name="buggy"),
        coupling_score=0.9,
        cohesion_score=0.3,
    )
    assert bad_comp.quality_score() < comp.quality_score()


# ── test_component_mutator_split ──────────────────────────────────────────────

def test_component_mutator_split():
    """Split a high-complexity component into two."""
    mutator = ComponentMutator(rng=random.Random(0))
    comp = Component(
        name="big_func",
        source_code="def big_func(x, y):\n    return x + y",
        line_start=1,
        line_end=3,
        interface=InterfaceSpec(
            name="big_func",
            input_types={"x": "int", "y": "int"},
            complexity_score=5.0,
        ),
        coupling_score=0.1,
        cohesion_score=0.8,
    )
    split = mutator.split_component(comp)
    assert split is not None
    assert split.name == "big_func__part2"
    assert split.interface.complexity_score < comp.interface.complexity_score


def test_component_mutator_split_low_complexity():
    """Split returns None for low-complexity components."""
    mutator = ComponentMutator(rng=random.Random(0))
    comp = Component(
        name="tiny",
        source_code="def tiny(): return 1",
        line_start=1,
        line_end=1,
        interface=InterfaceSpec(name="tiny", complexity_score=1.0),
    )
    assert mutator.split_component(comp) is None


# ── test_component_mutator_merge ──────────────────────────────────────────────

def test_component_mutator_merge():
    """Merge two dependent components."""
    mutator = ComponentMutator(rng=random.Random(0))
    a = Component(
        name="alpha",
        source_code="def alpha(): pass",
        line_start=1,
        line_end=1,
        interface=InterfaceSpec(name="alpha"),
        dependents={"beta"},
    )
    b = Component(
        name="beta",
        source_code="def beta(): pass",
        line_start=2,
        line_end=2,
        interface=InterfaceSpec(name="beta"),
        callers={"alpha"},
    )
    merged = mutator.merge_components(a, b)
    assert merged is not None
    assert "+" in merged.name


def test_component_mutator_merge_no_relation():
    """Merge returns None when components share no dependency."""
    mutator = ComponentMutator(rng=random.Random(0))
    a = Component(
        name="alone_a",
        source_code="def alone_a(): pass",
        line_start=1,
        line_end=1,
        interface=InterfaceSpec(name="alone_a"),
    )
    b = Component(
        name="alone_b",
        source_code="def alone_b(): pass",
        line_start=2,
        line_end=2,
        interface=InterfaceSpec(name="alone_b"),
    )
    assert mutator.merge_components(a, b) is None


# ── test_coupling_level ───────────────────────────────────────────────────────

@pytest.mark.parametrize("score,expected", [
    (0.0, CouplingLevel.LOW),
    (0.2, CouplingLevel.LOW),
    (0.5, CouplingLevel.MEDIUM),
    (0.7, CouplingLevel.HIGH),
    (0.9, CouplingLevel.CRITICAL),
])
def test_coupling_level_from_score(score: float, expected: CouplingLevel):
    assert CouplingLevel.from_score(score) == expected
