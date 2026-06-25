"""AST mutation and core LLM-guided evolution engine."""

from __future__ import annotations

import ast
import builtins
import copy
import random
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple


class ASTMutator:
    """Mutaciones sobre el AST que garantizan código sintácticamente válido."""

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

        random.shuffle(mutations)
        for mut_fn in mutations[:5]:
            try:
                new_tree = copy.deepcopy(tree)
                mut_fn(new_tree)
                ast.fix_missing_locations(new_tree)
                result = ast.unparse(new_tree)
                ast.parse(result)
                if result.strip() != code.strip():
                    return result
            except (SyntaxError, ValueError, AttributeError):
                continue

        return code

    @classmethod
    def _swap_binary_ops(cls, tree: ast.Module) -> None:
        swaps = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.BinOp) and type(node.op) in cls._COMMUTATIVE_PAIRS
        ]
        if swaps:
            node = random.choice(swaps)
            node.left, node.right = node.right, node.left

    @classmethod
    def _replace_constant(cls, tree: ast.Module) -> None:
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
        conditionals = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.If, ast.While))
        ]
        if conditionals:
            node = random.choice(conditionals)
            node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)

    @staticmethod
    def _swap_comparison(tree: ast.Module) -> None:
        _INVERSE = {
            ast.Lt: ast.Gt, ast.Gt: ast.Lt,
            ast.LtE: ast.GtE, ast.GtE: ast.LtE,
            ast.Eq: ast.Eq, ast.NotEq: ast.NotEq,
        }
        comps = [node for node in ast.walk(tree) if isinstance(node, ast.Compare)]
        if comps:
            node = random.choice(comps)
            if len(node.ops) != 1 or len(node.comparators) != 1:
                return
            new_ops = []
            for op in node.ops:
                inv = _INVERSE.get(type(op))
                if inv:
                    new_ops.append(inv())
                else:
                    new_ops.append(op)
            node.ops = new_ops
            node.left, node.comparators[-1] = node.comparators[-1], node.left

    _PROTECTED_NAMES: frozenset = frozenset(
        set(dir(builtins))
        | {"True", "False", "None"}
        | set(__import__("keyword").kwlist)
    )

    @classmethod
    def _rename_variable(cls, tree: ast.Module) -> None:
        locally_defined: set = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        protected = cls._PROTECTED_NAMES | locally_defined

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
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == original_id:
                node.id = original_id + suffix

    @staticmethod
    def _duplicate_statement(tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if hasattr(node, "body") and node.body and len(node.body) < 50:
                idx = random.randrange(len(node.body))
                node.body.insert(idx, copy.deepcopy(node.body[idx]))
                return

    @staticmethod
    def _swap_if_else(tree: ast.Module) -> None:
        ifs = [node for node in ast.walk(tree) if isinstance(node, ast.If) and node.orelse]
        if ifs:
            node = random.choice(ifs)
            node.body, node.orelse = node.orelse, node.body
            node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)

    @staticmethod
    def _replace_aug_assign(tree: ast.Module) -> None:
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


def ast_crossover(parent_a: str, parent_b: str, rng: random.Random = random) -> str:
    """Recombina funciones compartidas entre dos fragmentos de código AST."""
    try:
        tree_a = ast.parse(parent_a)
        tree_b = ast.parse(parent_b)
        funcs_a = {n.name: n for n in ast.walk(tree_a) if isinstance(n, ast.FunctionDef)}
        funcs_b = {n.name: n for n in ast.walk(tree_b) if isinstance(n, ast.FunctionDef)}
        common = set(funcs_a) & set(funcs_b)
        if not common:
            return parent_a
        for node in ast.walk(tree_a):
            if isinstance(node, ast.FunctionDef) and node.name in common:
                if rng.random() < 0.5:
                    replacement = copy.deepcopy(funcs_b[node.name])
                    node.body = replacement.body
                    node.args = replacement.args
        ast.fix_missing_locations(tree_a)
        result = ast.unparse(tree_a)
        ast.parse(result)
        return result
    except Exception:
        return parent_a
