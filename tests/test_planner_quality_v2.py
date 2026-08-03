import hashlib
import json
from pathlib import Path

import pytest

from evals.companion.run_planner_quality_v2 import (
    MANIFEST_PATH,
    REPO_ROOT,
    SUITE_ROOT,
    PlannerQualityError,
    _inference,
    _parser,
    load_frozen_suite,
    run_suite,
    write_report,
)
from parcel_robot.brain import PlanIR


def _success(
    fact: str,
    *,
    target: str | None = None,
    confidence: float = 0.9,
) -> dict[str, object]:
    return {
        "fact": fact,
        "target": target,
        "tolerance_m": None,
        "confidence_min": confidence,
    }


def _step(
    step_id: str,
    skill: str,
    arguments: dict[str, object],
    preconditions: list[str],
    success: dict[str, object],
    resources: list[str],
    *,
    timeout_s: float,
    interruptibility: str = "checkpoint",
) -> dict[str, object]:
    return {
        "id": step_id,
        "skill": skill,
        "arguments": arguments,
        "preconditions": preconditions,
        "success": success,
        "timeout_s": timeout_s,
        "max_attempts": 1,
        "recovery": ["safe_stop"],
        "resources": resources,
        "interruptibility": interruptibility,
    }


def _navigate(step_id: str, target: str, fact: str) -> dict[str, object]:
    return _step(
        step_id,
        "NavigateTo",
        {"directive": target},
        ["base_available", "camera_fresh", "lidar_fresh", "target_grounded"],
        _success(fact, target=target),
        ["base", "attention"],
        timeout_s=120.0,
    )


def _hold(step_id: str) -> dict[str, object]:
    return _step(
        step_id,
        "Hold",
        {},
        ["base_available"],
        _success("motion_stopped", confidence=1.0),
        ["base"],
        timeout_s=10.0,
        interruptibility="immediate",
    )


def _plan_for(case_id: str, turn_id: str) -> PlanIR:
    goal: dict[str, object]
    steps: list[dict[str, object]]
    task_id = f"quality-{case_id}"
    revision = 1
    if case_id == "sidewalk_then_hold":
        goal = {
            "relation": "inside",
            "target": {"kind": "semantic_region", "query": "sidewalk"},
            "tolerance_m": 0.0,
        }
        steps = [_navigate("sidewalk", "sidewalk", "inside"), _hold("wait")]
    elif case_id == "sidewalk_then_lamppost":
        goal = {
            "relation": "near",
            "target": {"kind": "semantic_object", "query": "lamppost"},
            "tolerance_m": 0.0,
        }
        steps = [
            _navigate("sidewalk", "sidewalk", "inside"),
            _navigate("lamppost", "lamppost", "near"),
        ]
    elif case_id == "five_steps_away_then_hold":
        goal = {
            "relation": "relative",
            "target": {"kind": "owner", "query": "owner"},
            "tolerance_m": 0.0,
        }
        steps = [
            _step(
                "move-away",
                "MoveRelative",
                {"direction": "away_from_owner", "steps": 5},
                ["base_available", "lidar_fresh", "owner_visible"],
                _success("distance_travelled"),
                ["base"],
                timeout_s=60.0,
            ),
            _hold("wait"),
        ]
    elif case_id == "orbit_then_follow_behind":
        goal = {
            "relation": "behind",
            "target": {"kind": "owner", "query": "owner"},
            "tolerance_m": 0.0,
        }
        steps = [
            _step(
                "orbit",
                "OrbitOwner",
                {"direction": "clockwise", "size": "small", "revolutions": 1.0},
                ["base_available", "camera_fresh", "lidar_fresh", "owner_visible"],
                _success("orbit_complete", target="owner"),
                ["base", "attention"],
                timeout_s=180.0,
            ),
            _step(
                "follow",
                "FollowFormation",
                {"relation": "behind", "distance_m": 1.2},
                [
                    "base_available",
                    "camera_fresh",
                    "lidar_fresh",
                    "owner_visible",
                    "owner_heading_available",
                ],
                _success("behind", target="owner"),
                ["base", "attention"],
                timeout_s=300.0,
            ),
        ]
    elif case_id == "correct_active_task_to_lamppost":
        goal = {
            "relation": "near",
            "target": {"kind": "semantic_object", "query": "lamppost"},
            "tolerance_m": 0.0,
        }
        steps = [_navigate("lamppost", "lamppost", "near")]
        task_id = "active-navigation"
        revision = 2
    else:  # pragma: no cover - the frozen case list controls this helper
        raise AssertionError(case_id)
    return PlanIR.from_mapping(
        {
            "schema_version": 1,
            "task_id": task_id,
            "plan_revision": revision,
            "source_turn_id": turn_id,
            "goal": goal,
            "invariants": [],
            "steps": steps,
            "requested_interrupt": "at_checkpoint",
        }
    )


class PassingProvider:
    def __init__(self) -> None:
        self.last_metrics: dict[str, object] = {}

    def plan(self, _transcript: str, **kwargs: object) -> PlanIR:
        frame = kwargs["intent_frame"]
        assert frame.route == "deliberative_plan"
        assert kwargs["observation"].robot.x is None
        schema_skills = kwargs["response_schema"]["$defs"]["step"]["properties"]["skill"]["enum"]
        assert "Pose" not in schema_skills
        assert "NavigateTo" in schema_skills
        properties = kwargs["response_schema"]["properties"]
        assert properties["source_turn_id"]["const"] == frame.turn_id
        if frame.speech_act == "correction":
            assert properties["task_id"]["const"] == "active-navigation"
            assert properties["plan_revision"]["const"] == 2
            assert properties["requested_interrupt"]["const"] == "at_checkpoint"
        else:
            assert properties["task_id"]["const"].startswith("parcel-task-")
            assert properties["plan_revision"]["const"] == 1
            assert properties["requested_interrupt"]["const"] == "at_checkpoint"
        case_id = frame.turn_id.removeprefix("planner-v2-")
        self.last_metrics = {"model_http_ms": 10.0, "_private_clock": 42.0}
        plan = _plan_for(case_id, "model-authored-wrong-source")
        if frame.speech_act == "correction":
            mapping = plan.as_dict()
            mapping.update(
                {
                    "task_id": "model-invented-task",
                    "plan_revision": 1,
                    "requested_interrupt": "interrupt_now",
                }
            )
            return PlanIR.from_mapping(mapping)
        return plan


def test_manifest_locks_cases_prompt_and_raw_plan_schema() -> None:
    manifest, cases = load_frozen_suite()

    assert MANIFEST_PATH == SUITE_ROOT / "manifest.json"
    assert len(cases) == manifest["case_count"] == 5
    locked = (
        (SUITE_ROOT / str(manifest["cases_file"]), "cases_sha256"),
        (REPO_ROOT / str(manifest["planner_prompt"]), "planner_prompt_sha256"),
        (REPO_ROOT / str(manifest["plan_schema"]), "plan_schema_sha256"),
    )
    for path, key in locked:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest[key]


def test_all_frozen_cases_pass_the_runtime_routed_validation_boundary() -> None:
    report = run_suite(
        PassingProvider(),
        inference={"model": {"id": "fake"}, "device": {"profile": "test"}},
        change_description="Verify the complete frozen contract with a fake provider.",
        run_id="test-planner-quality-v2",
        recorded_at_utc="2026-08-03T12:00:00Z",
    )

    aggregate = report["aggregate"]
    assert aggregate["case_count"] == 5
    assert aggregate["passed_case_count"] == 5
    assert aggregate["failed_case_count"] == 0
    assert aggregate["plan_quality_accuracy"] == 1.0
    assert aggregate["physical_navigation_episode_count"] == 0
    assert aggregate["physical_navigation_success_rate"] is None
    assert aggregate["latency_ms"]["model_http"] == {
        "count": 5,
        "minimum": 10.0,
        "median": 10.0,
        "mean": 10.0,
        "p95_nearest_rank": 10.0,
        "maximum": 10.0,
    }
    assert aggregate["latency_ms"]["runner_case"]["count"] == 5
    assert aggregate["tokens"] == {
        "prompt": None,
        "completion": None,
        "total": None,
    }
    assert all(case["intent_frame"]["route"] == "deliberative_plan" for case in report["cases"])
    assert all(case["validation"]["status"] == "accepted" for case in report["cases"])
    assert all("_private_clock" not in case["provider_metrics"] for case in report["cases"])
    assert all(
        case["raw_plan"]["source_turn_id"] == "model-authored-wrong-source"
        for case in report["cases"]
    )
    assert all(
        case["admitted_plan"]["source_turn_id"] == case["intent_frame"]["turn_id"]
        for case in report["cases"]
    )
    correction = report["cases"][-1]
    assert correction["raw_plan"]["task_id"] == "model-invented-task"
    assert correction["admitted_plan"]["task_id"] == "active-navigation"
    assert correction["admitted_plan"]["plan_revision"] == 2
    assert correction["admitted_plan"]["requested_interrupt"] == "at_checkpoint"


def test_case_selection_is_exact_and_unknown_ids_fail_closed() -> None:
    report = run_suite(
        PassingProvider(),
        inference={"model": {"id": "fake"}},
        change_description="Select exactly one frozen case.",
        case_ids=["sidewalk_then_lamppost"],
    )

    assert report["corpus"]["selected_case_ids"] == ["sidewalk_then_lamppost"]
    assert report["aggregate"]["case_count"] == 1
    with pytest.raises(PlannerQualityError, match="unknown case IDs"):
        run_suite(
            PassingProvider(),
            inference={"model": {"id": "fake"}},
            change_description="Reject an unknown case.",
            case_ids=["not-a-case"],
        )


def test_prompt_challenger_is_repo_local_and_digest_recorded(tmp_path: Path) -> None:
    challenger = REPO_ROOT / "prompts/system/planner_v1.md"
    report = run_suite(
        PassingProvider(),
        inference={"model": {"id": "fake"}},
        change_description="Use a separately hashed prompt challenger.",
        case_ids=["sidewalk_then_hold"],
        planner_prompt=challenger,
    )

    assert report["corpus"]["planner_prompt"] == "prompts/system/planner_v1.md"
    assert (
        report["corpus"]["planner_prompt_sha256"]
        == hashlib.sha256(challenger.read_bytes()).hexdigest()
    )
    assert report["corpus"]["planner_prompt_is_manifest_default"] is False

    outside = tmp_path / "prompt.md"
    outside.write_text("not repository evidence", encoding="utf-8")
    with pytest.raises(PlannerQualityError, match="inside the repository"):
        run_suite(
            PassingProvider(),
            inference={"model": {"id": "fake"}},
            change_description="Reject an untracked prompt.",
            case_ids=["sidewalk_then_hold"],
            planner_prompt=outside,
        )


def test_provider_failure_is_logged_without_physical_success_claim() -> None:
    class FailedProvider:
        def __init__(self) -> None:
            self.last_metrics = {"model_request_error": "TimeoutError"}

        def plan(self, *_args: object, **_kwargs: object) -> PlanIR:
            raise TimeoutError("model did not respond")

    report = run_suite(
        FailedProvider(),
        inference={"model": {"id": "failed"}},
        change_description="Record an intentional provider failure.",
        case_ids=["sidewalk_then_hold"],
    )
    case = report["cases"][0]

    assert case["passed"] is False
    assert case["failures"] == ["provider"]
    assert case["raw_plan"] is None
    assert case["admitted_plan"] is None
    assert case["provider_error"]["type"] == "TimeoutError"
    assert report["aggregate"]["physical_navigation_episode_count"] == 0
    assert report["aggregate"]["physical_navigation_success_rate"] is None


def test_frozen_case_tampering_fails_before_inference(tmp_path: Path) -> None:
    for filename in ("manifest.json", "cases.json"):
        (tmp_path / filename).write_bytes((SUITE_ROOT / filename).read_bytes())
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(cases_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(PlannerQualityError, match="does not match cases_sha256"):
        load_frozen_suite(tmp_path / "manifest.json")


def test_model_digest_and_immutable_report_writer(tmp_path: Path) -> None:
    artifact = tmp_path / "model.gguf"
    artifact.write_bytes(b"test-model")
    expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
    args = _parser().parse_args(
        [
            "--output",
            str(tmp_path / "unused.json"),
            "--model-artifact",
            str(artifact),
            "--model-sha256",
            expected,
        ]
    )

    inference = _inference(args)
    assert inference["model"]["artifact_sha256"] == expected
    target = write_report({"run_id": "one"}, tmp_path / "run.json")
    assert json.loads(target.read_text(encoding="utf-8"))["run_id"] == "one"
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_report({"run_id": "two"}, target)

    args.model_sha256 = "0" * 64
    with pytest.raises(PlannerQualityError, match="does not match"):
        _inference(args)


def test_committed_live_results_are_self_consistent_and_indexed() -> None:
    manifest, _cases = load_frozen_suite()
    results_dir = SUITE_ROOT / "results"
    paths = sorted(results_dir.glob("planner-v2-*.json"))
    ledger = (results_dir / "README.md").read_text(encoding="utf-8")

    assert len(paths) >= 5
    run_ids: set[str] = set()
    reports: dict[str, dict[str, object]] = {}
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        run_id = report["run_id"]
        assert isinstance(run_id, str)
        assert run_id not in run_ids
        run_ids.add(run_id)
        reports[run_id] = report
        assert run_id in ledger
        assert report["schema_version"] == 1
        assert report["suite_id"] == "parcel-planner-quality-v2"
        assert report["corpus"]["cases_sha256"] == manifest["cases_sha256"]
        cases = report["cases"]
        aggregate = report["aggregate"]
        passed = sum(bool(case["passed"]) for case in cases)
        assert aggregate["case_count"] == len(cases)
        assert aggregate["passed_case_count"] == passed
        assert aggregate["failed_case_count"] == len(cases) - passed
        assert aggregate["physical_navigation_episode_count"] == 0
        assert aggregate["physical_navigation_success_rate"] is None

    final = reports["planner-v2-20260803120316Z-6406b694"]
    assert final["runner_version"] == "runtime-routed-plan-quality-v4"
    assert final["aggregate"]["passed_case_count"] == 5
    assert final["aggregate"]["plan_quality_accuracy"] == 1.0
    assert final["aggregate"]["latency_ms"]["model_ttft"]["median"] == 868.039
    assert final["aggregate"]["latency_ms"]["model_http"]["median"] == 19664.294
