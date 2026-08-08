"""
Progressive Pipeline — MutaLambda 2.0 Workflow.

Implements the progressive discovery pipeline:
- FASE 0: Discovery & Hotspots
- FASE 1: Test Synthesis
- FASE 2: Fast Mode (default)
- FASE 3: Deep Evolution (fallback --deep)
- FASE 4: Patch & Report
"""

from __future__ import annotations

import ast
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Any
from pathlib import Path

from fitness_vector import FitnessVector
from workflow_protocol import ComplexityGate, ProtocolWorkflow, StageResult

logger = logging.getLogger("MutaLambda")


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

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = ["=" * 60]
        lines.append("MUTALAMBDA 2.0 — OPTIMIZATION REPORT")
        lines.append("=" * 60)
        lines.append(f"Success: {self.success}")
        lines.append(f"Phase reached: {self.phase_reached}")
        lines.append(f"Duration: {self.duration_sec:.2f}s")

        if self.fitness:
            lines.append(f"
Fitness:")
            lines.append(f"  Correctness: {self.fitness.correctness:.1%}")
            lines.append(f"  Latency P50: {self.fitness.latency_p50:.2f}ms")
            lines.append(f"  Memory Peak: {self.fitness.memory_peak_mb:.2f}MB")

        if self.report.get("hotspots"):
            lines.append(f"
Hotspots found: {len(self.report['hotspots'])}")
            for hs in self.report["hotspots"][:3]:
                lines.append(f"  • {hs.get('name', '?')} [{hs.get('severity', '?')}]")

        if self.report.get("tests_generated"):
            lines.append(f"
Tests generated: {self.report['tests_generated']}")

        if self.report.get("variants_evaluated"):
            lines.append(f"Variants evaluated: {self.report['variants_evaluated']}")

        lines.append("=" * 60)
        return "\n".join(lines)


class ProgressivePipeline:
    """Main pipeline for MutaLambda 2.0 optimization workflow."""

    def __init__(self, 
                 llm_fn: Optional[Callable[[str], str]] = None,
                 test_cases: Optional[List[Dict]] = None,
                 timeout_sec: float = 5.0,
                 min_improvement: float = 0.15,
                 fast_variants: int = 5):
        self.llm_fn = llm_fn
        self.test_cases = test_cases or []
        self.timeout_sec = timeout_sec
        self.min_improvement = min_improvement  # 15% improvement threshold
        self.fast_variants = fast_variants
        self.complexity_gate = ComplexityGate()
        self._report = {}

    def run(self, code: str, mode: str = "auto") -> PipelineResult:
        """Run the progressive pipeline on input code."""
        start_time = time.perf_counter()
        self._report = {
            "hotspots": [],
            "tests_generated": 0,
            "variants_evaluated": 0,
            "phases_completed": [],
        }

        # FASE 0: Discovery & Hotspots
        logger.info("FASE 0: Discovery & Hotspots")
        hotspots = self._discovery_phase(code)
        self._report["hotspots"] = [hs.to_dict() for hs in hotspots]
        self._report["phases_completed"].append("discovery")

        # FASE 1: Test Synthesis
        logger.info("FASE 1: Test Synthesis")
        tests = self._test_synthesis_phase(code, hotspots)
        self._report["tests_generated"] = len(tests)
        self._report["phases_completed"].append("test_synthesis")

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
            result = self._fast_phase(code, tests)
            self._report["phases_completed"].append("fast_mode")
            self._report["variants_evaluated"] = result.get("variants_evaluated", 0)

            if result.get("success"):
                result["report"] = self._report
                result["duration_sec"] = time.perf_counter() - start_time
                return PipelineResult(**result)

        # FASE 3: Deep Evolution (fallback)
        if mode in ("auto", "deep"):
            logger.info("FASE 3: Deep Evolution (--deep)")
            result = self._deep_phase(code, tests)
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
        """FASE 1: Synthesize tests for hotspots."""
        try:
            from test_synthesizer import TestSynthesizer
            synthesizer = TestSynthesizer()
            specs = synthesizer.synthesize_tests(code)

            logger.info(f"Generated {len(specs)} test specifications")
            return specs
        except ImportError:
            logger.warning("test_synthesizer not available, using existing tests")
            return []

    def _fast_phase(self, code: str, tests: list) -> dict:
        """FASE 2: Fast mode - generate and evaluate LLM variants."""
        variants_evaluated = 0

        if not self.llm_fn:
            logger.warning("No LLM function provided, skipping fast mode")
            return {"success": False, "reason": "no_llm"}

        # Generate variants via LLM
        prompt = self._build_fast_prompt(code, tests)
        try:
            variants = []
            for i in range(self.fast_variants):
                variant = self.llm_fn(prompt)
                if variant and variant != code:
                    variants.append(variant)

            variants_evaluated = len(variants)
            logger.info(f"Generated {len(variants)} unique variants")

            # Evaluate variants (would use SandboxEvaluator in full impl)
            best_variant = None
            best_fitness = None

            for variant in variants:
                fitness = self._evaluate_variant(code, variant)
                if fitness and fitness.correctness >= 1.0:
                    if best_fitness is None or fitness > best_fitness:
                        best_fitness = fitness
                        best_variant = variant

            if best_variant and best_fitness:
                improvement = self._calculate_improvement(code, best_fitness)
                if improvement >= self.min_improvement:
                    return {
                        "success": True,
                        "phase_reached": "fast_mode",
                        "original_code": code,
                        "optimized_code": best_variant,
                        "fitness": best_fitness,
                        "variants_evaluated": variants_evaluated,
                    }

            return {"success": False, "variants_evaluated": variants_evaluated}

        except Exception as e:
            logger.error(f"Fast mode error: {e}")
            return {"success": False, "variants_evaluated": variants_evaluated}

    def _deep_phase(self, code: str, tests: list) -> dict:
        """FASE 3: Deep evolution with NSGA-II."""
        # This would integrate with island_evolution.py
        # For now, return failure to indicate deep mode not run
        logger.info("Deep evolution would run NSGA-II with 3 objectives")
        return {"success": False, "reason": "deep_mode_placeholder"}

    def _build_fast_prompt(self, code: str, tests: list) -> str:
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

        if tests:
            prompt += f"

Existing tests to satisfy:
"
            for test in tests[:3]:
                prompt += f"\n{test.test_code}"

        return prompt

    def _evaluate_variant(self, original: str, variant: str) -> Optional[FitnessVector]:
        """Evaluate a code variant."""
        # Placeholder - in full implementation would use SandboxEvaluator
        return FitnessVector(correctness=1.0, latency_p50=10.0, memory_peak_mb=50.0)

    def _calculate_improvement(self, original: str, optimized_fitness: FitnessVector) -> float:
        """Calculate improvement percentage."""
        # Placeholder - would compare against baseline
        return 0.2  # 20% improvement


def run_progressive_optimization(code: str, 
                                  llm_fn: Callable[[str], str] = None,
                                  mode: str = "auto") -> PipelineResult:
    """Convenience function to run the progressive pipeline."""
    pipeline = ProgressivePipeline(llm_fn=llm_fn)
    return pipeline.run(code, mode=mode)
