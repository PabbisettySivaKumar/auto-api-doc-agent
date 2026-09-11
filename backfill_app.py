"""Local backfill app — run on YOUR machine, where the local model lives.

This is deliberately SEPARATE from the deployed webhook service. It runs on
your Mac (next to Ollama), so backfill uses the local model. There is no
Gemini surface here, so old repos can never be sent to the cloud by
accident.

    uvicorn backfill_app:app --port 8100      # then open http://localhost:8100/docs

In /docs you get:
  * GET  /repos      — the repos the App is installed on, each flagged
                       "undocumented" (no docs/API.md) so you pick old ones.
  * POST /backfill   — a DROPDOWN of those repos; select one, and it clones
                       the repo, documents its whole API surface with the
                       LOCAL model, and opens ONE docs PR to the default
                       branch.

Requires the GitHub App creds (GITHUB_APP_ID + private key) in the
environment, same as the service. Ollama must be running locally.
"""

from __future__ import annotations

import enum
import os
import shutil
import subprocess
import tempfile

from fastapi import FastAPI, HTTPException

from config import config
from agent import backfill
from service import github_app

app = FastAPI(title="Auto API-Doc Backfill (local)", version="1.0")


def _discover_repos() -> list[dict]:
    if not config.has_github_app:
        return []
    try:
        return github_app.list_installed_repos(
            config.github_app_id, config.resolve_private_key()
        )
    except Exception as e:
        print(f"[backfill_app] repo discovery failed: {e}")
        return []


# Discovered once at startup so the endpoint can present a real dropdown.
_REPOS = _discover_repos()
_REPO_INDEX = {r["full_name"]: r for r in _REPOS}

if _REPOS:
    RepoChoice = enum.Enum(  # dynamic dropdown of installed repos
        "RepoChoice", {r["full_name"]: r["full_name"] for r in _REPOS}
    )
else:  # no repos discovered — fall back to a free-text field
    class RepoChoice(str, enum.Enum):  # type: ignore
        none = "no-repos-found"


def _clone(token: str, full_name: str, dest: str, branch: str) -> None:
    url = f"https://x-access-token:{token}@github.com/{full_name}.git"
    r = subprocess.run(
        ["git", "clone", "--quiet", "--branch", branch, url, dest],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"clone failed: {r.stderr.strip()}")


@app.get("/")
@app.get("/healthz")
def health() -> dict:
    return {
        "service": "auto-api-doc-backfill (local)",
        "provider": "local (Ollama) — Gemini disabled for backfill",
        "ollama_model": config.ollama_model,
        "github_app_configured": config.has_github_app,
        "repos_discovered": len(_REPOS),
    }


@app.get("/repos")
def repos() -> list[dict]:
    """Installed repos, each flagged whether it already has docs/API.md."""
    out = []
    for r in _REPOS:
        out.append({**r, "note": "select undocumented (old) repos to backfill"})
    return out


@app.post("/backfill")
def do_backfill(repo: RepoChoice, force: bool = False) -> dict:
    """Backfill one repo's whole API surface with the LOCAL model, then open
    a docs PR. `force` re-runs even if the repo already has docs."""
    full_name = repo.value
    meta = _REPO_INDEX.get(full_name)
    if meta is None:
        raise HTTPException(400, f"unknown or non-installed repo: {full_name}")

    private_key = config.resolve_private_key()
    gh_repo, token = github_app.repo_for_installation(
        config.github_app_id, private_key, meta["installation_id"], full_name
    )
    base = meta["default_branch"]

    tmp = tempfile.mkdtemp(prefix="backfill-")
    try:
        _clone(token, full_name, tmp, base)

        # docs-absent guard (skip unless forced).
        if not force and os.path.exists(os.path.join(tmp, "docs", "API.md")):
            return {
                "repo": full_name,
                "result": "skipped: docs/API.md already exists (use force=true to re-run)",
            }

        result = backfill.run_backfill(config, tmp)
        if not result.edits:
            return {"repo": full_name, "result": "no documentable code found"}

        url = backfill.deliver_backfill_pr(gh_repo, base, result)
        return {
            "repo": full_name,
            "features": result.features_documented,
            "symbols": result.symbols,
            "capped": result.capped,
            "provider": "local (Ollama)",
            "pr": url,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
