#!/usr/bin/env python3
"""Guard the BLE001 ratchet: the debt inventory may shrink, never grow.

`ruff` has no warning severity, so BLE001 (blind `except Exception`) is enforced
as an error with the pre-existing cases frozen in
`[tool.ruff.lint.per-file-ignores]`. That alone stops *new* violations in clean
files, but nothing stops someone appending a new line to the inventory and
carrying on. This script closes that hole.

Four checks, all cheap enough to run on every push:

1. **Count may not increase.** Compared against BASELINE_ENTRIES below. Lower it
   in the same commit that triages a file.
2. **Every entry is scoped to BLE001 alone.** An entry like
   `"foo.py" = ["BLE001", "F401"]` would smuggle unrelated debt past review, and
   a bare `"*"` would disable the rule outright.
3. **No wildcards.** Literal paths only: a glob silently absorbs files created
   later, which is exactly the leak the ratchet exists to prevent.
4. **No stale entries.** If a listed file no longer trips BLE001 (triaged, or
   deleted), the line must go. Otherwise the inventory stops reflecting reality
   and the count stops being meaningful.

Usage:
    python scripts/check_ble_ratchet.py            # all four checks
    python scripts/check_ble_ratchet.py --update   # print the refreshed block
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

# ── Ratchet baseline ──────────────────────────────────────────────────────
# Entries in the BLE001 inventory. This number may only ever go DOWN.
# When you triage a module, remove its line and lower this by the same amount
# in the same commit.
#
#   2026-10-02  98  initial inventory (302 violations) minus evaluation_service
#   2026-10-02  97  -1 mutalambda_config/checkpoint_manager.py (tier 2, durability pass)
BASELINE_ENTRIES = 97

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = REPO / "pyproject.toml"


def load_inventory() -> dict[str, list[str]]:
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("tool", {}).get("ruff", {}).get("lint", {}).get("per-file-ignores", {})


def current_violations() -> set[str]:
    """Files that trip BLE001 today, ignoring per-file-ignores."""
    proc = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check", ".",
            # --isolated bypasses pyproject entirely. Without it ruff applies
            # the very per-file-ignores we are auditing and reports every
            # listed file as clean, which would make the staleness check a
            # no-op that always "passes".
            "--isolated",
            "--select", "BLE001",
            "--exclude", ".venv,build,dist,node_modules",
            "--no-cache",
            "--output-format", "concise",
        ],
        cwd=REPO, capture_output=True, text=True,
    )
    files = set()
    for line in proc.stdout.splitlines():
        m = re.match(r"^(.*?\.py):\d+:\d+: BLE001", line)
        if m:
            files.add(m.group(1))
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="print a refreshed inventory block")
    args = parser.parse_args()

    inventory = load_inventory()
    ble = {path: rules for path, rules in inventory.items() if "BLE001" in rules}
    failures: list[str] = []

    # 1. count may not grow
    if len(ble) > BASELINE_ENTRIES:
        added = len(ble) - BASELINE_ENTRIES
        failures.append(
            f"inventory GREW by {added} (now {len(ble)}, baseline {BASELINE_ENTRIES}).\n"
            f"    The BLE001 debt list may only shrink. Fix the blind except instead of\n"
            f"    adding a line, or use an inline `# noqa: BLE001 - <reason>` if the\n"
            f"    broad catch is genuinely correct."
        )

    # 2. each entry must be scoped to BLE001 and nothing else
    for path, rules in sorted(ble.items()):
        if sorted(rules) != ["BLE001"]:
            failures.append(
                f"{path} ignores {rules} - entries must be exactly [\"BLE001\"].\n"
                f"    A wider ignore hides unrelated debt that the ratchet cannot see."
            )

    # 3. literal paths only
    for path in sorted(ble):
        if any(ch in path for ch in "*?["):
            failures.append(
                f"{path} is a glob - the inventory must list literal paths.\n"
                f"    A pattern silently absorbs files added later."
            )

    # 4. stale entries must be removed
    live = current_violations()
    stale = sorted(p for p in ble if p not in live)
    if stale:
        detail = "\n".join(
            f"      {p}" + ("  (file is gone)" if not (REPO / p).exists() else "  (now clean)")
            for p in stale
        )
        failures.append(
            f"{len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'} - these files no "
            f"longer trip BLE001:\n{detail}\n"
            f"    Remove them and lower BASELINE_ENTRIES to {len(ble) - len(stale)}."
        )

    if args.update:
        keep = sorted(p for p in ble if p in live)
        print("# ── BLE001 debt inventory — remove lines as modules are triaged, never add ──")
        for p in keep:
            print(f'    "{p}" = ["BLE001"]')
        print(f"\n# BASELINE_ENTRIES = {len(keep)}", file=sys.stderr)
        return 0

    if failures:
        print("BLE001 ratchet violated:\n", file=sys.stderr)
        for f in failures:
            print(f"  ✗ {f}\n", file=sys.stderr)
        return 1

    headroom = BASELINE_ENTRIES - len(ble)
    print(
        f"BLE001 ratchet OK: {len(ble)} entries (baseline {BASELINE_ENTRIES}"
        + (f", {headroom} already retired" if headroom else "")
        + "), all scoped to BLE001, all literal paths, none stale."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
