#!/usr/bin/env python3
"""Shared toolchain helpers for language handlers (compilers, benchmarks)."""
import os
import statistics
import subprocess
import tempfile
import time
from typing import Any, Callable, Dict, List, Sequence, Tuple


def run_on_temp_source(
    source: str,
    suffix: str,
    build_command: Callable[[str], Sequence[str]],
    timeout: float,
    timeout_message: str,
) -> Tuple[bool, str]:
    """Write ``source`` to a temp file, run ``build_command(path)`` and clean up.

    Returns ``(ok, message)`` where message is the tool's stderr on failure.
    """
    tmpfile = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(source.encode())
            tmpfile = f.name

        result = subprocess.run(
            list(build_command(tmpfile)),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return (True, "")
        return (False, result.stderr)
    except subprocess.TimeoutExpired:
        return (False, timeout_message)
    except Exception as e:
        return (False, str(e))
    finally:
        if tmpfile and os.path.exists(tmpfile):
            try:
                os.unlink(tmpfile)
            except OSError:
                pass


def latency_stats(times: List[float], iterations: int) -> Dict[str, float]:
    """Summarize per-run latencies as p50/p99/throughput."""
    return {
        "latency_p50": statistics.median(times),
        "latency_p99": sorted(times)[int(len(times) * 0.99)],
        "throughput": iterations / sum(times) if sum(times) else 0,
        "runs": len(times),
    }


def benchmark_command(
    command: Sequence[str],
    iterations: int,
    timeout: float,
    ignore_errors: bool = False,
) -> Dict[str, Any]:
    """Time ``command`` over ``iterations`` runs and return latency statistics.

    A timeout ends the loop and the runs collected so far are reported. Other
    failures are reported as an error unless ``ignore_errors`` is set.
    """
    times: List[float] = []
    try:
        for _ in range(iterations):
            start = time.perf_counter()
            subprocess.run(list(command), capture_output=True, text=True, timeout=timeout)
            times.append(time.perf_counter() - start)
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        if not ignore_errors:
            return {"error": str(e)}

    if not times:
        return {"error": "No successful runs"}
    return latency_stats(times, iterations)
