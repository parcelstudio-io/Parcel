#!/usr/bin/env python
"""Independent, stdlib-only DMC-3 trace verifier.

This module intentionally does not import Parcel's bridge, executive,
authenticator, or consumer.  It recomputes the frozen inventory, content
identities, lifecycle oracle, state digests, and normalized trace digest from
serialized evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "manifest.json"

H2_REASON = {
    "unknown_task_result": "no_event_minted",
    "wrong_revision_result": "no_event_minted",
    "wrong_step_result": "no_event_minted",
    "wrong_attempt_result": "no_event_minted",
    "late_old_step_result": "no_event_minted",
    "post_terminal_result": "no_event_minted",
    "missing_success_fact": "unverified_success_claim_consumed_silently",
    "altered_event_payload": "event_authentication_failed",
    "altered_event_tag": "event_authentication_failed",
    "duplicate_event": "event_already_consumed",
    "event_sequence_regression": "event_sequence_regression",
    "wrong_source_epoch": "source_epoch_mismatch",
    "future_event": "event_from_future",
    "expired_event": "event_expired",
    "old_speech_generation": "speech_generation_mismatch",
    "new_speech_generation": "speech_generation_mismatch",
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
        derived_event = _content_id(
            "execution-narrative-event-v1",
            "event",
            payload,
        )
        return (
            event.get("schema_version") == 1
            and event.get("mission_id") == mission
            and event.get("action_id") == action
            and event_id == derived_event
        )
    except (KeyError, TypeError, ValueError):
        return False


def _contains_forbidden_secret(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"auth_tag", "key", "secret"} or _contains_forbidden_secret(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_secret(item) for item in value)
    return False


def _task(snapshot: dict[str, object], task_id: str) -> dict[str, object] | None:
    tasks = snapshot.get("tasks")
    if not isinstance(tasks, list):
        return None
    matches = [item for item in tasks if isinstance(item, dict) and item.get("task_id") == task_id]
    return matches[0] if len(matches) == 1 else None


def _chain(rows: list[dict[str, object]]) -> str:
    value = "0" * 64
    for row in rows:
        value = digest({"previous": value, "row": row})
    return value


def expected_ids(manifest: dict[str, object]) -> set[str]:
    corruptions = [str(item) for item in manifest["h2_corruptions"]]
    return (
        {f"h1-{trial:04d}" for trial in range(int(manifest["h1_trials"]))}
        | {
            f"h2-{trial:04d}-{corruptions[trial % len(corruptions)]}"
            for trial in range(int(manifest["h2_trials"]))
        }
        | {f"h3-{trial:04d}" for trial in range(int(manifest["h3_trials"]))}
    )


def _verify_event_record(record: dict[str, object], sequence: int) -> bool:
    event = record.get("event")
    consumer = record.get("consumer")
    if not isinstance(event, dict) or not isinstance(consumer, dict):
        return False
    frame = consumer.get("frame")
    return (
        _event_identity_ok(event)
        and event.get("event_sequence") == sequence
        and record.get("auth_verified") is True
        and record.get("authorizes_actuation") is False
        and consumer.get("accepted") is True
        and isinstance(frame, dict)
        and frame.get("event_id") == event.get("event_id")
        and frame.get("claimable_facts") == event.get("verified_facts")
        and frame.get("constraints")
        == [
            "wording_only",
            "no_actuation",
            "do_not_infer_unlisted_observations",
            "do_not_claim_completion_without_listed_facts",
        ]
    )


def _verify_h1(row: dict[str, object]) -> bool:
    events = row.get("events")
    inputs = row.get("input")
    dispositions = row.get("dispositions")
    if not isinstance(events, list) or not isinstance(inputs, list) or not isinstance(dispositions, list):
        return False
    if len(events) != 4 or len(inputs) != 4 or len(dispositions) != 4:
        return False
    serialized = [record.get("event") for record in events]
    if not all(isinstance(event, dict) for event in serialized):
        return False
    statuses = [event.get("status") for event in serialized if isinstance(event, dict)]
    if statuses != ["accepted", "started", "progress", "succeeded"]:
        return False
    if not all(_verify_event_record(record, index) for index, record in enumerate(events, 1)):
        return False
    task_ids = {event.get("task_id") for event in serialized if isinstance(event, dict)}
    revisions = {event.get("plan_revision") for event in serialized if isinstance(event, dict)}
    steps = {event.get("step_id") for event in serialized if isinstance(event, dict)}
    attempts = {event.get("attempt") for event in serialized if isinstance(event, dict)}
    success_event = serialized[-1]
    success_input = inputs[-1].get("value") if isinstance(inputs[-1], dict) else None
    if not isinstance(success_event, dict) or not isinstance(success_input, dict):
        return False
    success_facts = success_input.get("verified_facts")
    if not isinstance(success_facts, list) or not success_facts:
        return False
    post = row.get("executive_after")
    if not isinstance(post, dict):
        return False
    task_id = next(iter(task_ids), None)
    task = _task(post, str(task_id))
    return (
        len(task_ids) == len(revisions) == len(steps) == len(attempts) == 1
        and success_event.get("verified_facts") == success_facts
        and any(
            isinstance(fact, dict) and fact.get("fact") == "motion_stopped"
            for fact in success_facts
        )
        and isinstance(task, dict)
        and task.get("state") == "succeeded"
        and dispositions[0].get("accepted") is True
        and dispositions[2].get("accepted") is True
        and dispositions[3].get("accepted") is True
    )


def _verify_h2(row: dict[str, object]) -> bool:
    corruption = row.get("corruption")
    consumer = row.get("consumer")
    if corruption not in H2_REASON or not isinstance(consumer, dict):
        return False
    expected_accepted = corruption == "missing_success_fact"
    if (
        consumer.get("accepted") is not expected_accepted
        or consumer.get("reason") != H2_REASON[corruption]
        or consumer.get("frame") is not None
    ):
        return False
    if corruption != "missing_success_fact" and digest(
        consumer.get("state_before")
    ) != digest(consumer.get("state_after")):
        return False
    tested_event = row.get("tested_event")
    if isinstance(tested_event, dict):
        if not _event_identity_ok(tested_event) or tested_event.get("status") == "succeeded":
            return False
    disposition = row.get("tested_disposition")
    if not isinstance(disposition, dict):
        return False
    result_cases = {
        "unknown_task_result",
        "wrong_revision_result",
        "wrong_step_result",
        "wrong_attempt_result",
        "late_old_step_result",
        "post_terminal_result",
    }
    if corruption in result_cases:
        if disposition.get("accepted") is not False or tested_event is not None:
            return False
        before = row.get("executive_before")
        after = row.get("executive_after")
        if digest(before) != digest(after):
            return False
    if corruption == "missing_success_fact":
        if (
            disposition.get("accepted") is not True
            or disposition.get("action") != "task_failed"
            or not isinstance(tested_event, dict)
            or tested_event.get("status") != "failed"
            or tested_event.get("verified_facts") != []
        ):
            return False
        before_state = consumer.get("state_before")
        after_state = consumer.get("state_after")
        if not isinstance(before_state, dict) or not isinstance(after_state, dict):
            return False
        event_sequence = tested_event.get("event_sequence")
        if (
            not isinstance(event_sequence, int)
            or before_state.get("last_event_sequence") != event_sequence - 1
            or after_state.get("last_event_sequence") != event_sequence
            or tested_event.get("event_id") not in after_state.get("seen_event_ids", [])
        ):
            return False
        tasks = after_state.get("tasks")
        if not isinstance(tasks, list) or not any(
            isinstance(task, dict)
            and task.get("task_id") == tested_event.get("task_id")
            and task.get("phase") == "failed"
            for task in tasks
        ):
            return False
        replay = row.get("replay")
        if not isinstance(replay, dict) or (
            replay.get("accepted") is not False
            or replay.get("reason") != "event_already_consumed"
            or replay.get("frame") is not None
            or replay.get("state_unchanged") is not True
        ):
            return False
        continuation = row.get("continuation")
        if not isinstance(continuation, dict):
            return False
        continuation_event = continuation.get("event")
        continuation_consumer = continuation.get("consumer")
        continuation_disposition = continuation.get("disposition")
        if (
            not isinstance(continuation_event, dict)
            or not isinstance(continuation_consumer, dict)
            or not isinstance(continuation_disposition, dict)
            or not _event_identity_ok(continuation_event)
            or continuation_event.get("event_sequence") != event_sequence + 1
            or continuation_event.get("task_id") == tested_event.get("task_id")
            or continuation_event.get("status") != "accepted"
            or continuation.get("auth_verified") is not True
            or continuation.get("authorizes_actuation") is not False
            or continuation_disposition.get("accepted") is not True
            or continuation_consumer.get("accepted") is not True
            or not isinstance(continuation_consumer.get("frame"), dict)
        ):
            return False
    elif row.get("replay") is not None or row.get("continuation") is not None:
        return False
    auth_expected = corruption not in {"altered_event_payload", "altered_event_tag"}
    if corruption not in result_cases and corruption != "missing_success_fact":
        if row.get("tested_event_auth_verified") is not auth_expected:
            return False
    return True


def _fact_present(event: dict[str, object], fact_name: str, target: str) -> bool:
    facts = event.get("verified_facts")
    return isinstance(facts, list) and any(
        isinstance(fact, dict)
        and fact.get("fact") == fact_name
        and fact.get("target") == target
        for fact in facts
    )


def _verify_h3(row: dict[str, object]) -> bool:
    events = row.get("events")
    parent_id = row.get("parent_task_id")
    child_id = row.get("child_task_id")
    if not isinstance(events, list) or len(events) != 10 or parent_id == child_id:
        return False
    if not all(_verify_event_record(record, index) for index, record in enumerate(events, 1)):
        return False
    for record in events:
        replay = record.get("replay")
        if not isinstance(replay, dict) or (
            replay.get("accepted") is not False
            or replay.get("reason") != "event_already_consumed"
            or replay.get("frame") is not None
            or replay.get("state_unchanged") is not True
        ):
            return False
    serialized = [record["event"] for record in events]
    transitions = [(event.get("task_id"), event.get("status")) for event in serialized]
    expected = [
        (parent_id, "accepted"),
        (parent_id, "started"),
        (parent_id, "suspended"),
        (child_id, "accepted"),
        (child_id, "started"),
        (child_id, "progress"),
        (child_id, "progress"),
        (child_id, "succeeded"),
        (parent_id, "resumed"),
        (parent_id, "started"),
    ]
    if transitions != expected:
        return False
    child_events = [event for event in serialized if event.get("task_id") == child_id]
    if any(event.get("resume_parent_task_id") != parent_id for event in child_events):
        return False
    arrival = child_events[2]
    keys = child_events[3]
    if not _fact_present(arrival, "near", "sofa") or _fact_present(
        arrival, "object_observed", "keys"
    ):
        return False
    if not _fact_present(keys, "object_observed", "keys"):
        return False
    if row.get("arrival_only_keys_claims") != 0:
        return False
    before = row.get("parent_lineage_before")
    resumed = row.get("parent_lineage_resumed")
    if not isinstance(before, dict) or not isinstance(resumed, dict):
        return False
    for field in ("task_id", "plan_revision", "step_id", "attempt", "skill"):
        if before.get(field) != resumed.get(field):
            return False
    old = row.get("old_generation_after_advance")
    if not isinstance(old, dict) or (
        old.get("accepted") is not False
        or old.get("reason") != "speech_generation_mismatch"
        or old.get("frame") is not None
        or old.get("state_unchanged") is not True
    ):
        return False
    post = row.get("executive_after")
    if not isinstance(post, dict):
        return False
    parent = _task(post, str(parent_id))
    child = _task(post, str(child_id))
    return (
        isinstance(parent, dict)
        and parent.get("state") == "running"
        and isinstance(child, dict)
        and child.get("state") == "succeeded"
    )


def verify_one(result: dict[str, object], manifest: dict[str, object]) -> dict[str, object]:
    errors: list[str] = []
    if result.get("result_sha256") != digest(
        {key: value for key, value in result.items() if key != "result_sha256"}
    ):
        errors.append("result digest mismatch")
    if result.get("manifest_sha256") != file_sha256(MANIFEST_PATH):
        errors.append("manifest digest mismatch")
    rows = result.get("traces")
    if not isinstance(rows, list):
        return {"passed": False, "errors": errors + ["traces missing"]}
    ids = [row.get("case_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(rows) or set(ids) != expected_ids(manifest) or len(set(ids)) != len(ids):
        errors.append("case inventory mismatch")
    normalized = {
        "schema_version": result.get("schema_version"),
        "experiment_id": result.get("experiment_id"),
        "seed": result.get("seed"),
        "trial_counts": result.get("trial_counts"),
        "traces": rows,
    }
    if result.get("normalized_trace_sha256") != digest(normalized):
        errors.append("normalized trace digest mismatch")
    typed_rows = [row for row in rows if isinstance(row, dict)]
    if result.get("trace_chain_root_sha256") != _chain(typed_rows):
        errors.append("trace chain root mismatch")
    if _contains_forbidden_secret(result):
        errors.append("retained result contains authentication secret/tag")

    h1_rows = [row for row in typed_rows if row.get("hypothesis") == "D3-H1"]
    h2_rows = [row for row in typed_rows if row.get("hypothesis") == "D3-H2"]
    h3_rows = [row for row in typed_rows if row.get("hypothesis") == "D3-H3"]
    h1_task_ids = {
        event.get("task_id")
        for row in h1_rows
        for record in row.get("events", [])
        if isinstance(record, dict)
        and isinstance((event := record.get("event")), dict)
    }
    h1_event_ids = [
        event.get("event_id")
        for row in h1_rows
        for record in row.get("events", [])
        if isinstance(record, dict)
        and isinstance((event := record.get("event")), dict)
    ]
    h1_passed = (
        len(h1_rows) == int(manifest["h1_trials"])
        and len(h1_task_ids) == len(h1_rows)
        and len(h1_event_ids) == len(set(h1_event_ids))
        and all(_verify_h1(row) for row in h1_rows)
    )
    coverage = Counter(str(row.get("corruption")) for row in h2_rows)
    h2_task_ids = {
        task.get("task_id")
        for row in h2_rows
        if isinstance(row.get("executive_before"), dict)
        for task in row["executive_before"].get("tasks", [])
        if isinstance(task, dict)
    }
    h2_passed = (
        len(h2_rows) == int(manifest["h2_trials"])
        and len(h2_task_ids) == len(h2_rows)
        and set(coverage) == set(H2_REASON)
        and all(_verify_h2(row) for row in h2_rows)
    )
    h3_task_ids = {
        task_id
        for row in h3_rows
        for task_id in (row.get("parent_task_id"), row.get("child_task_id"))
    }
    h3_event_ids = [
        event.get("event_id")
        for row in h3_rows
        for record in row.get("events", [])
        if isinstance(record, dict)
        and isinstance((event := record.get("event")), dict)
    ]
    h3_passed = (
        len(h3_rows) == int(manifest["h3_trials"])
        and len(h3_task_ids) == len(h3_rows) * 2
        and len(h3_event_ids) == len(set(h3_event_ids))
        and all(_verify_h3(row) for row in h3_rows)
    )
    architecture = result.get("architecture_gate")
    h4_passed = isinstance(architecture, dict) and architecture.get("status") == "PASS"
    if not h1_passed:
        errors.append("D3-H1 oracle failed")
    if not h2_passed:
        errors.append("D3-H2 oracle failed")
    if not h3_passed:
        errors.append("D3-H3 oracle failed")
    if h4_passed:
        errors.append("D3-H4 unexpectedly passed without runtime evidence")
    return {
        "passed": not errors and h1_passed and h2_passed and h3_passed and h4_passed,
        "H1_passed": h1_passed,
        "H2_passed": h2_passed,
        "H3_passed": h3_passed,
        "H4_passed": h4_passed,
        "h2_coverage": dict(sorted(coverage.items())),
        "normalized_trace_sha256": result.get("normalized_trace_sha256"),
        "trace_chain_root_sha256": result.get("trace_chain_root_sha256"),
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
    repeated = (
        len(checks) >= 2
        and len({item.get("normalized_trace_sha256") for item in checks}) == 1
        and len({item.get("trace_chain_root_sha256") for item in checks}) == 1
    )
    h1_h3 = all(
        item.get("H1_passed") is True
        and item.get("H2_passed") is True
        and item.get("H3_passed") is True
        for item in checks
    )
    output = {
        "schema_version": 1,
        "inputs": [str(path) for path in args.input],
        "checks": checks,
        "two_run_digests_identical": repeated,
        "H1_H3_passed_twice": repeated and h1_h3,
        "promotion_passed": repeated
        and h1_h3
        and all(item.get("H4_passed") is True for item in checks),
        "verifier_imports_bridge": False,
    }
    output["verification_sha256"] = digest(output)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
