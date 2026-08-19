
TARGET_NAME = "normalize_minmax"
TIER = 4
function_name = "normalize_minmax"
import numpy as np
source = """
import numpy as np
def normalize_minmax(data, feature_min=0.0, feature_max=1.0):
    n_features = len(data[0])
    n_samples = len(data)
    mins = [float('inf')] * n_features
    maxs = [float('-inf')] * n_features
    for row in data:
        for j in range(n_features):
            v = row[j]
            if v < mins[j]:
                mins[j] = v
            if v > maxs[j]:
                maxs[j] = v
    out = [[0.0] * n_features for _ in range(n_samples)]
    for i in range(n_samples):
        for j in range(n_features):
            rng = maxs[j] - mins[j]
            if rng == 0:
                out[i][j] = (feature_min + feature_max) / 2.0
            else:
                out[i][j] = (data[i][j] - mins[j]) / rng * (feature_max - feature_min) + feature_min
    return out
"""
import numpy as np
def _ref(data, feature_min=0.0, feature_max=1.0):
    arr=np.asarray(data,dtype=float)
    mins=arr.min(axis=0); maxs=arr.max(axis=0); rng=maxs-mins
    rng=np.where(rng==0,1.0,rng)
    return ((arr-mins)/rng*(feature_max-feature_min)+feature_min).tolist()
DATA=[[1.0,10.0],[2.0,20.0],[3.0,30.0],[4.0,40.0]]
test_cases = [
    {"function": "normalize_minmax", "args": [DATA, 0.0, 1.0], "expected": _ref(DATA,0.0,1.0), "comparison": "array_allclose"},
    {"function": "normalize_minmax", "args": [[[5.0,5.0,5.0]], 0.0, 1.0], "expected": [[0.5,0.5,0.5]], "comparison": "array_allclose"},
]
invariants = ['all(x[1] <= float(v) <= x[2] for row in out for v in row)']
input_strategy = "st.lists(st.lists(st.floats(min_value=-100,max_value=100,allow_nan=False),min_size=2,max_size=4),min_size=2,max_size=8)"
