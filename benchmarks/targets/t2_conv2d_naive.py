
TARGET_NAME = "conv2d_naive"
TIER = 2
function_name = "conv2d"
source = """
def conv2d(image, kernel):
    kh = len(kernel)
    kw = len(kernel[0])
    ih = len(image)
    iw = len(image[0])
    oh = ih - kh + 1
    ow = iw - kw + 1
    out = [[0.0 for _ in range(ow)] for _ in range(oh)]
    for i in range(oh):
        for j in range(ow):
            s = 0.0
            for ki in range(kh):
                for kj in range(kw):
                    s = s + image[i+ki][j+kj] * kernel[ki][kj]
            out[i][j] = s
    return out
"""
def _conv(image, kernel):
    kh=len(kernel); kw=len(kernel[0]); ih=len(image); iw=len(image[0])
    oh=ih-kh+1; ow=iw-kw+1
    out=[[0.0]*ow for _ in range(oh)]
    for i in range(oh):
        for j in range(ow):
            s=0.0
            for ki in range(kh):
                for kj in range(kw): s+=image[i+ki][j+kj]*kernel[ki][kj]
            out[i][j]=s
    return out
IMG=[[1.0,2.0,3.0],[4.0,5.0,6.0],[7.0,8.0,9.0]]
KER=[[1.0,0.0],[-1.0,1.0]]
test_cases = [
    {"function": "conv2d", "args": [IMG, KER], "expected": _conv(IMG, KER), "comparison": "array_allclose"},
    {"function": "conv2d", "args": [[[1.0]],[[1.0]]], "expected": [[1.0]], "comparison": "array_allclose"},
]
invariants = ['len(out) == len(x[0]) - len(x[1]) + 1']
input_strategy = "st.tuples(st.lists(st.lists(st.floats(min_value=-5,max_value=5),min_size=3,max_size=4),min_size=3,max_size=4), st.lists(st.lists(st.floats(min_value=-2,max_value=2),min_size=2,max_size=2),min_size=2,max_size=2))"
