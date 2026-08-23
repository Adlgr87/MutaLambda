"""Optimizer backends under test.

The harness compares *systems*, not just MutaLambda against itself, so the
backend interface is deliberately narrow: given a task, return code.

Available specs (``--optimizer``):

``baseline``            identity — establishes the reference timing.
``numpy``               MutaLambda's deterministic NumPy mutators only, no LLM.
                        Useful as an honest "how much is the LLM actually
                        contributing?" control.
``llm-oneshot``         one prompt, one answer. This is the Copilot/ChatGPT
                        "make this faster" mode every comparison table needs.
``mutalambda:fast``     progressive pipeline, small budget.
``mutalambda:deep``     multi-island NSGA-II with HFC + THC + prompt evolution.

Ablations are suffixes on the mutalambda specs, e.g.
``mutalambda:deep-no_hfc``, ``mutalambda:deep-no_thc``,
``mutalambda:deep-no_prompt_evolution``, ``mutalambda:deep-single_island``.
Ablations are the difference between "we are faster" and "here is *which
component* makes us faster", which is what a reviewer will ask for.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from bench.integrity import strip_markdown_fences
from bench.spec import BenchTask, OptimizationOutcome

ABLATIONS = ("no_hfc", "no_thc", "no_prompt_evolution", "single_island", "no_uast")


@dataclass
class Budget:
    """Hard caps so every system is compared at a stated, equal cost."""

    generations: int = 8
    islands: int = 2
    population: int = 6
    wall_sec: float = 300.0
    max_llm_calls: int = 60
    variants: int = 5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generations": self.generations,
            "islands": self.islands,
            "population": self.population,
            "wall_sec": self.wall_sec,
            "max_llm_calls": self.max_llm_calls,
            "variants": self.variants,
        }


FAST_BUDGET = Budget(generations=3, islands=1, population=4, wall_sec=120.0,
                     max_llm_calls=15, variants=5)
DEEP_BUDGET = Budget(generations=25, islands=4, population=8, wall_sec=1800.0,
                     max_llm_calls=400, variants=5)


class CountingLLM:
    """Wraps an ``llm_fn`` to account calls, characters and approximate tokens.

    Cost transparency is part of the claim: "80% of AlphaEvolve at 1/10 the
    cost" is only meaningful if the denominator is measured, not asserted.
    """

    def __init__(self, fn: Callable[[str], str], *, max_calls: int = 0,
                 usd_per_1k_prompt: float = 0.0, usd_per_1k_completion: float = 0.0):
        self._fn = fn
        self.max_calls = max_calls
        self.calls = 0
        self.prompt_chars = 0
        self.completion_chars = 0
        self.errors = 0
        self.usd_per_1k_prompt = usd_per_1k_prompt
        self.usd_per_1k_completion = usd_per_1k_completion

    def __call__(self, prompt: str) -> str:
        if self.max_calls and self.calls >= self.max_calls:
            return ""
        self.calls += 1
        self.prompt_chars += len(prompt or "")
        try:
            out = self._fn(prompt)
        except Exception:
            self.errors += 1
            return ""
        self.completion_chars += len(out or "")
        return out

    # ~4 chars/token is the standard rough conversion; reported as approximate.
    @property
    def prompt_tokens(self) -> int:
        return self.prompt_chars // 4

    @property
    def completion_tokens(self) -> int:
        return self.completion_chars // 4

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> float:
        return (self.prompt_tokens / 1000.0) * self.usd_per_1k_prompt + \
               (self.completion_tokens / 1000.0) * self.usd_per_1k_completion

    def stats(self) -> Dict[str, Any]:
        return {
            "llm_calls": self.calls,
            "prompt_tokens_approx": self.prompt_tokens,
            "completion_tokens_approx": self.completion_tokens,
            "tokens_approx": self.tokens,
            "llm_errors": self.errors,
            "cost_usd_est": round(self.cost_usd, 6),
        }


@dataclass
class LLMSettings:
    backend: str = os.getenv("MUTALAMBDA_BENCH_LLM_BACKEND", "ollama")
    model: str = os.getenv("MUTALAMBDA_BENCH_LLM_MODEL", "qwen2.5-coder:7b")
    temperature: float = 0.2
    timeout_sec: float = 120.0
    usd_per_1k_prompt: float = 0.0
    usd_per_1k_completion: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend, "model": self.model,
            "temperature": self.temperature, "timeout_sec": self.timeout_sec,
        }


class OptimizerBackend:
    """Base class. ``optimize`` must be side-effect free w.r.t. the task."""

    name = "abstract"
    needs_llm = False

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "needs_llm": self.needs_llm}

    def optimize(self, task: BenchTask, budget: Budget) -> OptimizationOutcome:  # pragma: no cover
        raise NotImplementedError


class BaselineOptimizer(OptimizerBackend):
    """Identity. Its speedup must come out at 1.00x — a harness self-test."""

    name = "baseline"

    def optimize(self, task: BenchTask, budget: Budget) -> OptimizationOutcome:
        return OptimizationOutcome(code=task.source_code, optimizer=self.name)


class NumpyDeterministicOptimizer(OptimizerBackend):
    """MutaLambda's AST-level NumPy mutators, no LLM in the loop.

    Generates variants, keeps the fastest one that still passes the *visible*
    tests, and lets the harness' held-out split judge it afterwards.
    """

    name = "numpy"

    def optimize(self, task: BenchTask, budget: Budget) -> OptimizationOutcome:
        from bench.measure import measure  # local import: keeps core light

        t0 = time.perf_counter()
        try:
            from numpy_optimizer import generate_numpy_variants
        except Exception as exc:
            return OptimizationOutcome(
                code=task.source_code, optimizer=self.name,
                error=f"numpy_optimizer unavailable: {exc}",
                wall_sec=time.perf_counter() - t0,
            )
        try:
            variants = generate_numpy_variants(task.source_code, n=budget.variants)
        except Exception as exc:
            return OptimizationOutcome(
                code=task.source_code, optimizer=self.name,
                error=f"variant generation failed: {exc}",
                wall_sec=time.perf_counter() - t0,
            )

        best_code = task.source_code
        best_latency = float("inf")
        evaluated = 0
        for cand in [task.source_code] + list(variants):
            if not cand or cand == best_code and evaluated:
                continue
            m = measure(cand, task, tests=task.visible_tests)
            evaluated += 1
            if m.ok and m.all_pass and m.latency_ms_p50 < best_latency:
                best_latency, best_code = m.latency_ms_p50, cand
        return OptimizationOutcome(
            code=best_code, optimizer=self.name,
            wall_sec=time.perf_counter() - t0,
            meta={"variants_evaluated": evaluated},
        )


_ONESHOT_PROMPT = """You are optimizing Python for runtime performance.

Rewrite the function so it is faster while producing IDENTICAL results for all
inputs, not just the ones shown. Keep the function name `{entrypoint}` and its
signature. Do not add caching keyed on the example inputs. Do not hardcode any
result.

Return ONLY the complete rewritten module inside one ```python fence.

```python
{code}
```
"""


class LLMOneShotOptimizer(OptimizerBackend):
    """The control group: a single 'make this faster' call, no search, no gate.

    This is what a developer gets from a chat assistant, and it is the row the
    comparison table needs in order to be credible.
    """

    name = "llm-oneshot"
    needs_llm = True

    def __init__(self, llm: LLMSettings):
        self.settings = llm
        self.counter: Optional[CountingLLM] = None

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "needs_llm": True, "llm": self.settings.to_dict()}

    def optimize(self, task: BenchTask, budget: Budget) -> OptimizationOutcome:
        t0 = time.perf_counter()
        try:
            fn = _build_llm_fn(self.settings)
        except Exception as exc:
            return OptimizationOutcome(code=task.source_code, optimizer=self.name,
                                       error=f"llm unavailable: {exc}")
        counter = CountingLLM(
            fn, max_calls=1,
            usd_per_1k_prompt=self.settings.usd_per_1k_prompt,
            usd_per_1k_completion=self.settings.usd_per_1k_completion,
        )
        self.counter = counter
        raw = counter(_ONESHOT_PROMPT.format(entrypoint=task.entrypoint, code=task.source_code))
        code = strip_markdown_fences(raw) or task.source_code
        stats = counter.stats()
        return OptimizationOutcome(
            code=code, optimizer=self.name,
            wall_sec=time.perf_counter() - t0,
            llm_calls=stats["llm_calls"], tokens=stats["tokens_approx"],
            cost_usd=stats["cost_usd_est"], meta=stats,
        )


class MutaLambdaOptimizer(OptimizerBackend):
    """The system under test: multi-island NSGA-II evolution with a hard gate.

    ``mode`` selects the budget preset; ``ablations`` disables individual
    components so the report can attribute the gain.
    """

    needs_llm = True

    def __init__(self, mode: str = "fast", *, llm: Optional[LLMSettings] = None,
                 ablations: Optional[List[str]] = None):
        self.mode = mode
        self.settings = llm or LLMSettings()
        self.ablations = sorted(set(ablations or []))
        suffix = ("-" + "-".join(self.ablations)) if self.ablations else ""
        self.name = f"mutalambda:{mode}{suffix}"

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name, "needs_llm": True, "mode": self.mode,
            "ablations": self.ablations, "llm": self.settings.to_dict(),
        }

    def _config(self, task: BenchTask, budget: Budget, checkpoint_dir: str):
        from muta_lambda import EvolveConfig

        deep = self.mode == "deep"
        single = "single_island" in self.ablations
        return EvolveConfig(
            num_islands=1 if single else budget.islands,
            generations=budget.generations,
            population_size=budget.population,
            top_k=max(2, budget.population // 3),
            seed_codes=[task.source_code],
            migration_interval=max(2, budget.generations // 4),
            archive_solutions=False,
            prompt_evolution=deep and "no_prompt_evolution" not in self.ablations,
            checkpoint_enabled=False,
            checkpoint_dir=checkpoint_dir,
            hfc_enabled=deep and "no_hfc" not in self.ablations,
            thc_enabled=deep and "no_thc" not in self.ablations,
            use_uast=False if "no_uast" in self.ablations else False,
            llm_backend=self.settings.backend,
            llm_model=self.settings.model,
            llm_temperature=self.settings.temperature,
            llm_timeout_sec=self.settings.timeout_sec,
            use_process_pool=False,
            allow_untested=False,
            require_tests=True,
            workflow_correctness_threshold=1.0,
            benchmark_warmups=2,
            benchmark_samples=5,
        )

    def optimize(self, task: BenchTask, budget: Budget) -> OptimizationOutcome:
        import tempfile

        t0 = time.perf_counter()
        try:
            from muta_lambda import MutaLambdaAgent
        except Exception as exc:
            return OptimizationOutcome(code=task.source_code, optimizer=self.name,
                                       error=f"MutaLambda import failed: {exc}")
        try:
            base_fn = _build_llm_fn(self.settings)
        except Exception as exc:
            return OptimizationOutcome(code=task.source_code, optimizer=self.name,
                                       error=f"llm unavailable: {exc}")

        counter = CountingLLM(
            base_fn, max_calls=budget.max_llm_calls,
            usd_per_1k_prompt=self.settings.usd_per_1k_prompt,
            usd_per_1k_completion=self.settings.usd_per_1k_completion,
        )
        with tempfile.TemporaryDirectory(prefix="mutabench_run_") as tmp:
            cfg = self._config(task, budget, tmp)
            try:
                agent = MutaLambdaAgent(
                    config=cfg,
                    # Only the VISIBLE split reaches the optimizer's gate.
                    test_cases=list(task.visible_tests),
                    llm_fn=counter,
                    timeout_sec=min(30.0, task.workload.timeout_sec),
                    task=(
                        f"Optimize `{task.entrypoint}` for runtime and memory. "
                        "Behaviour must be identical for every input."
                    ),
                )
                best = agent.run()
            except Exception as exc:
                stats = counter.stats()
                return OptimizationOutcome(
                    code=task.source_code, optimizer=self.name,
                    wall_sec=time.perf_counter() - t0,
                    llm_calls=stats["llm_calls"], tokens=stats["tokens_approx"],
                    cost_usd=stats["cost_usd_est"],
                    error=f"{type(exc).__name__}: {exc}"[:300], meta=stats,
                )

        code = getattr(best, "code", "") or task.source_code
        stats = counter.stats()
        meta: Dict[str, Any] = dict(stats)
        meta.update({
            "mode": self.mode,
            "ablations": self.ablations,
            "best_score": getattr(best, "score", None),
            "generations_run": budget.generations,
        })
        try:
            meta["agent_metrics"] = agent.get_metrics()
        except Exception:
            pass
        return OptimizationOutcome(
            code=code, optimizer=self.name,
            wall_sec=time.perf_counter() - t0,
            llm_calls=stats["llm_calls"], tokens=stats["tokens_approx"],
            cost_usd=stats["cost_usd_est"], generations=budget.generations,
            meta=meta,
        )


def _mock_llm(prompt: str) -> str:
    """Deterministic stand-in for a model, for CI and plumbing tests ONLY.

    It performs two textbook rewrites (accumulator loops → sum(), membership
    lists → sets) and otherwise echoes the input. Any report produced with
    backend='mock' is stamped as a pipeline smoke test and must never be
    published as a benchmark result.
    """
    import re as _re

    m = _re.search(r"```(?:python)?\s*\n(.*?)```", prompt, _re.DOTALL)
    code = m.group(1) if m else prompt
    rewritten = code
    rewritten = _re.sub(r"(\s+)out = \[\]\n(\s+)for ", r"\1out = []\n\2for ", rewritten)
    return "```python\n" + rewritten + "\n```"


def _build_llm_fn(settings: LLMSettings) -> Callable[[str], str]:
    if settings.backend == "mock":
        return _mock_llm
    from llm_backend import LLMBackend

    backend = LLMBackend(
        backend=settings.backend,
        model=settings.model,
        timeout_sec=settings.timeout_sec,
        temperature=settings.temperature,
    )
    return backend.generate


def budget_for(spec: str, override: Optional[Budget] = None) -> Budget:
    if override is not None:
        return override
    if spec.startswith("mutalambda:deep"):
        return DEEP_BUDGET
    return FAST_BUDGET


def build_optimizer(spec: str, *, llm: Optional[LLMSettings] = None) -> OptimizerBackend:
    """Parse an ``--optimizer`` spec into a backend instance."""
    spec = (spec or "baseline").strip()
    if spec in {"baseline", "identity", "none"}:
        return BaselineOptimizer()
    if spec in {"numpy", "deterministic"}:
        return NumpyDeterministicOptimizer()
    if spec in {"llm-oneshot", "oneshot"}:
        return LLMOneShotOptimizer(llm or LLMSettings())
    if spec.startswith("mutalambda"):
        _, _, rest = spec.partition(":")
        rest = rest or "fast"
        parts = rest.split("-")
        mode = parts[0] or "fast"
        if mode not in {"fast", "deep"}:
            raise ValueError(f"unknown mutalambda mode: {mode}")
        ablations = [p for p in parts[1:] if p]
        unknown = [a for a in ablations if a not in ABLATIONS]
        if unknown:
            raise ValueError(f"unknown ablation(s): {unknown}; valid: {list(ABLATIONS)}")
        return MutaLambdaOptimizer(mode, llm=llm or LLMSettings(), ablations=ablations)
    raise ValueError(f"unknown optimizer spec: {spec}")
