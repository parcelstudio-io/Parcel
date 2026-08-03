import hashlib
import json
from pathlib import Path

import pytest

from evals.companion.run_brain_v1 import (
    CASES_PATH,
    MANIFEST_PATH,
    BrainSuiteError,
    load_frozen_suite,
    run_suite,
)

REPO = Path(__file__).resolve().parents[1]
SUITE = REPO / "evals" / "companion" / "brain_v1"


def _case(report: dict[str, object], case_id: str) -> dict[str, object]:
    return next(item for item in report["cases"] if item["case_id"] == case_id)


def test_manifest_cryptographically_locks_every_machine_readable_fixture() -> None:
    manifest, cases = load_frozen_suite()

    assert MANIFEST_PATH == SUITE / "manifest.json"
    assert CASES_PATH == SUITE / "integration_cases.jsonl"
    assert len(cases) == manifest["integration_case_count"] == 15
    assert len({case["case_id"] for case in cases}) == 15
    for filename, key in (
        ("router_cases.jsonl", "router_cases_sha256"),
        ("integration_cases.jsonl", "integration_cases_sha256"),
        ("report.schema.json", "report_schema_sha256"),
    ):
        payload = (SUITE / filename).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == manifest[key]


def test_full_frozen_brain_boundary_suite_passes_with_machine_metrics() -> None:
    report = run_suite()
    aggregate = report["aggregate"]

    assert report["passed"] is True
    assert aggregate["case_count"] == aggregate["passed_case_count"] == 15
    assert aggregate["failed_case_count"] == 0
    assert aggregate["expected_boundary_outcome_accuracy"] == 1.0
    assert aggregate["expected_fail_closed_case_count"] == 7
    assert aggregate["fail_closed_expectation_accuracy"] == 1.0
    assert aggregate["intent_frames_validated"] == 15
    assert aggregate["plan_contracts_parsed"] == 16
    assert aggregate["plans_admitted"] == 12
    assert aggregate["plans_rejected"] == 4
    assert aggregate["stale_reports_ignored"] == 1
    assert aggregate["verified_facts_emitted"] == 10
    assert aggregate["verified_facts_accepted"] == 9
    assert aggregate["physical_navigation_episode_count"] == 0
    assert aggregate["physical_navigation_success_rate"] is None
    json.dumps(report, sort_keys=True, allow_nan=False)


def test_positive_cases_reach_only_bounded_semantic_callbacks() -> None:
    report = run_suite(
        case_ids=(
            "sidewalk_inside_boundary",
            "lamppost_near_boundary",
            "owner_orbit_one_boundary",
            "five_steps_away_boundary",
            "behind_follow_boundary",
            "hold_and_speech_boundary",
        )
    )

    assert report["passed"] is True
    assert _case(report, "sidewalk_inside_boundary")["actual"]["verified_facts"] == [
        "inside"
    ]
    assert _case(report, "lamppost_near_boundary")["actual"]["verified_facts"] == [
        "near"
    ]
    away = _case(report, "five_steps_away_boundary")["actual"]
    assert away["callbacks"] == [
        {
            "kind": "spatial_behavior",
            "value": {
                "behavior": "move_steps",
                "direction": "away_from_owner",
                "steps": 5,
                "size": "normal",
                "revolutions": 1.0,
            },
        }
    ]
    assert not any(
        forbidden in json.dumps(report["cases"], sort_keys=True)
        for forbidden in ('"vx"', '"vy"', '"joint"', '"priority"')
    )


def test_correction_interrupt_and_failure_boundaries_are_explicit() -> None:
    report = run_suite()

    correction = _case(report, "correction_at_checkpoint_boundary")["actual"]
    assert correction["replacement_disposition"] == "defer"
    assert correction["checkpoint_report_action"] == (
        "replacement_activated_at_checkpoint"
    )
    assert correction["stale_report_action"] == "ignored_stale_result"
    assert correction["new_plan_revision"] == 2

    stopped = _case(report, "explicit_stop_interrupt_boundary")["actual"]
    assert stopped["interrupt_action"] == "cancel_now"
    assert stopped["task_state"] == "cancelled"

    social = _case(report, "social_interrupt_deferred_boundary")["actual"]
    assert social["interrupt_action"] == "defer_when_idle"
    assert social["task_state"] == "succeeded"

    failed = _case(report, "failed_navigation_verifier_no_fact")["actual"]
    assert failed["task_state"] == "failed"
    assert failed["verified_facts"] == []


@pytest.mark.parametrize(
    ("case_id", "validation_code"),
    [
        ("ungrounded_sidewalk_rejected", "target_not_grounded"),
        ("stale_lidar_rejected", "lidar_stale"),
        ("owner_heading_ungrounded_rejected", "owner_heading_unavailable"),
        ("emergency_stop_admission_rejected", "emergency_stopped"),
    ],
)
def test_admission_failures_never_dispatch(case_id: str, validation_code: str) -> None:
    result = _case(run_suite(case_ids=(case_id,)), case_id)

    assert result["passed"] is True
    assert result["actual"]["admission"] == "rejected"
    assert result["actual"]["validation_code"] == validation_code
    assert result["actual"]["no_dispatch"] is True
    assert result["metrics"]["semantic_dispatches"] == 0
    assert result["metrics"]["runtime_callbacks"] == 0


def test_emergency_race_is_rechecked_at_executive_tick() -> None:
    case_id = "emergency_between_admission_and_dispatch"
    result = _case(run_suite(case_ids=(case_id,)), case_id)

    assert result["passed"] is True
    assert result["actual"]["admission"] == "accepted"
    assert result["actual"]["task_state"] == "waiting_precondition"
    assert result["actual"]["no_dispatch"] is True


def test_tampered_corpus_fails_before_a_case_can_run(tmp_path: Path) -> None:
    for filename in (
        "manifest.json",
        "router_cases.jsonl",
        "integration_cases.jsonl",
        "report.schema.json",
    ):
        (tmp_path / filename).write_bytes((SUITE / filename).read_bytes())
    with (tmp_path / "integration_cases.jsonl").open("ab") as stream:
        stream.write(b"\n")

    with pytest.raises(BrainSuiteError, match="frozen SHA-256"):
        load_frozen_suite(tmp_path / "manifest.json")


def test_report_states_the_scope_boundary() -> None:
    report = run_suite(case_ids=("sidewalk_inside_boundary",))

    assert report["claims"]["does_not_prove"] == [
        "language-model planning quality on unseen requests",
        "camera or LiDAR perception accuracy",
        "physical sidewalk, lamppost, orbit, distance, or formation geometry",
        "collision avoidance, dynamic-city robustness, Unitree locomotion, or latency",
    ]
