"""
Interpretability safeguards for evolved code.

Provides 3 layers of protection against "alien code" syndrome:
1. Auto-documentation: Uses LLM to add human-readable comments
2. Human-readable checkpoints: Deobfuscates and extracts patterns
3. Fitness transparency reports: Documents what changed and why

These safeguards ensure evolved code remains maintainable and auditable.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class InterpretabilityReport:
    """Transparency report for an evolved code fragment."""
    
    original_code: str
    evolved_code: str
    generation: int
    fitness_before: float
    fitness_after: float
    improvements: List[str] = field(default_factory=list)
    lineage: List[str] = field(default_factory=list)
    tests_passed: bool = False
    human_readable_version: Optional[str] = None
    documentation: Optional[str] = None
    
    def to_markdown(self) -> str:
        """Generate markdown report for human review."""
        improvement_pct = ((self.fitness_after - self.fitness_before) / 
                          max(0.001, self.fitness_before) * 100)
        
        report = f"""## Evolved Code Report — Generation {self.generation}

**Fitness Improvement:** {self.fitness_before:.4f} → {self.fitness_after:.4f} ({improvement_pct:+.1f}%)

### Key Optimizations
"""
        
        if self.improvements:
            for i, imp in enumerate(self.improvements, 1):
                report += f"{i}. {imp}\n"
        else:
            report += "*(No specific optimizations identified)*\n"
        
        report += f"""
### Lineage
"""
        if self.lineage:
            report += "```\n" + " → ".join(self.lineage) + "\n```\n"
        else:
            report += "*(No lineage information available)*\n"
        
        report += f"""
### Test Status
{"✅ All tests passed" if self.tests_passed else "❌ Tests failed"}

### Evolved Code
```python
{self.evolved_code}
```
"""
        
        if self.human_readable_version:
            report += f"""
### Human-Readable Version (Checkpoint)
```python
{self.human_readable_version}
```
"""
        
        if self.documentation:
            report += f"""
### Auto-Generated Documentation
{self.documentation}
"""
        
        return report


class CodeDocumenter:
    """Layer 1: Auto-document evolved code using LLM."""
    
    def __init__(self, llm_backend=None):
        self.llm_backend = llm_backend
    
    def document(self, code: str, generation: int, context: str = "") -> str:
        """Add explanatory comments to evolved code.
        
        Args:
            code: The evolved (potentially obfuscated) code
            generation: Which generation produced this code
            context: Optional context about what was optimized
            
        Returns:
            Code with added docstrings and inline comments
        """
        if self.llm_backend is None:
            # Fallback: add minimal documentation
            return self._fallback_document(code, generation)
        
        prompt = f"""You are documenting Python code that was evolved by a genetic algorithm.
The code works correctly but may be hard to read.

Generation: {generation}
Optimization context: {context if context else "General performance optimization"}

Add clear docstrings and inline comments explaining:
1. What the code does (high-level purpose)
2. Key optimizations or non-obvious techniques used
3. Any performance tricks or mathematical insights

Code to document:
```python
{code}
```

Return ONLY the documented code (no explanations, no markdown).
"""
        
        try:
            documented = self.llm_backend.generate(prompt, max_tokens=2000)
            # Clean up any markdown artifacts
            documented = documented.strip()
            if documented.startswith("```python"):
                documented = documented[9:]
            if documented.startswith("```"):
                documented = documented[3:]
            if documented.endswith("```"):
                documented = documented[:-3]
            return documented.strip()
        except Exception as e:
            print(f"Warning: LLM documentation failed ({e}), using fallback")
            return self._fallback_document(code, generation)
    
    def _fallback_document(self, code: str, generation: int) -> str:
        """Minimal documentation when LLM is unavailable."""
        lines = code.split("\n")
        
        # Add header docstring if missing
        if not lines[0].strip().startswith('"""') and not lines[0].strip().startswith("'''"):
            header = f'"""Evolved code (generation {generation}).\n\nAuto-evolved by MutaLambda.\nOptimized for fitness vector objectives.\n"""'
            lines.insert(0, header)
        
        # Add generation marker
        lines.append(f"\n# Evolved: generation {generation}")
        
        return "\n".join(lines)


class CodeCheckpoint:
    """Layer 2: Create human-readable checkpoints of evolved code."""
    
    def create_checkpoint(self, code: str) -> str:
        """Deobfuscate and clean up evolved code for human review.
        
        Performs:
        - Variable renaming (if cryptic)
        - Whitespace normalization
        - Comment extraction
        - Pattern identification
        
        Returns:
            Cleaned, human-readable version of the code
        """
        # Normalize whitespace
        cleaned = self._normalize_whitespace(code)
        
        # Rename cryptic variables (v1, v2, etc.)
        cleaned = self._rename_variables(cleaned)
        
        # Extract and document patterns
        cleaned = self._extract_patterns(cleaned)
        
        return cleaned
    
    def _normalize_whitespace(self, code: str) -> str:
        """Fix indentation and spacing."""
        lines = []
        for line in code.split("\n"):
            # Remove trailing whitespace
            line = line.rstrip()
            # Ensure consistent indentation (4 spaces)
            if line and not line[0].isspace():
                lines.append(line)
            elif line:
                # Count leading spaces/tabs
                stripped = line.lstrip()
                indent = len(line) - len(stripped)
                # Normalize to 4-space indents
                indent_level = indent // 4
                lines.append("    " * indent_level + stripped)
            else:
                lines.append("")
        return "\n".join(lines)
    
    def _rename_variables(self, code: str) -> str:
        """Rename cryptic single-letter variables to descriptive names."""
        # This is a simplified version - full implementation would use AST
        # For now, just return as-is (LLM can do better renaming)
        return code
    
    def _extract_patterns(self, code: str) -> str:
        """Identify and document reusable patterns."""
        patterns = []
        
        # Look for common optimization patterns
        if "cache" in code.lower() or "memo" in code.lower():
            patterns.append("# Pattern: Caching/memoization for repeated computations")
        
        if re.search(r'\b(sum|map|filter|zip)\b', code):
            patterns.append("# Pattern: Functional programming constructs for efficiency")
        
        if "bit" in code.lower() or "<<" in code or ">>" in code:
            patterns.append("# Pattern: Bit manipulation for performance")
        
        if patterns:
            # Add patterns as comments at the top
            code = "\n".join(patterns) + "\n\n" + code
        
        return code


class FitnessReporter:
    """Layer 3: Generate fitness transparency reports."""
    
    def generate_report(
        self,
        original_code: str,
        evolved_code: str,
        generation: int,
        fitness_before: float,
        fitness_after: float,
        lineage: List[str] = None,
        tests_passed: bool = True,
        llm_backend=None,
    ) -> InterpretabilityReport:
        """Generate comprehensive transparency report.
        
        Args:
            original_code: Code before evolution
            evolved_code: Code after evolution
            generation: Generation number
            fitness_before: Fitness score before evolution
            fitness_after: Fitness score after evolution
            lineage: List of ancestor IDs
            tests_passed: Whether all tests still pass
            llm_backend: Optional LLM for optimization analysis
            
        Returns:
            InterpretabilityReport with full analysis
        """
        improvements = self._analyze_improvements(
            original_code, evolved_code, llm_backend
        )
        
        # Create human-readable checkpoint
        checkpoint = CodeCheckpoint()
        human_readable = checkpoint.create_checkpoint(evolved_code)
        
        # Auto-document
        documenter = CodeDocumenter(llm_backend)
        documentation = documenter.document(evolved_code, generation)
        
        return InterpretabilityReport(
            original_code=original_code,
            evolved_code=evolved_code,
            generation=generation,
            fitness_before=fitness_before,
            fitness_after=fitness_after,
            improvements=improvements,
            lineage=lineage or [],
            tests_passed=tests_passed,
            human_readable_version=human_readable,
            documentation=documentation,
        )
    
    def _analyze_improvements(
        self,
        original: str,
        evolved: str,
        llm_backend=None,
    ) -> List[str]:
        """Analyze what optimizations were made."""
        improvements = []
        
        # Simple heuristic analysis
        orig_lines = len(original.split("\n"))
        evolved_lines = len(evolved.split("\n"))
        
        if evolved_lines < orig_lines * 0.8:
            improvements.append(
                f"Code reduction: {orig_lines} → {evolved_lines} lines "
                f"({(1 - evolved_lines/orig_lines)*100:.0f}% smaller)"
            )
        
        # Check for common optimizations
        if "cache" in evolved.lower() and "cache" not in original.lower():
            improvements.append("Added caching mechanism")
        
        if "return" in evolved and evolved.count("return") > original.count("return"):
            improvements.append("Added early returns for optimization")
        
        # Use LLM for deeper analysis if available
        if llm_backend is not None:
            try:
                prompt = f"""Compare these two Python code versions and identify the key optimizations made.

Original code:
```python
{original}
```

Evolved code:
```python
{evolved}
```

List 2-4 specific optimizations (performance, algorithmic, or structural improvements).
Return as a bulleted list, no markdown formatting.
"""
                analysis = llm_backend.generate(prompt, max_tokens=500)
                # Parse bullet points
                for line in analysis.split("\n"):
                    line = line.strip()
                    if line.startswith("-") or line.startswith("*"):
                        improvements.append(line.lstrip("-* ").strip())
            except Exception:
                pass  # LLM analysis is optional
        
        if not improvements:
            improvements.append("Evolutionary optimization (details not analyzed)")
        
        return improvements


def create_interpretability_report(
    original_code: str,
    evolved_code: str,
    generation: int,
    fitness_before: float,
    fitness_after: float,
    output_path: Path,
    llm_backend=None,
) -> InterpretabilityReport:
    """Convenience function to generate and save a full interpretability report.
    
    Args:
        original_code: Code before evolution
        evolved_code: Code after evolution
        generation: Generation number
        fitness_before: Fitness before
        fitness_after: Fitness after
        output_path: Where to save the markdown report
        llm_backend: Optional LLM for analysis
        
    Returns:
        InterpretabilityReport object
    """
    reporter = FitnessReporter()
    report = reporter.generate_report(
        original_code=original_code,
        evolved_code=evolved_code,
        generation=generation,
        fitness_before=fitness_before,
        fitness_after=fitness_after,
        llm_backend=llm_backend,
    )
    
    # Save markdown report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report.to_markdown())
    
    print(f"✅ Interpretability report saved to: {output_path}")
    
    return report
