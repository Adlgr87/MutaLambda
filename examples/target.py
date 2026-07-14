"""Example evolution target for MutaLambda demos and CLI smoke tests."""


def solution(n: int) -> int:
    """Return the sum of integers from 1 to n (inclusive)."""
    total = 0
    i = 1
    while i <= n:
        total = total + i
        i = i + 1
    return total
