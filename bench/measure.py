"""Isolated, repeatable measurement of a code variant.

Every measurement runs in a **fresh subprocess** so that:

* module-level caches cannot leak between the baseline and the candidate;
* a crash or an OOM in a candidate cannot take the harness down;
* the timing loop is not polluted by the harness' own imports.

Only the standard library is used. The driver is generated as source text and
handed to ``python -I -S`` (isolated, no site) so the measured process is as
close to a clean interpreter as we can get without a container.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from bench.spec import BenchTask, Measurement, Workload

DRIVER = r'''
import gc
import json
import math
import resource
import sys
import time
import tracemalloc

def _norm(value):
    """JSON round-trips tuples into lists; compare on a common shape."""
    if isinstance(value, tuple):
        return [_norm(v) for v in value]
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    return value


def _allclose(got, expected, rtol=1e-6, atol=1e-9):
    """numpy-free recursive allclose so the driver stays dependency-light."""
    if isinstance(got, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(got) != len(expected):
            return False
        return all(_allclose(a, b, rtol, atol) for a, b in zip(got, expected))
    try:
        return math.isclose(float(got), float(expected), rel_tol=rtol, abs_tol=atol)
    except (TypeError, ValueError):
        return _norm(got) == _norm(expected)


def _compare(got, expected, comparison="equal"):
    comparison = (comparison or "equal").lower()
    if comparison == "equal":
        return _norm(got) == _norm(expected)
    if comparison == "float_close":
        try:
            return math.isclose(float(got), float(expected), rel_tol=1e-9, abs_tol=1e-12)
        except Exception:
            return False
    if comparison == "float_close_loose":
        try:
            return math.isclose(float(got), float(expected), rel_tol=1e-6, abs_tol=1e-9)
        except Exception:
            return False
    if comparison == "array_allclose":
        try:
            import numpy as np
            return bool(np.allclose(np.asarray(got), np.asarray(expected), rtol=1e-6, atol=1e-9))
        except ImportError:
            return _allclose(got, expected)
        except Exception:
            return _allclose(got, expected)
    if comparison == "sequence_close":
        return _allclose(got, expected)
    if comparison == "set_equal":
        try:
            return set(got) == set(expected)
        except Exception:
            return False
    if comparison == "sorted_equal":
        try:
            return sorted(got) == sorted(expected)
        except Exception:
            return False
    if comparison == "contains":
        try:
            return expected in got
        except TypeError:
            return False
    return got == expected


def _load(path):
    ns = {"__name__": "__muta_bench_candidate__", "__file__": path}
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    exec(compile(src, path, "exec"), ns, ns)
    return ns


def _run_tests(ns, tests):
    passed = 0
    failures = []
    for idx, tc in enumerate(tests):
        name = tc.get("function") or ENTRYPOINT
        fn = ns.get(name)
        try:
            if not callable(fn):
                raise NameError("entrypoint not found: %s" % name)
            got = fn(*tc.get("args", []), **tc.get("kwargs", {}))
            if "expected" in tc:
                ok = _compare(got, tc["expected"], tc.get("comparison", "equal"))
            else:
                ok = bool(got)
            if ok:
                passed += 1
            else:
                failures.append({"index": idx, "reason": "mismatch", "repr": repr(got)[:200]})
        except Exception as exc:
            failures.append({"index": idx, "reason": type(exc).__name__, "detail": str(exc)[:200]})
    return passed, failures[:10]


def main():
    cfg = json.loads(sys.stdin.read())
    global ENTRYPOINT
    ENTRYPOINT = cfg["entrypoint"]
    out = {
        "ok": False, "tests_passed": 0, "tests_total": len(cfg["tests"]),
        "samples": [], "mem_peak_mb": float("inf"), "rss_peak_mb": 0.0,
        "error": "", "failures": [], "first_sample_ms": None,
    }
    try:
        ns = _load(cfg["code_path"])
    except Exception as exc:
        out["error"] = "load:%s:%s" % (type(exc).__name__, str(exc)[:300])
        print(json.dumps(out)); return 1

    if cfg.get("setup"):
        try:
            exec(compile(cfg["setup"], "<setup>", "exec"), ns, ns)
        except Exception as exc:
            out["error"] = "setup:%s" % str(exc)[:300]
            print(json.dumps(out)); return 1

    passed, failures = _run_tests(ns, cfg["tests"])
    out["tests_passed"] = passed
    out["failures"] = failures
    if cfg.get("tests_only"):
        out["ok"] = True
        print(json.dumps(out)); return 0
    if out["tests_total"] and passed < out["tests_total"] and cfg.get("require_pass", True):
        out["ok"] = True   # measurement ran; correctness simply failed
        out["error"] = "tests_failed"
        print(json.dumps(out)); return 0

    fn = ns.get(ENTRYPOINT)
    if not callable(fn):
        out["error"] = "entrypoint_missing:%s" % ENTRYPOINT
        print(json.dumps(out)); return 1

    calls = [(tuple(a), dict(k)) for a, k in cfg["calls"]]
    if not calls:
        out["error"] = "empty_workload"
        print(json.dumps(out)); return 1

    def one_pass():
        for a, k in calls:
            fn(*a, **k)

    try:
        for _ in range(int(cfg.get("warmups", 0))):
            one_pass()
    except Exception as exc:
        out["error"] = "warmup:%s:%s" % (type(exc).__name__, str(exc)[:200])
        print(json.dumps(out)); return 1

    # ---- memory pass (separate from timing: tracemalloc distorts timing) ----
    try:
        gc.collect()
        tracemalloc.start()
        one_pass()
        _cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        out["mem_peak_mb"] = peak / (1024.0 * 1024.0)
    except Exception as exc:
        try:
            tracemalloc.stop()
        except Exception:
            pass
        out["error"] = "memory:%s" % str(exc)[:200]

    # ---- timing pass ----
    samples = []
    gc_was = gc.isenabled()
    gc.disable()
    try:
        for i in range(int(cfg.get("samples", 5))):
            t0 = time.perf_counter()
            one_pass()
            samples.append((time.perf_counter() - t0) * 1000.0)
    except Exception as exc:
        out["error"] = "timing:%s:%s" % (type(exc).__name__, str(exc)[:200])
    finally:
        if gc_was:
            gc.enable()

    out["samples"] = samples
    out["first_sample_ms"] = samples[0] if samples else None
    out["rss_peak_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    out["ok"] = bool(samples)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def environment_fingerprint() -> Dict[str, Any]:
    """Everything a reviewer needs to know the numbers are comparable."""
    info: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
    }
    try:  # Linux only, but that is where benchmarks should run anyway.
        with open("/proc/cpuinfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    info["cpu_model"] = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    try:
        info["loadavg_1m"] = round(os.getloadavg()[0], 3)
    except (OSError, AttributeError):
        pass
    info["governor"] = _cpu_governor()
    info["turbo_disabled"] = _turbo_disabled()
    return info


def _cpu_governor() -> str:
    path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return "unknown"


def _turbo_disabled() -> Optional[bool]:
    try:
        with open("/sys/devices/system/cpu/intel_pstate/no_turbo", "r", encoding="utf-8") as fh:
            return fh.read().strip() == "1"
    except OSError:
        return None


def measure(
    code: str,
    task: BenchTask,
    *,
    tests: Optional[Sequence[Dict[str, Any]]] = None,
    workload: Optional[Workload] = None,
    tests_only: bool = False,
    python_exe: Optional[str] = None,
    env_extra: Optional[Dict[str, str]] = None,
) -> Measurement:
    """Run one measurement pass of ``code`` for ``task`` in a fresh process."""
    wl = workload or task.workload
    test_cases = list(tests if tests is not None else task.all_tests)
    cfg = {
        "code_path": "",
        "entrypoint": task.entrypoint,
        "tests": test_cases,
        "calls": wl.normalised_calls(),
        "warmups": wl.warmups,
        "samples": wl.samples,
        "setup": wl.setup,
        "tests_only": tests_only,
        "require_pass": True,
    }

    tmpdir = tempfile.mkdtemp(prefix="mutabench_")
    try:
        code_path = Path(tmpdir) / "candidate.py"
        code_path.write_text(code, encoding="utf-8")
        driver_path = Path(tmpdir) / "_driver.py"
        driver_path.write_text(DRIVER, encoding="utf-8")
        cfg["code_path"] = str(code_path)

        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": tmpdir,
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
        if env_extra:
            env.update(env_extra)
        # `-I` implies -E -s (ignore env vars & user site) but we still need the
        # interpreter's own site-packages, hence no `-S`.
        cmd = [python_exe or sys.executable, "-I", str(driver_path)]
        try:
            proc = subprocess.run(
                cmd,
                input=json.dumps(cfg),
                capture_output=True,
                text=True,
                timeout=wl.timeout_sec,
                cwd=tmpdir,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return Measurement(ok=False, timed_out=True, error="timeout",
                               tests_total=len(test_cases))

        raw = (proc.stdout or "").strip().splitlines()
        payload: Dict[str, Any] = {}
        for line in reversed(raw):  # last JSON line wins (candidate may print)
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        if not payload:
            return Measurement(
                ok=False,
                tests_total=len(test_cases),
                error=("no_report:" + (proc.stderr or "")[-300:]).strip(),
            )
        return _to_measurement(payload)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _to_measurement(payload: Dict[str, Any]) -> Measurement:
    samples: List[float] = [float(s) for s in payload.get("samples") or []]
    m = Measurement(
        ok=bool(payload.get("ok")),
        tests_passed=int(payload.get("tests_passed", 0)),
        tests_total=int(payload.get("tests_total", 0)),
        mem_peak_mb=float(payload.get("mem_peak_mb", float("inf"))),
        samples=samples,
        error=str(payload.get("error", "")),
        failures=list(payload.get("failures") or []),
    )
    if samples:
        m.latency_ms_p50 = _percentile(samples, 50)
        m.latency_ms_p95 = _percentile(samples, 95)
        m.latency_ms_min = min(samples)
        m.latency_ms_stdev = statistics.stdev(samples) if len(samples) > 1 else 0.0
    return m


def _percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return float("inf")
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    k = (len(data) - 1) * (max(0.0, min(100.0, p)) / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(data) - 1)
    if lo == hi:
        return data[lo]
    return data[lo] * (hi - k) + data[hi] * (k - lo)


def measure_repeated(
    code: str,
    task: BenchTask,
    *,
    repeats: int = 5,
    tests: Optional[Sequence[Dict[str, Any]]] = None,
    workload: Optional[Workload] = None,
    python_exe: Optional[str] = None,
) -> Dict[str, Any]:
    """Repeat the whole measurement ``repeats`` times in *separate* processes.

    Cross-process repetition is what makes the published mean ± std honest:
    a single process can get lucky with allocator state, CPU frequency or
    branch predictor warmth.
    """
    runs: List[Measurement] = []
    for _ in range(max(1, repeats)):
        runs.append(
            measure(code, task, tests=tests, workload=workload, python_exe=python_exe)
        )
    ok_runs = [r for r in runs if r.ok and r.samples]
    p50s = [r.latency_ms_p50 for r in ok_runs]
    mems = [r.mem_peak_mb for r in ok_runs if r.mem_peak_mb != float("inf")]
    best = min(ok_runs, key=lambda r: r.latency_ms_p50, default=runs[0])
    return {
        "repeats": len(runs),
        "ok_repeats": len(ok_runs),
        "latency_ms_mean": statistics.fmean(p50s) if p50s else float("inf"),
        "latency_ms_std": statistics.stdev(p50s) if len(p50s) > 1 else 0.0,
        "latency_ms_median": statistics.median(p50s) if p50s else float("inf"),
        "latency_ms_min": min(p50s) if p50s else float("inf"),
        "mem_peak_mb_mean": statistics.fmean(mems) if mems else float("inf"),
        "mem_peak_mb_std": statistics.stdev(mems) if len(mems) > 1 else 0.0,
        "tests_passed": best.tests_passed,
        "tests_total": best.tests_total,
        "pass_rate": best.pass_rate,
        "all_pass": best.all_pass,
        "error": best.error or (runs[0].error if not ok_runs else ""),
        "timed_out": any(r.timed_out for r in runs),
        "failures": best.failures,
        "per_repeat_p50_ms": p50s,
        "first_sample_ms": best.samples[0] if best.samples else None,
        "steady_p50_ms": best.latency_ms_p50,
    }


def measure_interleaved(
    variants: Dict[str, str],
    task: BenchTask,
    *,
    repeats: int = 5,
    tests: Optional[Sequence[Dict[str, Any]]] = None,
    workload: Optional[Workload] = None,
    python_exe: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Measure several code variants A/B/A/B instead of AAA then BBB.

    Sequential blocks let CPU frequency drift, page-cache warmth and background
    load bias whichever variant ran second — on a shared box that alone can
    manufacture a 15% "speedup". Interleaving spreads that drift across all
    variants, and the per-round ordering is rotated so no variant is
    permanently first.
    """
    names = list(variants)
    rounds: Dict[str, List[Measurement]] = {n: [] for n in names}
    for r in range(max(1, repeats)):
        order = names[r % len(names):] + names[: r % len(names)]
        for name in order:
            rounds[name].append(
                measure(variants[name], task, tests=tests, workload=workload,
                        python_exe=python_exe)
            )
    return {name: _aggregate_runs(runs) for name, runs in rounds.items()}


def _aggregate_runs(runs: List[Measurement]) -> Dict[str, Any]:
    ok_runs = [r for r in runs if r.ok and r.samples]
    p50s = [r.latency_ms_p50 for r in ok_runs]
    mems = [r.mem_peak_mb for r in ok_runs if r.mem_peak_mb != float("inf")]
    best = min(ok_runs, key=lambda r: r.latency_ms_p50, default=runs[0])
    return {
        "repeats": len(runs),
        "ok_repeats": len(ok_runs),
        "latency_ms_mean": statistics.fmean(p50s) if p50s else float("inf"),
        "latency_ms_std": statistics.stdev(p50s) if len(p50s) > 1 else 0.0,
        "latency_ms_median": statistics.median(p50s) if p50s else float("inf"),
        "latency_ms_min": min(p50s) if p50s else float("inf"),
        "mem_peak_mb_mean": statistics.fmean(mems) if mems else float("inf"),
        "mem_peak_mb_std": statistics.stdev(mems) if len(mems) > 1 else 0.0,
        "tests_passed": best.tests_passed,
        "tests_total": best.tests_total,
        "pass_rate": best.pass_rate,
        "all_pass": best.all_pass,
        "error": best.error or (runs[0].error if not ok_runs else ""),
        "timed_out": any(r.timed_out for r in runs),
        "failures": best.failures,
        "per_repeat_p50_ms": p50s,
        "first_sample_ms": best.samples[0] if best.samples else None,
        "steady_p50_ms": best.latency_ms_p50,
    }


def calibrate_noise(task: BenchTask, *, repeats: int = 3) -> Dict[str, Any]:
    """Measure identical code as if it were two variants.

    The resulting ratio is this machine's noise floor: any reported speedup
    inside that band is indistinguishable from thermal drift, and the report
    says so instead of claiming a win.
    """
    pair = measure_interleaved(
        {"a": task.source_code, "b": task.source_code}, task, repeats=repeats
    )
    a = pair["a"]["latency_ms_mean"]
    b = pair["b"]["latency_ms_mean"]
    if not a or not b or a == float("inf") or b == float("inf"):
        return {"available": False}
    ratio = a / b
    spread = max(ratio, 1.0 / ratio)
    return {
        "available": True,
        "task": task.task_id,
        "identical_code_ratio": round(ratio, 4),
        "noise_band": round(spread, 4),
        "interpretation": (
            f"speedups below {spread:.2f}x on this machine are within measurement noise"
        ),
    }
