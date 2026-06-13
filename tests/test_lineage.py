"""
Tests for Fase 7: LineageGraph (Retroceso Temporal Multiversal).
"""

import pytest
from muta_lambda import (
    Individual,
    LineageGraph,
    LineageNode,
    FitnessVector,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_ind(code: str, score: float = 10.0,
              parent_ids: list = None) -> Individual:
    """Create a minimal individual with known parents."""
    ind = Individual(
        code=code,
        score=score,
        fitness=FitnessVector(correctness=score / 10.0),
    )
    if parent_ids:
        ind.parent_ids = parent_ids
    return ind


def _populate_chain(graph: LineageGraph, count: int = 5) -> list:
    """Create a linear chain of mutations and return the individuals."""
    inds = []
    prev = None
    for i in range(count):
        parents = [prev] if prev else []
        ind = _make_ind(
            f"def f(x): return x + {i}",
            score=10.0 + i,
            parent_ids=[p.id for p in parents] if parents else None,
        )
        if parents:
            graph.record(ind, parents, generation=i, island_id=0)
        else:
            # Seed individual — register manually
            graph.nodes[ind.id] = LineageNode(
                id=ind.id, generation=0, score=ind.score,
                code_hash=hash(ind.code) & 0xFFFFFFFF,
                island_id=0, alive=True,
            )
        inds.append(ind)
        prev = ind
    return inds


# ── Tests ──────────────────────────────────────────────────────────────────


def test_record_and_ancestors():
    """Registrar 5 generaciones y verificar ancestros del último."""
    graph = LineageGraph()
    inds = _populate_chain(graph, count=5)

    last = inds[-1]
    ancestors = graph.get_ancestors(last.id)

    # 4 ancestros (generation 0–3)
    assert len(ancestors) == 4
    for anc_id in ancestors:
        assert anc_id != last.id


def test_record_with_crossover():
    """Registrar un hijo con dos padres (crossover)."""
    graph = LineageGraph()
    # Dos padres independientes
    pa = _make_ind("def a():\n    return 1", score=8.0)
    pb = _make_ind("def b():\n    return 2", score=9.0)
    # Registrar padres manualmente como semillas
    graph.nodes[pa.id] = LineageNode(
        id=pa.id, generation=0, score=pa.score,
        code_hash=hash(pa.code) & 0xFFFFFFFF, island_id=0, alive=True,
    )
    graph.nodes[pb.id] = LineageNode(
        id=pb.id, generation=0, score=pb.score,
        code_hash=hash(pb.code) & 0xFFFFFFFF, island_id=0, alive=True,
    )

    child = _make_ind("def c():\n    return 3", score=10.0,
                      parent_ids=[pa.id, pb.id])
    graph.record(child, [pa, pb], generation=1, island_id=0)

    # Verificar ancestros
    ancestors = graph.get_ancestors(child.id)
    assert pa.id in ancestors
    assert pb.id in ancestors
    assert len(ancestors) == 2

    # Verificar que los padres están marcados como no vivos
    assert graph.nodes[pa.id].alive is False
    assert graph.nodes[pb.id].alive is False
    assert graph.nodes[child.id].alive is True


def test_genealogical_distance_same():
    """Distancia de un nodo a sí mismo es 0."""
    graph = LineageGraph()
    inds = _populate_chain(graph, count=3)
    assert graph.get_genealogical_distance(inds[0].id, inds[0].id) == 0


def test_genealogical_distance_parent_child():
    """Distancia padre→hijo = 1."""
    graph = LineageGraph()
    inds = _populate_chain(graph, count=3)
    assert graph.get_genealogical_distance(inds[0].id, inds[1].id) == 1


def test_genealogical_distance_siblings():
    """Distancia entre hermanos (mismo padre) = 2."""
    graph = LineageGraph()
    pa = _make_ind("def a():\n    return 1", score=5.0)
    # Registrar padre
    graph.nodes[pa.id] = LineageNode(
        id=pa.id, generation=0, score=pa.score,
        code_hash=hash(pa.code) & 0xFFFFFFFF, island_id=0, alive=True,
    )
    # Dos hijos del mismo padre
    c1 = _make_ind("def b():\n    return 2", score=6.0,
                   parent_ids=[pa.id])
    c2 = _make_ind("def c():\n    return 3", score=7.0,
                   parent_ids=[pa.id])
    graph.record(c1, [pa], generation=1, island_id=0)
    graph.record(c2, [pa], generation=1, island_id=0)

    dist = graph.get_genealogical_distance(c1.id, c2.id)
    assert dist == 2  # c1 → pa → c2


def test_genealogical_distance_unrelated():
    """Nodos sin conexión → None."""
    graph = LineageGraph()
    inds = _populate_chain(graph, count=2)

    isolated = _make_ind("def isolated():\n    pass", score=5.0)
    graph.nodes[isolated.id] = LineageNode(
        id=isolated.id, generation=99, score=isolated.score,
        code_hash=hash(isolated.code) & 0xFFFFFFFF, island_id=99, alive=True,
    )

    dist = graph.get_genealogical_distance(inds[0].id, isolated.id)
    assert dist is None


def test_find_abandoned_branches_empty():
    """Sin ramas abandonadas → lista vacía."""
    graph = LineageGraph()
    inds = _populate_chain(graph, count=5)
    candidates = graph.find_abandoned_branches(inds[-1].id, threshold_score=0.0)
    assert candidates == []


def test_find_abandoned_branches_finds_candidates():
    """Nodos fuera de la rama activa con score alto aparecen."""
    graph = LineageGraph()
    # Crear una cadena lineal (rama activa)
    chain = _populate_chain(graph, count=4)

    # Crear un nodo lateral (rama abandonada) con buen score
    lateral = _make_ind("def lateral():\n    return 99", score=15.0)
    graph.nodes[lateral.id] = LineageNode(
        id=lateral.id, generation=1, score=lateral.score,
        code_hash=hash(lateral.code) & 0xFFFFFFFF, island_id=1,
        alive=False,  # abandonado
    )

    candidates = graph.find_abandoned_branches(
        chain[-1].id, threshold_score=0.0,
    )
    assert len(candidates) >= 1
    assert any(c.id == lateral.id for c in candidates)


def test_find_abandoned_branches_skips_resurrected():
    """Nodo ya resucitado no aparece en candidatos."""
    graph = LineageGraph()
    chain = _populate_chain(graph, count=3)

    lateral = _make_ind("def lateral():\n    return 99", score=15.0)
    graph.nodes[lateral.id] = LineageNode(
        id=lateral.id, generation=1, score=lateral.score,
        code_hash=hash(lateral.code) & 0xFFFFFFFF, island_id=1,
        alive=False, resurrected=True,
    )

    candidates = graph.find_abandoned_branches(
        chain[-1].id, threshold_score=0.0,
    )
    assert not any(c.id == lateral.id for c in candidates)


def test_find_abandoned_branches_score_threshold():
    """Nodo con score bajo es filtrado."""
    graph = LineageGraph()
    chain = _populate_chain(graph, count=3)

    lateral = _make_ind("def lateral():\n    return 99", score=3.0)
    graph.nodes[lateral.id] = LineageNode(
        id=lateral.id, generation=1, score=lateral.score,
        code_hash=hash(lateral.code) & 0xFFFFFFFF, island_id=1,
        alive=False,
    )

    candidates = graph.find_abandoned_branches(
        chain[-1].id, threshold_score=5.0,
    )
    assert not any(c.id == lateral.id for c in candidates)


def test_serialization_roundtrip():
    """to_dict() → from_dict() preserva datos."""
    graph = LineageGraph()
    inds = _populate_chain(graph, count=5)

    data = graph.to_dict()
    restored = LineageGraph.from_dict(data)

    assert len(restored.nodes) == len(graph.nodes)
    for nid, node in graph.nodes.items():
        assert nid in restored.nodes
        rnode = restored.nodes[nid]
        assert rnode.generation == node.generation
        assert rnode.score == node.score
        assert rnode.alive == node.alive
        assert rnode.resurrected == node.resurrected
        assert rnode.parent_ids == node.parent_ids


def test_stats():
    """stats() retorna métricas correctas."""
    graph = LineageGraph()
    _populate_chain(graph, count=5)

    s = graph.stats()
    assert s["total_nodes"] == 5
    assert s["max_depth"] >= 4
    assert s["generations"] >= 4
    assert s["resurrections"] == 0


def test_empty_graph_stats():
    """Grafo vacío tiene stats coherentes."""
    graph = LineageGraph()
    s = graph.stats()
    assert s["total_nodes"] == 0
    assert s["max_depth"] == 0
    assert s["branches"] == 0
