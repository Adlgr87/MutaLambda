TARGET_NAME = "pascals_triangle"
TIER = 1
function_name = "pascals_triangle"
source = """def pascals_triangle(rows):
    triangle = []
    for i in range(rows):
        row = [1]
        if triangle:
            prev = triangle[-1]
            for j in range(len(prev) - 1):
                row.append(prev[j] + prev[j + 1])
            row.append(1)
        triangle.append(row)
    return triangle
"""
test_cases = [
    {"function": "pascals_triangle", "args": [4], "expected": [[1], [1, 1], [1, 2, 1], [1, 3, 3, 1]], "comparison": "equal"},
    {"function": "pascals_triangle", "args": [1], "expected": [[1]], "comparison": "equal"},
]
invariants = ['out[0] == [1] if out else True']
input_strategy = "st.integers(min_value=0, max_value=12)"
