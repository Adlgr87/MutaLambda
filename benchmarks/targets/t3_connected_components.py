
TARGET_NAME = "connected_components"
TIER = 3
function_name = "connected_components"
source = """
def connected_components(n, edges):
    parent = list(range(n))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for a, b in edges:
        union(a, b)
    comp = {}
    for i in range(n):
        root = find(i)
        comp.setdefault(root, []).append(i)
    return [sorted(c) for c in comp.values()]
"""
test_cases = [
    {"function": "connected_components", "args": [5, [[0,1],[2,3]]], "expected": [[0,1],[2,3],[4]], "comparison": "equal"},
    {"function": "connected_components", "args": [3, [[0,1],[1,2],[2,0]]], "expected": [[0,1,2]], "comparison": "equal"},
    {"function": "connected_components", "args": [4, []], "expected": [[0],[1],[2],[3]], "comparison": "equal"},
]
invariants = ['sum(len(c) for c in out) == x[0]']
input_strategy = "st.tuples(st.integers(min_value=1,max_value=15), st.lists(st.tuples(st.integers(min_value=0,max_value=14), st.integers(min_value=0,max_value=14)), min_size=0, max_size=10))"
