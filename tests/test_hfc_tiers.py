import ast

from fitness_vector import FitnessVector
from hfc_tiers import (
    HFCLeagueEngine,
    HFCTierConfig,
    TIER_ELITE,
    TIER_FACTORY,
    TIER_LABORATORY,
)
from models import EvalResult, Individual, LineageGraph


class _MockEvaluator:
    def __init__(self, functional_codes):
        self.functional_codes = set(functional_codes)

    def evaluate_batch(self, codes):
        results = []
        for code in codes:
            if code in self.functional_codes:
                fitness = FitnessVector(
                    correctness=1.0,
                    latency_p50=0.01,
                    latency_p99=0.01,
                    throughput=100.0,
                    memory_peak_mb=1.0,
                    parsimony=0.8,
                )
                results.append(
                    EvalResult(
                        fitness=fitness,
                        passed=True,
                        metrics=fitness.to_dict(),
                    )
                )
            else:
                fitness = FitnessVector.worst()
                results.append(
                    EvalResult(
                        fitness=fitness,
                        passed=False,
                        metrics=fitness.to_dict(),
                        stderr="syntax error",
                    )
                )
        return results


def _engine(lambda_clones=0, tier3_size=1):
    return HFCLeagueEngine(
        HFCTierConfig(
            max_tier1_size=10,
            max_tier2_size=10,
            max_tier3_size=tier3_size,
            lambda_clones=lambda_clones,
            top_down_distillation=False,
        ),
    )


def test_hfc_keeps_failures_in_laboratory_and_promotes_functional_code():
    good_code = "def f(x):\n    return x + 1\n"
    bad_code = "def broken(:\n"
    elite_code = "def f(x):\n    return x\n"

    engine = _engine(tier3_size=1)
    engine.tier1 = [Individual(code=good_code), Individual(code=bad_code)]
    engine.tier3 = [Individual(code=elite_code)]
    evaluator = _MockEvaluator(functional_codes={good_code, good_code.strip(), elite_code})

    snapshot = engine.step(
        llm_fn=lambda _prompt: good_code,
        evaluator=evaluator,
        generation=0,
        lineage_graph=LineageGraph(),
    )

    assert snapshot.tier_counts[TIER_LABORATORY] >= 1
    assert any(ind.tier == TIER_FACTORY and ind.passed for ind in engine.tier2)
    assert all(ind.tier == TIER_LABORATORY for ind in engine.tier1)


def test_tier2_bacterial_reproduction_clones_without_lineage_noise():
    parent_code = "def f(x):\n    return x + 1\n"
    engine = _engine(lambda_clones=3, tier3_size=1)
    parent = Individual(code=parent_code, tier=TIER_FACTORY)
    engine.tier2 = [parent]

    clones = engine._reproduce_factory(llm_fn=lambda _prompt: parent_code)

    assert len(clones) == 3
    assert all(clone.parent_ids == [parent.id] for clone in clones)
    assert all(clone.tier == TIER_FACTORY for clone in clones)
    assert all(clone.record_lineage is False for clone in clones)


def test_elite_domination_demotes_weakest_elite_to_factory():
    slow_code = "def f(x):\n    return x + 1\n"
    fast_code = "def f(x):\n    return x + 1\n"

    slow = Individual(
        code=slow_code,
        score=1.0,
        fitness=FitnessVector(
            correctness=1.0,
            latency_p50=0.20,
            latency_p99=0.20,
            throughput=10.0,
            memory_peak_mb=10.0,
            parsimony=0.5,
        ),
        tier=TIER_ELITE,
    )
    fast = Individual(
        code=fast_code,
        score=2.0,
        fitness=FitnessVector(
            correctness=1.0,
            latency_p50=0.01,
            latency_p99=0.01,
            throughput=100.0,
            memory_peak_mb=1.0,
            parsimony=0.8,
        ),
        tier=TIER_FACTORY,
    )

    engine = _engine(lambda_clones=0, tier3_size=1)
    engine.tier2 = [fast]
    engine.tier3 = [slow]
    evaluator = _MockEvaluator(functional_codes={slow_code, fast_code})

    engine.step(llm_fn=lambda _prompt: fast_code, evaluator=evaluator, generation=0)

    assert any(ind.id == fast.id for ind in engine.tier3)
    assert any(ind.id == slow.id for ind in engine.tier2)


def test_hfc_deduplicates_demoted_elite_duplicate_in_factory():
    existing_factory_code = "def f(x):\n    return x + 1\n"
    existing_elite_code = "def f(x):\n    return x + 2\n"

    challenger_code = "def f(x):\n    return x + 3\n"
    existing_factory = Individual(
        code=existing_factory_code,
        score=2.0,
        fitness=FitnessVector(
            correctness=1.0,
            latency_p50=0.01,
            latency_p99=0.01,
            throughput=80.0,
            memory_peak_mb=1.0,
            parsimony=0.8,
        ),
        id="same-id",
        tier=TIER_FACTORY,
    )
    existing_elite = Individual(
        code=existing_elite_code,
        score=1.0,
        fitness=FitnessVector(
            correctness=1.0,
            latency_p50=0.02,
            latency_p99=0.02,
            throughput=50.0,
            memory_peak_mb=1.0,
            parsimony=0.8,
        ),
        id="same-id",
        tier=TIER_ELITE,
    )
    challenger = Individual(
        code=challenger_code,
        score=3.0,
        fitness=FitnessVector(
            correctness=1.0,
            latency_p50=0.01,
            latency_p99=0.01,
            throughput=120.0,
            memory_peak_mb=1.0,
            parsimony=0.8,
        ),
        id="challenger-id",
        tier=TIER_FACTORY,
    )

    engine = _engine(lambda_clones=0, tier3_size=1)
    engine.tier2 = [existing_factory, challenger]
    engine.tier3 = [existing_elite]
    class MappingEvaluator:
        def __init__(self):
            self.fitness = {
                existing_factory_code: existing_factory.fitness,
                existing_elite_code: existing_elite.fitness,
                challenger_code: challenger.fitness,
            }

        def evaluate_batch(self, codes):
            results = []
            for code in codes:
                fitness = self.fitness[code]
                results.append(
                    EvalResult(
                        fitness=fitness,
                        passed=True,
                        metrics=fitness.to_dict(),
                    )
                )
            return results

    engine = _engine(lambda_clones=0, tier3_size=1)
    engine.tier2 = [existing_factory, challenger]
    engine.tier3 = [existing_elite]

    snapshot = engine.step(
        llm_fn=lambda _prompt: challenger_code,
        evaluator=MappingEvaluator(),
        generation=0,
    )

    assert snapshot.demoted == 1
    assert len(engine.tier2) == 1
    assert len({ind.id for ind in engine.tier2}) == 1
    assert engine.tier2[0].id == "same-id"


def test_dedupe_by_id_keeps_highest_score():
    low = Individual(code="low", score=1.0, id="same-id")
    high = Individual(code="high", score=5.0, id="same-id")

    assert HFCLeagueEngine._dedupe_by_id([low, high]) == [high]


def test_elite_domination_does_not_demote_newly_promoted_candidate():
    slow_code = "def f(x):\n    return x + 1\n"
    medium_code = "def f(x):\n    return x * 2\n"
    challenger_code = "def f(x):\n    return x + 3\n"

    slow = Individual(
        code=slow_code,
        score=1.0,
        fitness=FitnessVector(
            correctness=1.0,
            latency_p50=0.20,
            latency_p99=0.20,
            throughput=10.0,
            memory_peak_mb=10.0,
            parsimony=0.5,
        ),
        tier=TIER_ELITE,
    )
    medium = Individual(
        code=medium_code,
        score=100.0,
        fitness=FitnessVector(
            correctness=1.0,
            latency_p50=0.05,
            latency_p99=0.05,
            throughput=50.0,
            memory_peak_mb=2.0,
            parsimony=0.7,
        ),
        tier=TIER_ELITE,
    )
    challenger = Individual(
        code=challenger_code,
        score=50.0,
        fitness=FitnessVector(
            correctness=1.0,
            latency_p50=0.04,
            latency_p99=0.04,
            throughput=60.0,
            memory_peak_mb=1.0,
            parsimony=0.6,
        ),
        tier=TIER_FACTORY,
    )

    class MappingEvaluator:
        def __init__(self):
            self.fitness = {
                slow_code: slow.fitness,
                medium_code: medium.fitness,
                challenger_code: challenger.fitness,
            }

        def evaluate_batch(self, codes):
            results = []
            for code in codes:
                fitness = self.fitness[code]
                results.append(
                    EvalResult(
                        fitness=fitness,
                        passed=True,
                        metrics=fitness.to_dict(),
                    )
                )
            return results

    engine = _engine(lambda_clones=0, tier3_size=2)
    engine.tier2 = [challenger]
    engine.tier3 = [slow, medium]

    engine.step(
        llm_fn=lambda _prompt: challenger_code,
        evaluator=MappingEvaluator(),
        generation=0,
    )

    assert any(ind.id == challenger.id for ind in engine.tier3)
    assert all(ind.id != challenger.id for ind in engine.tier2)
    assert any(ind.id == slow.id for ind in engine.tier2)
    assert any(ind.id == medium.id for ind in engine.tier3)


def test_micro_mutators_keep_syntax_valid():
    code = "def f(n):\n    for _ in range(1):\n        return sum([i for i in range(n)])\n"
    engine = _engine(lambda_clones=6, tier3_size=1)

    for mutator in engine._micro_mutators:
        mutated = mutator.apply(code, llm_fn=None)
        ast.parse(mutated)


def test_top_down_distillation_extracts_concept_from_elite():
    elite_code = "def f(items):\n    seen = {}\n    return [seen.setdefault(x, x) for x in items]\n"
    engine = _engine(tier3_size=1)
    engine.config.top_down_distillation = True
    engine.tier3 = [Individual(code=elite_code, tier=TIER_ELITE, score=10.0)]

    concept = engine._maybe_distill(
        llm_fn=lambda _prompt: "Use a hashmap to avoid repeated scans.",
        generation=0,
        task="deduplicate efficiently",
    )

    assert "hashmap" in concept.lower()
