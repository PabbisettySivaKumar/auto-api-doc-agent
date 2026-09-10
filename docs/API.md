# Agent Python API Reference

Reference for the public API of the `agent/` package — the reusable core
that powers both the local runner (`run_local.py`) and the webhook service
(`service/`). This is the *reference*; the [README](../README.md) is the
overview/setup guide.

The pipeline is a linear flow, and the functions below mirror it:

```
diff → detect → retrieve → draft → self-check → deliver → log
```

```python
from agent import diff, detect, retrieve, draft, selfcheck, pr, log
```

---

## `agent.diff` — obtaining changes

### class `FileChange`
A single changed file with content before and after.

| Field | Type | Notes |
|---|---|---|
| `path` | `str` | Repo-relative path |
| `old_content` | `str \| None` | `None` for an added file |
| `new_content` | `str \| None` | `None` for a deleted file |
| `is_python` | `bool` (property) | True if `path` ends in `.py` |

### `changes_from_git(repo_path, base="HEAD~1", head="HEAD") -> list[FileChange]`
Files changed between two revisions of a local git repo.

### `changes_from_files(before_path, after_path, logical_path=None) -> list[FileChange]`
Compare two explicit file versions (fixture / demo mode). `logical_path`
overrides the reported path (defaults to the after file's name).

---

## `agent.detect` — API-surface detection

### class `Symbol`
One public API symbol extracted from source.

| Field | Type | Notes |
|---|---|---|
| `kind` | `str` | `"function"` or `"route"` |
| `name` | `str` | Qualified, e.g. `"UserAPI.list"` |
| `signature` | `str` | e.g. `"(user_id: int) -> User"` |
| `docstring` | `str \| None` | |
| `http_method` | `str \| None` | For routes, e.g. `"POST"` |
| `route_path` | `str \| None` | For routes, e.g. `"/users"` |
| `lineno` | `int` | |
| `key` | `str` (property) | Identity used to match across before/after |
| `describe()` | `str` | Human-readable one-liner |

### class `Change`
A classified difference between two symbol sets.

| Field | Type | Notes |
|---|---|---|
| `status` | `str` | `"added"`, `"removed"`, or `"changed"` |
| `key` | `str` | Matches `Symbol.key` |
| `before` | `Symbol \| None` | |
| `after` | `Symbol \| None` | |
| `details` | `list[str]` | e.g. signature/docstring diffs |
| `describe()` | `str` | Human-readable description |

### `extract_symbols(source: str | None) -> dict[str, Symbol]`
Map of `Symbol.key → Symbol` for all public API symbols in `source`.
Private names (leading `_`) are skipped; returns `{}` on `None` or a
`SyntaxError`.

### `diff_symbols(old, new) -> list[Change]`
Classify changes between two `{key: Symbol}` maps.

### `detect_file_changes(old_source, new_source) -> list[Change]`
Full per-file pipeline: extract both sides, diff, classify.

---

## `agent.retrieve` — locating relevant docs

### class `DocFile`
| Field | Type | Notes |
|---|---|---|
| `path` | `str` | |
| `kind` | `str` | `"markdown"` or `"openapi"` |
| `content` | `str` | |

### class `DocMatch`
| Field | Type | Notes |
|---|---|---|
| `doc` | `DocFile` | |
| `score` | `int` | Higher is more relevant |
| `matched_terms` | `list[str]` | Terms/snippets that matched |

### `find_docs(repo_path: str) -> list[DocFile]`
All Markdown + OpenAPI docs in the repo (skips vendored dirs).

### `relevant_docs(repo_path, changes) -> list[DocMatch]`
Direct (substring) retrieval over in-repo docs. Phase 1 default.

### `relevant_docs_auto(repo_path, changes, cfg=None, external_docs_dirs=None, force_rag=None) -> list[DocMatch]`
Auto-selects **direct** vs **RAG** retrieval. Uses RAG when
`external_docs_dirs` is given, `force_rag` is true (or `cfg.rag_force`), or
the corpus reaches `cfg.rag_min_docs`; otherwise substring matching.

---

## `agent.rag` — semantic retrieval (Phase 3)

### class `Embedder(cfg=None)`
Embeds text, preferring the Gemini embedding model, falling back to a
deterministic offline hashed embedding when no key is set.

- `embed(texts: list[str]) -> list[list[float]]`
- `used_model: bool` — True if Gemini embeddings were used

### `chunk_doc(content, max_chars=800) -> list[str]`
Split a doc into chunks, preferring Markdown heading boundaries.

### `build_index(docs, embedder) -> RagIndex`
Embed all doc chunks into a queryable index.

### `query_index(index, query_text, embedder, k=4) -> list[DocMatch]`
Top-`k` docs by best-chunk cosine similarity to `query_text`.

### `relevant_docs_over(docs, changes, cfg=None, k=4) -> list[DocMatch]`
Convenience: build an index over `docs` and query it from `changes`.

### `cosine(a, b) -> float`
Cosine similarity of two L2-normalized vectors.

---

## `agent.draft` — generating doc edits

### class `DocEdit`
| Field | Type | Notes |
|---|---|---|
| `path` | `str` | |
| `kind` | `str` | |
| `updated_content` | `str` | Full new file content |
| `rationale` | `str` | What changed and why |

### class `DraftResult`
| Field | Type | Notes |
|---|---|---|
| `edits` | `list[DocEdit]` | |
| `summary` | `str` | |
| `confidence` | `float` | 0.0–1.0 |
| `used_model` | `bool` | True if Gemini drafted (vs stub) |

### `draft_edits(changes, matches, cfg) -> DraftResult`
Draft targeted, minimal doc edits with Gemini; falls back to a
deterministic stub when no key is configured.

---

## `agent.selfcheck` — grounding the edits

### class `CheckResult`
| Field | Type | Notes |
|---|---|---|
| `warnings` | `list[str]` | |
| `adjusted_confidence` | `float` | Draft confidence minus penalties |
| `ok` | `bool` (property) | True if no warnings |

### `check(draft, changes) -> CheckResult`
Verify the drafted edits reflect the code changes; adjust confidence.

---

## `agent.pr` — delivery (always a PR, never a commit to main)

### `deliver_dry_run(output_dir, draft, check, confidence) -> str`
Write proposed edits + a PR body under `output_dir/proposed/`. Returns
that directory.

### `open_pr(repo, base_branch, draft, check, confidence) -> str`
Open a PR on an already-authenticated PyGithub `repo`. Returns the PR URL.

### `deliver_pr(cfg, draft, check, confidence) -> str`
Open a PR against `cfg.github_repo` using a personal token. Returns the
PR URL.

---

## `agent.log` — trajectory logging

### `log_run(output_dir, record) -> str`
Append one JSON line (input → reasoning → output) to
`output_dir/trajectories.jsonl`. Returns the log path.

---

## End-to-end example

```python
from config import config
from agent import diff, detect, retrieve, draft, selfcheck, pr

changes = []
for fc in diff.changes_from_git("/path/to/repo", "HEAD~1", "HEAD"):
    if fc.is_python:
        changes.extend(detect.detect_file_changes(fc.old_content, fc.new_content))

matches = retrieve.relevant_docs_auto("/path/to/repo", changes, config)
result = draft.draft_edits(changes, matches, config)
checked = selfcheck.check(result, changes)

if result.edits and checked.adjusted_confidence >= config.confidence_threshold:
    out = pr.deliver_dry_run(config.output_dir, result, checked,
                             checked.adjusted_confidence)
    print("proposed edits written to", out)
```
