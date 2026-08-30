#!/usr/bin/env python
"""Independent deterministic verifier for the MB-1 hosted checkpoint/output."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
if str(FOLDER) not in sys.path:
    sys.path.insert(0, str(FOLDER))

import events as ev
import run
import scorer as sc


def _prefix_matches(ledger: bytes, evidence: dict[str, object]) -> bool:
    size = int(evidence["bytes"])
    prefix = ledger[:size]
    return len(prefix) == size and hashlib.sha256(prefix).hexdigest() == evidence["sha256"]


def verify(checkpoint_path: Path, result_path: Path) -> dict[str, object]:
    corpus = ev.build_corpus()
    arms = ("Q", "D")
    fingerprint, config = run._hosted_fingerprint(
        corpus, seed=20260829, cap_usd=4.5, samples=3, arms=arms
    )
    checkpoint = run._read_hosted_checkpoint(
        checkpoint_path, fingerprint=fingerprint, config=config, resume=True
    )
    completed = checkpoint["completed"]
    expected = [
        run._completed_key(arm, sample, scenario.scenario_id)
        for arm in arms
        for sample in range(3)
        for scenario in corpus
    ]
    keys = [str(entry["key"]) for entry in completed]
    schedule_prefix_ok = keys == expected[: len(keys)]
    incomplete = checkpoint.get("incomplete", [])
    next_key_ok = not incomplete or all(
        entry.get("key") == expected[len(keys)] for entry in incomplete
    )

    ledger = run.WAVE_LEDGER.read_bytes()
    evidence_rows = [checkpoint["ledger_before"]]
    for entry in [*completed, *incomplete]:
        evidence_rows.extend((entry["ledger_before"], entry["ledger_after"]))
    ledger_prefixes_ok = all(_prefix_matches(ledger, evidence) for evidence in evidence_rows)

    database_ok = True
    recovery = checkpoint.get("recovery") or {}
    if recovery:
        database = Path(str(recovery["database"]))
        database_ok = (
            database.is_file()
            and hashlib.sha256(database.read_bytes()).hexdigest()
            == recovery["database_sha256"]
        )

    scenarios = {scenario.scenario_id: scenario for scenario in corpus}
    registry = sc.default_registry()
    results = [
        run._checkpoint_result(entry, scenarios=scenarios, registry=registry)
        for entry in completed
    ]
    recomputed = run._summarise(
        results, seed=20260829, arms=arms, tier="hosted-live", extra={}
    )
    published = json.loads(result_path.read_text(encoding="utf-8"))["stages"]["hosted"]
    summary_ok = (
        recomputed["arms"] == published["arms"]
        and recomputed["paired_delta"] == published["paired_delta"]
        and published["completed_scenarios"] == len(completed)
        and published["expected_scenarios"] == len(expected)
    )
    checkpoint_hash = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    result_hash = hashlib.sha256(result_path.read_bytes()).hexdigest()
    output_hash_link_ok = published["checkpoint_sha256"] == checkpoint_hash
    checks = {
        "entry_digests_and_fingerprint": True,
        "schedule_is_exact_prefix": schedule_prefix_ok,
        "incomplete_is_next_schedule_key": next_key_ok,
        "ledger_prefix_hashes": ledger_prefixes_ok,
        "recovery_database_hash": database_ok,
        "published_summary_recomputes": summary_ok,
        "published_checkpoint_hash": output_hash_link_ok,
    }
    return {
        "schema": "parcel.mb1.hosted_verification.v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "completed": len(completed),
        "expected": len(expected),
        "incomplete": [entry.get("key") for entry in incomplete],
        "checkpoint_sha256": checkpoint_hash,
        "result_sha256": result_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=FOLDER / "results/hosted-QD-full.checkpoint.json",
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=FOLDER / "results/hosted-QD-full.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=FOLDER / "results/hosted-QD-full.verification.json",
    )
    args = parser.parse_args()
    report = verify(args.checkpoint, args.result)
    run._atomic_json(args.output, report)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
