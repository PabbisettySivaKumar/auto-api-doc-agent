"""Unit checks for the JS/TS heuristic detector (agent/detect_js.py)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import detect, detect_js  # noqa: E402


def _keys(source: str) -> set[str]:
    return set(detect_js.extract_symbols(source).keys())


def test_extracts_functions_arrows_routes() -> None:
    src = """
    import express from 'express';
    const app = express();

    export function getUser(id) { return {}; }
    export const makeUser = async (name, email) => ({ name, email });
    app.post('/users', (req, res) => res.json({}));
    function _internal(x) { return x; }   // private -> skipped
    """
    keys = _keys(src)
    assert "func getUser" in keys
    assert "func makeUser" in keys
    assert "route POST /users" in keys
    assert "func _internal" not in keys, "private function must be skipped"
    print("PASS test_extracts_functions_arrows_routes")


def test_class_methods_not_double_counted() -> None:
    src = """
    class API {
      list(page) {
        if (page) { return []; }   // nested block must not be a method
        return [];
      }
      create(name, email) { return {}; }
    }
    """
    keys = _keys(src)
    assert "func API.list" in keys
    assert "func API.create" in keys
    # 'if' must not be picked up as a method.
    assert not any(k.endswith(".if") for k in keys)
    print("PASS test_class_methods_not_double_counted")


def test_signature_change_detected() -> None:
    before = "export function f(a: number): number { return a; }"
    after = "export function f(a: number, b: number): number { return a + b; }"
    changes = detect_js.detect_file_changes(before, after)
    assert {(c.status, c.key) for c in changes} == {("changed", "func f")}
    print("PASS test_signature_change_detected")


def test_dispatcher_routes_by_extension() -> None:
    js = "export function g(x) { return x; }"
    assert detect.detect_changes("src/g.ts", None, js)  # detected as added
    assert detect.detect_changes("README.md", None, "# hi") == []  # unsupported
    print("PASS test_dispatcher_routes_by_extension")


if __name__ == "__main__":
    test_extracts_functions_arrows_routes()
    test_class_methods_not_double_counted()
    test_signature_change_detected()
    test_dispatcher_routes_by_extension()
    print("\nAll JS/TS detector tests passed.")
