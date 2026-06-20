"""Tests for MutaLambda Evolution Upgrade v2.0 extensions."""

from __future__ import annotations

from checkpoint_manager import Checkpoint, _serialise_checkpoint
from fitness_vector import FitnessVector
from models import Individual, LineageGraph
from muta_ext.advanced_selection import AdvancedSelectionConfig, AdvancedSelectionEngine
from muta_ext.dialectic_engine import DialecticConfig, DialecticEngine
from muta_ext.pattern_memory import PatternMemory
from muta_ext.spatial_topology import SpatialConfig, SpatialTopology
from muta_ext.thc_engine import HorizontalTransferEngine, THCConfig


class FakeEvaluator:
    def evaluate_batch(self, codes):
        class Result:
            def __init__(self):
                self.fitness = FitnessVector(correctness=1.0, parsimony=1.0)
                self.passed = True
                self.stderr = ""

            @property
            def score(self):
                return self.fitness.to_scalar()

        return [Result() for _ in codes]


def test_advanced_selection_entropy_scores_population():
    pop = [
        Individual("def a(x):\n    return x + 1", score=1.0),
        Individual("def b(x):\n    return x * 2", score=2.0),
    ]
    engine = AdvancedSelectionEngine(AdvancedSelectionConfig(enabled=True))

    engine.score_population(pop)

    assert engine.metrics.population_entropy > 0.0
    assert engine.metrics.scored_individuals == 2
    assert all(hasattr(ind, "advanced_score") for ind in pop)


def test_advanced_selection_discovery_score_uses_descendants():
    graph = LineageGraph()
    parent = Individual("def f(x):\n    return x", score=1.0)
    child = Individual("def f(x):\n    return x + 1", score=2.0)
    graph.record(child, [parent], generation=1, island_id=0)
    engine = AdvancedSelectionEngine(
        AdvancedSelectionConfig(enabled=True),
        lineage_graph=graph,
    )

    assert engine.discovery_score(parent.id) > 0.0


def test_advanced_selection_disabled_preserves_score():
    ind = Individual("def f():\n    return 1", score=3.0)
    engine = AdvancedSelectionEngine(AdvancedSelectionConfig(enabled=False))

    engine.score_population([ind])

    assert ind.score == 3.0


def test_thc_harvests_and_creates_hybrid():
    donor = Individual("def helper(x):\n    return x + 1", score=10.0)
    receiver = Individual("def solve(x):\n    return x", score=1.0)
    engine = HorizontalTransferEngine(
        THCConfig(enabled=True, max_transfers_per_generation=4, min_donor_score=0.0)
    )

    result = engine.apply([donor, receiver], FakeEvaluator(), generation=1)

    assert len(result) == 2
    assert engine.metrics.transfers_attempted >= 1
    assert any(getattr(ind, "imported_fragments", []) for ind in result)


def test_thc_disabled_noop():
    pop = [Individual("def f():\n    return 1", score=1.0)]
    engine = HorizontalTransferEngine(THCConfig(enabled=False))

    assert engine.apply(pop, FakeEvaluator(), generation=1) == pop


def test_thc_records_fragment_survival():
    donor = Individual("def helper(x):\n    return x + 1", score=10.0)
    receiver = Individual("def solve(x):\n    return x", score=1.0)
    engine = HorizontalTransferEngine(THCConfig(enabled=True))

    engine.apply([donor, receiver], FakeEvaluator(), generation=1)

    assert engine.metrics.fragment_survival_gens >= 0.0


def test_dialectic_rejects_invalid_thesis():
    engine = DialecticEngine(DialecticConfig(enabled=True))

    result = engine.refine(
        "def f():\n    return 1",
        "def f(:",
        lambda _prompt: "unused",
    )

    assert result == "def f():\n    return 1"
    assert engine.metrics.sandbox_calls_saved == 1


def test_dialectic_accepts_valid_synthesis():
    engine = DialecticEngine(DialecticConfig(enabled=True))
    calls = []

    def llm(prompt):
        calls.append(prompt)
        if "Synthesize" in prompt:
            return "def f():\n    return 2"
        return "looks fine"

    result = engine.refine("def f():\n    return 1", "def f():\n    return 1", llm)

    assert result == "def f():\n    return 2"
    assert len(calls) == 2


def test_dialectic_disabled_returns_thesis():
    engine = DialecticEngine(DialecticConfig(enabled=False))

    result = engine.refine("base", "thesis", lambda _prompt: "ignored")

    assert result == "thesis"


def test_spatial_moore_neighbors_include_diagonal():
    topology = SpatialTopology(SpatialConfig(enabled=True, neighborhood="moore"))

    neighbors = topology.neighbors(4, list(range(9)))

    assert set(neighbors) == {0, 1, 2, 3, 5, 6, 7, 8}


def test_spatial_von_neumann_neighbors_are_direct():
    topology = SpatialTopology(SpatialConfig(enabled=True, neighborhood="von_neumann"))

    neighbors = topology.neighbors(4, list(range(9)))

    assert set(neighbors) == {1, 3, 5, 7}


def test_spatial_metrics_update():
    class IslandLike:
        population = [Individual("def f():\n    return 1")]

    topology = SpatialTopology(SpatialConfig(enabled=True))

    metrics = topology.update_metrics({0: IslandLike(), 1: IslandLike()})

    assert metrics.cluster_count >= 1


def test_pattern_memory_observe_and_best():
    memory = PatternMemory()

    memory.observe("shape", "FunctionDef,Return", True, "ctx", "node1")
    memory.observe("shape", "FunctionDef,Return", False, "ctx", "node2")

    best = memory.best()
    assert best[0].observations == 2
    assert best[0].success_rate == 0.5


def test_pattern_memory_roundtrip():
    memory = PatternMemory()
    memory.observe("shape", "A", True, "ctx", "node")

    restored = PatternMemory.from_dict(memory.to_dict())

    assert restored.best()[0].signature == "A"


def test_lineage_serializes_hybrid_metadata():
    graph = LineageGraph()
    parent = Individual("def f():\n    return 1", score=1.0)
    child = Individual("def f():\n    return 2", score=2.0)
    setattr(child, "imported_fragments", ["helper"])
    setattr(child, "creation_reason", "thc_transfer")

    graph.record(child, [parent], generation=1, island_id=0, reason="thc_transfer")
    restored = LineageGraph.from_dict(graph.to_dict())

    node = restored.nodes[child.id]
    assert node.imported_fragments == ["helper"]
    assert node.creation_reason == "thc_transfer"


def test_checkpoint_serializes_upgrade_metrics():
    cp = Checkpoint(
        generation=1,
        advanced_metrics={"population_entropy": 0.5},
        thc_metrics={"thc_transfer_rate": 0.25},
        dialectic_metrics={"sandbox_calls_saved": 2},
        spatial_metrics={"local_diversity_index": 0.7},
        pattern_memory={"records": {}},
    )

    data = _serialise_checkpoint(cp)

    assert data["advanced_metrics"]["population_entropy"] == 0.5
    assert data["thc_metrics"]["thc_transfer_rate"] == 0.25
    assert data["pattern_memory"] == {"records": {}}
