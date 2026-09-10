#!/usr/bin/env python3
"""Base language handler interface for UAST multi-language support."""

import os
import subprocess
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from muta_ext.uast.core_uast import CoreUAST

# ── Hardened subprocess execution for language handlers (ML-015) ────────────
# Candidate code is compiled/run through these toolchains. Every invocation
# goes through ``run_hardened`` so that: (1) no shell interpretation happens
# (``shell=False``), (2) secret-like environment variables are not inherited
# by the toolchain or the candidate binary, and (3) captured output is bounded.

_SAFE_ENV_VARS = {
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "HOME",
    # Toolchain caches required by Go/Rust builds.
    "GOPATH",
    "GOCACHE",
    "GOROOT",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "CC",
    "CXX",
    "CFLAGS",
    "CXXFLAGS",
}

_SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")

_MAX_OUTPUT_BYTES = 1_000_000


def _hardened_env() -> dict:
    """Copy the parent environment minus secret-looking variables."""
    env: dict = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if key in _SAFE_ENV_VARS:
            env[key] = value
            continue
        if any(hint in upper for hint in _SECRET_ENV_HINTS):
            continue  # drop potential secrets (API keys, tokens, passwords)
        env[key] = value
    return env


def run_hardened(
    cmd: List[str],
    *,
    timeout: float = 30.0,
    cwd: Optional[str] = None,
    max_output: int = _MAX_OUTPUT_BYTES,
) -> subprocess.CompletedProcess:
    """Run ``cmd`` without a shell, scrubbed env, bounded output and a timeout."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=_hardened_env(),
        )
    except subprocess.TimeoutExpired as exc:
        if isinstance(exc.stdout, str):
            exc.stdout = exc.stdout[:max_output]
        if isinstance(exc.stderr, str):
            exc.stderr = exc.stderr[:max_output]
        raise
    proc.stdout = (proc.stdout or "")[:max_output]
    proc.stderr = (proc.stderr or "")[:max_output]
    return proc


class BaseLanguageHandler(ABC):
    """Interface for language handlers. All language adapters
    must implement this to integrate with the evolution system."""

    @abstractmethod
    def parse(self, source: str) -> CoreUAST:
        """Parse source code to CoreUAST."""
        ...

    @abstractmethod
    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST back to source code."""
        ...

    @abstractmethod
    def validate_syntax(self, source: str) -> tuple[bool, str]:
        """Validate syntax without compilation."""
        ...

    @abstractmethod
    def compile(self, source: str, output_path: str) -> tuple[bool, str]:
        """Compile source to binary."""
        ...

    @abstractmethod
    def run_tests(self, source: str, test_source: str) -> tuple[bool, str, float]:
        """Run tests on compiled source."""
        ...

    @abstractmethod
    def benchmark(self, binary_path: str, iterations: int = 1000) -> dict:
        """Run benchmark on compiled binary."""
        ...

    @abstractmethod
    def roundtrip(self, source: str) -> str:
        """Parse → CoreUAST → Emit roundtrip."""
        ...
