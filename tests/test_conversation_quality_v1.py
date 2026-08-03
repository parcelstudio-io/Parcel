from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.companion.run_conversation_quality_v1 import (
    MANIFEST_PATH,
    ConversationQualityError,
    load_frozen_suite,
    run_conversation_suite,
    write_result,
)
from parcel_robot.models import ActionProposal, AffectEstimate, AgentDecision


class _FakeProvider:
    def __init__(self) -> None:
        self.system_prompt = ""
        self.last_metrics: dict[str, object] = {}

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    def decide(
        self,
        transcript: str,
        tools: list[dict[str, object]],
        context: list[dict[str, str]],
    ) -> AgentDecision:
        assert tools == []
        assert "Never invent joint values" in self.system_prompt
        self.last_metrics = {
            "model_http_ms": 10.0,
            "model_ttft_ms": 2.0,
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "_first_output_monotonic": 1.0,
        }
        if "promotion" in transcript:
            return AgentDecision(
                "Congratulations—that is great news!",
                intent="celebration",
                affect=AffectEstimate("happy", 0.9),
                next_action=ActionProposal(
                    kind="skill",
                    name="paw_wave",
                    trigger="inferred_affect",
                    timing_preference="when_safe",
                    interruption_request="none",
                    reason="celebration",
                ),
            )
        if "terrible day" in transcript:
            return AgentDecision(
                "I'm sorry it was so hard. I'm here with you.",
                intent="emotional_support",
                affect=AffectEstimate("sad", 0.9),
            )
        # These deliberately do not satisfy every semantic rubric; the test
        # verifies honest aggregation rather than manufacturing a perfect fake.
        return AgentDecision("I'm here to talk.", intent="conversation")


def test_manifest_locks_all_conversation_inputs() -> None:
    manifest, cases = load_frozen_suite()

    assert manifest["case_count"] == 10
    assert len(cases) == 10
    assert manifest["physical_navigation_episode_count"] == 0
    assert {case["personality_id"] for case in cases} == {
        "calm_guardian",
        "gentle_companion",
        "playful_companion",
    }


def test_fake_provider_records_separate_machine_and_human_claims() -> None:
    result = run_conversation_suite(
        _FakeProvider(),
        inference={"model": {"id": "fake"}, "device": {"profile": "test"}},
        change_description="Test the frozen conversation boundary.",
        run_id="conversation-test",
        recorded_at_utc="2026-08-03T15:00:00Z",
    )

    aggregate = result["aggregate"]
    assert aggregate["case_count"] == 10
    assert aggregate["provider_parse_success_rate"] == 1.0
    assert aggregate["machine_case_accuracy"] < 1.0
    assert aggregate["human_review_completed"] is False
    assert aggregate["human_conversation_quality_score"] is None
    assert result["claims"] == {
        "physical_navigation_episode_count": 0,
        "physical_navigation_success_rate": None,
        "motion_dispatched": False,
        "machine_checks_prove_conversational_quality": False,
        "human_review_required": True,
        "official_external_evaluation": False,
    }
    assert "_first_output_monotonic" not in result["cases"][0]["latency_ms"]


def test_manifest_tampering_fails_before_provider_call(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["case_count"] = 9
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ConversationQualityError, match="case count"):
        load_frozen_suite(changed)


def test_result_writer_is_immutable(tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    write_result({"ok": True}, target)

    with pytest.raises(FileExistsError):
        write_result({"ok": False}, target)
