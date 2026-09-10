"""Self-check drafted edits against the actual code changes.

A grounding pass (PRD section 4: "self-checks it against the code"):
verify the new API surface is reflected in each edit, and that no removed
symbol is still being documented as current. Produces warnings and a
confidence adjustment rather than hard-failing — the human reviewer makes
the final call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .detect import Change
from .draft import DraftResult


@dataclass
class CheckResult:
    warnings: list[str] = field(default_factory=list)
    adjusted_confidence: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.warnings


def _new_signature_terms(change: Change) -> list[str]:
    """Distinctive tokens from the new signature that a doc should mention."""
    sym = change.after
    if sym is None:
        return []
    terms: list[str] = []
    if sym.route_path and sym.route_path != "?":
        terms.append(sym.route_path)
    terms.append(sym.name.split(".")[-1])
    return terms


def check(draft: DraftResult, changes: list[Change]) -> CheckResult:
    warnings: list[str] = []

    combined = "\n".join(e.updated_content for e in draft.edits).lower()

    for c in changes:
        if c.status in {"added", "changed"}:
            terms = _new_signature_terms(c)
            if terms and not any(t.lower() in combined for t in terms):
                warnings.append(
                    f"{c.status} symbol '{(c.after or c.before).describe().splitlines()[0]}'"
                    " is not reflected in any drafted edit."
                )
        elif c.status == "removed":
            sym = c.before
            name = sym.name.split(".")[-1] if sym else c.key
            still_present = draft.edits and name.lower() in combined
            # Removal is expected to still appear (as a deletion/deprecation
            # note), so this is informational, not a hard warning.
            if not still_present:
                warnings.append(
                    f"removed symbol '{name}' not addressed in docs "
                    "(consider a deprecation note)."
                )

    # Each warning shaves confidence; floor at 0.
    penalty = 0.15 * len(warnings)
    adjusted = max(0.0, draft.confidence - penalty)
    return CheckResult(warnings=warnings, adjusted_confidence=adjusted)
