"""Tests para ScientificInvariant checks (HP-01 a HP-07)."""
import math
from muta_ext.scientific.invariants import (
    check_energy_non_negative,
    check_mass_conservation,
    check_bounds_physical,
    check_monotonicity,
    check_numerical_stability,
    filter_invariants,
    BASE_INVARIANTS,
)


class TestEnergyNonNegative:
    """Tests para check_energy_non_negative."""

    def test_positive(self):
        assert check_energy_non_negative({"total_energy": 42.0}, {})

    def test_zero(self):
        assert check_energy_non_negative({"total_energy": 0.0}, {})

    def test_negative(self):
        assert not check_energy_non_negative({"total_energy": -1.0}, {})

    def test_tolerance(self):
        assert check_energy_non_negative({"total_energy": -1e-10}, {})

    def test_no_key(self):
        assert check_energy_non_negative({"mass": 100}, {})

    def test_alt_key(self):
        assert check_energy_non_negative({"energy": 50.0}, {})


class TestMassConservation:
    """Tests para check_mass_conservation."""

    def test_zero(self):
        assert check_mass_conservation({"mass_delta": 0.0}, {})

    def test_small(self):
        assert check_mass_conservation({"mass_delta": 1e-9}, {})

    def test_large(self):
        assert not check_mass_conservation({"mass_delta": 1e-6}, {})

    def test_no_key(self):
        assert check_mass_conservation({"energy": 100}, {})


class TestBoundsPhysical:
    """Tests para check_bounds_physical."""

    def test_within(self):
        assert check_bounds_physical({"temperature": 300.0}, {})

    def test_outside(self):
        assert not check_bounds_physical({"temperature": 1e20}, {})

    def test_tiny(self):
        assert not check_bounds_physical({"density": 1e-16}, {})

    def test_no_phys(self):
        assert check_bounds_physical({"name": "test"}, {})


class TestMonotonicity:
    """Tests para check_monotonicity."""

    def test_non_decreasing(self):
        r = {"trajectory": [{"entropy": 0.0}, {"entropy": 0.5}]}
        assert check_monotonicity(r, {})

    def test_decreasing(self):
        r = {"trajectory": [{"entropy": 1.0}, {"entropy": 0.5}]}
        assert not check_monotonicity(r, {})

    def test_single(self):
        assert check_monotonicity({"trajectory": [{"entropy": 1.0}]}, {})

    def test_no_traj(self):
        assert check_monotonicity({"energy": 42.0}, {})


class TestNumericalStability:
    """Tests para check_numerical_stability."""

    def test_normal(self):
        assert check_numerical_stability({"value": 42.0}, {})

    def test_nan(self):
        assert not check_numerical_stability({"value": float('nan')}, {})

    def test_inf(self):
        assert not check_numerical_stability({"value": float('inf')}, {})

    def test_overflow(self):
        assert not check_numerical_stability({"value": 1e100}, {})


class TestFilter:
    """Tests para filter_invariants."""

    def test_all(self):
        assert len(filter_invariants()) == len(BASE_INVARIANTS)

    def test_hard(self):
        r = filter_invariants(severity="hard")
        assert all(i.severity == "hard" for i in r)

    def test_soft(self):
        r = filter_invariants(severity="soft")
        assert all(i.severity == "soft" for i in r)

    def test_names(self):
        r = filter_invariants(names=["energy_non_negative"])
        assert len(r) == 1