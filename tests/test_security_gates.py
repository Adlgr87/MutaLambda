"""Security regression tests for the in-process execution gates."""
from __future__ import annotations

import ast

import pytest

from runners import scan_code_security

UNSAFE = "import os\ndef f(x):\n    os.system('id')\n    return x\n"
SAFE = "def f(x):\n    return x + 1\n"


class TestScanCodeSecurity:
    def test_flags_builtins_reconstruction(self):
        findings = scan_code_security("def f(x):\n    return ().__class__.__base__\n")
        assert any("__class__" in f for f in findings)

    def test_flags_sys_modules_access(self):
        findings = scan_code_security("import sys\ndef f(x):\n    return sys.modules['os']\n")
        assert findings

    def test_flags_builtins_import(self):
        findings = scan_code_security("import builtins\ndef f(x):\n    return x\n")
        assert findings

    def test_allows_plain_code(self):
        assert scan_code_security(SAFE) == []


class TestDifferentialGate:
    def test_rejects_unsafe_candidate(self):
        from differential import UnsafeCodeError, _load_function

        with pytest.raises(UnsafeCodeError):
            _load_function(UNSAFE, "f")

    def test_loads_safe_candidate(self):
        from differential import _load_function

        assert _load_function(SAFE, "f")(1) == 2


class TestMassiveAdapterGate:
    def test_benchmark_rejects_unsafe_code(self, tmp_path):
        from massive_adapter import MassiveTargetAdapter

        src = tmp_path / "target.py"
        src.write_text(UNSAFE)
        adapter = MassiveTargetAdapter(source_file=str(src), entrypoint="f")

        result = adapter.benchmark(UNSAFE)
        assert result.error is not None
        assert result.error.startswith("security_scan:")


class TestHotspotProfilerInjection:
    def test_path_is_not_interpolated_into_source(self, tmp_path, monkeypatch):
        from hotspot_profiler import HotspotProfiler

        monkeypatch.chdir(tmp_path)
        target = tmp_path / 'x");open("pwned.txt","w").write("1");#.py'
        target.write_text("def main():\n    return 1\n\nmain()\n")

        HotspotProfiler().profile_script(str(target))
        assert not (tmp_path / "pwned.txt").exists()


class TestGeneratedMutatorGate:
    def test_rejects_dunder_escape(self):
        from muta_ext.uast.mutators.llm_generator import (
            MutatorSafetyError,
            _assert_safe_ast,
        )

        tree = ast.parse("def mutate(node, **kwargs):\n    return ().__class__\n")
        with pytest.raises(MutatorSafetyError):
            _assert_safe_ast(tree)
