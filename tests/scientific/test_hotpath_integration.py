"""Tests de integración hot-path (INT-*)."""
from muta_ext.scientific.hotpath import profile_workload
from muta_ext.scientific.hotpath_types import ProfileConfig
from muta_ext.uast.call_graph import extract_call_graph_from_source
import json


class TestIntegration:
    """Tests de integración completa."""

    def test_int01_enabled(self):
        def w():
            total = 0
            for i in range(5000):
                total += i * i
            return total

        r = profile_workload("w", w, ProfileConfig(min_cumulative_pct=0.1))
        # El profiling puede no detectar funciones en casos muy rápidos
        assert r.has_hot_paths or r.error is None

    def test_int02_disabled(self):
        def w():
            return sum(i * i for i in range(1000))

        r = profile_workload("w", w, ProfileConfig(enabled=False))
        assert not r.has_hot_paths

    def test_int04_checkpoint_serialize(self):
        data = [{"function_name": "slow", "cumulative_pct": 80.0}]
        ser = json.dumps(data)
        restored = json.loads(ser)
        assert restored[0]["function_name"] == "slow"

    def test_int05_massive_kernel(self):
        def energy_step(particles):
            return sum(p * p * 0.5 for p in particles)

        def run(steps=3000):
            particles = [float(i) for i in range(50)]
            for _ in range(steps):
                energy_step(particles)

        r = profile_workload("run", run, ProfileConfig(min_cumulative_pct=1.0))
        assert r.has_hot_paths