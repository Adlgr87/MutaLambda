"""Regression tests: ASTMutator must never crash on real-world code.

Found via dogfooding (running MutaLambda's mutator on MutaLambda's own
source): four mutation operators assumed ``node.body`` is always a list,
but for ``ast.Lambda`` / ``ast.IfExp`` it is a single expression node,
raising ``TypeError: 'Name' object is not iterable``.
"""

import random

import pytest

from evolution_engine import ASTMutator


LAMBDA_HEAVY_CODE = '''
def sort_by_score(items):
    return sorted(items, key=lambda ind: ind.score, reverse=True)

def pick(items):
    best = max(items, key=lambda x: x.fitness if x.fitness else 0)
    label = "high" if best.score > 50 else "low"
    total = 0
    for it in items:
        total += it.score
    return best, label, total
'''


@pytest.mark.root
class TestMutatorRobustness:
    def test_mutate_lambda_heavy_code_never_crashes(self):
        """100 seeded mutations over lambda/ifexp-heavy code: no exceptions."""
        for seed in range(100):
            random.seed(seed)
            result = ASTMutator.apply_random_mutation(LAMBDA_HEAVY_CODE)
            assert isinstance(result, str)
            assert result.strip()

    def test_mutate_own_nsga2_source_never_crashes(self):
        """Self-application: mutating MutaLambda's own nsga2.py must not crash."""
        with open("nsga2.py", "r", encoding="utf-8") as fh:
            src = fh.read()
        for seed in range(25):
            random.seed(seed)
            result = ASTMutator.apply_random_mutation(src)
            assert isinstance(result, str)
