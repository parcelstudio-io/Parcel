#!/usr/bin/env python3
"""Independent post-hoc verifier for the five retained LIT-1 fake traces.

This module intentionally imports only the standard library.  It does not import
the LIT-1 harness or reuse its grounding scorer.  The manifest freezes the five
already-produced traces and their content hashes; this audit is a refutation probe,
not a preregistered capability experiment.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} must contain an object")
        rows.append(value)
    return rows


def audit_trace(path: Path, expected_sha256: str, patterns: tuple[str, ...]) -> dict[str, Any]:
    actual_sha256 = sha256(path)
    if actual_sha256 != expected_sha256:
        raise ValueError(f"source drift for {path}: {actual_sha256} != {expected_sha256}")
    rows = load_jsonl(path)
    offers = [row for row in rows if row.get("hop") == "voice_offer"]
    if len(offers) != 1:
        raise ValueError(f"{path} must have exactly one voice_offer, got {len(offers)}")
    offer = offers[0]
    offer_t = float(offer["t"])
    text = str(offer.get("text", ""))
    arrival_claim = any(pattern.casefold() in text.casefold() for pattern in patterns)

    preceding_receipts = [
        row for row in rows if row.get("hop") == "receipt" and float(row["t"]) <= offer_t
    ]
    preceding_arrival = [
        row
        for row in rows
        if row.get("hop") == "arrival_authority"
        and row.get("step") == offer.get("step")
        and float(row["t"]) <= offer_t
    ]
    if not preceding_receipts or not preceding_arrival:
        raise ValueError(f"{path} lacks the receipt/arrival evidence preceding its offer")
    receipt = preceding_receipts[-1]
    arrival = preceding_arrival[-1]
    success_receipt_seen = any(row.get("kind") == "task_succeeded" for row in preceding_receipts)
    failed_receipt = receipt.get("kind") == "task_failed" and receipt.get("state") == "failed"
    independent_arrival_false = (
        arrival.get("scored") is True
        and arrival.get("system_arrival") is False
        and arrival.get("scorer_arrival") is False
    )
    false_terminal_arrival_claim = (
        arrival_claim and failed_receipt and independent_arrival_false and not success_receipt_seen
    )
    footers = [row for row in rows if row.get("hop") == "run_footer"]
    return {
        "path": str(path.relative_to(ROOT.parent)),
        "sha256": actual_sha256,
        "row_count": len(rows),
        "process_footer_ok": len(footers) == 1 and footers[0].get("ok") is True,
        "offer_t": offer_t,
        "offer_text": text,
        "offer_claimed_grounding": offer.get("grounded_in"),
        "preceding_receipt": {
            "kind": receipt.get("kind"),
            "state": receipt.get("state"),
            "detail": receipt.get("last_detail"),
            "task_id": receipt.get("task_id"),
            "plan_revision": receipt.get("plan_revision"),
        },
        "arrival_authority": {
            "goal": arrival.get("goal"),
            "system_arrival": arrival.get("system_arrival"),
            "scorer_arrival": arrival.get("scorer_arrival"),
            "distance_to_goal_m": arrival.get("distance_to_goal_m"),
        },
        "arrival_claim": arrival_claim,
        "success_receipt_seen": success_receipt_seen,
        "false_terminal_arrival_claim": false_terminal_arrival_claim,
    }


def main() -> int:
    manifest = load_json_object(MANIFEST)
    if manifest.get("schema") != "parcel.lit1-grounding-audit-manifest.v1":
        raise ValueError("unexpected manifest schema")
    raw_patterns = manifest.get("oracle", {}).get("terminal_arrival_claim_patterns")
    if not isinstance(raw_patterns, list) or not all(isinstance(item, str) for item in raw_patterns):
        raise ValueError("manifest oracle patterns must be strings")
    cases: list[dict[str, Any]] = []
    for item in manifest.get("files", []):
        if not isinstance(item, dict):
            raise ValueError("manifest files must contain objects")
        path = (ROOT / str(item["path"])).resolve()
        if ROOT.parent not in path.parents:
            raise ValueError(f"trace path escapes the research wave: {path}")
        cases.append(audit_trace(path, str(item["sha256"]), tuple(raw_patterns)))
    result = {
        "schema": "parcel.lit1-grounding-audit-result.v1",
        "evidence_class": "posthoc_adversarial_audit",
        "case_count": len(cases),
        "source_hashes_match": True,
        "process_footer_ok_count": sum(case["process_footer_ok"] for case in cases),
        "failed_terminal_before_offer_count": sum(
            case["preceding_receipt"]["kind"] == "task_failed" for case in cases
        ),
        "independent_nonarrival_count": sum(
            not case["arrival_authority"]["system_arrival"]
            and not case["arrival_authority"]["scorer_arrival"]
            for case in cases
        ),
        "false_terminal_arrival_claim_count": sum(
            case["false_terminal_arrival_claim"] for case in cases
        ),
        "all_cases_are_counterexamples": all(
            case["false_terminal_arrival_claim"] for case in cases
        ),
        "cases": cases,
        "verdict": "REFUTED_GROUNDING" if all(
            case["false_terminal_arrival_claim"] for case in cases
        ) else "MIXED",
        "does_not_prove": [
            "production Realtime behavior; the five traces use a scripted fake voice",
            "frequency outside the frozen five retained traces",
            "a physical or hosted model failure rate",
        ],
    }
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

