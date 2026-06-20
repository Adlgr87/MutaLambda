"""Basic prompt evolution utilities."""

from __future__ import annotations

import copy
import random
from typing import Callable, Dict, List, Optional, Tuple

from models import PromptGenome
from sandbox import SandboxEvaluator


class PromptEvolver:
    """Evoluciona una población de PromptGenomes usando fitness = score."""

    _DEFAULT_PROMPTS: List[Dict[str, object]] = [
        {
            "system_prompt": "You are an expert Python engineer. Return only valid Python code.",
            "mutation_instructions": "Focus on algorithmic correctness.",
            "temperature": 0.7,
        },
        {
            "system_prompt": "You are a performance-oriented Python optimizer. Return only code.",
            "mutation_instructions": "Minimize time complexity.",
            "temperature": 0.5,
        },
        {
            "system_prompt": "You are a Pythonic code craftsman. Return only valid Python.",
            "mutation_instructions": "Use idiomatic Python, comprehensions, and built-in functions.",
            "temperature": 0.6,
        },
    ]

    _MUTATION_OPS: List[Tuple[str, str]] = [
        ("system_prompt_suffix", " Be more concise."),
        ("system_prompt_suffix", " Prioritize readability."),
        ("system_prompt_suffix", " Add type hints."),
        ("system_prompt_suffix", " Optimize for edge cases."),
        ("temperature_bump", ""),
        ("temperature_drop", ""),
    ]

    def __init__(self, llm_fn: Callable[[str], str], evaluator: SandboxEvaluator):
        self.llm_fn = llm_fn
        self.evaluator = evaluator
        self.population: List[PromptGenome] = self._init_population()
        self._generation: int = 0

    def _init_population(self) -> List[PromptGenome]:
        return [
            PromptGenome(
                system_prompt=str(p["system_prompt"]),
                few_shot_examples=[],
                mutation_instructions=str(p["mutation_instructions"]),
                temperature=float(p["temperature"]),
            )
            for p in self._DEFAULT_PROMPTS
        ]

    def step(self, task: str, base_code: str) -> List[str]:
        """Un paso de evolución de prompts."""
        generated = [
            self.llm_fn(pg.render(task, base_code)) for pg in self.population
        ]

        eval_results = self.evaluator.evaluate_batch(generated)

        for pg, res in zip(self.population, eval_results):
            pg.fitness = max(pg.fitness, res.score)

        self.population.sort(key=lambda pg: pg.fitness, reverse=True)
        half = max(1, len(self.population) // 2)
        elites = self.population[:half]

        new_pop: List[PromptGenome] = list(elites)
        while len(new_pop) < len(self._DEFAULT_PROMPTS):
            parent = copy.deepcopy(random.choice(elites))
            self._apply_mutation(parent)
            parent.fitness = 0.0
            new_pop.append(parent)

        self.population = new_pop
        self._generation += 1
        return generated

    def _apply_mutation(self, genome: PromptGenome) -> None:
        """Aplica una mutación aleatoria a un genoma de prompt."""
        op_type, value = random.choice(self._MUTATION_OPS)
        if op_type == "system_prompt_suffix":
            genome.system_prompt += value
        elif op_type == "temperature_bump":
            genome.temperature = min(1.0, genome.temperature + 0.1)
        elif op_type == "temperature_drop":
            genome.temperature = max(0.1, genome.temperature - 0.1)

    def get_best_prompt(self) -> Optional[PromptGenome]:
        """Retorna el mejor prompt genome actual."""
        if not self.population:
            return None
        return max(self.population, key=lambda pg: pg.fitness)
