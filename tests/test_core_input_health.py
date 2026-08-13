from __future__ import annotations

import itertools
import math

import pytest

from parcel_robot.core.input_health import (
    DEFAULT_REQUIRED_INPUTS,
    EvidenceOrigin,
    HealthAction,
    InputEvidence,
    RequiredInput,
    evaluate_input_health,
)

NOW = 100.0


def _good(required_input: RequiredInput) -> InputEvidence:
    spec = DEFAULT_REQUIRED_INPUTS[required_input]
    return InputEvidence(
        captured_at=NOW - spec.max_age_s / 2.0,
        frame_id=spec.frame_id,
        # Card W0-A amendment: the origin used to be omitted here, because the
        # default WAS ``PHYSICAL``. That default is the P0-2 defect (omission
        # minted authority), so a healthy physical sample must now say so.
        origin=EvidenceOrigin.PHYSICAL,
    )


def _state(required_input: RequiredInput, state: str) -> InputEvidence | None | object:
    spec = DEFAULT_REQUIRED_INPUTS[required_input]
    if state == "good":
        return _good(required_input)
    if state == "missing":
        return None
    if state == "stale":
        return InputEvidence(captured_at=NOW - spec.max_age_s - 0.001, frame_id=spec.frame_id)
    if state == "malformed":
        return InputEvidence(captured_at=math.nan, frame_id=spec.frame_id)
    if state == "invalid_payload":
        return InputEvidence(captured_at=NOW, frame_id=spec.frame_id, payload_valid=False)
    if state == "wrong_frame":
        return InputEvidence(captured_at=NOW, frame_id=f"not-{spec.frame_id}")
    if state == "future":
        return InputEvidence(captured_at=NOW + 1.0, frame_id=spec.frame_id)
    if state == "wrong_type":
        return {"captured_at": NOW, "frame_id": spec.frame_id}
    if state == "origin_malformed":
        return InputEvidence(captured_at=NOW, frame_id=spec.frame_id, origin="physical")
    if state == "physical_fixture_label":
        return InputEvidence(
            captured_at=NOW,
            frame_id=spec.frame_id,
            origin=EvidenceOrigin.PHYSICAL,
            fixture_label="should-not-label-physical",
        )
    if state == "origin_unknown":
        # Card W0-A / board D-3: an undeclared producer. This is what a
        # default-constructed boundary object presents as.
        return InputEvidence(captured_at=NOW, frame_id=spec.frame_id)
    raise AssertionError(state)


def test_all_required_inputs_must_join_healthy_to_allow_translation() -> None:
    states = (
        "good",
        "missing",
        "stale",
        "malformed",
        "invalid_payload",
        "wrong_frame",
        "future",
    )

    for combination in itertools.product(states, repeat=len(RequiredInput)):
        evidence = {
            required_input: _state(required_input, state)
            for required_input, state in zip(RequiredInput, combination, strict=True)
        }
        verdict = evaluate_input_health(evidence, now=NOW)

        if combination == ("good",) * len(RequiredInput):
            assert verdict.translation_allowed
            assert verdict.action is HealthAction.ALLOW
            assert verdict.faults == ()
        else:
            assert not verdict.translation_allowed, combination
            expected = (
                HealthAction.LATCHED_STOP
                if any(
                    state in {"malformed", "invalid_payload", "wrong_frame", "future"}
                    for state in combination
                )
                else HealthAction.HOLD
            )
            assert verdict.action is expected, combination


@pytest.mark.parametrize("required_input", list(RequiredInput))
@pytest.mark.parametrize("state", ["missing", "stale", "malformed", "wrong_frame"])
def test_each_required_input_independently_forbids_translation(
    required_input: RequiredInput,
    state: str,
) -> None:
    evidence = {item: _good(item) for item in RequiredInput}
    evidence[required_input] = _state(required_input, state)  # type: ignore[assignment]

    verdict = evaluate_input_health(evidence, now=NOW)

    assert not verdict.translation_allowed
    assert {fault.required_input for fault in verdict.faults} == {required_input}


def test_explicitly_labeled_scan_fixture_is_the_only_admitted_stub_geometry() -> None:
    evidence = {item: _good(item) for item in RequiredInput}
    evidence[RequiredInput.SCAN] = InputEvidence(
        captured_at=NOW,
        frame_id="base_link",
        origin=EvidenceOrigin.SIMULATION,
        fixture_label="unit-test-empty-room-v1",
    )

    assert evaluate_input_health(evidence, now=NOW).translation_allowed

    evidence[RequiredInput.SCAN] = InputEvidence(
        captured_at=NOW,
        frame_id="base_link",
        origin=EvidenceOrigin.SIMULATION,
    )
    unlabeled = evaluate_input_health(evidence, now=NOW)
    assert unlabeled.action is HealthAction.LATCHED_STOP
    assert not unlabeled.translation_allowed


@pytest.mark.parametrize(
    "required_input",
    [RequiredInput.POSE, RequiredInput.CONTROLLER_FEEDBACK],
)
def test_non_geometry_inputs_cannot_be_replaced_by_sim_fixture(
    required_input: RequiredInput,
) -> None:
    evidence = {item: _good(item) for item in RequiredInput}
    evidence[required_input] = InputEvidence(
        captured_at=NOW,
        frame_id=DEFAULT_REQUIRED_INPUTS[required_input].frame_id,
        origin=EvidenceOrigin.SIMULATION,
        fixture_label="forbidden-substitution",
    )

    verdict = evaluate_input_health(evidence, now=NOW)

    assert verdict.action is HealthAction.LATCHED_STOP
    assert not verdict.translation_allowed


@pytest.mark.parametrize("now", [math.nan, math.inf, -math.inf])
def test_malformed_decision_time_latches_stop(now: float) -> None:
    evidence = {item: _good(item) for item in RequiredInput}

    verdict = evaluate_input_health(evidence, now=now)

    assert verdict.action is HealthAction.LATCHED_STOP
    assert not verdict.translation_allowed


@pytest.mark.parametrize(
    ("state", "expected_action"),
    [
        ("missing", HealthAction.HOLD),
        ("stale", HealthAction.HOLD),
        ("malformed", HealthAction.LATCHED_STOP),
        ("invalid_payload", HealthAction.LATCHED_STOP),
        ("wrong_frame", HealthAction.LATCHED_STOP),
        ("future", HealthAction.LATCHED_STOP),
        ("wrong_type", HealthAction.LATCHED_STOP),
        ("origin_malformed", HealthAction.LATCHED_STOP),
        ("physical_fixture_label", HealthAction.LATCHED_STOP),
        # Card W0-A additions to the severity contract.
        ("origin_unknown", HealthAction.LATCHED_STOP),
    ],
)
def test_hold_stop_severity_table(
    state: str,
    expected_action: HealthAction,
) -> None:
    """Contract table: missing/stale HOLD; malformed/frame/future latch STOP."""

    evidence = {item: _good(item) for item in RequiredInput}
    evidence[RequiredInput.SCAN] = _state(RequiredInput.SCAN, state)  # type: ignore[assignment]

    verdict = evaluate_input_health(evidence, now=NOW)

    assert verdict.action is expected_action
    assert not verdict.translation_allowed


def test_absent_required_key_is_treated_as_missing_hold() -> None:
    evidence = {
        RequiredInput.POSE: _good(RequiredInput.POSE),
        RequiredInput.CONTROLLER_FEEDBACK: _good(RequiredInput.CONTROLLER_FEEDBACK),
    }

    verdict = evaluate_input_health(evidence, now=NOW)

    assert verdict.action is HealthAction.HOLD
    assert not verdict.translation_allowed
    assert {fault.required_input for fault in verdict.faults} == {RequiredInput.SCAN}


def test_seeded_clear_on_stale_mutant_is_killed_by_translation_forbid_oracle() -> None:
    """Unit-level mutant: treating stale as ALLOW fails the P0-B forbid oracle."""

    def translation_forbid_oracle(translation_allowed: bool) -> None:
        assert translation_allowed is False

    evidence = {item: _good(item) for item in RequiredInput}
    evidence[RequiredInput.POSE] = _state(RequiredInput.POSE, "stale")  # type: ignore[assignment]
    healthy = evaluate_input_health(evidence, now=NOW)
    translation_forbid_oracle(healthy.translation_allowed)
    assert healthy.action is HealthAction.HOLD

    stale_treated_as_allow = True
    with pytest.raises(AssertionError):
        translation_forbid_oracle(stale_treated_as_allow)
