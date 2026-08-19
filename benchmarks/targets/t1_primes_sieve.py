TARGET_NAME = "primes_sieve"
TIER = 1
function_name = "primes_up_to"
source = """def primes_up_to(n):
    if n < 2:
        return []
    sieve = [True] * (n + 1)
    sieve[0] = False
    sieve[1] = False
    for i in range(2, int(n ** 0.5) + 1):
        if sieve[i]:
            for j in range(i * i, n + 1, i):
                sieve[j] = False
    return [i for i in range(n + 1) if sieve[i]]
"""
test_cases = [
    {"function": "primes_up_to", "args": [10], "expected": [2, 3, 5, 7], "comparison": "equal"},
    {"function": "primes_up_to", "args": [2], "expected": [2], "comparison": "equal"},
    {"function": "primes_up_to", "args": [1], "expected": [], "comparison": "equal"},
    {"function": "primes_up_to", "args": [20], "expected": [2, 3, 5, 7, 11, 13, 17, 19], "comparison": "equal"},
]
invariants = ['all(p >= 2 for p in out)']
input_strategy = "st.integers(min_value=0, max_value=100)"
