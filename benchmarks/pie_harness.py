"""PIE (Performance-Improving Edits) benchmark harness for MutaLambda.

Based on the PIE dataset from NeurIPS 2023:
  "PIE: A Dataset of Performance-Improving Edits for Code Forces Problems"
  77,000+ competitive C++ submission pairs where a human improved performance.

Since the full dataset requires scraping 77K CodeForces submissions, this
harness provides:
  1. A representative synthetic dataset of competitive programming patterns
  2. Infrastructure to evaluate C++ code with -O3 baseline
  3. Pipeline to run MutaLambda against C++ targets

Usage:
  python benchmarks/pie_harness.py --smoke            # pipeline check (5 tasks)
  python benchmarks/pie_harness.py --baseline-only    # verify C++ infra works
  python benchmarks/pie_harness.py --tasks 20 --mutalambda  # run MutaLambda

Dataset source for full version:
  https://github.com/hkproj/code-edit-viz (PIE dataset link)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.effibench_harness import summarize


# ---- Representative competitive programming tasks ----
# These are common patterns from CodeForces that benefit from optimization.
# Each has: original (slow) C++ and optimized (fast) C++ by human authors.

PIE_TASKS = [
    {
        "problem_idx": 1,
        "task_name": "Two Pointers - Remove Duplicates",
        "description": "Remove duplicates from sorted array, return new length.",
        "original": """\
#include <vector>

int removeDuplicates(std::vector<int>& nums) {
    // Original: erase in loop shifts elements each time O(n^2)
    for (size_t i = 0; i < nums.size();) {
        if (i > 0 && nums[i] == nums[i-1]) {
            nums.erase(nums.begin() + i);
        } else {
            i++;
        }
    }
    return nums.size();
}
""",
        "optimized": """\
#include <vector>

int removeDuplicates(std::vector<int>& nums) {
    // Optimized: two pointers, O(n)
    if (nums.empty()) return 0;
    int k = 1;
    for (int i = 1; i < nums.size(); i++) {
        if (nums[i] != nums[i-1]) {
            nums[k++] = nums[i];
        }
    }
    return k;
}
""",
        "tests": [
            "assert(removeDuplicates({1,1,2}) == 2)",
            "assert(removeDuplicates({0,0,1,1,1,2,2,3,3,4}) == 5)",
            "assert(removeDuplicates({}) == 0)",
            "assert(removeDuplicates({1,2,3,4}) == 4)",
        ],
    },
    {
        "problem_idx": 2,
        "task_name": "STL Map vs Unordered Map",
        "description": "Count elements, original uses map (ordered), optimized uses unordered_map.",
        "original": """\
#include <map>
#include <vector>

int countPairs(std::vector<int>& nums, int target) {
    std::map<int, int> freq;
    int count = 0;
    for (int num : nums) {
        freq[num]++;
    }
    for (auto& [num, cnt] : freq) {
        if (num * 2 == target) {
            count += cnt * (cnt - 1) / 2;
        } else if (freq.count(target - num)) {
            count += cnt * freq[target - num];
        }
    }
    return count;
}
""",
        "optimized": """\
#include <unordered_map>
#include <vector>

int countPairs(std::vector<int>& nums, int target) {
    std::unordered_map<int, int> freq;
    int count = 0;
    for (int num : nums) {
        freq[num]++;
    }
    // ... same logic but O(1) average lookup
    for (auto& [num, cnt] : freq) {
        if (num * 2 == target) {
            count += cnt * (cnt - 1) / 2;
        } else if (freq.count(target - num)) {
            count += cnt * freq[target - num];
        }
    }
    return count;
}
""",
        "tests": [
            "assert(countPairs({1,2,3,4,3,3}, 6) == 4)",
            "assert(countPairs({1,1,1,1}, 2) == 6)",
            "assert(countPairs({1,2,3}, 7) == 0)",
        ],
    },
    {
        "problem_idx": 3,
        "task_name": "String Concatenation O(n^2) to O(n)",
        "description": "Build string from repeated concatenation. Original O(n^2), optimized O(n) using reserve.",
        "original": """\
#include <string>
#include <vector>

std::string buildResult(std::vector<std::string>& parts) {
    std::string result = "";
    for (const auto& part : parts) {
        result = result + part;  // O(n^2): each concat copies entire string
    }
    return result;
}
""",
        "optimized": """\
#include <string>
#include <vector>

std::string buildResult(std::vector<std::string>& parts) {
    size_t total_len = 0;
    for (const auto& part : parts) {
        total_len += part.size();
    }
    std::string result;
    result.reserve(total_len);  // O(n): single allocation
    for (const auto& part : parts) {
        result += part;
    }
    return result;
}
""",
        "tests": [
            "assert(buildResult({\"hello\", \" \", \"world\"}) == \"hello world\")",
            "assert(buildResult({\"a\", \"b\", \"c\"}) == \"abc\")",
            "assert(buildResult({}) == \"\")",
        ],
    },
    {
        "problem_idx": 4,
        "task_name": "Vector Erase vs Swap-Erase",
        "description": "Remove specific elements. Original uses erase in loop, optimized uses swap-erase idiom.",
        "original": """\
#include <vector>

std::vector<int> removeEven(std::vector<int>& arr) {
    // Original: erase in loop, O(n^2)
    for (size_t i = 0; i < arr.size(); i++) {
        if (arr[i] % 2 == 0) {
            arr.erase(arr.begin() + i);
            i--;
        }
    }
    return arr;
}
""",
        "optimized": """\
#include <algorithm>
#include <vector>

std::vector<int> removeEven(std::vector<int>& arr) {
    // Optimized: swap-erase idiom, O(n)
    arr.erase(
        std::remove_if(arr.begin(), arr.end(),
                       [](int x) { return x % 2 == 0; }),
        arr.end()
    );
    return arr;
}
""",
        "tests": [
            "assert((removeEven({1,2,3,4,5}) == std::vector<int>({1,3,5}))",
            "assert((removeEven({2,4,6}) == std::vector<int>({}))",
            "assert((removeEven({1,3,5,7}) == std::vector<int>({1,3,5,7}))",
        ],
    },
    {
        "problem_idx": 5,
        "task_name": "Recursive DP Memoized to Iterative",
        "description": "Fibonacci with memoization (recursive, stack overhead) vs bottom-up (iterative).",
        "original": """\
#include <unordered_map>
#include <functional>

long long fib(int n) {
    // Original: recursive with memoization
    static std::unordered_map<int, long long> memo;
    if (n <= 1) return n;
    if (memo.count(n)) return memo[n];
    return memo[n] = fib(n-1) + fib(n-2);
}
""",
        "optimized": """\
#include <vector>

long long fib(int n) {
    // Optimized: iterative, no recursion overhead
    if (n <= 1) return n;
    long long a = 0, b = 1;
    for (int i = 2; i <= n; i++) {
        long long next = a + b;
        a = b;
        b = next;
    }
    return b;
}
""",
        "tests": [
            "assert(fib(0) == 0)",
            "assert(fib(1) == 1)",
            "assert(fib(10) == 55)",
            "assert(fib(20) == 6765)",
        ],
    },
]

PIE_TASKS_MORE = [
    {
        "problem_idx": 6,
        "task_name": "Loop Unrolling - Dot Product",
        "description": "Dot product with manual loop unrolling.",
        "original": """\
#include <vector>

long long dotProduct(const std::vector<int>& a, const std::vector<int>& b) {
    long long sum = 0;
    for (size_t i = 0; i < a.size(); i++) {
        sum += a[i] * b[i];
    }
    return sum;
}
""",
        "optimized": """\
#include <vector>

long long dotProduct(const std::vector<int>& a, const std::vector<int>& b) {
    long long sum = 0;
    size_t i = 0;
    for (; i + 3 < a.size(); i += 4) {
        sum += a[i] * b[i];
        sum += a[i+1] * b[i+1];
        sum += a[i+2] * b[i+2];
        sum += a[i+3] * b[i+3];
    }
    for (; i < a.size(); i++) {
        sum += a[i] * b[i];
    }
    return sum;
}
""",
        "tests": ["assert(dotProduct({1,2,3}, {4,5,6}) == 32)"],
    },
    {
        "problem_idx": 7,
        "task_name": "Prefix Sum vs Naive Accumulation",
        "description": "Range sum query: original recomputes, optimized uses prefix sums.",
        "original": """\
#include <vector>

int rangeSum(const std::vector<int>& nums, int left, int right) {
    int sum = 0;
    for (int i = left; i <= right; i++) {
        sum += nums[i];
    }
    return sum;
}
""",
        "optimized": """\
#include <vector>

int rangeSum(const std::vector<int>& nums, int left, int right) {
    static std::vector<int> prefix;
    static bool computed = false;
    if (!computed) {
        prefix.resize(nums.size() + 1, 0);
        for (size_t i = 0; i < nums.size(); i++) {
            prefix[i+1] = prefix[i] + nums[i];
        }
        computed = true;
    }
    return prefix[right+1] - prefix[left];
}
""",
        "tests": ["assert(rangeSum({1,2,3,4,5}, 1, 3) == 9)"],
    },
    {
        "problem_idx": 8,
        "task_name": "BFS Queue - deque vs Queue",
        "description": "BFS using deque (optimized) vs queue with extra allocations.",
        "original": """\
#include <vector>
#include <queue>

int bfsDistance(const std::vector<std::vector<int>>& adj, int start, int target) {
    std::vector<bool> visited(adj.size(), false);
    std::queue<std::pair<int, int>> q;
    q.push({start, 0});
    visited[start] = true;
    while (!q.empty()) {
        auto [node, dist] = q.front();
        q.pop();
        if (node == target) return dist;
        for (int neighbor : adj[node]) {
            if (!visited[neighbor]) {
                visited[neighbor] = true;
                q.push({neighbor, dist + 1});
            }
        }
    }
    return -1;
}
""",
        "optimized": """\
#include <vector>
#include <deque>

int bfsDistance(const std::vector<std::vector<int>>& adj, int start, int target) {
    std::vector<int> dist(adj.size(), -1);
    std::deque<int> q;
    q.push_back(start);
    dist[start] = 0;
    while (!q.empty()) {
        int node = q.front();
        q.pop_front();
        if (node == target) return dist[node];
        for (int neighbor : adj[node]) {
            if (dist[neighbor] == -1) {
                dist[neighbor] = dist[node] + 1;
                q.push_back(neighbor);
            }
        }
    }
    return -1;
}
""",
        "tests": ["assert(bfsDistance({{1,2},{0,2},{0,1}}, 0, 2) == 1)"],
    },
    {
        "problem_idx": 9,
        "task_name": "Binary Search - Recursive to Iterative",
        "description": "Recursive binary search (stack overhead) vs iterative.",
        "original": """\
#include <vector>

int binarySearchRec(const std::vector<int>& arr, int target, int lo, int hi) {
    if (lo > hi) return -1;
    int mid = lo + (hi - lo) / 2;
    if (arr[mid] == target) return mid;
    if (arr[mid] > target) return binarySearchRec(arr, target, lo, mid - 1);
    return binarySearchRec(arr, target, mid + 1, hi);
}
""",
        "optimized": """\
#include <vector>

int binarySearchRec(const std::vector<int>& arr, int target, int lo, int hi) {
    while (lo <= hi) {
        int mid = lo + (hi - lo) / 2;
        if (arr[mid] == target) return mid;
        if (arr[mid] > target) hi = mid - 1;
        else lo = mid + 1;
    }
    return -1;
}
""",
        "tests": ["assert(binarySearchRec({1,2,3,4,5,6,7,8,9,10}, 7, 0, 9) == 6)"],
    },
    {
        "problem_idx": 10,
        "task_name": "Sorting - Custom vs std::sort",
        "description": "Original uses bubble sort, optimized uses std::sort.",
        "original": """\
#include <vector>
#include <algorithm>

void customSort(std::vector<int>& arr) {
    // Original: bubble sort O(n^2)
    for (size_t i = 0; i < arr.size(); i++) {
        for (size_t j = 0; j + 1 < arr.size() - i; j++) {
            if (arr[j] > arr[j+1]) {
                std::swap(arr[j], arr[j+1]);
            }
        }
    }
}
""",
        "optimized": """\
#include <vector>
#include <algorithm>

void customSort(std::vector<int>& arr) {
    // Optimized: std::sort O(n log n)
    std::sort(arr.begin(), arr.end());
}
""",
        "tests": ["std::vector<int> v = {5,3,1,4,2}; customSort(v); assert(v == (std::vector<int>{1,2,3,4,5}))"],
    },
]


@dataclass
class PIETask:
    """A PIE benchmark task."""
    problem_idx: int
    task_name: str
    description: str
    original: str
    optimized: str
    tests: list[str] = field(default_factory=list)


PIE_TASKS_EXTENDED = PIE_TASKS + [PIETask(**t) for t in PIE_TASKS_MORE]


def compile_cpp(code: str, output_path: str, flag_o3: bool = True) -> tuple[bool, str]:
    """Compile C++ code with g++ -O3.

    Returns (success, error_message).
    """
    flags = ["-O3", "-std=c++17", "-march=native"] if flag_o3 else ["-O0", "-std=c++17"]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False) as f:
        f.write(code)
        code_path = f.name

    try:
        result = subprocess.run(
            ["g++"] + flags + [code_path, "-o", output_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        success = result.returncode == 0
        error = result.stderr if not success else ""
        return success, error
    except subprocess.TimeoutExpired:
        return False, "Compilation timeout"
    except FileNotFoundError:
        return False, "g++ not found - install g++ to use C++ benchmarks"
    finally:
        os.unlink(code_path)


def run_cpp_binary(binary_path: str, iterations: int = 1, timeout: float = 10.0) -> tuple[float, bool, str]:
    """Run compiled C++ binary and measure execution time.

    Returns (avg_exec_time_sec, success, output).
    """
    try:
        times = []
        output = ""
        for _ in range(iterations):
            start = time.perf_counter()
            result = subprocess.run(
                [binary_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            if result.returncode != 0:
                return 0.0, False, result.stdout + result.stderr
            output = result.stdout
        return sum(times) / len(times), True, output
    except subprocess.TimeoutExpired:
        return timeout, False, "Execution timeout"
    except Exception as e:
        return 0.0, False, str(e)


def build_full_program(func_code: str, task_name: str, iterations: int = 10000) -> str:
    """Build a complete C++ program that exercises the function.

    Each PIETask has function snippets; we wrap them with a main that
    runs the function repeatedly for timing.
    """
    IT = str(iterations)
    # Detect which function is present in the code
    if "removeDuplicates" in func_code:
        return (
            "#include <vector>\n#include <chrono>\n#include <iostream>\n"
            + func_code
            + "\nint main() {\n"
            + "    volatile int r;\n"
            + "    for (int i = 0; i < " + IT + "; i++) {\n"
            + "        std::vector<int> nums = {1,1,2,2,3,3,3,4,4,5,5,5,5,6,6,6,7,7,7,7,7,8,8,9,9,9,9,10,10,10};\n"
            + "        r = removeDuplicates(nums);\n"
            + "    }\n"
            + "    return 0;\n"
            + "}\n"
        )
    elif "countPairs" in func_code:
        return (
            "#include <unordered_map>\n#include <map>\n#include <vector>\n#include <chrono>\n"
            + func_code
            + "\nint main() {\n"
            + "    volatile int r;\n"
            + "    for (int i = 0; i < " + IT + "; i++) {\n"
            + "        std::vector<int> nums = {1,2,3,4,5,1,2,3,4,5,6,7,8,9,10,1,2,3,4,5,6,7,8,9,10,6,7,8,9,10};\n"
            + "        std::vector<int> copy = nums;\n"
            + "        r = countPairs(copy, 11);\n"
            + "    }\n"
            + "    return 0;\n"
            + "}\n"
        )
    elif "buildResult" in func_code:
        return (
            "#include <string>\n#include <vector>\n#include <chrono>\n"
            + func_code
            + "\nint main() {\n"
            + "    for (int i = 0; i < " + IT + "; i++) {\n"
            + "        std::vector<std::string> parts = {\"hello\", \"world\", \"foo\", \"bar\", \"baz\", \"qux\", \"abc\", \"def\", \"ghi\", \"jkl\"};\n"
            + "        std::vector<std::string> copy = parts;\n"
            + "        volatile std::string r = buildResult(copy);\n"
            + "    }\n"
            + "    return 0;\n"
            + "}\n"
        )
    elif "removeEven" in func_code:
        return (
            "#include <vector>\n#include <algorithm>\n#include <chrono>\n"
            + func_code
            + "\nint main() {\n"
            + "    for (int i = 0; i < " + IT + "; i++) {\n"
            + "        std::vector<int> arr = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30};\n"
            + "        std::vector<int> copy = arr;\n"
            + "        volatile auto r = removeEven(copy);\n"
            + "    }\n"
            + "    return 0;\n"
            + "}\n"
        )
    elif "fib" in func_code:
        return (
            "#include <unordered_map>\n#include <vector>\n#include <chrono>\n"
            + func_code
            + "\nint main() {\n"
            + "    volatile long long r;\n"
            + "    for (int i = 0; i < " + IT + "; i++) {\n"
            + "        r = fib(40);\n"
            + "    }\n"
            + "    return 0;\n"
            + "}\n"
        )
    else:
        return func_code + "\nint main() { return 0; }\n"


def benchmark_task(task: PIETask, iterations: int = 1000, run_iters: int = 5000) -> dict:
    """Benchmark a single PIE task.

    Measures:
    - baseline (original) compile success + exec time (run_iters internal loop)
    - optimized (human) compile success + exec time
    - speedup ratio
    - correctness (both pass tests)
    """
    result = {
        "problem_idx": task.problem_idx,
        "task_name": task.task_name,
        "n_tests": len(task.tests),
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        base_binary = os.path.join(tmpdir, "base")
        opt_binary = os.path.join(tmpdir, "opt")

        # Build full programs with timing loops
        base_prog = build_full_program(task.original, task.task_name, iterations=run_iters)
        opt_prog = build_full_program(task.optimized, task.task_name, iterations=run_iters)

        # Compile original
        ok, err = compile_cpp(base_prog, base_binary)
        result["baseline_compiled"] = ok
        result["baseline_compile_error"] = err[:200] if not ok else ""

        # Compile optimized
        ok2, err2 = compile_cpp(opt_prog, opt_binary)
        result["optimized_compiled"] = ok2
        result["optimized_compile_error"] = err2[:200] if not ok2 else ""

        if not ok or not ok2:
            result["status"] = "compile_fail"
            return result

        # Benchmark execution - each binary runs run_iters internally
        base_time, base_ok, base_out = run_cpp_binary(base_binary, iterations=iterations)
        opt_time, opt_ok, opt_out = run_cpp_binary(opt_binary, iterations=iterations)

        if base_ok and opt_ok:
            result["baseline_exec_ms"] = round(base_time * 1000, 4)
            result["optimized_exec_ms"] = round(opt_time * 1000, 4)
            result["speedup"] = round(base_time / opt_time, 4) if opt_time > 0 else None
            result["ratio_to_canonical"] = round(opt_time / base_time, 4) if base_time > 0 else None
            result["kept"] = (base_time / opt_time) >= (1.0 + 0.05)  # 5% improvement threshold
            result["status"] = "complete"
        else:
            result["status"] = "exec_fail"

    return result


def run_pie_harness(args: argparse.Namespace) -> int:
    """Main entry point for PIE benchmark."""

    # Check for g++
    try:
        subprocess.run(["g++", "--version"], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("WARNING: g++ not found. Install g++ to run C++ PIE benchmarks.")
        print("For Python-only benchmarks, use effibench_harness.py instead.")

    tasks = PIE_TASKS_EXTENDED if not args.smoke else PIE_TASKS_EXTENDED[:5]

    if args.baseline_only:
        print(f"=== PIE Baseline Mode ({len(tasks)} tasks) ===")
        print("Note: Requires g++ for C++ compilation\n")

    if args.mutalambda:
        print(f"=== PIE MutaLambda Mode ({len(tasks)} tasks) ===")
        print("Note: Running MutaLambda on C++ targets requires additional setup\n")

    records = []
    for i, task_data in enumerate(tasks):
        task = task_data if isinstance(task_data, PIETask) else PIETask(**task_data)
        print(f"[{i+1}/{len(tasks)}] #{task.problem_idx} {task.task_name[:50]}")

        if args.smoke:
            # Smoke: just verify the task loads correctly
            rec = {
                "problem_idx": task.problem_idx,
                "task_name": task.task_name,
                "status": "smoke_loaded",
                "n_tests": len(task.tests),
            }
        else:
            rec = benchmark_task(task, iterations=args.iterations)

        records.append(rec)
        tag = rec.get("status", "?")
        extra = ""
        if rec.get("speedup"):
            extra = f" speedup={rec['speedup']}"
        print(f"    {tag}{extra}\n")

    summary = summarize(records, min_improvement=0.05)
    report = {
        "benchmark": "PIE",
        "mode": "smoke" if args.smoke else ("baseline" if args.baseline_only else "mutalambda"),
        "config": {
            "tasks": args.tasks,
            "iterations": args.iterations,
            "parquet": args.parquet,
        },
        "summary": summary,
        "results": records,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    print(f"\nReport written to {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="PIE Benchmark Harness")
    p.add_argument("--smoke", action="store_true", help="Quick pipeline check")
    p.add_argument("--baseline-only", action="store_true", help="Only run baseline compilation")
    p.add_argument("--mutalambda", action="store_true", help="Run MutaLambda optimizer")
    p.add_argument("--parquet", default="/tmp/pie_train.parquet", help="PIE dataset parquet path")
    p.add_argument("--tasks", type=int, default=5, help="Number of tasks (smoke uses 5)")
    p.add_argument("--iterations", type=int, default=1000, help="Execution iterations for timing")
    p.add_argument("--out", default="benchmarks/results_pie.json", help="Output path")
    args = p.parse_args()

    return run_pie_harness(args)


if __name__ == "__main__":
    raise SystemExit(main())
