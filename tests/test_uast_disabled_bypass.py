#!/usr/bin/env python3
"""Verify UAST adapters can be used in Python-only mode.

When ``use_uast=False`` (or the ``uast`` extra is not installed) the package
``muta_ext.uast.adapters`` must import successfully *without* pulling in the
optional ``tree-sitter`` language bindings (``tree_sitter_rust``,
``tree_sitter_cpp``, ``tree_sitter_go``).  Heavy adapters are only loaded on
demand and surface a friendly :class:`ImportError` pointing at
``pip install 'mutalambda[uast]'`` (never a ``NameError``).

The "absent" scenarios simulate missing tree-sitter bindings inside a fresh
subprocess so we can *observe* what happens at genuine import time, which is
exactly what the acceptance criteria ask for.
"""
import os
import subprocess
import sys
import textwrap
from ast import literal_eval

import pytest

# tree-sitter language bindings that must NOT be imported eagerly
_TREE_SITTER_BINDINGS = ("tree_sitter_rust", "tree_sitter_cpp", "tree_sitter_go")
# adapter modules that import those bindings and must stay lazy
_ADAPTER_MODULES = (
    "muta_ext.uast.adapters.rust_adapter",
    "muta_ext.uast.adapters.cpp_adapter",
    "muta_ext.uast.adapters.go_adapter",
)

# Script that blocks the optional bindings (via a meta-path finder) and then
# exercises the adapters package, printing one machine-readable line per
# check.  Running in a subprocess guarantees import-time behaviour is not
# masked by the test process's module cache.
_BLOCKER_SCRIPT = textwrap.dedent(
    """
    import os, sys

    class _Blocker:
        # ``find_spec`` that raises ImportError is the import-system way to
        # declare a module is unimportable. We block the *base* ``tree_sitter``
        # binding (used at top-level by rust_adapter/cpp_adapter) plus the
        # per-language grammar packages so any lazy load of a heavy adapter
        # raises ImportError instead of resolving to the real package.
        blocked = set(os.environ["MUTA_TEST_BLOCK"].splitlines())
        def find_spec(self, name, path, target=None):
            if name in self.blocked or name == "tree_sitter" or name.startswith("tree_sitter."):
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
            return None
        find_module = find_spec

    sys.meta_path.insert(0, _Blocker())

    adapter_modules = set(os.environ["MUTA_TEST_ADAPTERS"].splitlines())

    import muta_ext.uast.adapters as adapters

    loaded = sorted(
        m for m in sys.modules
        if m.startswith("tree_sitter")
        or m in adapter_modules
    )
    print("PKG_IMPORT_OK")
    print("HEAVY_LOADED:" + repr(loaded))
    print("PYTHON:" + adapters.get_adapter("python").__class__.__name__)
    for lang in ("rust", "cpp", "go"):
        # backward-compat attribute access via module-level __getattr__
        try:
            getattr(adapters, lang.capitalize() + "Adapter")
            print(lang.upper() + "_GETATTR:no-error")
        except ImportError as e:
            print(lang.upper() + "_GETATTR:ImportError:" + str(e))
        except NameError as e:
            print(lang.upper() + "_GETATTR:NameError:" + str(e))
        # get_adapter path
        try:
            adapters.get_adapter(lang)
            print(lang.upper() + "_RESULT:no-error")
        except ImportError as e:
            print(lang.upper() + "_RESULT:ImportError:" + str(e))
        except NameError as e:
            print(lang.upper() + "_RESULT:NameError:" + str(e))
    """
)


def _run_isolated(blocked, adapter_modules):
    """Run the blocker script in a fresh interpreter, returning stdout."""
    proc = subprocess.run(
        [sys.executable, "-c", _BLOCKER_SCRIPT],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "MUTA_TEST_BLOCK": "\n".join(blocked),
            "MUTA_TEST_ADAPTERS": "\n".join(adapter_modules),
        },
    )
    # surface failures from the child clearly
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return proc.stdout


def test_package_import_does_not_pull_tree_sitter():
    """Importing the adapters package must not import tree-sitter bindings."""
    out = _run_isolated(_TREE_SITTER_BINDINGS, _ADAPTER_MODULES)
    assert "PKG_IMPORT_OK" in out
    loaded_line = [l for l in out.splitlines() if l.startswith("HEAVY_LOADED:")][0]
    loaded = literal_eval(loaded_line.split("HEAVY_LOADED:", 1)[1].strip())
    assert loaded == [], f"eager imports detected: {loaded}"


def test_python_adapter_works_without_tree_sitter():
    """get_adapter('python') works with no heavy dependencies."""
    out = _run_isolated(_TREE_SITTER_BINDINGS, _ADAPTER_MODULES)
    assert "PYTHON:PythonAdapter" in out


@pytest.mark.parametrize("language", ["rust", "cpp", "go"])
def test_heavy_adapter_raises_import_error_with_install_hint(language):
    """Heavy adapters raise ImportError (not NameError) with install hint."""
    out = _run_isolated(_TREE_SITTER_BINDINGS, _ADAPTER_MODULES)
    tag = language.upper()
    result_line = [l for l in out.splitlines() if l.startswith(tag + "_RESULT:")][0]
    assert result_line.startswith(tag + "_RESULT:ImportError:"), result_line
    assert "mutalambda[uast]" in result_line


@pytest.mark.parametrize("adapter_name", ["RustAdapter", "CppAdapter", "GoAdapter"])
def test_backward_compat_import_raises_import_error_not_name_error(adapter_name):
    """`from muta_ext.uast.adapters import RustAdapter` stays backward compatible.

    When the optional bindings are missing the re-export must NOT raise
    ``NameError``; it must either raise a friendly ``ImportError`` mentioning
    ``pip install 'mutalambda[uast]'`` or succeed (Go's module degrades
    gracefully at import time, keeping the class accessible).  ``NameError`` is
    always a bug.
    """
    language = {
        "RustAdapter": "rust",
        "CppAdapter": "cpp",
        "GoAdapter": "go",
    }[adapter_name]
    out = _run_isolated(_TREE_SITTER_BINDINGS, _ADAPTER_MODULES)
    tag = language.upper()
    gline = [l for l in out.splitlines() if l.startswith(tag + "_GETATTR:")][0]
    assert not gline.startswith(tag + "_GETATTR:NameError:"), (
        f"backward-compat re-export raised NameError for {adapter_name}: {gline}"
    )
    if gline.startswith(tag + "_GETATTR:ImportError:"):
        assert "mutalambda[uast]" in gline, (
            f"missing install hint for {adapter_name}: {gline}"
        )
    # a no-error (class accessible) line is also acceptable: backward compat
    # is preserved since the name still resolves.


def test_python_only_mode_get_adapter_python_not_none():
    """Smoke: with tree-sitter present (this test process), Python adapter loads."""
    from muta_ext.uast.adapters import get_adapter

    assert get_adapter("python") is not None
