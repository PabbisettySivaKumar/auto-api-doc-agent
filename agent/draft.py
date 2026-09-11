"""Draft targeted documentation edits for the detected API changes.

Uses the Gemini API (Google AI Studio) when a key is configured, and
falls back to a deterministic stub otherwise so the full pipeline runs
end-to-end with zero setup during a dry-run. The stub is clearly marked
as such — it is not a substitute for the model, only a wiring harness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .detect import Change
from .retrieve import DocMatch


@dataclass
class DocEdit:
    path: str
    kind: str
    updated_content: str
    rationale: str


@dataclass
class DraftResult:
    edits: list[DocEdit] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    used_model: bool = False
    # Human-readable provider label for the PR body. When empty, the body
    # falls back to "gemini"/"stub" from `used_model`.
    provider: str = ""


_SYSTEM = """You are a documentation-sync agent. You are given a set of
structural API changes detected in Python source, and the current content
of documentation files. Produce the smallest possible edits to each doc so
it accurately reflects the new API. Do NOT rewrite whole documents. Keep
tone, structure, and formatting identical to the original. If a doc needs
no change, omit it from your output."""


def _changes_block(changes: list[Change]) -> str:
    return "\n".join(c.describe() for c in changes)


def _build_prompt(changes: list[Change], matches: list[DocMatch]) -> str:
    docs_block = "\n\n".join(
        f"### FILE: {m.doc.path} ({m.doc.kind})\n"
        f"<<<CONTENT\n{m.doc.content}\nCONTENT"
        for m in matches
    )
    return (
        f"{_SYSTEM}\n\n"
        f"## Detected API changes\n{_changes_block(changes)}\n\n"
        f"## Current documentation\n{docs_block}\n\n"
        "## Output\n"
        "Return JSON only, matching this shape:\n"
        "{\n"
        '  "summary": "one-paragraph explanation of what you changed and why",\n'
        '  "confidence": 0.0-1.0,\n'
        '  "edits": [\n'
        '    {"path": "<file path>", "updated_content": "<full new file content>",\n'
        '     "rationale": "<what changed in this file>"}\n'
        "  ]\n"
        "}\n"
        "Only include files in `edits` that actually need to change."
    )


def _draft_with_gemini(
    changes: list[Change], matches: list[DocMatch], cfg
) -> DraftResult | None:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    try:
        client = genai.Client(api_key=cfg.gemini_api_key)
        resp = client.models.generate_content(
            model=cfg.gemini_model,
            contents=_build_prompt(changes, matches),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        data = json.loads(resp.text)
    except Exception as e:  # network / quota / parse — fall back to stub
        print(f"  [draft] Gemini call failed ({e}); using stub fallback.")
        return None

    by_path = {m.doc.path: m for m in matches}
    edits: list[DocEdit] = []
    for e in data.get("edits", []):
        m = by_path.get(e.get("path"))
        if m is None:
            continue
        edits.append(
            DocEdit(
                path=e["path"],
                kind=m.doc.kind,
                updated_content=e["updated_content"],
                rationale=e.get("rationale", ""),
            )
        )
    return DraftResult(
        edits=edits,
        summary=data.get("summary", ""),
        confidence=float(data.get("confidence", 0.0)),
        used_model=True,
    )


def _draft_stub(changes: list[Change], matches: list[DocMatch]) -> DraftResult:
    """Deterministic fallback: append a clearly-marked review note.

    This proves the pipeline (detect -> retrieve -> draft -> PR) without a
    model. It does not attempt real rewrites — it flags each relevant doc
    with the API changes an editor (or Gemini) should reconcile.
    """
    note_lines = ["", "<!-- auto-api-doc-agent: STUB DRAFT (no GEMINI_API_KEY set) -->"]
    note_lines.append("> **API changes detected that may affect this document:**")
    for c in changes:
        note_lines.append(f"> - {c.describe().splitlines()[0]}")
    note = "\n".join(note_lines) + "\n"

    edits = [
        DocEdit(
            path=m.doc.path,
            kind=m.doc.kind,
            updated_content=m.doc.content.rstrip() + "\n" + note,
            rationale=(
                f"Doc references {', '.join(m.matched_terms)}; flagged the "
                f"{len(changes)} detected API change(s) for reconciliation."
            ),
        )
        for m in matches
    ]
    return DraftResult(
        edits=edits,
        summary=(
            f"STUB draft: flagged {len(edits)} doc file(s) with {len(changes)} "
            "detected API change(s). Set GEMINI_API_KEY for real edits."
        ),
        # Deliberately low so it trips the manual-review threshold.
        confidence=0.3,
        used_model=False,
    )


def draft_edits(
    changes: list[Change], matches: list[DocMatch], cfg
) -> DraftResult:
    if not changes or not matches:
        return DraftResult(summary="No relevant docs to update.", confidence=1.0)
    if cfg.has_gemini:
        result = _draft_with_gemini(changes, matches, cfg)
        if result is not None:
            return result
    return _draft_stub(changes, matches)
