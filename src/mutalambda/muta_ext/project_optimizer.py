#!/usr/bin/env python3
"""Multi-file/Project-level optimization for MutaLambda."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
import json
import hashlib
from collections import defaultdict

from mutalambda.muta_ext.uast.core_uast import CoreUAST, Function, Identifier
from mutalambda.muta_ext.uast.adapters import get_adapter


@dataclass
class FileAnalysis:
    """Analysis result for a single file."""
    path: str
    functions: List[Dict] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    call_count: int = 0
    lines_of_code: int = 0
    complexity_score: float = 0.0


@dataclass
class CrossFileHotspot:
    """Cross-file function call hotspot."""
    caller_file: str
    callee_file: str
    function_name: str
    call_count: int
    hotness_score: float


@dataclass
class InliningOpportunity:
    """Opportunity for interprocedural inlining."""
    caller_file: str
    caller_function: str
    callee_file: str
    callee_function: str
    size_reduction_estimate: int
    call_frequency: int


@dataclass
class RedundancyPattern:
    """Detected redundant logic between files."""
    file1: str
    file2: str
    pattern_description: str
    similarity_score: float
    suggested_action: str


class ProjectAnalyzer:
    """Analyze project-wide optimization opportunities."""

    def __init__(self, project_root: str, extensions: List[str] = None):
        self.project_root = Path(project_root)
        self.extensions = extensions or [".go", ".py", ".rs", ".cpp", ".c"]
        self.file_analyses: Dict[str, FileAnalysis] = {}
        self.cross_file_hotspots: List[CrossFileHotspot] = []
        self.inline_opportunities: List[InliningOpportunity] = []
        self.redundancy_patterns: List[RedundancyPattern] = []
        self.call_graph: Dict[str, Set[str]] = defaultdict(set)
        self.function_registry: Dict[str, Dict] = {}

    def analyze(self, max_depth: int = 3, max_files: int = 100) -> Dict:
        """Run full project analysis."""
        # Discover source files
        source_files = self._discover_source_files()[:max_files]

        # Analyze each file
        for file_path in source_files:
            analysis = self._analyze_file(file_path)
            if analysis:
                self.file_analyses[file_path] = analysis
                self._build_call_graph(analysis)

        # Cross-file analysis
        self.cross_file_hotspots = self._detect_cross_file_hotspots()
        self.inline_opportunities = self._find_inline_opportunities(max_depth)
        self.redundancy_patterns = self._detect_redundancy()

        return self._generate_report()

    def _discover_source_files(self) -> List[Path]:
        """Discover source files in project."""
        files = []
        for ext in self.extensions:
            files.extend(self.project_root.rglob(f"*{ext}"))
        return sorted(files)

    def _analyze_file(self, file_path: Path) -> Optional[FileAnalysis]:
        """Analyze a single source file."""
        try:
            source = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            return None

        # Determine language from extension
        ext = file_path.suffix
        language = self._ext_to_language(ext)
        if not language:
            return None

        # Parse with UAST adapter
        try:
            adapter = get_adapter(language)
            if not adapter.can_parse(source):
                return None
            uast = adapter.parse_to_uast(source)
        except Exception:
            return None

        # Extract functions and metadata
        functions = []
        imports = []
        complexity = 0.0

        for node in uast.body:
            if isinstance(node, Function):
                functions.append({
                    "name": node.name.name,
                    "params": [p.name for p in node.params],
                    "return_type": node.return_type,
                    "body_length": len(node.body),
                    "line_number": self._get_line_number(source, node.name.name)
                })
                complexity += self._estimate_complexity(node)
            elif hasattr(node, 'original_text') and 'import' in getattr(node, 'original_text', ''):
                imports.append(node.original_text)

        return FileAnalysis(
            path=str(file_path),
            functions=functions,
            imports=imports,
            dependencies=[],
            call_count=sum(1 for f in functions for _ in f.get('params', [])),
            lines_of_code=len(source.split('\n')),
            complexity_score=complexity
        )

    def _ext_to_language(self, ext: str) -> Optional[str]:
        """Map file extension to language."""
        mapping = {
            '.go': 'go',
            '.py': 'python',
            '.rs': 'rust',
            '.cpp': 'cpp',
            '.c': 'cpp',
            '.h': 'cpp',
            '.hpp': 'cpp',
        }
        return mapping.get(ext)

    def _get_line_number(self, source: str, func_name: str) -> int:
        """Get line number of function definition."""
        lines = source.split('\n')
        for i, line in enumerate(lines, 1):
            if f'func {func_name}' in line or f'def {func_name}' in line:
                return i
        return 0

    def _estimate_complexity(self, func: Function) -> float:
        """Estimate cyclomatic complexity of a function."""
        complexity = 1.0
        for node in func.body:
            if hasattr(node, 'condition'):
                complexity += 1
            if hasattr(node, 'arms'):
                complexity += len(node.arms)
        return complexity

    def _build_call_graph(self, analysis: FileAnalysis):
        """Build call graph from file analysis."""
        for func in analysis.functions:
            caller = f"{analysis.path}:{func['name']}"
            self.function_registry[caller] = {
                'file': analysis.path,
                'name': func['name'],
                'complexity': func.get('complexity', 0)
            }

    def _detect_cross_file_hotspots(self) -> List[CrossFileHotspot]:
        """Detect cross-file function call hotspots."""
        hotspots = []
        # Structure: {caller_file: {callee_file: {func_name: call_count}}}
        function_calls: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: defaultdict(dict)
        )

        # Analyze call patterns across files
        for path, analysis in self.file_analyses.items():
            source = Path(path).read_text(encoding="utf-8")
            for func in analysis.functions:
                # Find calls to other functions
                for other_path, other_analysis in self.file_analyses.items():
                    if other_path == path:
                        continue
                    for other_func in other_analysis.functions:
                        func_name = other_func['name']
                        if func_name in source:
                            call_count = source.count(f"{func_name}(")
                            if call_count > 0:
                                function_calls[path][other_path][func_name] = call_count

        # Convert to hotspot objects
        for caller_file, callees in function_calls.items():
            for callee_file, funcs in callees.items():
                for func_name, count in funcs.items():
                    hotness = count / max(1, len(self.file_analyses))
                    hotspots.append(CrossFileHotspot(
                        caller_file=caller_file,
                        callee_file=callee_file,
                        function_name=func_name,
                        call_count=count,
                        hotness_score=hotness
                    ))

        return sorted(hotspots, key=lambda x: x.hotness_score, reverse=True)

    def _find_inline_opportunities(self, max_depth: int = 3) -> List[InliningOpportunity]:
        """Find opportunities for interprocedural inlining."""
        opportunities = []

        for path, analysis in self.file_analyses.items():
            for func in analysis.functions:
                # Small functions are good inline candidates
                if func['body_length'] < 20:  # Less than 20 lines
                    # Check call frequency
                    source = Path(path).read_text(encoding="utf-8")
                    call_count = source.count(f"{func['name']}(")
                    if call_count > 5:  # Frequently called
                        opportunities.append(InliningOpportunity(
                            caller_file=path,
                            caller_function=func['name'],
                            callee_file=path,
                            callee_function=func['name'],
                            size_reduction_estimate=func['body_length'] * 2,
                            call_frequency=call_count
                        ))

        return sorted(opportunities, key=lambda x: x.call_frequency, reverse=True)

    def _detect_redundancy(self) -> List[RedundancyPattern]:
        """Detect redundant logic between files."""
        patterns = []
        file_hashes = {}

        # Compute hash of function bodies
        for path, analysis in self.file_analyses.items():
            for func in analysis.functions:
                source = Path(path).read_text(encoding="utf-8")
                func_source = self._extract_function_source(source, func['name'])
                if func_source:
                    func_hash = hashlib.md5(func_source.encode()).hexdigest()[:16]
                    key = f"{path}:{func['name']}"
                    file_hashes[key] = {
                        'hash': func_hash,
                        'source': func_source,
                        'path': path,
                        'name': func['name']
                    }

        # Find similar hashes across files
        hash_groups = defaultdict(list)
        for key, info in file_hashes.items():
            hash_groups[info['hash']].append({**info, 'key': key})

        for hash_val, items in hash_groups.items():
            if len(items) > 1:
                # Check if from different files
                unique_files = set(item['path'] for item in items)
                if len(unique_files) > 1:
                    for i in range(len(items)):
                        for j in range(i + 1, len(items)):
                            patterns.append(RedundancyPattern(
                                file1=items[i]['path'],
                                file2=items[j]['path'],
                                pattern_description=f"Similar implementation of '{items[i]['name']}'",
                                similarity_score=0.95,  # Hash match is strong signal
                                suggested_action="Extract common logic to shared utility"
                            ))

        return patterns

    def _extract_function_source(self, source: str, func_name: str) -> Optional[str]:
        """Extract function source code."""
        lines = source.split('\n')
        in_function = False
        brace_count = 0
        func_lines = []

        for line in lines:
            if f'func {func_name}' in line or f'def {func_name}' in line:
                in_function = True
            if in_function:
                func_lines.append(line)
                brace_count += line.count('{') - line.count('}')
                if in_function and brace_count == 0 and len(func_lines) > 1:
                    return '\n'.join(func_lines)

        return None

    def _generate_report(self) -> Dict:
        """Generate comprehensive analysis report."""
        total_functions = sum(len(a.functions) for a in self.file_analyses.values())
        total_lines = sum(a.lines_of_code for a in self.file_analyses.values())

        return {
            "project_root": str(self.project_root),
            "files_analyzed": len(self.file_analyses),
            "total_functions": total_functions,
            "total_lines": total_lines,
            "cross_file_hotspots": [
                {
                    "caller": h.caller_file,
                    "callee": h.callee_file,
                    "function": h.function_name,
                    "calls": h.call_count,
                    "hotness": h.hotness_score
                }
                for h in self.cross_file_hotspots[:10]
            ],
            "inline_opportunities": [
                {
                    "file": o.caller_file,
                    "function": o.caller_function,
                    "size_reduction": o.size_reduction_estimate,
                    "call_frequency": o.call_frequency
                }
                for o in self.inline_opportunities[:10]
            ],
            "redundancy_patterns": [
                {
                    "file1": r.file1,
                    "file2": r.file2,
                    "description": r.pattern_description,
                    "similarity": r.similarity_score,
                    "action": r.suggested_action
                }
                for r in self.redundancy_patterns[:10]
            ],
            "file_summaries": [
                {
                    "path": a.path,
                    "functions": len(a.functions),
                    "lines": a.lines_of_code,
                    "complexity": a.complexity_score
                }
                for a in self.file_analyses.values()
            ]
        }

    def save_report(self, output_path: str):
        """Save analysis report to JSON file."""
        report = self._generate_report()
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        return output_path


def analyze_project(project_root: str, output_path: Optional[str] = None, **kwargs) -> Dict:
    """Convenience function to analyze a project."""
    analyzer = ProjectAnalyzer(project_root, **kwargs)
    report = analyzer.analyze()
    if output_path:
        analyzer.save_report(output_path)
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        project = sys.argv[1]
        report = analyze_project(project)
        print(json.dumps(report, indent=2))
    else:
        print("Usage: python project_analyzer.py <project_root>")
