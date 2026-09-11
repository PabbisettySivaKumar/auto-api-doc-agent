"""Feature resolution and bucketing (layered-docs Phase A).

A "feature" is defined by **code location**: the first path segment under a
configurable source root. e.g. with source_root="" (repo root):

    users/routes.py        -> feature "users"
    payments/api/charge.py -> feature "payments"
    src/orders/handler.py  -> feature "src"   (set source_root="src" to get "orders")

Code that isn't under a feature folder — a top-level file, or one of the
shared/utility folders — falls into a single `core-shared` bucket rather
than becoming its own noisy "feature".

One PR can touch several features; `bucket_changes` splits a flat list of
detected `Change`s (each carrying its `.file`) into per-feature groups so
the doc writer can update each feature independently.

An optional repo-root `features.yml` maps a feature slug to a nicer display
name, for teams that want to name things:

    features:
      users: User Management
      payments: Billing & Payments
"""

from __future__ import annotations

import os

from .detect import Change

CORE_SHARED = "core-shared"

# Top-level folders that are shared plumbing, not a product feature.
_SHARED_DIRS = {
    "utils",
    "util",
    "common",
    "core",
    "shared",
    "lib",
    "libs",
    "config",
    "configs",
    "scripts",
    "tests",
    "test",
    "docs",
    "internal",
    "helpers",
}


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").strip("/")


def resolve_feature(path: str, source_root: str = "") -> str:
    """Return the feature slug for a repo-relative file path.

    `source_root` is stripped first (e.g. "src"), so the feature is the
    first path segment *below* it. Files directly at the root, or under a
    shared/utility folder, resolve to `core-shared`.
    """
    p = _normalize(path)
    root = _normalize(source_root)
    if root and (p == root or p.startswith(root + "/")):
        p = p[len(root) :].lstrip("/")

    segments = p.split("/")
    # No directory component -> a root-level file -> shared.
    if len(segments) < 2:
        return CORE_SHARED

    top = segments[0]
    if not top or top.startswith(".") or top.lower() in _SHARED_DIRS:
        return CORE_SHARED
    return top


def _load_overrides(repo_path: str) -> dict[str, str]:
    """Read `features.yml` name overrides if present. Best-effort."""
    path = os.path.join(repo_path, "features.yml")
    if not os.path.exists(path):
        return {}
    try:
        import yaml

        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return {}
    features = data.get("features", data) if isinstance(data, dict) else {}
    if not isinstance(features, dict):
        return {}
    return {str(k): str(v) for k, v in features.items()}


def feature_display_name(slug: str, overrides: dict[str, str] | None = None) -> str:
    """Human-friendly name for a feature slug.

    Uses `features.yml` override when present; otherwise title-cases the
    slug (`user-management` / `user_management` -> "User Management").
    """
    if overrides and slug in overrides:
        return overrides[slug]
    if slug == CORE_SHARED:
        return "Core / Shared"
    words = slug.replace("-", " ").replace("_", " ").split()
    return " ".join(w.capitalize() for w in words) if words else slug


def bucket_changes(
    changes: list[Change], repo_path: str = ".", source_root: str = ""
) -> dict[str, list[Change]]:
    """Group changes by feature slug, preserving order within each feature."""
    buckets: dict[str, list[Change]] = {}
    for c in changes:
        feature = resolve_feature(c.file, source_root) if c.file else CORE_SHARED
        buckets.setdefault(feature, []).append(c)
    return buckets


def bucket_files(
    paths: list[str], source_root: str = ""
) -> dict[str, list[str]]:
    """Group file paths by feature slug (for whole-repo backfill)."""
    buckets: dict[str, list[str]] = {}
    for p in paths:
        buckets.setdefault(resolve_feature(p, source_root), []).append(p)
    return buckets
