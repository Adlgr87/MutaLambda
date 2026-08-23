"""On-demand, hash-pinned dataset acquisition.

No benchmark data lives in this repository. Each suite declares where its data
comes from; ``scripts/fetch_bench_datasets.py`` materialises it into a cache
directory (default ``~/.cache/mutalambda-bench``, override with
``MUTALAMBDA_BENCH_CACHE``) and records a manifest with sizes and digests so a
reviewer can confirm we ran on the same bytes they have.

Licensing is the suite author's responsibility: every source below carries the
upstream licence and a link, and nothing is redistributed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

CACHE_ENV = "MUTALAMBDA_BENCH_CACHE"
DEFAULT_CACHE = "~/.cache/mutalambda-bench"


class DatasetUnavailable(RuntimeError):
    """Raised by a suite when its data is not in the cache.

    The message always tells the user the exact command that fixes it — a
    benchmark harness that fails with 'FileNotFoundError' is a benchmark
    harness nobody runs twice.
    """


@dataclass
class DatasetSource:
    key: str
    kind: str            # "git" | "http" | "hf" | "pip" | "manual"
    url: str
    description: str
    license: str
    citation: str = ""
    subpath: str = ""     # file/dir inside the source that suites read
    sha256: str = ""      # pin for http archives
    revision: str = ""    # pin for git
    size_hint: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key, "kind": self.kind, "url": self.url,
            "description": self.description, "license": self.license,
            "citation": self.citation, "subpath": self.subpath,
            "sha256": self.sha256, "revision": self.revision,
            "size_hint": self.size_hint, "notes": self.notes,
        }


# ── source registry ────────────────────────────────────────────────────────

SOURCES: Dict[str, DatasetSource] = {
    "effibench": DatasetSource(
        key="effibench",
        kind="git",
        url="https://github.com/huangd1999/EffiBench.git",
        description=(
            "EffiBench (NeurIPS 2024): 1,000 efficiency-critical LeetCode problems, "
            "each with a human canonical solution used as the efficiency baseline."
        ),
        license="See upstream repository (research use).",
        citation="Huang et al., EffiBench: Benchmarking the Efficiency of Automatically Generated Code, NeurIPS 2024 (arXiv:2402.02037)",
        subpath="dataset",
        size_hint="~50 MB",
        notes=(
            "The canonical-solution field is what makes the '3.12x of human' claim "
            "checkable: we report candidate/canonical ratios, not raw milliseconds."
        ),
    ),
    "effibench-x": DatasetSource(
        key="effibench-x",
        kind="hf",
        url="EffiBench/effibench-x",
        description=(
            "EffiBench-X: 623 problems x 6 languages with per-language human expert "
            "solutions. Used for the cross-language efficiency table."
        ),
        license="See dataset card on the Hugging Face Hub.",
        citation="Qing et al., EffiBench-X, NeurIPS 2025 Datasets & Benchmarks (arXiv:2505.13004)",
        size_hint="~200 MB",
    ),
    "pie": DatasetSource(
        key="pie",
        kind="git",
        url="https://github.com/madaan/pie-perf.git",
        description=(
            "PIE: >77k C++ competitive-programming submission pairs where a human "
            "made the program faster, with unit tests per problem."
        ),
        license="See upstream repository; derived from IBM Project CodeNet (Apache-2.0 tooling).",
        citation="Shypula et al., Learning Performance-Improving Code Edits, ICLR 2024 (arXiv:2302.07867)",
        subpath="data",
        size_hint="~1 GB with test cases",
        notes=(
            "The published %Opt/Speedup numbers are gem5-simulated upstream. We report "
            "wall-clock on real hardware AND state that difference explicitly; comparing "
            "our wall-clock speedup to their gem5 speedup without saying so would be "
            "exactly the kind of dishonesty this harness exists to avoid."
        ),
    ),
    "polybench-python": DatasetSource(
        key="polybench-python",
        kind="git",
        url="https://github.com/pdclab/polybench-python.git",
        description=(
            "PolyBench/Python: 30 numerical kernels (gemm, jacobi, seidel, "
            "correlation, ...). The natural target for the NumPy/ParallelFor mutators."
        ),
        license="See upstream repository.",
        citation="Abella-González et al., PolyBench/Python, PMAM 2021",
        size_hint="~5 MB",
    ),
    "polybench-c": DatasetSource(
        key="polybench-c",
        kind="http",
        url="https://sourceforge.net/projects/polybench/files/polybench-c-4.2.1-beta.tar.gz/download",
        description="PolyBench/C 4.2.1 — reference kernels for the C++ emitter path.",
        license="See upstream (BSD-like, per-file headers).",
        size_hint="~1 MB",
    ),
    "rosetta": DatasetSource(
        key="rosetta",
        kind="git",
        url="https://github.com/acmeism/RosettaCodeData.git",
        description=(
            "Rosetta Code corpus: the same task implemented across languages. "
            "Backs the cross-language 'does the speedup carry over?' experiment."
        ),
        license="GNU FDL 1.2 (Rosetta Code content).",
        size_hint="~1 GB (shallow clone recommended)",
    ),
    "eoh": DatasetSource(
        key="eoh",
        kind="git",
        url="https://github.com/FeiLiu36/EoH.git",
        description=(
            "Evolution of Heuristics: the problem suite (online bin packing, TSP "
            "construction, circle packing) used to position against AlphaEvolve."
        ),
        license="MIT (see upstream).",
        citation="Liu et al., Evolution of Heuristics, ICML 2024",
        size_hint="~30 MB",
        notes="bench.suites.eoh ships native implementations of two problems so the "
              "tier-3 track runs without this clone; the clone adds the full suite.",
    ),
    "pyperformance": DatasetSource(
        key="pyperformance",
        kind="pip",
        url="pyperformance",
        description="Official CPython benchmark suite (50+ real workloads).",
        license="MIT",
        size_hint="pip install",
    ),
}


# ── cache plumbing ─────────────────────────────────────────────────────────

def cache_root() -> Path:
    return Path(os.getenv(CACHE_ENV, DEFAULT_CACHE)).expanduser()


def dataset_path(key: str) -> Path:
    return cache_root() / key


def is_available(key: str) -> bool:
    src = SOURCES.get(key)
    if src is None:
        return False
    if src.kind == "pip":
        try:
            __import__(src.url.replace("-", "_"))
            return True
        except Exception:
            return False
    p = dataset_path(key)
    if not p.exists():
        return False
    return any(p.iterdir())


def require(key: str, suite: str) -> Path:
    """Return the dataset path or explain precisely how to obtain it."""
    src = SOURCES.get(key)
    if src is None:
        raise DatasetUnavailable(f"unknown dataset key '{key}'")
    if not is_available(key):
        raise DatasetUnavailable(
            f"suite '{suite}' needs dataset '{key}' ({src.description.splitlines()[0]})\n"
            f"  fetch it with:  python scripts/fetch_bench_datasets.py {key}\n"
            f"  source:         {src.url}\n"
            f"  licence:        {src.license}\n"
            f"  cache dir:      {dataset_path(key)}"
        )
    return dataset_path(key)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _write_manifest(key: str, extra: Optional[Dict[str, Any]] = None) -> Path:
    src = SOURCES[key]
    root = dataset_path(key)
    files = 0
    total = 0
    for p in root.rglob("*"):
        if p.is_file():
            files += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    manifest = {
        "key": key,
        "source": src.to_dict(),
        "files": files,
        "bytes": total,
        "path": str(root),
    }
    manifest.update(extra or {})
    out = root / "_muta_manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


def fetch(key: str, *, force: bool = False, shallow: bool = True) -> Path:
    """Materialise a dataset into the cache. Returns its path."""
    src = SOURCES.get(key)
    if src is None:
        raise DatasetUnavailable(f"unknown dataset key '{key}'")
    dest = dataset_path(key)
    if dest.exists() and any(dest.iterdir()) and not force:
        return dest
    if force and dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if src.kind == "git":
        cmd = ["git", "clone"]
        if shallow and not src.revision:
            cmd += ["--depth", "1"]
        cmd += [src.url, str(dest)]
        subprocess.run(cmd, check=True)
        if src.revision:
            subprocess.run(["git", "-C", str(dest), "checkout", src.revision], check=True)
        rev = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        _write_manifest(key, {"revision": rev})
        return dest

    if src.kind == "http":
        dest.mkdir(parents=True, exist_ok=True)
        archive = dest / "download.bin"
        urllib.request.urlretrieve(src.url, archive)  # noqa: S310 (pinned by sha)
        digest = sha256_file(archive)
        if src.sha256 and digest != src.sha256:
            raise DatasetUnavailable(
                f"sha256 mismatch for {key}: expected {src.sha256}, got {digest}"
            )
        _extract(archive, dest)
        _write_manifest(key, {"sha256": digest})
        return dest

    if src.kind == "hf":
        try:
            from huggingface_hub import snapshot_download  # type: ignore
        except ImportError as exc:
            raise DatasetUnavailable(
                f"dataset '{key}' needs the Hugging Face client: pip install huggingface_hub"
            ) from exc
        dest.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=src.url, repo_type="dataset", local_dir=str(dest))
        _write_manifest(key, {})
        return dest

    if src.kind == "pip":
        raise DatasetUnavailable(f"install it with: pip install {src.url}")

    raise DatasetUnavailable(f"dataset '{key}' must be obtained manually: {src.url}")


def _extract(archive: Path, dest: Path) -> None:
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            tf.extractall(dest)  # noqa: S202 (trusted, hash-pinned source)
    elif zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    # else: leave the raw file in place


def status() -> List[Dict[str, Any]]:
    rows = []
    for key, src in sorted(SOURCES.items()):
        rows.append({
            "key": key,
            "available": is_available(key),
            "kind": src.kind,
            "path": str(dataset_path(key)),
            "size_hint": src.size_hint,
            "description": src.description.split("\n")[0],
        })
    return rows
