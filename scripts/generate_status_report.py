#!/usr/bin/env python3
"""Generate a machine-readable status report for MutaLambda.

Outputs JSON (and optional markdown) with commit, Python version, pytest
summary, optional dependency availability, and timestamp.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def git_commit() -> str:
    try:
        return _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    except Exception:
        return "unknown"


def optional_deps() -> dict:
    names = [
        "faiss",
        "sentence_transformers",
        "z3",
        "click",
        "rich",
        "streamlit",
        "pandas",
        "pdfplumber",
    ]
    out = {}
    for name in names:
        try:
            __import__(name if name != "sentence_transformers" else "sentence_transformers")
            out[name] = True
        except Exception:
            out[name] = False
    return out


def run_pytest() -> dict:
    proc = _run([sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"])
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    # crude parse: "155 passed, 5 skipped"
    summary = {"exit_code": proc.returncode, "raw_tail": text.strip().splitlines()[-5:]}
    for token in ("passed", "failed", "skipped", "errors"):
        summary[token] = 0
    import re

    m = re.search(
        r"(?:(\d+)\s+passed)?(?:,\s*)?(?:(\d+)\s+failed)?(?:,\s*)?(?:(\d+)\s+skipped)?",
        text.replace("\n", " "),
    )
    if m:
        summary["passed"] = int(m.group(1) or 0)
        summary["failed"] = int(m.group(2) or 0)
        summary["skipped"] = int(m.group(3) or 0)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="MutaLambda status report")
    parser.add_argument("--output", "-o", default="status_report.json")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()

    report = {
        "project": "MutaLambda",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": git_commit(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "optional_dependencies": optional_deps(),
        "tests": {"skipped": True} if args.skip_tests else run_pytest(),
    }

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")

    if args.markdown:
        md_path = out_path.with_suffix(".md")
        tests = report["tests"]
        lines = [
            f"# MutaLambda status — {report['commit'][:12]}",
            "",
            f"- Generated: `{report['generated_at']}`",
            f"- Python: `{report['python']}`",
            f"- Platform: `{report['platform']}`",
            f"- Tests: passed={tests.get('passed', '?')} failed={tests.get('failed', '?')} "
            f"skipped={tests.get('skipped', '?')} exit={tests.get('exit_code', '?')}",
            "",
            "## Optional dependencies",
            "",
        ]
        for k, v in report["optional_dependencies"].items():
            lines.append(f"- `{k}`: {'yes' if v else 'no'}")
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote {md_path}")

    return 0 if report["tests"].get("exit_code", 0) in (0, None) or args.skip_tests else 1


if __name__ == "__main__":
    raise SystemExit(main())
