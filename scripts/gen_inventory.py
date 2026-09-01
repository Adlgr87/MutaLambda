#!/usr/bin/env python3
"""Automatic architecture inventory generation.

Scans the repository with ``git ls-files '*.py'`` and emits a Markdown
report describing the module layout, public classes, key metrics, and
an architecture matrix.  The output is written to
``docs/architecture_inventory.md`` by default.

Usage::

    python scripts/gen_inventory.py [--out docs/architecture_inventory.md]
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ModuleInfo:
    """Collected metadata for a single source module."""

    path: str
    classes: List[str]
    functions: List[str]
    line_count: int
    public_class_count: int
    public_function_count: int


@dataclasses.dataclass
class InventoryReport:
    """Aggregated inventory across all tracked Python files."""

    modules: List[ModuleInfo]
    total_files: int
    total_lines: int
    total_classes: int
    total_functions: int
    packages: Dict[str, int]  # package path -> module count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_git(args: List[str]) -> str:
    """Run a git command inside the repo root and return stdout."""
    result = subprocess.run(
        ["git", "-C", REPO_ROOT] + args,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _list_python_files() -> List[str]:
    """Return relative paths of all tracked ``*.py`` files."""
    out = _run_git(["ls-files", "*.py"])
    return sorted(line for line in out.splitlines() if line.strip())


def _parse_module(file_rel: str) -> Tuple[List[str], List[str]]:
    """Extract top-level class and function names from a source file.

    Uses ``ast`` for syntactic robustness.
    """
    import ast

    abs_path = os.path.join(REPO_ROOT, file_rel)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            source = fh.read()
    except (OSError, UnicodeDecodeError):
        return [], []

    try:
        tree = ast.parse(source, filename=file_rel)
    except SyntaxError:
        return [], []

    classes: List[str] = []
    functions: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
    return classes, functions


def _count_lines(file_rel: str) -> int:
    abs_path = os.path.join(REPO_ROOT, file_rel)
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _package_of(file_rel: str) -> str:
    parts = file_rel.split("/")
    if len(parts) > 1:
        return "/".join(parts[:-1])
    return "(root)"


# ---------------------------------------------------------------------------
# Core inventory
# ---------------------------------------------------------------------------

def build_inventory(files: Optional[List[str]] = None) -> InventoryReport:
    """Build the full inventory report.

    Parameters
    ----------
    files:
        Optional explicit list of file paths (for testing).  When *None*,
        the list is obtained from ``git ls-files '*.py'``.
    """
    if files is None:
        files = _list_python_files()

    modules: List[ModuleInfo] = []
    packages: Dict[str, int] = defaultdict(int)
    total_classes = 0
    total_functions = 0

    for file_rel in files:
        classes, functions = _parse_module(file_rel)
        lines = _count_lines(file_rel)
        pub_classes = [c for c in classes if _is_public(c)]
        pub_funcs = [f for f in functions if _is_public(f)]
        modules.append(ModuleInfo(
            path=file_rel,
            classes=classes,
            functions=functions,
            line_count=lines,
            public_class_count=len(pub_classes),
            public_function_count=len(pub_funcs),
        ))
        packages[_package_of(file_rel)] += 1
        total_classes += len(classes)
        total_functions += len(functions)

    total_lines = sum(m.line_count for m in modules)
    return InventoryReport(
        modules=modules,
        total_files=len(modules),
        total_lines=total_lines,
        total_classes=total_classes,
        total_functions=total_functions,
        packages=dict(sorted(packages.items())),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_RENDERED_COLUMNS = ["Module", "Path", "#Classes", "#Functions", "#Lines"]


def _render_summary(report: InventoryReport) -> str:
    lines = [
        "# Architecture Inventory",
        "",
        "> Auto-generated by `scripts/gen_inventory.py` from `git ls-files '*.py'`.",
        "",
        "## Summary",
        "",
        f"| Metric               | Value |",
        f"|----------------------|------:|",
        f"| Source files         | {report.total_files} |",
        f"| Lines of Python      | {report.total_lines:,} |",
        f"| Top-level classes    | {report.total_classes} |",
        f"| Top-level functions  | {report.total_functions} |",
        f"| Packages / dirs      | {len(report.packages)} |",
        "",
    ]
    return "\n".join(lines)


def _render_package_matrix(report: InventoryReport) -> str:
    lines = ["## Modules by Package", "", "| Package | #Modules |", "|---|---:|"]
    for pkg, count in report.packages.items():
        lines.append(f"| `{pkg}` | {count} |")
    lines.append("")
    return "\n".join(lines)


def _render_module_table(report: InventoryReport) -> str:
    lines = [
        "## Module Inventory",
        "",
        "| Module | Path | #Classes | #Functions | #Lines |",
        "|---|---|---:|---:|---:|",
    ]
    for m in report.modules:
        base = os.path.basename(m.path)
        name = base[:-3] if base.endswith(".py") else base
        link = f"`{m.path}`"
        lines.append(
            f"| {name} | {link} | {len(m.classes)} | {len(m.functions)} | {m.line_count:,} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_markdown(report: InventoryReport) -> str:
    """Render the full inventory report as Markdown."""
    sections = [_render_summary(report), _render_package_matrix(report), _render_module_table(report)]
    sections.append("## Public API Highlights")
    sections.append("")
    sections.append("The following public classes and functions are the primary extension points:")
    sections.append("")
    sections.append("| Module | Public Classes | Public Functions |")
    sections.append("|---|---|---|")
    for m in report.modules:
        if m.public_class_count or m.public_function_count:
            classes = ", ".join(m.classes)
            funcs = ", ".join(m.functions)
            sections.append(f"| `{m.path}` | {classes or "—"} | {funcs or "—"} |")
    sections.append("")
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate an architecture inventory from tracked Python files.",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(REPO_ROOT, "docs", "architecture_inventory.md"),
        help="Output Markdown file (default: docs/architecture_inventory.md).",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Optional explicit file list (defaults to git ls-files).",
    )
    args = parser.parse_args(argv)

    report = build_inventory(files=args.files)
    markdown = render_markdown(report)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(markdown)

    print(f"Inventory written to {args.out}")
    print(f"  {report.total_files} source files · "
          f"{report.total_lines:,} lines · "
          f"{report.total_classes} classes · "
          f"{report.total_functions} functions")
    return 0


if __name__ == "__main__":
    sys.exit(main())