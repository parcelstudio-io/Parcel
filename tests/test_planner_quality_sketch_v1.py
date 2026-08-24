import hashlib
import json
from pathlib import Path

import pytest

from evals.companion.compare_planner_contract_size import project_plan_sketch
from evals.companion.run_planner_quality_sketch_v1 import (
    MANIFEST_PATH,
    REPO_ROOT,
    SUITE_ROOT,
    PlanSketchQualityError,
    _parser,
    load_frozen_suite,
    run_suite,
    write_report,
)
from parcel_robot.brain.plan_sketch import PlanSketch

PAIRED_RESULT = (
    REPO_ROOT / "evals/companion/planner_quality_v2/results/"
    "planner-v2-20260803-gemma4-cpu-run05.json"
)


def _paired_sketches() -> dict[str, PlanSketch]:
    report = json.loads(PAIRED_RESULT.read_text(encoding="utf-8"))
    return {
        case["case_id"]: PlanSketch.from_mapping(project_plan_sketch(case["raw_plan"]))
        for case in report["cases"]
    }


class PassingSketchProvider:
    def __init__(self) -> None:
        self.sketches = _paired_sketches()
        self.last_metrics: dict[str, object] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    def plan(self, transcript: str, **kwargs: object) -> PlanSketch:
        self.calls.append((transcript, kwargs))
        frame = kwargs["intent_frame"]
        schema = kwargs["response_schema"]
        assert frame.route == "deliberative_plan"
        assert kwargs["observation"].robot.x is None
        assert schema["x-parcel-output-contract"] == "plan_sketch_v1"
        assert set(schema["properties"]) == {"schema_version", "goal", "steps"}
        assert "task_id" not in schema["properties"]
        assert "Return exactly one PlanSketch v1" in kwargs["system_prompt"]
        case_id = frame.turn_id.removeprefix("planner-v2-")
        sketch = self.sketches[case_id]
        output_bytes = len(
            json.dumps(
                sketch.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        self.last_metrics = {
            "model_output_contract": "plan_sketch_v1",
            "model_output_bytes": output_bytes,
            "model_ttft_ms": 5.0,
            "model_http_ms": 10.0,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "_private_clock": 42.0,
        }
        return sketch


def test_manifest_locks_exact_paired_cases_sketch_schema_and_prompt() -> None:
    manifest, cases, locked = load_frozen_suite()

    assert MANIFEST_PATH == SUITE_ROOT / "manifest.json"
    assert manifest["output_contract"] == "plan_sketch_v1"
    assert len(cases) == manifest["case_count"] == 5
    expected = {
        "cases": "6717f2fbda80920133f20f4584630f78748b6146c17222600bf71471e9272d1a",
        "response_schema": "82cf50b2a99476edac7af12e09804482275a38e5299c31180fc7061f5b1ad0be",
        "planner_prompt": "609259572b17d976d3bf999010da0228ff891bb48dd8f396218901734cbefae3",
    }
    for name, digest in expected.items():
        assert manifest["locked_inputs"][name]["sha256"] == digest
        assert hashlib.sha256(locked[name].read_bytes()).hexdigest() == digest


def test_frozen_suite_compiles_raw_sketch_and_scores_identical_semantics() -> None:
    provider = PassingSketchProvider()
    report = run_suite(
        provider,
        inference={"model": {"id": "fake"}, "device": {"profile": "test"}},
        change_description="Exercise the complete frozen PlanSketch boundary.",
        run_id="planner-sketch-v1-test",
        recorded_at_utc="2026-08-03T12:50:00Z",
    )

    aggregate = report["aggregate"]
    assert aggregate["case_count"] == 5
    assert aggregate["passed_case_count"] == 5
    assert aggregate["failed_case_count"] == 0
    assert aggregate["plan_quality_accuracy"] == 1.0
    assert aggregate["physical_navigation_episode_count"] == 0
    assert aggregate["physical_navigation_success_rate"] is None
    assert aggregate["latency_ms"]["model_ttft"]["median"] == 5.0
    assert aggregate["latency_ms"]["model_http_full"]["median"] == 10.0
    assert aggregate["latency_ms"]["plan_compile"]["count"] == 5
    assert aggregate["latency_ms"]["plan_validation"]["count"] == 5
    assert aggregate["model_output_bytes"]["count"] == 5
    assert aggregate["tokens"]["completion"]["median"] == 50.0
    assert aggregate["tokens"]["total"]["median"] == 150.0
    assert len(provider.calls) == 5
    for case in report["cases"]:
        assert case["passed"] is True
        assert case["validation"]["status"] == "accepted"
        assert set(case["raw_plan_sketch"]) == {"schema_version", "goal", "steps"}
        assert "task_id" not in case["raw_plan_sketch"]
        assert case["admitted_plan_ir"]["source_turn_id"] == case["intent_frame"]["turn_id"]
        assert "_private_clock" not in case["provider_metrics"]
    correction = report["cases"][-1]
    assert correction["admitted_plan_ir"]["task_id"] == "active-navigation"
    assert correction["admitted_plan_ir"]["plan_revision"] == 2
    assert correction["admitted_plan_ir"]["requested_interrupt"] == "at_checkpoint"
    assert report["claims"]["does_not_prove"][0] == (
        "semantic skill execution or physical navigation success"
    )


def test_wrong_provider_contract_fails_without_physical_success_claim() -> None:
    class WrongProvider:
        def __init__(self) -> None:
            self.last_metrics = {"model_output_contract": "plan_ir_v1"}

        def plan(self, *_args: object, **_kwargs: object) -> object:
            return object()

    report = run_suite(
        WrongProvider(),
        inference={"model": {"id": "wrong-contract"}},
        change_description="Reject a provider that did not return PlanSketch.",
        case_ids=["sidewalk_then_hold"],
    )
    case = report["cases"][0]

    assert case["passed"] is False
    assert case["failures"] == ["provider"]
    assert case["raw_plan_sketch"] is None
    assert case["admitted_plan_ir"] is None
    assert case["provider_error"]["type"] == "TypeError"
    assert report["aggregate"]["physical_navigation_episode_count"] == 0
    assert report["aggregate"]["physical_navigation_success_rate"] is None


def test_case_selection_tamper_detection_and_immutable_writer(tmp_path: Path) -> None:
    report = run_suite(
        PassingSketchProvider(),
        inference={"model": {"id": "fake"}},
        change_description="Select one exact frozen case.",
        case_ids=["sidewalk_then_lamppost"],
    )
    assert report["corpus"]["selected_case_ids"] == ["sidewalk_then_lamppost"]
    assert report["aggregate"]["case_count"] == 1
    with pytest.raises(PlanSketchQualityError, match="unknown case IDs"):
        run_suite(
            PassingSketchProvider(),
            inference={"model": {"id": "fake"}},
            change_description="Reject unknown selection.",
            case_ids=["not-a-case"],
        )

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["locked_inputs"]["response_schema"]["sha256"] = "0" * 64
    tampered = tmp_path / "manifest.json"
    tampered.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PlanSketchQualityError, match="failed SHA-256"):
        load_frozen_suite(tampered)

    target = write_report(report, tmp_path / "result.json")
    assert json.loads(target.read_text(encoding="utf-8"))["run_id"] == report["run_id"]
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_report(report, target)


def test_cli_keeps_paired_1024_token_default_and_explicit_warm_gpu_fields() -> None:
    args = _parser().parse_args(
        [
            "--output",
            "unused.json",
            "--base-url",
            "http://127.0.0.1:8081",
            "--cache-state",
            "warm",
            "--device-profile",
            "cuda:rtx5000ada:sm89:31-of-31-layers",
            "--threads",
            "32",
            "--gpu-layers",
            "999",
        ]
    )

    assert args.plan_max_tokens == 1024
    assert args.plan_enable_thinking is False
    assert args.plan_temperature == 0.0
    assert args.plan_timeout == 90.0
    assert args.cache_state == "warm"
    assert args.gpu_layers == 999
