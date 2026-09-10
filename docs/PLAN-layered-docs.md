# Plan — Layered auto-maintained documentation (next phase)

**Status:** designed, not yet implemented. This is the source-of-truth plan;
update it as we build.

## Why

In fast-paced teams, docs rot — many people ship many features quickly and
documentation is never written well. This phase makes the agent maintain
two tiers of documentation automatically, so knowledge isn't lost.

## Vision — two tiers

- **Tier 1 — Main API doc** (`docs/API.md`, canonical in `main`): an index
  of *all* features/endpoints ever added. Accumulates; never loses prior
  entries (targeted edits, not rewrites). Each entry links to its Tier-2 doc.
- **Tier 2 — Per-feature deep-dives** (`docs/features/<feature>.md`): explain
  the feature's public surface + one level of key internals, with grounded
  mermaid diagrams.

## Design decisions (locked)

| Topic | Decision |
|---|---|
| Feature = ? | **Code location:** first path segment under the repo root (`users/…` → feature `users`). One PR can span multiple features → bucket changes by folder and update each independently. A feature can span multiple PRs → same folder updates the same docs. |
| Feature name | Auto-derived from folder; optional override via a repo-root `features.yml` (slug → nice name). |
| Non-feature code | Root files, `utils/`, `common/`, config → a **`core-shared`** catch-all bucket. |
| Tier-2 depth | Public surface in full (purpose, params, returns, side effects) **+ one level of key internals** (skip trivial getters/wrappers). Not unbounded. |
| Diagrams | **Grounded in the real call structure** (extracted from AST — not invented). A **sequence diagram** per non-trivial endpoint (handler→service→data); a **flowchart** only for genuinely branchy functions; nothing for simple/linear cases. |
| Trigger & delivery | Generate on the **feature PR** (opened + each push); diff `base…head`; **commit doc updates onto the feature branch** (loop-guarded). Docs merge into `main` with the feature. Keep the existing push-to-`main` trigger as a safety net. |
| Evolution | Later PRs on the same folder update that feature's docs in place. **Removals are marked "Deprecated/Removed" (kept for history), not deleted.** |

Accepted tradeoff: the agent writes to a human's in-flight branch (re-runs
their CI; rare chance of touching a file the dev is also editing).

## Implementation phases

Build A→B→C→D→E. A–C are pure/offline (unit-tested before any webhook
change). D is the only phase touching live GitHub. Keep the existing single-
`API.md` behavior behind a `DOC_MODE=single|layered` flag until layered is
proven on one repo.

### Phase A — Feature bucketing
- New `agent/features.py`: `resolve_feature(path)`, `feature_display_name`,
  `bucket_changes(changes) -> {feature: [Change]}`; `features.yml` override.
- Stamp `Change.file` in `detect.detect_changes` so bucketing knows the folder.
- `tests/test_features.py`.

### Phase B — Call-graph extraction (grounds diagrams)
- New `agent/callgraph.py`: Python `ast` who-calls-whom; JS/TS heuristic;
  `endpoint_flow(route)`, `is_branchy(func)`.
- `tests/test_callgraph.py`.

### Phase C — Two-tier doc writer
- New `agent/docwriter.py` (reuses `draft.py`'s Gemini/stub client):
  `render_tier2` (targeted edit; mark removed = Deprecated),
  `render_diagrams` (mermaid; validate syntax, drop diagram on parse fail),
  `update_tier1` (upsert entry in `docs/API.md` linking to the Tier-2 file).
- `tests/test_docwriter.py`.

### Phase D — PR-event trigger + loop-guard (live GitHub)
- Subscribe the App to `pull_request` (opened/synchronize/reopened) — App
  settings change, documented in `deploy/SETUP.md`.
- `service/webhook.py`: handle `pull_request` alongside `push`.
- **Loop-guard:** ignore commits authored by the app (identity check or a
  `[skip-doc-sync]` marker in the agent's commit message).
- `service/pipeline.py`: `run_for_pr(...)` → diff base…head → bucket (A) →
  call-graph (B) → write both tiers (C) → `pr.commit_to_branch(...)`.
- Keep `run_for_push` as the safety net.
- Extend `tests/test_service.py` (pull_request dispatch; loop-guard).

### Phase E — Eval, docs, rollout
- Eval: feature-bucketing cases + golden two-tier outputs (Tier-1 entry +
  Tier-2 sections + valid diagram for a known PR).
- Update `README.md`, `docs/API.md`, `deploy/SETUP.md`, `docs/ORCHESTRATION.md`.
- Flip `DOC_MODE` to `layered` after a one-repo test.

## Risks

- **Commit-to-branch re-trigger loop** — loop-guard with a dedicated test in D;
  commit at most once per PR-sync event.
- **Diagram hallucination** — AST-grounded (B) + mermaid syntax validation (C).
- **Gemini token cost** — two-tier + diagrams cost more; confidence gate and
  "only non-trivial diagrams" keep it bounded; watch free-tier quota.
- **Cross-language parity** — Python gets full call-graph first; JS/TS is
  heuristic (shallower Tier-2 initially; improve later with tree-sitter).
