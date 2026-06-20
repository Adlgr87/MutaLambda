import ast

import muta_lambda
from muta_lambda import LineageGraph, LineageNode, MutaLambdaAgent, EvolveConfig, Individual
from muta_ext.lineage.compression import LineageCompressor


def _parseable(code: str) -> str:
    ast.parse(code)
    return code


def test_lineage_compressor_roundtrip_code_preserved():
    graph = LineageGraph()
    original_code = _parseable("def f(x):\n    return x + 1\n")

    node = LineageNode(
        id="n1",
        generation=1,
        score=10.0,
        code_hash=0,
        code=original_code,
        fitness={},
        island_id=0,
        parent_ids=[],
        alive=False,
        resurrected=False,
    )
    graph.nodes[node.id] = node

    comp = LineageCompressor(graph)
    saved = comp.compress_inactive(active_branch_ids=set())
    assert saved == 1

    assert graph.nodes["n1"].code == ""
    reconstructed = comp.decompress_node("n1")
    assert reconstructed == original_code


def test_resurrect_branch_uses_decompressed_node_code_when_code_empty(monkeypatch):
    # Minimizar dependencias: creamos un agente con llm_fn dummy.
    cfg = EvolveConfig(
        num_islands=1,
        generations=1,
        seed_codes=[],
        topology="ring",
        population_size=2,
        top_k=1,
        migration_interval=10,
        migrants_per_island=1,
        archive_solutions=False,
        prompt_evolution=False,
        checkpoint_interval=0,
    )

    # Agent requiere test_cases para el SandboxEvaluator; usamos []
    agent = MutaLambdaAgent(config=cfg, test_cases=[], llm_fn=lambda _p: "", timeout_sec=0.01)

    # Preparar un nodo abandonado comprimido: code="" y payload comprimido.
    abandoned = LineageNode(
        id="dead01",
        generation=1,
        score=9.0,
        code_hash=0,
        code=_parseable("def res(x):\n    return x * 2\n"),
        fitness={},
        island_id=0,
        parent_ids=[],
        alive=False,
        resurrected=False,
    )
    agent._lineage.nodes[abandoned.id] = abandoned

    comp = LineageCompressor(agent._lineage)
    comp.compress_inactive(active_branch_ids=set())

    # Asegurarnos: node.code está vacío tras compresión
    assert agent._lineage.nodes[abandoned.id].code == ""

    # Preparar stagnant_island: si falla la reconstrucción debería venir de local_best
    # pero aquí queremos que use el nodo reconstruido. Forzamos local_best a un código distinto.
    stagnant = agent._find_stagnant_island()
    # En este caso solo hay 1 isla; si no existe local_best, se usa fallback dentro del método.
    if stagnant is not None and stagnant.local_best is not None:
        stagnant.local_best.code = "def solution():\n    return -1\n"

    # Evitamos dependencias internas: verificamos que el método
    # arranque de la reconstrucción del nodo. Como la implementación
    # muta el código, verificamos por presencia de una parte clave
    # del contenido original (ignorando el mutador).

    resurrected = agent._resurrect_branch(agent._lineage.nodes[abandoned.id])
    assert isinstance(resurrected, Individual)

    # El mutador puede cambiar formato/espaciado; verificamos por
    # una subcadena clave del contenido del nodo reconstruido.
    assert "returnx*2" in resurrected.code.replace(" ", "").replace("\n", "")
