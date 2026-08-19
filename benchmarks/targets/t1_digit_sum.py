\
TARGET_NAME = "digit_sum"
TIER = 1
function_name = "digit_sum"
source = """def digit_sum(n):
    s = 0
    n = abs(n)
    while n > 0:
        s = s + (n % 10)
        n = n // 10
    return s
"""
test_cases = [
    {"function": "digit_sum", "args": [12345], "expected": 15, "comparison": "equal"},
    {"function": "digit_sum", "args": [0], "expected": 0, "comparison": "equal"},
    {"function": "digit_sum", "args": [-567], "expected": 18, "comparison": "equal"},
]
invariants = ['out == sum(int(d) for d in str(abs(x))) if x != 0 else out == 0']
input_strategy = "st.integers(min_value=-1000000, max_value=1000000)"
