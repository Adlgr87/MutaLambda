#!/usr/bin/env python3
"""Python language handler using existing UAST infrastructure."""
import ast
import shutil
import subprocess
import tempfile
import time
from typing import Optional

from muta_ext.uast.core_uast import CoreUAST
from muta_ext.uast.adapters.python_adapter import PythonAdapter
from muta_ext.uast.emitters.python_emitter import PythonEmitter
from muta_ext.uast.handlers.base_handler import BaseLanguageHandler


class PythonHandler(BaseLanguageHandler):
    """Language handler for Python using the existing UAST infrastructure."""

    def __init__(self, config: Optional[dict] = None):
        self._adapter = PythonAdapter()
        self._emitter = PythonEmitter()
        self._config = config or {}

    def parse(self, source: str) -> CoreUAST:
        """Parse Python source to CoreUAST."""
        return self._adapter.parse_to_uast(source)

    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST to Python source."""
        return self._emitter.emit(uast)

    def validate_syntax(self, source: str) -> tuple[bool, str]:
        """Validate Python syntax using ast.parse."""
        try:
            ast.parse(source)
            return (True, "")
        except SyntaxError as e:
            return (False, str(e))

    def compile(self, source: str, output_path: str) -> tuple[bool, str]:
        """Compile Python source (compile to pyc)."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
                f.write(source.encode())
                tmpfile = f.name
            
            result = subprocess.run(
                ["python", "-m", "py_compile", tmpfile],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            import os
            os.unlink(tmpfile)
            
            if result.returncode == 0:
                return (True, "")
            return (False, result.stderr)
        except Exception as e:
            return (False, str(e))

    def run_tests(self, source: str, test_source: str) -> tuple[bool, str, float]:
        """Run Python tests using pytest."""
        start = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                main_py = f"{tmpdir}/main.py"
                test_py = f"{tmpdir}/test_main.py"
                
                with open(main_py, "w") as f:
                    f.write(source)
                
                with open(test_py, "w") as f:
                    f.write(test_source)
                
                result = subprocess.run(
                    ["python", "-m", "pytest", test_py, "-v"],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                elapsed = time.perf_counter() - start
                return (result.returncode == 0, result.stdout + result.stderr, elapsed)
        except Exception as e:
            return (False, str(e), 0.0)

    def benchmark(self, binary_path: str, iterations: int = 1000) -> dict:
        """Benchmark Python script execution."""
        times = []
        try:
            for _ in range(iterations):
                start = time.perf_counter()
                result = subprocess.run(
                    ["python", binary_path],
                    capture_output=True,
                    text=True,
                    timeout=self._config.get("run_timeout_sec", 10)
                )
                elapsed = time.perf_counter() - start
                times.append(elapsed)
        except Exception:
            pass
        
        if not times:
            return {"error": "No successful runs"}
        
        import statistics
        return {
            "latency_p50": statistics.median(times),
            "latency_p99": sorted(times)[int(len(times) * 0.99)] if times else 0,
            "throughput": iterations / sum(times) if times else 0,
            "runs": len(times)
        }

    def roundtrip(self, source: str) -> str:
        """Parse → CoreUAST → Emit roundtrip test."""
        uast = self.parse(source)
        return self.emit(uast)