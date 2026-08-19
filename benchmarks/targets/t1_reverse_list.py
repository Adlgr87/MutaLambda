TARGET_NAME = "reverse_list"
TIER = 1
function_name = "reverse_list"
source = """def reverse_list(xs):
    out = []
    for i in range(len(xs) - 1, -1, -1):
        out.append(xs[i])
    return out
"""
test_cases = [
    {"function": "reverse_list", "args": [[1, 2, 3]], "expected": [3, 2, 1], "comparison": "equal"},
    {"function": "reverse_list", "args": [[]], "expected": [], "comparison": "equal"},
    {"function": "reverse_list", "args": [[7]], "expected": [7], "comparison": "equal"},
]
invariants = ['list(out) == list(reversed(x))']
input_strategy = "st.lists(st.integers(min_value=-100, max_value=100), min_size=0, max_size=15)"
