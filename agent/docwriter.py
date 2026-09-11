"""Two-tier documentation writer (layered-docs Phase C).

Produces the layered docs for one feature:

  * Tier 2 — `docs/features/<feature>.md`: the feature's public surface +
    one level of key internals, plus grounded mermaid diagrams. Removed
    symbols are marked Deprecated, never deleted.
  * Tier 1 — an entry in the main `docs/API.md` index linking to the
    feature's Tier-2 doc; upserted in place so the index accumulates.

Grounding principle: **diagrams are generated deterministically from the
call graph (Phase B), not by the LLM.** The model only writes prose
descriptions. This guarantees every diagram reflects real code structure
and is syntactically valid; the LLM can never hallucinate a flow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .callgraph import CallGraph, FuncNode, endpoint_flow, is_branchy
from .detect import Change
from .draft import DocEdit
from . import llm

TIER1_INDEX = "docs/API.md"


def tier2_path(feature: str) -> str:
    return f"docs/features/{feature}.md"


# ---------------------------------------------------------------------------
# Diagrams — deterministic, grounded in the call graph
# ---------------------------------------------------------------------------

_MERMAID_TYPES = ("sequenceDiagram", "flowchart", "graph")


def validate_mermaid(text: str) -> bool:
    """Lightweight structural check: a safety net for any generated diagram."""
    if not text or not text.strip():
        return False
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return False
    header = lines[0].strip()
    if not header.startswith(_MERMAID_TYPES):
        return False
    if header.startswith("sequenceDiagram"):
        return any("->>" in ln or "-->>" in ln for ln in lines[1:])
    # flowchart/graph: need at least one edge
    return any("-->" in ln for ln in lines[1:])


def _mm_id(name: str) -> str:
    """Safe mermaid participant/node id from a function name."""
    return re.sub(r"[^A-Za-z0-9_]", "_", name) or "node"


def sequence_diagram(flow: list[FuncNode]) -> str | None:
    """Sequence diagram for an endpoint's call chain (handler->...->data)."""
    if len(flow) < 2:  # trivial passthrough — not worth a diagram
        return None
    route = flow[0]
    lines = ["sequenceDiagram", "    participant Client"]
    for n in flow:
        lines.append(f"    participant {_mm_id(n.simple)}")
    label = f"{route.http_method or 'CALL'} {route.route_path or route.simple}"
    lines.append(f"    Client->>{_mm_id(route.simple)}: {label}")
    for a, b in zip(flow, flow[1:]):
        lines.append(f"    {_mm_id(a.simple)}->>{_mm_id(b.simple)}: {b.simple}()")
    return "\n".join(lines)


def flowchart(func: FuncNode, graph: CallGraph) -> str | None:
    """Flowchart of a branchy function's resolved call steps (grounded).

    Targets branchy *orchestration* functions — those that branch AND call
    other functions. A function that branches on constants but calls nothing
    yields no call-flow chart (returns None); a sequence/flowchart of "no
    steps" would be noise, not documentation.
    """
    steps = [graph.resolve(c) for c in func.calls]
    steps = [s for s in steps if s is not None]
    # de-dup preserving order
    seen: set[str] = set()
    uniq = [s for s in steps if not (s.name in seen or seen.add(s.name))]
    if not uniq:
        return None
    lines = ["flowchart TD", f"    start([{func.simple}])"]
    prev = "start"
    for i, s in enumerate(uniq):
        nid = f"n{i}_{_mm_id(s.simple)}"
        lines.append(f"    {nid}[{s.simple}]")
        lines.append(f"    {prev} --> {nid}")
        prev = nid
    lines.append(f"    {prev} --> done([return])")
    return "\n".join(lines)


@dataclass
class Diagram:
    title: str
    mermaid: str


def render_diagrams(graph: CallGraph) -> list[Diagram]:
    """All grounded diagrams for a feature: sequence per non-trivial endpoint,
    flowchart per branchy non-route function. Invalid ones are dropped."""
    diagrams: list[Diagram] = []
    for route in graph.routes():
        flow = endpoint_flow(graph, route)
        mm = sequence_diagram(flow)
        if mm and validate_mermaid(mm):
            title = f"{route.http_method or 'CALL'} {route.route_path or route.simple}"
            diagrams.append(Diagram(title=title, mermaid=mm))
    for node in graph.nodes.values():
        if node.is_route or not is_branchy(node):
            continue
        mm = flowchart(node, graph)
        if mm and validate_mermaid(mm):
            diagrams.append(Diagram(title=f"{node.simple}()", mermaid=mm))
    return diagrams


# ---------------------------------------------------------------------------
# Tier 2 — per-feature deep-dive
# ---------------------------------------------------------------------------

_DEPRECATED_HEADING = "## Deprecated / Removed"


def _public_symbols(graph: CallGraph) -> list[FuncNode]:
    return [
        n
        for n in graph.nodes.values()
        if n.is_route or not n.simple.startswith("_")
    ]


def _key_internals(graph: CallGraph, public: list[FuncNode]) -> list[FuncNode]:
    """One level of callees of the public surface, excluding the public set."""
    public_names = {n.name for n in public}
    internals: dict[str, FuncNode] = {}
    for p in public:
        for callee in p.calls:
            t = graph.resolve(callee)
            if t and t.name not in public_names and t.name not in internals:
                internals[t.name] = t
    return list(internals.values())


def _describe(cfg, feature_name: str, node: FuncNode, mode: str = llm.INCREMENTAL) -> str:
    """One-line description of a symbol; LLM-enriched when available.

    `mode` selects the provider: "backfill" uses the local model only,
    "incremental" uses Gemini (see agent/llm.py).
    """
    text = llm.generate_text(
        cfg,
        f"In one concise sentence, describe what this {feature_name} "
        f"{'endpoint' if node.is_route else 'function'} does. "
        f"Name: {node.name}. Respond with only the sentence.",
        mode=mode,
    )
    if text:
        return text.strip().splitlines()[0]
    # Stub description (deterministic, offline).
    if node.is_route:
        return f"Handles `{node.http_method} {node.route_path}`."
    return f"`{node.simple}()` — see source for details."


def _existing_deprecated(existing_doc: str) -> list[str]:
    """Carry forward any previously-recorded deprecated lines."""
    if _DEPRECATED_HEADING not in existing_doc:
        return []
    tail = existing_doc.split(_DEPRECATED_HEADING, 1)[1]
    lines = []
    for ln in tail.splitlines():
        if ln.startswith("## "):  # next section
            break
        if ln.strip().startswith("- "):
            lines.append(ln.strip())
    return lines


def render_tier2(
    feature: str,
    display_name: str,
    graph: CallGraph,
    changes: list[Change],
    existing_doc: str = "",
    cfg=None,
    mode: str = llm.INCREMENTAL,
) -> DocEdit:
    """Assemble the feature's Tier-2 doc. Diagrams grounded; prose optional.

    `mode` is forwarded to the LLM helper: "backfill" keeps generation on
    the local model only; "incremental" uses Gemini.
    """
    public = _public_symbols(graph)
    internals = _key_internals(graph, public)
    diagrams = render_diagrams(graph)

    routes = [n for n in public if n.is_route]
    funcs = [n for n in public if not n.is_route]

    out: list[str] = [f"# {display_name}", ""]
    out.append(f"_Auto-generated feature documentation for `{feature}/`._")
    out.append("")

    if routes:
        out.append("## Endpoints")
        out.append("")
        for r in sorted(routes, key=lambda n: (n.route_path or "", n.http_method or "")):
            out.append(f"### {r.http_method} {r.route_path}")
            out.append("")
            out.append(_describe(cfg, display_name, r, mode))
            out.append("")

    if funcs:
        out.append("## Functions")
        out.append("")
        for f in sorted(funcs, key=lambda n: n.name):
            out.append(f"### `{f.name}`")
            out.append("")
            out.append(_describe(cfg, display_name, f, mode))
            out.append("")

    if internals:
        out.append("## Key internals")
        out.append("")
        for n in sorted(internals, key=lambda n: n.name):
            out.append(f"- `{n.name}` — called by the public surface.")
        out.append("")

    if diagrams:
        out.append("## Diagrams")
        out.append("")
        for d in diagrams:
            out.append(f"### {d.title}")
            out.append("")
            out.append("```mermaid")
            out.append(d.mermaid)
            out.append("```")
            out.append("")

    # Deprecations: carry forward existing + add newly-removed symbols.
    deprecated = _existing_deprecated(existing_doc)
    for c in changes:
        if c.status == "removed":
            sym = c.before
            label = sym.describe().splitlines()[0] if sym else c.key
            entry = f"- ~~{label}~~ (removed)"
            if entry not in deprecated:
                deprecated.append(entry)
    if deprecated:
        out.append(_DEPRECATED_HEADING)
        out.append("")
        out.extend(deprecated)
        out.append("")

    content = "\n".join(out).rstrip() + "\n"
    return DocEdit(
        path=tier2_path(feature),
        kind="markdown",
        updated_content=content,
        rationale=(
            f"Updated {display_name} feature docs: {len(public)} public "
            f"symbol(s), {len(diagrams)} diagram(s)."
        ),
    )


# ---------------------------------------------------------------------------
# Tier 1 — main index upsert
# ---------------------------------------------------------------------------

def _tier1_section(display_name: str, feature: str, summary: str) -> str:
    link = tier2_path(feature).replace("docs/", "")  # relative to docs/API.md
    return (
        f"## {display_name}\n\n"
        f"{summary}\n\n"
        f"See [detailed documentation]({link}).\n"
    )


def update_tier1(
    index_content: str, feature: str, display_name: str, summary: str
) -> DocEdit:
    """Upsert the feature's entry in the main API index. Idempotent by name."""
    section = _tier1_section(display_name, feature, summary)
    heading = f"## {display_name}"

    if not index_content.strip():
        content = "# API Documentation\n\n" + section
    elif heading in index_content:
        # Replace the existing section (from its heading to the next ## / EOF).
        pattern = re.compile(
            rf"(?ms)^{re.escape(heading)}\s.*?(?=^## |\Z)"
        )
        content = pattern.sub(section.rstrip() + "\n\n", index_content, count=1)
    else:
        content = index_content.rstrip() + "\n\n" + section

    content = content.rstrip() + "\n"
    return DocEdit(
        path=TIER1_INDEX,
        kind="markdown",
        updated_content=content,
        rationale=f"Upserted '{display_name}' entry in the API index.",
    )
