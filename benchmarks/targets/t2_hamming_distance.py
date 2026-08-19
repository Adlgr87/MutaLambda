
TARGET_NAME = "hamming_distance"
TIER = 2
function_name = "hamming_distance"
source = """
def hamming_distance(a, b):
    total = 0
    for i in range(len(a)):
        if a[i] != b[i]:
            total = total + 1
    return total
"""
test_cases = [
    {"function": "hamming_distance", "args": ["karolin", "kathrin"], "expected": 3, "comparison": "equal"},
    {"function": "hamming_distance", "args": ["abc", "abc"], "expected": 0, "comparison": "equal"},
    {"function": "hamming_distance", "args": ["1011101", "1001001"], "expected": 2, "comparison": "equal"},
]
invariants = ['0 <= out <= len(x[0])']
input_strategy = "st.tuples(st.text(alphabet='01',min_size=5,max_size=10), st.text(alphabet='01',min_size=5,max_size=10))"
