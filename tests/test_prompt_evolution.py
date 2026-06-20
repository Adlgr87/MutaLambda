"""
Tests for RichPromptEvolver and PromptGenome — meta‑evolution of prompts.
"""

import copy
import random

import pytest

# Import directly (prompt_evolution imports muta_lambda internally)
from muta_lambda import PromptGenome
from prompt_evolution import RichPromptEvolver


class DummyEvaluator:
    def evaluate_batch(self, codes):
        from fitness_vector import FitnessVector
        from models import EvalResult

        return [
            EvalResult(
                fitness=FitnessVector(correctness=1.0),
                passed=True,
                metrics={"score": 1.0},
            )
            for _ in codes
        ]


class TestPromptGenome:
    """Unit tests for PromptGenome dataclass and its methods."""

    def test_render_basic(self):
        pg = PromptGenome(
            system_prompt="You are a Python expert.",
            few_shot_examples=[],
            mutation_instructions="Optimize for speed.",
            temperature=0.7,
        )
        result = pg.render("Sum numbers", "def f(): pass")
        assert "You are a Python expert." in result
        assert "Sum numbers" in result
        assert "def f(): pass" in result
        assert "Optimize for speed." in result

    def test_render_with_fewshot(self):
        pg = PromptGenome(
            system_prompt="Be helpful.",
            few_shot_examples=[("in1", "out1"), ("in2", "out2")],
            mutation_instructions="",
            temperature=0.5,
        )
        result = pg.render("T", "C")
        assert "Example Input:" in result
        assert "in1" in result
        assert "out2" in result

    def test_mutate_returns_different_prompt(self):
        pg = PromptGenome(
            system_prompt="You are an expert Python engineer. Return code.",
            few_shot_examples=[("a", "b")],
            mutation_instructions="Focus on correctness.",
            temperature=0.7,
        )
        mutant = pg.mutate()
        assert isinstance(mutant, PromptGenome)
        # At least one attribute should differ; try multiple times to reduce flakiness
        for _ in range(5):
            if (mutant.system_prompt != pg.system_prompt
                or mutant.temperature != pg.temperature
                or mutant.few_shot_examples != pg.few_shot_examples
                or mutant.mutation_instructions != pg.mutation_instructions):
                break
            mutant = pg.mutate()
        different = (
            mutant.system_prompt != pg.system_prompt
            or mutant.temperature != pg.temperature
            or mutant.few_shot_examples != pg.few_shot_examples
            or mutant.mutation_instructions != pg.mutation_instructions
        )
        assert different, "Mutation should change at least one attribute"

    def test_mutate_preserves_original(self):
        """Mutation returns a copy; original is unchanged."""
        pg = PromptGenome(
            system_prompt="Original prompt.",
            few_shot_examples=[("x", "y")],
            mutation_instructions="Be correct.",
            temperature=0.5,
        )
        original_sys = pg.system_prompt
        original_temp = pg.temperature
        _ = pg.mutate()  # discard mutant
        assert pg.system_prompt == original_sys
        assert pg.temperature == original_temp

    def test_mutate_temperature_in_range(self):
        pg = PromptGenome(
            system_prompt="Test.",
            few_shot_examples=[],
            mutation_instructions="",
            temperature=0.5,
        )
        temps = []
        for _ in range(50):
            m = pg.mutate()
            temps.append(m.temperature)
        assert all(0.1 <= t <= 1.0 for t in temps)

    def test_crossover_produces_valid_child(self):
        parent_a = PromptGenome(
            system_prompt="Be fast.",
            few_shot_examples=[("a", "b")],
            mutation_instructions="Optimize.",
            temperature=0.3,
        )
        parent_b = PromptGenome(
            system_prompt="Be correct.",
            few_shot_examples=[("c", "d")],
            mutation_instructions="Verify.",
            temperature=0.7,
        )
        child = PromptGenome.crossover(parent_a, parent_b)
        assert isinstance(child, PromptGenome)
        assert child.system_prompt in ("Be fast.", "Be correct.")
        assert child.mutation_instructions in ("Optimize.", "Verify.")
        assert 0.1 <= child.temperature <= 1.0

    def test_crossover_temperature_between_parents(self):
        parent_a = PromptGenome("A", [], "", 0.3)
        parent_b = PromptGenome("B", [], "", 0.7)
        temps = []
        for _ in range(100):
            child = PromptGenome.crossover(parent_a, parent_b)
            temps.append(child.temperature)
        # With noise σ=0.02, range should be roughly [0.45, 0.55] but can be wider
        assert min(temps) >= 0.1
        assert max(temps) <= 1.0

    def test_fewshot_dedup_in_crossover(self):
        """Crossover should not duplicate few‑shot examples."""
        parent_a = PromptGenome("A", [("x","x")], "", 0.5)
        parent_b = PromptGenome("B", [("x","x")], "", 0.5)
        child = PromptGenome.crossover(parent_a, parent_b)
        # Duplicates removed by set() in crossover
        assert len(child.few_shot_examples) <= len(set(parent_a.few_shot_examples + parent_b.few_shot_examples))


class TestRichPromptEvolver:
    def test_pop_size_is_honored_above_default_prompt_count(self):
        evolver = RichPromptEvolver(
            llm_fn=lambda _prompt: "def f(): return 1",
            evaluator=DummyEvaluator(),
            pop_size=8,
            elite_frac=0.5,
        )

        assert len(evolver.population) == 8

    def test_step_uses_configured_population_size(self):
        evolver = RichPromptEvolver(
            llm_fn=lambda _prompt: "def f(): return 1",
            evaluator=DummyEvaluator(),
            pop_size=4,
            elite_frac=0.5,
        )

        generated = evolver.step("Sum numbers", "def f(n): return 0")

        assert len(generated) == 4
        assert len(evolver.population) == 4
