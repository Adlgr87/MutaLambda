"""Contract tests for the engine -> EventBus -> dashboard wiring.

These guard the class of bug found during the v5 scrutiny pass: the dashboard
subscribed to ``GenerationCompleted`` and read ``diversity`` / ``island_scores``
/ ``pareto_size`` from the payload, but the agent never published those keys, so
the diversity, per-island and Pareto charts were permanently empty while every
test still passed.
"""

from __future__ import annotations

import threading

import pytest

from dashboard import DashboardState, integrate_hitl
from mutalambda_core.event_bus import (
    GENERATION_COMPLETED,
    RUN_COMPLETED,
    CommandQueue,
    EventBus,
)


class _FakeAgent:
    """Minimal stand-in exposing the attributes `integrate_hitl` looks for."""

    def __init__(self) -> None:
        self.event_bus = EventBus()
        self.commands = CommandQueue()
        self.hints: list[str] = []

    def run(self, task: str = "", **kwargs):
        return f"ran:{task}"

    def inject_hint(self, code: str) -> None:
        self.hints.append(code)


# ---------------------------------------------------------------------------
# DashboardState
# ---------------------------------------------------------------------------


def test_record_generation_populates_every_series():
    state = DashboardState()
    state.record_generation(
        gen=1,
        best_score=0.75,
        diversity=0.42,
        pareto_frontier_size=5,
        island_data={0: 0.7, 1: 0.5},
    )
    snap = state.snapshot()
    assert snap["gen_numbers"] == [1]
    assert snap["global_best"] == [0.75]
    assert snap["diversity"] == [0.42]
    assert snap["pareto_size"] == [5]
    assert snap["island_bests"] == {0: [0.7], 1: [0.5]}


def test_record_generation_is_thread_safe():
    state = DashboardState(max_history=10_000)

    def writer(offset: int) -> None:
        for i in range(500):
            state.record_generation(offset + i, 0.1, 0.2, 1, {0: 1.0})

    threads = [threading.Thread(target=writer, args=(o,)) for o in (0, 1000, 2000)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = state.snapshot()
    assert len(snap["gen_numbers"]) == 1500
    assert len(snap["island_bests"][0]) == 1500


def test_review_decisions_are_recorded():
    state = DashboardState()
    state.record_review("def a(): ...", approved=True)
    state.record_review("def b(): ...", approved=False)
    snap = state.snapshot()
    assert snap["approved_variants"] == ["def a(): ..."]
    assert snap["rejected_variants"] == ["def b(): ..."]


def test_get_hints_drains_the_queue():
    state = DashboardState()
    state.add_hint("hint-1")
    state.add_hint("hint-2")
    assert state.get_hints() == ["hint-1", "hint-2"]
    assert state.get_hints() == []


# ---------------------------------------------------------------------------
# EventBus <-> dashboard contract
# ---------------------------------------------------------------------------


def test_integrate_hitl_consumes_generation_completed_payload():
    agent = _FakeAgent()
    state = integrate_hitl(agent, console=False)

    agent.event_bus.emit(
        GENERATION_COMPLETED,
        {
            "generation": 3,
            "best_score": 0.9,
            "diversity": 0.31,
            "pareto_size": 4,
            "island_scores": {0: 0.9, 1: 0.8},
        },
        run_id="r1",
        generation=3,
    )

    snap = state.snapshot()
    assert snap["gen_numbers"] == [3]
    assert snap["global_best"] == [0.9]
    assert snap["diversity"] == [0.31]
    assert snap["pareto_size"] == [4]
    assert snap["island_bests"] == {0: [0.9], 1: [0.8]}


def test_run_completed_is_consumed_without_error():
    agent = _FakeAgent()
    integrate_hitl(agent, console=False)
    agent.event_bus.emit(
        RUN_COMPLETED,
        {"best_score": 1.0, "elapsed_sec": 0.1, "generation_completed": 2},
        run_id="r1",
        generation=2,
    )
    assert agent.event_bus.counts()[RUN_COMPLETED] == 1


def test_hints_and_control_plane_reach_the_command_queue():
    agent = _FakeAgent()
    state = integrate_hitl(agent, console=False)

    state.add_hint("def faster(): ...")
    state.set_paused(True)  # type: ignore[attr-defined]
    state.request_stop()  # type: ignore[attr-defined]

    commands = [c["command"] for c in agent.commands.drain()]
    assert commands == ["inject_hint", "pause", "stop"]
    assert agent.commands.stop_requested is True


def test_hitl_run_wrapper_injects_pending_hints():
    agent = _FakeAgent()
    state = integrate_hitl(agent, console=False)
    state.add_hint("def seeded(): ...")
    agent.commands.drain()

    assert agent.run(task="go") == "ran:go"
    assert agent.hints == ["def seeded(): ..."]


# ---------------------------------------------------------------------------
# Agent-side contract: the publisher must emit what the consumer reads.
# ---------------------------------------------------------------------------


def test_agent_publishes_every_key_the_dashboard_reads():
    """Static contract check against muta_lambda/agent.py.

    A full generation needs an LLM + sandbox, so instead of running one we
    assert that the GenerationCompleted emission site carries the keys that
    `dashboard.integrate_hitl` reads. If someone renames or drops one, this
    fails instead of silently blanking the charts.
    """
    import ast
    import inspect

    import muta_lambda.agent as agent_mod

    tree = ast.parse(inspect.getsource(agent_mod))
    published: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "emit"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        name = first.id if isinstance(first, ast.Name) else getattr(first, "attr", None)
        if name != "GENERATION_COMPLETED":
            continue
        if len(node.args) > 1 and isinstance(node.args[1], ast.Dict):
            published |= {
                k.value for k in node.args[1].keys if isinstance(k, ast.Constant)
            }

    assert published, "no GENERATION_COMPLETED emission with a literal payload found"
    required = {"generation", "best_score", "diversity", "island_scores", "pareto_size"}
    missing = required - published
    assert not missing, f"agent does not publish keys the dashboard reads: {sorted(missing)}"


@pytest.mark.parametrize("module", ["dashboard", "dashboard_run"])
def test_dashboard_modules_import_cleanly(module):
    """Both Streamlit apps must be importable (they are listed in py-modules)."""
    import importlib

    assert importlib.import_module(module) is not None
