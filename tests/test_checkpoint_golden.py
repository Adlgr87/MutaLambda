"""Golden-master tests for checkpoint data model — auto-opt verification."""
import sys
sys.path.insert(0, ".")

from mutalambda_config.checkpoint_manager import CheckpointData
from mutalambda_engines.fitness_vector import FitnessVector

def test_checkpoint_data_fields_preserved():
    chkpt = CheckpointData(
        generation=5,
        island_populations=[[{"id": 1, "code": "x=1", "score": 1.0}]],
    )
    assert chkpt.generation == 5
    assert len(chkpt.island_populations) == 1
    assert chkpt.island_populations[0][0]["id"] == 1

def test_checkpoint_empty_population():
    chkpt = CheckpointData(generation=42, island_populations=[])
    assert len(chkpt.island_populations) == 0
    assert chkpt.generation == 42

def test_checkpoint_multiple_islands():
    chkpt = CheckpointData(
        generation=10,
        island_populations=[
            [{"id": 1, "code": "x=1", "score": 1.0}],
            [{"id": 2, "code": "x=2", "score": 0.5}],
        ],
    )
    assert len(chkpt.island_populations) == 2
    assert chkpt.island_populations[0][0]["id"] == 1
    assert chkpt.island_populations[1][0]["id"] == 2

def test_checkpoint_fitness_serialization():
    fv = FitnessVector(correctness=0.9999, latency_p50=0.0123, latency_p99=0.0456,
                       throughput=4242.0, memory_peak_mb=128.5, parsimony=0.7777)
    d = fv.to_dict()
    assert d["correctness"] == 0.9999
    assert d["latency_p50"] == 0.0123
    assert d["memory_peak_mb"] == 128.5

def test_checkpoint_growth_history():
    chkpt = CheckpointData(generation=20, island_populations=[])
    assert chkpt.generation == 20
