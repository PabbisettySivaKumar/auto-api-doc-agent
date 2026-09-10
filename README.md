# Auto API-Doc Sync Agent — Phase 1

An autonomous agent that watches a codebase for **API-surface changes**
(endpoints, function signatures, request/response shapes) and proposes
**targeted documentation edits** — always via a pull request, never an
auto-commit to `main`.

This is Phase 1 (single language: **Python**; docs: **Markdown + OpenAPI**;
no RAG, no orchestration framework), runnable locally with zero setup.

## Pipeline

```
diff → detect API changes (ast) → retrieve relevant docs
     → draft edits (Gemini | stub) → self-check → deliver (PR) → log trajectory
```

| Module | Role |
|---|---|
| `agent/diff.py` | Get changed files (local git or explicit file pair) |
| `agent/detect.py` | Extract & diff API surface via Python `ast` |
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
