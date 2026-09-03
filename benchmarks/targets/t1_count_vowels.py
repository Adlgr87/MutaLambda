TARGET_NAME = "count_vowels"
TIER = 1
function_name = "count_vowels"
source = """def count_vowels(s):
    count = 0
    vowels = "aeiouAEIOU"
    for ch in s:
        if ch in vowels:
            count = count + 1
    return count
"""
test_cases = [
    {"function": "count_vowels", "args": ["hello world"], "expected": 3, "comparison": "equal"},
    {"function": "count_vowels", "args": ["xyz"], "expected": 0, "comparison": "equal"},
    {"function": "count_vowels", "args": ["AEIOU"], "expected": 5, "comparison": "equal"},
]
invariants = ['0 <= out <= len(x)']
input_strategy = "st.text(alphabet='abcdefghijklmnopqrstuvwxyz ', min_size=0, max_size=30)"
