"""Score the detector against the labeled eval suite (PRD Phase 2).

    python run_eval.py            # print scorecard, write out/eval_report.json
    python run_eval.py --json     # machine-readable only

Exit code is non-zero if recall falls below the PRD target (default 0.90),
so this can gate CI.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval import harness

TARGET_RECALL = 0.90


def _fmt_labels(labels: set[tuple[str, str]]) -> str:
    return ", ".join(f"{s}:{k}" for s, k in sorted(labels)) or "—"


def print_scorecard(card: harness.Scorecard, target: float) -> None:
    print("\n=== API-Change Detection Eval ===\n")
    name_w = max((len(c.name) for c in card.cases), default=4)
    print(f"{'CASE':<{name_w}}  RESULT  DETAIL")
    print(f"{'-' * name_w}  ------  ------")
    for c in card.cases:
        if c.passed:
            print(f"{c.name:<{name_w}}  PASS")
        else:
            bits = []
            if c.false_negatives:
                bits.append(f"missed [{_fmt_labels(c.false_negatives)}]")
            if c.false_positives:
                bits.append(f"spurious [{_fmt_labels(c.false_positives)}]")
            print(f"{c.name:<{name_w}}  FAIL    " + "; ".join(bits))

    print(
        f"\nCases: {card.cases_passed}/{len(card.cases)} exact-match"
        f"   |   TP={card.tp} FP={card.fp} FN={card.fn}"
    )
    print(
        f"Precision: {card.precision:.2%}   "
        f"Recall: {card.recall:.2%}   "
        f"F1: {card.f1:.2%}"
    )
    meets = card.recall >= target
    verdict = "MEETS" if meets else "BELOW"
    print(
        f"\nPRD target — recall ≥ {target:.0%}: {verdict} "
        f"({card.recall:.2%})\n"
    )


def build_report(card: harness.Scorecard, target: float) -> dict:
    return {
        "target_recall": target,
        "meets_target": card.recall >= target,
        "totals": {
            "cases": len(card.cases),
            "cases_passed": card.cases_passed,
            "tp": card.tp,
            "fp": card.fp,
            "fn": card.fn,
            "precision": round(card.precision, 4),
            "recall": round(card.recall, 4),
            "f1": round(card.f1, 4),
        },
        "cases": [
            {
                "name": c.name,
                "description": c.description,
                "passed": c.passed,
                "expected": sorted(list(c.expected)),
                "detected": sorted(list(c.detected)),
                "false_negatives": sorted(list(c.false_negatives)),
                "false_positives": sorted(list(c.false_positives)),
            }
            for c in card.cases
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument("--target", type=float, default=TARGET_RECALL)
    parser.add_argument("--out", default="out/eval_report.json")
    args = parser.parse_args()

    card = harness.run_all()
    report = build_report(card, args.target)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_scorecard(card, args.target)
        print(f"Report written to: {args.out}")

    return 0 if report["meets_target"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
