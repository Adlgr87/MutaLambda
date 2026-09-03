
TARGET_NAME = "montecarlo_pi"
TIER = 2
function_name = "montecarlo_pi"
import random
source = """
import random
def montecarlo_pi(n, seed=0):
    rng = random.Random(seed)
    inside = 0
    for _ in range(n):
        x = rng.random()
        y = rng.random()
        if x*x + y*y <= 1.0:
            inside = inside + 1
    return (4.0 * inside) / n
"""
def _ref(n, seed=0):
    r=random.Random(seed); ins=0
    for _ in range(n):
        x=r.random(); y=r.random()
        if x*x+y*y<=1.0: ins+=1
    return (4.0*ins)/n
test_cases = [
    {"function": "montecarlo_pi", "args": [1000, 0], "expected": _ref(1000,0), "comparison": "float_close"},
    {"function": "montecarlo_pi", "args": [1, 42], "expected": _ref(1,42), "comparison": "float_close"},
]
invariants = ['0.0 <= out <= 4.0']
input_strategy = "st.tuples(st.integers(min_value=1,max_value=2000), st.integers(min_value=0,max_value=100))"
