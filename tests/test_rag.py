"""RAG retrieval checks. Uses the offline (no-key) embedder so results are
deterministic and require no network."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import rag, detect  # noqa: E402
from agent.retrieve import DocFile  # noqa: E402


def _changes_add_role() -> list[detect.Change]:
    before = (
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        '@app.post("/users")\n'
        "def create_user(name: str, email: str):\n    return {}\n"
    )
    after = before.replace(
        "def create_user(name: str, email: str):",
        "def create_user(name: str, email: str, role: str):",
    )
    return detect.detect_file_changes(before, after)


def _corpus() -> list[DocFile]:
    return [
        DocFile("docs/payments.md", "markdown",
                "# Payments\n\nCharge a card via POST /charges with an amount."),
        DocFile("docs/users.md", "markdown",
                "# Users API\n\n## POST /users\n\nThe create_user endpoint "
                "creates a user. Params: name, email."),
        DocFile("docs/auth.md", "markdown",
                "# Auth\n\nLogin via POST /login with username and password."),
        DocFile("docs/faq.md", "markdown",
                "# FAQ\n\nGeneral questions about billing and refunds."),
        DocFile("docs/webhooks.md", "markdown",
                "# Webhooks\n\nSubscribe to events like order.created."),
    ]


def test_offline_embedder_deterministic() -> None:
    e = rag.Embedder(cfg=None)
    v1 = e.embed(["POST /users create_user"])[0]
    v2 = e.embed(["POST /users create_user"])[0]
    assert v1 == v2
    assert not e.used_model
    # normalized
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-6
    print("PASS test_offline_embedder_deterministic")


def test_chunking_by_heading() -> None:
    doc = "# A\n\ntext a\n\n## B\n\ntext b\n\n## C\n\ntext c"
    chunks = rag.chunk_doc(doc)
    assert len(chunks) == 3
    assert chunks[0].startswith("# A")
    print("PASS test_chunking_by_heading")


def test_rag_ranks_relevant_doc_first() -> None:
    changes = _changes_add_role()
    assert changes, "expected a detected change"
    matches = rag.relevant_docs_over(_corpus(), changes, cfg=None, k=3)
    assert matches, "expected at least one match"
    assert matches[0].doc.path == "docs/users.md", (
        f"expected users.md first, got {[m.doc.path for m in matches]}"
    )
    # Scores are descending.
    scores = [m.score for m in matches]
    assert scores == sorted(scores, reverse=True)
    print("PASS test_rag_ranks_relevant_doc_first ->",
          [(m.doc.path, m.score) for m in matches])


def test_empty_corpus() -> None:
    assert rag.relevant_docs_over([], _changes_add_role(), cfg=None) == []
    print("PASS test_empty_corpus")


if __name__ == "__main__":
    test_offline_embedder_deterministic()
    test_chunking_by_heading()
    test_rag_ranks_relevant_doc_first()
    test_empty_corpus()
    print("\nAll RAG tests passed.")
