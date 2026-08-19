
TARGET_NAME = "bilinear_interpolate"
TIER = 4
function_name = "bilinear_interpolate"
source = """
def bilinear_interpolate(grid, x, y):
    h = len(grid)
    w = len(grid[0])
    x0 = int(x)
    y0 = int(y)
    x1 = x0 + 1
    y1 = y0 + 1
    if x0 < 0 or y0 < 0 or x1 >= w or y1 >= h:
        raise ValueError("out of bounds")
    q11 = grid[y0][x0]
    q21 = grid[y0][x1]
    q12 = grid[y1][x0]
    q22 = grid[y1][x1]
    w1 = (x1 - x) * (y1 - y)
    w2 = (x - x0) * (y1 - y)
    w3 = (x1 - x) * (y - y0)
    w4 = (x - x0) * (y - y0)
    return q11*w1 + q21*w2 + q12*w3 + q22*w4
"""
import numpy as np
def _ref(grid, x, y):
    g=np.asarray(grid,dtype=float); x0=int(x); y0=int(y); x1=x0+1; y1=y0+1
    if x0<0 or y0<0 or x1>=g.shape[1] or y1>=g.shape[0]: raise ValueError("out of bounds")
    q11=g[y0,x0]; q21=g[y0,x1]; q12=g[y1,x0]; q22=g[y1,x1]
    w1=(x1-x)*(y1-y); w2=(x-x0)*(y1-y); w3=(x1-x)*(y-y0); w4=(x-x0)*(y-y0)
    return q11*w1+q21*w2+q12*w3+q22*w4
GRID=[[0.0,10.0,20.0],[30.0,40.0,50.0],[60.0,70.0,80.0]]
test_cases = [
    {"function": "bilinear_interpolate", "args": [GRID, 1.5, 1.5], "expected": _ref(GRID,1.5,1.5), "comparison": "float_close"},
    {"function": "bilinear_interpolate", "args": [GRID, 0.0, 0.0], "expected": _ref(GRID,0.0,0.0), "comparison": "float_close"},
]
invariants = ['True']
input_strategy = "st.tuples(st.lists(st.lists(st.floats(min_value=0,max_value=100,allow_nan=False),min_size=3,max_size=3),min_size=3,max_size=3), st.floats(min_value=0,max_value=1.999999,allow_nan=False), st.floats(min_value=0,max_value=1.999999,allow_nan=False))"
