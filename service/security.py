"""Webhook payload verification (pure stdlib, independently testable).

GitHub signs each webhook body with HMAC-SHA256 keyed by the App's webhook
secret and sends it in the `X-Hub-Signature-256` header as
`sha256=<hexdigest>`. We recompute and compare in constant time.
"""

from __future__ import annotations

import hashlib
import hmac


def compute_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str | None, body: bytes, header: str | None) -> bool:
    """True iff `header` is a valid signature of `body` under `secret`.

    If no secret is configured we cannot verify — return False so the
    caller rejects the request rather than trusting it blindly.
    """
    if not secret or not header:
        return False
    expected = compute_signature(secret, body)
    return hmac.compare_digest(expected, header)


_ZERO_SHA = "0" * 40


def is_zero_sha(sha: str | None) -> bool:
    """A push `before`/`after` of all zeros means branch create/delete."""
    return not sha or sha == _ZERO_SHA
