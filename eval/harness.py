"""Eval harness: score the detector against a labeled test set of "PRs".

Each case is a directory under `eval/cases/<name>/` containing:

    before.py      the code before the change   (omit for an added file)
    after.py       the code after the change     (omit for a deleted file)
    expected.json  {"description": ..., "expected": [{"status","key"}, ...]}

`status`/`key` match `agent.detect.Change.status` and `.key`
(e.g. "route POST /users", "func UserAPI.list"). We run the detector on
each before/after pair and compare the produced (status, key) set against
the labeled set, aggregating precision / recall / F1.

The PRD's success metric is recall-oriented — "correctly identifies ≥ 90%
of API-surface-relevant changes" — so `recall` is the headline number,
with precision reported alongside to catch over-flagging.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import detect  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent / "cases"

# A "label" is a (status, key) pair identifying one expected change.
Label = tuple[str, str]


@dataclass
class CaseResult:
    name: str
    description: str
    expected: set[Label]
    detected: set[Label]

    @property
    def true_positives(self) -> set[Label]:
        return self.expected & self.detected

    @property
    def false_positives(self) -> set[Label]:
        return self.detected - self.expected

    @property
    def false_negatives(self) -> set[Label]:
        return self.expected - self.detected

    @property
    def passed(self) -> bool:
        """Exact match: nothing missed, nothing spurious."""
        return not self.false_positives and not self.false_negatives


@dataclass
class Scorecard:
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def tp(self) -> int:
        return sum(len(c.true_positives) for c in self.cases)

    @property
    def fp(self) -> int:
        return sum(len(c.false_positives) for c in self.cases)

    @property
    def fn(self) -> int:
        return sum(len(c.false_negatives) for c in self.cases)

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def cases_passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)


def _read(path: Path) -> str | None:
    return path.read_text() if path.exists() else None


def run_case(case_dir: Path) -> CaseResult:
    spec = json.loads((case_dir / "expected.json").read_text())
    expected: set[Label] = {
        (e["status"], e["key"]) for e in spec.get("expected", [])
    }

    before = _read(case_dir / "before.py")
    after = _read(case_dir / "after.py")
    changes = detect.detect_file_changes(before, after)
    detected: set[Label] = {(c.status, c.key) for c in changes}

    return CaseResult(
        name=case_dir.name,
        description=spec.get("description", ""),
        expected=expected,
        detected=detected,
    )


def run_all(cases_dir: Path = CASES_DIR) -> Scorecard:
    card = Scorecard()
    for case_dir in sorted(p for p in cases_dir.iterdir() if p.is_dir()):
        if (case_dir / "expected.json").exists():
            card.cases.append(run_case(case_dir))
    return card
