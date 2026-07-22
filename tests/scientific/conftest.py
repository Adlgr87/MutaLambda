"""Fixtures compartidas para tests científicos."""
import sys
from pathlib import Path
from typing import Dict, Any

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest
from muta_ext.scientific.invariants import BASE_INVARIANTS


@pytest.fixture
def scientific_config() -> Dict[str, Any]:
    """Configuración por defecto para extensión científica."""
    return {
        "enabled": True,
        "validation": {
            "invariants": True,
            "numerical_stability": True,
            "conservation_checks": True,
            "property_based": True,
        },
        "hotpath": {"enabled": False},
        "domain_operators": {"enabled": False},
    }


@pytest.fixture
def default_invariants():
    """Lista de invariantes base."""
    return list(BASE_INVARIANTS)