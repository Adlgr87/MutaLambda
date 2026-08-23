"""Native (C++) measurement path — required by PIE.

PIE programs are whole C++ programs that read stdin and write stdout, so they
cannot go through the Python driver. This module compiles a candidate with
``g++ -O3`` (the level PIE itself uses, so a reported speedup is a speedup
*over an already-optimised binary*), checks its stdout against the expected
outputs, and times it.

Honest-measurement notes that must travel with any number produced here:

* Wall-clock includes process start-up. It is identical for baseline and
  candidate, so ratios are fair, but absolute milliseconds are not comparable
  to PIE's published gem5 cycle counts.
* Upstream PIE reports gem5-simulated speedups precisely because commodity
  hardware produces phantom improvements. We compensate with repeats +
  cross-run std and we say "wall-clock" every single time.
"""

from __future__ import annotations

import os
import resource
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_FLAGS = ("-O3", "-std=c++17", "-w")


def compiler_available(compiler: str = "g++") -> bool:
    return shutil.which(compiler) is not None


def compiler_version(compiler: str = "g++") -> str:
    if not compiler_available(compiler):
        return "unavailable"
    try:
        out = subprocess.run([compiler, "--version"], capture_output=True, text=True, timeout=10)
        return (out.stdout or "").splitlines()[0] if out.stdout else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def compile_cpp(code: str, workdir: Path, *, compiler: str = "g++",
                flags: Sequence[str] = DEFAULT_FLAGS,
                timeout: float = 120.0) -> Dict[str, Any]:
    src = workdir / "prog.cpp"
    binary = workdir / "prog"
    src.write_text(code, encoding="utf-8")
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [compiler, *flags, str(src), "-o", str(binary)],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "compile_timeout", "binary": None,
                "compile_sec": time.perf_counter() - t0}
    if proc.returncode != 0:
        return {"ok": False, "error": f"compile_error: {(proc.stderr or '')[-400:]}",
                "binary": None, "compile_sec": time.perf_counter() - t0}
    return {"ok": True, "error": "", "binary": binary,
            "compile_sec": time.perf_counter() - t0}


def _normalise(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines())


def _run_once(binary: Path, stdin_text: str, timeout: float) -> Dict[str, Any]:
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    t0 = time.perf_counter()
    try:
        proc = subprocess.run([str(binary)], input=stdin_text, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "elapsed_ms": timeout * 1000.0, "stdout": "",
                "timed_out": True, "rss_kb": 0}
    elapsed = (time.perf_counter() - t0) * 1000.0
    after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return {"ok": proc.returncode == 0, "elapsed_ms": elapsed,
            "stdout": proc.stdout or "", "timed_out": False,
            "rss_kb": max(0, after - before), "returncode": proc.returncode}


def measure_native(
    code: str,
    *,
    tests: Sequence[Dict[str, str]],
    workload: Sequence[str],
    warmups: int = 1,
    samples: int = 5,
    timeout_sec: float = 30.0,
    compiler: str = "g++",
    flags: Sequence[str] = DEFAULT_FLAGS,
) -> Dict[str, Any]:
    """Compile, verify and time a C++ program.

    ``tests`` are ``{"stdin": ..., "expected_stdout": ...}`` dicts; ``workload``
    is the list of stdin payloads used for timing (usually the largest inputs).
    """
    result: Dict[str, Any] = {
        "ok": False, "tests_passed": 0, "tests_total": len(tests),
        "latency_ms_p50": float("inf"), "latency_ms_mean": float("inf"),
        "latency_ms_std": 0.0, "mem_peak_mb": float("inf"),
        "samples": [], "error": "", "compile_sec": 0.0, "failures": [],
    }
    if not compiler_available(compiler):
        result["error"] = f"{compiler} not available"
        return result

    tmp = Path(tempfile.mkdtemp(prefix="mutabench_cpp_"))
    try:
        built = compile_cpp(code, tmp, compiler=compiler, flags=flags)
        result["compile_sec"] = built["compile_sec"]
        if not built["ok"]:
            result["error"] = built["error"]
            return result
        binary: Path = built["binary"]

        passed = 0
        for i, tc in enumerate(tests):
            run = _run_once(binary, tc.get("stdin", ""), timeout_sec)
            if run["ok"] and _normalise(run["stdout"]) == _normalise(tc.get("expected_stdout", "")):
                passed += 1
            elif len(result["failures"]) < 5:
                result["failures"].append({
                    "index": i,
                    "reason": "timeout" if run.get("timed_out") else "mismatch",
                    "got": _normalise(run["stdout"])[:120],
                })
        result["tests_passed"] = passed
        if tests and passed < len(tests):
            result["ok"] = True
            result["error"] = "tests_failed"
            return result

        payloads = list(workload) or [tc.get("stdin", "") for tc in tests[:1]]
        for _ in range(max(0, warmups)):
            for payload in payloads:
                _run_once(binary, payload, timeout_sec)

        sample_times: List[float] = []
        rss: List[float] = []
        for _ in range(max(1, samples)):
            total = 0.0
            for payload in payloads:
                run = _run_once(binary, payload, timeout_sec)
                if run.get("timed_out"):
                    result["error"] = "timeout_during_timing"
                    break
                total += run["elapsed_ms"]
                rss.append(run["rss_kb"] / 1024.0)
            sample_times.append(total)

        result["samples"] = sample_times
        if sample_times:
            result["latency_ms_p50"] = statistics.median(sample_times)
            result["latency_ms_mean"] = statistics.fmean(sample_times)
            result["latency_ms_std"] = (
                statistics.stdev(sample_times) if len(sample_times) > 1 else 0.0
            )
            result["ok"] = True
        if rss:
            result["mem_peak_mb"] = max(rss)
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def measure_native_repeated(
    code: str,
    *,
    tests: Sequence[Dict[str, str]],
    workload: Sequence[str],
    repeats: int = 3,
    **kwargs: Any,
) -> Dict[str, Any]:
    runs = [measure_native(code, tests=tests, workload=workload, **kwargs)
            for _ in range(max(1, repeats))]
    ok_runs = [r for r in runs if r["ok"] and r["samples"]]
    p50s = [r["latency_ms_p50"] for r in ok_runs]
    mems = [r["mem_peak_mb"] for r in ok_runs if r["mem_peak_mb"] != float("inf")]
    best = min(ok_runs, key=lambda r: r["latency_ms_p50"], default=runs[0])
    total = best.get("tests_total", 0)
    return {
        "repeats": len(runs),
        "ok_repeats": len(ok_runs),
        "latency_ms_mean": statistics.fmean(p50s) if p50s else float("inf"),
        "latency_ms_std": statistics.stdev(p50s) if len(p50s) > 1 else 0.0,
        "latency_ms_median": statistics.median(p50s) if p50s else float("inf"),
        "latency_ms_min": min(p50s) if p50s else float("inf"),
        "mem_peak_mb_mean": statistics.fmean(mems) if mems else float("inf"),
        "mem_peak_mb_std": statistics.stdev(mems) if len(mems) > 1 else 0.0,
        "tests_passed": best.get("tests_passed", 0),
        "tests_total": total,
        "pass_rate": (best.get("tests_passed", 0) / total) if total else 0.0,
        "all_pass": bool(total) and best.get("tests_passed", 0) == total,
        "error": best.get("error", ""),
        "timed_out": any("timeout" in (r.get("error") or "") for r in runs),
        "failures": best.get("failures", []),
        "per_repeat_p50_ms": p50s,
        "compile_sec": best.get("compile_sec", 0.0),
        "steady_p50_ms": best.get("latency_ms_p50"),
        "first_sample_ms": (best.get("samples") or [None])[0],
    }


def environment_native() -> Dict[str, Any]:
    return {
        "compiler": compiler_version("g++"),
        "flags": " ".join(DEFAULT_FLAGS),
        "note": "wall-clock incl. process start-up; not comparable to gem5 cycles",
    }
