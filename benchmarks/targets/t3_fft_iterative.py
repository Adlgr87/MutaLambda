
TARGET_NAME = "fft_iterative"
TIER = 3
function_name = "fft_iterative"
import math
source = """
import math
def fft_iterative(real, imag):
    n = len(real)
    if n == 0:
        return [], []
    levels = n.bit_length() - 1
    if (1 << levels) != n:
        raise ValueError("length must be a power of 2")
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            real[i], real[j] = real[j], real[i]
            imag[i], imag[j] = imag[j], imag[i]
    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wlen_r = math.cos(ang)
        wlen_i = math.sin(ang)
        for i in range(0, n, length):
            wr, wi = 1.0, 0.0
            for k in range(length // 2):
                ur, ui = real[i + k], imag[i + k]
                vr = real[i + k + length // 2] * wr - imag[i + k + length // 2] * wi
                vi = real[i + k + length // 2] * wi + imag[i + k + length // 2] * wr
                real[i + k] = ur + vr
                imag[i + k] = ui + vi
                real[i + k + length // 2] = ur - vr
                imag[i + k + length // 2] = ui - vi
                wr, wi = wr * wlen_r - wi * wlen_i, wr * wlen_i + wi * wlen_r
        length = length * 2
    return real, imag
"""
import cmath
def _ref_fft(real, imag):
    n=len(real); vals=[complex(r,i) for r,i in zip(real,imag)]
    def _fft(a):
        n=len(a)
        if n<=1: return a
        even=_fft(a[::2]); odd=_fft(a[1::2])
        w=cmath.exp(-2j*cmath.pi/n)
        return [even[k]+w**k*odd[k] for k in range(n//2)]+[even[k]-w**k*odd[k] for k in range(n//2)]
    out=_fft(vals)
    return [x.real for x in out], [x.imag for x in out]
R=[0.0,1.0,2.0,3.0]; I=[0.0,0.0,0.0,0.0]
rr,ii=_ref_fft(list(R),list(I))
test_cases = [
    {"function": "fft_iterative", "args": [list(R), list(I)], "expected": (rr, ii), "comparison": "array_allclose"},
]
invariants = ['len(out[0]) == len(x[0]) and len(out[1]) == len(x[0])']
input_strategy = "st.sampled_from([1, 2, 4, 8]).flatmap(lambda n: st.tuples(st.lists(st.floats(min_value=-5,max_value=5,allow_nan=False), min_size=n, max_size=n), st.lists(st.floats(min_value=-5,max_value=5,allow_nan=False), min_size=n, max_size=n)))"

def arg_factory():
    import random
    n = 4
    vals = [random.uniform(-5, 5) for _ in range(n)]
    return [vals, [0.0]*n]
