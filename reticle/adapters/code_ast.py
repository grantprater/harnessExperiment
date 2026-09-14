"""Code AST Adapter and Syntax Analysis Engine."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class AstParseResult:
    valid: bool
    syntax_error: Optional[str] = None
    error_line: Optional[int] = None
    error_offset: Optional[int] = None
    functions: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)


def parse_and_inspect_code(code_str: str) -> AstParseResult:
    """Parse Python source code using the AST compiler and extract structural symbols."""
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return AstParseResult(
            valid=False,
            syntax_error=str(e.msg),
            error_line=e.lineno,
            error_offset=e.offset
        )

    funcs = []
    classes = []
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports.append(f"{mod}.{alias.name}")

    return AstParseResult(
        valid=True,
        functions=funcs,
        classes=classes,
        imports=imports
    )


def validate_python_syntax(code_str: str) -> Tuple[bool, Optional[str]]:
    """Return (True, None) if code is valid Python syntax, else (False, error_msg)."""
    res = parse_and_inspect_code(code_str)
    return res.valid, res.syntax_error
