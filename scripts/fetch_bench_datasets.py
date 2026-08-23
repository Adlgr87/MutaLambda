#!/usr/bin/env python3
"""Fetch public benchmark datasets into the local cache.

No dataset is vendored into this repository: they are large, they carry their
own licences, and a benchmark you cannot re-download is a benchmark nobody can
audit. This script materialises them on demand and writes a manifest
(revision / sha256 / file count) next to each one so a reviewer can confirm
they measured the same bytes.

    python scripts/fetch_bench_datasets.py --list
    python scripts/fetch_bench_datasets.py effibench polybench-python
    python scripts/fetch_bench_datasets.py --all --force
    MUTALAMBDA_BENCH_CACHE=/data/bench python scripts/fetch_bench_datasets.py pie

Licence note: by downloading you accept each upstream project's terms. They
are printed before every fetch, on purpose.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.datasets import (  # noqa: E402
    SOURCES, DatasetUnavailable, cache_root, dataset_path, fetch, is_available, status,
)


def _print_status() -> None:
    print(f"cache root: {cache_root()}\n")
    for row in status():
        mark = "✔ cached" if row["available"] else "✘ missing"
        print(f"{mark}  {row['key']:<20} {row['kind']:<7} {row['size_hint']:<12}")
        print(f"           {row['description']}")
        print(f"           {row['path']}")
    print("\nSuites and the dataset each one needs:")
    from bench.suites import list_suites

    for suite in list_suites():
        need = suite["dataset"] or "—"
        print(f"  {suite['name']:<16} {suite['tier']:<6} {suite['status']:<13} needs: {need}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("keys", nargs="*", help="dataset keys to fetch")
    parser.add_argument("--list", action="store_true", help="show cache status and exit")
    parser.add_argument("--all", action="store_true", help="fetch every registered dataset")
    parser.add_argument("--force", action="store_true", help="re-download even if cached")
    parser.add_argument("--full-clone", action="store_true",
                        help="clone full git history instead of --depth 1")
    parser.add_argument("--yes", action="store_true", help="skip the licence prompt")
    args = parser.parse_args(argv)

    if args.list or (not args.keys and not args.all):
        _print_status()
        return 0

    keys = sorted(SOURCES) if args.all else args.keys
    unknown = [k for k in keys if k not in SOURCES]
    if unknown:
        print(f"unknown dataset key(s): {unknown}\nknown: {sorted(SOURCES)}", file=sys.stderr)
        return 2

    failures = []
    for key in keys:
        src = SOURCES[key]
        if is_available(key) and not args.force:
            print(f"✔ {key} already cached at {dataset_path(key)}")
            continue
        print(f"\n── {key} ──")
        print(f"  {src.description}")
        print(f"  source:  {src.url}")
        print(f"  licence: {src.license}")
        if src.citation:
            print(f"  cite:    {src.citation}")
        print(f"  size:    {src.size_hint}")
        if src.notes:
            print(f"  note:    {src.notes}")
        if not args.yes:
            answer = input("  fetch this dataset? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("  skipped")
                continue
        try:
            path = fetch(key, force=args.force, shallow=not args.full_clone)
            print(f"  ✔ cached at {path}")
        except DatasetUnavailable as exc:
            print(f"  ✘ {exc}", file=sys.stderr)
            failures.append(key)
        except Exception as exc:  # network, git, permissions…
            print(f"  ✘ {type(exc).__name__}: {exc}", file=sys.stderr)
            failures.append(key)

    if failures:
        print(f"\nfailed: {failures}", file=sys.stderr)
        return 1
    print("\nDone. Check availability with: python -m bench.runner datasets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
