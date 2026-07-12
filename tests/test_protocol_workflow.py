from types import SimpleNamespace

import island as island_module
from fitness_vector import FitnessVector
from island import Island
from models import EvalResult, Individual, IslandConfig
from workflow_protocol import (
    PASS,
    RETRYABLE_FAIL,
    ProtocolStage,
    ProtocolTrace,
    ProtocolWorkflow,
    make_stage_result,
)


class DummyMigrationBus:
    def register_island(self, island_id, island):
        self.island = island

    def migrate(self, island_id, generation):
        return None


class RecordingEvaluator:
    def __init__(self):
        self.calls = []

    def evaluate_batch(self, codes):
        self.calls.append(list(codes))
        results = []
        for code in codes:
            passed = "return 1" in code and "eval(" not in code
            fitness = FitnessVector(
                correctness=1.0 if passed else 0.0,
                throughput=1.0 if passed else 0.0,
                parsimony=0.5,
            )
            results.append(
                EvalResult(
                    fitness=fitness,
                    passed=passed,
                    metrics={"correctness": fitness.correctness},
                    stdout="",
                    stderr="" if passed else "unsafe",
                    timed_out=False,
                )
            )
        return results


def test_protocol_workflow_stops_on_retryable_stage_in_order():
    seen = []

    def stage(name, status):
        def _runner(_context):
            seen.append(name)
            return make_stage_result(name, status, name)

        return _runner

    workflow = ProtocolWorkflow(
        [
            ProtocolStage("generate_candidate", stage("generate_candidate", PASS)),
            ProtocolStage("tests_gate", stage("tests_gate", RETRYABLE_FAIL)),
            ProtocolStage("decision_gate", stage("decision_gate", PASS)),
        ]
    )
    trace = ProtocolTrace(run_id="run-1", subject_id="candidate-1")

    accepted = workflow.execute({}, trace)

    assert accepted is False
    assert trace.decision == "retry"
    assert seen == ["generate_candidate", "tests_gate"]
    assert trace.stage_names() == ["generate_candidate", "tests_gate"]


def test_island_candidate_workflow_retries_unsafe_candidate(monkeypatch):
    evaluator = RecordingEvaluator()
    bus = DummyMigrationBus()
    island = Island(
        island_id=0,
        config=IslandConfig(population_size=2, top_k=1),
        llm_fn=lambda _prompt: "",
        evaluator=evaluator,
        migration_bus=bus,
    )

    traces = []
    island.configure_protocol(
        run_id="run-123",
        trace_sink=lambda trace: traces.append(trace.to_dict()),
        agent=None,
        config=SimpleNamespace(
            workflow_enabled=True,
            workflow_max_retries=1,
            workflow_correctness_threshold=1.0,
            workflow_require_score_improvement=False,
            workflow_enforce_security=True,
        ),
    )
    island.population = [
        Individual(code="def candidate():\n    return 1\n"),
        Individual(code="def candidate():\n    return 1\n"),
    ]

    monkeypatch.setattr(
        island,
        "_mutate_with_context",
        lambda code, score, error_info="": "def candidate():\n    return eval('1')\n",
    )
    monkeypatch.setattr(island_module.random, "random", lambda: 0.5)
    monkeypatch.setattr(
        island_module.ASTMutator,
        "apply_random_mutation",
        lambda code: "def candidate():\n    return 1\n",
    )

    island._evolve_local()

    assert len(traces) == 1
    trace = traces[0]
    assert trace["decision"] == "promote"
    assert trace["attempts"] == 2
    assert any(
        stage["name"] == "security_gate" and stage["status"] == "RETRYABLE_FAIL"
        for stage in trace["stages"]
    )
    assert trace["stages"][-1]["name"] == "decision_gate"
    assert trace["stages"][-1]["status"] == "PASS"
    assert island.population[-1].creation_reason == "mutation_retry"
    assert all("eval(" not in code for batch in evaluator.calls for code in batch)
