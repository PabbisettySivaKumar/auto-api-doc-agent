"""Phase 2 checks: signature verification and webhook dispatch.

Signature tests use only the stdlib. The endpoint test runs only if
FastAPI is installed and stubs out the pipeline so nothing touches
GitHub.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service import security  # noqa: E402

SECRET = "test-secret"


def test_signature_roundtrip() -> None:
    body = b'{"hello":"world"}'
    sig = security.compute_signature(SECRET, body)
    assert security.verify_signature(SECRET, body, sig)
    assert not security.verify_signature(SECRET, body, "sha256=deadbeef")
    assert not security.verify_signature(SECRET, body + b"x", sig)
    assert not security.verify_signature(None, body, sig)  # no secret -> reject
    assert not security.verify_signature(SECRET, body, None)  # no header -> reject
    print("PASS test_signature_roundtrip")


def test_zero_sha() -> None:
    assert security.is_zero_sha("0" * 40)
    assert security.is_zero_sha(None)
    assert not security.is_zero_sha("abc123")
    print("PASS test_zero_sha")


def test_webhook_endpoint() -> None:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("SKIP test_webhook_endpoint (fastapi not installed)")
        return

    # Configure a secret before importing the app, and stub the pipeline.
    import config as config_mod

    object.__setattr__(config_mod.config, "github_webhook_secret", SECRET)

    from service import pipeline

    calls = []
    pipeline.run_for_push = lambda *a, **k: calls.append((a, k)) or {"delivery": "stub"}

    from service.webhook import app

    client = TestClient(app)

    # Health check.
    assert client.get("/").status_code == 200

    payload = {
        "ref": "refs/heads/main",
        "before": "1" * 40,
        "after": "2" * 40,
        "repository": {"full_name": "octo/repo", "default_branch": "main"},
        "installation": {"id": 123},
    }
    body = json.dumps(payload).encode()
    good_sig = security.compute_signature(SECRET, body)

    # Bad signature -> 401.
    r = client.post(
        "/webhook",
        content=body,
        headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=bad"},
    )
    assert r.status_code == 401, r.status_code

    # Ping -> pong.
    r = client.post(
        "/webhook",
        content=body,
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": good_sig},
    )
    assert r.status_code == 200 and r.text == "pong"

    # Valid push -> 202 accepted and pipeline invoked (background task runs
    # synchronously under TestClient).
    r = client.post(
        "/webhook",
        content=body,
        headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": good_sig},
    )
    assert r.status_code == 202, (r.status_code, r.text)
    assert len(calls) == 1, calls
    assert calls[0][1]["full_name"] == "octo/repo"

    # Push to a non-default branch -> ignored, pipeline not called again.
    side = dict(payload, ref="refs/heads/feature")
    sbody = json.dumps(side).encode()
    r = client.post(
        "/webhook",
        content=sbody,
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": security.compute_signature(SECRET, sbody),
        },
    )
    assert r.status_code == 202 and "not default branch" in r.text
    assert len(calls) == 1

    print("PASS test_webhook_endpoint")


if __name__ == "__main__":
    test_signature_roundtrip()
    test_zero_sha()
    test_webhook_endpoint()
    print("\nAll service tests passed.")
