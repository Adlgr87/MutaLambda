
TARGET_NAME = "euclidean_distances"
TIER = 2
function_name = "euclidean_distances"
import numpy as np
source = """
import numpy as np
def euclidean_distances(a, b):
    n = len(a)
    m = len(b)
    out = np.zeros((n, m))
    for i in range(n):
        for j in range(m):
            s = 0.0
            for d in range(len(a[i])):
                diff = a[i][d] - b[j][d]
                s = s + diff * diff
            out[i][j] = s ** 0.5
    return out
"""
test_cases = [
    {"function": "euclidean_distances", "args": [[np.array([0.0,0.0]), np.array([3.0,4.0])], [np.array([0.0,0.0]), np.array([6.0,8.0])]], "expected": np.array([[0.0,10.0],[5.0,5.0]]), "comparison": "array_allclose"},
    {"function": "euclidean_distances", "args": [[np.array([1.0,2.0])], [np.array([1.0,2.0])]], "expected": np.array([[0.0]]), "comparison": "array_allclose"},
]
invariants = ['True']
input_strategy = "st.tuples(st.lists(st.lists(st.floats(min_value=-10,max_value=10,allow_nan=False),min_size=2,max_size=2),min_size=1,max_size=4), st.lists(st.lists(st.floats(min_value=-10,max_value=10,allow_nan=False),min_size=2,max_size=2),min_size=1,max_size=4))"
