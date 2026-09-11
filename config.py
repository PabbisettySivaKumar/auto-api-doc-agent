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

    # --- RAG (Phase 3: large / scattered / external docs) ---
    gemini_embed_model: str = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
    # Directory of docs living outside the repo (exported Confluence/Notion,
    # etc.). If set, RAG retrieval is used.
    external_docs_dir: str | None = os.getenv("EXTERNAL_DOCS_DIR")
    # Auto-switch to RAG once the in-repo doc corpus reaches this many files.
    rag_min_docs: int = int(os.getenv("RAG_MIN_DOCS", "25"))
    rag_top_k: int = int(os.getenv("RAG_TOP_K", "4"))
    rag_force: bool = os.getenv("RAG_FORCE", "").lower() in {"1", "true", "yes"}

    # --- Layered docs (Phase D) ---
    # "single": current behavior (push -> one API.md sync PR).
    # "layered": also handle pull_request events, generating two-tier feature
    #   docs committed onto the feature branch. Kept off by default until
    #   proven on one repo.
    doc_mode: str = os.getenv("DOC_MODE", "single")
    # Directory prefix stripped before resolving a feature (e.g. "src").
    source_root: str = os.getenv("SOURCE_ROOT", "")

    # --- Backfill / local model (Phase F) ---
    # Old repos without docs are documented via a LOCAL model only, never
    # Gemini (see agent/llm.py mode routing).
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
    # Cap on LLM-described symbols per backfill run (cost/scope guard).
    backfill_symbol_cap: int = int(os.getenv("BACKFILL_SYMBOL_CAP", "200"))

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
