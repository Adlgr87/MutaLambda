
TARGET_NAME = "histogram"
TIER = 2
function_name = "histogram"
import numpy as np
source = """
def histogram(values, n_bins):
    counts = [0] * n_bins
    lo = 0
    hi = n_bins
    span = (hi - lo)
    for v in values:
        idx = int((v - lo) * n_bins / span)
        if idx == n_bins:
            idx = n_bins - 1
        if idx >= 0 and idx < n_bins:
            counts[idx] = counts[idx] + 1
    return counts
"""
def _ref(values, n_bins):
    vals=np.asarray(values,dtype=float)
    counts,_=np.histogram(vals,bins=n_bins,range=(0,n_bins))
    return [int(c) for c in counts]
test_cases = [
    {"function": "histogram", "args": [[0.5,1.5,2.5,3.5], 4], "expected": _ref([0.5,1.5,2.5,3.5],4), "comparison": "equal"},
    {"function": "histogram", "args": [[1.0,1.0,1.0], 3], "expected": _ref([1.0,1.0,1.0],3), "comparison": "equal"},
]
invariants = ['sum(out) <= len(x[0])']
input_strategy = "st.tuples(st.lists(st.floats(min_value=0,max_value=4,allow_nan=False),min_size=0,max_size=20), st.integers(min_value=1,max_value=8))"
