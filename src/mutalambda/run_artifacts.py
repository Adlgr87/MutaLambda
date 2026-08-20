"""Per-run observability artifacts (workflow §15–16).

Produces:
  run_manifest.json
  best_solution.py
  best_solution.patch
  fitness_history.json
  lineage.json (optional)
  benchmark_report.md (optional summary)
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _git_commit() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError, TimeoutError):
        pass
    return "unknown"


def write_run_artifacts(
    agent: Any,
    *,
    output_dir: str | Path,
    baseline_code: str = "",
    task: str = "",
) -> Dict[str, str]:
    """Write the standard artifact set for a completed (or checkpointed) run.

    Returns mapping artifact_name → path.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}

    best = getattr(agent, "_global_best", None) or (
        agent._get_global_best() if hasattr(agent, "_get_global_best") else None
    )
    metrics = agent.get_metrics() if hasattr(agent, "get_metrics") else {}
    config = getattr(agent, "config", None)

    # best_solution.py
    best_path = out / "best_solution.py"
    best_code = best.code if best is not None else ""
    best_path.write_text(best_code or "# no solution\n", encoding="utf-8")
    paths["best_solution.py"] = str(best_path)

    # best_solution.patch
    patch_path = out / "best_solution.patch"
    if baseline_code and best_code:
        import difflib

        patch = "".join(
            difflib.unified_diff(
                baseline_code.splitlines(keepends=True),
                best_code.splitlines(keepends=True),
                fromfile="baseline",
                tofile="best_solution.py",
            )
        )
        patch_path.write_text(patch, encoding="utf-8")
    else:
        patch_path.write_text("", encoding="utf-8")
    paths["best_solution.patch"] = str(patch_path)

    # fitness_history.json
    hist = {
        "global_best_history": list(getattr(agent, "_global_best_history", []) or []),
        "generation_times": list(getattr(agent, "_generation_times", []) or []),
        "protocol": getattr(agent, "_protocol_metrics", {}),
    }
    hist_path = out / "fitness_history.json"
    hist_path.write_text(json.dumps(hist, indent=2), encoding="utf-8")
    paths["fitness_history.json"] = str(hist_path)

    # lineage.json
    lineage = getattr(agent, "_lineage", None)
    lin_path = out / "lineage.json"
    if lineage is not None and hasattr(lineage, "to_dict"):
        lin_path.write_text(json.dumps(lineage.to_dict(), indent=2), encoding="utf-8")
    else:
        lin_path.write_text("{}", encoding="utf-8")
    paths["lineage.json"] = str(lin_path)

    # run_manifest.json
    cfg_dict: Dict[str, Any] = {}
    if config is not None:
        if is_dataclass(config):
            try:
                cfg_dict = asdict(config)
            except Exception:
                cfg_dict = {"repr": repr(config)}
        else:
            cfg_dict = {"repr": repr(config)}

    manifest = {
        "schema": "mutalambda.run_manifest.v1",
        "generated_at": time.time(),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": getattr(agent, "run_id", ""),
        "task": task or getattr(agent, "task", ""),
        "git_commit": _git_commit(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "generation_completed": getattr(agent, "_generation_completed", 0),
        "current_generation": getattr(agent, "_current_generation", 0),
        "best_score": best.score if best is not None else None,
        "best_id": best.id if best is not None else None,
        "metrics": metrics,
        "config": cfg_dict,
        "artifacts": {k: Path(v).name for k, v in paths.items()},
        "extension_metrics": (
            agent.extensions.all_metrics()
            if getattr(agent, "extensions", None) is not None
            else {}
        ),
        "bandit": (
            agent._operator_bandit.snapshot()
            if getattr(agent, "_operator_bandit", None) is not None
            else {}
        ),
        "event_counts": (
            agent.event_bus.counts()
            if getattr(agent, "event_bus", None) is not None
            else {}
        ),
    }
    man_path = out / "run_manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    paths["run_manifest.json"] = str(man_path)

    # benchmark_report.md (lightweight)
    report_path = out / "benchmark_report.md"
    report_path.write_text(
        "\n".join(
            [
                f"# MutaLambda run `{manifest['run_id']}`",
                "",
                f"- Task: {manifest['task']}",
                f"- Generations completed: {manifest['generation_completed']}",
                f"- Best score: {manifest['best_score']}",
                f"- Commit: `{manifest['git_commit'][:12]}`",
                f"- Python: {manifest['python']}",
                "",
                "## Artifacts",
                "",
                *[f"- `{name}`" for name in paths],
                "",
            ]
        ),
        encoding="utf-8",
    )
    paths["benchmark_report.md"] = str(report_path)

    return paths
