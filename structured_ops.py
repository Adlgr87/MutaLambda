"""A1 (Fase 1) — structured LLM output: JSON Schema, zero free prose.

The mutation contract is a strict JSON document:

    {
      "ops": [
        {
          "op_type": "replace_function_body" | "insert_helper" |
                     "delete_dead_code" | "replace_expression" | "refactor",
          "location": "def solution(n: int)",
          "unified_diff": "@@ -3,4 +3,4 @@\\n ...",
          "rationale": "<= 20 words",
          "confidence": 0.0 - 1.0
        }
      ]
    }

Components:
* ``build_schema_prompt`` — forces the JSON-only contract (fixed order,
  deterministic when inputs are fixed — O2-compatible).
* ``extract_json_object`` / ``validate_ops`` — lenient extraction, strict
  validation; validation errors feed a single repair round.
* ``apply_unified_diff`` / ``apply_ops`` — robust hunk applier (drift
  tolerant) with per-op validation; failed ops are rejected, never guessed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "OP_TYPES",
    "MUTATION_OP_SCHEMA",
    "MUTATION_OUTPUT_SCHEMA",
    "ProposedOp",
    "build_schema_prompt",
    "extract_json_object",
    "parse_ops",
    "validate_ops",
    "apply_unified_diff",
    "apply_ops",
]

OP_TYPES = (
    "replace_function_body",
    "insert_helper",
    "delete_dead_code",
    "replace_expression",
    "refactor",
)

MUTATION_OP_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["op_type", "location", "unified_diff", "rationale"],
    "properties": {
        "op_type": {"type": "string", "enum": list(OP_TYPES)},
        "location": {
            "type": "string",
            "description": "Human anchor in the source, e.g. 'def solution(n: int)' or 'line 12'.",
        },
        "unified_diff": {
            "type": "string",
            "description": "Unified diff against SOURCE (context 1-3 lines).",
        },
        "rationale": {"type": "string", "maxLength": 200},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "additionalProperties": False,
}

MUTATION_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["ops"],
    "properties": {
        "ops": {"type": "array", "items": MUTATION_OP_SCHEMA, "minItems": 1},
    },
    "additionalProperties": False,
}


@dataclass
class ProposedOp:
    op_type: str
    location: str
    unified_diff: str
    rationale: str = ""
    confidence: float = 0.5
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "op_type": self.op_type,
            "location": self.location,
            "unified_diff": self.unified_diff,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


def build_schema_prompt(
    *,
    mode: str,
    code: str,
    score: Optional[float] = None,
    error_block: str = "",
    task: str = "",
    n: int = 1,
    extra_rules: str = "",
) -> str:
    """Deterministic JSON-only prompt (fixed section order, O2-compatible)."""
    score_line = f"\nCURRENT SCORE: {score:.4f}\n" if score is not None else ""
    error_line = f"\nCURRENT ERROR (compressed):\n{error_block}\n" if error_block else ""
    task_line = f"\nTASK CONTEXT:\n{task}\n" if task else ""
    schema_text = json.dumps(MUTATION_OUTPUT_SCHEMA, indent=2, sort_keys=True)
    example = json.dumps(
        {
            "ops": [
                {
                    "op_type": "replace_function_body",
                    "location": "def solution(n: int)",
                    "unified_diff": (
                        "@@ -3,7 +3,4 @@\n "
                        "def solution(n: int):\n-    total = 0\n-    i = 1\n-    while i <= n:\n"
                        "-        total = total + i\n-        i = i + 1\n-    return total\n"
                        "+    return n * (n + 1) // 2"
                    ),
                    "rationale": "Closed-form sum replaces the loop.",
                    "confidence": 0.9,
                }
            ]
        },
        indent=2,
    )
    return f"""SYSTEM: You are MutaLambda structured mutation engine (MODE: {mode}).
Respond with ONE JSON object only. No prose, no markdown, no code fences.
The object MUST validate against this JSON Schema (draft-07):
{schema_text}

RULES:
- "ops": exactly {n} object(s).
- "op_type": one of {", ".join(OP_TYPES)}.
- "unified_diff": a unified diff against the SOURCE block below (context 1-3 lines, keep line prefixes ' ', '-', '+').
- "rationale": at most 20 words.
- "confidence": number between 0 and 1.
- The diff must produce syntactically valid Python when applied.
{extra_rules}

EXAMPLE RESPONSE:
{example}
{score_line}{error_line}{task_line}
SOURCE:
{code}

Respond now with the JSON object only.
"""


def build_repair_prompt(errors: List[str], original_prompt: str) -> str:
    """Single repair round after a schema-invalid response."""
    return (
        "Your previous response was REJECTED. Validation errors:\n- "
        + "\n- ".join(errors[:8])
        + "\n\nRespond again with a valid JSON object only (no prose, no fences).\n\n"
        + original_prompt
    )


# ── JSON extraction & validation ─────────────────────────────────────────────


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Find the first balanced top-level JSON object in *text* (fence-tolerant)."""
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", candidate)
        if m:
            candidate = m.group(1).strip()
    start = candidate.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(candidate)):
            ch = candidate[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(candidate[start : i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(data, dict):
                        return data
                    break
        start = candidate.find("{", start + 1)
    return None


def validate_ops(data: Any) -> Tuple[List[ProposedOp], List[str]]:
    """Strict validation against the schema. Returns (ops, errors)."""
    errors: List[str] = []
    if not isinstance(data, dict):
        return [], ["top-level JSON object required"]
    ops_raw = data.get("ops")
    if ops_raw is None:
        # Tolerate a bare op object or a bare list (LLM shorthand).
        if isinstance(data.get("op_type"), str):
            ops_raw = [data]
        elif isinstance(data.get("ops"), list):
            ops_raw = data["ops"]
    if not isinstance(ops_raw, list) or not ops_raw:
        return [], ['missing non-empty "ops" array']
    ops: List[ProposedOp] = []
    for i, item in enumerate(ops_raw):
        if not isinstance(item, dict):
            errors.append(f"ops[{i}] must be an object")
            continue
        op_type = item.get("op_type")
        if op_type not in OP_TYPES:
            errors.append(f"ops[{i}].op_type must be one of {list(OP_TYPES)} (got {op_type!r})")
        loc = item.get("location")
        if not isinstance(loc, str) or not loc.strip():
            errors.append(f"ops[{i}].location must be a non-empty string")
        diff = item.get("unified_diff")
        if not isinstance(diff, str) or not diff.strip():
            errors.append(f"ops[{i}].unified_diff must be a non-empty string")
        rationale = item.get("rationale", "")
        if not isinstance(rationale, str):
            errors.append(f"ops[{i}].rationale must be a string")
            rationale = ""
        confidence = item.get("confidence", 0.5)
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            confidence = float(min(1.0, max(0.0, confidence)))
        else:
            errors.append(f"ops[{i}].confidence must be a number 0..1")
            confidence = 0.5
        if errors and errors[-1].startswith(f"ops[{i}]"):
            continue  # this op is already invalid — do not keep it
        ops.append(
            ProposedOp(
                op_type=op_type,
                location=loc,
                unified_diff=diff,
                rationale=rationale[:200],
                confidence=confidence,
                raw=item,
            )
        )
    return ops, errors


def parse_ops(text: str) -> Tuple[List[ProposedOp], List[str]]:
    """extract + validate in one step."""
    data = extract_json_object(text)
    if data is None:
        return [], ["no JSON object found in response"]
    return validate_ops(data)


# ── Unified diff application ─────────────────────────────────────────────────

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


def _parse_hunks(diff: str) -> List[Tuple[int, List[Tuple[str, str]]]]:
    """Parse hunks into (old_start, [(kind, line)]).

    Tolerant of LLM sloppiness: headers without @@ are treated as one loose
    hunk; context lines may lack the leading space.
    """
    lines = (diff or "").splitlines()
    hunks: List[Tuple[int, List[Tuple[str, str]]]] = []
    current: Optional[List[Tuple[str, str]]] = None
    start = 1
    for raw in lines:
        if raw.startswith("\\"):
            continue  # "\ No newline at end of file"
        m = _HUNK_RE.match(raw)
        if m:
            start = int(m.group(1)) or 1
            current = []
            hunks.append((start, current))
            continue
        if current is None:
            # Loose mode: first +/- line starts an implicit hunk.
            if raw.startswith(("+", "-")) and not raw.startswith("---") and not raw.startswith("+++"):
                current = []
                hunks.append((1, current))
            else:
                continue
        if raw.startswith("---") or raw.startswith("+++"):
            continue
        if raw.startswith(" "):
            current.append((" ", raw[1:]))
        elif raw.startswith("-"):
            current.append(("-", raw[1:]))
        elif raw.startswith("+"):
            current.append(("+", raw[1:]))
        elif raw == "":
            current.append((" ", ""))
        else:
            # No prefix: treat as context (common LLM shorthand).
            current.append((" ", raw))
    return hunks


def _find_seq(lines: List[str], seq: List[str], anchor: int, drift: int) -> Optional[int]:
    """Find *seq* in *lines* near *anchor* (0-based). Returns index or None."""
    n = len(seq)
    if n == 0:
        lo = max(0, anchor - drift)
        hi = min(len(lines), anchor + drift + 1)
        return anchor if lo <= min(anchor, len(lines)) <= hi else max(lo, min(hi, len(lines)))
    lo = max(0, anchor - drift)
    hi = min(len(lines), anchor + drift + n)
    for strict in (2, 1, 0):
        # strict=2: exact; 1: trailing-insensitive; 0: whitespace-insensitive
        # (LLM diffs frequently garble indentation — identify the line by
        # content, not by exact spacing).
        for i in range(lo, hi - n + 1):
            ok = True
            for j in range(n):
                a, b = lines[i + j], seq[j]
                if strict == 2:
                    same = a == b
                elif strict == 1:
                    same = a.rstrip() == b.rstrip()
                else:
                    same = a.strip() == b.strip()
                if not same:
                    ok = False
                    break
            if ok:
                return i
    return None


def apply_unified_diff(source: str, diff: str) -> Optional[str]:
    """Apply a (possibly sloppy) unified diff to *source*. None on mismatch."""
    hunks = _parse_hunks(diff)
    if not hunks or all(not ops for _, ops in hunks):
        return None
    src_lines = source.splitlines()
    out: List[str] = []
    pos = 0
    drift = 8
    for old_start, ops in hunks:
        old_seq = [text for kind, text in ops if kind in (" ", "-")]
        anchor = max(0, (old_start or 1) - 1)
        idx = _find_seq(src_lines, old_seq, anchor, drift)
        if idx is None:
            # Retry with wider drift once.
            idx = _find_seq(src_lines, old_seq, anchor, max(drift, len(src_lines) // 2))
        if idx is None:
            return None
        if idx < pos:
            return None  # hunks out of order / overlapping
        out.extend(src_lines[pos:idx])
        for kind, text in ops:
            if kind != "-":
                out.append(text)
        pos = idx + len(old_seq)
    out.extend(src_lines[pos:])
    result = "\n".join(out)
    if source.endswith("\n"):
        result += "\n"
    return result


def apply_ops(source: str, ops: List[ProposedOp], *, validate_python: bool = True) -> Tuple[str, List[str], List[str]]:
    """Apply ops sequentially. Returns (code, applied_locations, failed_locations)."""
    code = source
    applied: List[str] = []
    failed: List[str] = []
    for op in ops:
        try:
            new_code = apply_unified_diff(code, op.unified_diff)
        except Exception:
            new_code = None
        if new_code is None:
            failed.append(op.location)
            continue
        if validate_python:
            import ast as _ast

            try:
                _ast.parse(new_code)
            except SyntaxError:
                failed.append(op.location)
                continue
        code = new_code
        applied.append(op.location)
    return code, applied, failed
