
TARGET_NAME = "matrix_inverse_gauss"
TIER = 3
function_name = "matrix_inverse"
source = """
def matrix_inverse(mat):
    n = len(mat)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(mat)]
    for col in range(n):
        pivot = aug[col][col]
        if abs(pivot) < 1e-12:
            raise ValueError("singular")
        for j in range(2 * n):
            aug[col][j] = aug[col][j] / pivot
        for r in range(n):
            if r != col:
                factor = aug[r][col]
                for j in range(2 * n):
                    aug[r][j] = aug[r][j] - factor * aug[col][j]
    return [[aug[i][n + j] for j in range(n)] for i in range(n)]
"""
def _inverse(mat):
    n=len(mat)
    aug=[row[:]+[1.0 if i==j else 0.0 for j in range(n)] for i,row in enumerate(mat)]
    for col in range(n):
        p=aug[col][col]
        if abs(p)<1e-12: raise ValueError("singular")
        for j in range(2*n): aug[col][j]/=p
        for r in range(n):
            if r!=col:
                f=aug[r][col]
                for j in range(2*n): aug[r][j]-=f*aug[col][j]
    return [[aug[i][n+j] for j in range(n)] for i in range(n)]
M=[[4.0,7.0],[2.0,6.0]]
M2=[[2.0,1.0,1.0],[1.0,3.0,2.0],[1.0,0.0,0.0]]
test_cases = [
    {"function": "matrix_inverse", "args": [M], "expected": _inverse(M), "comparison": "array_allclose"},
    {"function": "matrix_inverse", "args": [M2], "expected": _inverse(M2), "comparison": "array_allclose"},
]
invariants = ['True']
input_strategy = "st.lists(st.lists(st.floats(min_value=-5,max_value=5,allow_nan=False),min_size=2,max_size=3),min_size=2,max_size=3)"
