TARGET_NAME = "fibonacci_naive"
TIER = 1
function_name = "fibonacci"
source = """def fibonacci(n):
    if n <= 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
"""
test_cases = [
    {"function": "fibonacci", "args": [0], "expected": 0, "comparison": "equal"},
    {"function": "fibonacci", "args": [1], "expected": 1, "comparison": "equal"},
    {"function": "fibonacci", "args": [10], "expected": 55, "comparison": "equal"},
    {"function": "fibonacci", "args": [20], "expected": 6765, "comparison": "equal"},
]
invariants = ['out >= 0']
input_strategy = "st.integers(min_value=0, max_value=40)"
