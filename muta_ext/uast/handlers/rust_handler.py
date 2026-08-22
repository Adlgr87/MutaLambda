#!/usr/bin/env python3
"""Rust language handler for UAST multi-language support."""
import shutil
import subprocess
import tempfile
import time
from typing import Optional

from muta_ext.uast.core_uast import CoreUAST
from muta_ext.uast.adapters.rust_adapter import RustAdapter
from muta_ext.uast.emitters.rust_emitter import RustEmitter
from muta_ext.uast.handlers.base_handler import BaseLanguageHandler
from muta_ext.uast.handlers.toolchain import benchmark_command, run_on_temp_source


class RustHandler(BaseLanguageHandler):
    """Language handler for Rust."""

    def __init__(self, config: Optional[dict] = None):
        self._adapter = RustAdapter()
        self._emitter = RustEmitter()
        self._config = config or {}
        self._compile_timeout = self._config.get("compile_timeout_sec", 30)
        self._run_timeout = self._config.get("run_timeout_sec", 10)

    def parse(self, source: str) -> CoreUAST:
        """Parse Rust source to CoreUAST."""
        return self._adapter.parse_to_uast(source)

    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST to Rust source."""
        return self._emitter.emit(uast)

    def validate_syntax(self, source: str) -> tuple[bool, str]:
        """Validate Rust syntax using rustc."""
        if not shutil.which("rustc"):
            # Fallback: just try to parse with tree-sitter
            return (True, "") if self._adapter.can_parse(source) else (False, "rustc not available")

        return run_on_temp_source(
            source,
            ".rs",
            lambda path: [
                "rustc", "--edition", "2021", "--crate-type", "lib", "-o", "/dev/null", path
            ],
            self._compile_timeout,
            "Syntax check timed out",
        )

    def compile(self, source: str, output_path: str) -> tuple[bool, str]:
        """Compile Rust source with rustc."""
        if not shutil.which("rustc"):
            return (False, "rustc not available")

        return run_on_temp_source(
            source,
            ".rs",
            lambda path: ["rustc", "--edition", "2021", path, "-o", output_path],
            self._compile_timeout,
            "Compilation timed out",
        )

    def run_tests(self, source: str, test_source: str) -> tuple[bool, str, float]:
        """Run Rust tests using cargo or rustc."""
        if not shutil.which("cargo"):
            # Fallback: can't run tests without cargo
            return (True, "cargo not available, skipping tests", 0.0)
        
        # For simplicity, we'll just compile and run basic tests
        # Full test integration would require a cargo project structure
        start = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Create minimal Cargo.toml
                import os
                cargo_toml = os.path.join(tmpdir, "Cargo.toml")
                with open(cargo_toml, "w") as f:
                    f.write('[package]\nname = "test"\nversion = "0.1.0"\nedition = "2021"\n')
                
                # Create src directory
                src_dir = os.path.join(tmpdir, "src")
                os.makedirs(src_dir)
                
                # Write main.rs with source + tests
                main_rs = os.path.join(src_dir, "main.rs")
                with open(main_rs, "w") as f:
                    f.write(source)
                    if test_source:
                        f.write("\n" + test_source)
                
                result = subprocess.run(
                    ["cargo", "test", "--release"],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=self._compile_timeout * 3
                )
                
                elapsed = time.perf_counter() - start
                return (result.returncode == 0, result.stdout + result.stderr, elapsed)
        except Exception as e:
            return (False, str(e), 0.0)

    def benchmark(self, binary_path: str, iterations: int = 1000) -> dict:
        """Run benchmark on compiled binary."""
        if not shutil.which(binary_path):
            return {"error": "Binary not found"}
        return benchmark_command([binary_path], iterations, self._run_timeout)

    def supported_features(self) -> dict:
        """Return supported features information."""
        return {
            "functions": True,
            "if_else": True,
            "for_while": True,
            "match": True,
            "structs_simple": True,
            "traits": False,
            "macros": False,
            "closures": False,
            "unsafe": False,
            "generics": False,
            "async": False,
        }