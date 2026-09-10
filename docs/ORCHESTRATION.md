# Orchestration decision — why still a plain loop (no LangGraph yet)

PRD Phase 3 says: *"introduce LangGraph **if** the state machine has
outgrown a plain loop."* This is a deliberate "not yet."

## Current shape

The agent is a straight linear pipeline, run once per push:

```
diff → detect → retrieve → draft → self-check → deliver → log
```

There are no cycles, no branching retries, no long-lived state, no
human-in-the-loop *pauses* inside the run (the human step happens later,
out-of-process, as a PR review). Each stage is a plain function call in
`service/pipeline.py` / `run_local.py`.

## When LangGraph would earn its place

Adopt it when the control flow actually needs what a graph gives you:

- **Loops / retries with state** — e.g. draft → self-check → *re-draft*
  until confidence clears a bar, with a max-iteration guard.
- **Branching** — different paths for "OpenAPI spec" vs "Markdown" vs
  "docstring-only", each with distinct tools.
- **Interruptible human-in-the-loop** — pausing mid-run for approval and
  resuming from a persisted checkpoint.
- **Parallel fan-out/fan-in** — drafting many docs concurrently then
  merging.

None of these are true today, so a graph framework would add ceremony and
a dependency without removing any pain — exactly what the PRD warns
against ("the pain a framework solves is only obvious once you've felt
it"). The pipeline is small enough that the mechanics staying visible is a
feature, not a limitation.

## Migration path when the time comes

The stages are already pure, single-responsibility functions with typed
inputs/outputs (`detect.detect_file_changes`, `retrieve.relevant_docs_auto`,
`draft.draft_edits`, `selfcheck.check`, `pr.open_pr`). Each maps cleanly to
one LangGraph node; wiring them into a `StateGraph` is additive and
touches no detection/draft logic.
