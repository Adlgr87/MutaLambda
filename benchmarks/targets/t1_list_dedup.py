TARGET_NAME = "list_dedup"
TIER = 1
function_name = "dedup"
source = """def dedup(items):
    seen = []
    result = []
    for item in items:
        if item not in seen:
            seen.append(item)
            result.append(item)
    return result
"""
test_cases = [
    {"function": "dedup", "args": [[1, 2, 2, 3, 1, 4]], "expected": [1, 2, 3, 4], "comparison": "equal"},
    {"function": "dedup", "args": [[]], "expected": [], "comparison": "equal"},
    {"function": "dedup", "args": [[5, 5, 5]], "expected": [5], "comparison": "equal"},
]
invariants = ['len(set(out)) == len(out)']
input_strategy = "st.lists(st.integers(min_value=0, max_value=5), min_size=0, max_size=10)"
