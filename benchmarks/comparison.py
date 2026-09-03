"""
Deep value comparison utilities for benchmark differential testing (D2/D4).
"""
from __future__ import annotations

import math
from typing import Any, Tuple


def compare_values(a: Any, b: Any, rel_tol: float = 1e-9, abs_tol: float = 1e-12) -> Tuple[bool, float]:
    """Compare two values loosely; return (equal, max_abs_error).

    Handles scalars, lists/tuples, numpy arrays, and nested combinations.
    """
    try:
        import numpy as np
        if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
            arr_a = np.asarray(a)
            arr_b = np.asarray(b)
            if arr_a.shape != arr_b.shape:
                return False, float("inf")
            if not math.isclose(float(np.max(np.abs(arr_a - arr_b))), 0.0,
                                rel_tol=0, abs_tol=abs_tol):
                equal = bool(np.allclose(arr_a, arr_b, rtol=rel_tol, atol=abs_tol))
                err = float(np.max(np.abs(arr_a - arr_b)))
                return equal, err
            return True, 0.0
    except ImportError:
        pass

    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return False, float("inf")
        max_err = 0.0
        for x, y in zip(a, b):
            ok, err = compare_values(x, y, rel_tol, abs_tol)
            if not ok:
                return False, err
            max_err = max(max_err, err)
        return True, max_err

    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False, float("inf")
        max_err = 0.0
        for k in a:
            ok, err = compare_values(a[k], b[k], rel_tol, abs_tol)
            if not ok:
                return False, err
            max_err = max(max_err, err)
        return True, max_err

    # Fallback to scalar comparison
    try:
        fa, fb = float(a), float(b)
        if math.isclose(fa, fb, rel_tol=rel_tol, abs_tol=abs_tol):
            return True, 0.0
        return False, abs(fa - fb)
    except (TypeError, ValueError):
        if a == b:
            return True, 0.0
        return False, float("inf")