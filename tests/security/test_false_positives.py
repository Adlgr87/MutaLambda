"""False-positive regression suite for the AST ``SecurityVisitor``.

The visitor must remain *conservative* about blocking — legitimate Python
that happens to use ``len``, ``sorted``, ``os.path.join``, ``np.array`` and
simple ``for`` loops must never be flagged, otherwise the evolutionary
pipeline would reject valid candidate programs.

Each snippet below is a safe idiom drawn from the canonical whitelist and
must produce **zero** findings from ``scan_code_security``.
"""
from __future__ import annotations

import pytest

from runners import scan_code_security, scan_findings


SAFE_SNIPPETS = [
    # ── Built-in functions ──────────────────────────────────────────────
    pytest.param("len(x)", id="len_builtin"),
    pytest.param("abs(-5)", id="abs_builtin"),
    pytest.param("min([1, 2, 3])", id="min_builtin"),
    pytest.param("max(1, 2, 3)", id="max_builtin"),
    pytest.param("sum([1, 2, 3])", id="sum_builtin"),
    pytest.param("str(42)", id="str_builtin"),
    pytest.param("int('42')", id="int_builtin"),
    pytest.param("list(range(10))", id="list_builtin"),
    pytest.param("dict(a=1, b=2)", id="dict_builtin"),
    pytest.param("zip([1, 2], [3, 4])", id="zip_builtin"),

    # ── sorted / comprehensions ─────────────────────────────────────────
    pytest.param("sorted([3, 1, 2])", id="sorted_simple"),
    pytest.param("sorted(items, key=lambda x: x.name)", id="sorted_with_key"),
    pytest.param("sorted(data, reverse=True)", id="sorted_reverse"),
    pytest.param("x = [i * 2 for i in range(10)]", id="list_comp"),
    pytest.param("y = [i for i in range(len(z))]", id="range_len_comp"),

    # ── os.path (imported normally or aliased) ─────────────────────────
    pytest.param('import os\nos.path.join("a", "b")', id="os_path_join"),
    pytest.param('import os as _os\n_os.path.join("a", "b")', id="os_path_join_aliased"),
    pytest.param('from os.path import join\njoin("a", "b")', id="from_os_path"),
    pytest.param('import os.path\nos.path.join("a", "b")', id="import_os_path"),

    # ── numpy / common library usage ───────────────────────────────────
    pytest.param(
        "import numpy as np\nnp.array([1, 2, 3])\nnp.zeros(5)\nnp.mean(data)",
        id="numpy_usage",
    ),
    pytest.param(
        "import math\nmath.sqrt(16)\nmath.pi",
        id="math_usage",
    ),

    # ── stdlib that is allowed (sys, json) ─────────────────────────────
    pytest.param(
        "import sys\nimport json\njson.dumps({'key': 'value'})",
        id="sys_json_safe"),
    pytest.param(
        "import re\nre.match('a', 'abc')",
        id="re_safe"),

    # ── common function/iterator patterns ─────────────────────────────
    pytest.param(
        "def f(x):\n    return x + 1",
        id="simple_function"),
    pytest.param(
        "for x in items:\n    total += x",
        id="simple_for"),
    pytest.param(
        "x = {'a': 1, 'b': 2}\nfor k, v in x.items():\n    process(k, v)",
        id="dict_items_iter"),
    pytest.param(
        "result = [fn(x) for x in data if x > 0]",
        id="conditional_comp"),
    pytest.param(
        "cache = {}\nfor item in items:\n    cache[item.key] = item.value",
        id="dict_build"),
]


@pytest.mark.parametrize("code", SAFE_SNIPPETS)
def test_safe_code_not_blocked_by_ast(code):
    """No false positives — safe snippets must yield zero findings."""
    findings = scan_code_security(code)
    assert findings == [], (
        f"false positive on safe code: {code!r} -> {findings}"
    )


@pytest.mark.parametrize("code", SAFE_SNIPPETS)
def test_safe_code_no_detailed_findings(code):
    """scan_findings must also return zero detailed findings for safe code."""
    findings = scan_findings(code)
    assert findings == [], (
        f"false positive (detailed) on safe code: {code!r} -> {findings}"
    )
