TARGET_NAME = "nested_loops_sum"
TIER = 1
function_name = "nested_sum"
source = """def nested_sum(matrix):
    total = 0
    for row in matrix:
        for val in row:
            total = total + val
    return total
"""
test_cases = [
    {"function": "nested_sum", "args": [[[1, 2], [3, 4]]], "expected": 10, "comparison": "equal"},
    {"function": "nested_sum", "args": [[[]]], "expected": 0, "comparison": "equal"},
    {"function": "nested_sum", "args": [[[0, -1], [-2, 3]]], "expected": 0, "comparison": "equal"},
]
invariants = ['out == sum(sum(r) for r in x)']
input_strategy = "st.lists(st.lists(st.integers(min_value=-10, max_value=10), min_size=0, max_size=5), min_size=1, max_size=5)"
