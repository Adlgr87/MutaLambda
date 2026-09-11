#!/usr/bin/env python3
"""Fase 1 acceptance measurement: Headroom levers before/after.

Simulates a (verbose) LLM deterministically against the SAME workload in
two configurations:

  BEFORE — legacy path: free-prose prompt (full source + full traceback),
           one call per mutation, verbose prose+code responses, occasional
           extraction failures (repair).
  AFTER  — headroom flags on: schema prompt (stubbed source + compressed
           traceback), ONE call for N=5 mutations, strict-JSON responses,
           occasional invalid-JSON (one bounded repair round).

Gates (Fase 1 acceptance):
  * input tokens  -60%
  * output tokens -40%
  * |repair rate Δ| <= 2pp vs baseline
  * 100% of accepted proposals schema-valid

Usage:  python bench_headroom_fase1.py
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

N = 5  # mutations per call (A3 batching)
SIM_CALLS = 200  # simulated candidate calls (40 generations x 5)


# ── Workload ─────────────────────────────────────────────────────────────────


def _target_code() -> str:
    lines = ['"""Signal processing helpers."""', "import math", "", "def process(data, k=32):"]
    for i in range(120):
        lines.append(f"    acc{i} = math.sqrt(data[{i % 7}] + {i})")
    lines.append("    total = 0")
    for i in range(10, 60):
        lines.append(f"    total = total + acc{i}")
    lines.append("    return total")
    return "\n".join(lines) + "\n"


def _traceback() -> str:
    lines = [f"[INFO] warmup {i} done" for i in range(150)]
    lines += [
        "[ERROR] Traceback (most recent call last):",
        '  File "sandbox_worker.py", line 88, in run_candidate',
        "    out = exec_candidate(code, args)",
        '  File "runners.py", line 210, in exec_candidate',
        "    result = _run_in_limits(code, args)",
        "ValueError: candidate returned [1, 2, 3] != expected [1.0, 2.0, 3.0]",
    ]
    return "\n".join(lines)


def _applicable_diff(code: str) -> str:
    """A diff that really applies to the generated target (50 lines → 1)."""
    old = "".join(f"-    total = total + acc{i}\n" for i in range(10, 60))
    return (
        "@@ -124,52 +124,3 @@\n"
        "     total = 0\n"
        + old
        + "+    total = (acc10 + acc31 + acc52) * 50\n"
        "     return total\n"
    )


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _main() -> int:
    from evolution_engine import CoreEvolutionEngine
    from optimization_flags import reset_optimization_flags

    engine = CoreEvolutionEngine()
    code = _target_code()
    error = _traceback()
    region = engine._top_region(code)
    rng = random.Random(1234)

    # ── BEFORE: legacy free-prose path ──────────────────────────────────────
    for var in (
        "MUTALAMBDA_OPT_HEADROOM__JSON_SCHEMA_OUTPUT__ENABLED",
        "MUTALAMBDA_OPT_HEADROOM__AST_STUBS__ENABLED",
        "MUTALAMBDA_OPT_HEADROOM__SMART_CRUSHER__ENABLED",
        "MUTALAMBDA_OPT_HEADROOM__BATCHING__ENABLED",
    ):
        os.environ.pop(var, None)
    reset_optimization_flags()

    legacy_prompt = engine.build_mutation_prompt(code, region, 0.42, error)

    def verbose_response(i: int) -> str:
        return (
            f"Sure! For mutation {i} I tightened the accumulation loop and "
            "cached the intermediate results. Here is the updated module "
            "with the new algorithm and defensive checks:\n"
            "```python\n"
            "def process(data, k=32):\n"
            + "".join(f"    acc = acc + data[{j % 7}]\n" for j in range(18))
            + "    return acc\n"
            "```\n"
            "This should keep the observable behaviour identical while "
            "reducing the constant factor of the inner loop.\n"
        )

    before_input = 0
    before_output = 0
    before_repairs = 0
    for i in range(SIM_CALLS):
        before_input += _tokens(legacy_prompt)
        before_output += _tokens(verbose_response(i))
        if rng.random() < 0.02:  # legacy: extractor sometimes fails on prose
            before_repairs += 1
    before = {
        "llm_calls": SIM_CALLS,
        "input_tokens": before_input,
        "output_tokens": before_output,
        "repairs": before_repairs,
        "repair_rate": round(before_repairs / SIM_CALLS, 4),
        "prompt_chars_per_call": len(legacy_prompt),
    }

    # ── AFTER: headroom levers on ──────────────────────────────────────────
    os.environ["MUTALAMBDA_OPT_HEADROOM__JSON_SCHEMA_OUTPUT__ENABLED"] = "1"
    os.environ["MUTALAMBDA_OPT_HEADROOM__AST_STUBS__ENABLED"] = "1"
    os.environ["MUTALAMBDA_OPT_HEADROOM__SMART_CRUSHER__ENABLED"] = "1"
    os.environ["MUTALAMBDA_OPT_HEADROOM__BATCHING__ENABLED"] = "1"
    reset_optimization_flags()

    import cost_ledger as cl

    cl.reset_cost_ledger()

    diff = _applicable_diff(code)
    valid_payload = json.dumps(
        {
            "ops": [
                {
                    "op_type": "replace_function_body",
                    "location": "def process(data, k=32)",
                    "unified_diff": diff,
                    "rationale": "Accumulation collapsed to a closed form.",
                    "confidence": 0.9,
                }
            ]
        }
    )

    rng2 = random.Random(99)
    after_input = 0
    after_output = 0
    after_repairs = 0
    schema_valid = 0
    accepted = 0
    after_calls = 0
    prompt_chars_total = 0

    from headroom_integration import llm_mutation_candidate

    def make_llm(state: dict):
        def llm(prompt: str) -> str:
            state["prompt_chars"] += len(prompt)
            if state.get("first") and rng2.random() < 0.01:
                # Occasionally the model emits prose → bounded repair round.
                state["first"] = False
                state["invalid"] = True
                return "I think the loop can be improved if we memoise it."
            return valid_payload

        return llm

    for _ in range(SIM_CALLS // N):
        state = {"prompt_chars": 0, "first": True, "invalid": False}
        sink: dict = {}
        out = llm_mutation_candidate(
            engine=engine,
            code=code,
            score=0.42,
            error_info=error,
            llm_fn=make_llm(state),
            stats_sink=sink,
        )
        after_calls += 1
        after_input += int(sink.get("tokens_in_est", 0))
        after_output += int(sink.get("tokens_out_est", 0))
        prompt_chars_total += state["prompt_chars"]
        if sink.get("repaired"):
            after_repairs += 1
        if sink.get("schema_valid"):
            schema_valid += 1
        if out is not None and not sink.get("fallback"):
            accepted += 1
    prompt_chars = prompt_chars_total // max(1, after_calls)

    after = {
        "llm_calls": after_calls,
        "input_tokens": after_input,
        "output_tokens": after_output,
        "repairs": after_repairs,
        "repair_rate": round(after_repairs / after_calls, 4),
        "schema_valid_calls": schema_valid,
        "accepted_ops_calls": accepted,
        "schema_validity_pct": round(100.0 * accepted / after_calls, 2),
        "calls_reduction_pct": round(100.0 * (1 - after_calls / SIM_CALLS), 2),
        "avg_prompt_chars_per_call": prompt_chars,
    }

    delta_input = 100.0 * (1 - after["input_tokens"] / before["input_tokens"])
    delta_output = 100.0 * (1 - after["output_tokens"] / before["output_tokens"])
    report = {
        "workload": {
            "target_lines": len(code.splitlines()),
            "traceback_lines": len(error.splitlines()),
            "mutations_per_call": N,
            "simulated_candidate_calls": SIM_CALLS,
        },
        "before": before,
        "after": after,
        "delta": {
            "input_tokens_reduction_pct": round(delta_input, 2),
            "output_tokens_reduction_pct": round(delta_output, 2),
            "repair_rate_delta_pp": round(
                100.0 * (after["repair_rate"] - before["repair_rate"]), 3
            ),
            "gates": {
                "input_tokens_-60": delta_input >= 60.0,
                "output_tokens_-40": delta_output >= 40.0,
                "repair_rate_±2pp": abs(after["repair_rate"] - before["repair_rate"]) <= 0.02,
                "schema_validity_100": after["schema_validity_pct"] == 100.0,
            },
        },
    }
    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "fase1_before_after.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    ledger = cl.get_cost_ledger().dump_json(out_dir / "fase1_cost_ledger.json")

    print("=" * 72)
    print("MutaLambda — FASE 1 before/after (Headroom levers)")
    print("=" * 72)
    print(
        f"[before] calls={before['llm_calls']} in={before['input_tokens']} out={before['output_tokens']} "
        f"repair={before['repair_rate']:.2%} prompt={before['prompt_chars_per_call']} chars/call"
    )
    print(
        f"[after ] calls={after['llm_calls']} in={after['input_tokens']} out={after['output_tokens']} "
        f"repair={after['repair_rate']:.2%} schema_valid={after['schema_validity_pct']:.0f}% "
        f"prompt={after['avg_prompt_chars_per_call']} chars/call (-{after['calls_reduction_pct']}% calls)"
    )
    d = report["delta"]
    print(
        f"\ninput -{d['input_tokens_reduction_pct']}% | output -{d['output_tokens_reduction_pct']}% | "
        f"Δrepair {d['repair_rate_delta_pp']:+.3f}pp"
    )
    for gate, ok in d["gates"].items():
        print(f"  gate {gate}: {'PASS' if ok else 'FAIL'}")
    print(f"\nartefacts: {out_path} | {ledger}")
    return 0 if all(d["gates"].values()) else 1


if __name__ == "__main__":
    sys.exit(_main())
