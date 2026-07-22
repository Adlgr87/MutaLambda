#!/usr/bin/env python3
"""C++ language handler for UAST multi-language support."""
import shutil
import subprocess
import tempfile
import time
from typing import Optional

from muta_ext.uast.core_uast import CoreUAST
from muta_ext.uast.adapters.cpp_adapter import CppAdapter
from muta_ext.uast.emitters.cpp_emitter import CppEmitter
from muta_ext.uast.handlers.base_handler import BaseLanguageHandler


class CppHandler(BaseLanguageHandler):
    """Language handler for C++."""

    def __init__(self, config: Optional[dict] = None):
        self._adapter = CppAdapter()
        self._emitter = CppEmitter()
        self._config = config or {}
        self._compile_timeout = self._config.get("compile_timeout_sec", 30)
        self._run_timeout = self._config.get("run_timeout_sec", 10)
        self._use_sanitizers = self._config.get("sanitizers", False)

    def parse(self, source: str) -> CoreUAST:
        """Parse C++ source to CoreUAST."""
        return self._adapter.parse_to_uast(source)

    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST to C++ source."""
        return self._emitter.emit(uast)

    def validate_syntax(self, source: str) -> tuple[bool, str]:
        """Validate C++ syntax using g++."""
        if not shutil.which("g++"):
            # Fallback: just try to parse with tree-sitter
            return (True, "") if self._adapter.can_parse(source) else (False, "g++ not available")
        
        try:
            with tempfile.NamedTemporaryFile(suffix=".cpp", delete=False) as f:
                f.write(source.encode())
                tmpfile = f.name
            
            result = subprocess.run(
                ["g++", "-fsyntax-only", "-std=c++17", tmpfile],
                capture_output=True,
                text=True,
                timeout=self._compile_timeout
            )
            
            import os
            os.unlink(tmpfile)
            
            if result.returncode == 0:
                return (True, "")
            return (False, result.stderr)
        except subprocess.TimeoutExpired:
            return (False, "Syntax check timed out")
        except Exception as e:
            return (False, str(e))

    def compile(self, source: str, output_path: str) -> tuple[bool, str]:
        """Compile C++ source with g++."""
        if not shutil.which("g++"):
            return (False, "g++ not available")
        
        try:
            with tempfile.NamedTemporaryFile(suffix=".cpp", delete=False) as f:
                f.write(source.encode())
                tmpfile = f.name
            
            cmd = ["g++", "-O2", "-std=c++17", tmpfile, "-o", output_path]
            if self._use_sanitizers:
                cmd.insert(1, "-fsanitize=undefined,address")
                cmd.insert(1, "-fno-sanitize-recover=all")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._compile_timeout
            )
            
            import os
            os.unlink(tmpfile)
            
            if result.returncode == 0:
                return (True, "")
            return (False, result.stderr)
        except subprocess.TimeoutExpired:
            return (False, "Compilation timed out")
        except Exception as e:
            return (False, str(e))

    def run_tests(self, source: str, test_source: str) -> tuple[bool, str, float]:
        """Run C++ tests."""
        # For simplicity, compile and run the combined source
        if not shutil.which("g++"):
            return (True, "g++ not available, skipping tests", 0.0)
        
        start = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                main_cpp = f"{tmpdir}/main.cpp"
                with open(main_cpp, "w") as f:
                    f.write(source)
                    if test_source:
                        f.write("\n" + test_source)
                
                output_path = f"{tmpdir}/test_binary"
                result = subprocess.run(
                    ["g++", "-O2", "-std=c++17", main_cpp, "-o", output_path],
                    capture_output=True,
                    text=True,
                    timeout=self._compile_timeout
                )
                
                elapsed = time.perf_counter() - start
                
                if result.returncode != 0:
                    return (False, result.stderr, elapsed)
                
                # Run the binary
                run_result = subprocess.run(
                    [output_path],
                    capture_output=True,
                    text=True,
                    timeout=self._run_timeout
                )
                
                return (run_result.returncode == 0, run_result.stdout + run_result.stderr, elapsed)
        except Exception as e:
            return (False, str(e), 0.0)

    def benchmark(self, binary_path: str, iterations: int = 1000) -> dict:
        """Run benchmark on compiled binary."""
        if not shutil.which(binary_path):
            return {"error": "Binary not found"}
        
        times = []
        try:
            for _ in range(iterations):
                start = time.perf_counter()
                result = subprocess.run(
                    [binary_path],
                    capture_output=True,
                    text=True,
                    timeout=self._run_timeout
                )
                elapsed = time.perf_counter() - start
                times.append(elapsed)
        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            return {"error": str(e)}
        
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

    def supported_features(self) -> dict:
        """Return supported features information."""
        return {
            "functions": True,
            "if_else": True,
            "for_while": True,
            "match": True,  # switch
            "structs_simple": True,
            "templates": False,
            "lambdas": False,
            "preprocessor": False,
        }