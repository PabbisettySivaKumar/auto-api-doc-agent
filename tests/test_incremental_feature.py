"""Regression test for the destructive-regeneration bug found in the live
incremental test: the PR pipeline must build a feature's call graph from ALL
files in the feature, not just the changed file, so regenerating the Tier-2
doc doesn't wipe endpoints/functions defined in the feature's other files."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service import pipeline  # noqa: E402
from agent import callgraph, docwriter  # noqa: E402


def _make_feature_repo() -> str:
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "app", "routes"))
    # The CHANGED file in this PR.
    Path(d, "app", "routes", "health.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "@router.get('/health')\n"
        "def health_check(verbose: bool = False):\n    return {}\n"
    )
    # An UNCHANGED file in the SAME feature — must NOT be wiped from docs.
    Path(d, "app", "routes", "chat.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "@router.post('/chat')\n"
        "def chat(message: str):\n    return {}\n"
    )
    return d


def test_feature_sources_reads_whole_feature() -> None:
    d = _make_feature_repo()
    srcs = pipeline._feature_sources(d, "app", "")
    assert "app/routes/health.py" in srcs
    assert "app/routes/chat.py" in srcs, "unchanged feature file must be included"
    print("PASS test_feature_sources_reads_whole_feature ->", sorted(srcs))


def test_regenerated_doc_keeps_all_endpoints() -> None:
    d = _make_feature_repo()
    srcs = pipeline._feature_sources(d, "app", "")
    graph = callgraph.build_call_graph(srcs)
    doc = docwriter.render_tier2("app", "App", graph, [], "", None).updated_content
    # Both endpoints present — the changed one AND the untouched one.
    assert "GET /health" in doc, doc
    assert "POST /chat" in doc, "unchanged endpoint was wiped — the bug!"
    print("PASS test_regenerated_doc_keeps_all_endpoints")


if __name__ == "__main__":
    test_feature_sources_reads_whole_feature()
    test_regenerated_doc_keeps_all_endpoints()
    print("\nAll incremental-feature tests passed.")
