
TARGET_NAME = "confusion_matrix"
TIER = 3
function_name = "confusion_matrix"
source = """
def confusion_matrix(y_true, y_pred, labels):
    n = len(labels)
    idx = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * n for _ in range(n)]
    for t, p in zip(y_true, y_pred):
        ti, pi = idx[t], idx[p]
        matrix[ti][pi] = matrix[ti][pi] + 1
    return matrix
"""
def _ref(yt, yp, labels):
    n=len(labels); idx={l:i for i,l in enumerate(labels)}; m=[[0]*n for _ in range(n)]
    for t,p in zip(yt,yp): m[idx[t]][idx[p]]+=1
    return m
test_cases = [
    {"function": "confusion_matrix", "args": [[0,1,0,1,0], [0,0,0,1,1], [0,1]], "expected": _ref([0,1,0,1,0],[0,0,0,1,1],[0,1]), "comparison": "equal"},
    {"function": "confusion_matrix", "args": ["aabc", "aacb", ["a","b","c"]], "expected": _ref("aabc","aacb",["a","b","c"]), "comparison": "equal"},
]
invariants = ['sum(sum(r) for r in out) <= len(x[0])']
input_strategy = "st.tuples(st.lists(st.sampled_from([0,1,2]), min_size=5, max_size=20), st.lists(st.sampled_from([0,1,2]), min_size=5, max_size=20), st.lists(st.sampled_from([0,1,2]), min_size=2, max_size=3, unique=True))"
