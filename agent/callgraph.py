"""Call-graph extraction (layered-docs Phase B).

Diagrams must be *grounded* in what the code actually does, not invented by
the model. This module extracts the real "who-calls-whom" structure from
source so the doc writer (Phase C) can render a mermaid diagram from facts
and merely have the LLM label/describe it.

Two consumers:
  * `endpoint_flow(route_func)` — ordered call chain from a route handler
    down through the functions it calls (handler -> service -> data), used
    for sequence diagrams of non-trivial endpoints.
  * `is_branchy(func)` — decision-point count, used to decide whether a
    function warrants a flowchart.

Python uses the stdlib `ast` for real fidelity. JS/TS uses a heuristic
(regex) extractor behind the same `CallGraph` interface — shallower, but
consistent. Only calls that resolve to functions defined in the analyzed
files are kept, so we never diagram library internals we can't see.
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field


@dataclass
class FuncNode:
    name: str  # qualified, e.g. "UserAPI.list" or "get_user"
    file: str = ""
    is_route: bool = False
    http_method: str | None = None
    route_path: str | None = None
    calls: list[str] = field(default_factory=list)  # callee simple names, in order
    branch_points: int = 0
    lineno: int = 0

    @property
    def simple(self) -> str:
        return self.name.split(".")[-1]


@dataclass
class CallGraph:
    nodes: dict[str, FuncNode] = field(default_factory=dict)  # keyed by qualified name
    # simple name -> qualified names (for resolving bare calls)
    _by_simple: dict[str, list[str]] = field(default_factory=dict)

    def add(self, node: FuncNode) -> None:
        self.nodes[node.name] = node
        self._by_simple.setdefault(node.simple, []).append(node.name)

    def resolve(self, simple_name: str) -> FuncNode | None:
        """Resolve a called simple-name to a defined FuncNode, if unambiguous
        enough to be useful. Returns the first match (source order)."""
        matches = self._by_simple.get(simple_name)
        if not matches:
            return None
        return self.nodes[matches[0]]

    def routes(self) -> list[FuncNode]:
        return [n for n in self.nodes.values() if n.is_route]


# ---------------------------------------------------------------------------
# Python extraction (stdlib ast)
# ---------------------------------------------------------------------------

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _route_from_decorator(dec: ast.expr) -> tuple[str, str] | None:
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return None
    attr = dec.func.attr
    path = None
    if dec.args and isinstance(dec.args[0], ast.Constant):
        path = str(dec.args[0].value)
    if attr in _HTTP_METHODS:
        return attr.upper(), path or "?"
    if attr == "route":
        method = "GET"
        for kw in dec.keywords:
            if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                elts = [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]
                if elts:
                    method = str(elts[0]).upper()
        return method, path or "?"
    return None


def _count_branches(node: ast.AST) -> int:
    count = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            count += 1
        elif isinstance(child, ast.Try):
            count += len(child.handlers)
        elif isinstance(child, ast.BoolOp):
            count += len(child.values) - 1
        elif isinstance(child, ast.IfExp):  # ternary
            count += 1
    return count


def _collect_calls(node: ast.AST) -> list[str]:
    """Ordered simple-names of functions called inside `node`."""
    calls: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            f = child.func
            if isinstance(f, ast.Name):
                calls.append(f.id)
            elif isinstance(f, ast.Attribute):
                calls.append(f.attr)
    return calls


def _py_functions(tree: ast.AST, file: str, graph: CallGraph) -> None:
    def visit(node: ast.AST, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                route = None
                for dec in child.decorator_list:
                    route = _route_from_decorator(dec)
                    if route:
                        break
                fn = FuncNode(
                    name=name,
                    file=file,
                    is_route=route is not None,
                    http_method=route[0] if route else None,
                    route_path=route[1] if route else None,
                    calls=_collect_calls(child),
                    branch_points=_count_branches(child),
                    lineno=getattr(child, "lineno", 0),
                )
                graph.add(fn)
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix=f"{child.name}.")

    visit(tree)


# ---------------------------------------------------------------------------
# JS/TS extraction (heuristic)
# ---------------------------------------------------------------------------

_JS_FUNC_RE = re.compile(
    r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*"
    r"([A-Za-z_$][\w$]*)\s*\([^)]*\)"
)
_JS_ARROW_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*"
    r"(?::\s*[^=]+?)?=\s*(?:async\s*)?\([^)]*\)\s*(?::\s*[^=>{]+?)?=>"
)
_JS_ROUTE_RE = re.compile(
    r"\b(?:app|router|api)\s*\.\s*(" + "|".join(_HTTP_METHODS) + r")\s*"
    r"\(\s*(['\"`])([^'\"`]+)\2"
)
_JS_CALL_RE = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
_JS_BRANCH_RE = re.compile(r"\b(if|for|while|switch|catch)\b|\?[^:]+:|&&|\|\|")
# Words that look like calls but are language keywords, not functions.
_JS_NONCALLS = {
    "if", "for", "while", "switch", "catch", "return", "function", "await",
    "typeof", "new", "super", "constructor",
}


def _js_body_after(source: str, start: int) -> str:
    """Extract the brace-delimited body starting at/after `start`."""
    open_idx = source.find("{", start)
    if open_idx == -1:
        return ""
    depth = 0
    for i in range(open_idx, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[open_idx + 1 : i]
    return source[open_idx + 1 :]


def _js_functions(source: str, file: str, graph: CallGraph) -> None:
    def body_stats(body: str) -> tuple[list[str], int]:
        calls = [
            m.group(1)
            for m in _JS_CALL_RE.finditer(body)
            if m.group(1) not in _JS_NONCALLS
        ]
        branches = len(_JS_BRANCH_RE.findall(body))
        return calls, branches

    for m in _JS_FUNC_RE.finditer(source):
        body = _js_body_after(source, m.end())
        calls, branches = body_stats(body)
        graph.add(
            FuncNode(name=m.group(1), file=file, calls=calls, branch_points=branches)
        )

    for m in _JS_ARROW_RE.finditer(source):
        body = _js_body_after(source, m.end())
        calls, branches = body_stats(body)
        graph.add(
            FuncNode(name=m.group(1), file=file, calls=calls, branch_points=branches)
        )

    for m in _JS_ROUTE_RE.finditer(source):
        method = m.group(1).upper()
        path = m.group(3)
        body = _js_body_after(source, m.end())
        calls, branches = body_stats(body)
        graph.add(
            FuncNode(
                name=path,
                file=file,
                is_route=True,
                http_method=method,
                route_path=path,
                calls=calls,
                branch_points=branches,
            )
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_call_graph(files: dict[str, str]) -> CallGraph:
    """Build a call graph from {path: source} across one feature's files."""
    graph = CallGraph()
    for path, source in files.items():
        if not source:
            continue
        if path.endswith(".py"):
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            _py_functions(tree, path, graph)
        elif os.path.splitext(path)[1].lower() in {
            ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"
        }:
            _js_functions(source, path, graph)
    return graph


def endpoint_flow(
    graph: CallGraph, route: FuncNode, max_depth: int = 4
) -> list[FuncNode]:
    """Ordered call chain from a route handler through functions it calls.

    Depth-first, following the first defined callee at each level, skipping
    calls that don't resolve to a known function (library calls, builtins).
    Cycles are guarded. Returns [route, ...downstream nodes].
    """
    flow: list[FuncNode] = [route]
    seen = {route.name}

    def walk(node: FuncNode, depth: int) -> None:
        if depth >= max_depth:
            return
        for callee_simple in node.calls:
            target = graph.resolve(callee_simple)
            if target is None or target.name in seen:
                continue
            seen.add(target.name)
            flow.append(target)
            walk(target, depth + 1)

    walk(route, 0)
    return flow


def is_branchy(func: FuncNode, threshold: int = 2) -> bool:
    """True if the function has enough decision points to warrant a flowchart."""
    return func.branch_points >= threshold
