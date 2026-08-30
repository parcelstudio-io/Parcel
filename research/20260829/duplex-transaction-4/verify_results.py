#!/usr/bin/env python
"""Independent stdlib-only verifier for retained DMC-4 raw evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
MANIFEST_PATH = HERE / "manifest.json"
SOURCE_MANIFEST_PATH = HERE / "source_manifest.json"

STATUS_BY_DISPOSITION = {
    "task_queued": "accepted",
    "replacement_activated": "replanned",
    "replacement_deferred": "replanned",
    "replacement_activated_at_checkpoint": "replanned",
    "replacement_activated_after_step": "replanned",
    "step_dispatched": "started",
    "step_timeout_retry": "blocked",
    "step_timeout_failed": "failed",
    "waiting_precondition": "blocked",
    "waiting_resource": "blocked",
    "progress_recorded": "progress",
    "step_succeeded": "progress",
    "task_succeeded": "succeeded",
    "retry_scheduled": "blocked",
    "task_failed": "failed",
    "task_cancelled": "cancelled",
    "cancelled_at_checkpoint": "cancelled",
    "cancelled_after_step": "cancelled",
    "interrupt_cancelled": "cancelled",
    "interrupt_waiting_checkpoint": "blocked",
    "interrupt_suspended": "suspended",
    "task_suspended": "suspended",
    "task_resumed": "resumed",
    "task_resumed_running": "resumed",
}

CORRUPTION_REASON = {
    "duplicate_event": "event_already_consumed",
    "reordered_event": "event_sequence_regression",
    "stale_epoch": "source_epoch_mismatch",
    "stale_speech_generation": "speech_generation_mismatch",
    "expired_event": "event_expired",
    "future_event": "event_from_future",
    "tag_corruption": "event_authentication_failed",
    "task_mutation": "unknown_task",
    "revision_mutation": "task_lineage_mismatch",
    "step_mutation": "task_lineage_mismatch",
    "attempt_mutation": "task_lineage_mismatch",
    "plan_mutation": "task_lineage_mismatch",
    "action_mutation": "task_lineage_mismatch",
    "fact_mutation": "event_authentication_failed",
    "evidence_mutation": "event_authentication_failed",
    "post_terminal_transition": "post_terminal_event",
    "event_sequence_gap": "event_sequence_gap",
}

REQUIRED_OUTCOMES = {
    "submission:task_queued",
    "replacement:replacement_activated",
    "replacement:replacement_deferred",
    "replacement:replacement_activated_at_checkpoint",
    "replacement:replacement_activated_after_step",
    "tick:step_dispatched",
    "tick:step_timeout_retry",
    "tick:step_timeout_failed",
    "tick:waiting_precondition",
    "tick:waiting_resource",
    "report:progress_recorded",
    "report:step_succeeded",
    "report:task_succeeded",
    "report:retry_scheduled",
    "report:task_failed",
    "report:task_cancelled",
    "report:cancelled_at_checkpoint",
    "report:cancelled_after_step",
    "dispatch_failure:retry_scheduled",
    "dispatch_failure:task_failed",
    "interruption:interrupt_cancelled",
    "interruption:interrupt_waiting_checkpoint",
    "interruption:interrupt_suspended",
    "explicit_lifecycle:task_suspended",
    "explicit_lifecycle:task_resumed",
    "explicit_lifecycle:task_resumed_running",
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def _content_id(namespace: str, prefix: str, value: dict[str, object]) -> str:
    return f"{prefix}-{digest({'namespace': namespace, **value})[:24]}"


def _event_identity_ok(event: dict[str, object]) -> bool:
    try:
        mission = _content_id(
            "execution-narrative-mission-v1",
            "mission",
            {
                "task_id": event["task_id"],
                "plan_sha256": event["plan_sha256"],
            },
        )
        action = _content_id(
            "execution-narrative-action-v1",
            "action",
            {
                "mission_id": mission,
                "plan_revision": event["plan_revision"],
                "step_id": event["step_id"],
                "attempt": event["attempt"],
                "action_name": event["action_name"],
            },
        )
        payload = dict(event)
        event_id = payload.pop("event_id")
        derived = _content_id("execution-narrative-event-v1", "event", payload)
        return (
            event.get("schema_version") == 1
            and event.get("mission_id") == mission
            and event.get("action_id") == action
            and event_id == derived
        )
    except (KeyError, TypeError, ValueError):
        return False


def _chain(rows: list[dict[str, object]]) -> str:
    value = "0" * 64
    for row in rows:
        value = digest({"previous": value, "row": row})
    return value


def verify_source_manifest(
    source_manifest: dict[str, object],
    *,
    root: Path = REPO_ROOT,
) -> list[str]:
    errors: list[str] = []
    files = source_manifest.get("files")
    if not isinstance(files, dict):
        return ["source manifest file inventory missing"]
    for relative, expected in files.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            errors.append("source manifest entry malformed")
            continue
        path = root / relative
        if not path.is_file():
            errors.append(f"source file missing: {relative}")
        elif file_sha256(path) != expected:
            errors.append(f"source hash mismatch: {relative}")
    return errors


def _expected_case_ids(manifest: dict[str, object]) -> set[str]:
    count = int(manifest["cases_per_family"])
    parent = int(manifest["parent_child_cases"])
    corrupt = int(manifest["corruption_cases"])
    corruptions = [str(item) for item in manifest["corruptions"]]
    return (
        {
            f"h1h2-{family}-{trial:04d}"
            for family in manifest["transition_families"]
            for trial in range(count)
        }
        | {f"h2-parent-child-{trial:04d}" for trial in range(parent)}
        | {
            f"h3-{trial:04d}-{corruptions[trial % len(corruptions)]}"
            for trial in range(corrupt)
        }
        | {"h4-normal", "h4-forced-overflow"}
    )


def _journal_event_match(
    transition: dict[str, object],
    record: dict[str, object],
    *,
    parent_task_id: str | None,
) -> bool:
    event = record.get("event")
    consumer = record.get("consumer")
    replay = record.get("replay")
    if not isinstance(event, dict) or not isinstance(consumer, dict) or not isinstance(replay, dict):
        return False
    expected_status = STATUS_BY_DISPOSITION.get(str(transition.get("disposition")))
    exact = {
        "event_sequence": "transition_sequence",
        "task_id": "task_id",
        "plan_revision": "plan_revision",
        "step_id": "step_id",
        "attempt": "attempt",
        "plan_sha256": "plan_sha256",
        "action_name": "skill",
        "detail_code": "detail_code",
        "verified_facts": "verified_facts",
        "evidence_refs": "evidence_refs",
    }
    if any(event.get(left) != transition.get(right) for left, right in exact.items()):
        return False
    silent = transition.get("detail_code") == "unverified_success_claim"
    frame = consumer.get("frame")
    if silent:
        consumer_ok = (
            consumer.get("accepted") is True
            and consumer.get("reason") == "unverified_success_claim_consumed_silently"
            and frame is None
        )
    else:
        consumer_ok = (
            consumer.get("accepted") is True
            and isinstance(frame, dict)
            and frame.get("event_id") == event.get("event_id")
            and frame.get("status") == expected_status
            and frame.get("claimable_facts") == transition.get("verified_facts")
        )
    return (
        expected_status is not None
        and event.get("status") == expected_status
        and event.get("resume_parent_task_id") == parent_task_id
        and _event_identity_ok(event)
        and record.get("auth_verified") is True
        and record.get("authorizes_actuation") is False
        and consumer_ok
        and replay.get("accepted") is False
        and replay.get("reason") == "event_already_consumed"
        and replay.get("frame") is None
        and replay.get("state_unchanged") is True
    )


def _verify_transition_row(row: dict[str, object]) -> bool:
    expected = row.get("expected_ledger")
    journal_read = row.get("journal_read")
    events = row.get("events")
    if not isinstance(expected, list) or not isinstance(journal_read, dict) or not isinstance(events, list):
        return False
    journal = journal_read.get("transitions")
    if journal_read.get("status") != "ok" or not isinstance(journal, list):
        return False
    if expected != journal or len(events) != len(journal):
        return False
    parent_id = row.get("parent_task_id")
    child_id = row.get("child_task_id")
    if [item.get("transition_sequence") for item in journal if isinstance(item, dict)] != list(
        range(1, len(journal) + 1)
    ):
        return False
    for transition, event in zip(journal, events):
        if not isinstance(transition, dict) or not isinstance(event, dict):
            return False
        parent = str(parent_id) if transition.get("task_id") == child_id else None
        if not _journal_event_match(transition, event, parent_task_id=parent):
            return False
    status = row.get("journal_status")
    consumer_state = row.get("final_consumer_state")
    base_ok = (
        isinstance(status, dict)
        and status.get("latest_sequence") == len(journal)
        and status.get("retained") == len(journal)
        and status.get("overflow_count") == 0
        and isinstance(consumer_state, dict)
        and consumer_state.get("last_event_sequence") == len(journal)
    )
    if not base_ok:
        return False

    # These are separately retained observations of calls that must not mutate
    # the owner journal.  Exact ledger equality alone would not prove that the
    # negative calls were actually made.
    family = row.get("family")
    if family == "submission":
        tested = row.get("tested_dispositions")
        if not isinstance(tested, dict):
            return False
        admitted = tested.get("admitted")
        prior = tested.get("prior_active")
        capacity = tested.get("capacity")
        return (
            isinstance(admitted, dict)
            and admitted.get("accepted") is True
            and isinstance(prior, dict)
            and prior.get("accepted") is False
            and isinstance(capacity, dict)
            and capacity.get("accepted") is False
            and capacity.get("journal_delta") == 0
        )
    if family == "dispatch_failure":
        stale = row.get("stale_replay")
        return (
            isinstance(stale, dict)
            and stale.get("accepted") is False
            and stale.get("journal_delta") == 0
        )
    if family == "interruption":
        overlap = row.get("overlap")
        return (
            isinstance(overlap, dict)
            and overlap.get("action") == "overlap"
            and overlap.get("journal_delta") == 0
        )
    if family == "explicit_lifecycle":
        return row.get("rejected_or_noop_journal_delta") == 0
    if family == "interruption_stack":
        parent = str(parent_id)
        child = str(child_id)
        lineage = [
            (parent, "task_queued"),
            (parent, "step_dispatched"),
            (parent, "task_suspended"),
            (child, "task_queued"),
            (child, "step_dispatched"),
            (child, "progress_recorded"),
            (child, "task_succeeded"),
            (parent, "task_resumed"),
            (parent, "step_dispatched"),
        ]
        return [
            (str(item.get("task_id")), str(item.get("disposition")))
            for item in journal
            if isinstance(item, dict)
        ] == lineage
    return True


def _verify_corruption(row: dict[str, object]) -> bool:
    corruption = row.get("corruption")
    if corruption == "skipped_cursor":
        return (
            row.get("fault_code") == "journal_cursor_ahead"
            and row.get("post_fault_event_count") == 0
        )
    if corruption == "overwritten_cursor":
        read = row.get("journal_read")
        return (
            isinstance(read, dict)
            and read.get("status") == "overflow"
            and read.get("transitions") == []
            and row.get("fault_code") == "journal_overflow"
            and row.get("post_fault_event_count") == 0
        )
    if corruption == "narrative_queue_overflow":
        return (
            row.get("fault_code") == "narrative_queue_overflow"
            and row.get("retained_prefix_sequences") == [1]
            and row.get("prefix_consumer_sequence") == 1
            and row.get("post_fault_event_count") == 0
        )
    consumer = row.get("consumer")
    if corruption not in CORRUPTION_REASON or not isinstance(consumer, dict):
        return False
    event = row.get("tested_event")
    return (
        isinstance(event, dict)
        and _event_identity_ok(event)
        and consumer.get("accepted") is False
        and consumer.get("reason") == CORRUPTION_REASON[corruption]
        and consumer.get("frame") is None
        and consumer.get("state_unchanged") is True
    )


def _verify_concurrency(rows: list[dict[str, object]], manifest: dict[str, object]) -> bool:
    by_id = {row.get("case_id"): row for row in rows}
    normal = by_id.get("h4-normal")
    forced = by_id.get("h4-forced-overflow")
    if not isinstance(normal, dict) or not isinstance(forced, dict):
        return False
    count = int(manifest["producer_threads"])
    normal_status = normal.get("journal_status")
    forced_status = forced.get("journal_status")
    forced_observed = forced.get("observed")
    return (
        normal.get("errors") == []
        and normal.get("alive_threads") == []
        and normal.get("expected_ledger") == normal.get("observed")
        and isinstance(normal_status, dict)
        and normal_status.get("retained") == count
        and normal_status.get("latest_sequence") == count
        and normal_status.get("overflow_count") == 0
        and forced.get("errors") == []
        and forced.get("alive_threads") == []
        and isinstance(forced_status, dict)
        and forced_status.get("capacity") == int(manifest["overflow_journal_capacity"])
        and forced_status.get("retained") == int(manifest["overflow_journal_capacity"])
        and forced_status.get("latest_sequence") == count
        and forced_status.get("overflow_count") == count - int(manifest["overflow_journal_capacity"])
        and isinstance(forced_observed, list)
        and len(forced_observed) == 1
        and forced_observed[0].get("status") == "overflow"
        and forced_observed[0].get("transitions") == []
        and forced.get("bridge_fault") == "journal_overflow"
        and forced.get("post_fault_event_count") == 0
    )


def verify_one(result: dict[str, object], manifest: dict[str, object]) -> dict[str, object]:
    errors: list[str] = []
    if result.get("result_sha256") != digest(
        {key: value for key, value in result.items() if key != "result_sha256"}
    ):
        errors.append("result digest mismatch")
    if result.get("manifest_sha256") != file_sha256(MANIFEST_PATH):
        errors.append("manifest digest mismatch")
    if result.get("source_manifest_sha256") != file_sha256(SOURCE_MANIFEST_PATH):
        errors.append("source manifest digest mismatch")
    source_manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    errors.extend(verify_source_manifest(source_manifest))
    expected_population = {
        "cases_per_family": int(manifest["cases_per_family"]),
        "parent_child_cases": int(manifest["parent_child_cases"]),
        "corruption_cases": int(manifest["corruption_cases"]),
        "producer_threads": int(manifest["producer_threads"]),
    }
    if result.get("population") != expected_population:
        errors.append("population scalar mismatch")
    if (
        result.get("schema_version") != 1
        or result.get("experiment_id") != manifest.get("experiment_id")
        or result.get("seed") != manifest.get("seed")
    ):
        errors.append("experiment scalar mismatch")

    transition_rows = result.get("transition_rows")
    parent_rows = result.get("parent_child_rows")
    corruption_rows = result.get("corruption_rows")
    concurrency_rows = result.get("concurrency_rows")
    if not all(
        isinstance(value, list)
        for value in (transition_rows, parent_rows, corruption_rows, concurrency_rows)
    ):
        return {"passed": False, "errors": errors + ["raw row inventory missing"]}
    assert isinstance(transition_rows, list)
    assert isinstance(parent_rows, list)
    assert isinstance(corruption_rows, list)
    assert isinstance(concurrency_rows, list)
    all_rows = [*transition_rows, *parent_rows, *corruption_rows, *concurrency_rows]
    ids = [row.get("case_id") for row in all_rows if isinstance(row, dict)]
    if len(ids) != len(all_rows) or len(set(ids)) != len(ids) or set(ids) != _expected_case_ids(manifest):
        errors.append("case inventory mismatch")

    normalized = {
        "schema_version": result.get("schema_version"),
        "experiment_id": result.get("experiment_id"),
        "seed": result.get("seed"),
        "population": result.get("population"),
        "not_constructible": result.get("not_constructible"),
        "transition_rows": transition_rows,
        "parent_child_rows": parent_rows,
        "corruption_rows": corruption_rows,
        "concurrency_rows": concurrency_rows,
        "non_actuation": result.get("non_actuation"),
    }
    if result.get("normalized_trace_sha256") != digest(normalized):
        errors.append("normalized trace digest mismatch")
    typed_rows = [row for row in all_rows if isinstance(row, dict)]
    if result.get("trace_chain_root_sha256") != _chain(typed_rows):
        errors.append("trace chain root mismatch")

    family_counts = Counter(str(row.get("family")) for row in transition_rows if isinstance(row, dict))
    h1_rows_ok = all(
        isinstance(row, dict) and _verify_transition_row(row)
        for row in [*transition_rows, *parent_rows]
    )
    ledgers = [
        transition
        for row in [*transition_rows, *parent_rows]
        if isinstance(row, dict)
        for transition in row.get("journal_read", {}).get("transitions", [])
        if isinstance(transition, dict)
    ]
    outcome_counts = Counter(
        f"{item.get('family')}:{item.get('disposition')}" for item in ledgers
    )
    h1 = (
        h1_rows_ok
        and all(
            family_counts.get(str(family)) == int(manifest["cases_per_family"])
            for family in manifest["transition_families"]
        )
        and len(ledgers) >= 1024
        and REQUIRED_OUTCOMES <= set(outcome_counts)
        and result.get("not_constructible") == manifest.get("not_constructible")
    )
    # H2 is the same one-to-one rows plus parent/child exact context and replay.
    h2 = h1_rows_ok and len(parent_rows) == int(manifest["parent_child_cases"])
    corruption_coverage = Counter(
        str(row.get("corruption")) for row in corruption_rows if isinstance(row, dict)
    )
    h3 = (
        len(corruption_rows) == int(manifest["corruption_cases"])
        and set(corruption_coverage) == set(str(item) for item in manifest["corruptions"])
        and all(isinstance(row, dict) and _verify_corruption(row) for row in corruption_rows)
    )
    h4 = _verify_concurrency(
        [row for row in concurrency_rows if isinstance(row, dict)], manifest
    )
    non_actuation = result.get("non_actuation")
    h5_static = (
        isinstance(non_actuation, dict)
        and non_actuation.get("forbidden_imports") == []
        and all(
            value is False
            for value in non_actuation.get("authorizes_actuation", {}).values()
        )
    )
    if not h1:
        errors.append("H1 completeness oracle failed")
    if not h2:
        errors.append("H2 bridge oracle failed")
    if not h3:
        errors.append("H3 corruption oracle failed")
    if not h4:
        errors.append("H4 concurrency oracle failed")
    if not h5_static:
        errors.append("H5 static non-actuation oracle failed")
    peak = result.get("peak_rss_kib")
    if isinstance(peak, bool) or not isinstance(peak, int) or peak <= 0:
        errors.append("peak RSS missing")
    return {
        "passed": not errors and h1 and h2 and h3 and h4 and h5_static,
        "H1_passed": h1,
        "H2_passed": h2,
        "H3_passed": h3,
        "H4_passed": h4,
        "H5_static_passed": h5_static,
        "accepted_mutations": len(ledgers),
        "family_counts": dict(sorted(family_counts.items())),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "corruption_coverage": dict(sorted(corruption_coverage.items())),
        "normalized_trace_sha256": result.get("normalized_trace_sha256"),
        "trace_chain_root_sha256": result.get("trace_chain_root_sha256"),
        "peak_rss_kib": peak,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    checks = [
        verify_one(json.loads(path.read_text(encoding="utf-8")), manifest)
        for path in args.input
    ]
    repeat = (
        len(checks) == 2
        and len({item.get("normalized_trace_sha256") for item in checks}) == 1
        and len({item.get("trace_chain_root_sha256") for item in checks}) == 1
    )
    output = {
        "schema_version": 1,
        "inputs": [str(path) for path in args.input],
        "checks": checks,
        "two_run_digests_identical": repeat,
        "all_hypotheses_passed_twice": repeat
        and all(item.get("passed") is True for item in checks),
        "verifier_imports_parcel": False,
    }
    output["verification_sha256"] = digest(output)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
