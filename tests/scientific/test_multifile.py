"""Tests multi-file (MF-*)."""
from muta_ext.uast.call_graph import extract_call_graph_multi_file, extract_call_graph_from_source
import pytest


class TestMultiFile:
    """Tests para extract_call_graph_multi_file."""

    def test_mf01_directory(self, tmp_path):
        (tmp_path / "a.py").write_text("from b import h\ndef f(n): return h(n)")
        (tmp_path / "b.py").write_text("def h(n): return n + 1")
        g = extract_call_graph_multi_file([str(tmp_path / "a.py"), str(tmp_path / "b.py")])
        assert "f" in {n.name for n in g.nodes.values()} and "h" in {n.name for n in g.nodes.values()}

    def test_mf02_explicit(self, tmp_path):
        (tmp_path / "x.py").write_text("def f(): return 1")
        (tmp_path / "y.py").write_text("def g(): return 2")
        g = extract_call_graph_multi_file([str(tmp_path / "x.py"), str(tmp_path / "y.py")])
        names = {n.name for n in g.nodes.values()}
        assert "f" in names and "g" in names

    def test_mf03_stable(self, tmp_path):
        (tmp_path / "a.py").write_text("def f(): return 1")
        (tmp_path / "b.py").write_text("def g(): return 2")
        g1 = extract_call_graph_multi_file([str(tmp_path / "a.py"), str(tmp_path / "b.py")])
        g2 = extract_call_graph_multi_file([str(tmp_path / "a.py"), str(tmp_path / "b.py")])
        assert len(g1.nodes) == len(g2.nodes)

    def test_mf04_invalid(self):
        g = extract_call_graph_multi_file(["/nonexistent/file.py"])
        assert len(g.nodes) == 0

    def test_mf05_single_backward(self, tmp_path):
        code = "def f(x): return x + 1\ndef g(x): return f(x) * 2"
        (tmp_path / "s.py").write_text(code)
        mg = extract_call_graph_multi_file([str(tmp_path / "s.py")])
        sg = extract_call_graph_from_source(code)
        assert "f" in {n.name for n in mg.nodes.values()}
        assert "f" in {n.name for n in sg.nodes.values()}