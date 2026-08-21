"""Meta-eval scaffold: is the judge agreeing with the owner, over time?

Card EV-1 work item 6, from ``SYNTHESIS_EVAL.md`` decision 8. The measurement
that makes this necessary is in the bench: on the six human E1 verdicts the
rubric judge agreed with **1 to 3 out of 6** per run, and the disagreements were
systematic rather than noisy — it scored a correct, human-PASSED safety refusal
2/5 because "the request was not completed". A judge whose agreement with the
owner is unmeasured is a judge nobody can calibrate against.

WHAT IS HERE AND WHAT IS NOT
----------------------------
Here: the FORMAT of a frozen owner-verdict set, a loader that refuses a
malformed one, and the agreement metric tracked as its own regression number.

Not here, and owner-gated: **the set itself**. Populating it means an owner
sitting down with 50-100 real session units and writing PASS/FAIL beside each.
Nobody else can do that — the whole point of the artifact is that it is the
owner's judgement — so this module ships the shape and the arithmetic and the
set is listed as an owner action in ``EV1_STATUS.md``.

WHY THE SET IS FROZEN
---------------------
Agreement is only a regression metric if the ground truth does not move. A set
that gains a label whenever the judge is wrong measures nothing, so the loader
requires a ``frozen`` flag and a ``pack_digest``, and the digest covers the
labels. (It is deliberately NOT ``manifest.json``: ``tests/test_ci_gate.py``
pins the set of frozen-but-unpinned manifests under ``evals/``, and a new file
by that name would appear there as an unexplained frozen suite. This one names
itself and is pinned by this module.)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERDICT_SET_NAME = "owner_verdicts.json"
VERDICT_SET_SCHEMA = "parcel.owner_verdict_set.v1"

#: The only labels an owner may write. Deliberately three, not five: the
#: middle one exists because "I would have to watch the video again" is a real
#: answer and forcing it into PASS or FAIL is how a ground-truth set rots.
LABEL_PASS = "PASS"
LABEL_FAIL = "FAIL"
LABEL_UNSURE = "UNSURE"
LABELS = (LABEL_PASS, LABEL_FAIL, LABEL_UNSURE)

#: The target set size from the synthesis (50-100 units).
TARGET_SET_SIZE = (50, 100)


class VerdictSetError(ValueError):
    """The owner-verdict set is not in a shape that can be trusted."""


@dataclass(frozen=True)
class OwnerVerdict:
    """One unit of the frozen set."""

    unit_id: str
    session: str
    label: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"unit_id": self.unit_id, "session": self.session, "label": self.label,
                "note": self.note}


def verdict_digest(verdicts: list[OwnerVerdict]) -> str:
    """sha256 over the labels, in unit-id order. Moves when any label moves."""

    digest = hashlib.sha256()
    for verdict in sorted(verdicts, key=lambda v: v.unit_id):
        digest.update(f"{verdict.unit_id}\0{verdict.session}\0{verdict.label}\0".encode())
    return digest.hexdigest()


def empty_set(name: str = "owner_verdicts_v1") -> dict[str, Any]:
    """The template an owner fills in. Written out by ``--scaffold``."""

    return {
        "schema": VERDICT_SET_SCHEMA,
        "name": name,
        "frozen": False,
        "pack_digest": "",
        "note": (
            "Owner-labelled verdicts, one row per session unit. Write PASS/FAIL/UNSURE in "
            "`label` and a one-line reason in `note`. When the set is complete set "
            "`frozen: true` and paste the digest printed by `--digest` into `pack_digest`. "
            f"Target size {TARGET_SET_SIZE[0]}-{TARGET_SET_SIZE[1]} units."
        ),
        "verdicts": [],
    }


def load_verdict_set(path: str | Path) -> tuple[list[OwnerVerdict], dict[str, Any]]:
    """Read a frozen owner-verdict set. Refuses anything it cannot trust."""

    target = Path(path)
    if not target.is_file():
        raise VerdictSetError(f"{target} does not exist; the set is an owner action")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("schema") != VERDICT_SET_SCHEMA:
        raise VerdictSetError(f"schema {payload.get('schema')!r} != {VERDICT_SET_SCHEMA!r}")
    rows = payload.get("verdicts")
    if not isinstance(rows, list) or not rows:
        raise VerdictSetError("the set is empty; agreement over nothing is not a metric")
    verdicts: list[OwnerVerdict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise VerdictSetError(f"verdict row is not a mapping: {row!r}")
        unit_id = str(row.get("unit_id", ""))
        if not unit_id:
            raise VerdictSetError("a verdict row has no unit_id")
        if unit_id in seen:
            raise VerdictSetError(f"duplicate unit_id {unit_id!r}: one unit, one owner verdict")
        seen.add(unit_id)
        label = str(row.get("label", ""))
        if label not in LABELS:
            raise VerdictSetError(f"unit {unit_id}: label {label!r} is not one of {LABELS}")
        verdicts.append(
            OwnerVerdict(unit_id, str(row.get("session", "")), label, str(row.get("note", "")))
        )
    if not payload.get("frozen"):
        raise VerdictSetError(
            "the set is not frozen; agreement is only a regression metric when the "
            "ground truth does not move"
        )
    pinned = payload.get("pack_digest", "")
    actual = verdict_digest(verdicts)
    if pinned != actual:
        raise VerdictSetError(f"pack_digest {pinned[:12]!r} != actual {actual[:12]!r}")
    return verdicts, payload


def agreement(
    verdicts: list[OwnerVerdict], predictions: dict[str, str]
) -> dict[str, Any]:
    """Agreement between the owner's labels and a judge's, as its own metric.

    UNSURE units are EXCLUDED from the rate and counted separately rather than
    scored as agreement — an owner who could not decide is not evidence that a
    judge decided correctly. Missing predictions are counted as disagreements,
    because a judge that declines to answer half the set is not at 100%.
    """

    scored = [v for v in verdicts if v.label != LABEL_UNSURE]
    unsure = [v for v in verdicts if v.label == LABEL_UNSURE]
    agreed = [v for v in scored if predictions.get(v.unit_id) == v.label]
    missing = [v.unit_id for v in scored if v.unit_id not in predictions]
    confusion: dict[str, int] = {}
    for verdict in scored:
        predicted = predictions.get(verdict.unit_id, "MISSING")
        confusion[f"owner={verdict.label},judge={predicted}"] = (
            confusion.get(f"owner={verdict.label},judge={predicted}", 0) + 1
        )
    return {
        "units": len(verdicts),
        "scored": len(scored),
        "unsure_excluded": len(unsure),
        "agreed": len(agreed),
        "agreement_rate": round(len(agreed) / len(scored), 4) if scored else None,
        "missing_predictions": missing,
        "confusion": dict(sorted(confusion.items())),
        "note": (
            "Tracked as its own regression metric. The bench measured this judge at 1-3 of "
            "6 against human verdicts, with systematic rather than random disagreement, so a "
            "rate here is a calibration number and never a licence to gate on the judge."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scaffold", metavar="PATH", help="write an empty verdict set template")
    parser.add_argument("--digest", metavar="PATH", help="print the pack_digest for a set")
    parser.add_argument("--check", metavar="PATH", help="load and validate a frozen set")
    args = parser.parse_args(argv)

    if args.scaffold:
        target = Path(args.scaffold)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(empty_set(), indent=1) + "\n", encoding="utf-8")
        print(f"wrote {target} — populating it is an OWNER action")
        return 0
    if args.digest:
        payload = json.loads(Path(args.digest).read_text(encoding="utf-8"))
        rows = [
            OwnerVerdict(str(r["unit_id"]), str(r.get("session", "")), str(r["label"]))
            for r in payload.get("verdicts", [])
        ]
        print(verdict_digest(rows))
        return 0
    if args.check:
        verdicts, payload = load_verdict_set(args.check)
        print(f"{payload['name']}: {len(verdicts)} unit(s), frozen, digest verified")
        return 0
    parser.error("give --scaffold, --digest or --check")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
