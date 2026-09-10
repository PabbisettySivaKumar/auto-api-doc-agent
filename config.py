"""Central configuration for the Auto API-Doc Sync Agent.

Values come from environment variables (optionally loaded from a local
`.env` file). Nothing here is required for a dry-run: the agent falls back
to safe defaults and a deterministic draft stub when keys are absent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


@dataclass(frozen=True)
class Config:
    # --- Gemini / Google AI Studio ---
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    # Pro for reasoning-heavy drafting; Flash for cheap classification.
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # --- GitHub (personal-token / single-repo local mode) ---
    github_token: str | None = os.getenv("GITHUB_TOKEN")
    # "owner/name" of the repo to open doc PRs against (live mode only).
    github_repo: str | None = os.getenv("GITHUB_REPO")
    base_branch: str = os.getenv("BASE_BRANCH", "main")

    # --- GitHub App (Phase 2: all-repos webhook service) ---
    github_app_id: str | None = os.getenv("GITHUB_APP_ID")
    # Private key: either inline PEM or a path to the .pem file.
    github_app_private_key: str | None = os.getenv("GITHUB_APP_PRIVATE_KEY")
    github_app_private_key_path: str | None = os.getenv(
        "GITHUB_APP_PRIVATE_KEY_PATH"
    )
    # Shared secret configured on the GitHub App webhook; used to verify
    # that inbound payloads genuinely came from GitHub.
    github_webhook_secret: str | None = os.getenv("GITHUB_WEBHOOK_SECRET")

    # --- Behavior ---
    # Below this confidence the agent flags for manual review instead of
    # opening a PR (see PRD section 8 open question).
    confidence_threshold: float = float(os.getenv("CONFIDENCE_THRESHOLD", "0.6"))
    # Where dry-run output and trajectory logs are written.
    output_dir: str = os.getenv("OUTPUT_DIR", "out")

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_github(self) -> bool:
        return bool(self.github_token and self.github_repo)

    @property
    def has_github_app(self) -> bool:
        return bool(
            self.github_app_id
            and (self.github_app_private_key or self.github_app_private_key_path)
        )

    def resolve_private_key(self) -> str | None:
        """Return the App private-key PEM, from inline value or file path."""
        if self.github_app_private_key:
            return self.github_app_private_key
        if self.github_app_private_key_path:
            try:
                with open(self.github_app_private_key_path) as f:
                    return f.read()
            except OSError:
                return None
        return None


config = Config()
