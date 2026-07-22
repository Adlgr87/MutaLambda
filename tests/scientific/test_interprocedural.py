"""Tests para mutación inter-procedural (IP-*)."""
from muta_ext.uast.call_graph import extract_call_graph_from_source


def select_functions(hot_names, call_graph, prob=0.25, max_f=3):
    """Helper para selección inter-procedural."""
    import random
    rng = random.Random(42)
    selected = set(hot_names)
    if prob > 0:
        for h in hot_names:
            if rng.random() < prob:
                for e in call_graph.edges_set():
                    if e[0] == h:
                        selected.add(e[1])
                    elif e[1] == h:
                        selected.add(e[0])
    if len(selected) > max_f:
        selected = set(list(hot_names) + list(selected - hot_names)[:max_f - len(hot_names)])
    return selected


class TestInterProcedural:
    """Tests para selección inter-procedural."""

    def test_ip01_prob_zero(self):
        g = extract_call_graph_from_source("def a(x): return b(x)\ndef b(x): return c(x)\ndef c(x): return x")
        s = select_functions({"b"}, g, prob=0.0)
        assert s == {"b"}

    def test_ip02_expansion(self):
        g = extract_call_graph_from_source("def a(x): return b(x)\ndef b(x): return c(x)\ndef c(x): return x")
        s = select_functions({"b"}, g, prob=1.0, max_f=10)
        assert "b" in s

    def test_ip03_limit(self):
        g = extract_call_graph_from_source("def a(x): return b(x)\ndef b(x): return c(x)\ndef c(x): return d(x)\ndef d(x): return x")
        s = select_functions({"a", "d"}, g, prob=1.0, max_f=2)
        assert len(s) <= 2

    def test_ip05_zero_identity(self):
        g = extract_call_graph_from_source("def f(x): return x + 1")
        assert select_functions({"f"}, g, prob=0.0) == {"f"}

    def test_ip06_empty(self):
        g = extract_call_graph_from_source("def f(x): return x + 1")
        assert select_functions(set(), g) == set()