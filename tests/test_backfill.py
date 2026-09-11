"""Phase F tests: whole-repo backfill + local-only guarantee. Offline."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import backfill, features, llm  # noqa: E402


def _make_old_repo() -> str:
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "users"))
    os.makedirs(os.path.join(d, "payments"))
    os.makedirs(os.path.join(d, "utils"))
    Path(d, "users", "api.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "def _save(u):\n    return u\n"
        "def create_user(name, email):\n    return _save({'name': name})\n"
        "@app.get('/users/{uid}')\n"
        "def get_user(uid: int):\n    return {}\n"
    )
    Path(d, "payments", "charge.py").write_text(
        "def charge(amount, currency):\n"
        "    if amount <= 0:\n        raise ValueError()\n"
        "    return settle(amount)\n"
        "def settle(a):\n    return a\n"
    )
    Path(d, "utils", "fmt.py").write_text("def money(x):\n    return x\n")
    Path(d, "README.md").write_text("# repo\n")  # non-code, ignored
    return d


def test_collect_and_bucket_whole_repo() -> None:
    d = _make_old_repo()
    sources = backfill.collect_source_files(d)
    assert "users/api.py" in sources and "payments/charge.py" in sources
    assert "README.md" not in sources  # non-code skipped
    buckets = features.bucket_files(list(sources))
    assert "users" in buckets and "payments" in buckets
    assert "core-shared" in buckets  # utils/ -> shared bucket
    print("PASS test_collect_and_bucket_whole_repo")


def test_run_backfill_documents_all_features() -> None:
    d = _make_old_repo()
    res = backfill.run_backfill(None, d)  # cfg=None -> stub prose, offline
    assert set(res.features_documented) >= {"users", "payments"}
    paths = {e.path for e in res.edits}
    assert "docs/API.md" in paths
    assert "docs/features/users.md" in paths
    assert "docs/features/payments.md" in paths
    print("PASS test_run_backfill_documents_all_features ->", res.features_documented)


def test_backfill_mode_never_calls_gemini() -> None:
    """Critical safety property: backfill routing must not reach Gemini."""
    calls = {"gemini": 0, "ollama": 0}

    orig_gemini = llm._gemini
    orig_ollama = llm._ollama
    llm._gemini = lambda *a, **k: calls.__setitem__("gemini", calls["gemini"] + 1) or "X"
    llm._ollama = lambda *a, **k: calls.__setitem__("ollama", calls["ollama"] + 1) or None

    class FakeCfg:
        has_gemini = True
        gemini_api_key = "k"
        gemini_model = "m"
        ollama_host = "http://localhost:11434"
        ollama_model = "q"
        source_root = ""
        backfill_symbol_cap = 200

    try:
        d = _make_old_repo()
        backfill.run_backfill(FakeCfg(), d)
        assert calls["gemini"] == 0, "backfill must NEVER call Gemini"
        assert calls["ollama"] > 0, "backfill should route to the local model"
    finally:
        llm._gemini = orig_gemini
        llm._ollama = orig_ollama
    print("PASS test_backfill_mode_never_calls_gemini ->", calls)


def test_incremental_mode_uses_gemini() -> None:
    """Counterpart: incremental routing goes to Gemini, not Ollama."""
    calls = {"gemini": 0, "ollama": 0}
    orig_gemini, orig_ollama = llm._gemini, llm._ollama
    llm._gemini = lambda *a, **k: calls.__setitem__("gemini", calls["gemini"] + 1) or "Y"
    llm._ollama = lambda *a, **k: calls.__setitem__("ollama", calls["ollama"] + 1) or "Z"

    class FakeCfg:
        has_gemini = True
        gemini_api_key = "k"
        gemini_model = "m"

    try:
        out = llm.generate_text(FakeCfg(), "hi", mode=llm.INCREMENTAL)
        assert out == "Y" and calls["gemini"] == 1 and calls["ollama"] == 0
    finally:
        llm._gemini, llm._ollama = orig_gemini, orig_ollama
    print("PASS test_incremental_mode_uses_gemini ->", calls)


def test_symbol_cap_guard() -> None:
    d = _make_old_repo()

    class CappedCfg:
        has_gemini = False
        source_root = ""
        backfill_symbol_cap = 1  # force the cap immediately

    res = backfill.run_backfill(CappedCfg(), d)
    assert res.capped, "expected the symbol cap to trip"
    assert res.edits, "still produces structural docs past the cap"
    print("PASS test_symbol_cap_guard -> symbols:", res.symbols)


if __name__ == "__main__":
    test_collect_and_bucket_whole_repo()
    test_run_backfill_documents_all_features()
    test_backfill_mode_never_calls_gemini()
    test_incremental_mode_uses_gemini()
    test_symbol_cap_guard()
    print("\nAll backfill tests passed.")
