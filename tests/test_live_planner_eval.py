import hashlib
import json
from pathlib import Path

import pytest

from evals.companion.run_live_planner_v1 import (
    MANIFEST_PATH,
    REPO_ROOT,
    RESULT_SCHEMA_PATH,
    SUITE_ROOT,
    LivePlannerEvalError,
    _inference_metadata,
    _parser,
    load_frozen_case,
    replay_record,
    run_live_evaluation,
    write_result,
)
from parcel_robot.brain.contracts import PlanIR

RECORDED_RUN = SUITE_ROOT / "results" / "live-planner-20260803-gemma4-run05.json"


def _record() -> dict[str, object]:
    value = json.loads(RECORDED_RUN.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_manifest_locks_case_prompt_plan_schema_and_result_schema() -> None:
    manifest, case, intent, snapshot = load_frozen_case()

    assert MANIFEST_PATH == SUITE_ROOT / "manifest.json"
    assert RESULT_SCHEMA_PATH == SUITE_ROOT / "result.schema.json"
    assert manifest["standalone_probe_profile"] == "full_default_registry/raw_plan_schema"
    assert case["case_id"] == "live-sidewalk-plan-v1"
    assert intent.route == "direct_skill"
    assert intent.matched_rule == "navigation_directive"
    assert snapshot.snapshot_id == "live-sidewalk-snapshot-v5"
    assert snapshot.camera.age_ms == 30.0
    assert snapshot.lidar.age_ms == 20.0
    assert snapshot.robot.x is None

    locked = (
        (SUITE_ROOT / str(manifest["case_file"]), "case_sha256"),
        (REPO_ROOT / str(manifest["planner_prompt"]), "planner_prompt_sha256"),
        (REPO_ROOT / str(manifest["plan_schema"]), "plan_schema_sha256"),
        (SUITE_ROOT / str(manifest["result_schema"]), "result_schema_sha256"),
    )
    for path, key in locked:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest[key]


def test_recorded_gemma_run_replays_exact_validation_boundary() -> None:
    report = replay_record(RECORDED_RUN)
    record = _record()

    assert report["replay_matched"] is True
    assert report["mismatches"] == []
    assert report["current_validation"] == record["output"]["validation"]
    assert report["current_validation"]["plan_sha256"] == (
        "8ab455dfd03a9316a0007987abcccc1655129839e40876025186ac41a4f248fc"
    )
    assert report["current_validation"]["effective_invariants"] == [
        "keep_collision_margin",
        "avoid_road_when_not_crossing",
        "stop_on_stale_perception",
        "yield_to_people",
        "do_not_interrupt_critical_task",
    ]


def test_record_preserves_latency_tokens_device_and_zero_physical_claim() -> None:
    record = _record()
    metrics = record["provider_metrics"]
    inference = record["inference"]

    assert metrics["overall_elapsed_ms"] == 24825.232
    assert metrics["model_http_ms"] == 24824.538
    assert metrics["model_ttft_ms"] == 5791.517
    assert (metrics["prompt_tokens"], metrics["completion_tokens"], metrics["total_tokens"]) == (
        2272,
        537,
        2809,
    )
    assert inference["model"]["artifact_sha256"] == (
        "3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d"
    )
    assert inference["device"]["gpu_layers"] == 0
    assert inference["device"]["gpu_available_but_unused"] is True
    assert record["claims"]["physical_navigation_episode_count"] == 0
    assert record["claims"]["physical_navigation_success_rate"] is None
    assert "explicit_provider_boundary_probe" == inference["routing_context"][
        "planner_invocation"
    ]


def test_fake_live_provider_uses_strict_frozen_objects_and_standalone_profile() -> None:
    raw_plan = _record()["output"]["raw_plan"]

    class FakeProvider:
        def __init__(self) -> None:
            self.last_metrics = {
                "model_http_ms": 12.0,
                "model_ttft_ms": 3.0,
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
                "_first_output_monotonic": 999.0,
            }

        def plan(self, transcript: str, **kwargs: object) -> PlanIR:
            assert transcript.endswith("It's dangerous.")
            assert kwargs["intent_frame"].route == "direct_skill"
            assert kwargs["observation"].snapshot_id == "live-sidewalk-snapshot-v5"
            registry = kwargs["skill_contracts"]["skill_registry"]
            assert "Pose" in {item["name"] for item in registry["skills"]}
            schema_skills = kwargs["response_schema"]["$defs"]["step"]["properties"][
                "skill"
            ]["enum"]
            assert "Pose" in schema_skills
            return PlanIR.from_mapping(raw_plan)

    result = run_live_evaluation(
        FakeProvider(),
        inference={"model": {"id": "fake"}, "device": {"profile": "test"}},
        change_description="Exercise the frozen provider boundary with a fake.",
        run_id="test-live-planner-run",
        recorded_at_utc="2026-08-03T12:00:00Z",
    )

    assert result["output"]["parse_status"] == "parsed"
    assert result["output"]["validation"]["status"] == "accepted"
    assert result["provider_metrics"]["total_tokens"] == 30
    assert "_first_output_monotonic" not in result["provider_metrics"]
    assert result["claims"]["physical_navigation_episode_count"] == 0


def test_failed_provider_call_is_retained_without_a_false_plan_claim() -> None:
    class FailedProvider:
        def __init__(self) -> None:
            self.last_metrics = {
                "model_http_ms": 90.0,
                "model_request_error": "TimeoutError",
            }

        def plan(self, *_args: object, **_kwargs: object) -> PlanIR:
            raise TimeoutError("model did not respond")

    result = run_live_evaluation(
        FailedProvider(),
        inference={"model": {"id": "failed"}, "device": {"profile": "test"}},
        change_description="Record an intentional provider failure fixture.",
        run_id="test-failed-provider-run",
        recorded_at_utc="2026-08-03T12:00:00Z",
    )

    assert result["output"]["parse_status"] == "provider_error"
    assert result["output"]["provider_error"]["type"] == "TimeoutError"
    assert result["output"]["raw_plan"] is None
    assert result["output"]["validation"]["status"] == "not_run"
    assert replay_record(result)["replay_matched"] is True


def test_model_artifact_digest_is_computed_and_optional_expectation_is_checked(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "model.gguf"
    artifact.write_bytes(b"tiny-test-model")
    expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
    args = _parser().parse_args(
        ["--model-artifact", str(artifact), "--model-sha256", expected]
    )

    metadata = _inference_metadata(args)

    assert metadata["model"]["artifact_size_bytes"] == len(b"tiny-test-model")
    assert metadata["model"]["artifact_sha256"] == expected
    args.model_sha256 = "0" * 64
    with pytest.raises(LivePlannerEvalError, match="does not match"):
        _inference_metadata(args)


def test_replay_detects_plan_tampering_without_contacting_model() -> None:
    record = json.loads(json.dumps(_record()))
    record["output"]["raw_plan"]["steps"][0]["arguments"]["directive"] = "lamppost"

    replay = replay_record(record)

    assert replay["replay_matched"] is False
    assert "output.validation.status" in replay["mismatches"]
    assert "output.validation.plan_sha256" in replay["mismatches"]


def test_frozen_case_tampering_fails_before_provider_call(tmp_path: Path) -> None:
    for filename in ("manifest.json", "sidewalk_case.json", "result.schema.json"):
        (tmp_path / filename).write_bytes((SUITE_ROOT / filename).read_bytes())
    case = tmp_path / "sidewalk_case.json"
    case.write_text(case.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(LivePlannerEvalError, match="frozen SHA-256"):
        load_frozen_case(tmp_path / "manifest.json")


def test_result_writer_is_immutable_by_default(tmp_path: Path) -> None:
    target = tmp_path / "run.json"
    write_result(_record(), target)

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_result(_record(), target)
