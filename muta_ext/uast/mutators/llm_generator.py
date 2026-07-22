"""Generate CoreUAST-compatible mutators from natural language."""

from __future__ import annotations

import ast
import inspect
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import requests


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-4o-mini"

_BLOCKED_IMPORTS = {
    "os",
    "subprocess",
    "socket",
    "http",
    "httpx",
    "urllib",
    "requests",
    "ftplib",
    "telnetlib",
    "paramiko",
}
_BLOCKED_CALLS = {"eval", "exec", "__import__", "compile"}
_BLOCKED_ATTR_CALLS = {
    "os.system",
    "os.popen",
    "subprocess.run",
    "subprocess.call",
    "subprocess.Popen",
    "socket.socket",
    "requests.get",
    "requests.post",
    "requests.put",
    "requests.delete",
}
_SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "range": range,
    "set": set,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
}


class MutatorGenerationError(RuntimeError):
    """Raised when the model response cannot produce a valid mutator."""


class MutatorSafetyError(MutatorGenerationError):
    """Raised when generated code violates safety constraints."""


class MutatorValidationError(MutatorGenerationError):
    """Raised when generated code is syntactically or functionally invalid."""


@dataclass(frozen=True)
class GeneratedMutatorResult:
    """Generated and validated mutator payload."""

    code: str
    provider: str
    model: str
    system_prompt: str
    user_prompt: str


def build_system_prompt(language: str) -> str:
    """Build strict system prompt for CoreUAST mutator generation."""
    return (
        "You generate mutator files for MutaLambda CoreUAST.\n"
        "Return ONLY valid Python code for a single file. No markdown.\n"
        "Contract:\n"
        "- Must define: def mutate(node, **kwargs):\n"
        "- Input is a CoreUAST-like Python dict/list tree.\n"
        "- Return the mutated node/tree.\n"
        "- Be deterministic and side-effect free.\n"
        "- Never read/write files, run commands, open sockets, or call network APIs.\n"
        "- Do not use eval/exec/compile or dynamic imports.\n"
        "- Keep implementation minimal and focused on the requested transformation.\n"
        f"Target language: {language}.\n"
        "Output must be Python source code only."
    )


def _extract_python_code(text: str) -> str:
    content = (text or "").strip()
    fenced = re.search(r"```(?:python)?\s*([\s\S]*?)```", content, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return content


def _resolve_attr_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _resolve_attr_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _assert_safe_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = (alias.name or "").split(".")[0]
                if name in _BLOCKED_IMPORTS:
                    raise MutatorSafetyError(f"Blocked import detected: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in _BLOCKED_IMPORTS:
                raise MutatorSafetyError(f"Blocked import detected: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_CALLS:
                raise MutatorSafetyError(f"Blocked call detected: {node.func.id}()")
            target = _resolve_attr_name(node.func)
            if target in _BLOCKED_ATTR_CALLS:
                raise MutatorSafetyError(f"Blocked call detected: {target}()")


def validate_generated_mutator(code: str, language: str) -> None:
    """Run syntax, safety, signature and smoke validation checks."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:  # pragma: no cover - exercised via unit tests
        raise MutatorValidationError(f"Generated code has syntax errors: {exc}") from exc

    _assert_safe_ast(tree)

    module_globals: Dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    try:
        exec(compile(tree, filename="<generated_mutator>", mode="exec"), module_globals)
    except Exception as exc:
        raise MutatorValidationError(f"Generated code could not be loaded safely: {exc}") from exc

    mutate_fn = module_globals.get("mutate")
    if not callable(mutate_fn):
        raise MutatorValidationError(
            "Generated mutator must define a callable mutate(node, **kwargs)."
        )

    sig = inspect.signature(mutate_fn)
    if len(sig.parameters) < 1:
        raise MutatorValidationError("mutate() must accept at least one argument: node")

    sample = {
        "type": "Module",
        "language": language,
        "body": [{"type": "Function", "name": "demo", "params": []}],
    }
    try:
        out = mutate_fn(sample, language=language)
    except Exception as exc:
        raise MutatorValidationError(
            f"Generated mutator failed smoke test on CoreUAST sample: {exc}"
        ) from exc
    if out is None:
        raise MutatorValidationError("mutate() returned None in smoke test.")


def _call_openai_chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout_sec: float,
    session: Optional[requests.Session] = None,
) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise MutatorGenerationError("OPENAI_API_KEY is required when llm.enabled=true.")

    client = session or requests.Session()
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    response = client.post(
        OPENAI_CHAT_COMPLETIONS_URL,
        json=payload,
        headers={"Authorization": "Bearer " + api_key},
        timeout=timeout_sec,
    )
    response.raise_for_status()
    body = response.json()
    choices = body.get("choices") or []
    if not choices:
        raise MutatorGenerationError("OpenAI response did not include choices.")
    return str(choices[0].get("message", {}).get("content", "") or "")


def generate_mutator(
    user_intent: str,
    language: str,
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 1400,
    timeout_sec: float = 60.0,
    completion_fn: Optional[Callable[..., str]] = None,
) -> GeneratedMutatorResult:
    """Generate and validate a CoreUAST mutator from natural language."""
    if not user_intent.strip():
        raise MutatorGenerationError("User intent cannot be empty.")
    if provider != "openai":
        raise MutatorGenerationError(f"Unsupported provider for mutator generation: {provider}")

    system_prompt = build_system_prompt(language)
    user_prompt = (
        "Generate a CoreUAST-compatible mutator for the following intent.\n"
        f"Intent: {user_intent.strip()}\n"
        "Return only Python code."
    )
    response_text = (
        completion_fn(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_sec=timeout_sec,
        )
        if completion_fn
        else _call_openai_chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_sec=timeout_sec,
        )
    )

    code = _extract_python_code(response_text)
    if not code.strip():
        raise MutatorGenerationError("Model returned empty output for mutator code.")
    validate_generated_mutator(code, language)
    return GeneratedMutatorResult(
        code=code,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def generate_mutator_code(user_intent: str, language: str, **kwargs: Any) -> str:
    """Public helper returning only generated mutator code."""
    return generate_mutator(user_intent, language, **kwargs).code
