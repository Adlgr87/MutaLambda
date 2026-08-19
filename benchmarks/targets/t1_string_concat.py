TARGET_NAME = "string_concat_naive"
TIER = 1
function_name = "join_words"
source = """def join_words(words):
    result = ""
    for w in words:
        result = result + " " + w
    return result.lstrip()
"""
test_cases = [
    {"function": "join_words", "args": [["hello", "world"]], "expected": "hello world", "comparison": "equal"},
    {"function": "join_words", "args": [[]], "expected": "", "comparison": "equal"},
    {"function": "join_words", "args": [["a", "b", "c", "d"]], "expected": "a b c d", "comparison": "equal"},
]
invariants = ['sorted(out.replace(" ", "")) == sorted("".join(x).replace(" ", ""))']
input_strategy = "st.lists(st.text(alphabet='abc ', min_size=1, max_size=3), min_size=0, max_size=8)"
