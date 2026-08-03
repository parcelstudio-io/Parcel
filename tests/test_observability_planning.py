from __future__ import annotations

import pytest

from parcel_robot.observability import (
    COMPONENT_METRIC_DEFINITIONS,
    PLANNING_LATENCY_DEFINITIONS,
    PLANNING_STAGE_DEFINITIONS,
    STAGES,
    ComponentMetrics,
    LatencyTracker,
)


def test_planning_trace_reports_e2e_and_component_intervals() -> None:
    tracker = LatencyTracker(max_turns=2)
    tracker.start(7, "Please wait by the lamppost", now=100.0)
    tracker.mark(7, "intent_routed", now=100.012)
    tracker.mark(7, "observation_snapshot", now=100.020)
    tracker.mark(7, "plan_first_output", now=100.150)
    tracker.mark(7, "plan_response", now=100.400)
    tracker.mark(7, "plan_validated", now=100.410)
    tracker.mark(7, "plan_accepted", now=100.425)
    tracker.finalize(7, now=100.500)

    snapshot = tracker.snapshot()
    row = snapshot["turns"][0]
    latency = row["latency_ms"]
    assert latency["UserQueryEndToFirstPlanOutput"] == pytest.approx(150.0)
    assert latency["UserQueryEndToAcceptedPlan"] == pytest.approx(425.0)
    assert latency["IntentRouting"] == pytest.approx(12.0)
    assert latency["ObservationSnapshotBuild"] == pytest.approx(8.0)
    assert latency["PlanTimeToFirstOutput"] == pytest.approx(130.0)
    assert latency["PlanDecode"] == pytest.approx(380.0)
    assert latency["PlanValidation"] == pytest.approx(10.0)
    assert latency["PlanAcceptance"] == pytest.approx(15.0)
    assert row["stage_offsets_ms"]["plan_accepted"] == pytest.approx(425.0)
    assert snapshot["aggregate"]["UserQueryEndToAcceptedPlan"]["count"] == 1


def test_non_streaming_plan_response_is_first_plan_output_fallback() -> None:
    tracker = LatencyTracker(max_turns=1)
    tracker.start(1, "go to the sidewalk", now=5.0)
    tracker.mark(1, "intent_routed", now=5.01)
    tracker.mark(1, "observation_snapshot", now=5.02)
    tracker.mark(1, "plan_response", now=5.20)
    tracker.finalize(1, now=5.21)

    latency = tracker.snapshot()["turns"][0]["latency_ms"]
    assert latency["UserQueryEndToFirstPlanOutput"] == pytest.approx(200.0)
    assert latency["PlanTimeToFirstOutput"] == pytest.approx(180.0)
    assert latency["UserQueryEndToAcceptedPlan"] is None
    assert latency["PlanValidation"] is None


def test_planning_first_output_retains_earliest_provider_timestamp() -> None:
    tracker = LatencyTracker(max_turns=1)
    tracker.start(1, "circle around me", now=10.0)
    tracker.mark(1, "observation_snapshot", now=10.1)
    tracker.mark(1, "plan_first_output", now=12.0)
    tracker.mark(1, "plan_first_output", now=10.4)
    tracker.mark(1, "plan_response", now=12.1)
    tracker.finalize(1, now=12.2)

    latency = tracker.snapshot()["turns"][0]["latency_ms"]
    assert latency["UserQueryEndToFirstPlanOutput"] == pytest.approx(400.0)
    assert latency["PlanTimeToFirstOutput"] == pytest.approx(300.0)


def test_planning_vocabulary_is_documented_without_closing_component_names() -> None:
    assert set(PLANNING_STAGE_DEFINITIONS) <= STAGES

    snapshot = LatencyTracker().snapshot()
    assert snapshot["stage_definitions"] == PLANNING_STAGE_DEFINITIONS
    assert set(PLANNING_LATENCY_DEFINITIONS) <= set(snapshot["definitions"])
    assert snapshot["component_definitions"] == COMPONENT_METRIC_DEFINITIONS

    components = ComponentMetrics()
    components.observe_ms("IntentRouter", 0.4)
    components.observe_ms("ApplicationSpecificSensor", 1.2)
    assert set(components.snapshot()) == {"ApplicationSpecificSensor", "IntentRouter"}
    assert components.snapshot()["IntentRouter"]["p99_ms"] == pytest.approx(0.4)
