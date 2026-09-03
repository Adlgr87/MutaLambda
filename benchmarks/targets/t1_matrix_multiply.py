TARGET_NAME = "matrix_multiply_naive"
TIER = 1
function_name = "matrix_multiply"
import numpy as np
source = """def matrix_multiply(a, b):
    rows = len(a)
    cols = len(b[0])
    inner = len(b)
    result = [[0.0 for _ in range(cols)] for _ in range(rows)]
    for i in range(rows):
        for j in range(cols):
            s = 0.0
            for k in range(inner):
                s = s + a[i][k] * b[k][j]
            result[i][j] = s
    return result
"""
A = [[1, 2, 3], [4, 5, 6]]
B = [[7, 8], [9, 10], [11, 12]]
EXPECTED = [[58, 64], [139, 154]]
test_cases = [
    {"function": "matrix_multiply", "args": [A, B], "expected": EXPECTED, "comparison": "equal"},
    {"function": "matrix_multiply", "args": [[[1, 0], [0, 1]], [[1, 0], [0, 1]]], "expected": [[1, 0], [0, 1]], "comparison": "equal"},
]
invariants = ['len(out) == len(x[0]) and (len(out[0]) == len(x[1][0]) if out else True)']
input_strategy = "st.sampled_from([(1, 1, 1), (2, 2, 2), (2, 3, 2), (3, 2, 3)]).flatmap(lambda dims: st.tuples(st.lists(st.lists(st.integers(min_value=0, max_value=5), min_size=dims[1], max_size=dims[1]), min_size=dims[0], max_size=dims[0]), st.lists(st.lists(st.integers(min_value=0, max_value=5), min_size=dims[2], max_size=dims[2]), min_size=dims[1], max_size=dims[1])))"

def arg_factory():
    import random
    m, k, n = 2, 2, 2
    a = [[random.randint(0, 5) for _ in range(k)] for _ in range(m)]
    b = [[random.randint(0, 5) for _ in range(n)] for _ in range(k)]
    return [a, b]
