#!/usr/bin/env python3
"""Go language handler for UAST integration."""
import shutil
import subprocess
from typing import Tuple

from muta_ext.uast.core_uast import CoreUAST
from muta_ext.uast.adapters.go_adapter import GoAdapter, parse_to_uast
from muta_ext.uast.emitters.go_emitter import GoEmitter, emit_from_uast
from muta_ext.uast.handlers.base_handler import BaseLanguageHandler
from muta_ext.uast.handlers.toolchain import run_on_temp_source


class GoHandler(BaseLanguageHandler):
    """Go language handler for MutaLambda."""

    language = "go"

    def __init__(self):
        self.adapter = GoAdapter()
        self.emitter = GoEmitter()

    def parse(self, source: str) -> CoreUAST:
        """Parse Go source to CoreUAST."""
        return parse_to_uast(source)

    def emit(self, uast: CoreUAST) -> str:
        """Emit CoreUAST back to Go source."""
        return emit_from_uast(uast)

    def validate_syntax(self, source: str) -> Tuple[bool, str]:
        """Validate Go syntax using go tool vet or gofmt."""
        if not shutil.which("gofmt"):
            return True, "gofmt not available, skipping syntax validation"

        try:
            result = subprocess.run(
                ["gofmt", "-e"],
                input=source,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, "valid"
            else:
                return False, result.stderr
        except subprocess.TimeoutExpired:
            return False, "validation timeout"
        except Exception as e:
            return False, str(e)

    def compile(self, source: str, output_path: str) -> Tuple[bool, str]:
        """Compile Go source to binary."""
        if not shutil.which("go"):
            return False, "go compiler not found"

        ok, message = run_on_temp_source(
            source,
            ".go",
            lambda path: ["go", "build", "-o", output_path, path],
            30,
            "compilation timeout",
        )
        return (True, "compiled successfully") if ok else (False, message)

    def run_tests(self, source: str, test_source: str) -> Tuple[bool, str, float]:
        """Run Go tests."""
        if not shutil.which("go"):
            return False, "go compiler not found", 0.0

        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write source files
            main_file = os.path.join(tmpdir, "main.go")
            test_file = os.path.join(tmpdir, "main_test.go")
            with open(main_file, 'w') as f:
                f.write(source)
            with open(test_file, 'w') as f:
                f.write(test_source)

            try:
                result = subprocess.run(
                    ["go", "test", "-v", "-bench=.", "-benchtime=1x", tmpdir],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                elapsed = 0.0
                for line in result.stdout.split('\n'):
                    if 'Benchmark' in line and 'ns/op' in line:
                        try:
                            elapsed = float(line.split('/')[-2].split(' ')[0])
                        except (ValueError, IndexError):
                            pass
                        break
                return result.returncode == 0, result.stdout, elapsed
            except subprocess.TimeoutExpired:
                return False, "test timeout", 0.0
            except Exception as e:
                return False, str(e), 0.0

    def benchmark(self, binary_path: str, iterations: int = 1000) -> dict:
        """Run benchmark on compiled Go binary."""
        if not shutil.which(binary_path):
            return {"error": "binary not found"}

        try:
            result = subprocess.run(
                [binary_path, "-test.bench=.", "-test.benchtime", f"{iterations}x"],
                capture_output=True,
                text=True,
                timeout=120
            )
            benchmarks = {}
            for line in result.stdout.split('\n'):
                if 'Benchmark' in line and 'ns/op' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        name = parts[0]
                        ops = parts[-2]
                        try:
                            benchmarks[name] = float(ops.replace('ns/op', ''))
                        except ValueError:
                            pass
            return benchmarks
        except subprocess.TimeoutExpired:
            return {"error": "benchmark timeout"}
        except Exception as e:
            return {"error": str(e)}


# Registry function
def get_handler() -> GoHandler:
    """Get Go language handler instance."""
    return GoHandler()
