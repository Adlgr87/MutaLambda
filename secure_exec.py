"""Hardened in-process execution helpers (remediation ML-001).

MutaLambda's core function is evaluating *generated candidate code*. The
authoritative isolation boundary is the subprocess/container runner in
``runners.py`` (:class:`SubprocessRunner`, :class:`ContainerRunner`,
:class:`MicroVMRunner`) — those remain the recommended path for untrusted
input.

This module provides the **only sanctioned** way to load dynamic code into
the current process (differential testing, metrics injection, benchmark
harnesses). It fails closed by default:

1. **AST pre-scan** — ``scan_code_security`` rejects ``exec``, ``eval``,
   ``compile``, ``__import__``, ``globals``/``locals``/``vars``, ``getattr``,
   ``open``, forbidden imports (``os``/``subprocess``/``socket``/...) and
   forbidden attribute calls (``os.system``, ``subprocess.run``, ...) *before*
   anything is compiled or executed.
2. **Restricted ``__builtins__``** — a copy of the builtins module with the
   unambiguous RCE / I/O / introspection primitives removed, as
   defense-in-depth on top of the scan.

Neither layer is a full sandbox (an adversarial ``().__class__.__bases__``
chain is still possible in-process). Callers that need true isolation must
use ``sandbox.SandboxEvaluator`` / ``runners.create_runner`` instead. These
helpers exist to shrink the blast radius of the remaining in-process paths,
not to replace the process boundary.
"""

from __future__ import annotations

import builtins
from typing import Any, Callable, Dict, Optional

from runners import scan_code_security

# Unambiguous RCE / I/O / introspection primitives that are removed from the
# guarded builtins. ``__import__`` is intentionally *kept*: legitimate
# candidate code imports ``math``/``random``/``numpy``, and the AST scan is
# the gate that blocks importing dangerous modules and direct ``__import__``
# calls.
_DISABLED_BUILTINS = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "open",
        "input",
        "globals",
        "locals",
        "vars",
        "dir",
        "breakpoint",
        "memoryview",
        "help",
        "exit",
        "quit",
    }
)

_GUARDED_BUILTINS: Optional[Dict[str, Any]] = None


def _make_forbidden(name: str) -> Callable[..., Any]:
    def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(f"builtin '{name}' is disabled in guarded execution")

    _forbidden.__name__ = name
    return _forbidden


def guarded_builtins() -> Dict[str, Any]:
    """Return a copy of ``builtins`` minus the disabled primitives.

    Disabled names are replaced with raising stubs so a stray reference fails
    loudly instead of silently resolving to the dangerous builtin.
    """
    global _GUARDED_BUILTINS
    if _GUARDED_BUILTINS is None:
        allowed: Dict[str, Any] = {}
        for name in dir(builtins):
            # Dunders are kept (``__import__`` is required for ``import``
            # statements and ``__build_class__`` for ``class`` statements);
            # the AST scan — not the builtins dict — is the gate that blocks
            # importing dangerous modules and calling ``__import__`` directly.
            if name in _DISABLED_BUILTINS:
                allowed[name] = _make_forbidden(name)
            else:
                allowed[name] = getattr(builtins, name)
        _GUARDED_BUILTINS = allowed
    return dict(_GUARDED_BUILTINS)


def guarded_namespace(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build an exec namespace with restricted builtins and optional extras."""
    namespace: Dict[str, Any] = {"__builtins__": guarded_builtins()}
    if extra:
        namespace.update(extra)
    return namespace


def exec_guarded(
    code: str,
    namespace: Optional[Dict[str, Any]] = None,
    *,
    scan: bool = True,
    filename: str = "<candidate>",
) -> Dict[str, Any]:
    """Compile and execute ``code`` in the current process, fail-closed.

    Raises
    ------
    RuntimeError
        If the AST security scan rejects the code.
    """
    if scan:
        findings = scan_code_security(code)
        if findings:
            raise RuntimeError(f"security_scan:{','.join(findings)}")
    if namespace is None:
        namespace = guarded_namespace()
    else:
        namespace.setdefault("__builtins__", guarded_builtins())
    exec(compile(code, filename, "exec"), namespace, namespace)  # noqa: S102
    return namespace


def load_function(
    code: str,
    function_name: str,
    *,
    scan: bool = True,
) -> Callable[..., Any]:
    """Load a single callable from ``code`` using guarded execution.

    The returned function keeps the guarded namespace as ``__globals__``, so
    helper functions defined alongside it remain reachable while dangerous
    builtins stay disabled.
    """
    namespace = guarded_namespace({"__name__": "__mutalambda_guarded__"})
    exec_guarded(code, namespace, scan=scan)
    fn = namespace.get(function_name)
    if not callable(fn):
        raise NameError(f"function not found: {function_name}")
    return fn
