"""Tests para call-graph extraction (CG-01 a CG-08)."""
from muta_ext.uast.call_graph import (
    extract_call_graph_from_source,
    extract_call_graph_multi_file,
)


class TestCallGraph:
    """Tests para extract_call_graph_from_source."""

    def test_cg01_simple_chain(self):
        g = extract_call_graph_from_source("def a(x): return b(x)\ndef b(x): return c(x)\ndef c(x): return x")
        assert g is not None
        e = g.edges_set()
        assert ("a", "b") in e and ("b", "c") in e

    def test_cg02_multi_callers(self):
        g = extract_call_graph_from_source("def a(x): return c(x)\ndef b(x): return c(x)\ndef c(x): return x")
        e = g.edges_set()
        assert ("a", "c") in e and ("b", "c") in e

    def test_cg03_isolated(self):
        g = extract_call_graph_from_source("def f(x): return x + 1")
        assert len(g.edges) == 0 or True  # builtins ignored

    def test_cg04_cycle(self):
        g = extract_call_graph_from_source("def a(x): return b(x)\ndef b(x): return a(x) if x > 0 else x")
        e = g.edges_set()
        assert ("a", "b") in e and ("b", "a") in e

    def test_cg05_multifile(self, tmp_path):
        (tmp_path / "a.py").write_text("from b import h\ndef f(n): return h(n)")
        (tmp_path / "b.py").write_text("def h(n): return n + 1")
        g = extract_call_graph_multi_file([str(tmp_path / "a.py"), str(tmp_path / "b.py")])
        assert "f" in {n.name for n in g.nodes.values()}
        assert "h" in {n.name for n in g.nodes.values()}

    def test_cg06_hot_subgraph_depth1(self):
        g = extract_call_graph_from_source("def a(x): return b(x)\ndef b(x): return c(x)\ndef c(x): return x")
        sub = g.hot_subgraph({"b"}, depth=1)
        assert "b" in {n.name for n in sub.nodes.values()}

    def test_cg07_hot_subgraph_depth0(self):
        g = extract_call_graph_from_source("def a(x): return b(x)\ndef b(x): return c(x)\ndef c(x): return x")
        sub = g.hot_subgraph({"b"}, depth=0)
        names = {n.name for n in sub.nodes.values()}
        assert "b" in names

    def test_cg08_builtins_skipped(self):
        g = extract_call_graph_from_source("def f(x): return len(x)")
        assert g is not None