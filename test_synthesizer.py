"""
Test Synthesizer — Automatic property-based test generation for MutaLambda.

Uses Hypothesis for property-based testing, with automatic strategy
generation from Python type hints.
"""

from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Callable
from pathlib import Path


@dataclass
class TestSpec:
    """Specification for a generated test."""
    target_function: str
    strategies: Dict[str, str]  # param_name -> hypothesis strategy
    test_code: str
    imports: List[str] = field(default_factory=list)


class TypeInferenceEngine:
    """Infer Hypothesis strategies from Python type hints."""

    # Mapping from Python types to Hypothesis strategies
    TYPE_STRATEGY_MAP = {
        'int': 'st.integers()',
        'float': 'st.floats(allow_nan=False, allow_infinity=False)',
        'str': 'st.text()',
        'bool': 'st.booleans()',
        'bytes': 'st.binary()',
        'list': 'st.lists(st.anything())',
        'dict': 'st.dictionaries(st.text(), st.anything())',
        'set': 'st.sets(st.anything())',
        'tuple': 'st.tuples(st.anything())',
        'Optional': 'st.none() | st.just(None)',
        'Any': 'st.anything()',
    }

    # NumPy-specific types
    NUMPY_STRATEGY_MAP = {
        'np.ndarray': 'st.arrays(dtype=np.float64, shape=st.tuples(st.integers(1, 10)))',
        'ndarray': 'st.arrays(dtype=np.float64, shape=st.tuples(st.integers(1, 10)))',
        'ArrayLike': 'st.lists(st.floats(allow_nan=False))',
    }

    @classmethod
    def infer_strategy(cls, type_hint: str) -> str:
        """Infer Hypothesis strategy from type hint string."""
        # Check direct mapping
        if type_hint in cls.TYPE_STRATEGY_MAP:
            return cls.TYPE_STRATEGY_MAP[type_hint]

        # Check for generic types
        if type_hint.startswith('List['):
            inner = type_hint[5:-1]
            inner_strategy = cls.infer_strategy(inner)
            return f'st.lists({inner_strategy})'

        if type_hint.startswith('Dict['):
            inner = type_hint[5:-1]
            key_type, val_type = inner.split(',', 1)
            key_strat = cls.infer_strategy(key_type.strip())
            val_strat = cls.infer_strategy(val_type.strip())
            return f'st.dictionaries({key_strat}, {val_strat})'

        if type_hint.startswith('Optional['):
            inner = type_hint[9:-1]
            inner_strategy = cls.infer_strategy(inner)
            return f'st.one_of(st.none(), {inner_strategy})'

        # Default to anything
        return 'st.anything()'

    @classmethod
    def extract_type_hints(cls, func_node: ast.FunctionDef) -> Dict[str, str]:
        """Extract type hints from AST function node."""
        hints = {}

        # Process arguments
        for arg in func_node.args.args:
            if arg.annotation:
                hints[arg.arg] = ast.unparse(arg.annotation)

        # Process return type
        if func_node.returns:
            hints['return'] = ast.unparse(func_node.returns)

        return hints


class TestSynthesizer:
    """Generate property-based tests from function signatures."""

    def __init__(self):
        self.type_engine = TypeInferenceEngine()

    def synthesize_tests(self, code: str, target_func: str = None) -> List[TestSpec]:
        """Generate test specifications for functions in code."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []

        specs = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if target_func and node.name != target_func:
                    continue

                # Skip private/helper functions
                if node.name.startswith('_'):
                    continue

                spec = self._generate_test_spec(node, code)
                if spec:
                    specs.append(spec)

        return specs

    def _generate_test_spec(self, func_node: ast.FunctionDef, full_code: str) -> Optional[TestSpec]:
        """Generate test spec for a single function."""
        # Extract type hints
        type_hints = self.type_engine.extract_type_hints(func_node)

        # If no type hints, use default strategies
        if not type_hints:
            type_hints = {arg.arg: 'Any' for arg in func_node.args.args}

        # Generate strategies
        strategies = {}
        for param, hint in type_hints.items():
            if param != 'return':
                strategies[param] = self.type_engine.infer_strategy(hint)

        if not strategies:
            return None

        # Generate test code
        test_code = self._generate_test_code(func_node.name, strategies, type_hints.get('return', 'Any'))

        imports = [
            'from hypothesis import given, strategies as st, settings',
            'import numpy as np',
        ]

        return TestSpec(
            target_function=func_node.name,
            strategies=strategies,
            test_code=test_code,
            imports=imports,
        )

    def _generate_test_code(self, func_name: str, strategies: Dict[str, str], return_type: str) -> str:
        """Generate Hypothesis test code."""
        lines = []
        lines.append(f'@given({", ".join(f"{name}={strat}" for name, strat in strategies.items())})')
        lines.append(f'@settings(max_examples=50)')
        lines.append(f'def test_{func_name}({", ".join(strategies.keys())}):')
        lines.append(f'    """Property-based test for {func_name}."""')
        lines.append(f'    result = {func_name}({", ".join(strategies.keys())})')
        lines.append(f'    ')
        lines.append(f'    # Basic properties')
        lines.append(f'    assert result is not None  # Or appropriate check')

        # Add return type specific checks
        if return_type in ('int', 'float'):
            lines.append(f'    assert isinstance(result, (int, float))')
        elif return_type == 'bool':
            lines.append(f'    assert isinstance(result, bool)')
        elif return_type == 'str':
            lines.append(f'    assert isinstance(result, str)')
        elif return_type.startswith('List'):
            lines.append(f'    assert isinstance(result, list)')

        lines.append(f'    ')
        lines.append(f'    # TODO: Add domain-specific properties')

        return '\n'.join(lines)

    def find_existing_tests(self, repo_path: str, func_name: str) -> List[str]:
        """Search for existing tests in repository."""
        test_files = []
        repo = Path(repo_path)

        # Search for test files
        for test_file in repo.glob('**/test_*.py'):
            content = test_file.read_text()
            if func_name in content:
                test_files.append(str(test_file))

        for test_file in repo.glob('**/*_test.py'):
            content = test_file.read_text()
            if func_name in content:
                test_files.append(str(test_file))

        return test_files


class ExistingTestScanner:
    """Scan repository for existing pytest/unittest tests."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)

    def scan(self) -> Dict[str, List[str]]:
        """Find all test files and their test functions."""
        tests = {}

        for test_file in self.repo_path.glob('**/test_*.py'):
            funcs = self._extract_test_functions(test_file)
            if funcs:
                tests[str(test_file)] = funcs

        for test_file in self.repo_path.glob('**/*_test.py'):
            funcs = self._extract_test_functions(test_file)
            if funcs:
                tests[str(test_file)] = funcs

        return tests

    def _extract_test_functions(self, file_path: Path) -> List[str]:
        """Extract test function names from a test file."""
        try:
            content = file_path.read_text()
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            return []

        test_funcs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                test_funcs.append(node.name)

        return test_funcs

    def find_tests_for_function(self, func_name: str) -> List[str]:
        """Find tests that target a specific function."""
        matching_tests = []

        for test_file in self.repo_path.glob('**/test_*.py'):
            try:
                content = test_file.read_text()
                if func_name in content:
                    matching_tests.append(str(test_file))
            except UnicodeDecodeError:
                continue

        return matching_tests
