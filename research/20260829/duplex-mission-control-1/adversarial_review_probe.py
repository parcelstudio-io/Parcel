#!/usr/bin/env python3
"""Post-hoc counterexamples for DMC-1 receipt and narration validity."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from dmc_sim import (
    Command,
    ExplicitTemporalController,
    MissionSystem,
    NarrationFrame,
    ParsedSteering,
    Receipt,
    TaskLedger,
    generate_spec,
)


def canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run() -> dict[str, object]:
    target = "amber nook"
    ledger = TaskLedger({target: (1, 0)})
    command = Command(0, "immediate", f"go to {target}", target, "probe-task")
    parsed = ParsedSteering("immediate", target, 1.0, command.transcript)
    ledger.apply(parsed, command, 0)

    malformed_terminal = Receipt(
        receipt_id="malformed-terminal",
        task_id="probe-task",
        revision=1,
        step_id="wrong-step",
        attempt=999,
        status="completed",
        due_tick=1,
        terminal=True,
    )
    malformed_accepted, malformed_disposition, _ = ledger.accept_receipt(
        malformed_terminal, 1
    )
    post_terminal_started = Receipt(
        receipt_id="post-terminal-started",
        task_id="probe-task",
        revision=1,
        step_id="another-wrong-step",
        attempt=1_000,
        status="started",
        due_tick=2,
        terminal=False,
    )
    post_terminal_accepted, post_terminal_disposition, _ = ledger.accept_receipt(
        post_terminal_started, 2
    )

    spec = generate_spec(123, "train")
    mission = MissionSystem(
        "review-probe",
        spec,
        ExplicitTemporalController(),
        rng_seed=456,
    )
    mission.valid_terminal_receipts.add("trusted-unrelated-receipt")
    fabricated = NarrationFrame(
        event="completed",
        task_id="fabricated-task",
        revision=999,
        status="completed",
        tense="completed",
        receipt_id="trusted-unrelated-receipt",
        evidence="fabricated",
        resume_target="fabricated-resume-target",
    )
    fabricated_narration_accepted = mission._validate_narration(fabricated, 0)

    observations = {
        "wrong_step_and_attempt_terminal_accepted": malformed_accepted,
        "wrong_step_and_attempt_terminal_disposition": malformed_disposition,
        "post_terminal_started_accepted": post_terminal_accepted,
        "post_terminal_started_disposition": post_terminal_disposition,
        "fabricated_terminal_narration_accepted": fabricated_narration_accepted,
    }
    secure_expectations = {
        "wrong_step_and_attempt_terminal_rejected": not malformed_accepted,
        "post_terminal_started_rejected": not post_terminal_accepted,
        "fabricated_terminal_narration_rejected": not fabricated_narration_accepted,
    }
    result: dict[str, object] = {
        "schema": "parcel.dmc1.adversarial_review.v1",
        "evidence_class": "desktop_unit_counterexample_no_physics_no_audio_no_hardware_no_motion",
        "observations": observations,
        "secure_expectations": secure_expectations,
        "all_secure_expectations_met": all(secure_expectations.values()),
        "interpretation": "H3_AND_H4_UNVERIFIED" if not all(secure_expectations.values()) else "NO_COUNTEREXAMPLE_FOUND",
    }
    result["semantic_sha256"] = canonical_digest(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
