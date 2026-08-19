
TARGET_NAME = "look_and_say"
TIER = 2
function_name = "look_and_say"
source = """
def look_and_say(s):
    result = ""
    i = 0
    while i < len(s):
        count = 1
        while i + count < len(s) and s[i + count] == s[i]:
            count = count + 1
        result = result + str(count) + s[i]
        i = i + count
    return result
"""
test_cases = [
    {"function": "look_and_say", "args": ["1"], "expected": "11", "comparison": "equal"},
    {"function": "look_and_say", "args": ["11"], "expected": "21", "comparison": "equal"},
    {"function": "look_and_say", "args": ["21"], "expected": "1211", "comparison": "equal"},
    {"function": "look_and_say", "args": ["1211"], "expected": "111221", "comparison": "equal"},
]
invariants = ['len(out) >= 1']
input_strategy = "st.text(alphabet='1234',min_size=1,max_size=8)"
