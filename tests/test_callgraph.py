"""Phase B tests: call-graph extraction (agent/callgraph.py)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import callgraph  # noqa: E402

PY_APP = '''
from fastapi import FastAPI
app = FastAPI()

def read_user_from_db(user_id):
    return {"id": user_id}

def get_user_service(user_id):
    return read_user_from_db(user_id)

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return get_user_service(user_id)

@app.post("/users")
def create_user(name, role):
    if not name:
        raise ValueError("name required")
    if role == "admin" and name:
        return {"admin": True}
    for _ in range(3):
        pass
    return {"name": name}
'''


def _graph(src, path="users/api.py"):
    return callgraph.build_call_graph({path: src})


def test_python_nodes_and_routes() -> None:
    g = _graph(PY_APP)
    names = set(g.nodes)
    assert {"get_user", "create_user", "get_user_service", "read_user_from_db"} <= names
    routes = {(r.http_method, r.route_path) for r in g.routes()}
    assert ("GET", "/users/{user_id}") in routes
    assert ("POST", "/users") in routes
    print("PASS test_python_nodes_and_routes")


def test_endpoint_flow_layers() -> None:
    g = _graph(PY_APP)
    route = next(r for r in g.routes() if r.route_path == "/users/{user_id}")
    flow = [n.simple for n in callgraph.endpoint_flow(g, route)]
    # handler -> service -> data layer, grounded in real calls.
    assert flow == ["get_user", "get_user_service", "read_user_from_db"], flow
    print("PASS test_endpoint_flow_layers ->", flow)


def test_is_branchy() -> None:
    g = _graph(PY_APP)
    create = g.nodes["create_user"]   # two ifs + a bool op + a for -> branchy
    get = g.nodes["get_user"]          # straight passthrough -> not branchy
    assert callgraph.is_branchy(create)
    assert not callgraph.is_branchy(get)
    print("PASS test_is_branchy -> create:", create.branch_points,
          "get:", get.branch_points)


def test_flow_skips_unknown_and_cycles() -> None:
    src = '''
def a():
    external_lib_call()   # unresolved -> skipped
    return b()

def b():
    return a()            # cycle -> guarded
'''
    g = _graph(src, "orders/svc.py")
    flow = [n.simple for n in callgraph.endpoint_flow(g, g.nodes["a"])]
    assert flow == ["a", "b"], flow  # external call skipped, no infinite loop
    print("PASS test_flow_skips_unknown_and_cycles ->", flow)


def test_js_callgraph() -> None:
    src = """
    const express = require('express');
    const router = express.Router();

    function loadItems(q) {
      if (q) { return query(q); }
      return [];
    }
    function listItemsService(q) {
      return loadItems(q);
    }
    router.get('/items', (req, res) => {
      const data = listItemsService(req.query.q);
      res.json(data);
    });
    """
    g = callgraph.build_call_graph({"items/routes.js": src})
    assert "loadItems" in g.nodes and "listItemsService" in g.nodes
    routes = {(r.http_method, r.route_path) for r in g.routes()}
    assert ("GET", "/items") in routes
    route = next(r for r in g.routes() if r.route_path == "/items")
    flow = [n.simple for n in callgraph.endpoint_flow(g, route)]
    assert "listItemsService" in flow and "loadItems" in flow, flow
    print("PASS test_js_callgraph ->", flow)


if __name__ == "__main__":
    test_python_nodes_and_routes()
    test_endpoint_flow_layers()
    test_is_branchy()
    test_flow_skips_unknown_and_cycles()
    test_js_callgraph()
    print("\nAll call-graph tests passed.")
