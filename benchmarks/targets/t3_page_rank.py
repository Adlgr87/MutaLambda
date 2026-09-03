TARGET_NAME = "pagerank_iterative"
TIER = 3
function_name = "pagerank_iterative"
import numpy as np
source = """
import numpy as np
def pagerank_iterative(adjacency, damping=0.85, max_iter=100, tol=1e-9):
    n = len(adjacency)
    rank = np.ones(n) / n
    out_degree = np.sum(adjacency, axis=1)
    for _ in range(max_iter):
        dangling_sum = 0.0
        for j in range(n):
            if out_degree[j] == 0:
                dangling_sum += rank[j]
        new_rank = np.zeros(n)
        for i in range(n):
            for j in range(n):
                if adjacency[j][i] > 0:
                    new_rank[i] += damping * rank[j] / out_degree[j]
            new_rank[i] += (1.0 - damping) / n
            new_rank[i] += damping * dangling_sum / n
        if np.max(np.abs(new_rank - rank)) < tol:
            break
        rank = new_rank
    return rank
"""
def _ref(adjacency, damping=0.85, max_iter=100, tol=1e-9):
    import numpy as np
    adj = np.asarray(adjacency, dtype=float)
    n = adj.shape[0]; rank = np.ones(n)/n; outdeg = np.sum(adj, axis=1)
    for _ in range(max_iter):
        dsum = sum(rank[j] for j in range(n) if outdeg[j]==0)
        nr = np.zeros(n)
        for i in range(n):
            for j in range(n):
                if adj[j][i] > 0:
                    nr[i] += damping*rank[j]/outdeg[j]
            nr[i] += (1.0-damping)/n + damping*dsum/n
        if np.max(np.abs(nr-rank)) < tol: break
        rank = nr
    return rank
ADJ = [[0,1,0,0],[0,0,1,0],[0,0,0,1],[1,0,0,0]]
test_cases = [
    {"function": "pagerank_iterative", "args": [ADJ, 0.85, 100, 1e-9], "expected": _ref(ADJ), "comparison": "array_allclose"},
    {"function": "pagerank_iterative", "args": [np.eye(4).tolist(), 0.85, 50, 1e-9], "expected": _ref(np.eye(4).tolist()), "comparison": "array_allclose"},
]
invariants = ['abs(sum(float(v) for v in (out.tolist() if hasattr(out, "tolist") else out)) - 1.0) < 1e-6']
input_strategy = "st.integers(min_value=3, max_value=6).flatmap(lambda n: st.tuples(st.lists(st.lists(st.integers(min_value=0, max_value=1), min_size=n, max_size=n), min_size=n, max_size=n), st.floats(min_value=0.5, max_value=0.9), st.integers(min_value=50, max_value=100), st.floats(min_value=1e-12, max_value=1e-6)))"
