"""Example: Simple NumPy array operation for optimization."""
import numpy as np


def compute_stats(data):
    """Compute mean and std of a numpy array."""
    n = len(data)
    mean = 0.0
    for i in range(n):
        mean += data[i]
    mean /= n

    variance = 0.0
    for i in range(n):
        diff = data[i] - mean
        variance += diff * diff
    variance /= n
    std = variance ** 0.5

    return mean, std
