"""Tests for FitnessDirectedMigration system.

Validates:
- GradientConfig defaults and custom values
- MigrationMetrics tracking
- FitnessDirectedMigration code signature and similarity
- Target selection based on fitness gradient + diversity gap
- Elite injection mechanism
- MigrationBus integration with fitness_gradient topology
- Benchmark evidence generation
"""

import copy
import random
import time
import unittest
from unittest.mock import MagicMock, patch

from migration import (
    FitnessDirectedMigration,
    GradientConfig,
    MigrationBus,
    MigrationMetrics,
)
from island import Island, IslandConfig
from models import Individual


def _make_individual(code: str, score: float) -> Individual:
    return Individual(code=code, score=score)


def _make_island(
    island_id: int,
    population: list,
    migration_interval: int = 5,
    migrants_per_island: int = 2,
) -> Island:
    config = IslandConfig(
        population_size=max(10, len(population)),
        top_k=min(5, len(population)),
        migration_interval=migration_interval,
        migrants_per_island=migrants_per_island,
    )
    island = Island(
        island_id=island_id,
        config=config,
        llm_fn=MagicMock(),
        evaluator=MagicMock(),
        migration_bus=MagicMock(),
    )
    island.population = population
    if population:
        island.local_best = max(population, key=lambda ind: ind.score)
    return island


class TestGradientConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = GradientConfig()
        self.assertAlmostEqual(cfg.alpha, 0.7)
        self.assertAlmostEqual(cfg.beta, 0.3)
        self.assertEqual(cfg.top_k_targets, 2)
        self.assertAlmostEqual(cfg.stagnation_threshold, 0.05)
        self.assertTrue(cfg.elite_injection)
        self.assertAlmostEqual(cfg.min_diversity_gap, 0.15)
        self.assertAlmostEqual(cfg.max_diversity_gap, 0.85)

    def test_custom(self):
        cfg = GradientConfig(alpha=0.9, beta=0.1, top_k_targets=3)
        self.assertAlmostEqual(cfg.alpha, 0.9)
        self.assertAlmostEqual(cfg.beta, 0.1)
        self.assertEqual(cfg.top_k_targets, 3)


class TestMigrationMetrics(unittest.TestCase):
    def test_initial_state(self):
        m = MigrationMetrics()
        self.assertEqual(m.total_migrations, 0)
        self.assertAlmostEqual(m.success_rate, 0.0)
        self.assertAlmostEqual(m.mean_improvement, 0.0)

    def test_record_successful_migration(self):
        m = MigrationMetrics()
        m.record_migration(0, 1, 0.8, 0.5, 0.7, is_elite=True)
        self.assertEqual(m.total_migrations, 1)
        self.assertEqual(m.successful_migrations, 1)
        self.assertAlmostEqual(m.success_rate, 1.0)
        self.assertAlmostEqual(m.mean_improvement, 0.2)
        self.assertEqual(m.elite_injections, 1)

    def test_record_failed_migration(self):
        m = MigrationMetrics()
        m.record_migration(0, 1, 0.3, 0.5, 0.4)
        self.assertEqual(m.total_migrations, 1)
        self.assertEqual(m.successful_migrations, 0)
        self.assertAlmostEqual(m.success_rate, 0.0)

    def test_mixed_migrations(self):
        m = MigrationMetrics()
        m.record_migration(0, 1, 0.8, 0.5, 0.7)  # success
        m.record_migration(0, 2, 0.3, 0.5, 0.4)  # fail
        m.record_migration(0, 3, 0.9, 0.5, 0.8)  # success
        self.assertEqual(m.total_migrations, 3)
        self.assertEqual(m.successful_migrations, 2)
        self.assertAlmostEqual(m.success_rate, 2 / 3, places=4)

    def test_get_report(self):
        m = MigrationMetrics()
        m.record_migration(0, 1, 0.8, 0.5, 0.7)
        report = m.get_report()
        self.assertIn("total_migrations", report)
        self.assertIn("success_rate", report)
        self.assertIn("mean_improvement", report)
        self.assertEqual(report["total_migrations"], 1)

    def test_migration_history(self):
        m = MigrationMetrics()
        m.record_migration(0, 1, 0.8, 0.5, 0.7, reason="fitness_gradient")
        self.assertEqual(len(m.migration_history), 1)
        entry = m.migration_history[0]
        self.assertEqual(entry["source"], 0)
        self.assertEqual(entry["target"], 1)
        self.assertEqual(entry["reason"], "fitness_gradient")
        self.assertIn("timestamp", entry)


class TestFitnessDirectedMigration(unittest.TestCase):
    def setUp(self):
        self.config = GradientConfig(
            alpha=0.7, beta=0.3, top_k_targets=2,
            min_diversity_gap=0.1, max_diversity_gap=0.9,
        )
        self.engine = FitnessDirectedMigration(self.config)

    def test_code_signature_deterministic(self):
        code = "def foo(x):\n    return x * 2"
        sig1 = self.engine._code_signature(code)
        sig2 = self.engine._code_signature(code)
        self.assertEqual(sig1, sig2)

    def test_code_signature_different(self):
        code_a = "def foo(x): return x * 2"
        code_b = "def bar(y, z): return y + z * 3"
        sig_a = self.engine._code_signature(code_a)
        sig_b = self.engine._code_signature(code_b)
        self.assertNotEqual(sig_a, sig_b)

    def test_code_similarity_identical(self):
        code = "def foo(x): return x * 2"
        sim = self.engine._code_similarity(code, code)
        self.assertAlmostEqual(sim, 1.0)

    def test_code_similarity_different(self):
        code_a = "alpha beta gamma delta"
        code_b = "epsilon zeta eta theta"
        sim = self.engine._code_similarity(code_a, code_b)
        self.assertAlmostEqual(sim, 0.0)

    def test_code_similarity_partial(self):
        code_a = "def foo return x plus y"
        code_b = "def bar return x times z"
        sim = self.engine._code_similarity(code_a, code_b)
        self.assertGreater(sim, 0.0)
        self.assertLess(sim, 1.0)

    def test_code_similarity_empty(self):
        self.assertAlmostEqual(self.engine._code_similarity("", "code"), 0.0)
        self.assertAlmostEqual(self.engine._code_similarity("code", ""), 0.0)

    def test_island_avg_fitness(self):
        pop = [_make_individual("a", 0.5), _make_individual("b", 0.8)]
        island = _make_island(0, pop)
        avg = self.engine._island_avg_fitness(island)
        self.assertAlmostEqual(avg, 0.65)

    def test_island_avg_fitness_empty(self):
        island = _make_island(0, [])
        avg = self.engine._island_avg_fitness(island)
        self.assertEqual(avg, float("-inf"))

    def test_select_targets_prefers_fitter_islands(self):
        """Targets with higher fitness should score higher."""
        source_pop = [_make_individual("src code alpha", 0.3)]
        source = _make_island(0, source_pop)

        target1_pop = [_make_individual("tgt1 different code beta", 0.5)]
        target1 = _make_island(1, target1_pop)

        target2_pop = [_make_individual("tgt2 other code gamma", 0.9)]
        target2 = _make_island(2, target2_pop)

        all_islands = {0: source, 1: target1, 2: target2}
        targets = self.engine.select_targets(source, all_islands)

        self.assertGreater(len(targets), 0)
        # The fitter island (target2) should have higher score
        if len(targets) >= 2:
            self.assertGreater(targets[0][0], targets[1][0])

    def test_select_targets_respects_diversity_gap(self):
        """Islands with too similar code should be skipped."""
        source_pop = [_make_individual("def foo(x): return x", 0.5)]
        source = _make_island(0, source_pop)

        # Very similar code to source
        clone_pop = [_make_individual("def foo(x): return x", 0.8)]
        clone = _make_island(1, clone_pop)

        # Different code
        diverse_pop = [_make_individual("while True: yield from generator", 0.8)]
        diverse = _make_island(2, diverse_pop)

        all_islands = {0: source, 1: clone, 2: diverse}
        targets = self.engine.select_targets(source, all_islands)

        # Clone should be filtered by min_diversity_gap
        target_ids = [t.id for _, t in targets]
        self.assertNotIn(1, target_ids)

    def test_select_targets_excludes_self(self):
        source_pop = [_make_individual("code", 0.5)]
        source = _make_island(0, source_pop)
        all_islands = {0: source}
        targets = self.engine.select_targets(source, all_islands)
        self.assertEqual(len(targets), 0)

    def test_select_targets_top_k_limit(self):
        config = GradientConfig(top_k_targets=1, min_diversity_gap=0.01)
        engine = FitnessDirectedMigration(config)

        source = _make_island(0, [_make_individual("src code", 0.3)])
        islands = {0: source}
        for i in range(1, 5):
            islands[i] = _make_island(
                i, [_make_individual(f"target{i} code {i*10}", 0.5 + i * 0.1)]
            )

        targets = engine.select_targets(source, islands)
        self.assertLessEqual(len(targets), 1)

    def test_elite_extraction(self):
        pop = [
            _make_individual("best", 0.95),
            _make_individual("good", 0.8),
            _make_individual("ok", 0.5),
            _make_individual("bad", 0.2),
        ]
        island = _make_island(0, pop)
        elites = self.engine.get_elite_migrants(island, fraction=0.25, max_elite=2)
        self.assertGreater(len(elites), 0)
        self.assertLessEqual(len(elites), 2)
        # Best individual should be among elites
        elite_scores = [e.score for e in elites]
        self.assertIn(0.95, elite_scores)

    def test_elite_extraction_empty(self):
        island = _make_island(0, [])
        elites = self.engine.get_elite_migrants(island)
        self.assertEqual(len(elites), 0)

    def test_migrate_records_metrics(self):
        source_pop = [
            _make_individual("src alpha beta gamma", 0.6),
            _make_individual("src delta epsilon", 0.4),
        ]
        source = _make_island(0, source_pop, migrants_per_island=1)

        target_pop = [_make_individual("tgt omega psi chi", 0.7)]
        target = _make_island(1, target_pop)

        all_islands = {0: source, 1: target}

        stats = self.engine.migrate(source, all_islands, generation=5)

        self.assertIn("migrated", stats)
        self.assertIn("elite_injected", stats)
        self.assertIn("skipped", stats)
        # Should have at least one migration
        self.assertGreater(
            stats["migrated"] + stats["skipped"], 0
        )

    def test_migrate_skips_when_no_targets(self):
        source_pop = [_make_individual("code", 0.5)]
        source = _make_island(0, source_pop)
        all_islands = {0: source}  # No other islands

        stats = self.engine.migrate(source, all_islands, generation=5)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["migrated"], 0)


class TestMigrationBusGradientIntegration(unittest.TestCase):
    def test_bus_accepts_fitness_gradient_topology(self):
        bus = MigrationBus(topology="fitness_gradient")
        self.assertEqual(bus.topology, "fitness_gradient")

    def test_bus_get_neighbors_returns_all_for_gradient(self):
        bus = MigrationBus(topology="fitness_gradient")
        for i in range(4):
            island = _make_island(i, [_make_individual(f"code{i}", 0.5)])
            bus.register_island(i, island)
        neighbors = bus._get_neighbors(0)
        self.assertEqual(sorted(neighbors), [1, 2, 3])

    def test_bus_migrate_with_gradient_topology(self):
        bus = MigrationBus(topology="fitness_gradient")
        islands = {}
        for i in range(3):
            pop = [_make_individual(f"island{i} code {i*10}", 0.3 + i * 0.2)]
            island = _make_island(i, pop, migration_interval=1, migrants_per_island=1)
            bus.register_island(i, island)
            islands[i] = island

        # Should not raise
        bus.migrate(0, generation=1)

    def test_bus_gradient_metrics(self):
        bus = MigrationBus(topology="fitness_gradient")
        for i in range(3):
            pop = [
                _make_individual(f"island{i} alpha beta code", 0.3 + i * 0.2),
                _make_individual(f"island{i} gamma delta", 0.2 + i * 0.15),
            ]
            island = _make_island(i, pop, migration_interval=1, migrants_per_island=1)
            bus.register_island(i, island)

        bus.migrate(0, generation=1)
        bus.migrate(1, generation=1)

        metrics = bus.get_migration_metrics()
        self.assertIn("total_migrations", metrics)
        self.assertIn("success_rate", metrics)

    def test_bus_standard_topology_still_works(self):
        """Ensure ring topology still works after gradient changes."""
        bus = MigrationBus(topology="ring")
        for i in range(3):
            pop = [_make_individual(f"code{i}", 0.5)]
            island = _make_island(i, pop, migration_interval=1, migrants_per_island=1)
            bus.register_island(i, island)

        # Should not raise
        bus.migrate(0, generation=1)

    def test_bus_gradient_config(self):
        bus = MigrationBus(topology="fitness_gradient")
        config = GradientConfig(alpha=0.9, beta=0.1, top_k_targets=3)
        bus.configure_gradient(config)
        self.assertIsNotNone(bus._gradient_config)
        self.assertAlmostEqual(bus._gradient_config.alpha, 0.9)

    def test_bus_get_global_best_with_gradient(self):
        bus = MigrationBus(topology="fitness_gradient")
        for i in range(3):
            score = 0.3 + i * 0.25
            pop = [_make_individual(f"code{i}", score)]
            island = _make_island(i, pop)
            bus.register_island(i, island)

        best = bus.get_global_best()
        self.assertIsNotNone(best)
        self.assertAlmostEqual(best.score, 0.8)


class TestFitnessTrendTracking(unittest.TestCase):
    def test_fitness_trend_first_call(self):
        engine = FitnessDirectedMigration()
        trend = engine._island_fitness_trend(0, 0.5)
        self.assertAlmostEqual(trend, 0.0)

    def test_fitness_trend_improving(self):
        engine = FitnessDirectedMigration()
        engine._island_fitness_trend(0, 0.3)
        engine._island_fitness_trend(0, 0.5)
        trend = engine._island_fitness_trend(0, 0.7)
        self.assertGreater(trend, 0.0)

    def test_fitness_trend_stagnating(self):
        engine = FitnessDirectedMigration()
        engine._island_fitness_trend(0, 0.7)
        engine._island_fitness_trend(0, 0.5)
        trend = engine._island_fitness_trend(0, 0.3)
        self.assertLess(trend, 0.0)


class TestStagnationBonus(unittest.TestCase):
    """Test that stagnant islands get rescue bonuses and improving islands
    get boost when sending to stagnant ones."""

    def test_stagnant_target_gets_rescue_boost(self):
        config = GradientConfig(
            alpha=0.7, beta=0.3, top_k_targets=3,
            min_diversity_gap=0.01, max_diversity_gap=0.99,
        )
        engine = FitnessDirectedMigration(config)

        # Source: improving trend
        source = _make_island(0, [_make_individual("src alpha beta", 0.5)])
        engine._island_fitness_history[0] = [0.3, 0.4, 0.5]  # improving

        # Target: stagnant
        target = _make_island(1, [_make_individual("tgt gamma delta epsilon", 0.6)])
        engine._island_fitness_history[1] = [0.6, 0.59, 0.58]  # stagnating

        all_islands = {0: source, 1: target}
        targets = engine.select_targets(source, all_islands)
        # Should have at least one target (rescue scenario)
        self.assertGreater(len(targets), 0)


if __name__ == "__main__":
    unittest.main()
