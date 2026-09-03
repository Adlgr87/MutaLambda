
TARGET_NAME = "gradient_descent"
TIER = 3
function_name = "gradient_descent"
source = """
def gradient_descent(grad_fn, x0, lr=0.01, n_steps=100):
    x = x0
    for _ in range(n_steps):
        g = grad_fn(x)
        x = x - lr * g
    return x
"""
test_cases = [
    {"function": "gradient_descent", "args": [lambda x: 2*x, 10.0, 0.1, 50], "expected": 10.0*(0.8**50), "comparison": "float_close"},
    {"function": "gradient_descent", "args": [lambda x: x, 5.0, 0.1, 30], "expected": 5.0*(0.9**30), "comparison": "float_close"},
]
invariants = ['True']
input_strategy = "st.tuples(st.sampled_from([lambda x: 2*x, lambda x: x, lambda x: x*x]), st.floats(min_value=-5,max_value=5,allow_nan=False), st.floats(min_value=0.001,max_value=0.5), st.integers(min_value=10,max_value=200))"
