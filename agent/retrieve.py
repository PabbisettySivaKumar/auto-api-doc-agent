"""Locate documentation relevant to the changed API symbols.

Phase 1 keeps this deliberately simple (PRD section 5.5: "small/in-repo
docs — direct file read, no vector DB"). We scan the repo for Markdown
files and OpenAPI specs, then rank doc sections by how many changed
symbols / route paths they mention. RAG is a later phase.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .detect import Change

_MARKDOWN_EXTS = {".md", ".mdx"}
_OPENAPI_HINTS = ("openapi", "swagger")
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "out"}


@dataclass
class DocFile:
    path: str
    kind: str  # "markdown" | "openapi"
    content: str


@dataclass
class DocMatch:
    doc: DocFile
    score: int
    matched_terms: list[str] = field(default_factory=list)


def _terms_for_change(change: Change) -> list[str]:
    """Search terms that a doc section would use to reference this symbol."""
    terms: list[str] = []
    sym = change.after or change.before
    if sym is None:
        return terms
    if sym.route_path and sym.route_path != "?":
        terms.append(sym.route_path)
    # Bare function/method name (last path component).
    terms.append(sym.name.split(".")[-1])
    return [t for t in terms if t]


def find_docs(repo_path: str) -> list[DocFile]:
    """All Markdown + OpenAPI docs in the repo."""
    docs: list[DocFile] = []
    root = Path(repo_path)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            ext = p.suffix.lower()
            rel = str(p.relative_to(root))
            try:
                if ext in _MARKDOWN_EXTS:
                    docs.append(DocFile(rel, "markdown", p.read_text()))
                elif ext in {".yaml", ".yml", ".json"} and any(
                    h in fn.lower() for h in _OPENAPI_HINTS
                ):
                    docs.append(DocFile(rel, "openapi", p.read_text()))
            except (UnicodeDecodeError, OSError):
                continue
    return docs


def relevant_docs(
    repo_path: str, changes: list[Change]
) -> list[DocMatch]:
    """Rank docs by how many changed symbols they reference."""
    terms: list[str] = []
    for c in changes:
        terms.extend(_terms_for_change(c))
    terms = list(dict.fromkeys(terms))  # de-dup, keep order

    matches: list[DocMatch] = []
    for doc in find_docs(repo_path):
        hay = doc.content.lower()
        hit = [t for t in terms if t.lower() in hay]
        if hit:
            matches.append(DocMatch(doc=doc, score=len(hit), matched_terms=hit))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches
