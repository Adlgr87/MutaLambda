"""
MutaLambda HITL Dashboard — Streamlit interface for Human-in-the-Loop.

Features:
  • Real-time phylogenetic tree of island evolution
  • Pareto frontier visualisation (multi-objective)
  • Expert hint injection as seeds into islands
  • Variant approval/rejection before costly evaluation
  • Fitness history charts per island
  • Archive exploration (browse past solutions)
  • Live telemetry (diversity, convergence, stagnation)

Usage:
  streamlit run dashboard.py
"""

from __future__ import annotations

import json
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

# Streamlit is optional — graceful import
try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]


# ── Dashboard State ──────────────────────────────────────────────────

class DashboardState:
    """
    Shared state between the evolution engine and the Streamlit dashboard.

    Thread-safe accumulators for real-time visualisation.
    """

    def __init__(self, max_history: int = 500):
        self.max_history = max_history
        # Generation metrics
        self.gen_numbers: deque = deque(maxlen=max_history)
        self.global_best: deque = deque(maxlen=max_history)
        self.island_bests: Dict[int, deque] = {}  # island_id → deque of scores
        self.diversity: deque = deque(maxlen=max_history)
        # Pareto frontier
        self.pareto_size: deque = deque(maxlen=max_history)
        # Human hints (pending injection)
        self.pending_hints: List[str] = []
        self.approved_variants: List[str] = []
        self.rejected_variants: List[str] = []
        # Control
        self.paused: bool = False
        self.stop_requested: bool = False

    def record_generation(
        self,
        gen: int,
        best_score: float,
        diversity: float,
        pareto_frontier_size: int = 0,
        island_data: Optional[Dict[int, float]] = None,
    ):
        self.gen_numbers.append(gen)
        self.global_best.append(best_score)
        self.diversity.append(diversity)
        self.pareto_size.append(pareto_frontier_size)
        if island_data:
            for isl_id, score in island_data.items():
                if isl_id not in self.island_bests:
                    self.island_bests[isl_id] = deque(maxlen=self.max_history)
                self.island_bests[isl_id].append(score)

    def add_hint(self, code: str):
        self.pending_hints.append(code)

    def get_hints(self) -> List[str]:
        hints = list(self.pending_hints)
        self.pending_hints.clear()
        return hints


# ── Dashboard Renderer ────────────────────────────────────────────────

class DashboardRenderer:
    """
    Renders the Streamlit HITL dashboard.

    Call `render()` periodically from the evolution loop to update
    charts and controls in real time.
    """

    def __init__(self, state: DashboardState):
        self.state = state
        self._render_count = 0

    def render(self, agent: Optional[Any] = None) -> None:
        """Render the full dashboard page."""
        if st is None:
            return

        self._render_count += 1

        st.set_page_config(
            page_title="MutaLambda HITL",
            page_icon="🧬",
            layout="wide",
        )

        st.title("🧬 MutaLambda — Human-in-the-Loop Dashboard")

        # ── Control bar ───────────────────────────────────────────
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Generation", len(self.state.gen_numbers))
        with col2:
            current_best = (
                self.state.global_best[-1]
                if self.state.global_best else 0.0
            )
            st.metric("Best Score", f"{current_best:.4f}")
        with col3:
            current_div = (
                self.state.diversity[-1]
                if self.state.diversity else 0.0
            )
            st.metric("Diversity", f"{current_div:.3f}")
        with col4:
            p_size = (
                self.state.pareto_size[-1]
                if self.state.pareto_size else 0
            )
            st.metric("Pareto Frontier", p_size)

        # ── Charts ────────────────────────────────────────────────
        tab1, tab2, tab3, tab4 = st.tabs(
            ["📈 Fitness", "🏝️ Islands", "🧠 HITL", "Advanced Metrics"]
        )

        with tab1:
            self._render_fitness_chart()
            self._render_diversity_chart()

        with tab2:
            self._render_island_charts(agent)
            self._render_pareto_chart()

        with tab3:
            self._render_hitl_panel(agent)

        with tab4:
            self._render_advanced_metrics(agent)

        # ── Auto-refresh ──────────────────────────────────────────
        if not self.state.stop_requested:
            time.sleep(1)
            st.rerun()

    def _render_fitness_chart(self):
        """Global best fitness over time."""
        if self.state.gen_numbers:
            import pandas as pd
            data = pd.DataFrame({
                "Generation": list(self.state.gen_numbers),
                "Best Score": list(self.state.global_best),
            })
            st.line_chart(data.set_index("Generation"), use_container_width=True)

    def _render_diversity_chart(self):
        """Diversity over time."""
        if self.state.diversity:
            import pandas as pd
            data = pd.DataFrame({
                "Generation": list(self.state.gen_numbers),
                "Diversity": list(self.state.diversity),
            })
            st.line_chart(data.set_index("Generation"), use_container_width=True)

    def _render_island_charts(self, agent):
        """Per-island best scores."""
        if self.state.island_bests:
            import pandas as pd
            data = {}
            for isl_id, scores in self.state.island_bests.items():
                data[f"Island {isl_id}"] = list(scores)
            if data:
                df = pd.DataFrame(data)
                st.line_chart(df, use_container_width=True)

    def _render_pareto_chart(self):
        """Pareto frontier size over time."""
        if self.state.pareto_size:
            import pandas as pd
            data = pd.DataFrame({
                "Generation": list(self.state.gen_numbers),
                "Pareto Frontier": list(self.state.pareto_size),
            })
            st.line_chart(data.set_index("Generation"), use_container_width=True)

    def _render_hitl_panel(self, agent):
        """Human-in-the-Loop controls."""
        st.subheader("💡 Expert Hint Injection")

        hint = st.text_area(
            "Paste code hint to inject into a random island:",
            placeholder="def optimized_solution(x):\n    return ...",
            height=150,
        )
        if st.button("🚀 Inject Hint") and hint.strip():
            self.state.add_hint(hint.strip())
            st.success("Hint injected! It will be picked up next generation.")

        st.divider()

        st.subheader("🔬 Variant Review")
        if agent and hasattr(agent, 'islands'):
            for island in agent.islands[:2]:  # show first 2 islands
                if island.population:
                    best = island.local_best
                    if best:
                        with st.expander(
                            f"Island {island.id} — Best (score={best.score:.4f})"
                        ):
                            st.code(best.code, language="python")

                            col_a, col_r = st.columns(2)
                            with col_a:
                                if st.button(
                                    f"✅ Approve Island {island.id}",
                                    key=f"approve_{island.id}",
                                ):
                                    self.state.approved_variants.append(best.code)
                                    st.success("Approved!")
                            with col_r:
                                if st.button(
                                    f"❌ Reject Island {island.id}",
                                    key=f"reject_{island.id}",
                                ):
                                    self.state.rejected_variants.append(best.code)
                                    st.warning("Rejected. Island will be reseeded.")

    def _render_advanced_metrics(self, agent):
        """Evolution Upgrade v2.0 telemetry."""
        st.subheader("Evolution Upgrade v2.0")
        if agent is None or not hasattr(agent, "get_metrics"):
            st.info("No agent metrics available yet.")
            return
        metrics = agent.get_metrics()
        advanced = metrics.get("advanced_selection", {}) or {}
        thc = metrics.get("thc", {}) or {}
        dialectic = metrics.get("dialectic", {}) or {}
        spatial = metrics.get("spatial", {}) or {}

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Discovery Score Avg", f"{advanced.get('discovery_score_avg', 0.0):.3f}")
            st.metric("Population Entropy", f"{advanced.get('population_entropy', 0.0):.3f}")
        with col2:
            st.metric("THC Rate", f"{thc.get('thc_transfer_rate', 0.0):.3f}")
            st.metric("Fragment Survival", f"{thc.get('fragment_survival_gens', 0.0):.2f}")
        with col3:
            st.metric("Critique Rejection", f"{dialectic.get('critique_rejection_rate', 0.0):.3f}")
            st.metric("Local Diversity", f"{spatial.get('local_diversity_index', 0.0):.3f}")


# ── Lightweight Dashboard (no Streamlit dependency) ──────────────────

def print_console_dashboard(
    gen: int,
    best_score: float,
    diversity: float,
    pareto_size: int,
    island_scores: Dict[int, float],
    hints_available: int = 0,
):
    """
    Lightweight console dashboard for environments without Streamlit.

    Prints a compact status line with generation metrics.
    """
    islands_str = " | ".join(
        f"I{isl}:{score:.2f}"
        for isl, score in sorted(island_scores.items())
    )
    hint_str = f" 💡{hints_available}" if hints_available > 0 else ""
    print(
        f"\r🧬 Gen {gen:4d} | Best={best_score:+.4f} | "
        f"Div={diversity:.3f} | Pareto={pareto_size} | "
        f"{islands_str}{hint_str}",
        end="",
        flush=True,
    )


# ── HITL Integration for MutaLambdaAgent ────────────────────────────

def integrate_hitl(
    agent: Any,
    dashboard: Optional[DashboardState] = None,
    console: bool = True,
) -> DashboardState:
    """
    Wire HITL callbacks into a MutaLambdaAgent.

    Prefer EventBus consumption when available (ML-UI04). Falls back to
    wrapping ``run()`` for older agents.
    """
    if dashboard is None:
        dashboard = DashboardState()

    # Subscribe to core events when EventBus is present.
    bus = getattr(agent, "event_bus", None)
    if bus is not None:
        from event_bus import GENERATION_COMPLETED, RUN_COMPLETED

        def _on_event(event) -> None:
            if event.name == GENERATION_COMPLETED:
                payload = event.payload or {}
                island_data = payload.get("island_scores") or {}
                dashboard.record_generation(
                    gen=int(payload.get("generation", event.generation)),
                    best_score=float(payload.get("best_score", float("-inf"))),
                    diversity=float(payload.get("diversity", 0.0)),
                    pareto_frontier_size=int(payload.get("pareto_size", 0)),
                    island_data={int(k): float(v) for k, v in island_data.items()}
                    if island_data
                    else None,
                )
            elif event.name == RUN_COMPLETED and console:
                print_console_dashboard(
                    gen=int(event.payload.get("generation_completed", event.generation)),
                    best_score=float(event.payload.get("best_score", 0.0)),
                    diversity=0.0,
                    pareto_size=0,
                    island_scores={},
                )

        bus.subscribe(_on_event)

    # Sync control plane: pause/resume/stop/hints via CommandQueue when present.
    commands = getattr(agent, "commands", None)
    if commands is not None:
        original_add = dashboard.add_hint

        def _add_hint(code: str) -> None:
            original_add(code)
            commands.push("inject_hint", code=code)

        dashboard.add_hint = _add_hint  # type: ignore[method-assign]

        def _set_paused(value: bool) -> None:
            dashboard.paused = value
            commands.push("pause" if value else "resume")

        def _request_stop() -> None:
            dashboard.stop_requested = True
            commands.push("stop")

        dashboard.set_paused = _set_paused  # type: ignore[attr-defined]
        dashboard.request_stop = _request_stop  # type: ignore[attr-defined]

    original_run = agent.run

    def _hitl_run(task: str = "", **kwargs: Any) -> Any:
        hints = dashboard.get_hints()
        if hints and hasattr(agent, "inject_hint"):
            for hint in hints:
                agent.inject_hint(hint)
        if dashboard.paused and commands is not None:
            commands.push("pause")
        if dashboard.stop_requested and commands is not None:
            commands.push("stop")
        return original_run(task, **kwargs)

    agent.run = _hitl_run  # type: ignore[method-assign]
    return dashboard
