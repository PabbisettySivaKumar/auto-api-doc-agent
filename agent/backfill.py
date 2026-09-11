"""Whole-repo backfill: document an old repo's *entire* current API surface
(layered-docs Phase F).

The incremental flow only documents what changes; an old repo whose code
already exists gets nothing. Backfill closes that gap: it walks the whole
repo, buckets every source file by feature, builds a full call graph per
feature, and renders the two-tier docs — with `changes=[]`, so the doc
writer simply documents everything present.

Provider: **local model only** (`mode="backfill"` in agent/llm.py). Old
repos are never sent to Gemini, by construction.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import features, callgraph, docwriter, llm, pr
from .draft import DocEdit, DraftResult
from .selfcheck import CheckResult

_CODE_EXTS = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "out",
    "dist", "build", ".next", "coverage", "vendor", "docs",
}


@dataclass
class BackfillResult:
    edits: list[DocEdit] = field(default_factory=list)
    features_documented: list[str] = field(default_factory=list)
    symbols: int = 0
    used_model: bool = False
    capped: bool = False


def collect_source_files(repo_dir: str) -> dict[str, str]:
    """{repo-relative path: source} for every code file in the repo."""
    sources: dict[str, str] = {}
    root = os.path.abspath(repo_dir)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in _CODE_EXTS:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            try:
                with open(full, encoding="utf-8") as f:
                    sources[rel] = f.read()
            except (UnicodeDecodeError, OSError):
                continue
    return sources


def run_backfill(cfg, repo_dir: str) -> BackfillResult:
    """Document the whole repo. Returns two-tier DocEdits (Tier-1 + per
    feature Tier-2). Generation uses the LOCAL model only."""
    source_root = getattr(cfg, "source_root", "")
    sources = collect_source_files(repo_dir)
    buckets = features.bucket_files(list(sources), source_root)
    overrides = features._load_overrides(repo_dir)

    # Existing index (usually empty for an old repo) — upserted per feature.
    index_path = os.path.join(repo_dir, docwriter.TIER1_INDEX)
    index_content = ""
    if os.path.exists(index_path):
        with open(index_path) as f:
            index_content = f.read()

    cap = getattr(cfg, "backfill_symbol_cap", 200)
    result = BackfillResult()
    edits: list[DocEdit] = []

    for feature in sorted(buckets):
        feat_sources = {p: sources[p] for p in buckets[feature]}
        graph = callgraph.build_call_graph(feat_sources)
        if not graph.nodes:
            continue  # nothing documentable in this feature (e.g. configs)

        display = features.feature_display_name(feature, overrides)
        n_public = sum(
            1 for n in graph.nodes.values()
            if n.is_route or not n.simple.startswith("_")
        )
        # Cost/scope guard: past the cap, keep bucketing but stop LLM prose
        # (render_tier2 still produces structure + grounded diagrams).
        mode = llm.BACKFILL
        if result.symbols + n_public > cap:
            result.capped = True
            local_cfg = None  # None cfg -> stub descriptions, no model calls
        else:
            local_cfg = cfg
        result.symbols += n_public

        existing_tier2 = ""
        t2_path = os.path.join(repo_dir, docwriter.tier2_path(feature))
        if os.path.exists(t2_path):
            with open(t2_path) as f:
                existing_tier2 = f.read()

        tier2 = docwriter.render_tier2(
            feature, display, graph, [], existing_tier2, local_cfg, mode=mode
        )
        summary = f"Documented {n_public} public symbol(s) in `{feature}/`."
        tier1 = docwriter.update_tier1(index_content, feature, display, summary)
        index_content = tier1.updated_content

        edits.extend([tier2, tier1])
        result.features_documented.append(feature)

    result.edits = edits
    # Local model was attempted whenever a real cfg reached render (i.e. at
    # least one feature under the cap). Actual reachability is logged by the
    # llm helper; this flag just says "we tried the local model".
    result.used_model = cfg is not None and not (result.capped and result.symbols == 0)
    return result


def deliver_backfill_pr(repo, base_branch: str, result: BackfillResult) -> str | None:
    """Open ONE PR to `base_branch` (usually main) with the whole docs tree.

    Reuses the standard PR path (never commits to the base directly).
    Returns the PR URL, or None if there was nothing to document.
    """
    if not result.edits:
        return None
    summary = (
        f"Backfilled API documentation for {len(result.features_documented)} "
        f"feature(s): {', '.join(result.features_documented)}. "
        f"Generated locally (offline model); no code sent to any cloud service."
    )
    if result.capped:
        summary += (
            f" Note: symbol cap reached ({result.symbols}); some sections use "
            "structural descriptions."
        )
    draft = DraftResult(
        edits=result.edits,
        summary=summary,
        confidence=1.0,
        used_model=result.used_model,
        provider="local (ollama) — no cloud",
    )
    return pr.open_pr(repo, base_branch, draft, CheckResult(), 1.0)
