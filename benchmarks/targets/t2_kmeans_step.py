
TARGET_NAME = "kmeans_step"
TIER = 2
function_name = "kmeans_step"
import numpy as np
source = """
def kmeans_step(points, labels, k):
    dim = len(points[0])
    sums = [[0.0 for _ in range(dim)] for _ in range(k)]
    counts = [0 for _ in range(k)]
    for i in range(len(points)):
        c = labels[i]
        counts[c] = counts[c] + 1
        for d in range(dim):
            sums[c][d] = sums[c][d] + points[i][d]
    centers = []
    for c in range(k):
        if counts[c] > 0:
            centers.append([sums[c][d] / counts[c] for d in range(dim)])
        else:
            centers.append([0.0 for _ in range(dim)])
    return centers
"""
def _kmeans(points, labels, k):
    dim=len(points[0]); sums=[[0.0]*dim for _ in range(k)]; counts=[0]*k
    for i in range(len(points)):
        c=labels[i]; counts[c]+=1
        for d in range(dim): sums[c][d]+=points[i][d]
    out=[]
    for c in range(k):
        out.append([sums[c][d]/counts[c] for d in range(dim)] if counts[c]>0 else [0.0]*dim)
    return out
PTS=[[1.0,2.0],[1.5,1.8],[5.0,8.0],[8.0,8.0],[1.0,0.5],[9.0,11.0]]
LABELS=[0,0,1,1,0,1]
test_cases = [
    {"function": "kmeans_step", "args": [PTS, LABELS, 2], "expected": _kmeans(PTS, LABELS, 2), "comparison": "array_allclose"},
    {"function": "kmeans_step", "args": [[[1.0,2.0]], [0], 1], "expected": _kmeans([[1.0,2.0]], [0], 1), "comparison": "array_allclose"},
]
invariants = ['len(out) == x[2]']
input_strategy = "st.tuples(st.lists(st.lists(st.floats(min_value=0,max_value=10),min_size=2,max_size=2),min_size=3,max_size=6), st.lists(st.integers(min_value=0,max_value=1),min_size=3,max_size=6), st.integers(min_value=1,max_value=3))"
