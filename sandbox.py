"""Sandbox evaluation for generated Python code."""

from __future__ import annotations

import ast
import atexit
import json
import logging
import multiprocessing
import os
import resource
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

from fitness_vector import FitnessVector
from models import EvalResult

logger = logging.getLogger("MutaLambda")


def _set_memory_limit(memory_mb: int) -> None:
    """Set a hard virtual-memory ceiling in the child process."""
    if memory_mb <= 0:
        return
    limit_bytes = int(memory_mb * 1024 * 1024)
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    if hard == resource.RLIM_INFINITY or hard < 0 or hard > limit_bytes:
        hard = limit_bytes
    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, hard))


def _eval_worker(args: Tuple[str, List[Dict], float, int]) -> EvalResult:
    """Execute one candidate in an isolated subprocess and extract metrics."""
    code, test_cases, timeout_sec, memory_mb = args
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        preexec_fn = (lambda: _set_memory_limit(memory_mb)) if memory_mb > 0 else None
        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            input=json.dumps(test_cases),
            preexec_fn=preexec_fn,
        )
        elapsed = time.perf_counter() - start

        try:
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            peak_kb: float = float(usage.ru_maxrss)
            if sys.platform == "darwin":
                peak_kb /= 1024.0
            peak_mb = peak_kb / 1024.0
        except (AttributeError, ValueError):
            peak_mb = 0.0

        num_tests = max(1, len(test_cases))
        throughput = num_tests / max(elapsed, 1e-9)

        code_kb = max(1.0, len(code.encode("utf-8")) / 1024.0)
        try:
            tree = ast.parse(code)
            decision_points = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, (ast.If, ast.While, ast.For,
                                     ast.ExceptHandler, ast.BoolOp))
            )
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    decision_points += len(node.orelse) > 0
            cyclomatic = 1 + decision_points
        except SyntaxError:
            cyclomatic = 1
        parsimony = 1.0 / (1.0 + cyclomatic / code_kb)

        try:
            lines = proc.stdout.strip().split('\n')
            report = None
            for line in reversed(lines):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        report = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
            if report is None:
                if not test_cases and proc.returncode == 0:
                    report = {"passed": 1, "total": 1}
                else:
                    raise ValueError("No valid JSON line found in subprocess stdout")
            passed = report.get("passed", 0)
            total = report.get("total", 1)
            correctness = passed / max(total, 1)
        except Exception:
            correctness = 0.0

        fitness = FitnessVector(
            correctness=correctness,
            latency_p50=elapsed,
            latency_p99=elapsed,
            throughput=throughput,
            memory_peak_mb=peak_mb,
            parsimony=parsimony,
        )

        metrics: Dict[str, float] = {
            "latency": elapsed,
            "latency_p50": elapsed,
            "latency_p99": elapsed,
            "throughput": throughput,
            "memory_peak_mb": peak_mb,
            "parsimony": parsimony,
            "correctness": correctness,
            "cyclomatic_complexity": float(cyclomatic),
            "code_kb": code_kb,
        }

        return EvalResult(
            fitness=fitness,
            passed=proc.returncode == 0,
            metrics=metrics,
            stdout=proc.stdout[:2000],
            stderr=proc.stderr[:2000],
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        return EvalResult(
            fitness=FitnessVector(
                correctness=0.0,
                latency_p50=timeout_sec,
                latency_p99=timeout_sec,
                throughput=0.0,
                memory_peak_mb=float("inf"),
                parsimony=0.0,
            ),
            passed=False,
            metrics={
                "latency": timeout_sec,
                "correctness": 0.0,
                "error": "TimeoutExpired",
            },
            stdout="",
            stderr="[TIMEOUT]",
            timed_out=True,
        )
    except Exception as exc:
        error_str = str(exc)[:2000]
        return EvalResult(
            fitness=FitnessVector(
                correctness=0.0,
                latency_p50=timeout_sec,
                latency_p99=timeout_sec,
                throughput=0.0,
                memory_peak_mb=float("inf"),
                parsimony=0.0,
            ),
            passed=False,
            metrics={
                "latency": timeout_sec,
                "correctness": 0.0,
                "error": error_str[:200],
            },
            stdout="",
            stderr=error_str,
            timed_out="Timeout" in error_str or "timeout" in error_str.lower(),
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class SandboxEvaluator:
    """Evalúa lotes de código en paralelo usando ProcessPoolExecutor."""

    def __init__(
        self,
        test_cases: List[Dict],
        timeout_sec: float = 10.0,
        memory_mb: int = 256,
        parallelism: Optional[int] = None,
    ):
        self.test_cases = test_cases
        self.timeout_sec = timeout_sec
        self.memory_mb = memory_mb
        if os.getenv("MUTALAMBDA_E2E_SERIAL", "0") == "1":
            self.parallelism = 1
        else:
            self.parallelism = min(
                parallelism or multiprocessing.cpu_count(),
                multiprocessing.cpu_count(),
            )
        self._pool = ProcessPoolExecutor(max_workers=self.parallelism)
        atexit.register(self.shutdown)

    def evaluate_batch(self, codes: List[str]) -> List[EvalResult]:
        """Evaluación paralela con pool persistente."""
        if not codes:
            return []

        args_list = [(code, self.test_cases, self.timeout_sec, self.memory_mb) for code in codes]
        results: List[EvalResult] = [None] * len(codes)  # type: ignore[list-item]

        future_to_idx = {
            self._pool.submit(_eval_worker, args): idx
            for idx, args in enumerate(args_list)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                logger.warning("Eval worker %d raised: %s", idx, exc)
                error_str = str(exc)[:2000]
                results[idx] = EvalResult(
                    fitness=FitnessVector.worst(),
                    passed=False,
                    metrics={"error": error_str[:200]},
                    stdout="",
                    stderr=error_str,
                    timed_out=False,
                )

        return results  # type: ignore[return-value]

    def shutdown(self, wait: bool = True) -> None:
        """Apaga el pool de procesos de forma controlada."""
        self._pool.shutdown(wait=wait)
