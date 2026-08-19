# Tier 1 (Easy) — simple loop reduction.  Classic vectorization target.
TARGET_NAME = "compute_sum"
TIER = 1
function_name = "compute_sum"
import numpy as np  # noqa: E402  (used by tests only)
source = '''import numpy as np
def compute_sum(arr):
    total = 0.0
    for i in range(len(arr)):
        total = total + arr[i]
    return total
'''
# Deterministic correctness cases (Layer 1 + differential baseline).
test_cases = [
    {"function": "compute_sum", "args": [np.array([1, 2, 3, 4, 5], dtype=float)], "expected": 15.0, "comparison": "float_close"},
    {"function": "compute_sum", "args": [np.array([], dtype=float)], "expected": 0.0, "comparison": "float_close"},
    {"function": "compute_sum", "args": [np.array([1.5, 2.5, 3.0], dtype=float)], "expected": 7.0, "comparison": "float_close"},
]
# Hypothesis property: sum is invariant under permutation of elements.
invariants = ['abs(out - sum(x)) < 1e-6 * (1 + abs(sum(x)))']
input_strategy = "st.lists(st.floats(min_value=-1e4, max_value=1e4, allow_nan=False), min_size=0, max_size=20)"
