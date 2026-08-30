#!/usr/bin/env python
"""Deterministic DMC-3 H1-H3 product-contract replay harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from dataclasses import replace
from pathlib import Path
from typing import Any

from parcel_robot.brain.contracts import (
    ExecutionResult,
    GoalSpec,
    GoalTarget,
    PlanIR,
    PlanStep,
    SuccessCondition,
    VerifiedFact,
)
from parcel_robot.brain.execution_narrative_bridge import NarratingTaskExecutiveV1
from parcel_robot.brain.executive import TaskExecutive
from parcel_robot.brain.validator import PlanValidator
from parcel_robot.contracts.execution_narrative_v1 import build_execution_narrative_event
from parcel_robot.voice.execution_narrative import (
    AuthenticatedExecutionNarrativeEventV1,
    NarrativeConsumerStateV1,
    TrustedExecutionNarrativeAuthenticatorV1,
    advance_speech_generation,
    consume_execution_narrative_event,
)


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
MANIFEST_PATH = HERE / "manifest.json"
AUTH = TrustedExecutionNarrativeAuthenticatorV1(
    authenticator_id="dmc3_frozen_executive",
    key=b"dmc3-frozen-local-authentication-key-20260829",
)


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


def token(namespace: str, trial: int, field: str, length: int = 24) -> str:
    return hashlib.sha256(
        f"20260829:{namespace}:{trial}:{field}".encode("ascii")
    ).hexdigest()[:length]


def _now_ns(trial: int) -> int:
    return 1_000_000_000_000 + trial * 100_000_000


def _plan(trial: int, namespace: str, *, steps: int = 1) -> PlanIR:
    task_id = f"task-{token(namespace, trial, 'task')}"
    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=1,
        source_turn_id=f"turn-{token(namespace, trial, 'turn')}",
        goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
        invariants=(),
        steps=tuple(
            PlanStep(
                f"step-{token(namespace, trial, f'step-{index}')}",
                "Hold",
                {},
                ("base_available",),
                SuccessCondition("motion_stopped"),
                5.0,
                1,
                (),
                ("base",),
                "immediate",
            )
            for index in range(steps)
        ),
    )


def _result(
    request: Any,
    trial: int,
    namespace: str,
    *,
    status: str,
    facts: tuple[VerifiedFact, ...] = (),
    task_id: str | None = None,
    revision: int | None = None,
    step_id: str | None = None,
    attempt: int | None = None,
    detail: str = "controller_update",
) -> ExecutionResult:
    terminal = status != "in_progress"
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id if task_id is None else task_id,
        plan_revision=request.plan_revision if revision is None else revision,
        step_id=request.step_id if step_id is None else step_id,
        attempt=request.attempt if attempt is None else attempt,
        status=status,
        feedback_code=status,
        snapshot_id=f"snapshot-{token(namespace, trial, detail)}",
        verified_facts=facts,
        checkpoint=True,
        detail_code=detail,
        started_at_monotonic_s=1000.0 + trial,
        finished_at_monotonic_s=(1000.1 + trial if terminal else None),
    )


def _bridge(manifest: dict[str, object], trial: int) -> NarratingTaskExecutiveV1:
    now = _now_ns(trial)
    return NarratingTaskExecutiveV1(
        TaskExecutive(),
        authenticator=AUTH,
        source_epoch=int(manifest["source_epoch"]),
        speech_generation_provider=lambda: int(manifest["speech_generation"]),
        monotonic_ns=lambda: now,
        event_ttl_ns=int(manifest["event_ttl_ns"]),
    )


def _disposition(value: object) -> dict[str, object]:
    fields = ("accepted", "disposition", "action", "task_id", "plan_revision", "state", "reason")
    return {
        field: getattr(value, field)
        for field in fields
        if hasattr(value, field)
    }


def _request(value: object) -> dict[str, object]:
    fields = ("task_id", "plan_revision", "step_id", "attempt", "skill", "recovery_action")
    return {field: getattr(value, field) for field in fields}


def _consume_event(
    state: NarrativeConsumerStateV1,
    authenticated: object,
    *,
    now: int,
) -> tuple[NarrativeConsumerStateV1, dict[str, object]]:
    before = state.as_dict()
    reduction = consume_execution_narrative_event(
        state,
        authenticated,
        authenticator=AUTH,
        now_monotonic_ns=now,
    )
    observed = {
        "accepted": reduction.accepted,
        "reason": reduction.reason,
        "frame": reduction.frame.as_dict() if reduction.frame is not None else None,
        "state_before": before,
        "state_after": reduction.state.as_dict(),
    }
    return reduction.state, observed


def _event_record(
    authenticated: AuthenticatedExecutionNarrativeEventV1,
    consume: dict[str, object],
) -> dict[str, object]:
    return {
        "event": authenticated.event.as_dict(),
        "authenticator_id": authenticated.authenticator_id,
        "auth_verified": AUTH.verify(authenticated),
        "authorizes_actuation": authenticated.authorizes_actuation,
        "consumer": consume,
    }


def run_h1_trial(manifest: dict[str, object], trial: int) -> dict[str, object]:
    plan = _plan(trial, "h1")
    validated = PlanValidator().validate(plan)
    bridge = _bridge(manifest, trial)
    inputs: list[dict[str, object]] = []
    dispositions: list[dict[str, object]] = []

    before = bridge.snapshot()
    submitted = bridge.submit(validated)
    inputs.append({"operation": "submit", "value": plan.as_dict()})
    dispositions.append(_disposition(submitted))
    request = bridge.tick(now=1000.0 + trial)[0]
    inputs.append({"operation": "tick", "value": {"now": 1000.0 + trial}})
    dispositions.append({"dispatch": _request(request)})
    progress_fact = VerifiedFact("near", "owner", "localization", 0.9)
    progress = _result(
        request,
        trial,
        "h1",
        status="in_progress",
        facts=(progress_fact,),
        detail="progress",
    )
    progress_disposition = bridge.report(progress)
    inputs.append({"operation": "report", "value": progress.as_dict()})
    dispositions.append(_disposition(progress_disposition))
    success_fact = VerifiedFact("motion_stopped", None, "controller", 1.0)
    success = _result(
        request,
        trial,
        "h1",
        status="succeeded",
        facts=(success_fact,),
        detail="motion_stopped",
    )
    success_disposition = bridge.report(success)
    inputs.append({"operation": "report", "value": success.as_dict()})
    dispositions.append(_disposition(success_disposition))
    after = bridge.snapshot()

    state = NarrativeConsumerStateV1(
        source_epoch=int(manifest["source_epoch"]),
        speech_generation=int(manifest["speech_generation"]),
    )
    events: list[dict[str, object]] = []
    for authenticated in bridge.drain_narrative_events():
        state, consumed = _consume_event(state, authenticated, now=_now_ns(trial) + 1)
        events.append(_event_record(authenticated, consumed))
    return {
        "case_id": f"h1-{trial:04d}",
        "hypothesis": "D3-H1",
        "trial": trial,
        "input": inputs,
        "dispositions": dispositions,
        "executive_before": before,
        "executive_after": after,
        "events": events,
        "final_consumer_state": state.as_dict(),
    }


def _rebuild_event(event: Any, **changes: object):
    values = event.as_dict()
    values.update(changes)
    for field in ("schema_version", "event_id", "mission_id", "action_id"):
        values.pop(field, None)
    facts = tuple(
        VerifiedFact.from_mapping(item) for item in values.pop("verified_facts")
    )
    evidence_refs = tuple(values.pop("evidence_refs"))
    return build_execution_narrative_event(
        **values,
        verified_facts=facts,
        evidence_refs=evidence_refs,
    )


def _consume_setup(
    manifest: dict[str, object],
    events: tuple[AuthenticatedExecutionNarrativeEventV1, ...],
    trial: int,
) -> NarrativeConsumerStateV1:
    state = NarrativeConsumerStateV1(
        source_epoch=int(manifest["source_epoch"]),
        speech_generation=int(manifest["speech_generation"]),
    )
    for authenticated in events:
        reduction = consume_execution_narrative_event(
            state,
            authenticated,
            authenticator=AUTH,
            now_monotonic_ns=_now_ns(trial) + 1,
        )
        if not reduction.accepted:
            raise RuntimeError(f"invalid H2 setup: {reduction.reason}")
        state = reduction.state
    return state


def run_h2_trial(
    manifest: dict[str, object],
    trial: int,
    corruption: str,
) -> dict[str, object]:
    plan = _plan(trial, "h2", steps=2 if corruption == "late_old_step_result" else 1)
    bridge = _bridge(manifest, trial)
    bridge.submit(PlanValidator().validate(plan))
    first_request = bridge.tick(now=1000.0 + trial)[0]
    setup_dispositions: list[dict[str, object]] = []
    tested_input: dict[str, object]
    tested_disposition: dict[str, object]
    tested_authenticated: object | None = None
    tested_event: dict[str, object] | None = None

    result_corruptions = {
        "unknown_task_result",
        "wrong_revision_result",
        "wrong_step_result",
        "wrong_attempt_result",
        "late_old_step_result",
        "post_terminal_result",
        "missing_success_fact",
    }
    if corruption in result_corruptions:
        request = first_request
        if corruption == "late_old_step_result":
            completed = _result(
                first_request,
                trial,
                "h2",
                status="succeeded",
                facts=(VerifiedFact("motion_stopped", None, "controller", 1.0),),
                detail="first_step_complete",
            )
            setup_dispositions.append(_disposition(bridge.report(completed)))
            request = bridge.tick(now=1001.0 + trial)[0]
            tested = completed
        elif corruption == "post_terminal_result":
            completed = _result(
                first_request,
                trial,
                "h2",
                status="succeeded",
                facts=(VerifiedFact("motion_stopped", None, "controller", 1.0),),
                detail="task_complete",
            )
            setup_dispositions.append(_disposition(bridge.report(completed)))
            tested = completed
        else:
            tested = _result(
                request,
                trial,
                "h2",
                status="succeeded",
                facts=(
                    ()
                    if corruption == "missing_success_fact"
                    else (VerifiedFact("motion_stopped", None, "controller", 1.0),)
                ),
                detail="tested_corruption",
            )
            if corruption == "unknown_task_result":
                tested = replace(
                    tested,
                    task_id=f"task-{token('h2', trial, 'unknown-task')}",
                )
            elif corruption == "wrong_revision_result":
                tested = replace(tested, plan_revision=2)
            elif corruption == "wrong_step_result":
                tested = replace(
                    tested,
                    step_id=f"step-{token('h2', trial, 'wrong-step')}",
                )
            elif corruption == "wrong_attempt_result":
                tested = replace(tested, attempt=2)
        setup_events = bridge.drain_narrative_events()
        before = bridge.snapshot()
        disposition = bridge.report(tested)
        after = bridge.snapshot()
        new_events = bridge.drain_narrative_events()
        tested_input = {"kind": "execution_result", "value": tested.as_dict()}
        tested_disposition = _disposition(disposition)
        if new_events:
            tested_authenticated = new_events[0]
            tested_event = new_events[0].event.as_dict()
        state = _consume_setup(manifest, setup_events, trial)
    else:
        setup_events = bridge.drain_narrative_events()
        state = _consume_setup(manifest, setup_events, trial)
        base = setup_events[-1]
        sequence = state.last_event_sequence + 1
        changes: dict[str, object] = {
            "event_sequence": sequence,
            "issued_at_monotonic_ns": _now_ns(trial),
            "claimable_until_monotonic_ns": _now_ns(trial) + int(manifest["event_ttl_ns"]),
            "status": "progress",
            "detail_code": f"corrupt-{corruption}",
        }
        if corruption == "altered_event_payload":
            changed = _rebuild_event(base.event, **changes)
            tested_authenticated = AuthenticatedExecutionNarrativeEventV1(
                changed,
                base.authenticator_id,
                base.auth_tag,
            )
        elif corruption == "altered_event_tag":
            changed = _rebuild_event(base.event, **changes)
            tested_authenticated = AuthenticatedExecutionNarrativeEventV1(
                changed,
                base.authenticator_id,
                "0" * 64,
            )
        elif corruption == "duplicate_event":
            tested_authenticated = base
        else:
            if corruption == "event_sequence_regression":
                changes["event_sequence"] = state.last_event_sequence
            elif corruption == "wrong_source_epoch":
                changes["source_epoch"] = int(manifest["source_epoch"]) + 1
            elif corruption == "future_event":
                changes["issued_at_monotonic_ns"] = _now_ns(trial) + 100
                changes["claimable_until_monotonic_ns"] = (
                    _now_ns(trial) + int(manifest["event_ttl_ns"])
                )
            elif corruption == "expired_event":
                changes["issued_at_monotonic_ns"] = _now_ns(trial) - 100
                changes["claimable_until_monotonic_ns"] = _now_ns(trial)
            elif corruption == "old_speech_generation":
                state = advance_speech_generation(
                    state,
                    speech_generation=int(manifest["speech_generation"]) + 1,
                )
            elif corruption == "new_speech_generation":
                changes["speech_generation"] = int(manifest["speech_generation"]) + 1
            else:
                raise ValueError(f"unhandled corruption: {corruption}")
            changed = _rebuild_event(base.event, **changes)
            tested_authenticated = AUTH.authenticate(changed)
        assert isinstance(tested_authenticated, AuthenticatedExecutionNarrativeEventV1)
        tested_event = tested_authenticated.event.as_dict()
        tested_input = {"kind": "narrative_event", "value": tested_event}
        tested_disposition = {}
        before = bridge.snapshot()
        after = bridge.snapshot()

    consumer_before = state.as_dict()
    replay: dict[str, object] | None = None
    continuation: dict[str, object] | None = None
    if tested_authenticated is None:
        consumption = {
            "accepted": False,
            "reason": "no_event_minted",
            "frame": None,
            "state_before": consumer_before,
            "state_after": consumer_before,
        }
    else:
        next_state, consumption = _consume_event(
            state,
            tested_authenticated,
            now=_now_ns(trial) + 1,
        )
        if corruption == "missing_success_fact":
            replay_reduction = consume_execution_narrative_event(
                next_state,
                tested_authenticated,
                authenticator=AUTH,
                now_monotonic_ns=_now_ns(trial) + 1,
            )
            replay = {
                "accepted": replay_reduction.accepted,
                "reason": replay_reduction.reason,
                "frame": (
                    replay_reduction.frame.as_dict()
                    if replay_reduction.frame is not None
                    else None
                ),
                "state_unchanged": replay_reduction.state is next_state,
            }
            followup_plan = _plan(trial, "h2-continuation")
            followup_disposition = bridge.submit(
                PlanValidator().validate(followup_plan)
            )
            followup_events = bridge.drain_narrative_events()
            if len(followup_events) != 1:
                raise RuntimeError("missing-success continuation did not mint one event")
            final_state, followup_consumption = _consume_event(
                next_state,
                followup_events[0],
                now=_now_ns(trial) + 1,
            )
            continuation = {
                "input": {
                    "operation": "submit",
                    "value": followup_plan.as_dict(),
                },
                "disposition": _disposition(followup_disposition),
                **_event_record(followup_events[0], followup_consumption),
                "final_consumer_state": final_state.as_dict(),
            }
    return {
        "case_id": f"h2-{trial:04d}-{corruption}",
        "hypothesis": "D3-H2",
        "trial": trial,
        "corruption": corruption,
        "setup_event_count": len(setup_events),
        "setup_dispositions": setup_dispositions,
        "tested_input": tested_input,
        "tested_disposition": tested_disposition,
        "tested_event": tested_event,
        "tested_event_auth_verified": (
            AUTH.verify(tested_authenticated) if tested_authenticated is not None else None
        ),
        "consumer": consumption,
        "replay": replay,
        "continuation": continuation,
        "executive_before": before,
        "executive_after": after,
    }


def run_h3_trial(manifest: dict[str, object], trial: int) -> dict[str, object]:
    bridge = _bridge(manifest, trial)
    parent_plan = _plan(trial, "h3-parent")
    child_plan = _plan(trial, "h3-child")
    dispositions: list[dict[str, object]] = []
    dispositions.append(_disposition(bridge.submit(PlanValidator().validate(parent_plan))))
    parent_request = bridge.tick(now=1000.0 + trial)[0]
    dispositions.append({"dispatch": _request(parent_request)})
    dispositions.append(
        _disposition(bridge.suspend_task(parent_plan.task_id, reason="check_keys_on_sofa"))
    )
    dispositions.append(
        _disposition(
            bridge.submit(
                PlanValidator().validate(child_plan),
                task_class="voice",
                resume_parent_task_id=parent_plan.task_id,
            )
        )
    )
    child_request = bridge.tick(now=1001.0 + trial)[0]
    dispositions.append({"dispatch": _request(child_request)})
    arrival = VerifiedFact("near", "sofa", "localization", 0.96)
    arrival_result = _result(
        child_request,
        trial,
        "h3",
        status="in_progress",
        facts=(arrival,),
        detail="sofa_arrival",
    )
    dispositions.append(_disposition(bridge.report(arrival_result)))
    keys = VerifiedFact("object_observed", "keys", "camera", 0.93)
    keys_result = _result(
        child_request,
        trial,
        "h3",
        status="in_progress",
        facts=(keys,),
        detail="keys_observation",
    )
    dispositions.append(_disposition(bridge.report(keys_result)))
    complete = _result(
        child_request,
        trial,
        "h3",
        status="succeeded",
        facts=(VerifiedFact("motion_stopped", None, "controller", 1.0),),
        detail="search_complete",
    )
    dispositions.append(_disposition(bridge.report(complete)))
    dispositions.append(
        _disposition(bridge.resume_task(parent_plan.task_id, reason="child_complete"))
    )
    resumed_request = bridge.tick(now=1002.0 + trial)[0]
    dispositions.append({"dispatch": _request(resumed_request)})
    executive_after = bridge.snapshot()

    state = NarrativeConsumerStateV1(
        source_epoch=int(manifest["source_epoch"]),
        speech_generation=int(manifest["speech_generation"]),
    )
    event_records: list[dict[str, object]] = []
    arrival_only_keys_claims = 0
    authenticated_events = bridge.drain_narrative_events()
    for authenticated in authenticated_events:
        before = state
        state, consumed = _consume_event(
            state,
            authenticated,
            now=_now_ns(trial) + 1,
        )
        replay = consume_execution_narrative_event(
            state,
            authenticated,
            authenticator=AUTH,
            now_monotonic_ns=_now_ns(trial) + 1,
        )
        frame = consumed["frame"]
        if authenticated.event.detail_code.endswith("sofa_arrival") and isinstance(frame, dict):
            claims = frame.get("claimable_facts", [])
            if isinstance(claims, list):
                arrival_only_keys_claims += sum(
                    1
                    for fact in claims
                    if isinstance(fact, dict)
                    and fact.get("fact") == "object_observed"
                    and fact.get("target") == "keys"
                )
        record = _event_record(authenticated, consumed)
        record["replay"] = {
            "accepted": replay.accepted,
            "reason": replay.reason,
            "frame": replay.frame.as_dict() if replay.frame is not None else None,
            "state_unchanged": replay.state is state,
        }
        record["consumer_state_identity_advanced"] = state is not before
        event_records.append(record)

    advanced = advance_speech_generation(
        state,
        speech_generation=int(manifest["speech_generation"]) + 1,
    )
    old_generation = consume_execution_narrative_event(
        advanced,
        authenticated_events[-1],
        authenticator=AUTH,
        now_monotonic_ns=_now_ns(trial) + 1,
    )
    return {
        "case_id": f"h3-{trial:04d}",
        "hypothesis": "D3-H3",
        "trial": trial,
        "parent_task_id": parent_plan.task_id,
        "child_task_id": child_plan.task_id,
        "parent_lineage_before": _request(parent_request),
        "parent_lineage_resumed": _request(resumed_request),
        "inputs": {
            "parent_plan": parent_plan.as_dict(),
            "child_plan": child_plan.as_dict(),
            "arrival_result": arrival_result.as_dict(),
            "keys_result": keys_result.as_dict(),
            "completion_result": complete.as_dict(),
        },
        "dispositions": dispositions,
        "events": event_records,
        "arrival_only_keys_claims": arrival_only_keys_claims,
        "old_generation_after_advance": {
            "accepted": old_generation.accepted,
            "reason": old_generation.reason,
            "frame": old_generation.frame.as_dict() if old_generation.frame is not None else None,
            "state_unchanged": old_generation.state is advanced,
        },
        "executive_after": executive_after,
        "final_consumer_state": advanced.as_dict(),
    }


def _chain(rows: list[dict[str, object]]) -> str:
    value = "0" * 64
    for row in rows:
        value = digest({"previous": value, "row": row})
    return value


def run_suite(manifest: dict[str, object], *, trial_limits: dict[str, int] | None = None) -> dict[str, object]:
    limits = trial_limits or {}
    h1_count = limits.get("h1", int(manifest["h1_trials"]))
    h2_count = limits.get("h2", int(manifest["h2_trials"]))
    h3_count = limits.get("h3", int(manifest["h3_trials"]))
    corruptions = tuple(str(item) for item in manifest["h2_corruptions"])
    rows: list[dict[str, object]] = []
    rows.extend(run_h1_trial(manifest, trial) for trial in range(h1_count))
    rows.extend(
        run_h2_trial(manifest, trial, corruptions[trial % len(corruptions)])
        for trial in range(h2_count)
    )
    rows.extend(run_h3_trial(manifest, trial) for trial in range(h3_count))
    normalized = {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "seed": manifest["seed"],
        "trial_counts": {"h1": h1_count, "h2": h2_count, "h3": h3_count},
        "traces": rows,
    }
    return {
        **normalized,
        "manifest_sha256": file_sha256(MANIFEST_PATH),
        "normalized_trace_sha256": digest(normalized),
        "trace_chain_root_sha256": _chain(rows),
        "architecture_gate": {
            "hypothesis": "D3-H4",
            "status": "PARTIAL_RED",
            "reason": "TaskExecutive.tick has silent authoritative mutations without typed transition records; snapshot inference is forbidden",
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    result = run_suite(manifest)
    result["result_sha256"] = digest(result)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "trials": result["trial_counts"],
                "normalized_trace_sha256": result["normalized_trace_sha256"],
                "architecture_gate": result["architecture_gate"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
