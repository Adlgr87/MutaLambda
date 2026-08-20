"""Tests for ProfileMode.SELF — the self-evolution security profile.

SELF waives *only* dynamic-introspection AST findings (getattr/chr) so that
MutaLambda can evolve its own first-party code, which uses introspection
legitimately.  Everything genuinely dangerous must remain blocked under SELF.
"""

import pytest

from pathlib import Path

import mutalambda.mutation_filters as mf
from mutalambda.mutation_filters import ProfileMode


GETATTR_CODE = '''
def _get_fitness(ind):
    fitness = getattr(ind, 'fitness', None)
    if fitness is not None:
        return fitness
    return None
'''

EVAL_CODE = "def f(x):\n    return eval(x)\n"
EXEC_CODE = "def f(x):\n    exec(x)\n"
IMPORT_OS_CODE = "import os\n\ndef f():\n    return os.getcwd()\n"
ALIAS_EVAL_CODE = "g = eval\n\ndef f(x):\n    return g(x)\n"
DUNDER_CODE = "def f():\n    return __builtins__.__dict__\n"


@pytest.mark.root
class TestSelfProfile:
    def test_getattr_blocked_under_balanced(self):
        report = mf.check_no_critical_patterns(GETATTR_CODE)
        assert report.blocked
        assert any("getattr_call" in issue for issue in report.issues)

    def test_getattr_allowed_under_self(self):
        report = mf.check_no_critical_patterns(GETATTR_CODE, profile="self")
        assert report.passed
        assert not report.blocked

    def test_own_nsga2_source_passes_under_self(self):
        """MutaLambda must be able to gate its own hot-path module."""
        import mutalambda.nsga2 as _n
        src = Path(_n.__file__).read_text(encoding="utf-8")
        assert mf.check_no_critical_patterns(src).blocked  # balanced: blocked
        assert mf.check_no_critical_patterns(src, profile="self").passed

    @pytest.mark.parametrize("dangerous", [
        EVAL_CODE, EXEC_CODE, IMPORT_OS_CODE, ALIAS_EVAL_CODE, DUNDER_CODE,
    ])
    def test_dangerous_patterns_still_blocked_under_self(self, dangerous):
        report = mf.check_no_critical_patterns(dangerous, profile="self")
        assert report.blocked, f"SELF must still block: {dangerous!r}"

    def test_self_profile_enum_roundtrip(self):
        assert ProfileMode.from_str("self") is ProfileMode.SELF
        from mutalambda.models import ProfileMode as ModelsProfileMode
        assert ModelsProfileMode.from_str("self") == ProfileMode.SELF

    def test_run_all_filters_self_profile(self):
        report = mf.run_all_filters(GETATTR_CODE, profile="self")
        assert report.passed
        report_balanced = mf.run_all_filters(GETATTR_CODE, profile="balanced")
        assert not report_balanced.passed
