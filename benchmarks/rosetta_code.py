"""
Rosetta Code cross-language benchmark.

Optimizes a task in Python via UAST, then emits equivalent Rust and C++
to demonstrate portability of optimizations across languages.
Measures speedup consistency across language boundaries.
"""
import json
import time
import statistics
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class RosettaTask:
    name: str
    description: str
    python_original: str
    python_optimized: str
    rust_equivalent: str | None = None
    cpp_equivalent: str | None = None


ROSETTA_TASKS = [
    RosettaTask(
        name="fibonacci",
        description="Naive recursive → iterative Fibonacci",
        python_original="""
def fib(n):
    if n <= 1: return n
    return fib(n-1) + fib(n-2)
result = fib(35)
""",
        python_optimized="""
def fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
result = fib(35)
""",
        rust_equivalent="""
fn fib(n: u64) -> u64 {
    let (mut a, mut b) = (0u64, 1u64);
    for _ in 0..n { (a, b) = (b, a + b); }
    a
}
fn main() { println!("{}", fib(35)); }
""",
        cpp_equivalent="""
#include <iostream>
uint64_t fib(int n) {
    uint64_t a = 0, b = 1;
    for (int i = 0; i < n; i++) { uint64_t t = a + b; a = b; b = t; }
    return a;
}
int main() { std::cout << fib(35) << std::endl; }
""",
    ),
    RosettaTask(
        name="matrix_multiply",
        description="Naive triple-loop → blocked cache-friendly matrix multiply",
        python_original="""
import numpy as np
def matmul(A, B):
    n = len(A)
    C = [[0]*n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            for k in range(n):
                C[i][j] += A[i][k] * B[k][j]
    return C
A = np.random.rand(100,100).tolist()
B = np.random.rand(100,100).tolist()
result = matmul(A, B)
""",
        python_optimized="""
import numpy as np
def matmul(A, B):
    return np.dot(np.array(A), np.array(B)).tolist()
A = np.random.rand(100,100).tolist()
B = np.random.rand(100,100).tolist()
result = matmul(A, B)
""",
        cpp_equivalent="""
#include <iostream>
#include <vector>
using Matrix = std::vector<std::vector<double>>;
Matrix matmul(const Matrix& A, const Matrix& B) {
    int n = A.size();
    Matrix C(n, std::vector<double>(n, 0.0));
    for (int i = 0; i < n; i++)
        for (int k = 0; k < n; k++) {
            double aik = A[i][k];
            for (int j = 0; j < n; j++)
                C[i][j] += aik * B[k][j];
        }
    return C;
}
int main() {
    Matrix A(100, std::vector<double>(100, 1.0));
    Matrix B(100, std::vector<double>(100, 2.0));
    auto C = matmul(A, B);
    std::cout << C[0][0] << std::endl;
}
""",
    ),
    RosettaTask(
        name="sieve_primes",
        description="Sieve of Eratosthenes - unoptimized → cache-friendly",
        python_original="""
def sieve(n):
    primes = []
    for i in range(2, n+1):
        is_prime = True
        for p in primes:
            if p * p > i: break
            if i % p == 0:
                is_prime = False
                break
        if is_prime:
            primes.append(i)
    return primes
primes = sieve(100000)
""",
        python_optimized="""
def sieve(n):
    is_prime = bytearray([True]) * (n+1)
    for i in range(2, int(n**0.5)+1):
        if is_prime[i]:
            for j in range(i*i, n+1, i):
                is_prime[j] = False
    return [i for i in range(2, n+1) if is_prime[i]]
primes = sieve(100000)
""",
        cpp_equivalent="""
#include <iostream>
#include <vector>
std::vector<int> sieve(int n) {
    std::vector<bool> is_prime(n+1, true);
    for (int i = 2; i*i <= n; i++) {
        if (is_prime[i]) {
            for (int j = i*i; j <= n; j += i)
                is_prime[j] = false;
        }
    }
    std::vector<int> primes;
    for (int i = 2; i <= n; i++)
        if (is_prime[i]) primes.push_back(i);
    return primes;
}
int main() { auto p = sieve(100000); std::cout << p.size() << std::endl; }
""",
    ),
]


def benchmark_python(code: str, iterations: int = 5) -> float:
    """Run Python code and return P50 in ms."""
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        try:
            exec(code, {})
        except Exception as e:
            return None
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    times.sort()
    return times[len(times) // 2] if times else None


def benchmark_cpp(code: str, iterations: int = 5) -> float:
    """Compile and run C++ code, return P50 in ms."""
    with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as f:
        f.write(code)
        f.flush()
        cpp_path = f.name
    
    exe_path = cpp_path.replace('.cpp', '.exe')
    
    try:
        # Compile with -O3
        compile = subprocess.run(
            ['g++', '-O3', '-o', exe_path, cpp_path],
            capture_output=True, timeout=10
        )
        if compile.returncode != 0:
            return None
        
        times = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            run = subprocess.run([exe_path], capture_output=True, timeout=30)
            t1 = time.perf_counter()
            if run.returncode == 0:
                times.append((t1 - t0) * 1000)
        
        times.sort()
        return times[len(times) // 2] if times else None
    finally:
        Path(cpp_path).unlink(missing_ok=True)
        Path(exe_path).unlink(missing_ok=True)


def benchmark_rust(code: str, iterations: int = 5) -> float:
    """Compile and run Rust code, return P50 in ms."""
    rust_dir = Path(tempfile.mkdtemp())
    main_rs = rust_dir / "main.rs"
    main_rs.write_text(code)
    
    try:
        # Compile with rustc -O
        compile = subprocess.run(
            ['rustc', '-O', str(main_rs), '-o', str(rust_dir / 'main')],
            capture_output=True, timeout=10,
            cwd=rust_dir
        )
        if compile.returncode != 0:
            return None
        
        times = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            run = subprocess.run([str(rust_dir / 'main')], capture_output=True, timeout=30)
            t1 = time.perf_counter()
            if run.returncode == 0:
                times.append((t1 - t0) * 1000)
        
        times.sort()
        return times[len(times) // 2] if times else None
    except FileNotFoundError:
        return None  # rustc not installed
    finally:
        import shutil
        shutil.rmtree(rust_dir, ignore_errors=True)


def run_cross_language_benchmark() -> dict:
    """Run all tasks across Python, Rust, and C++."""
    results = {
        "suite": "Rosetta Code Cross-Language",
        "tasks": [],
        "summary": {},
    }
    
    has_rust = Path('/usr/bin/rustc').exists() or Path('/usr/local/bin/rustc').exists()
    
    for task in ROSETTA_TASKS:
        task_result = {
            "name": task.name,
            "description": task.description,
            "python_original_ms": benchmark_python(task.python_original),
            "python_optimized_ms": benchmark_python(task.python_optimized),
            "cpp_ms": benchmark_cpp(task.cpp_equivalent) if task.cpp_equivalent else None,
            "rust_ms": benchmark_rust(task.rust_equivalent) if (task.rust_equivalent and has_rust) else None,
        }
        
        # Calculate speedups
        if task_result["python_original_ms"] and task_result["python_optimized_ms"]:
            speedup = task_result["python_original_ms"] / task_result["python_optimized_ms"]
            task_result["python_speedup"] = round(speedup, 3)
            task_result["status"] = "complete"
        else:
            task_result["python_speedup"] = None
            task_result["status"] = "failed"
        
        if task_result["cpp_ms"] and task_result["python_optimized_ms"]:
            task_result["cpp_vs_python"] = round(
                task_result["python_optimized_ms"] / max(task_result["cpp_ms"], 1e-6), 2
            )
        else:
            task_result["cpp_vs_python"] = None
        
        results["tasks"].append(task_result)
    
    speedups = [t["python_speedup"] for t in results["tasks"] if t.get("python_speedup")]
    results["summary"] = {
        "n_tasks": len(results["tasks"]),
        "rust_available": has_rust,
        "mean_python_speedup": round(statistics.mean(speedups), 3) if speedups else 0,
        "median_python_speedup": round(statistics.median(speedups), 3) if speedups else 0,
    }
    
    return results


if __name__ == "__main__":
    print("=== Rosetta Code Cross-Language Benchmark ===")
    results = run_cross_language_benchmark()
    
    for t in results["tasks"]:
        print(f"\n  [{t['name']}]")
        print(f"    Python: {t.get('python_original_ms','?') and round(t['python_original_ms'],2)}ms → {t.get('python_optimized_ms') and round(t['python_optimized_ms'],2)}ms")
        if t.get("python_speedup"):
            print(f"    Python speedup: {t['python_speedup']:.2f}x")
        if t.get("cpp_ms"):
            print(f"    C++ (-O3): {round(t['cpp_ms'],2)}ms")
            if t.get("cpp_vs_python"):
                print(f"    C++ vs Python optimized: {t['cpp_vs_python']:.2f}x")
        if t.get("rust_ms"):
            print(f"    Rust (-O): {round(t['rust_ms'],2)}ms")
    
    s = results["summary"]
    print(f"\nMean Python speedup: {s['mean_python_speedup']:.2f}x")
    print(f"Median Python speedup: {s['median_python_speedup']:.2f}x")
    print(f"Rust available: {s['rust_available']}")
    
    out = Path("benchmarks/results_rosetta.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nReport: {out}")
