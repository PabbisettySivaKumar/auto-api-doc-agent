"""Lightweight RAG for large / scattered / external docs (PRD Phase 3).

When docs are a few files in-repo, `retrieve.relevant_docs` (substring
matching) is enough — the PRD is explicit about not adding a vector DB
before you need one. This module is the "need one" path: when docs are
numerous or live outside the repo (exported Confluence/Notion Markdown,
etc.), we embed doc chunks and retrieve by semantic similarity.

Design choices to stay zero-cost and deployable on a small free instance:

* Embeddings via the Gemini embedding model when a key is set, with a
  deterministic **offline** fallback (hashed bag-of-tokens) so tests and
  dry-runs are reproducible with no key — mirroring the draft-stub pattern.
* A pure-Python cosine vector store (no numpy / Chroma / LanceDB). The
  `VectorStore` interface is small on purpose: swapping in Chroma or
  LanceDB later is a single-class change, nothing else moves.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field

from .detect import Change
from .retrieve import DocFile, DocMatch

_EMBED_DIM = 256
_TOKEN_RE = re.compile(r"[A-Za-z0-9_/{}.-]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # inputs are L2-normalized


class Embedder:
    """Embeds text, preferring Gemini, falling back to a hashed embedding."""

    def __init__(self, cfg=None):
        self.cfg = cfg
        self.used_model = False

    def _offline(self, text: str) -> list[float]:
        vec = [0.0] * _EMBED_DIM
        for tok in _tokenize(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % _EMBED_DIM] += 1.0
        return _l2_normalize(vec)

    def _gemini(self, texts: list[str]) -> list[list[float]] | None:
        try:
            from google import genai
        except ImportError:
            return None
        try:
            client = genai.Client(api_key=self.cfg.gemini_api_key)
            model = getattr(self.cfg, "gemini_embed_model", "gemini-embedding-001")
            resp = client.models.embed_content(model=model, contents=texts)
            vecs = [list(e.values) for e in resp.embeddings]
            return [_l2_normalize(v) for v in vecs]
        except Exception as e:  # network / quota — fall back offline
            print(f"  [rag] Gemini embedding failed ({e}); using offline embedder.")
            return None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.cfg is not None and getattr(self.cfg, "has_gemini", False):
            vecs = self._gemini(texts)
            if vecs is not None:
                self.used_model = True
                return vecs
        return [self._offline(t) for t in texts]


def chunk_doc(content: str, max_chars: int = 800) -> list[str]:
    """Split a doc into chunks, preferring Markdown heading boundaries."""
    if not content.strip():
        return []
    # Split on headings while keeping the heading with its section.
    parts = re.split(r"(?m)^(?=#{1,6}\s)", content)
    chunks: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_chars:
            chunks.append(part)
        else:
            for i in range(0, len(part), max_chars):
                chunks.append(part[i : i + max_chars])
    return chunks or [content.strip()]


@dataclass
class _Entry:
    doc_idx: int
    text: str
    vector: list[float]


@dataclass
class RagIndex:
    docs: list[DocFile]
    entries: list[_Entry] = field(default_factory=list)
    used_model: bool = False


def build_index(docs: list[DocFile], embedder: Embedder) -> RagIndex:
    index = RagIndex(docs=docs)
    chunk_texts: list[str] = []
    chunk_owner: list[int] = []
    for i, doc in enumerate(docs):
        for chunk in chunk_doc(doc.content):
            chunk_texts.append(chunk)
            chunk_owner.append(i)
    if chunk_texts:
        vectors = embedder.embed(chunk_texts)
        index.entries = [
            _Entry(doc_idx=chunk_owner[j], text=chunk_texts[j], vector=vectors[j])
            for j in range(len(chunk_texts))
        ]
    index.used_model = embedder.used_model
    return index


def query_index(
    index: RagIndex, query_text: str, embedder: Embedder, k: int = 4
) -> list[DocMatch]:
    if not index.entries:
        return []
    qvec = embedder.embed([query_text])[0]

    # Best chunk score per doc.
    best: dict[int, tuple[float, str]] = {}
    for e in index.entries:
        score = cosine(qvec, e.vector)
        cur = best.get(e.doc_idx)
        if cur is None or score > cur[0]:
            first_line = e.text.splitlines()[0][:80] if e.text else ""
            best[e.doc_idx] = (score, first_line)

    ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:k]
    matches: list[DocMatch] = []
    for doc_idx, (score, snippet) in ranked:
        if score <= 0:
            continue
        matches.append(
            DocMatch(
                doc=index.docs[doc_idx],
                score=round(score * 100),
                matched_terms=[snippet] if snippet else [],
            )
        )
    return matches


def _query_from_changes(changes: list[Change]) -> str:
    terms: list[str] = []
    for c in changes:
        sym = c.after or c.before
        if sym is None:
            continue
        if sym.route_path and sym.route_path != "?":
            terms.append(sym.route_path)
        terms.append(sym.name)
        terms.append(c.describe().splitlines()[0])
    return "  ".join(terms)


def relevant_docs_over(
    docs: list[DocFile], changes: list[Change], cfg=None, k: int = 4
) -> list[DocMatch]:
    """Full RAG retrieval over an explicit doc set. DocMatch-compatible."""
    embedder = Embedder(cfg)
    index = build_index(docs, embedder)
    return query_index(index, _query_from_changes(changes), embedder, k=k)
