"""Mutation filters for MutaLambda — prevent buggy code submissions (ML-F01).

Filters are applied after code generation / mutation and before the candidate
enters the population.
"""

from __future__ import annotations

import ast
import enum
import logging
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional
from mutalambda.runners import scan_code_security  # AST-based escape detection

_LOG_LEVEL = os.environ.get("MUTALAMBDA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MutaLambda")


# ── Blocked patterns (regex) ───────────────────────────────────────────────────

_CRITICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bexec\s*\(", re.IGNORECASE),
    re.compile(r"\beval\s*\(", re.IGNORECASE),
    re.compile(r"\bos\.system\s*\(", re.IGNORECASE),
    re.compile(r"\bos\.popen\s*\(", re.IGNORECASE),
    re.compile(r"\bsubprocess\.call\s*\(", re.IGNORECASE),
    re.compile(r"\bsubprocess\.run\s*\(", re.IGNORECASE),
    re.compile(r"\bsys\.exit\s*\(", re.IGNORECASE),
    re.compile(r"\b__import__\s*\(", re.IGNORECASE),
    re.compile(r"\bimportlib\.import_module\s*\(", re.IGNORECASE),
    re.compile(r"\bopen\s*\(.*['\"]w+", re.IGNORECASE),
    re.compile(r"\bdelete\s+os\.", re.IGNORECASE),
    re.compile(r"\bremove\s+os\.", re.IGNORECASE),
    re.compile(r"\bshutil\.rmtree\s*\(", re.IGNORECASE),
)

_WARNING_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bassert\b", re.IGNORECASE), "assert statement"),
    (re.compile(r"\braise\s+Exception\b"), "generic Exception"),
    (re.compile(r"\bexcept\s*:\s*$"), "bare except"),
    (re.compile(r"\bexcept\s*\(\s*\):"), "bare except tuple"),
    (re.compile(r"\bTODO\b"), "TODO comment"),
    (re.compile(r"\bFIXME\b"), "FIXME comment"),
    (re.compile(r"\bHACK\b"), "HACK comment"),
    (re.compile(r"\b# type:\s*ignore\b"), "type: ignore comment"),
    (re.compile(r"\bpass\b\s*$"), "empty pass statement"),
    (re.compile(r"\bprint\s*\("), "print statement"),
)

_INFO_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bglobal\s+\w+"), "global keyword usage"),
    (re.compile(r"\b__dict__"), "__dict__ access"),
    (re.compile(r"\bglobals\(\)"), "globals() call"),
    (re.compile(r"\btime\.sleep\s*\("), "time.sleep call"),
    (re.compile(r"\binput\s*\("), "input() call"),
)

_SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# AST findings waived under ProfileMode.SELF (trusted first-party code).
# Only dynamic-introspection findings — never eval/exec/imports/open/aliases.
_SELF_WAIVED_AST_FINDINGS = frozenset({"getattr_call", "chr_call"})


@dataclass
class FitnessReport:
    """Resultado de la validación post-evaluación de un individuo."""
    passed: bool = True
    blocked: bool = False
    issues: List[str] = field(default_factory=list)
    severity: str = "none"
    is_valid: bool = True
    fixed_code: str = ""


class ProfileMode(str, enum.Enum):
    """Profile mode for evolution filters."""
    HOTFIX = "hotfix"
    BALANCED = "balanced"
    DEBT = "debt"
    STRICT = "strict"
    PERMISSIVE = "permissive"
    RELEASE = "release"
    SELF = "self"

    @classmethod
    def from_str(cls, value: str) -> "ProfileMode":
        try:
            return cls(value.lower())
        except ValueError:
            logger.warning("Unknown profile '%s', defaulting to 'balanced'", value)
            return cls.BALANCED


def _make_report(passed, blocked, issues, severity):
    return FitnessReport(passed=passed, blocked=blocked, issues=issues, severity=severity)


def _severity_rank(severity):
    return _SEVERITY_ORDER.get(severity, 0)


def check_empty_code(code):
    if not code.strip():
        return _make_report(False, True, ["empty code snippet"], "critical")
    return _make_report(True, False, [], "none")


def check_syntax(code):
    try:
        ast.parse(code)
        return _make_report(True, False, [], "none")
    except SyntaxError as exc:
        msg = f"syntax error: {exc.msg} at line {exc.lineno}"
        logger.debug("SyntaxFilter blocked: %s", msg)
        return _make_report(False, True, [msg], "critical")


def check_max_length(code, max_lines=500):
    line_count = len(code.strip().splitlines())
    if line_count > max_lines:
        return _make_report(False, True, [f"code exceeds {max_lines} lines ({line_count} lines)"], "high")
    return _make_report(True, False, [], "none")


def check_no_critical_patterns(code, profile="balanced"):
    """Block both regex-detected and AST-escape patterns.

    The regex patterns (_CRITICAL_PATTERNS) catch obvious syntactic forms but
    are trivially evaded (e.g. ``import os as _o``; ``f = exec``).  The AST
    SecurityVisitor in ``runners`` catches the structural variants; combining
    both removes that entire class of evasion (see test_sandbox_escapes.py).

    Profile ``self`` (ProfileMode.SELF) is intended for **self-evolution**:
    optimizing MutaLambda's own trusted first-party code.  Framework code
    legitimately uses dynamic introspection (``getattr``/``chr``), so those
    AST findings are waived under ``self`` — but every genuinely dangerous
    pattern (eval/exec/subprocess/imports/open/aliasing/dunder access) is
    still blocked, and the sandbox remains the hard execution boundary.
    """
    profile_enum = ProfileMode.from_str(profile) if isinstance(profile, str) else profile
    issues = []
    for pattern in _CRITICAL_PATTERNS:
        if pattern.search(code):
            issues.append(f"blocked pattern detected: {pattern.pattern[:40]}...")
    # AST structural scan — catches aliasing / getattr(__builtins__, ...) / chr().
    try:
        ast_findings = scan_code_security(code)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("AST security scan failed: %r", exc)
        ast_findings = []
    if profile_enum == ProfileMode.SELF and ast_findings:
        waived = [f for f in ast_findings if f in _SELF_WAIVED_AST_FINDINGS]
        ast_findings = [f for f in ast_findings if f not in _SELF_WAIVED_AST_FINDINGS]
        if waived:
            logger.info("Self-profile waived introspection findings: %s", waived)
    if ast_findings:
        issues.extend(f"ast:{f}" for f in ast_findings)
    if issues:
        logger.warning("CriticalPatternsFilter blocked: %s", issues)
        return _make_report(False, True, issues, "critical")
    return _make_report(True, False, [], "none")


def check_warning_patterns(code, profile="balanced"):
    profile_enum = ProfileMode.from_str(profile) if isinstance(profile, str) else profile
    issues = []
    for pattern, desc in _WARNING_PATTERNS:
        if pattern.search(code):
            issues.append(f"warning: {desc}")
    if not issues:
        return _make_report(True, False, [], "none")
    if profile_enum in (ProfileMode.HOTFIX, ProfileMode.RELEASE):
        logger.warning("WarningPatternsFilter blocked (profile=%s): %s", profile_enum.value, issues)
        return _make_report(False, True, issues, "high")
    logger.info("WarningPatternsFilter allowed (profile=%s): %s", profile_enum.value, issues)
    return _make_report(True, False, issues, "low")


def check_info_patterns(code):
    issues = []
    for pattern, desc in _INFO_PATTERNS:
        if pattern.search(code):
            issues.append(f"info: {desc}")
    if issues:
        logger.debug("InfoPatternsFilter: %s", issues)
    return _make_report(True, False, issues, "none")


def check_ast_depth(code, max_depth=50):
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return _make_report(False, True, ["syntax error in AST depth check"], "critical")

    def _depth(node):
        max_d = 0
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.AST):
                max_d = max(max_d, _depth(child))
        return max_d + 1

    depth = _depth(tree)
    if depth > max_depth:
        return _make_report(False, True, [f"AST depth {depth} exceeds limit {max_depth}"], "medium")
    return _make_report(True, False, [], "none")


def check_import_cycles(code):
    imports = set()
    from_imports = {}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return _make_report(False, True, ["syntax error in import cycle check"], "critical")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                imports.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                imports.add(top)
                for alias in node.names:
                    from_imports[alias.name] = top
    conflicts = []
    for name, module in from_imports.items():
        if name in imports and module == imports & {name}:
            conflicts.append(f"self-import: {name}")
    if conflicts:
        return _make_report(False, True, conflicts, "medium")
    return _make_report(True, False, [], "none")


def run_all_filters(code, profile="balanced", enforce_syntax=True):
    from mutalambda.models import ProfileMode as PM, FitnessReport as FR

    profile_enum = PM.from_str(profile) if isinstance(profile, str) else profile

    checks = [
        ("empty", check_empty_code(code)),
        ("syntax", check_syntax(code) if enforce_syntax else _make_report(True, False, [], "none")),
        ("critical_patterns", check_no_critical_patterns(code, profile_enum)),
        ("ast_depth", check_ast_depth(code)),
        ("import_cycles", check_import_cycles(code)),
        ("warning_patterns", check_warning_patterns(code, profile_enum)),
        ("info_patterns", check_info_patterns(code)),
    ]

    all_issues = []
    max_severity = "none"
    blocked = False

    for name, report in checks:
        if report.blocked:
            blocked = True
        all_issues.extend(report.issues)
        if _severity_rank(report.severity) > _severity_rank(max_severity):
            max_severity = report.severity

    return FR(passed=not blocked, blocked=blocked, issues=all_issues, severity=max_severity, is_valid=not blocked, fixed_code=code)


def _filter_mutant(code: str, profile_mode: ProfileMode) -> Optional[str]:
    """Return cleaned code if passes all filters, or None if rejected."""
    report = run_all_filters(code, profile_mode)
    if not report.is_valid:
        return None
    return report.fixed_code

__all__ = [
    "run_all_filters",
    "check_syntax",
    "check_max_length",
    "check_no_critical_patterns",
    "check_warning_patterns",
    "check_info_patterns",
    "check_ast_depth",
    "check_empty_code",
    "check_import_cycles",
    "FitnessReport",
    "ProfileMode",
    "_filter_mutant",
]
