
TARGET_NAME = "newton_raphson"
TIER = 4
function_name = "newton_raphson"
source = """
def newton_raphson(fn, deriv, x0, max_iter=100, tol=1e-10):
    x = x0
    for _ in range(max_iter):
        fx = fn(x)
        if abs(fx) < tol:
            return x
        dfx = deriv(x)
        if abs(dfx) < 1e-15:
            raise ValueError("zero derivative")
        x = x - fx / dfx
    return x
"""
test_cases = [
    {"function": "newton_raphson", "args": [lambda x: x*x - 2, lambda x: 2*x, 1.0, 100, 1e-10], "expected": 2**0.5, "comparison": "float_close"},
    {"function": "newton_raphson", "args": [lambda x: x**3 - x - 2, lambda x: 3*x**2 - 1, 1.5, 100, 1e-10], "expected": 1.5213797068045676, "comparison": "float_close"},
]
invariants = ['True']
input_strategy = "st.tuples(st.sampled_from([lambda x: x*x-2, lambda x: x**3-x-2]), st.sampled_from([lambda x: 2*x, lambda x: 3*x**2-1]), st.floats(min_value=-3,max_value=3,allow_nan=False), st.integers(min_value=20,max_value=200), st.floats(min_value=1e-15,max_value=1e-5))"
