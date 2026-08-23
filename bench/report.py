"""Aggregation and publication-ready rendering of benchmark results.

The report format follows one rule: **every headline number must be
reconstructible from the per-task rows printed underneath it.** Aggregates
carry the count they were computed over, the excluded tasks are listed with
their reason, and nothing that failed an integrity gate is folded into a
speedup average.
"""

from __future__ import annotations

import json
import math
import statistics
from typing import Any, Dict, Iterable, List, Optional, Sequence

from bench.spec import SuiteReport, TaskRecord

# A task counts as "optimized" (PIE's %Opt) when it is at least this much
# faster. PIE uses >10%; we keep the same threshold and say so.
OPT_THRESHOLD = 1.10


def _finite(values: Iterable[float]) -> List[float]:
    return [v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v > 0]


def geometric_mean(values: Sequence[float]) -> float:
    vals = _finite(values)
    if not vals:
        return float("nan")
    return math.exp(statistics.fmean(math.log(v) for v in vals))


def aggregate(records: Sequence[TaskRecord], *, noise_band: float = 1.0) -> Dict[str, Any]:
    """Aggregate per-task rows.

    ``noise_band`` is the machine's measured identical-code ratio. A task is
    only credited as "optimized" when it beats BOTH the %Opt threshold and the
    noise floor — otherwise the headline number is just reporting thermal
    drift with extra steps.
    """
    threshold = max(OPT_THRESHOLD, float(noise_band or 1.0))
    total = len(records)
    counted = [r for r in records if r.counted]
    excluded = [r for r in records if not r.counted]

    speedups = [r.speedup for r in counted]
    mems = [r.memory_ratio for r in counted]
    ratios_after = _finite([r.ratio_to_reference for r in counted])
    ratios_before = _finite([
        r.reference.get("baseline_ratio", float("nan")) for r in records
    ])

    optimized = [r for r in counted if r.speedup >= threshold]
    regressed = [r for r in counted if r.speedup < 0.95]

    llm_calls = sum(int(r.budget.get("llm_calls") or 0) for r in records)
    tokens = sum(int(r.budget.get("tokens") or 0) for r in records)
    cost = sum(float(r.budget.get("cost_usd") or 0.0) for r in records)
    wall = sum(float(r.budget.get("wall_sec") or 0.0) for r in records)

    verdicts: Dict[str, int] = {}
    for r in records:
        v = str(r.integrity.get("verdict", "unknown"))
        verdicts[v] = verdicts.get(v, 0) + 1

    correct = [r for r in records if r.optimized.get("all_pass")]

    return {
        "tasks_total": total,
        "tasks_counted": len(counted),
        "tasks_excluded": len(excluded),
        "correctness_rate": (len(correct) / total) if total else 0.0,
        "integrity_verdicts": verdicts,
        "pct_opt": (len(optimized) / total) if total else 0.0,
        "pct_opt_threshold": threshold,
        "pct_opt_threshold_source": (
            "noise floor" if threshold > OPT_THRESHOLD else "PIE >10% convention"
        ),
        "noise_band": float(noise_band or 1.0),
        "within_noise": [r.task_id for r in counted if 1.0 < r.speedup < threshold],
        "speedup_mean": statistics.fmean(speedups) if speedups else float("nan"),
        "speedup_geomean": geometric_mean(speedups),
        "speedup_median": statistics.median(speedups) if speedups else float("nan"),
        "speedup_max": max(speedups) if speedups else float("nan"),
        "regressions": len(regressed),
        "memory_ratio_geomean": geometric_mean(mems),
        "ratio_to_reference_before": geometric_mean(ratios_before) if ratios_before else float("nan"),
        "ratio_to_reference_after": geometric_mean(ratios_after) if ratios_after else float("nan"),
        "llm_calls_total": llm_calls,
        "tokens_approx_total": tokens,
        "cost_usd_est_total": round(cost, 4),
        "optimizer_wall_sec_total": round(wall, 2),
        "excluded_tasks": [
            {"task_id": r.task_id, "verdict": r.integrity.get("verdict"),
             "reasons": r.notes}
            for r in excluded
        ],
    }


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "—"
        return f"{value:.{digits}f}{suffix}"
    return str(value)


def _pct(value: Any, digits: int = 1) -> str:
    if not isinstance(value, (int, float)) or math.isnan(value):
        return "—"
    return f"{100.0 * value:.{digits}f}%"


def render_markdown(report: SuiteReport, *, include_diffs: bool = False) -> str:
    agg = report.aggregates or aggregate(report.records)
    env = report.env or {}
    cfg = report.config or {}

    lines: List[str] = []
    lines.append(f"# {report.suite} — `{report.optimizer}`")
    lines.append("")
    lines.append(
        f"**Tier:** {report.tier} · **Tasks:** {agg['tasks_total']} · "
        f"**Repeats/measurement:** {cfg.get('repeats', '?')} · "
        f"**Schema:** `{report.schema}`"
    )
    lines.append("")

    llm_cfg = (cfg.get("llm") or {}) if isinstance(cfg.get("llm"), dict) else {}
    if llm_cfg.get("backend") == "mock" or cfg.get("suite_status") in {"planned", "experimental"}:
        reasons = []
        if llm_cfg.get("backend") == "mock":
            reasons.append("the LLM backend is `mock` (deterministic stub, not a model)")
        if cfg.get("suite_status") in {"planned", "experimental"}:
            reasons.append(f"the suite status is `{cfg.get('suite_status')}`")
        lines.append(
            "> ⚠️ **Not a publishable result**: " + "; ".join(reasons) +
            ". This run exercises the pipeline, it does not measure it."
        )
        lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("| Metric | Value | Over |")
    lines.append("|---|---|---|")
    lines.append(f"| Correctness (visible + held-out) | {_pct(agg['correctness_rate'])} | {agg['tasks_total']} tasks |")
    thr = agg.get("pct_opt_threshold", OPT_THRESHOLD)
    lines.append(
        f"| %Opt (≥{thr:.2f}x, {agg.get('pct_opt_threshold_source', '')}) | "
        f"{_pct(agg['pct_opt'])} | {agg['tasks_total']} tasks |"
    )
    lines.append(f"| Speedup (geomean) | {_fmt(agg['speedup_geomean'])}x | {agg['tasks_counted']} counted |")
    lines.append(f"| Speedup (median) | {_fmt(agg['speedup_median'])}x | {agg['tasks_counted']} counted |")
    lines.append(f"| Speedup (max) | {_fmt(agg['speedup_max'])}x | — |")
    lines.append(f"| Regressions (<0.95x) | {agg['regressions']} | {agg['tasks_counted']} counted |")
    lines.append(f"| Memory ratio (geomean) | {_fmt(agg['memory_ratio_geomean'])}x | {agg['tasks_counted']} counted |")
    if not math.isnan(agg.get("ratio_to_reference_before", float("nan"))):
        lines.append(
            f"| Ratio to human reference | {_fmt(agg['ratio_to_reference_before'])}x → "
            f"**{_fmt(agg['ratio_to_reference_after'])}x** | geomean |"
        )
    lines.append(f"| Excluded by integrity gates | {agg['tasks_excluded']} | {agg['tasks_total']} tasks |")
    lines.append("")

    if agg.get("within_noise"):
        lines.append("")
        lines.append(
            f"> {len(agg['within_noise'])} task(s) improved but stayed inside the "
            f"{agg.get('noise_band', 1.0):.2f}x noise floor and are **not** counted as "
            f"optimized: {', '.join('`' + t + '`' for t in agg['within_noise'])}"
        )
    lines.append("")
    lines.append("## Cost")
    lines.append("")
    lines.append("| LLM calls | Tokens (approx) | Est. USD | Optimizer wall-clock |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| {agg['llm_calls_total']} | {agg['tokens_approx_total']:,} | "
        f"${agg['cost_usd_est_total']:.4f} | {agg['optimizer_wall_sec_total']:.1f}s |"
    )
    lines.append("")

    lines.append("## Environment")
    lines.append("")
    for key in ("cpu_model", "platform", "python", "implementation", "cpu_count",
                "governor", "turbo_disabled", "loadavg_1m"):
        if key in env:
            lines.append(f"- **{key}**: {env[key]}")
    if env.get("governor") not in (None, "performance", "unknown"):
        lines.append(
            f"- ⚠️ CPU governor is `{env.get('governor')}`; results are indicative, "
            "not publication-grade. Use `performance` and disable turbo."
        )
    noise = env.get("noise_calibration") or {}
    if noise.get("available"):
        lines.append(
            f"- **measurement noise floor**: identical code measured "
            f"{noise['identical_code_ratio']:.3f}x against itself → "
            f"{noise['interpretation']}"
        )
    if cfg.get("git_commit"):
        lines.append(f"- **git commit**: `{cfg['git_commit']}`")
    if cfg.get("llm"):
        lines.append(f"- **LLM**: `{json.dumps(cfg['llm'])}`")
    lines.append("")

    lines.append("## Per-task results")
    lines.append("")
    lines.append("| Task | Baseline p50 | Optimized p50 | Speedup | Mem | Tests | Integrity | LLM cost |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in report.records:
        b = r.baseline
        o = r.optimized
        tests = f"{o.get('tests_passed', 0)}/{o.get('tests_total', 0)}"
        verdict = r.integrity.get("verdict", "?")
        mark = {"clean": "✅", "note": "ℹ️", "suspect": "⚠️",
                "rejected": "❌"}.get(verdict, "?")
        lines.append(
            f"| `{r.task_id}` "
            f"| {_fmt(b.get('latency_ms_mean'))} ± {_fmt(b.get('latency_ms_std'))} ms "
            f"| {_fmt(o.get('latency_ms_mean'))} ± {_fmt(o.get('latency_ms_std'))} ms "
            f"| **{_fmt(r.speedup)}x** "
            f"| {_fmt(r.memory_ratio)}x "
            f"| {tests} "
            f"| {mark} {verdict} "
            f"| {r.budget.get('llm_calls', 0)} calls / {r.budget.get('tokens', 0):,} tok |"
        )
    lines.append("")

    quality_rows = [r for r in report.records if (r.optimized.get("quality") or {}).get("baseline") is not None]
    if quality_rows:
        lines.append("## Objective quality (tier 3)")
        lines.append("")
        lines.append("| Task | Objective | Baseline | Optimized | Better? |")
        lines.append("|---|---|---|---|---|")
        for r in quality_rows:
            q = r.optimized["quality"]
            direction = "higher is better" if q.get("higher_is_better") else "lower is better"
            improved = q.get("improved")
            verdict = "✅ yes" if improved else ("— no change" if improved is None else "❌ no")
            lines.append(
                f"| `{r.task_id}` | {direction} | {_fmt(q.get('baseline'), 4)} | "
                f"{_fmt(q.get('optimized'), 4)} | {verdict} |"
            )
        lines.append("")
        lines.append(
            "> Feasibility is recomputed inside the probe, independently of the task "
            "code: an infeasible solution scores ±inf and can never win."
        )
        lines.append("")

    flagged = [r for r in report.records
               if r.integrity.get("verdict") != "clean" or r.integrity.get("findings")]
    if flagged:
        lines.append("## Integrity findings")
        lines.append("")
        for r in flagged:
            lines.append(f"- `{r.task_id}` → **{r.integrity.get('verdict')}**")
            for finding in r.integrity.get("findings", []):
                detail = f" ({finding['detail']})" if finding.get("detail") else ""
                lines.append(f"  - `{finding['check']}`: {finding['reason']}{detail}")
        lines.append("")

    if include_diffs:
        lines.append("## Diffs")
        lines.append("")
        for r in report.records:
            if r.diff.strip():
                lines.append(f"<details><summary><code>{r.task_id}</code></summary>")
                lines.append("")
                lines.append("```diff")
                lines.append(r.diff.rstrip())
                lines.append("```")
                lines.append("")
                lines.append("</details>")
                lines.append("")

    lines.append("## How to reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append(cfg.get("command", "python -m bench.runner run --help"))
    lines.append("```")
    lines.append("")
    lines.append(
        "> Speedup is `baseline_mean_p50 / optimized_mean_p50`, each measured in a "
        "fresh subprocess, repeated across runs; the ± column is the cross-run "
        "standard deviation. Tasks whose integrity verdict is not `clean` are "
        "listed but excluded from every aggregate."
    )
    return "\n".join(lines)


def render_comparison(reports: Sequence[SuiteReport]) -> str:
    """Side-by-side table across optimizer configurations (incl. ablations)."""
    if not reports:
        return "No reports."
    suite = reports[0].suite
    lines = [f"# {suite} — optimizer comparison", "",
             "| Optimizer | %Opt | Speedup geomean | Correctness | Clean | Tokens | Est. USD |",
             "|---|---|---|---|---|---|---|"]
    for rep in reports:
        agg = rep.aggregates or aggregate(rep.records)
        clean = agg["integrity_verdicts"].get("clean", 0)
        lines.append(
            f"| `{rep.optimizer}` | {_pct(agg['pct_opt'])} | "
            f"{_fmt(agg['speedup_geomean'])}x | {_pct(agg['correctness_rate'])} | "
            f"{clean}/{agg['tasks_total']} | {agg['tokens_approx_total']:,} | "
            f"${agg['cost_usd_est_total']:.4f} |"
        )
    lines.append("")
    lines.append(
        "> Ablation rows share the task set, the budget and the machine; the only "
        "difference is the disabled component."
    )
    return "\n".join(lines)


def render_task_card(record: TaskRecord) -> str:
    """The per-task audit card from the benchmark plan."""
    b, o = record.baseline, record.optimized
    lines = [
        f"### {record.task_id}",
        "",
        f"- **Original**: {_fmt(b.get('latency_ms_mean'))} ms p50, "
        f"{_fmt(b.get('mem_peak_mb_mean'))} MB peak, "
        f"{b.get('tests_passed', 0)}/{b.get('tests_total', 0)} tests pass",
        f"- **{record.optimizer}**: {_fmt(o.get('latency_ms_mean'))} ms "
        f"({_pct(1.0 - (o.get('latency_ms_mean') or 0) / (b.get('latency_ms_mean') or 1))} faster), "
        f"{_fmt(o.get('mem_peak_mb_mean'))} MB, "
        f"{o.get('tests_passed', 0)}/{o.get('tests_total', 0)} tests pass, "
        f"{record.budget.get('tokens', 0):,} tokens, "
        f"{_fmt(record.budget.get('wall_sec'), 1)}s wall",
        f"- **Repeats**: {record.repeats} (mean ± std reported)",
        f"- **Integrity**: {record.integrity.get('verdict')} "
        f"({len(record.integrity.get('findings', []))} findings)",
    ]
    if record.notes:
        lines.append(f"- **Notes**: {'; '.join(record.notes)}")
    return "\n".join(lines)
