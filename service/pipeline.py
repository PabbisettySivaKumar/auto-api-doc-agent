"""Run the full agent pipeline for one repository push.

Reuses the entire Phase 1 core unchanged by shallow-materialising the repo
into a temp dir: clone with the installation token, run
diff -> detect -> retrieve -> draft -> self-check locally, then open the
PR through the authenticated App client. Temp dir is always cleaned up.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from typing import Any

from agent import diff, detect, retrieve, draft, selfcheck, pr, log
from . import github_app


def _clone(token: str, full_name: str, dest: str) -> None:
    url = f"https://x-access-token:{token}@github.com/{full_name}.git"
    result = subprocess.run(
        ["git", "clone", "--quiet", url, dest],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"clone failed: {result.stderr.strip()}")


def run_for_push(
    cfg,
    installation_id: int,
    full_name: str,
    before_sha: str,
    after_sha: str,
    base_branch: str,
) -> dict[str, Any]:
    """Process a push to the default branch. Returns a result summary."""
    private_key = cfg.resolve_private_key()
    repo, token = github_app.repo_for_installation(
        cfg.github_app_id, private_key, installation_id, full_name
    )

    tmp = tempfile.mkdtemp(prefix="auto-doc-")
    try:
        _clone(token, full_name, tmp)

        file_changes = diff.changes_from_git(tmp, before_sha, after_sha)
        changes: list[detect.Change] = []
        for fc in file_changes:
            changes.extend(
                detect.detect_changes(fc.path, fc.old_content, fc.new_content)
            )

        if not changes:
            result = {"repo": full_name, "result": "no-api-changes"}
            log.log_run(cfg.output_dir, result)
            return result

        external = [cfg.external_docs_dir] if cfg.external_docs_dir else None
        matches = retrieve.relevant_docs_auto(
            tmp, changes, cfg, external_docs_dirs=external
        )
        drafted = draft.draft_edits(changes, matches, cfg)
        checked = selfcheck.check(drafted, changes)
        confidence = checked.adjusted_confidence

        delivery: str
        if not drafted.edits:
            delivery = "no-edits"
        elif confidence < cfg.confidence_threshold:
            # All-repos automation: below threshold, stay silent rather
            # than open a low-confidence PR on someone's repo.
            delivery = f"skipped-low-confidence:{confidence:.2f}"
        else:
            url = pr.open_pr(repo, base_branch, drafted, checked, confidence)
            delivery = f"pr:{url}"

        result = {
            "repo": full_name,
            "changes": changes,
            "relevant_docs": [m.doc.path for m in matches],
            "summary": drafted.summary,
            "used_model": drafted.used_model,
            "confidence": confidence,
            "warnings": checked.warnings,
            "delivery": delivery,
        }
        log.log_run(cfg.output_dir, result)
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
