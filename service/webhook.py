"""FastAPI webhook receiver for the Auto API-Doc Sync GitHub App.

One always-on service handles every repo the App is installed on. On a
push to a repo's default branch it verifies the signature, then dispatches
the agent pipeline in the background so GitHub gets a fast 202.

Run locally:
    uvicorn service.webhook:app --reload --port 8000

Endpoints:
    GET  /          health check
    GET  /healthz   liveness probe
    POST /webhook   GitHub App webhook sink
"""

from __future__ import annotations

import logging
import os

from fastapi import BackgroundTasks, FastAPI, Header, Request, Response

from config import config
from . import security, pipeline

logger = logging.getLogger("auto-doc-agent")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Auto API-Doc Sync Agent", version="2.0")

# Render injects RENDER_GIT_COMMIT on every deploy; fall back to a generic
# env var (or "unknown") so the endpoint works on any host / locally.
DEPLOYED_COMMIT = (
    os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "unknown"
)


@app.get("/")
@app.get("/healthz")
def health() -> dict:
    return {
        "service": "auto-api-doc-sync",
        "status": "ok",
        "commit": DEPLOYED_COMMIT[:7] if DEPLOYED_COMMIT != "unknown" else "unknown",
        "github_app_configured": config.has_github_app,
        "webhook_secret_configured": bool(config.github_webhook_secret),
        "gemini_configured": config.has_gemini,
    }


def _process_push(payload: dict) -> None:
    """Background worker: run the pipeline for one push event."""
    repo = payload.get("repository", {})
    full_name = repo.get("full_name")
    default_branch = repo.get("default_branch", "main")
    installation_id = payload.get("installation", {}).get("id")
    before = payload.get("before")
    after = payload.get("after")

    try:
        result = pipeline.run_for_push(
            config,
            installation_id=installation_id,
            full_name=full_name,
            before_sha=before,
            after_sha=after,
            base_branch=default_branch,
        )
        logger.info("processed push %s -> %s", full_name, result.get("delivery", result.get("result")))
    except Exception:
        logger.exception("pipeline failed for %s", full_name)


@app.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> Response:
    body = await request.body()

    if not security.verify_signature(
        config.github_webhook_secret, body, x_hub_signature_256
    ):
        return Response(status_code=401, content="invalid signature")

    payload = await request.json()

    if x_github_event == "ping":
        return Response(status_code=200, content="pong")

    if x_github_event != "push":
        # Acknowledge other events (installation, pull_request, ...) so
        # GitHub doesn't retry; we only act on pushes for now.
        return Response(status_code=202, content=f"ignored event: {x_github_event}")

    repo = payload.get("repository", {})
    default_branch = repo.get("default_branch", "main")
    ref = payload.get("ref", "")

    if ref != f"refs/heads/{default_branch}":
        return Response(status_code=202, content="ignored: not default branch")

    if security.is_zero_sha(payload.get("before")) or security.is_zero_sha(
        payload.get("after")
    ):
        return Response(status_code=202, content="ignored: branch create/delete")

    if not payload.get("installation", {}).get("id"):
        return Response(status_code=400, content="missing installation id")

    background_tasks.add_task(_process_push, payload)
    return Response(status_code=202, content="accepted")
