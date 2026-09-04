"""Hybrid semantic distance: cosine similarity (AST embeddings) + Jaccard overlap (AST tokens).

Used by mutation_filters.py to avoid redundant / low-diversity mutations.
"""
from __future__ import annotations

import ast
import hashlib
import math
from typing import Set, Tuple


def ast_token_set(code: str) -> Set[str]:
    """Extract a set of normalized tokens from an AST for Jaccard overlap."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    
    tokens: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            tokens.add(f"func:{node.name}")
        elif isinstance(node, ast.ClassDef):
            tokens.add(f"class:{node.name}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                tokens.add(f"call:{node.func.attr}")
            elif isinstance(node.func, ast.Name):
                tokens.add(f"call:{node.func.id}")
        elif isinstance(node, (ast.If, ast.For, ast.While, ast.With)):
            tokens.add(type(node).__name__)
    
    return tokens


def jaccard_similarity(a: Set[str], b: Set[str]) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not a and not b:
        return 1.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def ast_hash(code: str) -> str:
    """Hash an AST representation for use as a pseudo-embedding key."""
    try:
        tree = ast.parse(code)
        # Normalize by sorting node fields
        dump = ast.dump(tree, annotate_fields=False)
        return hashlib.sha256(dump.encode()).hexdigest()
    except SyntaxError:
        return hashlib.sha256(code.encode()).hexdigest()


def cosine_similarity(hash_a: str, hash_b: str) -> float:
    """Cosine similarity over hex character n-gram distributions.
    
    This is a lightweight proxy for embedding-based similarity, suitable
    for AST representations without requiring an embedding model.
    """
    def ngram_counts(s: str, n: int = 2) -> dict[str, int]:
        counts: dict[str, int] = {}
        for i in range(len(s) - n + 1):
            gram = s[i:i + n]
            counts[gram] = counts.get(gram, 0) + 1
        return counts
    
    a_counts = ngram_counts(hash_a)
    b_counts = ngram_counts(hash_b)
    
    keys = set(a_counts) | set(b_counts)
    dot = sum(a_counts.get(k, 0) * b_counts.get(k, 0) for k in keys)
    mag_a = math.sqrt(sum(v * v for v in a_counts.values()))
    mag_b = math.sqrt(sum(v * v for v in b_counts.values()))
    
    return dot / (mag_a * mag_b) if mag_a > 0 and mag_b > 0 else 0.0


def hybrid_distance(code_a: str, code_b: str) -> float:
    """Hybrid semantic distance in [0, 1].
    
    Combines:
    - 0.6 * (1 - cosine_similarity) over AST hash n-grams
    - 0.4 * (1 - jaccard_similarity) over token sets
    
    A distance of 0.0 means identical, 1.0 means maximally different.
    Threshold recommendation: > 0.7 → sufficiently diverse mutation.
    """
    tokens_a = ast_token_set(code_a)
    tokens_b = ast_token_set(code_b)
    jaccard = jaccard_similarity(tokens_a, tokens_b)
    
    hash_a = ast_hash(code_a)
    hash_b = ast_hash(code_b)
    cosine = cosine_similarity(hash_a, hash_b)
    
    distance = 0.6 * (1.0 - cosine) + 0.4 * (1.0 - jaccard)
    return round(distance, 4)
