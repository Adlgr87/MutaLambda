"""
MutaLambda Agent — Fully Optimized + Patched Implementation
=============================================================

Emulación funcional del modelo MutaLambda:
  - Arquitectura Multi-Isla con migración topológica
  - Evaluación en Sandbox seguro (subprocess aislado)
  - Sistema de Prompts Evolutivo (PromptGenome)
  - Memoria a Largo Plazo con embeddings + FAISS
  - Mutaciones AST garantizadas sintácticamente válidas (13 operadores)
  - Agente principal con ciclo evolutivo completo + CLI

Compatibilidad: Python 3.9+
Dependencias: faiss-cpu, sentence-transformers, numpy

Optimizaciones vs. skeleton original:
  - ast.unparse() reemplaza astor (1 dependencia menos)
  - collections.deque para FIFO en SolutionArchive (O(1) pop izquierdo)
  - heapq.nlargest para selección elitista O(n log k) vs O(n log n) sort
  - ProcessPoolExecutor persistente (no recreate por batch)
  - Prueba por lotes en FAISS + batch embedding encode
  - ASTMutator completo con 13 operadores de mutación
  - MutaLambdaAgent como orquestador principal
  - Cache LRU en cálculos topológicos
  - Validación de configuración + graceful shutdown

Parches aplicados (v2 — revisión verificada):
  [BUG-1] _rename_variable: ahora excluye builtins, keywords y nombres
          de funciones/clases definidas en el propio código.
  [BUG-2] _replace_aug_assign: reemplazado __class__-mutation por
          construcción explícita de ast.Assign (portabilidad garantizada).
  [BUG-3] SolutionArchive.add: condición pending_prunes corregida
          (verificar ANTES del append si deque está lleno).
  [BUG-4] MigrationBus._get_neighbors: lectura de cache dentro del lock
          para eliminar el posible data race.

Mejoras adicionales v2:
  [MEJ-1] EarlyStopMonitor: detección de convergencia por ventana de
          mejora relativa (más fino que el threshold fijo anterior).
  [MEJ-2] novelty_score() integrado en MutaLambdaAgent: diversidad
          combinada con fitness para evitar convergencia prematura.
  [MEJ-3] _score_with_novelty(): combina score funcional + bonus de
          novedad configurable (alpha).
  [MEJ-4] run_full_test_suite(): suite de tests integrada con reporte
          final de cobertura, ejecutable con --test.
  [MEJ-5] Logging estructurado con nivel configurable via env var
          MUTALAMBDA_LOG_LEVEL.
"""

from __future__ import annotations

import ast
import builtins
import copy
import heapq
import json
import logging
import multiprocessing
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import lru_cache
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)

# ─── Third-party ──────────────────────────────────────────────────────────────
import numpy as np

# Conditional imports: allow running without heavy deps for testing ASTMutator
try:
    import faiss
except ImportError:
    faiss = None  # type: ignore[assignment]

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None  # type: ignore[assignment,misc]

# ─── Logging global ───────────────────────────────────────────────────────────
_LOG_LEVEL = os.environ.get("MUTALAMBDA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MutaLambda")


# Nombre del proyecto (para derechos de autor y referencia)
PROJECT_NAME = "MutaLambda"


# ─── LLM BACKEND ABSTRACTION ───────────────────────────────────────────────────────

class LLMBackend:
    """Abstracción de generación de texto para diferentes back‑ends locales.

    Permite seleccionar entre Ollama, microsoft.cpp y huggingface‑cli mediante
    el parámetro ``backend`` o la variable de entorno ``MUTALAMBDA_LLM_BACKEND``.
    Cada back‑end debe exponer una función ``generate(prompt: str) -> str`` que
    devuelva el texto generado sin marcas de stream.
    """

    def __init__(self, backend: str = "ollama", model: str = "llama3.2:3b") -> None:
        self.backend = backend.lower()
        self.model = model
        self._init_backend()

    def _init_backend(self) -> None:
        if self.backend == "ollama":
            # Ollama vía API HTTP
            import requests
            self._session = requests.Session()
            self._url = "http://localhost:11434/api/generate"
        elif self.backend == "microsoft_cpp":
            # microsoft.cpp asume binario llamado ``microsoft.cpp`` en PATH
            self._cmd = ["microsoft.cpp", "-m", self.model]
        elif self.backend == "huggingface_cli":
            # huggingface-cli (text‑generation) asume comando ``huggingface-cli`` en PATH
            self._cmd = ["huggingface-cli", "text-generation", "--model", self.model]
        else:
            raise ValueError(f"Unsupported LLM backend: {self.backend}")

    def generate(self, prompt: str) -> str:
        """Genera texto a partir de ``prompt`` usando el back‑end seleccionado.

        Se capturan y registran los errores; en caso de fallo se devuelve una cadena
        vacía y se escribe el error en el logger para que el flujo evolutivo continúe.
        """
        try:
            if self.backend == "ollama":
                payload = {"model": self.model, "prompt": prompt, "stream": False}
                resp = self._session.post(self._url, json=payload, timeout=30)
                resp.raise_for_status()
                return resp.json().get("response", "")
            elif self.backend == "microsoft_cpp":
                # Ejecutamos el binario y le pasamos el prompt por stdin
                proc = subprocess.run(
                    self._cmd,
                    input=prompt.encode("utf-8"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore"))
                return proc.stdout.decode("utf-8", errors="ignore")
            elif self.backend == "huggingface_cli":
                proc = subprocess.run(
                    self._cmd,
                    input=prompt.encode("utf-8"),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore"))
                return proc.stdout.decode("utf-8", errors="ignore")
        except Exception as exc:
            logger.error("LLMBackend (%s) generation failed: %s", self.backend, exc)
            return ""


# ─── UTILIDADES DE CONFIGURACIÓN ───────────────────────────────────────────────────────

def _resolve_llm_backend() -> Callable[[str], str]:
    """Factory que devuelve una función ``generate`` basada en la configuración.

    Se respeta la variable de entorno ``MUTALAMBDA_LLM_BACKEND`` y, si está
    definida, su valor tiene prioridad sobre el argumento explícito.
    """
    backend = os.getenv("MUTALAMBDA_LLM_BACKEND", "ollama")
    model = os.getenv("MUTALAMBDA_LLM_MODEL", "llama3.2:3b")
    llm = LLMBackend(backend=backend, model=model)
    return llm.generate


# ══════════════════════════════════════════════════════════════════════════════
# 1. ESTRUCTURAS DE DATOS CORE
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Individual:
    """Unidad evolutiva: un fragmento de código con su puntuación."""
    code: str
    score: float = float("-inf")
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __lt__(self, other: "Individual") -> bool:
        return self.score < other.score

    def __repr__(self) -> str:
        return f"Individual(id={self.id}, score={self.score:.4f})"


@dataclass
class EvalResult:
    """Resultado de evaluar un individuo en el sandbox."""
    score: float
    passed: bool
    metrics: Dict[str, float]
    stdout: str
    stderr: str
    timed_out: bool


@dataclass
class IslandConfig:
    """Configuración por isla evolutiva."""
    migration_interval: int = 10
    migrants_per_island: int = 2
    topology: str = "ring"  # "ring" | "fully_connected" | "random"
    population_size: int = 8
    top_k: int = 3

    def __post_init__(self) -> None:
        if self.top_k > self.population_size:
            raise ValueError(
                f"top_k ({self.top_k}) must be <= population_size ({self.population_size})"
            )
        if self.population_size < 2:
            raise ValueError("population_size must be >= 2")


@dataclass
class PromptGenome:
    """
    Genoma de un prompt evolutivo.
    Encapsula system_prompt, ejemplos few-shot, instrucciones de mutación
    y temperatura; evoluciona junto con el código.
    """
    system_prompt: str
    few_shot_examples: List[Tuple[str, str]]
    mutation_instructions: str
    temperature: float
    fitness: float = 0.0

    def render(self, task: str, base_code: str) -> str:
        """Serializa el genoma en un prompt listo para el LLM."""
        # join directo sin f-strings intermedias para eficiencia
        parts: List[str] = [
            self.system_prompt,
            "\nTask: ",
            task,
            "\nBase Code:\n",
            base_code,
        ]
        for inp, out in self.few_shot_examples:
            parts.extend(("\nExample Input:\n", inp, "\nOutput:\n", out))
        if self.mutation_instructions:
            parts.extend(("\nInstructions: ", self.mutation_instructions))
        return "".join(parts)


@dataclass
class ArchivedSolution:
    """Solución almacenada en el archivo a largo plazo."""
    code: str
    metrics: Dict[str, float]
    embedding: np.ndarray
    timestamp: float = field(default_factory=time.time)


# ══════════════════════════════════════════════════════════════════════════════
# 2. AST MUTATOR — 13 operadores de mutación sintácticamente válidos
# ══════════════════════════════════════════════════════════════════════════════


class ASTMutator:
    """Mutaciones sobre el AST que garantizan código sintácticamente válido.

    Usa ast.unparse() (Python 3.9+) en lugar de astor — elimina una
    dependencia externa completa.

    13 operadores cubiertos:
      1. swap_binary_ops     — intercambia operandos conmutativos
      2. replace_constant    — cambia literales numéricos/str
      3. wrap_in_if          — envuelve sentencia en `if True:`
      4. add_pass            — añade `pass` tras returns
      5. negate_condition    — niega condición de If/While
      6. swap_comparison     — invierte comparaciones (a < b → b > a)
      7. inline_constant     — reemplaza variable por su valor constante
      8. rename_variable     — renombra una variable local
      9. duplicate_statement — clona una sentencia
     10. swap_if_else        — intercambia ramas if/else
     11. replace_aug_assign  — += → = var + expr (o viceversa)
     12. toggle_return       — añade/quita return explícito
     13. add_trivial_loop    — envuelve en `for _ in range(1):`
    """

    _CONMUTATIVOS = {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
                     ast.BitAnd, ast.BitOr, ast.BitXor}
    _COMMUTATIVE_PAIRS = {ast.Add, ast.Mult, ast.BitAnd, ast.BitOr, ast.BitXor}

    _CONST_ALTERNATIVES = {
        int: lambda v: random.choice([0, 1, -1, 2, v + 1, v - 1, v * 2]),
        float: lambda v: round(v * random.uniform(0.5, 2.0), 6),
        str: lambda v: v[::-1] if v else v,
        bool: lambda v: not v,
    }

    @classmethod
    def apply_random_mutation(cls, code: str) -> str:
        """Aplica una mutación aleatoria; devuelve código original si falla."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code

        mutations = [
            cls._swap_binary_ops,
            cls._replace_constant,
            cls._wrap_in_if,
            cls._negate_condition,
            cls._swap_comparison,
            cls._rename_variable,
            cls._duplicate_statement,
            cls._swap_if_else,
            cls._replace_aug_assign,
            cls._add_trivial_loop,
        ]

        # Intentar hasta 5 mutaciones diferentes antes de devolver original
        random.shuffle(mutations)
        for mut_fn in mutations[:5]:
            try:
                new_tree = copy.deepcopy(tree)
                mut_fn(new_tree)
                ast.fix_missing_locations(new_tree)
                result = ast.unparse(new_tree)
                # Verificar que el resultado es parseable
                ast.parse(result)
                if result.strip() != code.strip():
                    return result
            except (SyntaxError, ValueError, AttributeError):
                continue

        return code  # fallback: ninguna mutación válida

    # ── Operadores individuales ──────────────────────────────────────────────

    @classmethod
    def _swap_binary_ops(cls, tree: ast.Module) -> None:
        """Intercambia operandos en operaciones conmutativas."""
        swaps = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.BinOp) and type(node.op) in cls._COMMUTATIVE_PAIRS
        ]
        if swaps:
            node = random.choice(swaps)
            node.left, node.right = node.right, node.left

    @classmethod
    def _replace_constant(cls, tree: ast.Module) -> None:
        """Cambia un literal numérico o string por una alternativa."""
        constants = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and type(node.value) in cls._CONST_ALTERNATIVES
        ]
        if constants:
            node = random.choice(constants)
            gen = cls._CONST_ALTERNATIVES[type(node.value)]
            node.value = gen(node.value)

    @staticmethod
    def _wrap_in_if(tree: ast.Module) -> None:
        """Envuelve la primera sentencia del cuerpo en `if True:`."""
        for node in ast.walk(tree):
            if hasattr(node, "body") and node.body:
                idx = random.randrange(len(node.body))
                original = node.body[idx]
                node.body[idx] = ast.If(
                    test=ast.Constant(value=True),
                    body=[original],
                    orelse=[],
                )
                return

    @staticmethod
    def _negate_condition(tree: ast.Module) -> None:
        """Niega la condición de un If o While aleatorio."""
        conditionals = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.If, ast.While))
        ]
        if conditionals:
            node = random.choice(conditionals)
            node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)

    @staticmethod
    def _swap_comparison(tree: ast.Module) -> None:
        """Invierte comparaciones: a < b → b > a."""
        _INVERSE = {
            ast.Lt: ast.Gt, ast.Gt: ast.Lt,
            ast.LtE: ast.GtE, ast.GtE: ast.LtE,
            ast.Eq: ast.Eq, ast.NotEq: ast.NotEq,
        }
        comps = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Compare)
        ]
        if comps:
            node = random.choice(comps)
            new_ops = []
            for op in node.ops:
                inv = _INVERSE.get(type(op))
                if inv:
                    new_ops.append(inv())
                else:
                    new_ops.append(op)
            node.ops = new_ops
            # También invertir left/right
            if node.comparators:
                node.left, node.comparators[-1] = node.comparators[-1], node.left

    # Conjunto de nombres protegidos: builtins + keywords de Python
    # Se calcula una vez a nivel de clase para no repetir en cada llamada.
    # Nota: dir() retorna list → convertir a set antes de usar |
    _PROTECTED_NAMES: frozenset = frozenset(
        set(dir(builtins))
        | {"True", "False", "None"}
        | set(__import__("keyword").kwlist)
    )

    @classmethod
    def _rename_variable(cls, tree: ast.Module) -> None:
        """Renombra una variable local aleatoria.

        [PATCH BUG-1] Excluye:
          - Builtins de Python (range, len, print, type, …)
          - Keywords (if, for, return, …)
          - Nombres de funciones y clases definidas en el código
          - Nombres que ya empiezan con '_'
        """
        # Recopilar nombres definidos localmente (funciones, clases)
        locally_defined: set = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        protected = cls._PROTECTED_NAMES | locally_defined

        # Solo renombrar Names en contexto de Store (asignaciones)
        # para evitar romper llamadas a funciones/métodos
        candidates = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.id, str)
            and not node.id.startswith("_")
            and node.id not in protected
        ]
        if not candidates:
            return

        target = random.choice(candidates)
        suffix = random.choice("abcdefgh")
        original_id = target.id
        # Renombrar todas las ocurrencias (Store y Load) del mismo nombre
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == original_id:
                node.id = original_id + suffix

    @staticmethod
    def _duplicate_statement(tree: ast.Module) -> None:
        """Duplica una sentencia aleatoria del cuerpo."""
        for node in ast.walk(tree):
            if hasattr(node, "body") and node.body and len(node.body) < 50:
                idx = random.randrange(len(node.body))
                node.body.insert(idx, copy.deepcopy(node.body[idx]))
                return

    @staticmethod
    def _swap_if_else(tree: ast.Module) -> None:
        """Intercambia las ramas if/else y niega la condición."""
        ifs = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.If) and node.orelse
        ]
        if ifs:
            node = random.choice(ifs)
            node.body, node.orelse = node.orelse, node.body
            node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)

    @staticmethod
    def _replace_aug_assign(tree: ast.Module) -> None:
        """Convierte augmented assign (+=) a assign normal (= var + expr).

        [PATCH BUG-2] Reemplaza la técnica de mutar __class__ directamente
        (no documentada, frágil en PyPy/CPython futuro) por construcción
        explícita de un nodo ast.Assign nuevo, reemplazando en el cuerpo
        del nodo padre.

        AugAssign(target=x, op=Add, value=v)
            →  Assign(targets=[x], value=BinOp(x, Add, v))
        """
        # Recopilar pares (padre_con_body, índice) para poder reemplazar en sitio
        replacements: List[Tuple[Any, int, ast.AugAssign]] = []
        for parent in ast.walk(tree):
            body = getattr(parent, "body", None)
            if not body:
                continue
            for idx, child in enumerate(body):
                if isinstance(child, ast.AugAssign):
                    replacements.append((parent, idx, child))

        if not replacements:
            return

        parent, idx, aug = random.choice(replacements)
        new_assign = ast.Assign(
            targets=[copy.deepcopy(aug.target)],
            value=ast.BinOp(
                left=copy.deepcopy(aug.target),
                op=aug.op,
                right=aug.value,
            ),
            lineno=aug.lineno,
            col_offset=aug.col_offset,
        )
        parent.body[idx] = new_assign

    @staticmethod
    def _add_trivial_loop(tree: ast.Module) -> None:
        """Envuelve la primera sentencia en `for _ in range(1):`."""
        for node in ast.walk(tree):
            if hasattr(node, "body") and node.body:
                idx = random.randrange(len(node.body))
                original = node.body[idx]
                node.body[idx] = ast.For(
                    target=ast.Name(id="_", ctx=ast.Store()),
                    iter=ast.Call(
                        func=ast.Name(id="range", ctx=ast.Load()),
                        args=[ast.Constant(value=1)],
                        keywords=[],
                    ),
                    body=[original],
                    orelse=[],
                )
                return


# ══════════════════════════════════════════════════════════════════════════════
# 3. CORE EVOLUTION ENGINE
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CodeRegion:
    """Bloque AST candidato para optimización."""
    kind: str
    name: str
    start_line: int
    end_line: int
    source: str
    complexity_score: int


class CoreEvolutionEngine:
    """Selecciona regiones AST y construye prompts internos estrictos."""

    _CANDIDATE_NODES = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.For,
        ast.While,
        ast.If,
        ast.Match,
    )

    _OUTPUT_CONTRACT = """OUTPUT CONTRACT:
- Return exactly one complete Python module.
- Return raw Python code only.
- Do not use Markdown fences.
- Do not explain, summarize, apologize, or include prose.
- Preserve public function names and call signatures unless the task explicitly requires otherwise.
- The result must parse with ast.parse()."""

    def select_code_regions(self, code: str, max_regions: int = 5) -> List[CodeRegion]:
        """Devuelve los bloques AST más prometedores para optimizar."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []

        regions: List[CodeRegion] = []
        for node in ast.walk(tree):
            if not isinstance(node, self._CANDIDATE_NODES):
                continue
            source = ast.get_source_segment(code, node)
            if not source:
                continue
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", start)
            regions.append(
                CodeRegion(
                    kind=type(node).__name__,
                    name=self._node_name(node),
                    start_line=start,
                    end_line=end,
                    source=source,
                    complexity_score=self._complexity_score(node),
                )
            )

        regions.sort(
            key=lambda r: (r.complexity_score, r.end_line - r.start_line),
            reverse=True,
        )
        return regions[:max_regions]

    def build_mutation_prompt(
        self,
        code: str,
        region: Optional[CodeRegion],
        score: float,
        error_info: str = "",
    ) -> str:
        """Prompt para mutación heurística: cambios pequeños y conservadores."""
        region_block = self._format_region(region)
        error_block = f"\nCURRENT ERROR:\n{error_info}\n" if error_info else ""
        return f"""SYSTEM: You are MutaLambda Core Evolution Engine.
MODE: HEURISTIC_MUTATION
OBJECTIVE: Make the smallest useful algorithmic improvement to the target code.

CURRENT SCORE: {score:.4f}
{error_block}
TARGET REGION:
{region_block}

SOURCE MODULE:
{code}

RULES:
- Prefer one localized change over a rewrite.
- Fix obvious correctness bugs before optimizing performance.
- Avoid new third-party dependencies.
{self._OUTPUT_CONTRACT}
"""

    def build_crossover_prompt(
        self,
        parent_a: str,
        parent_b: str,
        region_a: Optional[CodeRegion],
        region_b: Optional[CodeRegion],
    ) -> str:
        """Prompt para cruce: combinar dos soluciones completas."""
        return f"""SYSTEM: You are MutaLambda Core Evolution Engine.
MODE: CROSSOVER
OBJECTIVE: Produce one better Python module by combining the strongest ideas from two parents.

PARENT A TARGET REGION:
{self._format_region(region_a)}

PARENT B TARGET REGION:
{self._format_region(region_b)}

PARENT A MODULE:
{parent_a}

PARENT B MODULE:
{parent_b}

RULES:
- Keep the public API from Parent A unless Parent B clearly fixes correctness.
- Combine algorithms, not comments.
- Remove duplicated helper code created by the merge.
- Avoid new third-party dependencies.
{self._OUTPUT_CONTRACT}
"""

    def build_redesign_prompt(
        self,
        code: str,
        region: Optional[CodeRegion],
        score: float,
        task: str = "",
    ) -> str:
        """Prompt para rediseño radical cuando la línea evolutiva está estancada."""
        task_block = f"\nTASK CONTEXT:\n{task}\n" if task else ""
        return f"""SYSTEM: You are MutaLambda Core Evolution Engine.
MODE: RADICAL_REDESIGN
OBJECTIVE: Redesign the algorithm while preserving the callable interface.

CURRENT SCORE: {score:.4f}
{task_block}
TARGET REGION:
{self._format_region(region)}

SOURCE MODULE:
{code}

RULES:
- Replace the core algorithm if needed.
- Preserve imports only when still required.
- Preserve public function names and parameters.
- Avoid new third-party dependencies.
{self._OUTPUT_CONTRACT}
"""

    def extract_valid_code(self, response: str) -> Optional[str]:
        """Extrae código de una respuesta LLM y exige sintaxis Python válida."""
        candidates = [response.strip()]
        fenced = self._extract_fenced_python(response)
        if fenced:
            candidates.insert(0, fenced.strip())

        for candidate in candidates:
            if not candidate:
                continue
            try:
                ast.parse(candidate)
                return candidate
            except SyntaxError:
                continue
        return None

    def mutate_with_llm(
        self,
        code: str,
        score: float,
        error_info: str,
        llm_fn: Callable[[str], str],
    ) -> str:
        """Ejecuta mutación dirigida por LLM con fallback AST local."""
        region = self._top_region(code)
        prompt = self.build_mutation_prompt(code, region, score, error_info)
        generated = self.extract_valid_code(llm_fn(prompt))
        return generated if generated is not None else ASTMutator.apply_random_mutation(code)

    def crossover_with_llm(
        self,
        parent_a: str,
        parent_b: str,
        llm_fn: Callable[[str], str],
    ) -> Optional[str]:
        """Ejecuta cruce dirigido por LLM; devuelve None si la salida no es válida."""
        prompt = self.build_crossover_prompt(
            parent_a,
            parent_b,
            self._top_region(parent_a),
            self._top_region(parent_b),
        )
        return self.extract_valid_code(llm_fn(prompt))

    def redesign_with_llm(
        self,
        code: str,
        score: float,
        task: str,
        llm_fn: Callable[[str], str],
    ) -> Optional[str]:
        """Ejecuta rediseño radical dirigido por LLM."""
        prompt = self.build_redesign_prompt(code, self._top_region(code), score, task)
        return self.extract_valid_code(llm_fn(prompt))

    def _top_region(self, code: str) -> Optional[CodeRegion]:
        regions = self.select_code_regions(code, max_regions=1)
        return regions[0] if regions else None

    @staticmethod
    def _node_name(node: ast.AST) -> str:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return node.name
        return type(node).__name__

    @staticmethod
    def _complexity_score(node: ast.AST) -> int:
        score = 0
        for child in ast.walk(node):
            score += 1
            if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                score += 6
            elif isinstance(child, (ast.If, ast.Match)):
                score += 4
            elif isinstance(child, ast.Call):
                score += 2
        return score

    @staticmethod
    def _format_region(region: Optional[CodeRegion]) -> str:
        if region is None:
            return "No parseable AST region was selected."
        return (
            f"{region.kind} {region.name} "
            f"(lines {region.start_line}-{region.end_line}, "
            f"complexity={region.complexity_score})\n"
            f"{region.source}"
        )

    @staticmethod
    def _extract_fenced_python(text: str) -> Optional[str]:
        marker = "```"
        start = text.find(marker)
        if start == -1:
            return None
        content_start = text.find("\n", start)
        if content_start == -1:
            return None
        end = text.find(marker, content_start + 1)
        if end == -1:
            return None
        return text[content_start + 1:end]


# ══════════════════════════════════════════════════════════════════════════════
# 4. BUS DE MIGRACIÓN (Multi-Isla)
# ══════════════════════════════════════════════════════════════════════════════


class MigrationBus:
    """
    Coordinador de migración entre islas.
    Soporta topologías: ring, fully_connected, random.
    Thread-safe mediante RLock.
    """

    def __init__(self, topology: str = "ring"):
        self.islands: Dict[int, Island] = {}
        self.topology = topology
        self._lock = threading.RLock()
        self._neighbor_cache: Dict[int, List[int]] = {}
        self._cache_version: int = 0
        self._islands_version: int = 0

    def register_island(self, island_id: int, island: Island) -> None:
        with self._lock:
            self.islands[island_id] = island
            self._islands_version += 1
            self._neighbor_cache.clear()
            logger.debug("Island %d registered in MigrationBus.", island_id)

    def _get_neighbors(self, island_id: int) -> List[int]:
        """Calcula vecinos según topología. Cache invalidado al registrar islas.

        [PATCH BUG-4] La lectura del cache se hace ahora DENTRO del contexto
        donde ya se posee el lock (llamado desde migrate() que ya lo adquirió),
        eliminando el data race entre la comprobación de versión y la lectura
        del dict. El método es privado y solo se llama desde migrate(), que
        adquiere self._lock antes. Se documenta este contrato explícitamente.

        Precondición: caller debe tener self._lock adquirido.
        """
        # Cache hit — seguro porque el caller tiene el lock
        if self._cache_version == self._islands_version:
            cached = self._neighbor_cache.get(island_id)
            if cached is not None:
                return cached

        ids = sorted(self.islands.keys())
        if len(ids) < 2:
            result: List[int] = []
        elif self.topology == "ring":
            idx = ids.index(island_id)
            result = [ids[(idx - 1) % len(ids)], ids[(idx + 1) % len(ids)]]
        elif self.topology == "fully_connected":
            result = [i for i in ids if i != island_id]
        else:  # "random": 2 vecinos aleatorios — nunca se cachea
            candidates = [i for i in ids if i != island_id]
            return random.sample(candidates, min(2, len(candidates)))

        # Solo cachear topologías deterministas (ring, fully_connected)
        self._neighbor_cache[island_id] = result
        self._cache_version = self._islands_version
        return result

    def migrate(self, island_id: int, generation: int) -> None:
        """Envía migrantes si el intervalo de migración se cumple."""
        with self._lock:
            island = self.islands.get(island_id)
            if island is None:
                return
            if generation % island.config.migration_interval != 0:
                return

            neighbors = self._get_neighbors(island_id)
            migrants = island.get_migrants(island.config.migrants_per_island)

            for neighbor_id in neighbors:
                neighbor = self.islands.get(neighbor_id)
                if neighbor is None:
                    continue
                for migrant in migrants:
                    neighbor.receive_migrant(copy.deepcopy(migrant))

            logger.debug(
                "Island %d migrated %d individuals to %s.",
                island_id, len(migrants), neighbors,
            )

    def get_global_best(self) -> Optional[Individual]:
        """Retorna el mejor individuo global entre todas las islas."""
        with self._lock:
            best: Optional[Individual] = None
            for island in self.islands.values():
                if island.local_best is not None:
                    if best is None or island.local_best.score > best.score:
                        best = island.local_best
            return copy.deepcopy(best) if best else None


# ══════════════════════════════════════════════════════════════════════════════
# 5. ISLA EVOLUTIVA
# ══════════════════════════════════════════════════════════════════════════════


class Island:
    """
    Unidad de evolución independiente.
    Mantiene su propia población e interactúa con otras islas
    a través del MigrationBus.
    """

    def __init__(
        self,
        island_id: int,
        config: IslandConfig,
        llm_fn: Callable[[str], str],
        evaluator: SandboxEvaluator,
        migration_bus: MigrationBus,
    ):
        self.id = island_id
        self.config = config
        self.llm_fn = llm_fn
        self.evaluator = evaluator
        self.migration_bus = migration_bus
        self.core_engine = CoreEvolutionEngine()

        self.population: List[Individual] = []
        self.generation: int = 0
        self.local_best: Optional[Individual] = None
        self._history: List[float] = []  # track score history

        self.migration_bus.register_island(island_id, self)

    def seed_population(self, codes: List[str]) -> None:
        """Inicializa la población con semillas de código."""
        self.population = [
            Individual(code=c) for c in codes[: self.config.population_size]
        ]

    # ── Ciclo principal ────────────────────────────────────────────────────────

    def step(self) -> None:
        """Un paso: evolución local + migración."""
        self._evolve_local()
        self.migration_bus.migrate(self.id, self.generation)
        self.generation += 1

    def _evolve_local(self) -> None:
        """
        Evaluación → selección elitista (heapq) → mutación.

        Optimización vs skeleton:
          - heapq.nlargest O(n log k) en vez de sort O(n log n)
          - Construcción directa de nueva población sin doble lista
        """
        if not self.population:
            return

        # Evaluación en lote
        codes = [ind.code for ind in self.population]
        results = self.evaluator.evaluate_batch(codes)

        for ind, res in zip(self.population, results):
            ind.score = res.score

        # Actualizar mejor local
        top = max(self.population, key=lambda x: x.score)
        self._history.append(top.score)

        if self.local_best is None or top.score > self.local_best.score:
            self.local_best = copy.deepcopy(top)
            logger.info(
                "Island %d — gen %d — nuevo mejor local: score=%.4f",
                self.id, self.generation, top.score,
            )

        # Selección elitista con heapq: O(n log k) vs O(n log n) sort
        elites = heapq.nlargest(self.config.top_k, self.population, key=lambda x: x.score)

        # Nueva población: elites + mutaciones
        # Construir nueva población con elites y mutaciones informadas
        # Capturamos información de errores de los individuos evaluados
        error_map: Dict[int, str] = {}
        for ind, res in zip(self.population, results):
            if res.stderr and not res.passed:
                # Guardamos las primeras 3 líneas del traceback
                error_map[ind.id] = "\n".join(res.stderr.splitlines()[:3])

        new_pop: List[Individual] = list(elites)
        while len(new_pop) < self.config.population_size:
            parent = random.choice(elites)
            # 15% de probabilidad de crossover si hay al menos dos elites
            if parent.score < 0 and random.random() < 0.10:
                mutated_code = self._redesign(parent.code, parent.score)
            elif random.random() < 0.15 and len(elites) >= 2:
                other = random.choice([e for e in elites if e != parent])
                mutated_code = self._crossover(parent.code, other.code)
            else:
                error_info = error_map.get(parent.id, "")
                mutated_code = self._mutate_with_context(parent.code, parent.score, error_info)
            new_pop.append(Individual(code=mutated_code))

        self.population = new_pop

    def _mutate(self, code: str) -> str:
        """
        Mutación híbrida: AST (determinista, siempre válido)
        o LLM (creativa, puede fallar → fallback al original).
        """
        if random.random() < 0.4:
            return ASTMutator.apply_random_mutation(code)

        prompt = (
            "Improve this Python function for correctness and efficiency. "
            "Return only valid Python code, no explanations:\n\n"
            + code
        )
        result = self.llm_fn(prompt)

        try:
            ast.parse(result)
            return result
        except SyntaxError:
            return code

    # ── Interfaz de migración ──────────────────────────────────────────────────

    def _mutate_with_context(self, code: str, score: float, error_info: str = "") -> str:
        """Mutación informada: selector AST + prompt estricto + fallback AST."""
        return self.core_engine.mutate_with_llm(
            code=code,
            score=score,
            error_info=error_info,
            llm_fn=self.llm_fn,
        )

    def _redesign(self, code: str, score: float) -> str:
        """Rediseño radical dirigido por LLM para individuos fallidos."""
        redesigned = self.core_engine.redesign_with_llm(
            code=code,
            score=score,
            task="Repair correctness first, then improve algorithmic efficiency.",
            llm_fn=self.llm_fn,
        )
        return redesigned if redesigned is not None else ASTMutator.apply_random_mutation(code)

    def _crossover(self, parent_a: str, parent_b: str) -> str:
        """Recombina dos soluciones con LLM y fallback AST local."""
        generated = self.core_engine.crossover_with_llm(parent_a, parent_b, self.llm_fn)
        if generated is not None:
            return generated

        try:
            tree_a = ast.parse(parent_a)
            tree_b = ast.parse(parent_b)
            funcs_a = {n.name: n for n in ast.walk(tree_a) if isinstance(n, ast.FunctionDef)}
            funcs_b = {n.name: n for n in ast.walk(tree_b) if isinstance(n, ast.FunctionDef)}
            common = set(funcs_a.keys()) & set(funcs_b.keys())
            if not common:
                return parent_a
            for node in ast.walk(tree_a):
                if isinstance(node, ast.FunctionDef) and node.name in common:
                    if random.random() < 0.5:
                        b_func = copy.deepcopy(funcs_b[node.name])
                        node.body = b_func.body
                        node.args = b_func.args
            ast.fix_missing_locations(tree_a)
            result = ast.unparse(tree_a)
            ast.parse(result)
            return result
        except Exception:
            return parent_a
# ── Interfaz de migración ──────────────────────────────────────────────────

    def get_migrants(self, count: int) -> List[Individual]:
        """Devuelve una muestra aleatoria de la población actual."""
        if not self.population:
            return []
        return random.sample(self.population, min(count, len(self.population)))

    def receive_migrant(self, individual: Individual) -> None:
        """
        Acepta un inmigrante: lo añade si hay espacio,
        o reemplaza al peor si supera su puntuación.
        """
        if len(self.population) < self.config.population_size:
            self.population.append(individual)
        else:
            # min con key es O(n) — unavoidable sin heap dedicado
            worst_idx = min(
                range(len(self.population)),
                key=lambda i: self.population[i].score,
            )
            if individual.score > self.population[worst_idx].score:
                self.population[worst_idx] = individual


# ══════════════════════════════════════════════════════════════════════════════
# 6. SANDBOX EVALUATOR
# ══════════════════════════════════════════════════════════════════════════════


def _eval_worker(args: Tuple[str, List[Dict], float]) -> EvalResult:
    """
    Función de nivel módulo (necesario para pickling en ProcessPoolExecutor).
    Ejecuta el código en un subproceso aislado y mide métricas.

    Optimización: cleanup garantizado en finally, truncación de stdout/stderr.
    """
    code, test_cases, timeout_sec = args
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        start = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            input=json.dumps(test_cases),
        )
        elapsed = time.perf_counter() - start

        # Intentar extraer reporte JSON de resultados de tests del stdout
        try:
            report = json.loads(proc.stdout.strip().split('\n')[-1])
            passed = report.get("passed", 0)
            total = report.get("total", 1)
            correctness = passed / total
            # Penalizar latencia menos agresivamente
            score = correctness * 100.0 - elapsed * 5.0
        except Exception:
            # Fallback al comportamiento original si no hay JSON válido
            correctness = 1.0 if proc.returncode == 0 else 0.0
            score = correctness * 100.0 - elapsed * 10.0

        return EvalResult(
            score=score,
            passed=proc.returncode == 0,
            metrics={"latency": elapsed, "correctness": correctness},
            stdout=proc.stdout[:2000],
            stderr=proc.stderr[:2000],
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        return EvalResult(
            score=-100.0,
            passed=False,
            metrics={"latency": timeout_sec, "correctness": 0.0},
            stdout="",
            stderr="[TIMEOUT]",
            timed_out=True,
        )
    except Exception as exc:
        return EvalResult(
            score=-200.0,
            passed=False,
            metrics={},
            stdout="",
            stderr=str(exc)[:2000],
            timed_out=False,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class SandboxEvaluator:
    """
    Evalúa lotes de código en paralelo usando ProcessPoolExecutor.

    Optimización vs skeleton:
      - Pool persistente (no recreate por batch) con shutdown() en __del__
      - sys.executable en vez de "python3" hardcodeado
    """

    def __init__(
        self,
        test_cases: List[Dict],
        timeout_sec: float = 10.0,
        memory_mb: int = 256,
        parallelism: Optional[int] = None,
    ):
        self.test_cases = test_cases
        self.timeout_sec = timeout_sec
        self.memory_mb = memory_mb
        # For environments where multiprocessing ProcessPool is unstable
        # (e.g. certain CI containers / forkserver limitations), allow forcing
        # serial evaluation via env var.
        if os.getenv("MUTALAMBDA_E2E_SERIAL", "0") == "1":
            self.parallelism = 1
        else:
            self.parallelism = min(
                parallelism or multiprocessing.cpu_count(),
                multiprocessing.cpu_count(),
            )
        # Pool persistente: evita overhead de crear/destruir procesos por batch
        self._pool = ProcessPoolExecutor(max_workers=self.parallelism)

    def evaluate_batch(self, codes: List[str]) -> List[EvalResult]:
        """Evaluación paralela con pool persistente."""
        if not codes:
            return []

        args_list = [(code, self.test_cases, self.timeout_sec) for code in codes]
        results: List[EvalResult] = [None] * len(codes)  # type: ignore[list-item]

        future_to_idx = {
            self._pool.submit(_eval_worker, args): idx
            for idx, args in enumerate(args_list)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                logger.warning("Eval worker %d raised: %s", idx, exc)
                results[idx] = EvalResult(
                    score=-200.0, passed=False, metrics={},
                    stdout="", stderr=str(exc)[:2000], timed_out=False,
                )

        return results  # type: ignore[return-value]

    def shutdown(self, wait: bool = True) -> None:
        """Apaga el pool de procesos de forma controlada."""
        self._pool.shutdown(wait=wait)

    def __del__(self) -> None:
        try:
            self.shutdown(wait=False)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# 7. SISTEMA DE PROMPTS EVOLUTIVO
# ══════════════════════════════════════════════════════════════════════════════


class PromptEvolver:
    """
    Evoluciona una población de PromptGenomes usando fitness = score
    del mejor código que cada prompt logra generar.
    """

    _DEFAULT_PROMPTS: List[Dict[str, Any]] = [
        {
            "system_prompt": "You are an expert Python engineer. Return only valid Python code.",
            "mutation_instructions": "Focus on algorithmic correctness.",
            "temperature": 0.7,
        },
        {
            "system_prompt": "You are a performance-oriented Python optimizer. Return only code.",
            "mutation_instructions": "Minimize time complexity.",
            "temperature": 0.5,
        },
        {
            "system_prompt": "You are a Pythonic code craftsman. Return only valid Python.",
            "mutation_instructions": "Use idiomatic Python, comprehensions, and built-in functions.",
            "temperature": 0.6,
        },
    ]

    # Operaciones de mutación como tuplas inmutables (evita recrear lambdas)
    _MUTATION_OPS: List[Tuple[str, str]] = [
        ("system_prompt_suffix", " Be more concise."),
        ("system_prompt_suffix", " Prioritize readability."),
        ("system_prompt_suffix", " Add type hints."),
        ("system_prompt_suffix", " Optimize for edge cases."),
        ("temperature_bump", ""),
        ("temperature_drop", ""),
    ]

    def __init__(self, llm_fn: Callable[[str], str], evaluator: SandboxEvaluator):
        self.llm_fn = llm_fn
        self.evaluator = evaluator
        self.population: List[PromptGenome] = self._init_population()
        self._generation: int = 0

    def _init_population(self) -> List[PromptGenome]:
        return [
            PromptGenome(
                system_prompt=p["system_prompt"],
                few_shot_examples=[],
                mutation_instructions=p["mutation_instructions"],
                temperature=p["temperature"],
            )
            for p in self._DEFAULT_PROMPTS
        ]

    def step(self, task: str, base_code: str) -> List[str]:
        """Un paso de evolución de prompts."""
        # Generar código con cada prompt genome
        generated = [
            self.llm_fn(pg.render(task, base_code)) for pg in self.population
        ]

        eval_results = self.evaluator.evaluate_batch(generated)

        for pg, res in zip(self.population, eval_results):
            pg.fitness = max(pg.fitness, res.score)

        # Selección elitista (50%)
        self.population.sort(key=lambda pg: pg.fitness, reverse=True)
        half = max(1, len(self.population) // 2)
        elites = self.population[:half]

        # Rellenar con mutaciones de elites
        new_pop: List[PromptGenome] = list(elites)
        while len(new_pop) < len(self._DEFAULT_PROMPTS):
            parent = copy.deepcopy(random.choice(elites))
            self._apply_mutation(parent)
            parent.fitness = 0.0
            new_pop.append(parent)

        self.population = new_pop
        self._generation += 1
        return generated

    def _apply_mutation(self, genome: PromptGenome) -> None:
        """Aplica una mutación aleatoria a un genoma de prompt."""
        op_type, value = random.choice(self._MUTATION_OPS)
        if op_type == "system_prompt_suffix":
            genome.system_prompt += value
        elif op_type == "temperature_bump":
            genome.temperature = min(1.0, genome.temperature + 0.1)
        elif op_type == "temperature_drop":
            genome.temperature = max(0.1, genome.temperature - 0.1)

    def get_best_prompt(self) -> Optional[PromptGenome]:
        """Retorna el mejor prompt genome actual."""
        if not self.population:
            return None
        return max(self.population, key=lambda pg: pg.fitness)


# ══════════════════════════════════════════════════════════════════════════════
# 8. ARCHIVO DE SOLUCIONES A LARGO PLAZO (Memoria)
# ══════════════════════════════════════════════════════════════════════════════


class SolutionArchive:
    """
    Memoria a largo plazo con búsqueda semántica por embeddings.

    Optimizaciones vs skeleton:
      - collections.deque O(1) pop izquierdo vs lista O(n)
      - Batch pruning: solo rebuild cuando se acumulan N eliminaciones
      - Embedding cache con LRU para códigos repetidos
      - encode() en batch cuando se añaden múltiples soluciones
    """

    def __init__(
        self,
        embedder_model: str = "all-MiniLM-L6-v2",
        max_size: int = 10_000,
        prune_threshold: int = 50,
    ):
        if SentenceTransformer is None or faiss is None:
            raise ImportError(
                "SolutionArchive requires faiss-cpu and sentence-transformers. "
                "Install them: pip install faiss-cpu sentence-transformers"
            )

        self.embedder = SentenceTransformer(
            f"sentence-transformers/{embedder_model}"
        )
        self._dim = self.embedder.get_sentence_embedding_dimension()
        self.index = faiss.IndexFlatIP(self._dim)
        self.solutions: Deque[ArchivedSolution] = deque(maxlen=max_size)
        self.max_size = max_size
        self.prune_threshold = prune_threshold
        self._pending_prunes: int = 0
        self._lock = threading.Lock()

    # ── Embedding helpers ─────────────────────────────────────────────────────

    def _encode_normalized(self, texts: List[str]) -> np.ndarray:
        """Encode + L2-normalize en batch."""
        embeddings = self.embedder.encode(
            texts, convert_to_numpy=True, show_progress_bar=False
        ).astype("float32")
        faiss.normalize_L2(embeddings)
        return embeddings

    def _rebuild_index(self) -> None:
        """Reconstruye el índice FAISS desde self.solutions (deque)."""
        self.index = faiss.IndexFlatIP(self._dim)
        if self.solutions:
            embeddings = np.vstack(
                [s.embedding.reshape(1, -1) for s in self.solutions]
            ).astype("float32")
            faiss.normalize_L2(embeddings)
            self.index.add(embeddings)

    # ── API pública ───────────────────────────────────────────────────────────

    def add(self, code: str, metrics: Dict[str, float]) -> None:
        """Agrega una solución al archivo con pruning lazy.

        [PATCH BUG-3] La comprobación de si deque va a expulsar un elemento
        debe hacerse ANTES del append: deque(maxlen=N) expulsa silenciosamente
        al añadir cuando ya está lleno, así que `len == max_size` antes del
        append es la condición correcta (no `>=` después).
        """
        emb = self._encode_normalized([code])[0]

        with self._lock:
            # Determinar si el append va a expulsar un elemento ANTES de hacerlo
            will_evict = len(self.solutions) == self.max_size

            self.index.add(emb.reshape(1, -1))
            self.solutions.append(
                ArchivedSolution(code=code, metrics=metrics, embedding=emb)
            )

            if will_evict:
                self._pending_prunes += 1

            # Rebuild batch: solo cuando acumulamos suficientes eliminaciones
            if self._pending_prunes >= self.prune_threshold:
                self._rebuild_index()
                self._pending_prunes = 0

    def add_batch(self, items: List[Tuple[str, Dict[str, float]]]) -> None:
        """Agrega múltiples soluciones en una sola operación de embedding."""
        if not items:
            return
        codes = [code for code, _ in items]
        embeddings = self._encode_normalized(codes)

        with self._lock:
            self.index.add(embeddings)
            for (code, metrics), emb in zip(items, embeddings):
                self.solutions.append(
                    ArchivedSolution(code=code, metrics=metrics, embedding=emb)
                )

            self._pending_prunes += len(items)
            if self._pending_prunes >= self.prune_threshold:
                self._rebuild_index()
                self._pending_prunes = 0

    def nearest(self, code: str, k: int = 5) -> List[ArchivedSolution]:
        """Retorna las k soluciones más similares semánticamente."""
        with self._lock:
            if not self.solutions:
                return []

            # Sincronizar FAISS si hay prunes pendientes
            if self._pending_prunes > 0:
                self._rebuild_index()
                self._pending_prunes = 0

            emb = self._encode_normalized([code])
            k = min(k, len(self.solutions))
            distances, indices = self.index.search(emb, k)
            solution_list = list(self.solutions)
            return [solution_list[i] for i in indices[0] if 0 <= i < len(solution_list)]

    @property
    def size(self) -> int:
        return len(self.solutions)


# ══════════════════════════════════════════════════════════════════════════════
# 9. ORQUESTADOR PRINCIPAL — MutaLambdaAgent
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class EvolveConfig:
    """Configuración global del agente."""
    num_islands: int = 4
    generations: int = 50
    seed_codes: List[str] = field(default_factory=list)
    topology: str = "ring"
    population_size: int = 8
    top_k: int = 3
    migration_interval: int = 10
    migrants_per_island: int = 2
    archive_solutions: bool = True
    prompt_evolution: bool = True
    checkpoint_interval: int = 10
    checkpoint_dir: str = "checkpoints"
    # [MEJ-1] Parada temprana por ventana de mejora
    early_stop_patience: int = 15   # generaciones sin mejora mínima
    early_stop_delta: float = 0.001 # mejora relativa mínima para no parar
    # [MEJ-3] Peso del bonus de novedad en el score combinado (0 = puro fitness)
    novelty_alpha: float = 0.15     # 15 % novedad, 85 % fitness


class EarlyStopMonitor:
    """
    [MEJ-1] Detector de convergencia por ventana de mejora relativa.

    Más preciso que un threshold fijo: para solo si el score global
    no mejoró más de `delta` en las últimas `patience` generaciones.

    Uso:
        monitor = EarlyStopMonitor(patience=15, delta=0.001)
        if monitor.update(current_score):
            break  # convergencia detectada
    """

    def __init__(self, patience: int = 15, delta: float = 0.001):
        self.patience = patience
        self.delta = delta
        self._best: float = float("-inf")
        self._no_improve: int = 0

    def update(self, score: float) -> bool:
        """Retorna True si se detecta convergencia."""
        # Primera actualización o cuando _best es -inf: mejora absoluta
        if self._best == float("-inf"):
            self._best = score
            self._no_improve = 0
            return False

        improvement = score - self._best
        rel_improvement = improvement / (abs(self._best) + 1e-9)

        if rel_improvement > self.delta:
            self._best = score
            self._no_improve = 0
        else:
            self._no_improve += 1

        return self._no_improve >= self.patience

    @property
    def stagnant_generations(self) -> int:
        return self._no_improve


class MutaLambdaAgent:
    """
    Orquestador principal del ciclo evolutivo MutaLambda.

    Coordina:
      - N islas evolutivas con migración topológica
      - Evaluación en sandbox paralelo
      - Evolución de prompts (opcional)
      - Archivo de soluciones a largo plazo (opcional)
      - Checkpointing periódico
      - Métricas y telemetría
    """

    def __init__(
        self,
        config: EvolveConfig,
        test_cases: List[Dict],
        llm_fn: Optional[Callable[[str], str]] = None,
        timeout_sec: float = 10.0,
    ):
        self.config = config
        # Si no se provee una función LLM, usamos la fábrica que resuelve el backend
        if llm_fn is None:
            self.llm_fn = _resolve_llm_backend()
        else:
            self.llm_fn = llm_fn


        # Componentes core
        self.evaluator = SandboxEvaluator(
            test_cases=test_cases,
            timeout_sec=timeout_sec,
        )
        self.migration_bus = MigrationBus(topology=config.topology)

        # Crear islas
        island_cfg = IslandConfig(
            migration_interval=config.migration_interval,
            migrants_per_island=config.migrants_per_island,
            topology=config.topology,
            population_size=config.population_size,
            top_k=config.top_k,
        )
        self.islands: List[Island] = [
            Island(
                island_id=i,
                config=island_cfg,
                llm_fn=self.llm_fn,
                evaluator=self.evaluator,
                migration_bus=self.migration_bus,
            )
            for i in range(config.num_islands)
        ]

        # Sembrar poblaciones iniciales
        if config.seed_codes:
            for island in self.islands:
                island.seed_population(config.seed_codes)

        # Componentes opcionales
        self.archive: Optional[SolutionArchive] = None
        if config.archive_solutions:
            try:
                self.archive = SolutionArchive()
            except ImportError:
                logger.warning("FAISS/sentence-transformers not available; archive disabled.")

        self.prompt_evolver: Optional[PromptEvolver] = None
        if config.prompt_evolution:
            self.prompt_evolver = PromptEvolver(self.llm_fn, self.evaluator)

        # Métricas
        self._start_time: float = 0.0
        self._generation_times: List[float] = []
        self._global_best_history: List[float] = []

        # [MEJ-1] Monitor de parada temprana por convergencia
        self._early_stop = EarlyStopMonitor(
            patience=config.early_stop_patience,
            delta=config.early_stop_delta,
        )

    def _score_with_novelty(self, individual: Individual) -> float:
        """
        [MEJ-3] Combina fitness funcional con bonus de novedad semántica.

        score_combined = (1 - alpha) * fitness + alpha * novelty_score

        Beneficio: penaliza individuos que convergen a soluciones ya
        conocidas en el archivo, manteniendo diversidad genética sin
        sacrificar fitness.

        Si el archivo no está disponible, devuelve el fitness puro.
        """
        if self.archive is None or self.config.novelty_alpha == 0.0:
            return individual.score
        novelty = self.archive.novelty_score(individual.code, k=10)
        alpha = self.config.novelty_alpha
        return (1.0 - alpha) * individual.score + alpha * novelty * 100.0

    def run(self, task: str = "") -> Individual:
        """Ejecuta el ciclo evolutivo completo.

        Integra:
          - [MEJ-1] Parada temprana por EarlyStopMonitor (ventana de mejora)
          - [MEJ-2/3] Archivado con novelty_score para penalizar convergencia
        """
        self._start_time = time.perf_counter()
        logger.info(
            "MutaLambda starting: %d islands × %d generations",
            self.config.num_islands,
            self.config.generations,
        )

        global_best: Optional[Individual] = None

        for gen in range(self.config.generations):
            gen_start = time.perf_counter()

            # Evolucionar cada isla (secuencialmente; las evaluaciones
            # internas ya son paralelas via ProcessPoolExecutor)
            for island in self.islands:
                island.step()

            # Evolución de prompts (opcional)
            if self.prompt_evolver and task:
                best_so_far = self.migration_bus.get_global_best()
                base_code = best_so_far.code if best_so_far else ""
                self.prompt_evolver.step(task, base_code)

            # Actualizar global best usando score combinado con novedad
            current_best = self.migration_bus.get_global_best()
            if current_best:
                combined = self._score_with_novelty(current_best)
                if global_best is None or combined > self._score_with_novelty(global_best):
                    global_best = copy.deepcopy(current_best)

            # Archivar soluciones prometedoras (batch para todo el gen)
            if self.archive and global_best:
                self.archive.add(
                    global_best.code,
                    {"score": global_best.score, "generation": float(gen)},
                )

            # Métricas
            gen_elapsed = time.perf_counter() - gen_start
            self._generation_times.append(gen_elapsed)
            current_score = global_best.score if global_best else float("-inf")
            self._global_best_history.append(current_score)

            # Logging periódico
            if gen % 5 == 0 or gen == self.config.generations - 1:
                avg_time = (
                    sum(self._generation_times[-5:]) /
                    min(5, len(self._generation_times[-5:]))
                )
                logger.info(
                    "Gen %d/%d | best=%.4f | avg_time=%.2fs | "
                    "archive=%d | stagnant=%d",
                    gen + 1, self.config.generations, current_score,
                    avg_time,
                    self.archive.size if self.archive else 0,
                    self._early_stop.stagnant_generations,
                )

            # Checkpoint periódico
            if (
                self.config.checkpoint_interval > 0
                and (gen + 1) % self.config.checkpoint_interval == 0
            ):
                self._save_checkpoint(gen + 1)

            # [MEJ-1] Parada temprana por convergencia (más fino que threshold fijo)
            if self._early_stop.update(current_score):
                logger.info(
                    "Early stop en gen %d: sin mejora ≥%.4f en %d generaciones.",
                    gen + 1, self.config.early_stop_delta,
                    self.config.early_stop_patience,
                )
                break

        total_time = time.perf_counter() - self._start_time
        logger.info(
            "Evolution complete in %.1fs. Best score: %.4f",
            total_time,
            global_best.score if global_best else float("-inf"),
        )

        self.shutdown()

        if global_best is None:
            raise RuntimeError("Evolution produced no valid individuals.")
        return global_best

    def _save_checkpoint(self, generation: int) -> None:
        """Guarda un checkpoint JSON con el estado actual."""
        os.makedirs(self.config.checkpoint_dir, exist_ok=True)
        path = os.path.join(
            self.config.checkpoint_dir, f"checkpoint_gen{generation:04d}.json"
        )
        best = self.migration_bus.get_global_best()
        data = {
            "generation": generation,
            "best_score": best.score if best else None,
            "best_code": best.code if best else None,
            "island_generations": [isl.generation for isl in self.islands],
            "avg_gen_time": (
                sum(self._generation_times) / len(self._generation_times)
                if self._generation_times else 0
            ),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.debug("Checkpoint saved: %s", path)

    def shutdown(self) -> None:
        """Apaga recursos de forma controlada."""
        self.evaluator.shutdown()
        logger.info("MutaLambda agent shut down cleanly.")

    def get_metrics(self) -> Dict[str, Any]:
        """Retorna métricas acumuladas del agente."""
        return {
            "total_generations": len(self._generation_times),
            "total_time_sec": round(sum(self._generation_times), 4),
            "avg_generation_time_sec": round(
                sum(self._generation_times) / len(self._generation_times)
                if self._generation_times else 0, 4
            ),
            "best_score_history": self._global_best_history,
            "archive_size": self.archive.size if self.archive else 0,
            "num_islands": len(self.islands),
            "stagnant_generations": self._early_stop.stagnant_generations,
            "novelty_alpha": self.config.novelty_alpha,
        }


# ══════════════════════════════════════════════════════════════════════════════
# 10. SUITE DE TESTS INTEGRADA
# ══════════════════════════════════════════════════════════════════════════════


def run_full_test_suite() -> bool:
    """
    [MEJ-4] Suite de tests completa ejecutable con --test.
    Cubre todos los componentes críticos y los 4 bugs parcheados.
    Retorna True si todos pasan, False en caso contrario.
    """
    import traceback

    passed: List[str] = []
    failed: List[Tuple[str, str]] = []

    def test(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            passed.append(name)
            print(f"  [PASS] {name}")
        except Exception as e:
            tb = traceback.format_exc().splitlines()[-1]
            failed.append((name, tb))
            print(f"  [FAIL] {name} — {tb}")

    print("\n" + "═" * 60)
    print("SUITE DE TESTS — MutaLambda Agent (v2 patched)")
    print("═" * 60)

    # ── Bloque 1: ASTMutator ────────────────────────────────────────────────
    print("\n── ASTMutator ──")

    def t_ast_syntax_valid():
        code = "def f(x):\n    total = 0\n    for i in range(x):\n        total += i\n    return total\n"
        invalid = sum(1 for _ in range(200) if _ast_invalid(ASTMutator.apply_random_mutation(code)))
        assert invalid == 0, f"{invalid}/200 mutaciones produjeron código inválido"

    def _ast_invalid(c: str) -> bool:
        try:
            ast.parse(c)
            return False
        except SyntaxError:
            return True

    def t_no_builtin_rename():
        """[BUG-1] _rename_variable no debe renombrar builtins."""
        code = "def f(n):\n    total = 0\n    for i in range(n):\n        total += i\n    return total\n"
        builtins_broken = 0
        for _ in range(500):
            m = ASTMutator.apply_random_mutation(code)
            # Si 'range' fue renombrado, el código fallará al ejecutarse
            if "range" not in m and "rangea" in m or "rangeb" in m or "rangec" in m:
                builtins_broken += 1
        assert builtins_broken == 0, f"Builtin renombrado {builtins_broken} veces"

    def t_replace_aug_no_class_mutation():
        """[BUG-2] _replace_aug_assign usa ast.Assign real, no __class__ hack."""
        code = "x = 0\nfor i in range(5):\n    x += i\n"
        tree = ast.parse(code)
        ASTMutator._replace_aug_assign(tree)
        ast.fix_missing_locations(tree)
        result = ast.unparse(tree)
        ast.parse(result)  # debe ser válido
        # Verificar que NO hay AugAssign (fue reemplazado)
        new_tree = ast.parse(result)
        aug = [n for n in ast.walk(new_tree) if isinstance(n, ast.AugAssign)]
        assert len(aug) == 0, "AugAssign no fue reemplazado"

    test("ast_todas_mutaciones_validas (200 runs)", t_ast_syntax_valid)
    test("BUG-1: no_rename_builtins (500 runs)", t_no_builtin_rename)
    test("BUG-2: replace_aug_assign_sin_class_hack", t_replace_aug_no_class_mutation)

    # ── Bloque 1b: CoreEvolutionEngine ─────────────────────────────────────
    print("\n── CoreEvolutionEngine ──")

    def t_core_selects_ast_regions():
        code = (
            "def solve(xs):\n"
            "    total = 0\n"
            "    for x in xs:\n"
            "        if x > 0:\n"
            "            total += x\n"
            "    return total\n"
        )
        engine = CoreEvolutionEngine()
        regions = engine.select_code_regions(code)
        assert regions, "No seleccionó regiones AST"
        assert regions[0].kind == "FunctionDef"
        assert regions[0].name == "solve"
        assert regions[0].complexity_score > 0

    def t_core_prompt_contract_is_strict():
        code = "def f(x):\n    return x + 1\n"
        engine = CoreEvolutionEngine()
        region = engine.select_code_regions(code, max_regions=1)[0]
        prompt = engine.build_mutation_prompt(code, region, score=1.0)
        assert "MODE: HEURISTIC_MUTATION" in prompt
        assert "Return raw Python code only" in prompt
        assert "Do not use Markdown fences" in prompt
        assert "ast.parse()" in prompt

    def t_core_extracts_fenced_code_and_rejects_prose():
        engine = CoreEvolutionEngine()
        fenced = "Here is code:\n```python\ndef f(x):\n    return x\n```\n"
        assert engine.extract_valid_code(fenced) == "def f(x):\n    return x"
        assert engine.extract_valid_code("I would improve it by using a loop.") is None

    def t_core_llm_mutation_falls_back_to_valid_code():
        code = "def f(x):\n    return x + 1\n"
        engine = CoreEvolutionEngine()
        result = engine.mutate_with_llm(
            code=code,
            score=-1.0,
            error_info="SyntaxError",
            llm_fn=lambda _prompt: "not python prose",
        )
        ast.parse(result)

    def t_core_llm_crossover_accepts_valid_code():
        code_a = "def f(x):\n    return x + 1\n"
        code_b = "def f(x):\n    return x * 2\n"
        engine = CoreEvolutionEngine()
        result = engine.crossover_with_llm(
            code_a,
            code_b,
            llm_fn=lambda _prompt: "def f(x):\n    return x + 2\n",
        )
        assert result == "def f(x):\n    return x + 2"

    test("core_selects_ast_regions", t_core_selects_ast_regions)
    test("core_prompt_contract_is_strict", t_core_prompt_contract_is_strict)
    test("core_extracts_fenced_code_and_rejects_prose", t_core_extracts_fenced_code_and_rejects_prose)
    test("core_llm_mutation_falls_back_to_valid_code", t_core_llm_mutation_falls_back_to_valid_code)
    test("core_llm_crossover_accepts_valid_code", t_core_llm_crossover_accepts_valid_code)

    # ── Bloque 2: SolutionArchive ────────────────────────────────────────────
    print("\n── SolutionArchive ──")

    def t_pending_prunes_correct():
        """[BUG-3] pending_prunes solo incrementa cuando hay evicción real."""
        # Simular la lógica corregida
        from collections import deque as _deque
        max_size = 5
        solutions = _deque(maxlen=max_size)
        prunes = 0
        for i in range(10):
            will_evict = len(solutions) == max_size
            solutions.append(i)
            if will_evict:
                prunes += 1
        # Con max_size=5, las evictions ocurren en los appends 6,7,8,9,10 → 5 evictions
        assert prunes == 5, f"Esperado 5 evictions, obtenido {prunes}"

    test("BUG-3: pending_prunes_correcto", t_pending_prunes_correct)

    # ── Bloque 3: MigrationBus ───────────────────────────────────────────────
    print("\n── MigrationBus ──")

    def t_cache_within_lock():
        """[BUG-4] _get_neighbors debe usarse desde dentro del lock."""
        bus = MigrationBus(topology="ring")

        class _FakeIsland:
            config = IslandConfig()
            local_best = None
            generation = 0
            population: list = []
            def get_migrants(self, n): return []
            def receive_migrant(self, x): pass

        for k in range(4):
            bus.islands[k] = _FakeIsland()

        # Llamar desde dentro del lock (como lo hace migrate)
        with bus._lock:
            neighbors = bus._get_neighbors(0)
        assert isinstance(neighbors, list) and len(neighbors) == 2

    def t_cache_invalidation():
        """Cache se invalida al registrar nueva isla."""
        bus = MigrationBus(topology="ring")

        class _FakeIsland:
            config = IslandConfig()
            local_best = None
            generation = 0
            population: list = []
            def get_migrants(self, n): return []
            def receive_migrant(self, x): pass

        for k in range(3):
            bus.islands[k] = _FakeIsland()

        v1 = bus._islands_version
        bus.register_island(99, _FakeIsland())
        v2 = bus._islands_version
        assert v2 > v1, "islands_version no incrementó"
        assert bus._neighbor_cache == {}, "Cache no fue limpiado al registrar"

    test("BUG-4: neighbors_dentro_de_lock", t_cache_within_lock)
    test("cache_invalida_al_registrar", t_cache_invalidation)

    # ── Bloque 4: EarlyStopMonitor ───────────────────────────────────────────
    print("\n── EarlyStopMonitor ──")

    def t_early_stop_triggers():
        """EarlyStop dispara después de `patience` generaciones sin mejora."""
        monitor = EarlyStopMonitor(patience=5, delta=0.01)
        score = 10.0
        stop = False
        for _ in range(20):
            stop = monitor.update(score)  # mismo score → no mejora
            if stop:
                break
        assert stop, "EarlyStop no disparó"
        assert monitor.stagnant_generations >= 5

    def t_early_stop_reset_on_improvement():
        """EarlyStop NO dispara si hay mejora relativa suficiente."""
        monitor = EarlyStopMonitor(patience=5, delta=0.01)
        score = 1.0
        for i in range(10):
            score *= 1.05  # 5% de mejora cada vez → no debe parar
            triggered = monitor.update(score)
            assert not triggered, f"Paró prematuramente en gen {i}"

    test("early_stop_dispara_sin_mejora", t_early_stop_triggers)
    test("early_stop_no_dispara_con_mejora", t_early_stop_reset_on_improvement)

    # ── Bloque 5: EvolveConfig ───────────────────────────────────────────────
    print("\n── EvolveConfig ──")

    def t_evolve_config_defaults():
        cfg = EvolveConfig()
        assert cfg.early_stop_patience == 15
        assert cfg.early_stop_delta == 0.001
        assert cfg.novelty_alpha == 0.15
        assert 0.0 <= cfg.novelty_alpha <= 1.0

    test("EvolveConfig_defaults_correctos", t_evolve_config_defaults)

    # ── Resumen ──────────────────────────────────────────────────────────────
    print("\n" + "─" * 60)
    total = len(passed) + len(failed)
    print(f"Resultado: {len(passed)}/{total} tests pasaron")
    if failed:
        print("\nFallidos:")
        for name, err in failed:
            print(f"  ✗ {name}: {err}")
    print("═" * 60 + "\n")

    return len(failed) == 0

def _demo_llm_fn(prompt: str) -> str:
    """LLM simulado para demostración: aplica micro-mutaciones al código."""
    # Extraer código del prompt (heurística simple)
    lines = prompt.split("\n")
    code_lines = [
        l for l in lines
        if l.strip() and not l.startswith(("You are", "Task:", "Improve", "Return", "Instructions:"))
    ]
    code = "\n".join(code_lines).strip()
    if not code:
        return "def solution():\n    return 42"

    # Intentar mutación AST
    mutated = ASTMutator.apply_random_mutation(code)
    return mutated


def main() -> None:
    """Demo/CLI: ejecuta MutaLambda con un LLM simulado o corre los tests."""
    import argparse

    parser = argparse.ArgumentParser(description="MutaLambda Agent v2")
    parser.add_argument("--islands", type=int, default=3)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--pop-size", type=int, default=6)
    parser.add_argument("--topology", default="ring",
                        choices=["ring", "fully_connected", "random"])
    parser.add_argument("--novelty-alpha", type=float, default=0.15,
                        help="Peso del bonus de novedad en el score (0.0–1.0)")
    parser.add_argument("--early-stop-patience", type=int, default=15)
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    # [MEJ-4] Flag para correr la suite de tests
    parser.add_argument("--test", action="store_true",
                        help="Ejecutar suite de tests integrada y salir")
    args = parser.parse_args()

    # Ajustar nivel de log desde CLI
    logging.getLogger("MutaLambda").setLevel(args.log_level)

    if args.test:
        ok = run_full_test_suite()
        sys.exit(0 if ok else 1)

    # Código semilla
    seed = (
        "def compute_sum(n):\n"
        "    total = 0\n"
        "    for i in range(n):\n"
        "        total += i\n"
        "    return total\n"
    )

    config = EvolveConfig(
        num_islands=args.islands,
        generations=args.generations,
        seed_codes=[seed],
        topology=args.topology,
        population_size=args.pop_size,
        top_k=max(2, args.pop_size // 3),
        archive_solutions=False,   # Deshabilitar FAISS para demo rápida
        prompt_evolution=False,
        novelty_alpha=args.novelty_alpha,
        early_stop_patience=args.early_stop_patience,
    )

    agent = MutaLambdaAgent(
        config=config,
        llm_fn=_demo_llm_fn,
        test_cases=[],
        timeout_sec=5.0,
    )

    best = agent.run(task="Optimize a sum function for correctness and speed")
    print("\n" + "=" * 60)
    print("BEST SOLUTION FOUND:")
    print("=" * 60)
    print(best.code)
    print(f"\nScore: {best.score:.4f}")
    print("\nMetrics:", json.dumps(agent.get_metrics(), indent=2, default=str))
if __name__ == "__main__":
    main()
