#!/usr/bin/env python3
"""Explainable Optimization Mode for MutaLambda.

Generates LLM-powered explanations for optimization decisions, including:
- Justification for mutations
- Risk analysis
- Complexity impact
- Alternative considerations
"""
from __future__ import annotations
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import hashlib
import json
import logging
from enum import Enum

from muta_ext.uast.core_uast import CoreUAST, Function, Node
try:
    from llm_backend import LLMBackend
except ImportError:
    LLMBackend = None  # type: ignore[misc,assignment]

logger = logging.getLogger("MutaLambda")


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OptimizationType(str, Enum):
    VECTORIZATION = "vectorization"
    LOOP_FUSION = "loop_fusion"
    LOOP_FISSION = "loop_fission"
    INLINE = "inline"
    CACHE_OPTIMIZATION = "cache_optimization"
    ALGORITHM_CHANGE = "algorithm_change"
    PARALLELIZATION = "parallelization"
    MEMORY_OPTIMIZATION = "memory_optimization"
    CONCURRENCY = "concurrency"
    STRENGTH_REDUCTION = "strength_reduction"


@dataclass
class ComplexityAnalysis:
    """Before/after complexity analysis."""
    time_before: str
    time_after: str
    space_before: str
    space_after: str
    notes: str = ""


@dataclass
class OptimizationExplanation:
    """Complete explanation for an optimization decision."""
    optimization_type: OptimizationType
    target_function: str
    justification: str
    risk_level: RiskLevel
    risk_details: str
    complexity: ComplexityAnalysis
    alternatives_considered: List[str]
    confidence: float  # 0.0 to 1.0
    code_diff_summary: str
    expected_impact: Dict[str, float]  # speedup, memory_change, etc.


class ExplanationGenerator:
    """Generate explanations for optimization decisions using LLM."""

    def __init__(self, llm_backend: Optional[LLMBackend] = None):
        self.llm = llm_backend
        self._cache: Dict[str, OptimizationExplanation] = {}

    def explain_optimization(
        self,
        original_code: str,
        optimized_code: str,
        optimization_type: OptimizationType,
        target_function: str,
        fitness_change: Dict[str, float],
        uast_before: Optional[CoreUAST] = None,
        uast_after: Optional[CoreUAST] = None,
    ) -> OptimizationExplanation:
        """Generate detailed explanation for an optimization."""
        cache_key = self._make_cache_key(original_code, optimized_code, optimization_type)

        if cache_key in self._cache:
            return self._cache[cache_key]

        # Analyze complexity
        complexity = self._analyze_complexity(uast_before, uast_after)

        # Generate justification
        justification = self._generate_justification(
            original_code, optimized_code, optimization_type, target_function
        )

        # Assess risks
        risk_level, risk_details = self._assess_risks(
            original_code, optimized_code, optimization_type
        )

        # Find alternatives
        alternatives = self._find_alternatives(optimization_type)

        # Calculate confidence
        confidence = self._calculate_confidence(
            fitness_change, complexity, risk_level
        )

        explanation = OptimizationExplanation(
            optimization_type=optimization_type,
            target_function=target_function,
            justification=justification,
            risk_level=risk_level,
            risk_details=risk_details,
            complexity=complexity,
            alternatives_considered=alternatives,
            confidence=confidence,
            code_diff_summary=self._summarize_diff(original_code, optimized_code),
            expected_impact=fitness_change
        )

        self._cache[cache_key] = explanation
        return explanation

    def explain_mutations_batch(
        self,
        mutations: List[Dict[str, Any]],
        results: List[Dict[str, Any]]
    ) -> List[OptimizationExplanation]:
        """Generate explanations for multiple mutations."""
        explanations = []
        for mutation, result in zip(mutations, results):
            explanation = self.explain_optimization(
                original_code=mutation.get('original', ''),
                optimized_code=mutation.get('optimized', ''),
                optimization_type=OptimizationType(mutation.get('type', 'algorithm_change')),
                target_function=mutation.get('function', 'unknown'),
                fitness_change=result.get('fitness_change', {}),
                uast_before=mutation.get('uast_before'),
                uast_after=mutation.get('uast_after')
            )
            explanations.append(explanation)
        return explanations

    def _generate_justification(
        self,
        original: str,
        optimized: str,
        opt_type: OptimizationType,
        func_name: str
    ) -> str:
        """Generate human-readable justification for the optimization."""
        # Use LLM if available
        if self.llm:
            prompt = self._build_explanation_prompt(original, optimized, opt_type, func_name)
            try:
                response = self.llm.generate(prompt, max_tokens=500)
                return response.strip()[:1000]
            except Exception:
                logger.warning(
                    "LLM explanation failed for %s; using heuristic explanation",
                    func_name,
                    exc_info=True,
                )

        # Fallback: heuristic-based explanation
        return self._heuristic_explanation(opt_type, func_name, original, optimized)

    def _heuristic_explanation(
        self,
        opt_type: OptimizationType,
        func_name: str,
        original: str,
        optimized: str
    ) -> str:
        """Generate explanation using rule-based heuristics."""
        explanations = {
            OptimizationType.VECTORIZATION: (
                f"Applied vectorization to function '{func_name}'. "
                f"The original loop performed element-wise operations sequentially. "
                f"The optimized version uses vectorized operations (e.g., NumPy broadcasting) "
                f"to process multiple elements in parallel, reducing CPU cycles."
            ),
            OptimizationType.LOOP_FUSION: (
                f"Fused consecutive loops in '{func_name}' into a single pass. "
                f"This improves cache locality and reduces loop overhead, "
                f"trading a small increase in register pressure for better memory access patterns."
            ),
            OptimizationType.LOOP_FISSION: (
                f"Split a complex loop in '{func_name}' into multiple simpler loops. "
                f"This allows better vectorization opportunities and improves branch prediction."
            ),
            OptimizationType.INLINE: (
                f"Inlining candidate '{func_name}' at call sites. "
                f"Small function calls have significant overhead from stack manipulation. "
                f"Inlining eliminates this overhead but increases code size."
            ),
            OptimizationType.ALGORITHM_CHANGE: (
                f"Replaced algorithm in '{func_name}' with a more efficient approach. "
                f"The original had O(n²) complexity due to linear search; "
                f"the optimized version uses O(n log n) sorting or O(n) hash-based lookup."
            ),
            OptimizationType.PARALLELIZATION: (
                f"Parallelized sequential loop in '{func_name}' using worker threads/processes. "
                f"This trades increased memory usage for reduced execution time on multi-core systems."
            ),
            OptimizationType.MEMORY_OPTIMIZATION: (
                f"Reduced memory allocations in '{func_name}' by reusing buffers "
                f"and avoiding unnecessary temporary objects."
            ),
            OptimizationType.CONCURRENCY: (
                f"Introduced concurrent execution pattern in '{func_name}' "
                f"using goroutines/channels to overlap computation with I/O."
            ),
            OptimizationType.STRENGTH_REDUCTION: (
                f"Replaced expensive operation in '{func_name}' with cheaper equivalent. "
                f"For example, replaced multiplication with addition in loop induction, "
                f"or bit shifts for powers of 2."
            ),
        }
        return explanations.get(opt_type, f"Applied {opt_type.value} optimization to '{func_name}'.")

    def _assess_risks(
        self,
        original: str,
        optimized: str,
        opt_type: OptimizationType
    ) -> tuple[RiskLevel, str]:
        """Assess risks of the optimization."""
        risks = {
            OptimizationType.VECTORIZATION: (
                RiskLevel.MEDIUM,
                "Vectorization may increase memory usage by 10-30% due to temporary arrays. "
                "Not all operations can be vectorized."
            ),
            OptimizationType.LOOP_FUSION: (
                RiskLevel.LOW,
                "Loop fusion is generally safe. May increase register pressure slightly."
            ),
            OptimizationType.LOOP_FISSION: (
                RiskLevel.LOW,
                "Loop fission improves cache behavior. Minimal risk."
            ),
            OptimizationType.INLINE: (
                RiskLevel.MEDIUM,
                "Inlining increases code size, which may cause instruction cache misses. "
                "Excessive inlining can bloat binary size."
            ),
            OptimizationType.ALGORITHM_CHANGE: (
                RiskLevel.HIGH,
                "Algorithm changes may alter numerical precision or behavior for edge cases. "
                "Thorough testing required."
            ),
            OptimizationType.PARALLELIZATION: (
                RiskLevel.HIGH,
                "Parallelization introduces race conditions if not carefully implemented. "
                "Memory overhead scales with thread count."
            ),
            OptimizationType.MEMORY_OPTIMIZATION: (
                RiskLevel.LOW,
                "Memory optimizations are generally safe. May reduce readability."
            ),
            OptimizationType.CONCURRENCY: (
                RiskLevel.MEDIUM,
                "Concurrency adds complexity in debugging. Channel deadlocks possible."
            ),
            OptimizationType.STRENGTH_REDUCTION: (
                RiskLevel.LOW,
                "Strength reduction is mathematically equivalent. Safe transformation."
            ),
        }
        return risks.get(opt_type, (RiskLevel.MEDIUM, "Unknown risk profile."))

    def _find_alternatives(self, opt_type: OptimizationType) -> List[str]:
        """Find alternative optimization strategies."""
        alternatives = {
            OptimizationType.VECTORIZATION: [
                "Use SIMD intrinsics directly",
                "Employ GPU acceleration via CUDA/OpenCL",
                "Use library routines (e.g., BLAS)",
                "Rewrite algorithm to avoid the pattern"
            ],
            OptimizationType.ALGORITHM_CHANGE: [
                "Use different data structure (tree vs hash)",
                "Apply divide-and-conquer strategy",
                "Use approximation for accuracy trade-off",
                "Precompute values if called repeatedly"
            ],
            OptimizationType.PARALLELIZATION: [
                "Use work-stealing runtime",
                "Apply GPU computation",
                "Use async I/O for I/O-bound workloads",
                "Pipeline the computation"
            ],
        }
        return alternatives.get(opt_type, ["Review manually for alternatives"])

    def _analyze_complexity(
        self,
        before: Optional[CoreUAST],
        after: Optional[CoreUAST]
    ) -> ComplexityAnalysis:
        """Analyze complexity changes."""
        if not before or not after:
            return ComplexityAnalysis(
                time_before="unknown",
                time_after="unknown",
                space_before="unknown",
                space_after="unknown",
                notes="UAST not available for complexity analysis"
            )

        # Count operations
        before_ops = self._count_operations(before)
        after_ops = self._count_operations(after)

        return ComplexityAnalysis(
            time_before=f"~{before_ops} operations",
            time_after=f"~{after_ops} operations",
            space_before=self._estimate_space(before),
            space_after=self._estimate_space(after),
            notes=f"Operation count {'decreased' if after_ops < before_ops else 'increased'} by {abs(after_ops - before_ops)}"
        )

    def _count_operations(self, uast: CoreUAST) -> int:
        """Count approximate operations in UAST."""
        count = 0
        for node in uast.body:
            count += self._count_node_ops(node)
        return count

    def _count_node_ops(self, node: Node) -> int:
        """Count operations in a single node."""
        if isinstance(node, Function):
            return sum(self._count_node_ops(child) for child in node.body)
        if hasattr(node, 'body'):
            return sum(self._count_node_ops(child) for child in node.body if isinstance(child, Node))
        return 1

    def _estimate_space(self, uast: CoreUAST) -> str:
        """Estimate space complexity from UAST."""
        # Simple heuristic: count allocations
        alloc_count = 0
        for node in uast.body:
            if hasattr(node, 'value') and isinstance(node.value, list):
                alloc_count += 1
        return f"~{alloc_count} heap allocations"

    def _calculate_confidence(
        self,
        fitness_change: Dict[str, float],
        complexity: ComplexityAnalysis,
        risk: RiskLevel
    ) -> float:
        """Calculate confidence score for the optimization."""
        base_confidence = 0.7

        # Adjust based on fitness improvement
        speedup = fitness_change.get('latency_p50', 0)
        if speedup > 0:
            base_confidence += min(0.2, speedup * 0.1)

        # Adjust based on risk
        risk_penalty = {
            RiskLevel.LOW: 0.0,
            RiskLevel.MEDIUM: -0.1,
            RiskLevel.HIGH: -0.2,
            RiskLevel.CRITICAL: -0.3,
        }
        base_confidence += risk_penalty.get(risk, 0)

        # Adjust based on complexity change
        if "decreased" in complexity.notes.lower():
            base_confidence += 0.05
        elif "increased" in complexity.notes.lower():
            base_confidence -= 0.05

        return max(0.1, min(1.0, base_confidence))

    def _summarize_diff(self, original: str, optimized: str) -> str:
        """Generate diff summary."""
        orig_lines = set(original.split('\n'))
        opt_lines = set(optimized.split('\n'))

        added = opt_lines - orig_lines
        removed = orig_lines - opt_lines

        summary_parts = []
        if added:
            summary_parts.append(f"+{len(added)} lines added")
        if removed:
            summary_parts.append(f"-{len(removed)} lines removed")

        return ", ".join(summary_parts) if summary_parts else "Minimal changes"

    def _build_explanation_prompt(
        self,
        original: str,
        optimized: str,
        opt_type: OptimizationType,
        func_name: str
    ) -> str:
        """Build LLM prompt for explanation generation."""
        return f"""Analyze this code optimization and explain:

OPTIMIZATION TYPE: {opt_type.value}
FUNCTION: {func_name}

ORIGINAL CODE:
{original[:2000]}

OPTIMIZED CODE:
{optimized[:2000]}

Provide:
1. Clear justification for why this optimization improves performance
2. Risk assessment (low/medium/high)
3. Expected complexity changes
4. One sentence summary

Keep explanation concise and technical."""

    def _make_cache_key(self, original: str, optimized: str, opt_type: OptimizationType) -> str:
        """Generate cache key for explanation."""
        content = f"{original[:500]}|{optimized[:500]}|{opt_type.value}"
        return hashlib.md5(content.encode()).hexdigest()[:16]


class ExplainableOptimizer:
    """Main interface for explainable optimization mode."""

    def __init__(self, llm_backend: Optional[LLMBackend] = None):
        self.generator = ExplanationGenerator(llm_backend)

    def optimize_and_explain(
        self,
        original_code: str,
        optimized_code: str,
        optimization_type: str,
        function_name: str,
        fitness_results: Dict[str, float]
    ) -> Dict[str, Any]:
        """Run optimization and generate comprehensive explanation."""
        opt_type = OptimizationType(optimization_type)

        explanation = self.generator.explain_optimization(
            original_code=original_code,
            optimized_code=optimized_code,
            optimization_type=opt_type,
            target_function=function_name,
            fitness_change=fitness_results
        )

        return {
            "optimization_type": explanation.optimization_type.value,
            "target_function": explanation.target_function,
            "justification": explanation.justification,
            "risk_level": explanation.risk_level.value,
            "risk_details": explanation.risk_details,
            "complexity": {
                "time_before": explanation.complexity.time_before,
                "time_after": explanation.complexity.time_after,
                "space_before": explanation.complexity.space_before,
                "space_after": explanation.complexity.space_after,
                "notes": explanation.complexity.notes
            },
            "alternatives_considered": explanation.alternatives_considered,
            "confidence": explanation.confidence,
            "code_changes": explanation.code_diff_summary,
            "expected_impact": explanation.expected_impact
        }


def create_explainable_optimizer(llm_config: Optional[Dict] = None) -> ExplainableOptimizer:
    """Factory function to create explainable optimizer."""
    llm = None
    if llm_config:
        llm = LLMBackend(llm_config)
    return ExplainableOptimizer(llm)
