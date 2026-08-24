#!/usr/bin/env python3
"""Certificate generator for an optimised code artefact.

Produces a JSON certificate that binds together:
  * the baseline source hash,
  * the optimised source hash,
  * the invariants lockfile hash (so tampering is detectable),
  * the evolution seed used,
  * the configuration hash,
  * an optional HMAC signature (``--sign``) produced with the CI secret
    ``CERTIFY_HMAC_SECRET``.

Usage:
    python certify.py \
        --baseline baseline.json \
        --optimized optimized.json \
        --invariants invariants.lock \
        --seed 12345 \
        --config config.yaml \
        [--sign] \
        [-o certificate.json]

Exit codes:
    0  certificate generated (with or without signature)
    2  missing required artefact / input error
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

__all__ = ["Certificate", "CertificateBuilder"]

CERTIFICATE_VERSION = "1.0.0"


@dataclass
class Certificate:
    version: str
    baseline_hash: str
    optimized_hash: str
    invariants_hash: str
    seed: Any
    config_hash: str
    signature_algorithm: str = ""
    signature: str = ""
    signed: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Certificate":
        return cls(
            version=data.get("version", CERTIFICATE_VERSION),
            baseline_hash=data.get("baseline_hash", ""),
            optimized_hash=data.get("optimized_hash", ""),
            invariants_hash=data.get("invariants_hash", ""),
            seed=data.get("seed"),
            config_hash=data.get("config_hash", ""),
            signature_algorithm=data.get("signature_algorithm", ""),
            signature=data.get("signature", ""),
            signed=data.get("signed", False),
            details=data.get("details", {}),
        )

    def verify_signature(self, secret: str) -> bool:
        """Verify the HMAC signature against *secret* (empty if unsigned)."""
        if not self.signed or not self.signature:
            return False
        expected = _compute_hmac(self._signable_dict(), secret)
        return hmac.compare_digest(self.signature, expected)

    def _signable_dict(self) -> Dict[str, Any]:
        return {
            "baseline_hash": self.baseline_hash,
            "optimized_hash": self.optimized_hash,
            "invariants_hash": self.invariants_hash,
            "seed": self.seed,
            "config_hash": self.config_hash,
        }


def _stable_hash(data: str) -> str:
    """SHA-256 hex of a string payload."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    """SHA-256 hex of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_json(path: Path, key: str = "hash") -> str:
    """Extract a hash from a JSON artefact.

    Accepts several shapes:
      * ``{"hash": "..."}``
      * ``{"baseline_hash": "..."}`` / ``{"optimized_hash": "..."}``
      * ``{"content_hash": "..."}``
    Falls back to hashing the raw file contents.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _hash_file(path)
    for k in (key, "hash", "content_hash", "baseline_hash", "optimized_hash"):
        v = data.get(k) if isinstance(data, dict) else None
        if isinstance(v, str) and v:
            return v
    return _hash_file(path)


def _hash_invariants(path: Path) -> str:
    """Hash an invariants lockfile.

    Prefers an explicit ``hash``/``invariants_hash`` field, otherwise computes a
    SHA-256 over the canonicalised (sorted-key) JSON payload.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _hash_file(path)
    if isinstance(data, dict):
        if data.get("hash"):
            return data["hash"]
        if data.get("invariants_hash"):
            return data["invariants_hash"]
        # Recompute a content hash over the stable payload (excluding the hash
        # field itself if present, to avoid self-reference).
        payload = {k: v for k, v in sorted(data.items()) if not k.endswith("_hash")}
        return _stable_hash(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    return _hash_file(path)


def _hash_config(path: Optional[Path]) -> str:
    if path is None:
        return ""
    if not path.exists():
        return ""
    return _hash_file(path)


def _compute_hmac(payload: Dict[str, Any], secret: str) -> str:
    """HMAC-SHA256 over the canonical JSON of the signable payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


class CertificateBuilder:
    """Assemble a Certificate from artefact file paths."""

    def __init__(self, seed: Any = None, secret: Optional[str] = None):
        self.seed = seed
        self.secret = secret

    def build(
        self,
        baseline: Path,
        optimized: Path,
        invariants: Path,
        config: Optional[Path] = None,
    ) -> Certificate:
        baseline_hash = _hash_json(baseline, key="baseline_hash")
        optimized_hash = _hash_json(optimized, key="optimized_hash")
        invariants_hash = _hash_invariants(invariants)
        config_hash = _hash_config(config)

        cert = Certificate(
            version=CERTIFICATE_VERSION,
            baseline_hash=baseline_hash,
            optimized_hash=optimized_hash,
            invariants_hash=invariants_hash,
            seed=self.seed,
            config_hash=config_hash,
        )
        if self.secret:
            cert.signature_algorithm = "HMAC-SHA256"
            cert.signature = _compute_hmac(cert._signable_dict(), self.secret)
            cert.signed = True
        return cert


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="certify",
        description="Generate a JSON certificate binding baseline/optimized hashes, invariants, seed and config.",
    )
    parser.add_argument(
        "--baseline", type=Path, required=True, help="Path to baseline.json artefact."
    )
    parser.add_argument(
        "--optimized", type=Path, required=True, help="Path to optimized.json artefact."
    )
    parser.add_argument(
        "--invariants", type=Path, required=True, help="Path to invariants.lock artefact."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional config file hashed into the certificate.",
    )
    parser.add_argument("--seed", default=None, help="Evolution seed (int or string).")
    parser.add_argument(
        "--sign",
        action="store_true",
        help="Sign the certificate with HMAC-SHA256 using $CERTIFY_HMAC_SECRET.",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("certificate.json"), help="Output path."
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    for label, path in (
        ("baseline", args.baseline),
        ("optimized", args.optimized),
        ("invariants", args.invariants),
    ):
        if not path.exists():
            print(f"Error: {label} artefact not found: {path}", file=sys.stderr)
            return 2

    secret = None
    if args.sign:
        import os

        secret = os.environ.get("CERTIFY_HMAC_SECRET", "")
        if not secret:
            print("Error: --sign requires $CERTIFY_HMAC_SECRET to be set", file=sys.stderr)
            return 2

    # Coerce seed into int when possible for type stability.
    seed: Any = args.seed
    if seed is not None:
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = str(seed)

    builder = CertificateBuilder(seed=seed, secret=secret)
    cert = builder.build(
        baseline=args.baseline,
        optimized=args.optimized,
        invariants=args.invariants,
        config=args.config,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(cert.to_dict(), f, indent=2, ensure_ascii=False)

    print(f"Certificate written to {args.output}")
    print(f"baseline_hash={cert.baseline_hash[:16]} optimized_hash={cert.optimized_hash[:16]}")
    print(
        f"invariants_hash={cert.invariants_hash[:16]} config_hash={cert.config_hash[:16] or 'none'}"
    )
    if cert.signed:
        print(f"signed={cert.signed} signature={cert.signature[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
