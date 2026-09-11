from types import SimpleNamespace
import pytest
import island as island_module
from fitness_vector import FitnessVector
from island import Island
from models import EvalResult, Individual, IslandConfig
from workflow_protocol import PASS, RETRYABLE_FAIL

# T4 Helper
class _EvalWithMetrics:
    def __init__(self, metrics, passed=True):
        self.metrics = metrics
        self.passed = passed
        # Mock FitnessVector (simplified)
        self.fitness = SimpleNamespace(
            correctness=metrics.get("correctness", 1.0),
            throughput=metrics.get("throughput", 1.0),
            parsimony=metrics.get("parsimony", 0.5),
        )

class RecordingEvaluator:
    def __init__(self, metrics_override=None):
        self.calls = []
        self.metrics_override = metrics_override

    def evaluate_batch(self, codes):
        self.calls.append(list(codes))
        results = []
        for code in codes:
            metrics = self.metrics_override if self.metrics_override else {
                "correctness": 1.0,
                "score": 1.0,
            }
            fitness = FitnessVector(
                correctness=metrics.get("correctness", 1.0),
                throughput=metrics.get("throughput", 1.0),
                parsimony=metrics.get("parsimony", 0.5),
            )
            results.append(
                EvalResult(
                    fitness=fitness,
                    passed=True,
                    metrics=metrics,
                    stdout="",
                    stderr="",
                    timed_out=False,
                )
            )
        return results

class DummyMigrationBus:
    def register_island(self, island_id, island):
        self.island = island
    def migrate(self, island_id, generation):
        return None

def setup_island(scientific_config):
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
            scientific_config=scientific_config,
        ),
    )
    island.population = [
        Individual(code="def candidate():\n    return 1\n"),
        Individual(code="def candidate():\n    return 1\n"),
    ]
    return island, traces, evaluator

def test_scientific_validation_disabled_passthrough(monkeypatch):
    scientific_config = {"enabled": False}
    island, traces, _ = setup_island(scientific_config)
    
    monkeypatch.setattr(island, "_mutate_with_context", lambda c, s, e="": "def candidate():\n    return 1\n")
    monkeypatch.setattr(island_module.random, "random", lambda: 0.5)
    monkeypatch.setattr(island_module.ASTMutator, "apply_random_mutation", lambda c: "def candidate():\n    return 1\n")
    # Remote's Phase 6.5 short-circuits AST-only mutations to a reduced workflow
    # that skips the SVL gate; force the full workflow so the gate is exercised.
    monkeypatch.setattr(island, "_is_ast_only_mutation", lambda parent_code, mutated_code, strategy: False)
    
    island._evolve_local()
    
    assert len(traces) > 0
    trace = traces[0]
    assert trace["decision"] == "promote"
    svl_stage = next((s for s in trace["stages"] if s["name"] == "scientific_validation"), None)
    assert svl_stage is not None
    assert svl_stage["status"] == "PASS"
    assert "disabled" in svl_stage["message"].lower()

def test_scientific_validation_rejects_conservation_violation(monkeypatch):
    # Violates energy_non_negative: total_energy = -5.0
    scientific_config = {
        "enabled": True, 
        "validation": {
            "invariants": True, "numerical_stability": True, "conservation_checks": True, "property_based": True
        }
    }
    island, traces, evaluator = setup_island(scientific_config)
    evaluator.metrics_override = {"correctness": 1.0, "total_energy": -5.0}
    
    monkeypatch.setattr(island, "_mutate_with_context", lambda c, s, e="": "def candidate():\n    return 1\n")
    monkeypatch.setattr(island_module.random, "random", lambda: 0.5)
    monkeypatch.setattr(island_module.ASTMutator, "apply_random_mutation", lambda c: "def candidate():\n    return 1\n")
    # Remote's Phase 6.5 short-circuits AST-only mutations to a reduced workflow
    # that skips the SVL gate; force the full workflow so the gate is exercised.
    monkeypatch.setattr(island, "_is_ast_only_mutation", lambda parent_code, mutated_code, strategy: False)
    
    island._evolve_local()
    
    trace = traces[0]
    svl_stage = next((s for s in trace["stages"] if s["name"] == "scientific_validation"), None)
    assert svl_stage is not None
    assert svl_stage["status"] == "FAIL"
    assert trace["decision"] == "reject"

def test_scientific_validation_passthrough_when_enabled_clean(monkeypatch):
    scientific_config = {
        "enabled": True, 
        "validation": {
            "invariants": True, "numerical_stability": True, "conservation_checks": True, "property_based": True
        }
    }
    island, traces, evaluator = setup_island(scientific_config)
    # Clean metrics
    evaluator.metrics_override = {"correctness": 1.0, "total_energy": 10.0, "score": 1.0}
    
    monkeypatch.setattr(island, "_mutate_with_context", lambda c, s, e="": "def candidate():\n    return 1\n")
    monkeypatch.setattr(island_module.random, "random", lambda: 0.5)
    monkeypatch.setattr(island_module.ASTMutator, "apply_random_mutation", lambda c: "def candidate():\n    return 1\n")
    # Remote's Phase 6.5 short-circuits AST-only mutations to a reduced workflow
    # that skips the SVL gate; force the full workflow so the gate is exercised.
    monkeypatch.setattr(island, "_is_ast_only_mutation", lambda parent_code, mutated_code, strategy: False)
    
    island._evolve_local()
    
    trace = traces[0]
    svl_stage = next((s for s in trace["stages"] if s["name"] == "scientific_validation"), None)
    assert svl_stage is not None
    assert svl_stage["status"] == "PASS"
    assert trace["decision"] == "promote"

def test_stage_runner_disabled_and_enabled():
    from muta_ext.scientific.validation import run_scientific_validation_stage
    
    # Disabled
    disabled = run_scientific_validation_stage({
        "eval_result": None, 
        "scientific_config": {"enabled": False}
    })
    assert disabled.status == "PASS"
    assert disabled.metadata["scientific_score"] == 1.0
    
    # Enabled with violation
    enabled = run_scientific_validation_stage({
        "eval_result": _EvalWithMetrics({"total_energy": -5.0}),
        "scientific_config": {
            "enabled": True, 
            "validation": {
                "invariants": True, "numerical_stability": True, "conservation_checks": True, "property_based": True
            }
        }
    })
    assert enabled.status == "FAIL"
    assert enabled.metadata["scientific_score"] < 1.0
