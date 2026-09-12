#!/usr/bin/env python
"""Canonical test-count generator (per AGENTS.md convention).

Regenerates ``docs/ARTIFACTS/test_count.txt`` from the number of test
*functions* (``def test_`` / ``async def test_``) found under ``tests/``.
Counting functions (not pytest-collected items) keeps the number stable
regardless of parametrization expansion, so docs can cite a single canonical
value that never drifts from the source tree.

Usage::

    python scripts/report_test_count.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
OUT_PATH = ROOT / "docs" / "ARTIFACTS" / "test_count.txt"

_TEST_FN = re.compile(r"^\s*(?:async\s+)?def\s+test_")


def count_test_functions() -> int:
    """Count top-level ``def test_*`` functions under ``tests/``."""
    total = 0
    for path in TESTS_DIR.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            if _TEST_FN.match(line):
                total += 1
    return total


def main() -> int:
    count = count_test_functions()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(f"{count}\n", encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(ROOT)} = {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
