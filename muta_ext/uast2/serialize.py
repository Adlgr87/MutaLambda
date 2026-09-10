#!/usr/bin/env python3
"""Flat-slab serialisation for UAST v2 (msgpack first, JSON fallback).

The arena makes serialisation trivially parallel to memory: the document is
stored as a **flat list of nodes** whose children are integer references, and
the roots are just a list of indices.  Compared to the legacy recursive JSON
dumps this gives:

* no repeated ``__type__`` dict nesting per level (references instead),
* msgpack binary encoding (``use_bin_type=True``, same conventions as
  ``checkpoint_manager``), optionally zlib-compressed,
* exact restoration of arena ids, parent pointers and locations.

Example:
    >>> from muta_ext.uast2.serialize import dumps, loads
    >>> payload = dumps(parse_to_uast("x = 1"))
    >>> document = loads(payload)
"""

from __future__ import annotations

import json
import typing as T
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from muta_ext.uast2.arena import Arena
from muta_ext.uast2.core import (
    KIND_NODE,
    KIND_NODE_DICT,
    KIND_NODE_LIST,
    UASTNode,
    CoreUAST,
    child_kinds,
    walk,
)

__all__ = [
    "SerializationError",
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "dumps",
    "loads",
    "dump",
    "load",
    "payload",
    "from_payload",
    "dumps_json",
    "loads_json",
]

FORMAT_NAME = "mutalambda.uast2"
FORMAT_VERSION = 1

_COMPRESSED_KEY = "compressed"
_VALUE_WRAPPER = "$value"


class SerializationError(ValueError):
    """Raised when a payload cannot be encoded/decoded."""


def _msgpack():
    try:
        import msgpack

        return msgpack
    except ImportError:  # pragma: no cover - optional dependency
        return None


# ── Encoding ─────────────────────────────────────────────────────────────────


def payload(uast: CoreUAST, include_location: bool = True) -> Dict[str, Any]:
    """Build the flat-slab payload for *uast* (no I/O)."""
    nodes: List[UASTNode] = list(uast.walk())
    ids: Dict[int, int] = {id(node): index for index, node in enumerate(nodes)}
    encoded: List[Dict[str, Any]] = []
    for index, node in enumerate(nodes):
        kinds = child_kinds(type(node))
        values: List[Any] = []
        for field_name in node._fields:
            values.append(_encode_value(getattr(node, field_name), kinds.get(field_name), ids))
        entry: Dict[str, Any] = {
            "t": type(node).__name__,
            "f": values,
            "p": ids.get(id(node._parent)) if node._parent is not None else None,
        }
        if node.tag is not None:
            entry["g"] = node.tag
        if include_location and node.lineno is not None:
            entry["l"] = [node.lineno, node.col_offset, node.end_lineno, node.end_col_offset]
        encoded.append(entry)
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "engine": uast.engine,
        "language": uast.language,
        "metadata": _encode_plain(uast.metadata),
        "roots": [ids[id(node)] for node in uast.body if id(node) in ids],
        "fields": _field_table(nodes),
        "nodes": encoded,
    }


def _field_table(nodes: T.Sequence[UASTNode]) -> Dict[str, List[str]]:
    """Field order per node type (forward compatibility for older readers)."""
    table: Dict[str, List[str]] = {}
    for node in nodes:
        name = type(node).__name__
        if name not in table:
            table[name] = list(node._fields)
    return table


def _encode_value(value: Any, kind: Optional[str], ids: Dict[int, int]) -> Any:
    if kind == KIND_NODE:
        if value is None:
            return None
        if isinstance(value, UASTNode):
            return ids[id(value)]
        return {_VALUE_WRAPPER: _encode_plain(value)}
    if kind == KIND_NODE_LIST:
        if value is None:
            return None
        if isinstance(value, UASTNode):  # e.g. Assign.target with a single node
            return ids[id(value)]
        if isinstance(value, (list, tuple)):
            return [ids[id(item)] if isinstance(item, UASTNode) else {_VALUE_WRAPPER: _encode_plain(item)} for item in value]
        return {_VALUE_WRAPPER: _encode_plain(value)}
    if kind == KIND_NODE_DICT:
        if value is None:
            return None
        if isinstance(value, dict):
            return {
                key: ids[id(item)] if isinstance(item, UASTNode) else {_VALUE_WRAPPER: _encode_plain(item)}
                for key, item in value.items()
            }
        return {_VALUE_WRAPPER: _encode_plain(value)}
    return _encode_plain(value)


def _encode_plain(value: Any) -> Any:
    value_type = type(value)
    if value is None or value_type in (str, int, float, bool):
        return value
    if value_type is bytes:
        return value
    if value_type in (list, tuple):
        return [_encode_plain(item) for item in value]
    if value_type is dict:
        return {str(key): _encode_plain(item) for key, item in value.items()}
    return str(value)


# ── Decoding ─────────────────────────────────────────────────────────────────


def from_payload(data: Dict[str, Any]) -> CoreUAST:
    """Rebuild a :class:`CoreUAST` (with arena ids + parents) from a payload."""
    fmt = data.get("format")
    if fmt != FORMAT_NAME:
        raise SerializationError(f"Unknown payload format: {fmt!r}")
    version = data.get("version", 0)
    if version > FORMAT_VERSION:
        raise SerializationError(
            f"Payload version {version} is newer than supported ({FORMAT_VERSION})"
        )
    entries: List[Dict[str, Any]] = data.get("nodes") or []
    nodes: List[Optional[UASTNode]] = []
    for index, entry in enumerate(entries):
        type_name = entry.get("t")
        from muta_ext.uast2.core import NODE_REGISTRY

        cls = NODE_REGISTRY.get(type_name)
        if cls is None:
            raise SerializationError(f"Unknown node type in payload: {type_name!r}")
        location = entry.get("l")
        node = cls(
            tag=entry.get("g"),
            lineno=location[0] if location else None,
            col_offset=location[1] if location else None,
            end_lineno=location[2] if location else None,
            end_col_offset=location[3] if location else None,
        )
        node._id = index
        nodes.append(node)

    for entry, node in zip(entries, nodes):
        assert node is not None
        kinds = child_kinds(type(node))
        values = entry.get("f") or []
        for field_name, raw in zip(node._fields, values):
            setattr(node, field_name, _decode_value(raw, kinds.get(field_name), nodes))
        parent_index = entry.get("p")
        if parent_index is not None and 0 <= parent_index < len(nodes):
            parent = nodes[parent_index]
            node._parent = parent
            node._slot = _slot_of(parent, node) if parent is not None else None

    roots = data.get("roots") or []
    body = [nodes[index] for index in roots if isinstance(index, int) and 0 <= index < len(nodes)]
    document = CoreUAST(
        body=[node for node in body if node is not None],
        language=data.get("language", "python"),
        metadata=dict(data.get("metadata") or {}),
        engine=data.get("engine", "v2"),
    )
    document.prepared = True
    return document


def _slot_of(parent: UASTNode, child: UASTNode) -> Any:
    """Recover the slot (field or ``(field, index)``) of *child* inside *parent*."""
    for field_name in parent._fields:
        value = getattr(parent, field_name)
        if value is child:
            return field_name
        if isinstance(value, list):
            for index, item in enumerate(value):
                if item is child:
                    return (field_name, index)
        elif isinstance(value, dict):
            for key, item in value.items():
                if item is child:
                    return (field_name, key)
    return None


def _decode_value(raw: Any, kind: Optional[str], nodes: List[Optional[UASTNode]]) -> Any:
    """Inverse of :func:`_encode_value` (defensive: unknown shapes pass through)."""
    if raw is None:
        return None
    if kind == KIND_NODE:
        reference = _decode_reference(raw, nodes)
        if reference is not None:
            return reference
        if isinstance(raw, dict) and _VALUE_WRAPPER in raw:
            return raw[_VALUE_WRAPPER]
        return raw
    if kind == KIND_NODE_LIST:
        if isinstance(raw, list):
            decoded: List[Any] = []
            for item in raw:
                reference = _decode_reference(item, nodes)
                if reference is not None:
                    decoded.append(reference)
                elif isinstance(item, dict) and _VALUE_WRAPPER in item:
                    decoded.append(item[_VALUE_WRAPPER])
                else:
                    decoded.append(item)
            return decoded
        reference = _decode_reference(raw, nodes)
        if reference is not None:
            return reference
        if isinstance(raw, dict) and _VALUE_WRAPPER in raw:
            return raw[_VALUE_WRAPPER]
        return raw
    if kind == KIND_NODE_DICT:
        if isinstance(raw, dict):
            mapping: Dict[Any, Any] = {}
            for key, item in raw.items():
                if isinstance(item, dict) and _VALUE_WRAPPER in item:
                    mapping[key] = item[_VALUE_WRAPPER]
                    continue
                reference = _decode_reference(item, nodes)
                mapping[key] = reference if reference is not None else item
            return mapping
        return raw
    return raw


def _decode_reference(raw: Any, nodes: List[Optional[UASTNode]]) -> Optional[UASTNode]:
    if isinstance(raw, int) and not isinstance(raw, bool):
        if 0 <= raw < len(nodes):
            return nodes[raw]
        raise SerializationError(f"Node reference out of range: {raw}")
    if isinstance(raw, dict) and _VALUE_WRAPPER in raw:
        return None
    return None


# ── Bytes / files ────────────────────────────────────────────────────────────


def dumps(
    uast: CoreUAST,
    compress: Union[bool, int, None] = False,
    include_location: bool = True,
) -> bytes:
    """Serialise *uast* to msgpack bytes (falls back to JSON when unavailable).

    ``compress`` accepts ``True``/an int level (zlib) — useful for checkpoints
    of large documents.
    """
    data = payload(uast, include_location=include_location)
    msgpack = _msgpack()
    if msgpack is not None:
        raw = msgpack.packb(data, use_bin_type=True)
        fmt = "msgpack"
    else:  # pragma: no cover - optional dependency
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        fmt = "json"
    if compress:
        level = zlib.Z_DEFAULT_COMPRESSION if compress is True else int(compress)
        raw = zlib.compress(raw, level)
        header = json.dumps({"format": FORMAT_NAME, "codec": fmt, _COMPRESSED_KEY: True}).encode(
            "utf-8"
        )
    else:
        header = json.dumps({"format": FORMAT_NAME, "codec": fmt, _COMPRESSED_KEY: False}).encode(
            "utf-8"
        )
    return len(header).to_bytes(4, "little") + header + raw


def loads(raw: Union[bytes, bytearray, memoryview]) -> CoreUAST:
    """Deserialise bytes produced by :func:`dumps` (auto-detects codec/zlib)."""
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise SerializationError("loads() expects bytes")
    buffer = bytes(raw)
    if len(buffer) < 4:
        raise SerializationError("Payload too short")
    header_length = int.from_bytes(buffer[:4], "little")
    header = json.loads(buffer[4 : 4 + header_length].decode("utf-8"))
    body = buffer[4 + header_length :]
    if header.get(_COMPRESSED_KEY):
        body = zlib.decompress(body)
    codec = header.get("codec")
    if codec == "msgpack":
        msgpack = _msgpack()
        if msgpack is None:  # pragma: no cover - optional dependency
            raise SerializationError("msgpack is required to read this payload")
        data = msgpack.unpackb(body, raw=False)
    else:
        data = json.loads(body.decode("utf-8"))
    return from_payload(data)


def dump(
    uast: CoreUAST,
    path: Union[str, Path],
    compress: Union[bool, int, None] = False,
    include_location: bool = True,
) -> int:
    """Write *uast* to *path*; returns the number of bytes written."""
    data = dumps(uast, compress=compress, include_location=include_location)
    Path(path).write_bytes(data)
    return len(data)


def load(path: Union[str, Path]) -> CoreUAST:
    """Read a document written by :func:`dump`."""
    return loads(Path(path).read_bytes())


# ── JSON helpers (legacy-compatible dict form) ───────────────────────────────


def dumps_json(uast: CoreUAST, indent: Optional[int] = None) -> str:
    """Legacy-compatible JSON text (``CoreUAST.to_dict``)."""
    return json.dumps(uast.to_dict(), sort_keys=True, indent=indent, default=str)


def loads_json(text: str) -> CoreUAST:
    """Parse legacy-compatible JSON text into a v2 document."""
    return CoreUAST.from_dict(json.loads(text))
