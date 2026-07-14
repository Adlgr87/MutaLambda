"""External-project target adapter (workflow §15 — MASSIVE use case).

MutaLambda is a general evolutionary optimizer. [MASSIVE](https://github.com/Adlgr87/MASSIVE)
is a **separate** scientific simulation repo that historically motivated MutaLambda;
this adapter does **not** import MASSIVE. Point it at pure-function source files +
declarative tests from any project (including MASSIVE kernels).

Recommended first MASSIVE targets (if that repo is checked out separately):
- massive/core/utility_logic.py
- pure kernels from energy_engine / numerics

Avoid Streamlit/API/LangChain surfaces as first targets.
"""

from __future__ import annotations

import ast
import difflib
import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from api_fingerprint import compare_api, extract_api_fingerprint
from benchmarking import BenchmarkConfig, BenchmarkResult, run_callable_benchmark
from differential import DifferentialResult, differential_test
from runners import SubprocessRunner


@dataclass
class CorrectnessResult:
    ok: bool
    correctness: float
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "correctness": self.correctness,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass
class MassiveTargetAdapter:
    """Adapter that loads a pure-function MASSIVE (or local) target.

    Parameters
    ----------
    source_file:
        Path to a Python file containing the entrypoint function.
    tests_file or test_cases:
        Declarative JSON tests (function/args/expected/comparison).
    entrypoint:
        Public function name to preserve (API fingerprint + differential).
    massive_root:
        Optional MASSIVE repo root; used only for path resolution helpers.
    """

    source_file: str
    entrypoint: str = "solution"
    tests_file: str = ""
    test_cases: Optional[List[Dict[str, Any]]] = None
    benchmark_file: str = ""
    api_policy: str = "strict"
    massive_root: str = ""
    timeout_sec: float = 10.0

    def __post_init__(self) -> None:
        self._source_path = Path(self.source_file)
        if self.massive_root and not self._source_path.is_file():
            alt = Path(self.massive_root) / self.source_file
            if alt.is_file():
                self._source_path = alt
        if self.test_cases is None:
            self.test_cases = []
        if self.tests_file and not self.test_cases:
            self.test_cases = self._load_json_list(self.tests_file)
        self._benchmark_cfg = BenchmarkConfig()
        if self.benchmark_file:
            try:
                data = json.loads(Path(self.benchmark_file).read_text(encoding="utf-8"))
                self._benchmark_cfg = BenchmarkConfig(
                    warmups=int(data.get("warmups", 5)),
                    samples=int(data.get("samples", 30)),
                    operations_per_case=int(data.get("operations_per_case", 1)),
                    repetitions=int(data.get("repetitions", 1)),
                )
            except OSError:
                pass

    @staticmethod
    def _load_json_list(path: str) -> List[Dict[str, Any]]:
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"tests file must be a JSON list: {path}")
        return data

    def load_source(self) -> str:
        if not self._source_path.is_file():
            raise FileNotFoundError(f"source not found: {self._source_path}")
        return self._source_path.read_text(encoding="utf-8")

    def extract_entrypoint_source(self, source: Optional[str] = None) -> str:
        """Return the source of the entrypoint function only (when possible)."""
        src = source if source is not None else self.load_source()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return src
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == self.entrypoint:
                lines = src.splitlines(keepends=True)
                # 1-based linenos
                chunk = "".join(lines[node.lineno - 1 : node.end_lineno])
                return textwrap.dedent(chunk)
        return src

    def tests(self) -> List[Dict[str, Any]]:
        cases = list(self.test_cases or [])
        # Ensure function field defaults to entrypoint
        normalized = []
        for tc in cases:
            if not isinstance(tc, dict):
                continue
            item = dict(tc)
            item.setdefault("function", self.entrypoint)
            normalized.append(item)
        return normalized

    def evaluate(self, code: str) -> CorrectnessResult:
        runner = SubprocessRunner(timeout_sec=self.timeout_sec)
        result = runner.run(code, self.tests())
        return CorrectnessResult(
            ok=bool(result.passed and result.fitness.correctness >= 1.0),
            correctness=float(result.fitness.correctness),
            message="passed" if result.passed else (result.stderr or "failed")[:200],
            details={"metrics": dict(result.metrics)},
        )

    def equivalence(self, candidate: str) -> CorrectnessResult:
        """API + differential equivalence against the original source."""
        original = self.load_source()
        api = compare_api(
            extract_api_fingerprint(original),
            extract_api_fingerprint(candidate),
            policy=self.api_policy,
        )
        if not api.compatible:
            return CorrectnessResult(
                ok=False,
                correctness=0.0,
                message="api_incompatible",
                details=api.to_dict(),
            )
        diff: DifferentialResult = differential_test(
            original,
            candidate,
            self.tests(),
            default_function=self.entrypoint,
        )
        return CorrectnessResult(
            ok=diff.equivalent,
            correctness=1.0 if diff.equivalent else max(
                0.0, 1.0 - (diff.mismatches / max(1, diff.compared))
            ),
            message="equivalent" if diff.equivalent else "differential_mismatch",
            details=diff.to_dict(),
        )

    def benchmark(self, code: str) -> BenchmarkResult:
        """Micro-benchmark entrypoint using declared test inputs when available."""
        # Build a zero-arg callable that runs the entrypoint on first test args.
        namespace: Dict[str, Any] = {"__name__": "__massive_bench__"}
        try:
            exec(compile(code, "<bench>", "exec"), namespace, namespace)  # noqa: S102
        except Exception as exc:
            return BenchmarkResult(error=f"compile:{exc}")
        fn = namespace.get(self.entrypoint)
        if not callable(fn):
            return BenchmarkResult(error=f"missing entrypoint {self.entrypoint}")

        cases = self.tests()
        args_list = [list(tc.get("args", [])) for tc in cases if "args" in tc]
        if not args_list:
            args_list = [[]]

        def work() -> None:
            for args in args_list:
                fn(*args)

        return run_callable_benchmark(work, self._benchmark_cfg)

    def patch(self, original: str, candidate: str) -> str:
        """Unified diff patch for review / promotion packages."""
        return "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                candidate.splitlines(keepends=True),
                fromfile="original",
                tofile="candidate",
            )
        )

    def promotion_package(self, candidate: str) -> Dict[str, Any]:
        """Artifacts required before promoting a MASSIVE candidate."""
        original = self.load_source()
        correctness = self.evaluate(candidate)
        equiv = self.equivalence(candidate)
        bench_base = self.benchmark(original)
        bench_cand = self.benchmark(candidate)
        return {
            "entrypoint": self.entrypoint,
            "source_file": str(self._source_path),
            "correctness": correctness.to_dict(),
            "equivalence": equiv.to_dict(),
            "benchmark_baseline": bench_base.to_dict(),
            "benchmark_candidate": bench_cand.to_dict(),
            "patch": self.patch(original, candidate),
            "promotable": bool(
                correctness.ok and equiv.ok and not bench_cand.error
            ),
        }

    @classmethod
    def from_massive_utility_logic(
        cls,
        massive_root: str,
        tests_file: str,
        *,
        entrypoint: str = "calculate_group_cohesion",
    ) -> "MassiveTargetAdapter":
        """Factory for the first recommended pure MASSIVE target."""
        root = Path(massive_root)
        source = root / "massive" / "core" / "utility_logic.py"
        if not source.is_file():
            source = root / "utility_logic.py"
        return cls(
            source_file=str(source),
            entrypoint=entrypoint,
            tests_file=tests_file,
            massive_root=massive_root,
            api_policy="strict",
        )
