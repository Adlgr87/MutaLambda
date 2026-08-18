"""
MutaLambda Run Dashboard — Streamlit interface for inspecting completed runs.

Usage:
  streamlit run dashboard_run.py
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

# Streamlit is required for this dashboard
if st is None:
    raise ImportError("streamlit is required: pip install streamlit")

CHECKPOINT_DIR = Path("checkpoints")


def list_runs() -> list[Path]:
    """List run directories (run_*) sorted by modification time, newest first."""
    if not CHECKPOINT_DIR.exists():
        return []
    runs = sorted(
        [d for d in CHECKPOINT_DIR.iterdir() if d.is_dir() and d.name.startswith("run_")],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    return runs


def load_run_manifest(run_dir: Path) -> dict:
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return {}


def load_fitness_history(run_dir: Path) -> tuple[list[int], list[float]]:
    path = run_dir / "fitness_history.json"
    if not path.exists():
        return [], []
    data = json.loads(path.read_text())
    return (
        list(range(len(data.get("global_best_history", [])))),
        data.get("global_best_history", []),
    )


def load_lineage(run_dir: Path) -> dict:
    path = run_dir / "lineage.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


# ── Streamlit UI ──

st.set_page_config(page_title="MutaLambda Dashboard", layout="wide")
st.title("🧬 MutaLambda Run Dashboard")

runs = list_runs()

if not runs:
    st.info("No runs found. Run `muta_lambda quick my_script.py` first.")
    st.stop()

# Sidebar: run selector
with st.sidebar:
    st.header("🗂 Runs")
    run_names = [r.name for r in runs]
    selected = st.selectbox("Selecciona un run", run_names, index=0)
    selected_run = next(r for r in runs if r.name == selected)

manifest = load_run_manifest(selected_run)
fitness_gens, fitness_scores = load_fitness_history(selected_run)
lineage = load_lineage(selected_run)

# ── Tabs ──
tab_overview, tab_fitness, tab_lineage, tab_code = st.tabs(
    ["📋 Overview", "📈 Fitness", "🌳 Lineage", "💻 Best Code"]
)

with tab_overview:
    if manifest:
        st.caption(f"**Run ID:** `{manifest.get('run_id', '—')}`")
        st.caption(f"**Task:** {manifest.get('task', '—')}")
        metrics: dict = manifest.get("metrics", {})
        if metrics:
            cols = st.columns(4)
            cols[0].metric("Best Score", f"{metrics.get('best_score', 0):.4f}")
            cols[1].metric("Generations", metrics.get("total_generations", 0))
            cols[2].metric("Total Time", f"{metrics.get('total_time_sec', 0):.1f}s")
            cols[3].metric("Avg Gen Time", f"{metrics.get('avg_generation_time_sec', 0):.2f}s")
        if manifest.get("config"):
            with st.expander("Config"):
                st.json(manifest["config"])
    else:
        st.warning("No manifest found.")

with tab_fitness:
    if fitness_scores:
        st.line_chart(fitness_scores)
        latest = fitness_scores[-1] if fitness_scores else 0
        st.caption(f"Última puntuación: **{latest:.4f}** (mejor global)")
    else:
        st.info("No fitness history available.")

with tab_lineage:
    if lineage:
        nodes: dict = lineage.get("nodes", {})
        st.caption(f"Total nodes: **{len(nodes)}**")
        st.caption(f"Max depth: **{lineage.get('max_depth', '—')}**")
        st.caption(f"Resurrections: **{lineage.get('resurrection_count', 0)}**")
        if nodes:
            node_ids = sorted(nodes.keys())
            selected_node = st.selectbox("Node ID", node_ids)
            node = nodes[selected_node]
            st.json({k: v for k, v in node.items() if k != "code"})
    else:
        st.info("No lineage data available.")

with tab_code:
    best_path = selected_run / "best_solution.py"
    if best_path.exists():
        code = best_path.read_text()
        st.code(code, language="python")
        if (selected_run / "best_solution.patch").exists():
            patch = (selected_run / "best_solution.patch").read_text()
            with st.expander("📄 Patch"):
                st.code(patch, language="diff")
    else:
        st.info("No best solution found for this run.")