# Auto API-Doc Sync Agent

An autonomous agent that watches a codebase for **API-surface changes**
(endpoints, function signatures, request/response shapes) and proposes
**targeted documentation edits** — always via a pull request, never an
auto-commit to `main`.

**Languages:** Python (`ast`) and JavaScript/TypeScript (heuristic).
**Docs:** Markdown + OpenAPI, in-repo or external (RAG).
**Delivery:** run locally, or as an always-on GitHub App across all repos.

PRD roadmap status: Phase 1 (MVP) ✅ · Phase 2 (eval suite) ✅ ·
Phase 3 (RAG; LangGraph deferred) ✅ · Phase 4 (multi-language ✅;
Vertex AI intentionally skipped — stays on AI Studio).

## Pipeline

```
diff → detect API changes (ast) → retrieve relevant docs
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
| `agent/pr.py` | Open a PR (or write a dry-run under `out/`) |
| `agent/log.py` | Append a JSON-lines trajectory per run |
| `run_local.py` | Orchestrator wiring it all together |

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

## Phase 2 — all repos, automatically (built)

The same core is wrapped in a **FastAPI webhook service** + a **GitHub
App** installed once across your account, so **every repo** (including
future ones) gets doc PRs automatically — no per-repo workflow file.

```
Any repo → push → GitHub App → FastAPI service (service/webhook.py)
        → clone + diff + detect + retrieve + draft + self-check → open doc PR
```

| Module | Role |
|---|---|
| `service/security.py` | Verify GitHub's HMAC-SHA256 webhook signature |
| `service/github_app.py` | Mint installation tokens; authenticated PyGithub client |
| `service/pipeline.py` | Clone repo at head, run the core, open the PR |
| `service/webhook.py` | FastAPI app: verify → dispatch push events in background |
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
**`deploy/SETUP.md`**. Tests:

```bash
python3 tests/test_service.py   # signature + webhook dispatch
```

## Eval suite (PRD Phase 2)

A labeled test set of "PRs" scores detection accuracy against the PRD
success metric ("≥ 90% of API-surface-relevant changes detected").

```bash
python3 run_eval.py           # scorecard + out/eval_report.json (exit != 0 if below target)
python3 run_eval.py --json    # machine-readable
```

- `eval/cases/<name>/` — each case has `before.py`, `after.py`, and
  `expected.json` (labeled `status`/`key` changes). Includes negative
  cases (private-helper edits, implementation-only diffs) that must
  produce **no** detections.
- `eval/harness.py` — runs the detector per case, computes precision /
  recall / F1 and per-case exact-match.

Current: **12/12 cases, recall 100%** (target 90%).

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
