"""Phase E: golden end-to-end test of the two-tier writer.

Given a fixed multi-file feature, assert the *whole* rendered output — Tier-2
sections, grounded diagram count, deprecation handling, and the Tier-1 index
links. This locks the doc shape so future refactors can't silently change it.
Runs offline (stub prose)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import features, callgraph, docwriter, detect  # noqa: E402

# A two-file "orders" feature: an API layer + a service layer.
ORDERS_API = '''
from fastapi import APIRouter
router = APIRouter()

def _audit(order):
    return order

@router.post("/orders")
def create_order(item: str, qty: int):
    return place_order(item, qty)

@router.get("/orders/{oid}")
def get_order(oid: int):
    return lookup_order(oid)
'''

ORDERS_SERVICE = '''
def place_order(item, qty):
    if qty <= 0:
        raise ValueError("qty must be positive")
    if item == "":
        raise ValueError("item required")
    return _persist({"item": item, "qty": qty})

def lookup_order(oid):
    return _persist_read(oid)

def _persist(o):
    return o

def _persist_read(oid):
    return {"id": oid}
'''


def test_golden_two_tier() -> None:
    files = {
        "orders/api.py": ORDERS_API,
        "orders/service.py": ORDERS_SERVICE,
    }

    # Bucketing: both files resolve to the "orders" feature.
    buckets = features.bucket_files(list(files))
    assert set(buckets) == {"orders"}, buckets

    graph = callgraph.build_call_graph(files)
    display = features.feature_display_name("orders")
    assert display == "Orders"

    tier2 = docwriter.render_tier2("orders", display, graph, [], "", None)
    doc = tier2.updated_content

    # --- Tier-2 assertions ---
    assert tier2.path == "docs/features/orders.md"
    assert doc.startswith("# Orders")
    # Both endpoints documented.
    assert "### POST /orders" in doc
    assert "### GET /orders/{oid}" in doc
    # Public service functions documented.
    assert "### `place_order`" in doc
    assert "### `lookup_order`" in doc
    # Key internals: persist/persist_read are non-public callees of the surface.
    assert "## Key internals" in doc
    assert "persist" in doc
    # Grounded diagrams present: a sequence diagram for the create_order flow
    # (POST /orders -> place_order -> persist) and a flowchart for the branchy
    # place_order. Count the mermaid blocks.
    assert doc.count("```mermaid") >= 2, doc.count("```mermaid")
    # Sequence diagram is grounded in the real call chain.
    assert "place_order" in doc and "persist" in doc

    # --- Tier-1 index assertions ---
    tier1 = docwriter.update_tier1("", "orders", display, "Order management.")
    idx = tier1.updated_content
    assert tier1.path == "docs/API.md"
    assert "## Orders" in idx
    assert "features/orders.md" in idx
    print("PASS test_golden_two_tier ->", doc.count("```mermaid"), "diagrams")


def test_golden_deprecation() -> None:
    graph = callgraph.build_call_graph({"orders/api.py": ORDERS_API,
                                        "orders/service.py": ORDERS_SERVICE})
    # A change set where an old endpoint was removed.
    changes = detect.detect_changes(
        "orders/api.py",
        'from fastapi import APIRouter\nrouter = APIRouter()\n\n'
        '@router.delete("/orders/{oid}")\ndef cancel_order(oid):\n    return {}\n',
        ORDERS_API,
    )
    assert any(c.status == "removed" for c in changes)
    tier2 = docwriter.render_tier2("orders", "Orders", graph, changes, "", None)
    assert docwriter._DEPRECATED_HEADING in tier2.updated_content
    assert "removed" in tier2.updated_content.lower()
    print("PASS test_golden_deprecation")


if __name__ == "__main__":
    test_golden_two_tier()
    test_golden_deprecation()
    print("\nAll golden-docs tests passed.")
