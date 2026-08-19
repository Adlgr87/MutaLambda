#!/usr/bin/env python3
"""Block A4 — smoke tests for core module importability.

These tests assert that every core module of MutaLambda imports cleanly and
that Python-only mode (``use_uast=False``) is functional without the optional
``uast`` tree-sitter dependencies.
"""
import importlib

import pytest

CORE_MODULES = [
    "cli.main",
    "cli.config_manager",
    "muta_lambda",
    "evolution_engine",
    "island",
    "fitness_vector",
    "sandbox",
    "runners",
    "checkpoint_manager",
    "config_loader",
]


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_core_module_imports(module_name):
    """Each core module must be importable without error."""
    importlib.import_module(module_name)


def test_python_only_mode_works():
    """get_adapter('python') must succeed in Python-only mode (no tree-sitter)."""
    from muta_ext.uast.adapters import get_adapter

    assert get_adapter("python") is not None
