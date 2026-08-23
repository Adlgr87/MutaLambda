"""End-to-end runner behaviour: honest baselines, real speedups, clean reports."""

from __future__ import annotations

import json

import pytest

from bench.optimizers import (
    Budget, OptimizerBackend, build_optimizer, CountingLLM, LLMSettings,
)
from bench.report import aggregate, render_comparison, render_markdown
from bench.runner import run_suite, run_task, write_artifacts
from bench.spec import BenchTask, OptimizationOutcome
from bench.suites import REGISTRY, load_tasks

pytestmark = pytest.mark.bench

FAST_BUDGET = Budget(generations=1, islands=1, population=4, wall_sec=30.0,
                     max_llm_calls=1, variants=2)


class KnownGoodOptimizer(OptimizerBackend):
    """Applies the textbook rewrite for one smoke task."""

    name = "test-known-good"

    def optimize(self, task: BenchTask, budget: Budget) -> OptimizationOutcome:
        return OptimizationOutcome(
            code="def sum_squares(n):\n    return n * (n + 1) * (2 * n + 1) // 6\n",
            optimizer=self.name, wall_sec=0.01, llm_calls=2, tokens=1200,
        )


class CheatingOptimizer(OptimizerBackend):
    """Returns a lookup table built from the visible tests."""

    name = "test-cheater"

    def optimize(self, task: BenchTask, budget: Budget) -> OptimizationOutcome:
        table = {tuple(t["args"])[0]: t["expected"] for t in task.visible_tests}
        entries = ", ".join(f"{k}: {v}" for k, v in table.items())
        return OptimizationOutcome(
            code=(f"_T = {{{entries}}}\n\n"
                  "def sum_squares(n):\n"
                  "    return _T.get(n, 0)\n"),
            optimizer=self.name,
        )


def _sum_squares_task() -> BenchTask:
    return next(t for t in load_tasks("smoke") if t.task_id == "smoke/sum_squares")


def test_baseline_optimizer_reports_no_speedup():
    """Identity must not manufacture a win.

    The band is wide because CI machines are noisy — that is exactly why the
    harness measures and publishes a noise floor instead of pretending a 1.1x
    on a shared runner means something.
    """
    task = _sum_squares_task()
    record = run_task(task, build_optimizer("baseline"), FAST_BUDGET, repeats=3)
    assert 0.4 < record.speedup < 2.5, f"identity produced {record.speedup}x"
    assert record.integrity["verdict"] != "rejected"
    assert record.optimized["all_pass"]
    assert record.diff == ""


def test_real_optimization_is_measured_and_counted():
    task = _sum_squares_task()
    record = run_task(task, KnownGoodOptimizer(), FAST_BUDGET, repeats=3)
    assert record.integrity["verdict"] != "rejected"
    assert record.speedup > 5.0, f"closed form should crush the loop, got {record.speedup}"
    assert record.optimized["all_pass"]
    assert record.diff.startswith("---")
    assert record.budget["tokens"] == 1200


def test_cheating_optimizer_is_caught_and_not_counted():
    task = _sum_squares_task()
    record = run_task(task, CheatingOptimizer(), FAST_BUDGET, repeats=2)
    assert not record.counted
    assert record.integrity["verdict"] == "rejected"
    checks = {f["check"] for f in record.integrity["findings"]}
    assert {"hardcoded_answers", "holdout"} & checks


def test_aggregate_excludes_uncounted_tasks():
    task = _sum_squares_task()
    good = run_task(task, KnownGoodOptimizer(), FAST_BUDGET, repeats=2)
    bad = run_task(task, CheatingOptimizer(), FAST_BUDGET, repeats=2)
    agg = aggregate([good, bad])
    assert agg["tasks_total"] == 2
    assert not bad.counted, "a hardcoded lookup table must never be counted"
    assert agg["tasks_excluded"] >= 1
    assert any(t["verdict"] == "rejected" for t in agg["excluded_tasks"])


def test_noise_band_suppresses_marginal_wins():
    task = _sum_squares_task()
    record = run_task(task, build_optimizer("baseline"), FAST_BUDGET, repeats=2)
    record.speedup = 1.12  # inside a 1.30x noise band
    agg = aggregate([record], noise_band=1.30)
    assert agg["pct_opt"] == 0.0
    assert agg["within_noise"] == [record.task_id]
    assert agg["pct_opt_threshold"] == 1.30


def test_run_suite_and_report_render(tmp_path):
    report = run_suite("smoke", "baseline", repeats=2, limit=2, calibrate=False,
                       verbose=False)
    assert len(report.records) == 2
    md = render_markdown(report)
    assert "## Headline" in md
    assert "## How to reproduce" in md
    assert "noise" in md.lower() or "Speedup" in md

    root = write_artifacts(report, tmp_path)
    saved = json.loads((root / "report.json").read_text())
    assert saved["schema"] == "muta-bench/1"
    assert len(saved["records"]) == 2
    assert (root / "report.md").exists()
    assert (root / "task_cards.md").exists()


def test_comparison_table_across_optimizers():
    a = run_suite("smoke", "baseline", repeats=1, limit=1, calibrate=False, verbose=False)
    b = run_suite("smoke", "baseline", repeats=1, limit=1, calibrate=False, verbose=False)
    b.optimizer = "mutalambda:deep-no_hfc"
    table = render_comparison([a, b])
    assert "baseline" in table and "no_hfc" in table


def test_mock_llm_run_is_labelled_unpublishable():
    llm = LLMSettings(backend="mock", model="stub")
    report = run_suite("smoke", "llm-oneshot", repeats=1, limit=1, llm=llm,
                       calibrate=False, verbose=False)
    md = render_markdown(report)
    assert "Not a publishable result" in md


# ── optimizer spec parsing ─────────────────────────────────────────────────

def test_optimizer_spec_parsing():
    assert build_optimizer("baseline").name == "baseline"
    assert build_optimizer("numpy").name == "numpy"
    assert build_optimizer("mutalambda:fast").name == "mutalambda:fast"
    assert build_optimizer("mutalambda:deep-no_hfc-no_thc").name == \
        "mutalambda:deep-no_hfc-no_thc"


def test_unknown_ablation_is_rejected_loudly():
    with pytest.raises(ValueError, match="unknown ablation"):
        build_optimizer("mutalambda:deep-no_magic")


def test_unknown_optimizer_is_rejected():
    with pytest.raises(ValueError, match="unknown optimizer"):
        build_optimizer("copilot")


def test_counting_llm_tracks_cost():
    counter = CountingLLM(lambda p: "x" * 400, max_calls=2,
                          usd_per_1k_prompt=1.0, usd_per_1k_completion=2.0)
    counter("y" * 800)
    counter("y" * 800)
    counter("y" * 800)  # over the cap
    assert counter.calls == 2
    assert counter.tokens > 0
    assert counter.cost_usd > 0


def test_every_registered_suite_declares_its_status():
    for name, meta in REGISTRY.items():
        assert meta["status"] in {"ready", "planned", "experimental"}, name
        assert meta["tier"] in {"tier1", "tier2", "tier3"}, name
        assert meta["summary"]
