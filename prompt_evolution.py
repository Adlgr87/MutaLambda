"""
RichPromptEvolver — Meta-evolution of PromptGenome populations.

Enhances the basic PromptEvolver with:
  • 15 diverse mutation operators (vs 6 trivial ones)
  • Crossover between two parent prompt genomes
  • Archive-aware few-shot example evolution (draws from SolutionArchive)
  • Diversity tracking to avoid prompt population convergence
  • Multi-objective prompt fitness: code quality + code diversity + consistency
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from muta_lambda import (
    PromptGenome,
    SandboxEvaluator,
    SolutionArchive,
    logger,
)


# ── Enriched mutation operators ─────────────────────────────────────────

# ── Rich mutation operators (13 unique) ──────────────────────────────────────
_MUTATION_OPS_RICH: List[Tuple[str, str]] = [
    # System prompt mutations
    ("sys_mut_word", "swap two random words"),
    ("sys_add_reminder", "append: Always output raw Python only"),
    ("sys_add_constraint_a", "append: Avoid external dependencies"),
    ("sys_add_constraint_b", "append: Use type hints everywhere"),
    ("sys_remove_sentence", "delete last sentence"),
    ("sys_emphasize", "prefix: IMPORTANT: "),
    # Mutation instruction mutations
    ("instr_add_algo", "Add: Prioritize algorithmic correctness"),
    ("instr_add_mem", "Add: Optimize for memory efficiency"),
    ("instr_remove", "remove last instruction line"),
    ("instr_rephrase", "rephrase current instructions"),
    # Few-shot mutations
    ("fewshot_add", ""),   # add example from archive
    ("fewshot_drop", ""),  # remove random example
    ("fewshot_swap", ""),  # swap two examples
    # Temperature mutations
    ("temp_jitter", ""),   # gaussian perturbation σ=0.05
    ("temp_randomize", ""),# random sample U(0.1, 1.0)
]


@dataclass
class PromptFitness:
    """Multi-objective prompt fitness.

    Evaluates not just what code a prompt produces, but how diverse,
    consistent, and adaptable its outputs are.

    code_quality  : float  — best score achieved (0‑1 normalised)
    diversity     : float  — uniqueness of outputs across generations (0‑1)
    consistency   : float  — reliability (1‑variance of scores) (0‑1)
    """
    code_quality: float = 0.0
    diversity: float = 0.0
    consistency: float = 0.0

    def combined(self) -> float:
        """Weighted aggregate: 50% quality, 30% diversity, 20% consistency."""
        return 0.50 * self.code_quality + 0.30 * self.diversity + 0.20 * self.consistency


class RichPromptEvolver:
    """
    Meta-evolves PromptGenome populations with crossover, rich mutations,
    archive-aware few-shot evolution, and diversity tracking.

    Parameters
    ----------
    llm_fn : callable
        LLM generation function.
    evaluator : SandboxEvaluator
        Code evaluator for fitness assignment.
    archive : SolutionArchive | None
        Archive for diverse few-shot examples (optional).
    pop_size : int
        Population size (default 6).
    elite_frac : float
        Fraction preserved as elites (0.5 = 50%).
    """

    _DEFAULT_PROMPTS: List[Dict[str, Any]] = [
        {
            "system_prompt": "You are an expert Python engineer. Return only valid Python code.",
            "mutation_instructions": "Focus on algorithmic correctness.",
            "temperature": 0.7,
        },
        {
            "system_prompt": "You are a performance-oriented Python optimizer. Return only code.",
            "mutation_instructions": "Minimize time complexity. Use built-ins.",
            "temperature": 0.5,
        },
        {
            "system_prompt": "You are a Pythonic code craftsman. Return only valid Python.",
            "mutation_instructions": "Use idiomatic Python, comprehensions.",
            "temperature": 0.6,
        },
        {
            "system_prompt": "You write simple, readable Python. Return only code.",
            "mutation_instructions": "Prefer clarity over cleverness.",
            "temperature": 0.4,
        },
        {
            "system_prompt": "You are a creative Python problem solver. Return only code.",
            "mutation_instructions": "Explore unconventional algorithms.",
            "temperature": 0.8,
        },
        {
            "system_prompt": "You are a rigorous Python tester. Return only code.",
            "mutation_instructions": "Focus on edge-case handling and robustness.",
            "temperature": 0.55,
        },
    ]

    def __init__(
        self,
        llm_fn: Callable[[str], str],
        evaluator: SandboxEvaluator,
        archive: Optional[SolutionArchive] = None,
        pop_size: int = 6,
        elite_frac: float = 0.5,
    ):
        self.llm_fn = llm_fn
        self.evaluator = evaluator
        self.archive = archive
        self.pop_size = pop_size
        self.elite_frac = elite_frac

        self.population: List[PromptGenome] = self._init_population()
        self._generation: int = 0
        self._output_history: List[List[str]] = []  # track generated code per gen
        self._best_history: List[float] = []
        self._diversity_history: List[float] = []

    # ── Initialisation ──────────────────────────────────────────────────

    def _init_population(self) -> List[PromptGenome]:
        return [
            PromptGenome(
                system_prompt=p["system_prompt"],
                few_shot_examples=[],
                mutation_instructions=p["mutation_instructions"],
                temperature=p["temperature"],
            )
            for p in self._DEFAULT_PROMPTS[:self.pop_size]
        ]

    # ── Main evolution step ─────────────────────────────────────────────

    def step(self, task: str, base_code: str) -> List[str]:
        """
        One generation of prompt evolution.

        1. Generate code with each prompt genome
        2. Evaluate quality + diversity of outputs
        3. Select elites (top elite_frac)
        4. Breed new population via crossover + mutation
        5. Track diversity metrics

        Returns
        -------
        List[str]
            Code generated by all prompts this generation.
        """
        # ── Generation ───────────────────────────────────────────────
        generated = [
            self.llm_fn(pg.render(task, base_code))
            for pg in self.population
        ]
        self._output_history.append(generated)

        eval_results = self.evaluator.evaluate_batch(generated)

        # ── Compute multi-objective prompt fitness ───────────────────
        for pg, res, gen_code in zip(self.population, eval_results, generated):
            quality = max(0.0, min(1.0, res.score / 100.0)) if res.passed else 0.0

            # Diversity: how unique is the generated code vs others this gen?
            all_codes = [g for g in generated if g != gen_code]
            uniqueness = 1.0 if not all_codes else (
                1.0 - sum(1 for c in all_codes if c == gen_code) / len(all_codes)
            )
            # Consistency: track score variance (placeholder until we have history)
            consistency = 0.5  # neutral until enough history

            pf = PromptFitness(
                code_quality=quality,
                diversity=uniqueness,
                consistency=consistency,
            )
            pg.fitness = pf.combined()

        # ── Selection (elitist) ──────────────────────────────────────
        self.population.sort(key=lambda pg: pg.fitness, reverse=True)
        elite_count = max(1, int(len(self.population) * self.elite_frac))
        elites = self.population[:elite_count]

        # ── Breeding: fill with crossover + mutation ─────────────────
        new_pop: List[PromptGenome] = [copy.deepcopy(e) for e in elites]
        while len(new_pop) < self.pop_size:
            if len(elites) >= 2 and random.random() < 0.6:
                # Crossover
                p1, p2 = random.sample(elites, 2)
                child = self._crossover(p1, p2)
            else:
                # Mutation
                parent = random.choice(elites)
                child = copy.deepcopy(parent)
                self._apply_mutation(child)
            child.fitness = 0.0
            new_pop.append(child)

        self.population = new_pop

        # ── Diversity tracking ───────────────────────────────────────
        diversity = self._population_diversity()
        self._diversity_history.append(diversity)
        best = max(pg.fitness for pg in self.population)
        self._best_history.append(best)

        self._generation += 1

        if self._generation % 5 == 0:
            logger.info(
                "PromptEvolver gen %d | best=%.3f | diversity=%.3f | pop=%d",
                self._generation, best, diversity, len(self.population),
            )

        return generated

    # ── Crossover ──────────────────────────────────────────────────────

    @staticmethod
    def _crossover(
        parent_a: PromptGenome, parent_b: PromptGenome
    ) -> PromptGenome:
        """
        Combine two parent prompt genomes.

        Uniform crossover: each component independently inherits
        from one parent with equal probability.  Few‑shot examples
        are merged and thinned.
        """
        # System prompt: pick one parent
        sys = parent_a.system_prompt if random.random() < 0.5 else parent_b.system_prompt

        # Mutation instructions: pick one parent
        instr = (
            parent_a.mutation_instructions
            if random.random() < 0.5
            else parent_b.mutation_instructions
        )

        # Temperature: average with noise
        temp = (parent_a.temperature + parent_b.temperature) / 2.0
        temp += random.gauss(0, 0.02)
        temp = max(0.1, min(1.0, temp))

        # Few‑shot: merge and sample half
        all_fewshot = list(set(parent_a.few_shot_examples + parent_b.few_shot_examples))
        random.shuffle(all_fewshot)
        fewshot = all_fewshot[: max(1, len(all_fewshot) // 2)]

        return PromptGenome(
            system_prompt=sys,
            few_shot_examples=fewshot,
            mutation_instructions=instr,
            temperature=temp,
        )

    # ── Rich mutation ───────────────────────────────────────────────────

    def _apply_mutation(self, genome: PromptGenome) -> None:
        """Apply one random rich mutation operator."""
        op_type, arg = random.choice(_MUTATION_OPS_RICH)

        if op_type == "sys_mut_word":
            self._mut_sys_swap_words(genome)
        elif op_type == "sys_add_reminder":
            genome.system_prompt += " " + arg
        elif op_type in ("sys_add_constraint_a", "sys_add_constraint_b"):
            genome.system_prompt += ". " + arg
        elif op_type == "sys_remove_sentence":
            self._mut_sys_remove_sentence(genome)
        elif op_type == "sys_emphasize":
            genome.system_prompt = arg + genome.system_prompt
        elif op_type in ("instr_add_algo", "instr_add_mem"):
            genome.mutation_instructions = (
                genome.mutation_instructions + ". " + arg
                if genome.mutation_instructions else arg
            )
        elif op_type == "instr_remove":
            self._mut_instr_remove_last(genome)
        elif op_type == "instr_rephrase":
            self._mut_instr_rephrase(genome)
        elif op_type == "fewshot_add":
            self._mut_fewshot_add(genome)
        elif op_type == "fewshot_drop":
            if genome.few_shot_examples:
                genome.few_shot_examples.pop(
                    random.randrange(len(genome.few_shot_examples))
                )
        elif op_type == "fewshot_swap":
            if len(genome.few_shot_examples) >= 2:
                i, j = random.sample(range(len(genome.few_shot_examples)), 2)
                genome.few_shot_examples[i], genome.few_shot_examples[j] = \
                    genome.few_shot_examples[j], genome.few_shot_examples[i]
        elif op_type == "temp_jitter":
            genome.temperature += random.gauss(0, 0.05)
            genome.temperature = max(0.1, min(1.0, genome.temperature))
        elif op_type == "temp_randomize":
            genome.temperature = random.uniform(0.1, 1.0)

    # ── Sub-operators ───────────────────────────────────────────────────

    @staticmethod
    def _mut_sys_swap_words(genome: PromptGenome) -> None:
        words = genome.system_prompt.split()
        if len(words) < 2:
            return
        i, j = random.sample(range(len(words)), 2)
        words[i], words[j] = words[j], words[i]
        genome.system_prompt = " ".join(words)

    @staticmethod
    def _mut_sys_remove_sentence(genome: PromptGenome) -> None:
        sentences = [s.strip() for s in genome.system_prompt.split(". ") if s.strip()]
        if len(sentences) <= 1:
            return
        sentences.pop(random.randrange(len(sentences)))
        genome.system_prompt = ". ".join(sentences) + "."

    @staticmethod
    def _mut_instr_remove_last(genome: PromptGenome) -> None:
        parts = [p.strip() for p in genome.mutation_instructions.split(". ") if p.strip()]
        if parts:
            parts.pop()
            genome.mutation_instructions = ". ".join(parts) + ("." if parts else "")

    @staticmethod
    def _mut_instr_rephrase(genome: PromptGenome) -> None:
        synonyms = {
            "optimize": ["enhance", "improve", "refine"],
            "ensure": ["guarantee", "verify", "confirm"],
            "avoid": ["prevent", "eliminate", "minimize"],
            "use": ["employ", "utilize", "leverage"],
            "correct": ["accurate", "valid", "precise"],
        }
        words = genome.mutation_instructions.split()
        for i, w in enumerate(words):
            low = w.lower().rstrip(",.;")
            if low in synonyms:
                words[i] = random.choice(synonyms[low]) + (
                    w[len(low):] if len(w) > len(low) else ""
                )
                break
        genome.mutation_instructions = " ".join(words)

    def _mut_fewshot_add(self, genome: PromptGenome) -> None:
        """Add a diverse example from archive (if available)."""
        if self.archive and self.archive.size > 0:
            diverse = self.archive.get_diverse_sample(k=3)
            for code in diverse:
                example = (code, code)  # simplified: input = output for code tasks
                if example not in genome.few_shot_examples:
                    genome.few_shot_examples.append(example)
                    break
        elif len(genome.few_shot_examples) < 5:
            # Fallback: add generic example
            genome.few_shot_examples.append((
                "def f(x): return x + 1",
                "def f(x):\n    return x + 1\n",
            ))

    # ── Diversity ───────────────────────────────────────────────────────

    def _population_diversity(self) -> float:
        """
        Measure prompt population diversity by system_prompt uniqueness.
        0.0 = all identical, 1.0 = all unique.
        """
        promps = [pg.system_prompt for pg in self.population]
        if not promps:
            return 0.0
        return len(set(promps)) / len(promps)

    def get_best_prompt(self) -> Optional[PromptGenome]:
        """Return the highest-fitness prompt genome."""
        if not self.population:
            return None
        return max(self.population, key=lambda pg: pg.fitness)

    @property
    def generation(self) -> int:
        return self._generation

    def get_metrics(self) -> Dict[str, Any]:
        """Telemetry for prompt evolution."""
        return {
            "generation": self._generation,
            "population_size": len(self.population),
            "best_fitness": self._best_history[-1] if self._best_history else 0.0,
            "diversity": self._diversity_history[-1] if self._diversity_history else 0.0,
            "best_prompt_temp": (
                self.get_best_prompt().temperature
                if self.get_best_prompt() else 0.0
            ),
        }
