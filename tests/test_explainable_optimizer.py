#!/usr/bin/env python3
"""Tests for explainable optimization in MutaLambda."""
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from muta_ext.explainable_optimizer import (
    ExplainableOptimizer,
    ExplanationGenerator,
    OptimizationType,
    RiskLevel,
    ComplexityAnalysis,
    OptimizationExplanation
)


class TestExplanationGenerator:
    """Test explanation generation."""

    def test_explain_vectorization(self):
        """Test explaining vectorization optimization."""
        generator = ExplanationGenerator()
        
        original = """
for i in range(len(arr)):
    arr[i] = arr[i] * 2
"""
        optimized = "arr = arr * 2"  # Vectorized
        
        explanation = generator.explain_optimization(
            original_code=original,
            optimized_code=optimized,
            optimization_type=OptimizationType.VECTORIZATION,
            target_function="scale_array",
            fitness_change={"latency_p50": 0.3}
        )
        
        assert explanation.optimization_type == OptimizationType.VECTORIZATION
        assert explanation.target_function == "scale_array"
        assert explanation.justification
        assert explanation.risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]

    def test_explain_algorithm_change(self):
        """Test explaining algorithm change optimization."""
        generator = ExplanationGenerator()
        
        original = """
for i in range(n):
    for j in range(n):
        if arr[i] == arr[j]:
            return True
"""
        optimized = """
seen = set()
for x in arr:
    if x in seen:
        return True
    seen.add(x)
"""
        
        explanation = generator.explain_optimization(
            original_code=original,
            optimized_code=optimized,
            optimization_type=OptimizationType.ALGORITHM_CHANGE,
            target_function="has_duplicates",
            fitness_change={"latency_p50": 0.1}
        )
        
        assert explanation.optimization_type == OptimizationType.ALGORITHM_CHANGE
        assert "O(n²)" in explanation.justification or "O(n log n)" in explanation.justification
        assert explanation.risk_level == RiskLevel.HIGH  # Algorithm changes are risky

    def test_explain_parallelization(self):
        """Test explaining parallelization optimization."""
        generator = ExplanationGenerator()
        
        original = """
result = []
for item in data:
    result.append(process(item))
"""
        optimized = """
with ThreadPoolExecutor() as executor:
    result = list(executor.map(process, data))
"""
        
        explanation = generator.explain_optimization(
            original_code=original,
            optimized_code=optimized,
            optimization_type=OptimizationType.PARALLELIZATION,
            target_function="process_all",
            fitness_change={"latency_p50": 0.4}
        )
        
        assert explanation.optimization_type == OptimizationType.PARALLELIZATION
        assert explanation.risk_level in [RiskLevel.MEDIUM, RiskLevel.HIGH]

    def test_heuristic_explanation(self):
        """Test heuristic-based explanation generation."""
        generator = ExplanationGenerator()
        
        explanation = generator._heuristic_explanation(
            OptimizationType.VECTORIZATION,
            "test_func",
            "original",
            "optimized"
        )
        
        assert len(explanation) > 0
        assert "test_func" in explanation

    def test_assess_risks(self):
        """Test risk assessment."""
        generator = ExplanationGenerator()
        
        risk_level, details = generator._assess_risks(
            "original", "optimized", OptimizationType.VECTORIZATION
        )
        
        assert risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert len(details) > 0

    def test_find_alternatives(self):
        """Test finding alternative optimizations."""
        generator = ExplanationGenerator()
        
        alternatives = generator._find_alternatives(OptimizationType.VECTORIZATION)
        
        assert len(alternatives) > 0
        assert isinstance(alternatives, list)

    def test_calculate_confidence(self):
        """Test confidence calculation."""
        generator = ExplanationGenerator()
        
        complexity = ComplexityAnalysis(
            time_before="O(n²)",
            time_after="O(n log n)",
            space_before="O(1)",
            space_after="O(n)",
            notes="Complexity decreased"
        )
        
        confidence = generator._calculate_confidence(
            fitness_change={"latency_p50": 0.3},
            complexity=complexity,
            risk=RiskLevel.LOW
        )
        
        assert 0.1 <= confidence <= 1.0

    def test_summarize_diff(self):
        """Test diff summarization."""
        generator = ExplanationGenerator()
        
        original = "line1\nline2\nline3\n"
        optimized = "line1\nmodified\nline3\nline4\n"
        
        summary = generator._summarize_diff(original, optimized)
        
        assert "+" in summary or "-" in summary


class TestExplainableOptimizer:
    """Test main explainable optimizer interface."""

    def test_optimize_and_explain(self):
        """Test end-to-end optimization explanation."""
        optimizer = ExplainableOptimizer()
        
        result = optimizer.optimize_and_explain(
            original_code="for i in range(n):\n    for j in range(n):\n        pass",
            optimized_code="for i in range(n):\n    for j in range(i+1, n):\n        pass",
            optimization_type="algorithm_change",
            function_name="nested_loops",
            fitness_results={"latency_p50": 0.5}
        )
        
        assert "optimization_type" in result
        assert "justification" in result
        assert "risk_level" in result
        assert "confidence" in result
        assert result["optimization_type"] == "algorithm_change"

    def test_explain_batch(self):
        """Test batch explanation generation."""
        generator = ExplanationGenerator()
        
        mutations = [
            {
                "original": "a = a + 1",
                "optimized": "a += 1",
                "type": "strength_reduction",
                "function": "increment"
            }
        ]
        results = [{"fitness_change": {"latency_p50": 0.01}}]
        
        explanations = generator.explain_mutations_batch(mutations, results)
        
        assert len(explanations) == 1
        assert explanations[0].optimization_type == OptimizationType.STRENGTH_REDUCTION


class TestOptimizationTypes:
    """Test optimization type enum."""

    def test_all_optimization_types_exist(self):
        """Test all optimization types are defined."""
        expected_types = [
            "vectorization",
            "loop_fusion",
            "loop_fission",
            "inline",
            "cache_optimization",
            "algorithm_change",
            "parallelization",
            "memory_optimization",
            "concurrency",
            "strength_reduction"
        ]
        
        for opt_type in expected_types:
            assert hasattr(OptimizationType, opt_type.upper())


class TestRiskLevels:
    """Test risk level enum."""

    def test_all_risk_levels_exist(self):
        """Test all risk levels are defined."""
        expected_levels = ["low", "medium", "high", "critical"]
        
        for level in expected_levels:
            assert hasattr(RiskLevel, level.upper())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
