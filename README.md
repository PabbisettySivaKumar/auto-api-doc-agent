# Auto API-Doc Sync Agent

An autonomous agent that watches a codebase for **API-surface changes**
(endpoints, function signatures, request/response shapes) and proposes
**targeted documentation edits** — always via a pull request, never an
auto-commit to `main`.

## Status — complete & live

Built, deployed, and verified end-to-end on real repos.

| Capability | What it does | Status |
|---|---|---|
| **Incremental sync** | On a change, propose targeted doc edits via PR | ✅ live |
| **All-repos service** | One GitHub App + FastAPI service, no per-repo file | ✅ on Render (free) |
| **Multi-language** | Python (`ast`) + JavaScript/TypeScript (heuristic) | ✅ |
| **RAG** | Semantic retrieval for scattered/external docs | ✅ |
| **Layered docs** | Two-tier: API index + per-feature deep-dives with signatures + grounded mermaid diagrams, committed onto the PR branch (one idempotent commit, description reuse) | ✅ live |
| **Backfill** | Document an *old* repo's whole API surface with a **local model** | ✅ verified |
| **CI** | Full test suite + accuracy eval on every push/PR, gates on recall | ✅ |

- **Live-verified:** doc-sync PRs merged on a **Python** and a **JavaScript**
  repo; whole-repo **backfill** run on two real repos, generated entirely by a
  **local model** (no code left the machine).
- **Quality gate:** detection eval **18/18, recall 100%** (target 90%), plus a
  golden two-tier output test.
- **Zero-cost, minimal deps:** free hosting; local model for bulk work; no
  numpy/Chroma/tree-sitter.

### Two model paths (by design, never crossed)
| Situation | Model | Runs on |
|---|---|---|
| **Old repo, no `docs/API.md`** → backfill | **Local (Ollama)** | your Mac |
| **New PR / push, docs exist** → incremental | **Gemini** | Render service |

The backfill path has **no Gemini branch at all** (falls back to a stub, never
the cloud), so old repos can't be sent to Gemini by accident.

**Languages:** Python (`ast`) and JavaScript/TypeScript (heuristic).
**Docs:** Markdown + OpenAPI, in-repo or external (RAG); plus layered feature docs.
**Delivery:** run locally, an always-on GitHub App across repos, or the local
backfill app.

See [`docs/PLAN-layered-docs.md`](docs/PLAN-layered-docs.md) for the layered-docs
design and [`deploy/SETUP.md`](deploy/SETUP.md) for deployment + backfill steps.

## Pipeline

```
diff → detect API changes (Python ast / JS-TS) → retrieve relevant docs (direct | RAG)
     → draft edits (Gemini | stub) → self-check → deliver (PR) → log trajectory
```

| Module | Role |
|---|---|
| `agent/diff.py` | Get changed files (local git or explicit file pair) |
| `agent/detect.py` | Extract & diff API surface via Python `ast`; `detect_changes()` dispatches by language |
| `agent/detect_js.py` | JS/TS API-surface detection (heuristic, zero-dep) |
| `agent/retrieve.py` | Find Markdown / OpenAPI docs that reference changed symbols |
| `agent/draft.py` | Draft minimal doc edits with Gemini (stub fallback if no key) |
| `agent/selfcheck.py` | Ground the edits against the code; adjust confidence |
| `agent/pr.py` | Open a PR / commit onto a branch (or dry-run under `out/`) |
| `agent/log.py` | Append a JSON-lines trajectory per run |
| `agent/rag.py` | Semantic retrieval for scattered/external docs |
| `agent/features.py` | Resolve + bucket changes/files by feature (folder) |
| `agent/callgraph.py` | Extract who-calls-whom (grounds diagrams) |
| `agent/docwriter.py` | Two-tier docs + grounded mermaid diagrams |
| `agent/backfill.py` | Whole-repo backfill (local model) → one PR |
| `agent/llm.py` | Provider routing: backfill→local, incremental→Gemini |
| `service/webhook.py` | GitHub App webhook: push + pull_request (layered) |
| `service/pipeline.py` | Clone → run core → deliver, for push and PR events |
| `run_local.py` | Local orchestrator wiring it all together |
| `backfill_app.py` | Local app with a repo dropdown for backfilling old repos |

## Quick start (no setup — stub mode)

```bash
python3 run_local.py          # runs the bundled fixtures demo
```

Output lands in `out/proposed/` (proposed docs + PR body) and
`out/trajectories.jsonl` (the run log).

## Real drafts with Gemini

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env          # set GEMINI_API_KEY
python3 run_local.py
```

## Run against your own repo

```bash
python3 run_local.py --repo /path/to/repo --base HEAD~1 --head HEAD
```

## Open a real PR (live mode)

Set `GITHUB_TOKEN` (repo scope) and `GITHUB_REPO=owner/name` in `.env`, then:

```bash
python3 run_local.py --repo /path/to/repo --live
```

A PR is only opened when confidence ≥ `CONFIDENCE_THRESHOLD` (default 0.6);
below that the run is flagged for manual review and written to `out/` only.

## Deployment — all repos, automatically

The same core is wrapped in a **FastAPI webhook service** + a **GitHub
App** installed once across your account, so **every repo** (including
future ones) gets doc PRs automatically — no per-repo workflow file.
Currently deployed on Render's free plan (see `deploy/SETUP.md`).

```
Any repo → push / pull_request → GitHub App → FastAPI service (service/webhook.py)
        → clone + diff + detect + retrieve + draft/docwriter + self-check
        → open doc PR (push)  or  commit docs onto the PR branch (pull_request, layered)
```

The service handles **push** (single-`API.md` sync PR) and, when
`DOC_MODE=layered`, **pull_request** events (two-tier feature docs committed
onto the PR branch, loop-guarded). See `deploy/SETUP.md` §6 to enable layered
mode and §7 for local backfill of old repos.

| Module | Role |
|---|---|
| `service/security.py` | Verify GitHub's HMAC-SHA256 webhook signature |
| `service/github_app.py` | Mint installation tokens; authenticated PyGithub client |
| `service/pipeline.py` | Clone repo, run the core; `run_for_push` (sync PR) + `run_for_pr` (layered, commits onto PR branch) |
| `service/webhook.py` | FastAPI app: verify → dispatch push + pull_request in background |
| `deploy/` | Dockerfile, GitHub App manifest, `SETUP.md` |
| `render.yaml` | Render free-plan Blueprint (one-click deploy) |
| `.github/workflows/keep-warm.yml` | Pings `/healthz` every 10 min to beat free-plan cold starts |
| [`docs/API.md`](docs/API.md) | Python API reference for the `agent/` package (the agent's own docs — a dogfooding target) |

Run the service locally:

```bash
python3 -m pip install -r requirements.txt
uvicorn service.webhook:app --reload --port 8000
curl localhost:8000/          # health + config status
```

Full deployment + GitHub App creation/installation steps are in
**`deploy/SETUP.md`**.

## Tests & eval

```bash
python3 tests/test_service.py       # webhook: push + pull_request, loop/fork guards
python3 tests/test_rag.py           # RAG retrieval (offline, deterministic)
python3 tests/test_detect_js.py     # JS/TS detector
python3 tests/test_features.py      # feature bucketing
python3 tests/test_callgraph.py     # call-graph extraction
python3 tests/test_docwriter.py     # two-tier writer + diagrams + signatures + reuse
python3 tests/test_golden_docs.py   # golden end-to-end two-tier output
python3 tests/test_incremental_feature.py  # PR flow documents the whole feature
python3 tests/test_pr_commit.py     # single idempotent commit per run
python3 tests/test_backfill.py      # backfill + local-only safety proof
python3 run_eval.py                 # 18-case accuracy scorecard (exit != 0 below target)
```

CI (`.github/workflows/ci.yml`) runs all of the above on every push and PR;
a detection-accuracy regression (recall below target) fails the build.

## Eval suite (PRD Phase 2)

A labeled test set of "PRs" scores detection accuracy against the PRD
success metric ("≥ 90% of API-surface-relevant changes detected").

```bash
python3 run_eval.py           # scorecard + out/eval_report.json (exit != 0 if below target)
python3 run_eval.py --json    # machine-readable
```

- `eval/cases/<name>/` — each case has `before.*`, `after.*` (any language
  — `.py`, `.js`, `.ts`) and `expected.json` (labeled `status`/`key`
  changes). Includes negative cases (private-helper edits,
  implementation-only diffs) that must produce **no** detections.
- `eval/harness.py` — routes each case to its language detector, computes
  precision / recall / F1 and per-case exact-match.

Current: **18/18 cases (12 Python + 6 JS/TS), recall 100%** (target 90%).

## RAG for scattered / external docs (PRD Phase 3)

When docs are a few files in-repo, retrieval uses fast substring matching.
When they're numerous or live **outside** the repo (exported
Confluence/Notion Markdown, etc.), `retrieve.relevant_docs_auto` switches
to **semantic RAG** — embedding doc chunks and ranking by cosine
similarity to the changed API symbols.

- `agent/rag.py` — Gemini embeddings (`gemini-embedding-001`) with a
  deterministic **offline** fallback (no key needed for tests/dry-run);
  pure-Python cosine store (no numpy / Chroma / LanceDB — swapping those in
  is a one-class change behind the same interface).
- **Auto-selects** RAG when `EXTERNAL_DOCS_DIR` is set, `RAG_FORCE=true`,
  or the corpus reaches `RAG_MIN_DOCS` files. Otherwise stays on the
  cheaper direct path (PRD: don't reach for a vector DB before you need it).

```bash
python3 run_local.py --rag                        # force RAG on fixtures
python3 run_local.py --external-docs ~/exported_docs   # RAG over external docs
python3 tests/test_rag.py                          # deterministic offline tests
```

**Orchestration (LangGraph):** deliberately **not** added yet — the
pipeline is still a clean linear loop with no cycles/branching/paused
state, so a graph framework would add ceremony without removing pain. The
rationale and migration path are in [`docs/ORCHESTRATION.md`](docs/ORCHESTRATION.md).
