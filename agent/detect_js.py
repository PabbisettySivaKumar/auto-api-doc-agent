"""Detect API-surface changes in JavaScript / TypeScript (PRD Phase 4).

This is a **heuristic** extractor (regex + brace scanning), not a full
parser. It deliberately adds zero dependencies so it runs anywhere the
rest of the agent runs (incl. the Render free tier). It produces the same
`Symbol` / `Change` types as the Python detector, so everything
downstream — retrieval, RAG, drafting, PR — works unchanged.

Recognised surface:
  * function declarations         export function foo(a): T { ... }
  * arrow functions on bindings   export const foo = (a) => ...
  * class methods                 class API { list(page) { ... } }
  * Express-style routes          app.get("/x") / router.post("/x")

Known limits vs. a real parser (tree-sitter is the upgrade path): params
containing `)` (e.g. a default that calls a function) can confuse the
param capture, and JSDoc is not read. Signature changes on functions/
methods and added/removed endpoints — the doc-relevant cases — are caught.
"""

from __future__ import annotations

import os
import re

from .detect import Change, Symbol, diff_symbols

JS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "all"}

# Names that are control-flow / not real methods, to reject in class bodies.
_NOT_METHODS = {
    "if", "for", "while", "switch", "catch", "return", "function", "do",
    "else", "try", "finally", "with", "constructor", "await", "yield",
}

_FUNC_DECL_RE = re.compile(
    r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*"
    r"([A-Za-z_$][\w$]*)\s*(\([^)]*\))\s*(?::\s*([^{\n]+?))?\s*\{"
)
_ARROW_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*"
    r"(?::\s*[^=]+?)?=\s*(?:async\s*)?"
    r"(\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::\s*([^=>{]+?))?=>"
)
_ROUTE_RE = re.compile(
    r"\b(?:app|router|api)\s*\.\s*(" + "|".join(_HTTP_METHODS) + r")\s*"
    r"\(\s*(['\"`])([^'\"`]+)\2"
)
_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)[^{]*\{")
_METHOD_TAIL_RE = re.compile(
    r"(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?"
    r"([A-Za-z_$][\w$]*)\s*(\([^)]*\))\s*(?::\s*([^{]+?))?\s*$"
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _signature(params: str, ret: str | None) -> str:
    if not params.startswith("("):
        params = f"({params})"  # bare arrow param: x => ...
    sig = _norm(params)
    if ret:
        sig += f": {_norm(ret)}"
    return sig


def _matching_brace(s: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _add(symbols: dict[str, Symbol], sym: Symbol) -> None:
    if sym.kind == "function" and sym.name.split(".")[-1].startswith("_"):
        return  # skip private surface, mirroring the Python detector
    symbols[sym.key] = sym


def _extract_methods(class_name: str, body: str, symbols: dict[str, Symbol]) -> None:
    """Find method definitions at the top level of a class body."""
    i = 0
    last = 0
    while i < len(body):
        ch = body[i]
        if ch == "{":
            header = body[last:i]
            close = _matching_brace(body, i)
            if close == -1:
                break
            m = _METHOD_TAIL_RE.search(header)
            if m:
                name = m.group(1)
                if name not in _NOT_METHODS:
                    _add(
                        symbols,
                        Symbol(
                            kind="function",
                            name=f"{class_name}.{name}",
                            signature=_signature(m.group(2), m.group(3)),
                        ),
                    )
            i = close + 1
            last = i
            continue
        i += 1


def extract_symbols(source: str | None) -> dict[str, Symbol]:
    """Map of Symbol.key -> Symbol for JS/TS API surface in `source`."""
    if not source:
        return {}

    symbols: dict[str, Symbol] = {}

    # 1. Classes (and their methods), removing their bodies so top-level
    #    scans below don't re-match methods as free functions.
    stripped_parts: list[str] = []
    cursor = 0
    for m in _CLASS_RE.finditer(source):
        open_brace = source.find("{", m.start())
        close = _matching_brace(source, open_brace)
        if close == -1:
            continue
        _extract_methods(m.group(1), source[open_brace + 1 : close], symbols)
        stripped_parts.append(source[cursor : m.start()])
        cursor = close + 1
    stripped_parts.append(source[cursor:])
    stripped = "".join(stripped_parts)

    # 2. Top-level function declarations.
    for m in _FUNC_DECL_RE.finditer(stripped):
        _add(
            symbols,
            Symbol(
                kind="function",
                name=m.group(1),
                signature=_signature(m.group(2), m.group(3)),
            ),
        )

    # 3. Arrow functions bound to a name.
    for m in _ARROW_RE.finditer(stripped):
        _add(
            symbols,
            Symbol(
                kind="function",
                name=m.group(1),
                signature=_signature(m.group(2), m.group(3)),
            ),
        )

    # 4. Express-style routes.
    for m in _ROUTE_RE.finditer(stripped):
        method = m.group(1).upper()
        path = m.group(3)
        symbols[f"route {method} {path}"] = Symbol(
            kind="route",
            name=path,
            signature="",
            http_method=method,
            route_path=path,
        )

    return symbols


def detect_file_changes(
    old_source: str | None, new_source: str | None
) -> list[Change]:
    return diff_symbols(extract_symbols(old_source), extract_symbols(new_source))


def is_js(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in JS_EXTENSIONS
