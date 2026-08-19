"""Security regression suite for MutaLambda sandbox (Bloque C).

Verifies that the AST ``SecurityVisitor`` (exposed via
``runners.scan_code_security``) defeats the six documented sandbox-evasion
patterns and that the subprocess runner refuses to execute them.

These patterns come directly from the remediation plan and must ALL be
blocked — a single miss indicates a sandbox regression.

Additionally, this suite reproduces the pre-hardening claim from PLAN_MUTALAMBDA2 §C
that *"5 of 6 trivial evasions pass the regex filter"*.  The regex patterns
in ``mutation_filters._CRITICAL_PATTERNS`` are structurally weak: they match
literal token sequences only and are trivially bypassed by aliasing, getattr
indirection, or chr-concatenation.  The AST ``SecurityVisitor`` is what closes
that gap, so the tests below assert both the regex-only failure **and** the
AST-only success — together proving the combined filter is hardened.
"""
from __future__ import annotations

import pytest

from runners import (
    ContainerRunner,
    SecurityFinding,
    SecurityVisitor,
    SubprocessRunner,
    scan_code_security,
    scan_findings,
)
from mutation_filters import _CRITICAL_PATTERNS, check_no_critical_patterns


# ── The six trivial regex-evadable payloads (PLAN_MUTALAMBDA2 §C) ─────────────

# Each payload is a canonical sandbox-escape trick that a *regex-only* filter
# fails to catch.  The AST SecurityVisitor catches every one of them.
REGEX_EVASION_PAYLOADS = [
    pytest.param(
        'getattr(__builtins__, chr(101)+chr(120)+chr(101)+chr(99))("whoami")',
        id="chr_concat_getattr",
    ),
    pytest.param(
        'import os as _o; _o.system("whoami")',
        id="import_os_as_alias",
    ),
    pytest.param(
        'getattr(__builtins__, chr(101)+chr(118)+chr(97)+chr(108))(compile("1+1", "<s>", "eval"))',
        id="eval_compile",
    ),
    pytest.param(
        'getattr(getattr(__builtins__, "e"), "xec")("id")',
        id="nested_getattr_builtins",
    ),
    pytest.param(
        '__builtins__.__dict__["__import__"]("subprocess").Popen(["ls"])',
        id="subprocess_dynamic_getattr",
    ),
    pytest.param(
        'import base64; f = base64.b64decode("aW1wb3J0IG9z").decode(); '
        'getattr(getattr(__builtins__, "e"), "xec")(f)',
        id="exec_via_base64_decode",
    ),
]


# ── Reproduction: regex-only filter is trivially evaded ────────────────────────

@pytest.mark.parametrize("code", REGEX_EVASION_PAYLOADS)
def test_regex_filter_allows_evasion(code):
    """*Reproduces* PLAN_MUTALAMBDA2 §C: the bare regex ``_CRITICAL_PATTERNS``
    fail to block the documented evasion class.

    This test **asserts the vulnerability** — i.e., it expects the regex to
    miss.  If a future change hardens the regex, this test will flip to red,
    signalling Block C2 should remove it (the AST visitor is the real gate).
    """
    blocked = any(p.search(code) for p in _CRITICAL_PATTERNS)
    assert not blocked, (
        f"regex filter unexpectedly blocked payload: {code!r}"
    )


def test_regex_filter_5_of_6_evasible():
    """Aggregate claim from PLAN_MUTALAMBDA2 §C — at least 5 of 6 payloads must
    slip past the regex patterns alone."""
    bypassed = sum(
        1 for code in [p.values[0] for p in REGEX_EVASION_PAYLOADS]
        if not any(pat.search(code) for pat in _CRITICAL_PATTERNS)
    )
    assert bypassed >= 5, f"expected >=5 regex-pass-throughs, got {bypassed}"


# ── The AST SecurityVisitor defeats all six evasions ──────────────────────────

@pytest.mark.parametrize("code", REGEX_EVASION_PAYLOADS)
def test_ast_visitor_blocks_evasion(code):
    """The ``SecurityVisitor`` in ``runners`` must catch every regex-evadable
    payload and surface at least one finding."""
    findings = scan_code_security(code)
    assert findings, f"AST visitor missed evasion: {code!r} -> {findings}"


@pytest.mark.parametrize("code", REGEX_EVASION_PAYLOADS)
def test_combined_filter_blocks_evasion(code):
    """The combined ``check_no_critical_patterns`` (regex + AST) must block
    every documented escape payload."""
    report = check_no_critical_patterns(code)
    assert report.blocked, f"combined filter allowed: {code!r}"


# ── The six documented evasion vectors (original plan) ───────────────────────

ESCAPE_PATTERNS = [
    pytest.param(
        'exec("import os")',
        id="exec-directo",
    ),
    pytest.param(
        'getattr(__builtins__, chr(101)+chr(120)+chr(101)+chr(99))("whoami")',
        id="getattr-builtins-chr",
    ),
    pytest.param(
        'import os as _o; _o.system("whoami")',
        id="os-alias",
    ),
    pytest.param(
        'f = exec\nf("import os")',
        id="exec-alias",
    ),
    pytest.param(
        'import subprocess; subprocess.Popen(["ls"])',
        id="subprocess-popen",
    ),
    pytest.param(
        'open("/etc/passwd", "a")',
        id="open-append",
    ),
]

# Extra adversarial vectors beyond the plan's six.
EXTRA_ESCAPES = [
    pytest.param('mod = __import__("os")', id="dunder-import"),
    pytest.param('import importlib; importlib.import_module("os")', id="importlib"),
    pytest.param('import pickle; pickle.loads(b"x")', id="pickle-loads"),
    pytest.param('__import__("os").system("id")', id="dunder-import-chain"),
    pytest.param('os = __import__; os("os").system("id")', id="two-step-dunder"),
]


# ── scan_code_security blocks the six core escapes ────────────────────────────

@pytest.mark.parametrize("code", ESCAPE_PATTERNS)
def test_scan_blocks_escape(code):
    findings = scan_code_security(code)
    assert findings, f"evasion not detected: {code!r} -> {findings}"


@pytest.mark.parametrize("code", EXTRA_ESCAPES)
def test_scan_blocks_extra_escapes(code):
    findings = scan_code_security(code)
    assert findings, f"evasion not detected: {code!r}"


# ── The subprocess runner must reject every escape ────────────────────────────

@pytest.mark.parametrize("code", ESCAPE_PATTERNS + EXTRA_ESCAPES)
def test_subprocess_runner_rejects_escape(code):
    result = SubprocessRunner(timeout_sec=5.0, enforce_ast_scan=True).run(code, [])
    assert not result.passed, f"runner executed unsafe code: {code!r}"
    # Either a security_scan error or an empty-tests guard surfaces.
    assert result.timed_out is False


# ── Detailed findings carry source positions ─────────────────────────────────

def test_findings_have_positions():
    findings = scan_findings('import os; os.system("ls")')
    assert findings, "expected findings"
    f = findings[0]
    assert isinstance(f, SecurityFinding)
    assert f.lineno >= 1
    assert f.kind


def test_syntax_error_reported():
    # scan_code_security returns a syntax_error entry (legacy contract).
    findings = scan_code_security("def broken(:")
    assert findings
    assert any("syntax_error" in f for f in findings)
    # scan_findings returns empty list for syntax errors (by design).
    assert scan_findings("def broken(:") == []


# ── Mutation filter layer closes the regex-evasion class ───────────────────────

@pytest.mark.parametrize("code", ESCAPE_PATTERNS + EXTRA_ESCAPES)
def test_mutation_filter_blocks_escape(code):
    """The regex filter in mutation_filters must be backed by the AST visitor
    so textual evasion tricks do not pass the pre-execution gate either."""
    report = check_no_critical_patterns(code)
    assert report.blocked, f"mutation filter allowed evasion: {code!r}"


# ── Safe code is not flagged (no false positives) ────────────────────────────

SAFE_PATTERNS = [
    "def f(x):\n    return x + 1\n",
    "import sys\nimport json\ndef f(x):\n    return json.dumps(x)\n",
    "import math\nimport collections\nimport re\n"
    "d = collections.Counter([1,2,2,3])\n"
    "return math.sqrt(16) if re.match('a', 'abc') else 0\n",
    "x = [i for i in range(10)]\ny = sorted(x, reverse=True)\n"
    "return sum(y)\n",
]


@pytest.mark.parametrize("code", SAFE_PATTERNS)
def test_safe_code_not_flagged(code):
    assert scan_code_security(code) == [], f"false positive on safe code: {code!r}"


# ── Container runner applies the same AST gate ──────────────────────────────

def test_container_runner_scans_before_run():
    """ContainerRunner shares the enforce_ast_scan gate; escape must be blocked
    before any container is even consulted."""
    runner = ContainerRunner(timeout_sec=5.0, enforce_ast_scan=True)
    # We never reach container engine resolution because the AST gate fires.
    result = runner.run('import os; os.system("id")', [])
    assert not result.passed
    assert not result.timed_out


# ── SecurityVisitor is reusable / deterministic ─────────────────────────────

def test_visitor_deterministic():
    code = 'import subprocess; subprocess.Popen(["ls"])'
    a = [f.message for f in scan_findings(code)]
    b = [f.message for f in scan_findings(code)]
    assert a == b


def test_visitor_class_construction():
    v = SecurityVisitor()
    v.visit(__import__("ast").parse("exec('x')"))
    assert v.findings
