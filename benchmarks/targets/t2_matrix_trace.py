
TARGET_NAME = "matrix_trace"
TIER = 2
function_name = "matrix_trace"
source = """
def matrix_trace(mat):
    total = 0.0
    for i in range(len(mat)):
        total = total + mat[i][i]
    return total
"""
test_cases = [
    {"function": "matrix_trace", "args": [[[1, 2], [3, 4]]], "expected": 5.0, "comparison": "float_close"},
    {"function": "matrix_trace", "args": [[[5]]], "expected": 5.0, "comparison": "float_close"},
    {"function": "matrix_trace", "args": [[[0, 0, 0], [0, 0, 0], [0, 0, 0]]], "expected": 0.0, "comparison": "float_close"},
]
invariants = ['True']
input_strategy = "st.lists(st.lists(st.floats(min_value=-10,max_value=10,allow_nan=False),min_size=1,max_size=5),min_size=1,max_size=5)"
