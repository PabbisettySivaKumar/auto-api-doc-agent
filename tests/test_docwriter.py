"""Phase C tests: two-tier doc writer (agent/docwriter.py). Offline/stub."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import docwriter, callgraph, detect  # noqa: E402

FEATURE_SRC = '''
from fastapi import FastAPI
app = FastAPI()

def _read_user(user_id):
    return {"id": user_id}

def get_user_service(user_id):
    return _read_user(user_id)

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return get_user_service(user_id)

def admin_handler(req):
    return {}

def guest_handler(req):
    return {}

def user_handler(req):
    return {}

def route_request(req):
    if req.get("admin"):
        return admin_handler(req)
    if req.get("guest"):
        return guest_handler(req)
    return user_handler(req)
'''


def _graph():
    return callgraph.build_call_graph({"users/api.py": FEATURE_SRC})


def test_validate_mermaid() -> None:
    assert docwriter.validate_mermaid("sequenceDiagram\n  A->>B: x")
    assert docwriter.validate_mermaid("flowchart TD\n  a --> b")
    assert not docwriter.validate_mermaid("")
    assert not docwriter.validate_mermaid("not a diagram")
    assert not docwriter.validate_mermaid("sequenceDiagram")  # no messages
    print("PASS test_validate_mermaid")


def test_sequence_diagram_grounded() -> None:
    g = _graph()
    route = next(r for r in g.routes() if r.route_path == "/users/{user_id}")
    flow = callgraph.endpoint_flow(g, route)
    mm = docwriter.sequence_diagram(flow)
    assert mm and docwriter.validate_mermaid(mm)
    # grounded: the real downstream calls appear as messages
    assert "get_user_service" in mm and "read_user" in mm
    print("PASS test_sequence_diagram_grounded")


def test_flowchart_only_for_branchy() -> None:
    g = _graph()
    diagrams = docwriter.render_diagrams(g)
    titles = [d.title for d in diagrams]
    # endpoint gets a sequence diagram
    assert any("/users/{user_id}" in t for t in titles), titles
    # route_request branches AND calls -> flowchart; get_user_service (linear) -> none
    assert any("route_request" in t for t in titles), titles
    assert not any("get_user_service" in t for t in titles), titles
    for d in diagrams:
        assert docwriter.validate_mermaid(d.mermaid)
    print("PASS test_flowchart_only_for_branchy ->", titles)


def test_tier2_structure_and_diagrams() -> None:
    g = _graph()
    edit = docwriter.render_tier2("users", "Users", g, changes=[], cfg=None)
    doc = edit.updated_content
    assert edit.path == "docs/features/users.md"
    assert doc.startswith("# Users")
    assert "## Endpoints" in doc and "GET /users/{user_id}" in doc
    assert "## Functions" in doc
    assert "## Key internals" in doc and "read_user" in doc  # one level down
    assert "```mermaid" in doc
    print("PASS test_tier2_structure_and_diagrams")


def test_tier2_marks_removed_as_deprecated() -> None:
    g = _graph()
    # Simulate a change set where an old endpoint was removed.
    changes = detect.detect_changes(
        "users/api.py",
        'from fastapi import FastAPI\napp = FastAPI()\n\n'
        '@app.delete("/users/{user_id}")\ndef delete_user(user_id):\n    return {}\n',
        FEATURE_SRC,
    )
    removed = [c for c in changes if c.status == "removed"]
    assert removed, "expected a removed symbol in the fixture"
    edit = docwriter.render_tier2("users", "Users", g, changes=changes, cfg=None)
    assert docwriter._DEPRECATED_HEADING in edit.updated_content
    assert "removed" in edit.updated_content.lower()
    print("PASS test_tier2_marks_removed_as_deprecated")


def test_tier2_carries_forward_deprecations() -> None:
    g = _graph()
    existing = (
        "# Users\n\n## Deprecated / Removed\n\n"
        "- ~~OLD /legacy~~ (removed)\n"
    )
    edit = docwriter.render_tier2(
        "users", "Users", g, changes=[], existing_doc=existing, cfg=None
    )
    assert "OLD /legacy" in edit.updated_content  # prior deprecation preserved
    print("PASS test_tier2_carries_forward_deprecations")


def test_tier1_upsert_idempotent() -> None:
    e1 = docwriter.update_tier1("", "users", "Users", "User management.")
    assert e1.path == "docs/API.md"
    assert "## Users" in e1.updated_content
    assert "features/users.md" in e1.updated_content

    # Add a second feature.
    e2 = docwriter.update_tier1(e1.updated_content, "payments", "Payments", "Billing.")
    assert "## Users" in e2.updated_content and "## Payments" in e2.updated_content

    # Re-updating Users must not duplicate the section.
    e3 = docwriter.update_tier1(e2.updated_content, "users", "Users", "Updated summary.")
    assert e3.updated_content.count("## Users") == 1
    assert "Updated summary." in e3.updated_content
    assert "## Payments" in e3.updated_content  # other feature preserved
    print("PASS test_tier1_upsert_idempotent")


if __name__ == "__main__":
    test_validate_mermaid()
    test_sequence_diagram_grounded()
    test_flowchart_only_for_branchy()
    test_tier2_structure_and_diagrams()
    test_tier2_marks_removed_as_deprecated()
    test_tier2_carries_forward_deprecations()
    test_tier1_upsert_idempotent()
    print("\nAll doc-writer tests passed.")
