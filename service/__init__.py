"""Phase 2 — FastAPI webhook service + GitHub App integration.

Wraps the Phase 1 agent core (the `agent` package) so that a single
GitHub App installation can keep docs in sync across every repo it can
see, without adding a workflow file to each repo.
"""
