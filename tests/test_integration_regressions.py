from types import SimpleNamespace

from island import Island
from models import FitnessVector, Individual, IslandConfig
from muta_lambda import EvolveConfig, MutaLambdaAgent


class DummyMigrationBus:
    def __init__(self):
        self.lineage_graph = None

    def register_island(self, island_id, island):
        self.island = island

    def migrate(self, island_id, generation):
        return None


class DummyEvaluator:
    def evaluate_batch(self, codes):
        from models import EvalResult

        results = []
        for _code in codes:
            fitness = FitnessVector(correctness=1.0, throughput=1.0, parsimony=0.5)
            results.append(
                EvalResult(
                    fitness=fitness,
                    passed=True,
                    metrics={"correctness": 1.0},
                    stdout="",
                    stderr="",
                    timed_out=False,
                )
            )
        return results


def test_receive_migrant_ignores_foreign_score():
    island = Island(
        island_id=0,
        config=IslandConfig(population_size=2, top_k=1),
        llm_fn=lambda _prompt: "def f():\n    return 1\n",
        evaluator=DummyEvaluator(),
        migration_bus=DummyMigrationBus(),
    )
    island.population = [
        Individual(code="def a():\n    return 1\n", score=5.0),
        Individual(code="def b():\n    return 2\n", score=2.0),
    ]

    migrant = Individual(code="def m():\n    return 3\n", score=999.0)
    island.receive_migrant(migrant)

    assert any(ind.code == migrant.code for ind in island.population)
    inserted = next(ind for ind in island.population if ind.code == migrant.code)
    assert inserted.score == float("-inf")
    assert inserted.fitness is None
    assert inserted.passed is False


def test_mutate_with_context_falls_back_to_mutate_when_unchanged(monkeypatch):
    island = Island(
        island_id=0,
        config=IslandConfig(population_size=2, top_k=1),
        llm_fn=lambda _prompt: "def f(x):\n    return x\n",
        evaluator=DummyEvaluator(),
        migration_bus=DummyMigrationBus(),
    )

    monkeypatch.setattr(
        island.core_engine,
        "mutate_with_llm",
        lambda code, score, error_info, llm_fn: code,
    )
    monkeypatch.setattr(
        island,
        "_mutate",
        lambda code: "def f(x):\n    return x + 1\n",
    )

    out = island._mutate_with_context("def f(x):\n    return x\n", score=0.0)
    assert out.strip() == "def f(x):\n    return x + 1"


def test_early_stop_uses_combined_score(monkeypatch):
    cfg = EvolveConfig(
        num_islands=1,
        generations=1,
        seed_codes=["def solution():\n    return 1\n"],
        population_size=2,
        top_k=1,
        archive_solutions=False,
        prompt_evolution=False,
        novelty_alpha=0.2,
    )
    agent = MutaLambdaAgent(
        config=cfg,
        test_cases=[],
        llm_fn=lambda _prompt: "def solution():\n    return 1\n",
        timeout_sec=1.0,
    )

    seen_scores = []
    monkeypatch.setattr(agent, "_score_with_novelty", lambda ind: ind.score + 42.0)
    monkeypatch.setattr(agent._early_stop, "update", lambda score: (seen_scores.append(score), False)[1])

    best = agent.run(task="")
    assert seen_scores, "expected early-stop update to be called"
    assert seen_scores[-1] == best.score + 42.0
