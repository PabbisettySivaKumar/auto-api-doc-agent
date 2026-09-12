"""Run the full agent pipeline for one repository push.

Reuses the entire Phase 1 core unchanged by shallow-materialising the repo
into a temp dir: clone with the installation token, run
diff -> detect -> retrieve -> draft -> self-check locally, then open the
PR through the authenticated App client. Temp dir is always cleaned up.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Any

from agent import diff, detect, retrieve, draft, selfcheck, pr, log
from agent import features, callgraph, docwriter, backfill
from . import github_app


def _clone(token: str, full_name: str, dest: str, branch: str | None = None) -> None:
    url = f"https://x-access-token:{token}@github.com/{full_name}.git"
    cmd = ["git", "clone", "--quiet"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, dest]
    result = subprocess.run(cmd, capture_output=True, text=True)
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


def _read(tmp: str, path: str) -> str:
    full = os.path.join(tmp, path)
    try:
        with open(full) as f:
            return f.read()
    except OSError:
        return ""


def _feature_sources(tmp: str, feature: str, source_root: str) -> dict[str, str]:
    """Current on-disk source of EVERY file in this feature (not only the
    changed ones).

    The Tier-2 doc is regenerated from this call graph, so it must see the
    whole feature — otherwise it would document only the changed file and
    wipe the rest of the feature's endpoints/functions/diagrams.
    """
    all_sources = backfill.collect_source_files(tmp)
    return {
        path: src
        for path, src in all_sources.items()
        if features.resolve_feature(path, source_root) == feature
    }


def run_for_pr(
    cfg,
    installation_id: int,
    full_name: str,
    pr_number: int,
    head_branch: str,
    base_branch: str,
) -> dict[str, Any]:
    """Layered-docs pipeline for an open PR: diff base..head, bucket changes
    by feature, and commit two-tier docs onto the feature (head) branch so
    they merge with the feature. Returns a result summary."""
    private_key = cfg.resolve_private_key()
    repo, token = github_app.repo_for_installation(
        cfg.github_app_id, private_key, installation_id, full_name
    )

    tmp = tempfile.mkdtemp(prefix="auto-doc-pr-")
    try:
        # Clone the feature branch so we can read post-change source + docs.
        _clone(token, full_name, tmp, branch=head_branch)

        file_changes = diff.changes_from_git(
            tmp, f"origin/{base_branch}", head_branch
        )
        changes: list[detect.Change] = []
        for fc in file_changes:
            changes.extend(
                detect.detect_changes(fc.path, fc.old_content, fc.new_content)
            )

        if not changes:
            result = {"repo": full_name, "pr": pr_number, "result": "no-api-changes"}
            log.log_run(cfg.output_dir, result)
            return result

        source_root = getattr(cfg, "source_root", "")
        overrides = features._load_overrides(tmp)
        buckets = features.bucket_changes(changes, tmp, source_root)

        all_edits = []
        index_content = _read(tmp, docwriter.TIER1_INDEX)
        per_feature: dict[str, Any] = {}

        for feature, fchanges in buckets.items():
            display = features.feature_display_name(feature, overrides)
            srcs = _feature_sources(tmp, feature, source_root)
            graph = callgraph.build_call_graph(srcs)

            existing_tier2 = _read(tmp, docwriter.tier2_path(feature))
            tier2 = docwriter.render_tier2(
                feature, display, graph, fchanges, existing_tier2, cfg
            )
            summary = f"{len(fchanges)} API change(s) in `{feature}/`."
            tier1 = docwriter.update_tier1(index_content, feature, display, summary)
            index_content = tier1.updated_content  # chain edits across features

            all_edits.extend([tier2, tier1])
            per_feature[feature] = {
                "changes": len(fchanges),
                "tier2": tier2.path,
            }

        commit_sha = pr.commit_to_branch(
            repo,
            head_branch,
            all_edits,
            f"docs: auto-update feature documentation (PR #{pr_number})",
        )
        delivery = f"committed:{commit_sha}" if commit_sha else "up-to-date"

        result = {
            "repo": full_name,
            "pr": pr_number,
            "head": head_branch,
            "features": per_feature,
            "delivery": delivery,
        }
        log.log_run(cfg.output_dir, result)
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
