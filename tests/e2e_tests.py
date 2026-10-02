"""E2E tests reales (pipeline) para MutaLambda.

Foco del bloque C:
  - LLM stub determinista (no red)
  - Mutación/crossover/rediseño vía core (fallback AST incluido)
  - SandboxEvaluator con ejecución en subprocess
  - Migración entre islas
  - (Opcional) SolutionArchive con novelty_score

Uso:
  python e2e_tests.py

Recomendado para CI:
  python e2e_tests.py --fast
"""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List

# Prefer package install; fall back to repo root for uninstalled checkouts.
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    import muta_lambda as core
except ImportError:  # pragma: no cover
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    import muta_lambda as core


def _extract_first_function_name(code: str) -> str:
    import ast

    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            return node.name
    return "compute_sum"


@dataclass
class SampleTestSpec:
    # Un conjunto de casos para la función objetivo.
    # El sandbox recibe el test_cases como JSON para que el código generado lo ejecute.
    function_name: str
    inputs: List[List[Any]]
    expected: List[Any]


def build_test_cases_from_spec(spec: SampleTestSpec) -> List[Dict[str, Any]]:
    """Build sandbox test cases from a reusable sample specification."""
    if len(spec.inputs) != len(spec.expected):
        raise ValueError(
            f"SampleTestSpec inputs/expected length mismatch: "
            f"{len(spec.inputs)} != {len(spec.expected)}"
        )

    return [
        {
            "function": spec.function_name,
            "args": args,
            "expected": expected,
        }
        for args, expected in zip(spec.inputs, spec.expected)
    ]


def build_test_cases_sum() -> List[Dict[str, Any]]:
    """Genera test_cases para el sandbox.

    Convención para este repo (adaptada al evaluador existente):
    - El código generado se ejecuta como módulo
    - Este harness define la interfaz esperada en stdout en JSON

    Como el sandbox actual hace subprocess.run([python, tmp_path], input=json.dumps(test_cases)),
    los test_cases se pasan por stdin al script.

    Por lo tanto, el código generado debe leer stdin y ejecutar asserts y finalmente imprimir JSON
    con keys: passed/total.
    """
    return build_test_cases_from_spec(
        SampleTestSpec(
            function_name="compute_sum",
            inputs=[[0], [1], [5]],
            expected=[0, 0, 10],
        )
    )


def make_llm_stub(mode: str = "good") -> Any:
    """Stub determinista.

    mode:
      - "good": genera módulo con compute_sum correcto y harness de tests
      - "bad": genera módulo con compute_sum incorrecto
      - "syntax_error": devuelve texto no parseable (para validar fallback AST)
    """

    def llm_fn(prompt: str) -> str:
        if mode == "syntax_error":
            return "this is not python"

        # El stub devuelve un módulo completo y determinista, así que el
        # "Base Code:" del prompt se ignora deliberadamente.

        if mode == "bad":
            compute_body = "    return n"
        else:
            # sum(i for i in range(n))
            compute_body = "    return sum(range(n))"

        # IMPORTANTE: devolver SOLO la función.
        #
        # Este stub incluía antes su propio harness `_run()` que leía los
        # test_cases de stdin y los despachaba con `globals()[fn](*args)`.
        # Eso quedó obsoleto cuando el sandbox pasó a generar su propio
        # wrapper (`runners.build_wrapper_source`), y además el escáner de
        # seguridad (ML-002) rechaza `globals` como `sensitive_name`. El
        # resultado: TODO candidato era rechazado antes de ejecutar un solo
        # test, así que "good" y "bad" puntuaban idénticamente -1.0 y el
        # gate e2e no comprobaba nada. Mantener este módulo mínimo.
        return f"def compute_sum(n):\n{compute_body}\n"

    return llm_fn


def run_e2e(
    llm_mode: str,
    fast: bool,
    use_archive: bool,
    serial: bool,
) -> Dict[str, Any]:

    test_cases = build_test_cases_from_spec(
        SampleTestSpec(
            function_name="compute_sum",
            inputs=[[0], [1], [5]],
            expected=[0, 0, 10],
        )
    )

    # Semilla mínima: igual que el stub, solo la función. El harness lo
    # aporta el sandbox; incluir uno propio con globals() hacía que el
    # escáner de seguridad rechazara la semilla.
    seed_code = "def compute_sum(n):\n    return 0\n"

    cfg = core.EvolveConfig(
        num_islands=2,
        generations=3 if fast else 5,
        seed_codes=[seed_code],
        topology="ring",
        population_size=4,
        top_k=2,
        migration_interval=1,
        migrants_per_island=1,
        archive_solutions=use_archive,
        prompt_evolution=False,
        checkpoint_interval=0,
        novelty_alpha=0.2,
        early_stop_patience=10,
        early_stop_delta=0.0,
    )

    agent = core.MutaLambdaAgent(
        config=cfg,
        test_cases=test_cases,
        llm_fn=make_llm_stub(llm_mode),
        timeout_sec=3.0,
    )

    start = time.perf_counter()
    best = agent.run(task="")
    elapsed = time.perf_counter() - start

    metrics = agent.get_metrics()

    # Generar evaluation hooks para el contrato.
    archive_metrics: Dict[str, Any] = {
        "archive_size": metrics.get("archive_size", 0),
    }

    return {
        "best_solution_code": best.code,
        "evaluation_elapsed_sec": elapsed,
        "archive_metrics": archive_metrics,
        "agent_metrics": metrics,
        "llm_mode": llm_mode,
    }



# ── Diagnóstico ───────────────────────────────────────────────────────────

# Umbrales del gate. "good" debe resolver realmente el problema y "bad" debe
# fallarlo de forma inequívoca; un margen estrecho significaría que el gate
# no distingue una evolución sana de una rota.
GOOD_MIN_SCORE = 0.5
BAD_MAX_SCORE = 0.0
# Suelo de corrección: FitnessVector.to_scalar() devuelve correctness-1.0
# para cualquier candidato imperfecto, así que -1.0 exacto = correctness 0,
# es decir "no pasó ni un solo test" — típicamente porque nunca llegó a
# ejecutarse (rechazo del escáner de seguridad, error de carga, timeout).
UNEVALUATED_SCORE = -1.0


def diagnose_candidate(code: str, test_cases: List[Dict[str, Any]]) -> List[str]:
    """Explica *por qué* un candidato puntuó como puntuó.

    Un score de -1.0 puede significar "todos los tests fallaron" o "el código
    nunca se ejecutó", y esos dos casos se arreglan de formas opuestas. Esta
    función los separa: escáner de seguridad, error de carga, y después, caso
    a caso, qué devolvió frente a qué se esperaba y con qué comparador.
    """
    lines: List[str] = []

    # 1. ¿Lo rechazó el escáner antes de ejecutarlo?
    try:
        from runners import scan_code_security

        findings = scan_code_security(code)
        if findings:
            lines.append(
                f"RECHAZADO POR EL ESCÁNER DE SEGURIDAD: {', '.join(findings)}"
            )
            lines.append(
                "  -> el candidato NUNCA se ejecutó; el score no mide corrección."
            )
            return lines
    except Exception as exc:  # noqa: BLE001 - diagnóstico, nunca debe romper el gate
        lines.append(f"(no se pudo ejecutar el escáner de seguridad: {exc!r})")

    # 2. Ejecutar caso a caso y reportar got/expected/comparador/excepción.
    try:
        from comparison import compare_values
    except Exception:  # noqa: BLE001 - diagnóstico
        compare_values = None  # type: ignore[assignment]

    ns: Dict[str, Any] = {}
    try:
        exec(compile(code, "<candidate>", "exec"), ns)  # noqa: S102 - código propio del test
    except (KeyboardInterrupt, MemoryError):
        raise
    except BaseException as exc:  # noqa: BLE001 - ver nota
        # BaseException, no Exception: un candidato con `raise SystemExit(...)`
        # a nivel de módulo mataría el diagnóstico y con él toda la ejecución
        # e2e, ocultando justo lo que se intentaba explicar. KeyboardInterrupt
        # y MemoryError sí se propagan: son del operador o de la máquina.
        lines.append(f"EL MÓDULO NO CARGA: {type(exc).__name__}: {exc}")
        return lines

    for i, tc in enumerate(test_cases):
        fn_name = tc.get("function")
        args = tc.get("args", [])
        expected = tc.get("expected")
        comparator = tc.get("comparison", "equal")
        fn = ns.get(fn_name)
        if not callable(fn):
            lines.append(f"  caso {i}: función {fn_name!r} ausente o no invocable")
            continue
        try:
            got = fn(*args)
        except (KeyboardInterrupt, MemoryError):
            raise
        except BaseException as exc:  # noqa: BLE001 - la excepción ES el dato
            lines.append(
                f"  caso {i}: {fn_name}{tuple(args)} LANZÓ "
                f"{type(exc).__name__}: {exc}  (esperaba {expected!r})"
            )
            continue
        if compare_values is not None:
            try:
                ok = compare_values(got, expected, comparator)
            except ValueError as exc:
                lines.append(f"  caso {i}: COMPARADOR INDEFINIDO {comparator!r} ({exc})")
                continue
        else:
            ok = got == expected
        mark = "ok " if ok else "FAIL"
        lines.append(
            f"  caso {i}: {mark} {fn_name}{tuple(args)} -> {got!r} "
            f"(esperaba {expected!r}, comparador={comparator!r})"
        )
    return lines


def classify(good: float, bad: float) -> tuple[int, str]:
    """Devuelve (exit_code, veredicto).

    0 = good supera a bad con margen; 1 = fallo real; 2 = indeterminado.
    El 2 es deliberadamente distinto del 1: "el pipeline no midió nada" es un
    problema de instrumentación, no una regresión de calidad evolutiva, y
    confundirlos fue exactamente lo que dejó este gate verde durante meses.
    """
    if good == UNEVALUATED_SCORE or bad == UNEVALUATED_SCORE:
        return 2, (
            "INDETERMINADO: algún pipeline puntuó exactamente -1.0 (correctness=0). "
            "Eso normalmente significa que el candidato nunca llegó a ejecutarse, "
            "no que sea peor. El gate no puede concluir nada."
        )
    if good <= bad:
        return 1, f"FALLO: good ({good:.4f}) no supera a bad ({bad:.4f})."
    if good < GOOD_MIN_SCORE or bad > BAD_MAX_SCORE:
        return 1, (
            f"FALLO: margen insuficiente. Se exige good >= {GOOD_MIN_SCORE} y "
            f"bad <= {BAD_MAX_SCORE}; se obtuvo good={good:.4f}, bad={bad:.4f}."
        )
    return 0, f"OK: good ({good:.4f}) supera a bad ({bad:.4f}) con margen."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--serial", action="store_true", help="Forzar parallelism=1 en el sandbox")
    args = ap.parse_args()

    # 1) E2E bueno: debería converger a compute_sum correcto.
    out_good = run_e2e(llm_mode="good", fast=args.fast, use_archive=False, serial=args.serial)

    # 2) E2E malo: puede fallar pero el flujo no debe romperse.
    out_bad = run_e2e(llm_mode="bad", fast=args.fast, use_archive=False, serial=args.serial)

    # 3) E2E syntax_error: fuerza fallback AST (aunque con seed+AST mutator no garantizamos acierto,
    #    lo importante es que no se rompe el pipeline end-to-end).
    out_syntax = run_e2e(
        llm_mode="syntax_error", fast=args.fast, use_archive=False, serial=args.serial
    )

    print("\n[E2E RESULTS] SUMMARY")
    for k, out in [("good", out_good), ("bad", out_bad), ("syntax_error", out_syntax)]:
        print(
            f"- {k}: llm_mode={out['llm_mode']} best_score={out['agent_metrics']['best_score_history'][-1] if out['agent_metrics']['best_score_history'] else None} "
            f"gens={out['agent_metrics']['total_generations']} time={out['evaluation_elapsed_sec']:.2f}s"
        )

    # Asserts simples: el flujo debe producir best_solution_code parseable.
    import ast

    for out in (out_good, out_bad, out_syntax):
        ast.parse(out["best_solution_code"])

    final_good = out_good["agent_metrics"]["best_score_history"][-1]
    final_bad = out_bad["agent_metrics"]["best_score_history"][-1]

    exit_code, verdict = classify(final_good, final_bad)

    # Diagnóstico activo: cuando el gate no puede concluir, decir POR QUÉ en
    # el momento, en vez de dejar un -1.0 mudo que hay que investigar a mano.
    if exit_code != 0:
        test_cases = build_test_cases_sum()
        print("\n[E2E DIAGNÓSTICO]")
        for label, out, score in (
            ("good", out_good, final_good),
            ("bad", out_bad, final_bad),
        ):
            print(f"\n  --- {label} (score={score:.4f}) ---")
            for line in diagnose_candidate(out["best_solution_code"], test_cases):
                print(f"  {line}")
            print("  código del mejor candidato:")
            for cl in out["best_solution_code"].splitlines()[:15]:
                print(f"    | {cl}")

    print(f"\n  [E2E] good={final_good:.4f}  bad={final_bad:.4f}")
    print(f"  [E2E] {verdict}")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
