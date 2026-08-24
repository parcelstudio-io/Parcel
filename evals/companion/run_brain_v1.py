"""Run the frozen Parcel companion brain-v1 contract integration suite.

This suite intentionally stops at runtime-owned semantic verification.  Its
controller traces are deterministic fixtures, not simulated geometry.  It can
prove that only admitted plans reach semantic runtime callbacks and that the
executive accepts success only when a trusted adapter supplies the requested
verified fact.  It cannot prove that a robot physically reached a sidewalk,
lamppost, or owner-relative pose; headless-city and external navigation suites
own those claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from parcel_robot.brain.contracts import IntentFrame, ObservationSnapshot, PlanIR
from parcel_robot.brain.executive import InterruptRequest, TaskExecutive
from parcel_robot.brain.router import DeterministicIntentRouter
from parcel_robot.brain.runtime_adapter import SemanticRuntimeState, SemanticTaskRuntimeAdapter
from parcel_robot.brain.validator import PlanValidationError, PlanValidator, SkillContractRegistry
from parcel_robot.models import SpatialIntent

SUITE_ID = "parcel-companion-brain-v1"
RUNNER_VERSION = "brain-contract-integration-v1"
SUITE_ROOT = Path(__file__).resolve().parent / "brain_v1"
MANIFEST_PATH = SUITE_ROOT / "manifest.json"
CASES_PATH = SUITE_ROOT / "integration_cases.jsonl"
ROUTER_CASES_PATH = SUITE_ROOT / "router_cases.jsonl"
REPORT_SCHEMA_PATH = SUITE_ROOT / "report.schema.json"


class BrainSuiteError(ValueError):
    """The frozen corpus or one of its deterministic fixtures is invalid."""


@dataclass(slots=True)
class _Metrics:
    intent_frames_validated: int = 0
    plan_contracts_parsed: int = 0
    plans_admitted: int = 0
    plans_rejected: int = 0
    executive_submissions: int = 0
    semantic_dispatches: int = 0
    runtime_callbacks: int = 0
    controller_polls: int = 0
    typed_results: int = 0
    verified_facts_emitted: int = 0
    verified_facts_accepted: int = 0
    reports_accepted: int = 0
    stale_reports_ignored: int = 0
    interrupts_requested: int = 0
    logical_ticks: int = 0


@dataclass(slots=True)
class _Harness:
    metrics: _Metrics = field(default_factory=_Metrics)
    callbacks: list[dict[str, object]] = field(default_factory=list)
    dispatch_skills: list[str] = field(default_factory=list)
    verified_facts: list[str] = field(default_factory=list)
    report_actions: list[str] = field(default_factory=list)

    def build_adapter(self) -> SemanticTaskRuntimeAdapter:
        def navigate(directive: str) -> None:
            self._callback("navigate", directive)

        def follow(relation: str, distance_m: float) -> None:
            self._callback(
                "follow_formation",
                {"relation": relation, "distance_m": distance_m},
            )

        def spatial(intent: SpatialIntent) -> None:
            self._callback("spatial_behavior", asdict(intent))

        def hold() -> None:
            self._callback("hold", None)

        def vocalize(text: str) -> None:
            self._callback("vocalize", text)

        return SemanticTaskRuntimeAdapter(
            navigate=navigate,
            follow_formation=follow,
            spatial_behavior=spatial,
            hold=hold,
            vocalize=vocalize,
        )

    def _callback(self, kind: str, value: object) -> None:
        self.metrics.runtime_callbacks += 1
        self.callbacks.append({"kind": kind, "value": value})


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BrainSuiteError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise BrainSuiteError(f"{path} must contain one JSON object")
    return value


def _load_cases(
    manifest: Mapping[str, object],
    *,
    cases_path: Path = CASES_PATH,
) -> list[dict[str, Any]]:
    try:
        payload = cases_path.read_bytes()
    except OSError as error:
        raise BrainSuiteError(f"cannot read frozen cases: {error}") from error
    expected_digest = manifest.get("integration_cases_sha256")
    if not isinstance(expected_digest, str) or _sha256(payload) != expected_digest:
        raise BrainSuiteError("integration_cases.jsonl does not match its frozen SHA-256")
    cases: list[dict[str, Any]] = []
    for line_number, raw in enumerate(payload.decode("utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise BrainSuiteError(f"invalid case JSON on line {line_number}: {error}") from error
        if not isinstance(value, dict):
            raise BrainSuiteError(f"case line {line_number} must be an object")
        cases.append(value)
    expected_count = manifest.get("integration_case_count")
    if expected_count != len(cases):
        raise BrainSuiteError(
            f"manifest expects {expected_count!r} integration cases, found {len(cases)}"
        )
    identifiers = [case.get("case_id") for case in cases]
    if any(not isinstance(item, str) or not item for item in identifiers):
        raise BrainSuiteError("every integration case needs a non-empty case_id")
    if len(set(identifiers)) != len(identifiers):
        raise BrainSuiteError("integration case IDs must be unique")
    return cases


def load_frozen_suite(
    manifest_path: str | Path = MANIFEST_PATH,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load and cryptographically verify the frozen brain-v1 corpus."""

    path = Path(manifest_path)
    manifest = _validate_manifest(_load_object(path))
    root = path.parent
    _verify_frozen_file(
        manifest,
        key="router_cases_sha256",
        path=root / "router_cases.jsonl",
    )
    _verify_frozen_file(
        manifest,
        key="report_schema_sha256",
        path=root / "report.schema.json",
    )
    router_count = sum(
        bool(line.strip())
        for line in (root / "router_cases.jsonl").read_text(encoding="utf-8").splitlines()
    )
    if router_count != manifest.get("case_count"):
        raise BrainSuiteError("router case count does not match the frozen manifest")
    return manifest, _load_cases(
        manifest,
        cases_path=root / "integration_cases.jsonl",
    )


def _validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != 1:
        raise BrainSuiteError("brain-v1 manifest schema_version must equal 1")
    if manifest.get("suite_id") != SUITE_ID:
        raise BrainSuiteError(f"unexpected suite_id: {manifest.get('suite_id')!r}")
    if manifest.get("runner_version") != RUNNER_VERSION:
        raise BrainSuiteError(f"unexpected runner_version: {manifest.get('runner_version')!r}")
    if manifest.get("frozen") is not True:
        raise BrainSuiteError("brain-v1 manifest must explicitly declare frozen=true")
    return manifest


def _verify_frozen_file(
    manifest: Mapping[str, object],
    *,
    key: str,
    path: Path,
) -> None:
    expected = manifest.get(key)
    if not isinstance(expected, str) or len(expected) != 64:
        raise BrainSuiteError(f"manifest {key} must be a SHA-256 digest")
    try:
        actual = _sha256(path.read_bytes())
    except OSError as error:
        raise BrainSuiteError(f"cannot read frozen file {path}: {error}") from error
    if actual != expected:
        raise BrainSuiteError(f"{path.name} does not match its frozen SHA-256")


def _snapshot(spec: Mapping[str, object]) -> ObservationSnapshot:
    """Expand one bounded camera/LiDAR-only fixture into the strict contract."""

    snapshot_id = _text(spec, "snapshot_id")
    camera_fresh = _bool(spec, "camera_fresh", default=True)
    lidar_fresh = _bool(spec, "lidar_fresh", default=True)
    emergency = _bool(spec, "emergency_stopped", default=False)
    moving = _bool(spec, "robot_moving", default=False)
    raw_entities = spec.get("entities", [])
    if not isinstance(raw_entities, list):
        raise BrainSuiteError("snapshot entities must be a list")
    entities: list[dict[str, object]] = []
    for index, entity in enumerate(raw_entities):
        if not isinstance(entity, dict):
            raise BrainSuiteError("snapshot entities must contain objects")
        label = _text(entity, "label")
        kind = _text(entity, "kind")
        attributes = entity.get("attributes", {})
        if not isinstance(attributes, dict):
            raise BrainSuiteError("entity attributes must be an object")
        entities.append(
            {
                "entity_id": str(entity.get("entity_id", f"entity-{index + 1}")),
                "kind": kind,
                "label": label,
                "confidence": float(entity.get("confidence", 0.95)),
                "source": "camera_semantic_fixture",
                "observed_at_monotonic_s": 9.9,
                "attributes": attributes,
            }
        )
    payload: dict[str, object] = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "captured_at_monotonic_s": 10.0,
        "camera": {
            "name": "camera",
            "available": True,
            "fresh": camera_fresh,
            "source": "camera_fixture",
            "observed_at_monotonic_s": 9.9,
            "age_ms": 100.0,
        },
        "lidar": {
            "name": "lidar",
            "available": True,
            "fresh": lidar_fresh,
            "source": "lidar_fixture",
            "observed_at_monotonic_s": 9.95,
            "age_ms": 50.0,
        },
        "robot": {
            "moving": moving,
            "controller_state": "moving" if moving else "standing",
            "x": None,
            "y": None,
            "z": None,
            "yaw_rad": None,
        },
        "safety": {
            "emergency_stopped": emergency,
            "collision_imminent": False,
            "telemetry_fresh": True,
            "nearest_obstacle_m": 2.5,
            "nearest_person_m": 3.0,
        },
        "battery": {"state": "unavailable", "percent": None, "source": "unavailable"},
        "task": {
            "state": "idle",
            "task_id": None,
            "plan_revision": None,
            "step_id": None,
            "at_checkpoint": True,
        },
        "resource_leases": [],
        "entities": entities,
    }
    return ObservationSnapshot.from_mapping(payload)


def _runtime_state(spec: Mapping[str, object]) -> SemanticRuntimeState:
    fields = {
        "snapshot_id",
        "navigation_enabled",
        "navigation_state",
        "navigation_goal",
        "navigation_reason",
        "spatial_enabled",
        "spatial_state",
        "spatial_reason",
        "follow_enabled",
        "follow_state",
        "follow_mode",
        "stop_confirmed",
        "control_feedback_fresh",
        "robot_moving",
    }
    unknown = set(spec) - fields
    if unknown:
        raise BrainSuiteError(f"unknown runtime-state fields: {sorted(unknown)}")
    return SemanticRuntimeState(**dict(spec))  # type: ignore[arg-type]


def _intent(case: Mapping[str, object], harness: _Harness) -> IntentFrame:
    transcript = _text(case, "transcript")
    case_id = _text(case, "case_id")
    turn_id = _text(case, "turn_id")
    reference = f"frozen:{case_id}:transcript"
    frame = DeterministicIntentRouter().route(
        transcript,
        turn_id=turn_id,
        original_transcript_ref=reference,
        is_final=_bool(case, "is_final", default=True),
    )
    # Round-trip through the strict mapping parser so this is an IntentFrame
    # contract test rather than merely a router branch test.
    frame = IntentFrame.from_mapping(frame.as_dict())
    if frame.transcript_sha256 != _sha256(transcript.encode("utf-8")):
        raise BrainSuiteError("router did not preserve exact transcript identity")
    if frame.original_transcript_ref != reference:
        raise BrainSuiteError("router changed the frozen transcript reference")
    expected = case.get("router_expected", {})
    if not isinstance(expected, dict):
        raise BrainSuiteError("router_expected must be an object")
    actual = frame.as_dict()
    for key, value in expected.items():
        if actual.get(key) != value:
            raise BrainSuiteError(
                f"router expectation failed for {case_id}: {key}={actual.get(key)!r}, "
                f"expected {value!r}"
            )
    harness.metrics.intent_frames_validated += 1
    return frame


def _plan(
    raw: object,
    *,
    expected_turn_id: str | None,
    harness: _Harness,
) -> PlanIR:
    if not isinstance(raw, dict):
        raise BrainSuiteError("plan must be a JSON object")
    plan = PlanIR.from_mapping(raw)
    harness.metrics.plan_contracts_parsed += 1
    if expected_turn_id is not None and plan.source_turn_id != expected_turn_id:
        raise BrainSuiteError("PlanIR source_turn_id does not match its frozen IntentFrame")
    return plan


def _validator() -> PlanValidator:
    registry = SkillContractRegistry.default(owner_heading_supported=True).restricted(
        SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS
    )
    return PlanValidator(registry)


def _admit(
    plan: PlanIR,
    snapshot: ObservationSnapshot,
    harness: _Harness,
):
    try:
        validated = _validator().validate(plan, snapshot)
    except PlanValidationError:
        harness.metrics.plans_rejected += 1
        raise
    harness.metrics.plans_admitted += 1
    return validated


def _dispatch(
    executive: TaskExecutive,
    adapter: SemanticTaskRuntimeAdapter,
    snapshot: ObservationSnapshot,
    harness: _Harness,
    *,
    now: float,
):
    harness.metrics.logical_ticks += 1
    requests = executive.tick(snapshot, now=now)
    for request in requests:
        harness.metrics.semantic_dispatches += 1
        harness.dispatch_skills.append(request.skill)
        immediate = adapter.dispatch(request, now=now)
        if immediate is not None:
            _report(executive, immediate, harness)
    return requests


def _poll_and_report(
    executive: TaskExecutive,
    adapter: SemanticTaskRuntimeAdapter,
    state: Mapping[str, object],
    harness: _Harness,
    *,
    now: float,
) -> None:
    harness.metrics.controller_polls += 1
    for result in adapter.poll(_runtime_state(state), now=now):
        _report(executive, result, harness)


def _report(executive: TaskExecutive, result, harness: _Harness):
    harness.metrics.typed_results += 1
    harness.metrics.verified_facts_emitted += len(result.verified_facts)
    harness.verified_facts.extend(fact.fact for fact in result.verified_facts)
    disposition = executive.report(result)
    harness.report_actions.append(disposition.action)
    if disposition.accepted:
        harness.metrics.reports_accepted += 1
        if result.status == "succeeded" and disposition.action in {
            "step_succeeded",
            "task_succeeded",
        }:
            harness.metrics.verified_facts_accepted += len(result.verified_facts)
    elif disposition.action == "ignored_stale_result":
        harness.metrics.stale_reports_ignored += 1
    return disposition


def _task_state(executive: TaskExecutive, task_id: str) -> str:
    tasks = executive.snapshot()["tasks"]
    for task in tasks:
        if task["task_id"] == task_id:
            return str(task["state"])
    return "absent"


def _step_traces(case: Mapping[str, object]) -> dict[str, list[dict[str, object]]]:
    raw = case.get("step_traces", {})
    if not isinstance(raw, dict):
        raise BrainSuiteError("step_traces must be an object")
    result: dict[str, list[dict[str, object]]] = {}
    for step_id, states in raw.items():
        if not isinstance(step_id, str) or not isinstance(states, list) or any(
            not isinstance(state, dict) for state in states
        ):
            raise BrainSuiteError("step_traces must map step IDs to state-object lists")
        result[step_id] = states
    return result


def _run_pipeline(
    case: Mapping[str, object],
    frame: IntentFrame,
    harness: _Harness,
) -> dict[str, object]:
    snapshot = _snapshot(_mapping(case, "snapshot"))
    plan = _plan(case.get("plan"), expected_turn_id=frame.turn_id, harness=harness)
    expected = _mapping(case, "expected")
    try:
        validated = _admit(plan, snapshot, harness)
    except PlanValidationError as error:
        return {
            "admission": "rejected",
            "validation_code": error.code,
            "task_state": "absent",
            "dispatch_skills": [],
            "callbacks": [],
            "verified_facts": [],
            "no_dispatch": True,
        }
    if expected.get("admission") == "rejected":
        raise BrainSuiteError("a case expected rejection but its plan was admitted")

    executive = TaskExecutive()
    adapter = harness.build_adapter()
    submission = executive.submit(validated, task_class=str(case.get("task_class", "active_task")))
    harness.metrics.executive_submissions += 1
    if not submission.accepted:
        raise BrainSuiteError(f"validated plan was not submitted: {submission.reason}")
    traces = _step_traces(case)
    logical_time = 20.0
    while _task_state(executive, plan.task_id) not in {"succeeded", "failed", "cancelled"}:
        requests = _dispatch(
            executive, adapter, snapshot, harness, now=logical_time
        )
        logical_time += 1.0
        if not requests:
            break
        for request in requests:
            if request.skill in {"Vocalize", "AskClarification"}:
                continue
            states = traces.get(request.step_id)
            if states is None:
                raise BrainSuiteError(f"missing runtime trace for step {request.step_id}")
            for state in states:
                _poll_and_report(
                    executive, adapter, state, harness, now=logical_time
                )
                logical_time += 1.0
    state = _task_state(executive, plan.task_id)
    return {
        "admission": "accepted",
        "validation_code": None,
        "task_state": state,
        "dispatch_skills": harness.dispatch_skills,
        "callbacks": harness.callbacks,
        "verified_facts": harness.verified_facts,
        "report_actions": harness.report_actions,
        "no_dispatch": harness.metrics.semantic_dispatches == 0,
    }


def _run_emergency_between(
    case: Mapping[str, object],
    frame: IntentFrame,
    harness: _Harness,
) -> dict[str, object]:
    admitted_snapshot = _snapshot(_mapping(case, "snapshot"))
    execution_snapshot = _snapshot(_mapping(case, "execution_snapshot"))
    plan = _plan(case.get("plan"), expected_turn_id=frame.turn_id, harness=harness)
    validated = _admit(plan, admitted_snapshot, harness)
    executive = TaskExecutive()
    adapter = harness.build_adapter()
    submission = executive.submit(validated)
    harness.metrics.executive_submissions += 1
    if not submission.accepted:
        raise BrainSuiteError("emergency-between fixture could not submit admitted plan")
    _dispatch(executive, adapter, execution_snapshot, harness, now=20.0)
    return {
        "admission": "accepted",
        "validation_code": None,
        "task_state": _task_state(executive, plan.task_id),
        "dispatch_skills": harness.dispatch_skills,
        "callbacks": harness.callbacks,
        "verified_facts": harness.verified_facts,
        "no_dispatch": harness.metrics.semantic_dispatches == 0,
    }


def _run_correction(
    case: Mapping[str, object],
    frame: IntentFrame,
    harness: _Harness,
) -> dict[str, object]:
    snapshot = _snapshot(_mapping(case, "snapshot"))
    setup = _plan(case.get("setup_plan"), expected_turn_id=None, harness=harness)
    replacement = _plan(case.get("plan"), expected_turn_id=frame.turn_id, harness=harness)
    initial_validated = _admit(setup, snapshot, harness)
    replacement_validated = _admit(replacement, snapshot, harness)
    executive = TaskExecutive()
    adapter = harness.build_adapter()
    submission = executive.submit(initial_validated)
    harness.metrics.executive_submissions += 1
    if not submission.accepted:
        raise BrainSuiteError("correction setup plan could not be submitted")
    old_request = _dispatch(executive, adapter, snapshot, harness, now=20.0)[0]
    replacement_submission = executive.replace(replacement_validated)
    harness.metrics.executive_submissions += 1

    traces = _mapping(case, "correction_traces")
    old_progress = adapter.poll(
        _runtime_state(_mapping(traces, "old_progress")), now=21.0
    )[0]
    harness.metrics.controller_polls += 1
    old_terminal = adapter.poll(
        _runtime_state(_mapping(traces, "old_terminal")), now=22.0
    )[0]
    harness.metrics.controller_polls += 1
    progress_disposition = _report(executive, old_progress, harness)
    stale_disposition = _report(executive, old_terminal, harness)
    if old_request.plan_revision == replacement.plan_revision:
        raise BrainSuiteError("correction fixture did not increase the plan revision")

    new_request = _dispatch(executive, adapter, snapshot, harness, now=23.0)[0]
    _poll_and_report(
        executive,
        adapter,
        _mapping(traces, "replacement_terminal"),
        harness,
        now=24.0,
    )
    return {
        "admission": "accepted",
        "validation_code": None,
        "task_state": _task_state(executive, replacement.task_id),
        "dispatch_skills": harness.dispatch_skills,
        "callbacks": harness.callbacks,
        "verified_facts": harness.verified_facts,
        "replacement_disposition": replacement_submission.disposition,
        "checkpoint_report_action": progress_disposition.action,
        "stale_report_action": stale_disposition.action,
        "new_plan_revision": new_request.plan_revision,
        "no_dispatch": False,
    }


def _run_interrupt(
    case: Mapping[str, object],
    frame: IntentFrame,
    harness: _Harness,
) -> dict[str, object]:
    snapshot = _snapshot(_mapping(case, "snapshot"))
    setup = _plan(case.get("setup_plan"), expected_turn_id=None, harness=harness)
    validated = _admit(setup, snapshot, harness)
    executive = TaskExecutive()
    adapter = harness.build_adapter()
    submission = executive.submit(validated)
    harness.metrics.executive_submissions += 1
    if not submission.accepted:
        raise BrainSuiteError("interrupt setup plan could not be submitted")
    _dispatch(executive, adapter, snapshot, harness, now=20.0)

    interrupt = _mapping(case, "interrupt")
    request = InterruptRequest(
        source=_text(interrupt, "source"),
        reason=_text(interrupt, "reason"),
        requested=_text(interrupt, "requested"),
        target_task_id=setup.task_id,
    )
    harness.metrics.interrupts_requested += 1
    decision = executive.request_interrupt(request)
    if decision.action == "cancel_now":
        adapter.cancel(decision.affected_task_ids)
    elif decision.action == "defer_when_idle":
        trace = _mapping(case, "terminal_trace")
        _poll_and_report(executive, adapter, trace, harness, now=21.0)
    return {
        "admission": "accepted",
        "validation_code": None,
        "task_state": _task_state(executive, setup.task_id),
        "dispatch_skills": harness.dispatch_skills,
        "callbacks": harness.callbacks,
        "verified_facts": harness.verified_facts,
        "interrupt_action": decision.action,
        "affected_task_ids": list(decision.affected_task_ids),
        "no_dispatch": harness.metrics.semantic_dispatches == 0,
        "intent_route": frame.route,
    }


def _compare_expected(expected: Mapping[str, object], actual: Mapping[str, object]) -> list[str]:
    failures: list[str] = []
    for key, value in expected.items():
        if actual.get(key) != value:
            failures.append(f"{key}: expected {value!r}, got {actual.get(key)!r}")
    return failures


def run_case(case: Mapping[str, object]) -> dict[str, Any]:
    """Run one frozen case without model, simulator, network, or durable writes."""

    harness = _Harness()
    case_id = _text(case, "case_id")
    try:
        frame = _intent(case, harness)
        scenario = str(case.get("scenario", "pipeline"))
        if scenario == "pipeline":
            actual = _run_pipeline(case, frame, harness)
        elif scenario == "emergency_between_admission_and_dispatch":
            actual = _run_emergency_between(case, frame, harness)
        elif scenario == "correction":
            actual = _run_correction(case, frame, harness)
        elif scenario == "interrupt":
            actual = _run_interrupt(case, frame, harness)
        else:
            raise BrainSuiteError(f"unknown case scenario: {scenario}")
        expected = _mapping(case, "expected")
        failures = _compare_expected(expected, actual)
    except (BrainSuiteError, PlanValidationError, TypeError, ValueError, KeyError) as error:
        actual = {"harness_error": f"{type(error).__name__}: {error}"}
        failures = [actual["harness_error"]]
        expected = case.get("expected", {})
    return {
        "case_id": case_id,
        "scenario": str(case.get("scenario", "pipeline")),
        "passed": not failures,
        "expected": expected,
        "actual": actual,
        "failures": failures,
        "metrics": asdict(harness.metrics),
    }


def run_suite(
    *,
    case_ids: Sequence[str] | None = None,
    manifest_path: str | Path = MANIFEST_PATH,
) -> dict[str, Any]:
    """Return deterministic per-case outcomes and aggregate boundary metrics."""

    manifest, cases = load_frozen_suite(manifest_path)
    requested = frozenset(case_ids or ())
    known = frozenset(str(case["case_id"]) for case in cases)
    unknown = requested - known
    if unknown:
        raise BrainSuiteError(f"unknown requested case IDs: {sorted(unknown)}")
    selected = [case for case in cases if not requested or case["case_id"] in requested]
    outcomes = [run_case(case) for case in selected]
    totals = _Metrics()
    for outcome in outcomes:
        for name, value in outcome["metrics"].items():
            setattr(totals, name, getattr(totals, name) + int(value))
    passed = sum(bool(outcome["passed"]) for outcome in outcomes)
    expected_fail_closed = sum(
        outcome["expected"].get("admission") == "rejected"
        or outcome["expected"].get("no_dispatch") is True
        or outcome["expected"].get("task_state") in {"failed", "cancelled"}
        for outcome in outcomes
    )
    matched_fail_closed = sum(
        outcome["passed"]
        and (
            outcome["expected"].get("admission") == "rejected"
            or outcome["expected"].get("no_dispatch") is True
            or outcome["expected"].get("task_state") in {"failed", "cancelled"}
        )
        for outcome in outcomes
    )
    count = len(outcomes)
    aggregate = {
        "case_count": count,
        "passed_case_count": passed,
        "failed_case_count": count - passed,
        "expected_boundary_outcome_accuracy": passed / count if count else 0.0,
        "expected_fail_closed_case_count": expected_fail_closed,
        "matched_fail_closed_case_count": matched_fail_closed,
        "fail_closed_expectation_accuracy": (
            matched_fail_closed / expected_fail_closed if expected_fail_closed else 1.0
        ),
        **asdict(totals),
        "physical_navigation_episode_count": 0,
        "physical_navigation_success_rate": None,
    }
    return {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "corpus": {
            "frozen": True,
            "integration_cases_sha256": manifest["integration_cases_sha256"],
            "selected_case_ids": [outcome["case_id"] for outcome in outcomes],
        },
        "passed": passed == count,
        "aggregate": aggregate,
        "cases": outcomes,
        "claims": {
            "proves": [
                "strict IntentFrame and PlanIR parsing for the frozen fixtures",
                "snapshot-bound admission and fail-closed validation decisions",
                "semantic dispatch, resource ownership, interruption, and stale-result handling",
                "acceptance of terminal success only through typed runtime-adapter facts",
            ],
            "does_not_prove": [
                "language-model planning quality on unseen requests",
                "camera or LiDAR perception accuracy",
                "physical sidewalk, lamppost, orbit, distance, or formation geometry",
                "collision avoidance, dynamic-city robustness, Unitree locomotion, or latency",
            ],
        },
    }


def _mapping(value: Mapping[str, object], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise BrainSuiteError(f"{key} must be an object")
    return item


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise BrainSuiteError(f"{key} must be non-empty text")
    return item


def _bool(value: Mapping[str, object], key: str, *, default: bool) -> bool:
    item = value.get(key, default)
    if not isinstance(item, bool):
        raise BrainSuiteError(f"{key} must be a boolean")
    return item


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_suite(case_ids=args.case_ids)
    except BrainSuiteError as error:
        report = {
            "schema_version": 1,
            "suite_id": SUITE_ID,
            "passed": False,
            "harness_error": str(error),
        }
    payload = json.dumps(
        report,
        indent=None if args.compact else 2,
        separators=(",", ":") if args.compact else None,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
