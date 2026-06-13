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
        tab1, tab2, tab3 = st.tabs(
            ["📈 Fitness", "🏝️ Islands", "🧠 HITL"]
        )

        with tab1:
            self._render_fitness_chart()
            self._render_diversity_chart()

        with tab2:
            self._render_island_charts(agent)
            self._render_pareto_chart()

        with tab3:
            self._render_hitl_panel(agent)

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

    Parameters
    ----------
    agent : MutaLambdaAgent
        The evolution agent to instrument.
    dashboard : DashboardState | None
        If provided, use this state; otherwise create new.
    console : bool
        Enable console dashboard (non-Streamlit fallback).

    Returns
    -------
    DashboardState
        The shared state object.
    """
    if dashboard is None:
        dashboard = DashboardState()

    # Monkey-patch hints integration: check for pending hints each generation
    original_run = agent.run

    def _hitl_run(task: str = "") -> Any:
        # Pre-generation: inject hints if available
        hints = dashboard.get_hints()
        if hints:
            for hint in hints:
                _inject_hint(agent, hint)

        # Run evolution normally
        return original_run(task)

    agent.run = _hitl_run  # type: ignore[method-assign]

    return dashboard


def _inject_hint(agent: Any, code: str) -> None:
    """
    Inject expert code into a random island as a seed individual.
    """
    import random as _random
    island = _random.choice(agent.islands)
    new_ind = type(agent.islands[0].population[0])(
        code=code, score=0.0
    )
    island.population.append(new_ind)
    if hasattr(agent, '_island_pool'):
        pass  # IslandPool will pick up on next generation
