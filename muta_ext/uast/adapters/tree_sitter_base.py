#!/usr/bin/env python3
"""Shared tree-sitter plumbing for language adapters."""
from typing import Any, Optional, Union

from muta_ext.uast.adapters.base import BaseAdapter
from muta_ext.uast.core_uast import CoreUAST, Node, Opaque

try:
    from tree_sitter import Language, Parser
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False


def node_text(node: Any, source: Union[str, bytes]) -> str:
    """Extract the source text of a tree-sitter node, handling str and bytes."""
    text = source[node.start_byte:node.end_byte]
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return text


class TreeSitterAdapter(BaseAdapter):
    """Base for tree-sitter backed adapters.

    Subclasses declare ``language``, implement ``_load_language()`` to return a
    tree-sitter language handle, and add ``_visit_<node_type>`` methods. The
    dispatch, parser construction and error handling live here.
    """

    language = ""
    display_name = ""
    strict_parse = True
    source_as_bytes = False

    def __init__(self):
        if not TREE_SITTER_AVAILABLE:
            raise ImportError(f"tree-sitter is required for the {self._name} adapter")
        self._parser = Parser(Language(self._load_language()))

    def _load_language(self) -> Any:
        """Return the tree-sitter language handle for this adapter."""
        raise NotImplementedError

    @property
    def _name(self) -> str:
        return self.display_name or self.language

    def can_parse(self, source: str) -> bool:
        """Check whether the source parses without errors."""
        try:
            tree = self._parser.parse(bytes(source, "utf-8"))
            return not tree.root_node.has_error
        except Exception:
            return False

    def parse_to_uast(self, source: str) -> CoreUAST:
        """Parse source to CoreUAST."""
        try:
            tree = self._parser.parse(bytes(source, "utf-8"))
            if self.strict_parse and tree.root_node.has_error:
                raise ValueError(f"{self._name} source has parse errors")
            payload = source.encode("utf-8") if self.source_as_bytes else source
            return self._transform(tree.root_node, payload)
        except Exception as e:
            raise ValueError(f"Cannot parse {self._name} source: {e}")

    def _transform(self, node: Any, source: Union[str, bytes]) -> CoreUAST:
        """Transform the tree-sitter root node to CoreUAST."""
        body = []
        for child in node.children:
            uast_node = self._visit(child, source)
            if uast_node is not None:
                body.append(uast_node)

        source_text = source.decode("utf-8", errors="replace") if isinstance(source, bytes) else source
        return CoreUAST(
            body=body,
            language=self.language,
            metadata={"source": source_text},
        )

    def _visit(self, node: Any, source: Union[str, bytes]) -> Optional[Node]:
        """Dispatch to ``_visit_<node_type>``, falling back to Opaque."""
        visitor = getattr(self, f"_visit_{node.type.replace('-', '_')}", None)
        if visitor:
            return visitor(node, source)
        return Opaque(original_text=node_text(node, source), lang=self.language)
