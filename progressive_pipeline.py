"""
Progressive Pipeline — MutaLambda 2.0 Workflow.

Implements the progressive discovery pipeline:
- FASE 0: Discovery & Hotspots
- FASE 1: Test Synthesis
- FASE 2: Fast Mode (default)
- FASE 3: Deep Evolution (fallback --deep)
- FASE 4: Patch & Report

Unlike the previous skeleton, the fast and deep phases now plug into the
real machinery:

* ``_fast_phase`` evaluates every LLM variant with the same
  :class:`~sandbox.SandboxEvaluator` used by the evolution engine (real
  correctness, latency and memory — no placeholder ``FitnessVector``).
* ``_deep_phase`` instantiates a real :class:`~muta_lambda.MutaLambdaAgent`
  (multi-island NSGA-II evolution) seeded with the input code and returns
  the evolved elite instead of a ``deep_mode_placeholder`` dict.

When no declarative test cases are supplied, the pipeline synthesises
*regression* cases from the baseline function signatures: it runs the
original code on a handful of sample inputs and captures its outputs as the
expected values. This gives the optimizer a real correctness target even for
scripts without a hand-written test suite (differential, not magical).
"""

from __future__ import annotations

import ast
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Any

from fitness_vector import FitnessVector
from workflow_protocol import ComplexityGate

logger = logging.getLogger("MutaLambda")


# ── Regression-test synthesis ──────────────────────────────────────────────

def _json_safe(value: Any) -> Any:
    """Convert a value into something JSON-serializable for test cases."""
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, (np.floating, np.integer)):
            return value.item()
        if isinstance(value, (list, tuple)):
            return [_json_safe(v) for v in value]
        if isinstance(value, dict):
            return {k: _json_safe(v) for k, v in value.items()}
    except ImportError:
        pass
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def _comparison_for(value: Any) -> str:
    """Choose a comparator for a captured expected value."""
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return "array_allclose"
        if isinstance(value, np.floating):
            return "float_close"
    except ImportError:
        pass
    if isinstance(value, float):
        return "float_close"
    if isinstance(value, (list, tuple)):
        # Containers of floats still compare best with allclose semantics;
        # keep it simple and rely on exact equality for plain lists.
        return "equal"
    return "equal"


def _values_for_arg(arg: ast.arg) -> List[Any]:
    """Generate a few sample values for a function argument."""
    hint = ""
    if arg.annotation is not None:
        try:
            hint = ast.unparse(arg.annotation).lower()
        except Exception:
            hint = ""

    # Heuristic on the parameter name for loop-bound style arguments.
    if arg.arg in ("n", "size", "length", "count", "num", "iters", "iterations", "steps"):
        return [0, 1, 5, 10]

    if "int" in hint:
        return [0, 1, 5, 10]
    if "float" in hint:
        return [0.0, 1.0, 2.5]
    if "bool" in hint:
        return [False, True]
    if "str" in hint:
        return ["", "abc"]
    if "list" in hint:
        return [[], [1, 2, 3]]
    if "ndarray" in hint or "array" in hint:
        try:
            import numpy as np

            return [np.array([1.0, 2.0, 3.0]), np.zeros(3)]
        except ImportError:
            return [[1.0, 2.0, 3.0], [0.0, 0.0, 0.0]]
    return [0, 1, 2]


def _sample_inputs(func_node: ast.FunctionDef) -> List[tuple]:
    """Build a small set of sample argument tuples for a function."""
    args = func_node.args.args
    if not args:
        return [()]

    per_arg = [_values_for_arg(a) for a in args]
    combos: List[tuple] = []
    if per_arg:
        combos.append(tuple(vals[0] for vals in per_arg))
        combos.append(tuple(vals[-1] for vals in per_arg))
        combos.append(tuple(vals[len(vals) // 2] for vals in per_arg))

    seen = set()
    out: List[tuple] = []
    for combo in combos:
        key = tuple(repr(v) for v in combo)
        if key not in seen:
            seen.add(key)
            out.append(combo)
    return out


def synthesize_regression_tests(code: str, max_cases_per_func: int = 3) -> List[Dict]:
    """Synthesise declarative test cases from the baseline function outputs.

    Runs the *original* code on sample inputs and records its outputs as the
    expected values. Optimised variants must then reproduce this behaviour,
    which gives a real correctness signal without a hand-written suite.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    funcs = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    ]
    if not funcs:
        return []

    namespace: Dict[str, Any] = {"__name__": "__mutalambda_synth__"}
    try:
        exec(compile(code, "<mutalambda_synth>", "exec"), namespace, namespace)  # noqa: S102
    except Exception as exc:
        logger.warning("Regression-test synthesis: baseline failed to load: %s", exc)
        return []

    cases: List[Dict] = []
    for fn in funcs:
        func = namespace.get(fn.name)
        if not callable(func):
            continue
        for args in _sample_inputs(fn)[:max_cases_per_func]:
            try:
                expected = func(*args)
            except Exception:
                # Skip inputs the baseline itself rejects.
                continue
            cases.append({
                "function": fn.name,
                "args": [_json_safe(a) for a in args],
                "expected": _json_safe(expected),
                "comparison": _comparison_for(expected),
            })
    return cases


# ── Pipeline result ────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """Result of the progressive pipeline."""
    success: bool
    phase_reached: str
    original_code: str
    optimized_code: Optional[str]
    fitness: Optional[FitnessVector]
    report: Dict[str, Any] = field(default_factory=dict)
    duration_sec: float = 0.0
    variants_evaluated: int = 0
    improvement: float = 0.0

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = ["=" * 60]
        lines.append("MUTALAMBDA 2.0 — OPTIMIZATION REPORT")
        lines.append("=" * 60)
        lines.append(f"Success: {self.success}")
        lines.append(f"Phase reached: {self.phase_reached}")
        lines.append(f"Duration: {self.duration_sec:.2f}s")

        if self.fitness:
            lines.append("")
            lines.append("Fitness:")
            lines.append(f"  Correctness: {self.fitness.correctness:.1%}")
            lines.append(f"  Latency P50: {self.fitness.latency_p50 * 1000:.2f}ms")
            lines.append(f"  Memory Peak: {self.fitness.memory_peak_mb:.2f}MB")

        if self.report.get("hotspots"):
            lines.append("")
            lines.append(f"Hotspots found: {len(self.report['hotspots'])}")
            for hs in self.report["hotspots"][:3]:
                lines.append(f"  • {hs.get('name', '?')} [{hs.get('severity', '?')}]")

        if self.report.get("tests_generated"):
            lines.append("")
            lines.append(f"Tests generated: {self.report['tests_generated']}")

        if self.report.get("tests_synthesized"):
            lines.append(f"Regression tests synthesized: {self.report['tests_synthesized']}")

        if self.report.get("variants_evaluated"):
            lines.append(f"Variants evaluated: {self.report['variants_evaluated']}")

        lines.append("=" * 60)
        return "\n".join(lines)


# ── Pipeline ───────────────────────────────────────────────────────────────

class ProgressivePipeline:
    """Main pipeline for MutaLambda 2.0 optimization workflow."""

    def __init__(self,
                 llm_fn: Optional[Callable[[str], str]] = None,
                 test_cases: Optional[List[Dict]] = None,
                 timeout_sec: float = 5.0,
                 min_improvement: float = 0.15,
                 fast_variants: int = 5,
                 evolve_config: Any = None):
        self.llm_fn = llm_fn
        self.test_cases = list(test_cases or [])
        self.timeout_sec = timeout_sec
        self.min_improvement = min_improvement  # 15% improvement threshold
        self.fast_variants = fast_variants
        self.evolve_config = evolve_config
        self.complexity_gate = ComplexityGate()
        self._report: Dict[str, Any] = {}
        self._evaluator = None
        self._resolved_test_cases: List[Dict] = []

    # ── Public API ────────────────────────────────────────────────────────

    def run(self, code: str, mode: str = "auto") -> PipelineResult:
        """Run the progressive pipeline on input code."""
        start_time = time.perf_counter()
        self._report = {
            "hotspots": [],
            "tests_generated": 0,
            "tests_synthesized": 0,
            "variants_evaluated": 0,
            "phases_completed": [],
        }

        try:
            # FASE 0: Discovery & Hotspots
            logger.info("FASE 0: Discovery & Hotspots")
            hotspots = self._discovery_phase(code)
            self._report["hotspots"] = [hs.to_dict() for hs in hotspots]
            self._report["phases_completed"].append("discovery")

            # FASE 1: Test Synthesis
            logger.info("FASE 1: Test Synthesis")
            specs = self._test_synthesis_phase(code, hotspots)
            self._report["tests_generated"] = len(specs)
            self._report["phases_completed"].append("test_synthesis")

            # Resolve the *declarative* test cases used for real evaluation.
            # Falls back to synthesised regression tests when none were given.
            self._resolved_test_cases = self._resolve_test_cases(code)
            if not self._resolved_test_cases:
                logger.warning(
                    "No test cases available (none supplied and none synthesised). "
                    "Correctness cannot be verified — no variant will be promoted."
                )

            # Complexity Gate check
            gate_result = self.complexity_gate.evaluate(code)
            self._report["complexity_gate"] = gate_result

            if gate_result["recommendation"] == "skip":
                logger.info("Code has I/O calls — skipping optimization")
                return PipelineResult(
                    success=False,
                    phase_reached="complexity_gate",
                    original_code=code,
                    optimized_code=None,
                    fitness=None,
                    report=self._report,
                    duration_sec=time.perf_counter() - start_time,
                )

            # FASE 2: Fast Mode (default)
            if mode in ("auto", "fast"):
                logger.info("FASE 2: Fast Mode")
                result = self._fast_phase(code, specs)
                self._report["phases_completed"].append("fast_mode")
                self._report["variants_evaluated"] = result.get("variants_evaluated", 0)

                if result.get("success"):
                    result["report"] = self._report
                    result["duration_sec"] = time.perf_counter() - start_time
                    return PipelineResult(**result)

            # FASE 3: Deep Evolution (fallback)
            if mode in ("auto", "deep"):
                logger.info("FASE 3: Deep Evolution (--deep)")
                result = self._deep_phase(code, specs)
                self._report["phases_completed"].append("deep_evolution")

                if result.get("success"):
                    result["report"] = self._report
                    result["duration_sec"] = time.perf_counter() - start_time
                    return PipelineResult(**result)

            # No improvement found
            return PipelineResult(
                success=False,
                phase_reached="exhausted",
                original_code=code,
                optimized_code=None,
                fitness=None,
                report=self._report,
                duration_sec=time.perf_counter() - start_time,
            )
        finally:
            self._shutdown_evaluator()

    # ── FASE 0/1 helpers ──────────────────────────────────────────────────

    def _discovery_phase(self, code: str) -> list:
        """FASE 0: Discover hotspots in code."""
        try:
            from hotspot_profiler import HotspotProfiler
            profiler = HotspotProfiler(min_time_threshold=0.05)
            hotspots = profiler.extract_hotspots(code)

            if hotspots:
                logger.info(f"Found {len(hotspots)} hotspots")
                for hs in hotspots[:3]:
                    logger.info(f"  • {hs.name} [{hs.severity}]")
            else:
                logger.info("No significant hotspots found")

            return hotspots
        except ImportError:
            logger.warning("hotspot_profiler not available, skipping discovery")
            return []

    def _test_synthesis_phase(self, code: str, hotspots: list) -> list:
        """FASE 1: Synthesize Hypothesis property specs for hotspots."""
        try:
            from test_synthesizer import TestSynthesizer
            synthesizer = TestSynthesizer()
            specs = synthesizer.synthesize_tests(code)

            logger.info(f"Generated {len(specs)} test specifications")
            return specs
        except ImportError:
            logger.warning("test_synthesizer not available, using existing tests")
            return []

    # ── Evaluation helpers ────────────────────────────────────────────────

    def _resolve_test_cases(self, code: str) -> List[Dict]:
        """Return declarative test cases, synthesising from baseline if needed."""
        if self.test_cases:
            return self.test_cases

        cases = synthesize_regression_tests(code)
        self._report["tests_synthesized"] = len(cases)
        if cases:
            logger.info(
                "Synthesised %d regression test cases from baseline behaviour",
                len(cases),
            )
        return cases

    def _ensure_evaluator(self):
        """Lazily create a real :class:`SandboxEvaluator`."""
        if self._evaluator is None:
            from sandbox import SandboxEvaluator
            self._evaluator = SandboxEvaluator(
                test_cases=self._resolved_test_cases,
                timeout_sec=self.timeout_sec,
                allow_untested=True,
            )
        return self._evaluator

    def _shutdown_evaluator(self) -> None:
        if self._evaluator is not None:
            try:
                self._evaluator.shutdown()
            except Exception:
                pass
            self._evaluator = None

    def _evaluate(self, code: str) -> FitnessVector:
        """Evaluate one code string and return its FitnessVector."""
        evaluator = self._ensure_evaluator()
        return evaluator.evaluate_batch([code])[0].fitness

    # ── FASE 2: Fast Mode ─────────────────────────────────────────────────

    def _fast_phase(self, code: str, specs: list) -> dict:
        """FASE 2: Fast mode — generate and evaluate LLM variants."""
        variants_evaluated = 0

        if not self.llm_fn:
            logger.warning("No LLM function provided, skipping fast mode")
            return {"success": False, "reason": "no_llm"}

        baseline_fitness = self._evaluate(code)
        self._report["baseline_fitness"] = baseline_fitness.to_dict()
        if baseline_fitness.correctness < 1.0:
            logger.warning(
                "Baseline code does not pass its tests (correctness=%.2f). "
                "Variants will be judged against this same bar.",
                baseline_fitness.correctness,
            )

        prompt = self._build_fast_prompt(code, specs)
        try:
            variants = []
            for _ in range(self.fast_variants):
                variant = self.llm_fn(prompt)
                if variant and variant.strip() != code.strip():
                    variants.append(variant)

            variants_evaluated = len(variants)
            logger.info(f"Generated {len(variants)} unique variants")

            if not variants:
                return {"success": False, "reason": "no_variants",
                        "variants_evaluated": variants_evaluated}

            evaluator = self._ensure_evaluator()
            results = evaluator.evaluate_batch(variants)

            best_variant = None
            best_fitness = None
            for variant, result in zip(variants, results):
                fitness = result.fitness
                if fitness.correctness >= 1.0:
                    if best_fitness is None or fitness > best_fitness:
                        best_fitness = fitness
                        best_variant = variant

            if best_variant is not None and best_fitness is not None:
                improvement = self._calculate_improvement(baseline_fitness, best_fitness)
                if improvement >= self.min_improvement:
                    return {
                        "success": True,
                        "phase_reached": "fast_mode",
                        "original_code": code,
                        "optimized_code": best_variant,
                        "fitness": best_fitness,
                        "variants_evaluated": variants_evaluated,
                        "improvement": improvement,
                    }
                logger.info(
                    "Fast mode found a correct variant but improvement %.1f%% "
                    "was below threshold %.1f%%",
                    improvement * 100, self.min_improvement * 100,
                )

            return {"success": False, "reason": "no_improvement",
                    "variants_evaluated": variants_evaluated}

        except Exception as e:
            logger.error(f"Fast mode error: {e}")
            return {"success": False, "reason": f"error:{e}",
                    "variants_evaluated": variants_evaluated}

    # ── FASE 3: Deep Evolution ────────────────────────────────────────────

    def _default_deep_config(self):
        """Minimal evolution config for the deep phase."""
        from muta_lambda import EvolveConfig

        return EvolveConfig(
            num_islands=2,
            generations=5,
            population_size=4,
            top_k=2,
            archive_solutions=False,
            prompt_evolution=False,
            checkpoint_enabled=False,
            write_run_artifacts=False,
            workflow_enabled=False,
            convergent_boost_enabled=False,
            resurrection_enabled=False,
            early_stop_patience=3,
        )

    def _deep_phase(self, code: str, specs: list) -> dict:
        """FASE 3: Deep evolution with the real multi-island NSGA-II engine."""
        if not self.llm_fn:
            logger.warning("No LLM function provided, skipping deep evolution")
            return {"success": False, "reason": "no_llm"}

        try:
            from muta_lambda import MutaLambdaAgent
        except ImportError as exc:
            logger.error("Evolution engine unavailable: %s", exc)
            return {"success": False, "reason": f"engine_unavailable:{exc}"}

        config = self.evolve_config or self._default_deep_config()
        config.seed_codes = [code]

        logger.info(
            "Deep evolution: %d islands × %d generations × pop %d",
            config.num_islands, config.generations, config.population_size,
        )

        agent = MutaLambdaAgent(
            config=config,
            test_cases=self._resolved_test_cases,
            llm_fn=self.llm_fn,
            timeout_sec=self.timeout_sec,
        )
        try:
            best = agent.run(task="Optimize for correctness and speed")
        except RuntimeError as exc:
            logger.error("Deep evolution produced no valid individuals: %s", exc)
            return {"success": False, "reason": f"no_valid_individuals:{exc}"}
        finally:
            try:
                agent.shutdown()
            except Exception:
                pass

        if best is None or not getattr(best, "code", ""):
            return {"success": False, "reason": "no_best"}

        baseline_fitness = self._evaluate(code)
        optimized_fitness = self._evaluate(best.code)
        improvement = self._calculate_improvement(baseline_fitness, optimized_fitness)

        if optimized_fitness.correctness < 1.0:
            return {"success": False, "reason": "best_not_correct"}

        if improvement < self.min_improvement:
            logger.info(
                "Deep evolution produced a correct candidate but improvement "
                "%.1f%% was below threshold %.1f%%",
                improvement * 100, self.min_improvement * 100,
            )
            return {"success": False, "reason": "no_improvement",
                    "improvement": improvement}

        return {
            "success": True,
            "phase_reached": "deep_evolution",
            "original_code": code,
            "optimized_code": best.code,
            "fitness": optimized_fitness,
            "improvement": improvement,
        }

    # ── Prompt / improvement helpers ──────────────────────────────────────

    def _build_fast_prompt(self, code: str, specs: list) -> str:
        """Build prompt for fast mode LLM variants."""
        prompt = f"""Optimize this Python function for performance while maintaining correctness.

Original code:
```python
{code}
```

Requirements:
1. Maintain 100% correctness (all tests must pass)
2. Reduce execution time (vectorize with NumPy if possible)
3. Minimize memory usage

Return ONLY the optimized Python code, no explanations."""

        if specs:
            prompt += "\n\nExisting tests to satisfy:\n"
            for spec in specs[:3]:
                prompt += f"\n{spec.test_code}"

        return prompt

    def _calculate_improvement(
        self,
        baseline: FitnessVector,
        optimized: FitnessVector,
    ) -> float:
        """Compute the improvement fraction of ``optimized`` vs ``baseline``.

        A positive value means the candidate is better (faster / leaner).
        Latency dominates the score; memory is a secondary term.
        """
        latency_gain = 0.0
        if baseline.latency_p50 > 0:
            latency_gain = (baseline.latency_p50 - optimized.latency_p50) / baseline.latency_p50

        memory_gain = 0.0
        if baseline.memory_peak_mb > 0:
            memory_gain = (baseline.memory_peak_mb - optimized.memory_peak_mb) / baseline.memory_peak_mb

        return 0.7 * latency_gain + 0.3 * memory_gain


def run_progressive_optimization(code: str,
                                 llm_fn: Callable[[str], str] = None,
                                 mode: str = "auto") -> PipelineResult:
    """Convenience function to run the progressive pipeline."""
    pipeline = ProgressivePipeline(llm_fn=llm_fn)
    return pipeline.run(code, mode=mode)
