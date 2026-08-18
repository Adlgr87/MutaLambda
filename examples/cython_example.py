"""Example: Loop-based computation for Cython optimization."""


def sum_squares(n):
    """Compute sum of squares from 1 to n."""
    total = 0
    for i in range(1, n + 1):
        total += i * i
    return total
