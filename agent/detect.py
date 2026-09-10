"""Detect API-surface changes in Python source using the stdlib `ast`.

We extract two kinds of "public API" symbols from each file:

* functions / methods — name + full signature + docstring
* HTTP routes         — decorators like @app.get("/x"), @router.post(...),
                        or @app.route("/x", methods=["POST"])

then compare the *before* and *after* surface of a changed file to
classify each symbol as added / removed / changed. Line-level diffs are
ignored — only structural changes to the API surface are reported, which
is what the docs actually care about (PRD section 5.2).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

# Attribute names commonly used for route decorators.
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


@dataclass
class Symbol:
    kind: str  # "function" | "route"
    name: str  # qualified, e.g. "get_user" or "UserAPI.list"
    signature: str  # e.g. "(user_id: int, verbose: bool = False) -> User"
    docstring: str | None = None
    http_method: str | None = None  # for routes
    route_path: str | None = None  # for routes
    lineno: int = 0

    @property
    def key(self) -> str:
        """Identity used to match a symbol across before/after."""
        if self.kind == "route":
            return f"route {self.http_method} {self.route_path}"
        return f"func {self.name}"

    def describe(self) -> str:
        if self.kind == "route":
            return f"{self.http_method} {self.route_path}  ({self.name}{self.signature})"
        return f"{self.name}{self.signature}"


@dataclass
class Change:
    status: str  # "added" | "removed" | "changed"
    key: str
    before: Symbol | None = None
    after: Symbol | None = None
    details: list[str] = field(default_factory=list)

    def describe(self) -> str:
        sym = self.after or self.before
        head = f"[{self.status.upper()}] {sym.describe() if sym else self.key}"
        if self.details:
            head += "\n    - " + "\n    - ".join(self.details)
        return head


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    a = node.args
    parts: list[str] = []

    posonly = getattr(a, "posonlyargs", [])
    defaults = list(a.defaults)
    # Defaults align to the tail of (posonly + args).
    non_kw = posonly + a.args
    default_offset = len(non_kw) - len(defaults)

    def render(arg: ast.arg, default: ast.expr | None) -> str:
        s = arg.arg
        if arg.annotation is not None:
            s += f": {ast.unparse(arg.annotation)}"
        if default is not None:
            s += f" = {ast.unparse(default)}"
        return s

    for i, arg in enumerate(non_kw):
        default = None
        di = i - default_offset
        if di >= 0:
            default = defaults[di]
        parts.append(render(arg, default))
        if posonly and i == len(posonly) - 1:
            parts.append("/")

    if a.vararg is not None:
        va = "*" + a.vararg.arg
        if a.vararg.annotation is not None:
            va += f": {ast.unparse(a.vararg.annotation)}"
        parts.append(va)
    elif a.kwonlyargs:
        parts.append("*")

    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        parts.append(render(arg, default))

    if a.kwarg is not None:
        kw = "**" + a.kwarg.arg
        if a.kwarg.annotation is not None:
            kw += f": {ast.unparse(a.kwarg.annotation)}"
        parts.append(kw)

    sig = "(" + ", ".join(parts) + ")"
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def _route_from_decorator(dec: ast.expr) -> tuple[str, str] | None:
    """Return (http_method, path) if the decorator looks like a route."""
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return None
    attr = dec.func.attr
    path = None
    if dec.args and isinstance(dec.args[0], ast.Constant):
        path = str(dec.args[0].value)

    if attr in _HTTP_METHODS:  # @app.get("/x")
        return attr.upper(), path or "?"
    if attr == "route":  # @app.route("/x", methods=["POST"])
        method = "GET"
        for kw in dec.keywords:
            if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                elts = [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]
                if elts:
                    method = str(elts[0]).upper()
        return method, path or "?"
    return None


def extract_symbols(source: str | None) -> dict[str, Symbol]:
    """Map of symbol.key -> Symbol for all public API symbols in `source`."""
    if not source:
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    symbols: dict[str, Symbol] = {}

    def visit(node: ast.AST, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                sig = _format_signature(child)
                doc = ast.get_docstring(child)

                route = None
                for dec in child.decorator_list:
                    route = _route_from_decorator(dec)
                    if route:
                        break

                if route:
                    method, path = route
                    sym = Symbol(
                        kind="route",
                        name=name,
                        signature=sig,
                        docstring=doc,
                        http_method=method,
                        route_path=path,
                        lineno=child.lineno,
                    )
                else:
                    # Skip private helpers — not public API surface.
                    if child.name.startswith("_"):
                        continue
                    sym = Symbol(
                        kind="function",
                        name=name,
                        signature=sig,
                        docstring=doc,
                        lineno=child.lineno,
                    )
                symbols[sym.key] = sym
            elif isinstance(child, ast.ClassDef):
                if not child.name.startswith("_"):
                    visit(child, prefix=f"{child.name}.")

    visit(tree)
    return symbols


def diff_symbols(
    old: dict[str, Symbol], new: dict[str, Symbol]
) -> list[Change]:
    """Classify changes between two symbol maps."""
    changes: list[Change] = []

    for key, sym in new.items():
        if key not in old:
            changes.append(Change("added", key, after=sym))

    for key, sym in old.items():
        if key not in new:
            changes.append(Change("removed", key, before=sym))

    for key in old.keys() & new.keys():
        before, after = old[key], new[key]
        details: list[str] = []
        if before.signature != after.signature:
            details.append(
                f"signature: {before.name}{before.signature} "
                f"-> {after.name}{after.signature}"
            )
        if (before.docstring or "") != (after.docstring or ""):
            details.append("docstring changed")
        if details:
            changes.append(
                Change("changed", key, before=before, after=after, details=details)
            )

    return changes


def detect_file_changes(
    old_source: str | None, new_source: str | None
) -> list[Change]:
    """Full pipeline for one file: extract both sides, diff, classify."""
    return diff_symbols(extract_symbols(old_source), extract_symbols(new_source))
