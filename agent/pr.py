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
        f"(model: {draft.provider or ('gemini' if draft.used_model else 'stub')})",
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


def _current_content(repo, path: str, branch: str) -> str | None:
    """Content of `path` on `branch`, or None if it doesn't exist."""
    try:
        return repo.get_contents(path, ref=branch).decoded_content.decode()
    except Exception:
        return None


def commit_to_branch(repo, branch: str, edits, message: str) -> str | None:
    """Commit all doc edits onto an existing branch in a SINGLE commit.

    Idempotent: files already matching are skipped, and if nothing changed
    the function is a no-op (returns None, no empty commit) — which also
    prevents needless webhook re-triggers. Uses the git tree API so every
    edit lands in one commit rather than one commit per file.

    The commit message carries SKIP_MARKER for the loop-guard.
    """
    from github import InputGitTreeElement

    # Keep only edits whose content actually differs from the branch.
    changed = [e for e in edits if _current_content(repo, e.path, branch) != e.updated_content]
    if not changed:
        return None  # nothing to do — idempotent no-op

    ref = repo.get_git_ref(f"heads/{branch}")
    base_commit = repo.get_git_commit(ref.object.sha)

    elements = [
        InputGitTreeElement(path=e.path, mode="100644", type="blob", content=e.updated_content)
        for e in changed
    ]
    new_tree = repo.create_git_tree(elements, base_commit.tree)
    new_commit = repo.create_git_commit(
        f"{message} {SKIP_MARKER}", new_tree, [base_commit]
    )
    ref.edit(new_commit.sha)
    return new_commit.sha


def deliver_pr(
    cfg, draft: DraftResult, check: CheckResult, confidence: float
) -> str:
    """Open a real PR against cfg.github_repo using a personal token."""
    from github import Github  # PyGithub

    gh = Github(cfg.github_token)
    repo = gh.get_repo(cfg.github_repo)
    return open_pr(repo, cfg.base_branch, draft, check, confidence)
