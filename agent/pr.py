"""Deliver drafted edits — always as a PR, never a commit to main.

In dry-run mode (default when no GitHub token/repo is configured) the
proposed file contents and PR body are written under `out/` so the run is
fully inspectable without touching any remote. Live mode uses PyGithub to
create a branch, commit the edits, and open a PR with a summary comment
(PRD section 5.7).
"""

from __future__ import annotations

import time
from pathlib import Path

from .draft import DraftResult
from .selfcheck import CheckResult


def _pr_body(draft: DraftResult, check: CheckResult, confidence: float) -> str:
    lines = [
        "## Auto API-Doc Sync",
        "",
        draft.summary or "Proposed documentation updates for recent API changes.",
        "",
        f"**Confidence:** {confidence:.2f}  "
        f"(model: {'gemini' if draft.used_model else 'stub'})",
        "",
        "### Files updated",
    ]
    for e in draft.edits:
        lines.append(f"- `{e.path}` — {e.rationale}")
    if check.warnings:
        lines += ["", "### Self-check warnings"]
        lines += [f"- ⚠️ {w}" for w in check.warnings]
    lines += ["", "_Opened by the Auto API-Doc Sync Agent. Human review required._"]
    return "\n".join(lines)


def deliver_dry_run(
    output_dir: str, draft: DraftResult, check: CheckResult, confidence: float
) -> str:
    """Write proposed edits + PR body to `out/proposed/` and return the dir."""
    base = Path(output_dir) / "proposed"
    base.mkdir(parents=True, exist_ok=True)

    for e in draft.edits:
        dest = base / e.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(e.updated_content)

    (base / "_PR_BODY.md").write_text(_pr_body(draft, check, confidence))
    return str(base)


def open_pr(
    repo,
    base_branch: str,
    draft: DraftResult,
    check: CheckResult,
    confidence: float,
) -> str:
    """Open a PR on an already-authenticated PyGithub `repo`.

    Shared by both entry points: the cfg-based local runner and the
    GitHub-App-based webhook service. Returns the PR URL.
    """
    base = repo.get_branch(base_branch)
    branch = f"auto-doc-sync/{int(time.time())}"
    repo.create_git_ref(ref=f"refs/heads/{branch}", sha=base.commit.sha)

    for e in draft.edits:
        try:
            existing = repo.get_contents(e.path, ref=branch)
            repo.update_file(
                e.path,
                f"docs: sync {e.path} with API changes",
                e.updated_content,
                existing.sha,
                branch=branch,
            )
        except Exception:
            repo.create_file(
                e.path,
                f"docs: add {e.path} for API changes",
                e.updated_content,
                branch=branch,
            )

    pr = repo.create_pull(
        title="docs: auto-sync documentation with API changes",
        body=_pr_body(draft, check, confidence),
        head=branch,
        base=base_branch,
    )
    return pr.html_url


# Marker placed in the agent's own commit messages. The webhook loop-guard
# checks for it (belt-and-suspenders alongside the committer-identity check)
# so the agent's doc commit never re-triggers itself.
SKIP_MARKER = "[skip-doc-sync]"


def commit_to_branch(repo, branch: str, edits, message: str) -> str | None:
    """Commit doc edits directly onto an existing branch (the feature PR
    branch). Skips files whose content is already up to date so we don't
    create empty commits (and needless re-triggers). Returns the new commit
    SHA, or None if nothing changed.

    The commit message carries SKIP_MARKER for the loop-guard.
    """
    full_message = f"{message} {SKIP_MARKER}"
    changed = False
    last_sha: str | None = None

    for e in edits:
        try:
            existing = repo.get_contents(e.path, ref=branch)
            if existing.decoded_content.decode() == e.updated_content:
                continue  # already up to date — skip to avoid empty churn
            res = repo.update_file(
                e.path, full_message, e.updated_content, existing.sha, branch=branch
            )
        except Exception:
            res = repo.create_file(
                e.path, full_message, e.updated_content, branch=branch
            )
        changed = True
        commit = res.get("commit") if isinstance(res, dict) else None
        last_sha = getattr(commit, "sha", None) if commit else None

    return last_sha if changed else None


def deliver_pr(
    cfg, draft: DraftResult, check: CheckResult, confidence: float
) -> str:
    """Open a real PR against cfg.github_repo using a personal token."""
    from github import Github  # PyGithub

    gh = Github(cfg.github_token)
    repo = gh.get_repo(cfg.github_repo)
    return open_pr(repo, cfg.base_branch, draft, check, confidence)
