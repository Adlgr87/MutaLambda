
TARGET_NAME = "radix_sort"
TIER = 2
function_name = "radix_sort"
source = """
def radix_sort(arr):
    if len(arr) == 0:
        return []
    max_val = max(arr)
    exp = 1
    output = list(arr)
    while max_val // exp > 0:
        output = _counting_sort_by_digit(output, exp)
        exp = exp * 10
    return output
def _counting_sort_by_digit(arr, exp):
    n = len(arr)
    output = [0] * n
    count = [0] * 10
    for num in arr:
        digit = (num // exp) % 10
        count[digit] = count[digit] + 1
    for i in range(1, 10):
        count[i] = count[i] + count[i - 1]
    for i in range(n - 1, -1, -1):
        digit = (arr[i] // exp) % 10
        output[count[digit] - 1] = arr[i]
        count[digit] = count[digit] - 1
    return output
"""
test_cases = [
    {"function": "radix_sort", "args": [[170, 45, 75, 90, 802, 24, 2, 66]], "expected": [2, 24, 45, 66, 75, 90, 170, 802], "comparison": "equal"},
    {"function": "radix_sort", "args": [[]], "expected": [], "comparison": "equal"},
    {"function": "radix_sort", "args": [[5]], "expected": [5], "comparison": "equal"},
]
invariants = ['out == sorted(x)']
input_strategy = "st.lists(st.integers(min_value=0,max_value=9999),min_size=0,max_size=30)"
