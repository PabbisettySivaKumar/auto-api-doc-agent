"""End-to-end local runner for the Auto API-Doc Sync Agent (Phase 1).

Two modes:

  # Compare two revisions of a local git repo:
  python run_local.py --repo /path/to/repo --base HEAD~1 --head HEAD

  # Compare two explicit file versions against a docs folder (demo):
  python run_local.py --before fixtures/api_before.py \\
                      --after  fixtures/api_after.py  \\
                      --logical-path api.py --docs-root fixtures

With no arguments it runs the bundled fixtures demo.

The pipeline: diff -> detect API changes -> retrieve relevant docs ->
draft edits (Gemini or stub) -> self-check -> deliver (dry-run PR or real
PR) -> log trajectory.
"""

from __future__ import annotations

import argparse

from config import config
from agent import diff, detect, retrieve, draft, selfcheck, pr, log


def _gather_changes(args) -> tuple[list[diff.FileChange], str]:
    if args.repo:
        changes = diff.changes_from_git(args.repo, args.base, args.head)
        return changes, args.repo
    changes = diff.changes_from_files(args.before, args.after, args.logical_path)
    return changes, args.docs_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="path to a local git repo")
    parser.add_argument("--base", default="HEAD~1")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--before", default="fixtures/api_before.py")
    parser.add_argument("--after", default="fixtures/api_after.py")
    parser.add_argument("--logical-path", default="api.py")
    parser.add_argument("--docs-root", default="fixtures")
    parser.add_argument(
        "--external-docs",
        default=None,
        help="comma-separated dirs of docs outside the repo (enables RAG)",
    )
    parser.add_argument(
        "--rag", action="store_true", help="force RAG retrieval"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="open a real PR (requires GITHUB_TOKEN + GITHUB_REPO)",
    )
    args = parser.parse_args()

    file_changes, docs_root = _gather_changes(args)

    # 1. Detect API-surface changes across all changed files (any language).
    all_changes: list[detect.Change] = []
    for fc in file_changes:
        all_changes.extend(
            detect.detect_changes(fc.path, fc.old_content, fc.new_content)
        )

    print(f"\n=== Auto API-Doc Sync Agent (Phase 1) ===")
    print(f"Changed files: {len(file_changes)} | API changes: {len(all_changes)}")
    for c in all_changes:
        print("  " + c.describe().replace("\n", "\n  "))

    if not all_changes:
        print("\nNo API-surface changes detected. Nothing to do.")
        log.log_run(config.output_dir, {"result": "no-api-changes"})
        return

    # 2. Retrieve relevant docs (auto-selects direct vs. RAG).
    external = args.external_docs.split(",") if args.external_docs else None
    matches = retrieve.relevant_docs_auto(
        docs_root,
        all_changes,
        config,
        external_docs_dirs=external,
        force_rag=True if args.rag else None,
    )
    mode = "RAG" if (args.rag or external) else "auto"
    print(f"\nRelevant docs ({mode}): {len(matches)}")
    for m in matches:
        print(f"  {m.doc.path} (score {m.score}, matched {m.matched_terms})")

    # 3. Draft edits.
    result = draft.draft_edits(all_changes, matches, config)
    print(f"\nDraft: {result.summary}")

    # 4. Self-check.
    checked = selfcheck.check(result, all_changes)
    confidence = checked.adjusted_confidence
    print(f"Confidence (post-check): {confidence:.2f}")
    for w in checked.warnings:
        print(f"  ⚠️ {w}")

    # 5. Deliver — gate on the confidence threshold (PRD section 8).
    if not result.edits:
        print("\nNo edits produced.")
        delivery = "none"
    elif confidence < config.confidence_threshold:
        print(
            f"\nConfidence {confidence:.2f} < threshold "
            f"{config.confidence_threshold}: flagging for MANUAL REVIEW, "
            "writing dry-run output only."
        )
        out = pr.deliver_dry_run(config.output_dir, result, checked, confidence)
        print(f"Proposed changes written to: {out}")
        delivery = f"manual-review:{out}"
    elif args.live and config.has_github:
        url = pr.deliver_pr(config, result, checked, confidence)
        print(f"\nOpened PR: {url}")
        delivery = f"pr:{url}"
    else:
        out = pr.deliver_dry_run(config.output_dir, result, checked, confidence)
        print(f"\nDry-run: proposed changes written to: {out}")
        delivery = f"dry-run:{out}"

    # 6. Log the trajectory.
    log_path = log.log_run(
        config.output_dir,
        {
            "changes": all_changes,
            "relevant_docs": [m.doc.path for m in matches],
            "summary": result.summary,
            "used_model": result.used_model,
            "confidence": confidence,
            "warnings": checked.warnings,
            "delivery": delivery,
        },
    )
    print(f"Trajectory logged to: {log_path}\n")


if __name__ == "__main__":
    main()
