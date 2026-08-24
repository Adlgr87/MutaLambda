#!/usr/bin/env python3
"""Static analyzer for mathematical, physical and cryptographic invariants.

Reads a CoreUAST JSON document (produced by ``universal_parser.py``) and emits
an ``invariants.lock`` JSON lockfile capturing:

* physical constants (CODATA values) found literal in the source,
* mathematical identities referenced or structurally present,
* numerical tolerance metadata (float32 / float64 boundaries),
* cryptographic pattern usage (hashes, signatures, PRNG).

The lockfile is versioned and includes a content hash so downstream stages
(``certify.py``, the verification phase) can detect tampering.

Usage:
    python invariant_detector.py <uast.json> [--output invariants.lock]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "InvariantsLock",
    "PhysicalConstant",
    "MathematicalIdentity",
    "NumericalTolerance",
    "CryptoPattern",
    "CODATA_CONSTANTS",
    "MATH_IDENTITIES",
    "detect_invariants",
]

LOCKFILE_VERSION = "1.0.0"

# ── CODATA / physical constants (2022 CODATA recommended values, SI) ──────────
CODATA_CONSTANTS: Dict[str, Dict[str, Any]] = {
    # symbol: (value, unit, uncertainty, description)
    "c": {"value": 299_792_458.0, "unit": "m/s", "uncertainty": 0.0, "name": "speed of light"},
    "h": {"value": 6.626_070_15e-34, "unit": "J·s", "uncertainty": 0.0, "name": "Planck constant"},
    "hbar": {
        "value": 1.054_571_817e-34,
        "unit": "J·s",
        "uncertainty": 1.3e-51,
        "name": "reduced Planck constant",
    },
    "G": {
        "value": 6.674_30e-11,
        "unit": "m³/kg·s²",
        "uncertainty": 1.5e-15,
        "name": "gravitational constant",
    },
    "e": {"value": 1.602_176_634e-19, "unit": "C", "uncertainty": 0.0, "name": "elementary charge"},
    "eps0": {
        "value": 8.854_187_8128e-12,
        "unit": "F/m",
        "uncertainty": 1.9e-21,
        "name": "vacuum permittivity",
    },
    "mu0": {
        "value": 1.256_637_062_12e-6,
        "unit": "N/A²",
        "uncertainty": 1.3e-13,
        "name": "vacuum permeability",
    },
    "kB": {"value": 1.380_649e-23, "unit": "J/K", "uncertainty": 0.0, "name": "Boltzmann constant"},
    "NA": {
        "value": 6.022_140_76e23,
        "unit": "1/mol",
        "uncertainty": 0.0,
        "name": "Avogadro constant",
    },
    "R": {"value": 8.314_462_618, "unit": "J/(mol·K)", "uncertainty": 0.0, "name": "gas constant"},
    "alpha": {
        "value": 7.297_352_5693e-3,
        "unit": "",
        "uncertainty": 1.3e-11,
        "name": "fine-structure constant",
    },
    "me": {
        "value": 9.109_383_7015e-31,
        "unit": "kg",
        "uncertainty": 2.4e-42,
        "name": "electron mass",
    },
    "mp": {
        "value": 1.672_621_923_69e-27,
        "unit": "kg",
        "uncertainty": 5.3e-44,
        "name": "proton mass",
    },
    "u": {
        "value": 1.660_539_066_60e-27,
        "unit": "kg",
        "uncertainty": 5.3e-44,
        "name": "atomic mass unit",
    },
}

# Float type tolerance boundaries.
FLOAT32_EPS = 1.1920928955078125e-7  # 2**-23
FLOAT32_MIN_NORMAL = 1.1754943508864688e-38
FLOAT32_MAX = 3.306492283e38
FLOAT64_EPS = 2.220446049250313e-16  # 2**-52
FLOAT64_MIN_NORMAL = 2.2250738585072014e-308

# ── Recognised mathematical identities ─────────────────────────────────────
# Each entry: name → (description, structural signature keywords to match)
MATH_IDENTITIES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "add_identity": ("x + 0 = x", ("+", "0", "add")),
    "mul_identity": ("x * 1 = x", ("*", "1", "mul")),
    "mul_zero": ("x * 0 = 0", ("*", "0", "mul")),
    "pythagorean": ("sin²θ + cos²θ = 1", ("sin", "cos", "2", "pythagorean")),
    "euler": ("e^(iπ) + 1 = 0", ("exp", "pi", "euler", "imaginary")),
    "ln_exp": ("ln(e^x) = x", ("ln", "exp", "log")),
    "pythagorean_hyp": ("a² + b² = c²", ("hypot", "pythagorean", "sqrt")),
}

# ── Cryptographic pattern signatures (best-effort detection) ────────────────
CRYPTO_PATTERNS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "sha256": ("SHA-256 hash usage", ("sha256", "sha-256", "hashlib.sha256")),
    "sha3": ("SHA-3 hash usage", ("sha3_256", "sha3_512", "hashlib.sha3")),
    "md5": ("MD5 hash usage (deprecated)", ("md5", "hashlib.md5")),
    "hmac": ("HMAC keyed hash", ("hmac", "Hmac")),
    "ed25519": ("Ed25519 signatures", ("ed25519", "Ed25519")),
    "rsa": ("RSA signatures", ("rsa", "RSA", "PKCS1_v1_5")),
    "prng": ("Pseudo-random source", ("random.random", "random.uniform", "rng", "prng", "PRNG")),
    "secrets": ("Cryptographically secure random", ("secrets.", "secrets.choice", "secrets.token")),
    "aes": ("AES symmetric encryption", ("aes", "AES", "Fernet")),
}


@dataclass(frozen=True)
class PhysicalConstant:
    symbol: str
    value: float
    unit: str
    uncertainty: float
    description: str
    matches: Tuple[str, ...]


@dataclass(frozen=True)
class MathematicalIdentity:
    name: str
    description: str
    matched_keywords: Tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class NumericalTolerance:
    kind: str  # "float32" | "float64" | "epsilon" | "dtype_check"
    lower_bound: float
    upper_bound: float
    description: str


@dataclass(frozen=True)
class CryptoPattern:
    kind: str
    description: str
    matched_keywords: Tuple[str, ...]


@dataclass
class InvariantsLock:
    """Versioned lockfile of detected invariants for a source module."""

    version: str
    source_hash: str
    file: str
    language: str
    physical_constants: List[PhysicalConstant] = field(default_factory=list)
    mathematical_identities: List[MathematicalIdentity] = field(default_factory=list)
    numerical_tolerances: List[NumericalTolerance] = field(default_factory=list)
    crypto_patterns: List[CryptoPattern] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "source_hash": self.source_hash,
            "file": self.file,
            "language": self.language,
            "physical_constants": [asdict(c) for c in self.physical_constants],
            "mathematical_identities": [asdict(i) for i in self.mathematical_identities],
            "numerical_tolerances": [asdict(t) for t in self.numerical_tolerances],
            "crypto_patterns": [asdict(p) for p in self.crypto_patterns],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InvariantsLock":
        return cls(
            version=data.get("version", LOCKFILE_VERSION),
            source_hash=data.get("source_hash", ""),
            file=data.get("file", ""),
            language=data.get("language", ""),
            physical_constants=[PhysicalConstant(**c) for c in data.get("physical_constants", [])],
            mathematical_identities=[
                MathematicalIdentity(**i) for i in data.get("mathematical_identities", [])
            ],
            numerical_tolerances=[
                NumericalTolerance(**t) for t in data.get("numerical_tolerances", [])
            ],
            crypto_patterns=[CryptoPattern(**p) for p in data.get("crypto_patterns", [])],
        )

    def content_hash(self) -> str:
        """SHA-256 of the canonicalised (sorted-key) payload."""
        payload = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _walk_values(uast: Dict[str, Any]) -> Iterable[Any]:
    """Yield every scalar/dict/list value found inside a UAST document."""
    if isinstance(uast, dict):
        yield uast
        for v in uast.values():
            yield from _walk_values(v)
    elif isinstance(uast, list):
        for item in uast:
            yield from _walk_values(item)


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _collect_scalars(uast: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Collect (field_path, text_value) pairs for every scalar in the UAST."""
    out: List[Tuple[str, str]] = []

    def _visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                _visit(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _visit(item, f"{path}[{i}]")
        elif isinstance(node, (str, int, float, bool)):
            text = _as_text(node)
            if text:
                out.append((path, text))

    _visit(uast, "")
    return out


def detect_invariants(uast: Dict[str, Any], source: str = "") -> InvariantsLock:
    """Analyze a CoreUAST dict (and optional source) for preserved invariants."""
    from code_hash import stable_code_hash

    source_hash = (
        stable_code_hash(source) if source else uast.get("metadata", {}).get("source_hash", "")
    )
    language = uast.get("language", "unknown")
    file = uast.get("file", "")

    # Combine UAST scalars + raw source text as the search corpus.
    scalars = _collect_scalars(uast)
    corpus_text = source or " ".join(t for _, t in scalars)

    constants = _detect_constants(scalars, corpus=corpus_text)
    identities = _detect_identities(corpus_text)
    tolerances = _detect_tolerances(corpus_text)
    crypto = _detect_crypto(corpus_text)

    return InvariantsLock(
        version=LOCKFILE_VERSION,
        source_hash=source_hash,
        file=file,
        language=language,
        physical_constants=constants,
        mathematical_identities=identities,
        numerical_tolerances=tolerances,
        crypto_patterns=crypto,
    )


def _detect_constants(scalars: List[Tuple[str, str]], corpus: str = "") -> List[PhysicalConstant]:
    """Match numeric literals against CODATA constant values.

    Scans both scalar node values and numeric tokens in the source corpus so
    that large physical constants (e.g. ``299792458.0``) are matched even when
    the UAST descriptor does not preserve their numeric value.
    """
    matches: List[PhysicalConstant] = []
    # Build reverse lookup by numeric value with a relative tolerance.
    targets: Dict[float, Dict[str, Any]] = {}
    for symbol, info in CODATA_CONSTANTS.items():
        targets[info["value"]] = {**info, "symbol": symbol}

    # Gather candidate numeric strings from both sources.
    candidates: List[str] = []
    for _, text in scalars:
        candidates.append(text)
    if corpus:
        candidates.extend(_numeric_tokens(corpus))

    matched_symbols: set = set()
    for text in candidates:
        try:
            value = float(text)
        except (TypeError, ValueError):
            continue
        for target_val, info in targets.items():
            if _matches_constant(value, target_val):
                symbol = info["symbol"]
                if symbol in matched_symbols:
                    continue
                matched_symbols.add(symbol)
                matches.append(
                    PhysicalConstant(
                        symbol=symbol,
                        value=info["value"],
                        unit=info["unit"],
                        uncertainty=info["uncertainty"],
                        description=info["name"],
                        matches=(text,),
                    )
                )
    return matches


def _numeric_tokens(text: str) -> List[str]:
    """Extract numeric-looking substrings from free text."""
    import re

    return re.findall(r"[+-]?\d+\.?\d*(?:[eE][+-]?\d+)?", text)


def _matches_constant(found: float, expected: float) -> bool:
    if expected == 0.0:
        return abs(found) < FLOAT64_EPS
    rel = abs(found - expected) / abs(expected)
    return rel < 1e-6


def _detect_identities(corpus: str) -> List[MathematicalIdentity]:
    matches: List[MathematicalIdentity] = []
    lower = corpus.lower()
    for name, (description, keywords) in MATH_IDENTITIES.items():
        hit_keywords = tuple(k for k in keywords if k in lower)
        if hit_keywords:
            confidence = min(len(hit_keywords) / len(keywords), 1.0)
            matches.append(
                MathematicalIdentity(
                    name=name,
                    description=description,
                    matched_keywords=hit_keywords,
                    confidence=confidence,
                )
            )
    return matches


def _detect_tolerances(corpus: str) -> List[NumericalTolerance]:
    """Detect float32/float64 dtype usage and tolerance boundaries."""
    tolerances: List[NumericalTolerance] = []
    lower = corpus.lower()

    dtype_specs = (
        ("float32", "float32", FLOAT32_EPS, "np.float32"),
        ("float64", "float64", FLOAT64_EPS, "np.float64"),
        ("float16", "float16", 9.765625e-4, "np.float16"),
        ("float128", "float128", 1.9236588e-34, "np.float128"),
    )
    for kind, label, eps, spec in dtype_specs:
        if label in lower or spec.lower() in lower:
            tolerances.append(
                NumericalTolerance(
                    kind=kind,
                    lower_bound=0.0,
                    upper_bound=eps,
                    description=f"Machine epsilon for {kind} ({spec})",
                )
            )

    # Literal epsilon references.
    if "float32_eps" in lower or "np.finfo(float32)" in lower:
        tolerances.append(
            NumericalTolerance(
                kind="epsilon",
                lower_bound=0.0,
                upper_bound=FLOAT32_EPS,
                description="float32 machine epsilon boundary",
            )
        )
    if "float64_eps" in lower or "np.finfo(float64)" in lower:
        tolerances.append(
            NumericalTolerance(
                kind="epsilon",
                lower_bound=0.0,
                upper_bound=FLOAT64_EPS,
                description="float64 machine epsilon boundary",
            )
        )
    return tolerances


def _detect_crypto(corpus: str) -> List[CryptoPattern]:
    patterns: List[CryptoPattern] = []
    lower = corpus.lower()
    seen: set[str] = set()
    for kind, (description, keywords) in CRYPTO_PATTERNS.items():
        hit = tuple(k for k in keywords if k.lower() in lower)
        if hit and kind not in seen:
            seen.add(kind)
            patterns.append(
                CryptoPattern(
                    kind=kind,
                    description=description,
                    matched_keywords=hit,
                )
            )
    return patterns


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="invariant_detector",
        description="Static analyzer for mathematical/physical/cryptographic invariants in a CoreUAST.",
    )
    parser.add_argument("uast", type=Path, help="Path to a uast.json document.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("invariants.lock"),
        help="Output lockfile path (default: invariants.lock).",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Optional original source file (for richer corpus / stable hash).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.uast.exists():
        parser.error(f"UAST file not found: {args.uast}")
        return 2

    try:
        with open(args.uast, "r", encoding="utf-8") as f:
            uast = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {args.uast}: {exc}", file=sys.stderr)
        return 2

    source = ""
    if args.source is not None:
        source = args.source.read_text(encoding="utf-8")

    lock = detect_invariants(uast, source)
    if not args.source and uast.get("source_text"):
        # Re-run with embedded source text if available for a richer corpus.
        source = uast["source_text"]
        lock = detect_invariants(uast, source)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(lock.to_dict(), f, indent=2, ensure_ascii=False)

    # Surface the content hash for downstream certification.
    lock_hash = lock.content_hash()
    print(
        f"Detected {len(lock.physical_constants)} constants, "
        f"{len(lock.mathematical_identities)} identities, "
        f"{len(lock.numerical_tolerances)} tolerances, "
        f"{len(lock.crypto_patterns)} crypto patterns → {args.output} "
        f"(content_hash={lock_hash[:12]})"
    )
    print(f"invariants_hash={lock_hash}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
