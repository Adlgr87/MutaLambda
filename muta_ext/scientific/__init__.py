"""
Scientific Optimization Extension for MutaLambda.
Proporciona SVL, Hot-path profiling y Domain-Specialized Mutation Operators.
"""
from muta_ext.scientific.invariants import (
    ScientificInvariant,
    check_energy_non_negative,
    check_mass_conservation,
    check_bounds_physical,
    check_monotonicity,
    check_numerical_stability,
    BASE_INVARIANTS,
)
from muta_ext.scientific.validation import (
    run_scientific_validation_stage,
    ScientificValidationResult,
    evaluate_invariants,
)
from muta_ext.scientific.hotpath_types import (
    HotPath,
    HotPathResult,
    ProfileConfig,
)
from muta_ext.scientific.hotpath import (
    profile_code,
    profile_workload,
)

__all__ = [
    "ScientificInvariant", "BASE_INVARIANTS",
    "evaluate_invariants", "ScientificValidationResult",
    "run_scientific_validation_stage",
    "HotPath", "HotPathResult", "ProfileConfig",
    "profile_code", "profile_workload",
    "check_energy_non_negative", "check_mass_conservation",
    "check_bounds_physical", "check_monotonicity",
    "check_numerical_stability",
]