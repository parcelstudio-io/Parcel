import hashlib
import json
from pathlib import Path

import pytest

from parcel_robot.brain import DeterministicIntentRouter

REPO = Path(__file__).resolve().parents[1]
SUITE = REPO / "evals" / "companion" / "brain_v1"


def test_frozen_router_cases() -> None:
    manifest = json.loads((SUITE / "manifest.json").read_text(encoding="utf-8"))
    payload = (SUITE / "router_cases.jsonl").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == manifest["router_cases_sha256"]

    cases = [json.loads(line) for line in payload.decode().splitlines() if line]
    assert len(cases) == manifest["case_count"]
    router = DeterministicIntentRouter()
    for case in cases:
        frame = router.route(
            case["transcript"],
            turn_id=f"turn-{case['case_id']}",
            is_final=case["is_final"],
        )
        actual = frame.as_dict()
        for key, expected in case["expected"].items():
            if key == "affect":
                assert actual["affect_evidence"]["label"] == expected, case["case_id"]
            else:
                assert actual[key] == expected, case["case_id"]


def test_router_preserves_exact_transcript_identity_without_storing_text() -> None:
    transcript = "  Follow Me  "
    frame = DeterministicIntentRouter().route(
        transcript,
        turn_id="turn-exact",
        original_transcript_ref="transcript-store:item-7",
    )

    assert frame.original_transcript_ref == "transcript-store:item-7"
    assert frame.transcript_sha256 == hashlib.sha256(transcript.encode()).hexdigest()
    assert "transcript" not in frame.as_dict()


def test_partial_asr_can_never_become_actionable() -> None:
    router = DeterministicIntentRouter(skill_ids=("backflip",))
    for transcript in ("stop now", "follow me", "do backflip", "go to sidewalk"):
        frame = router.route(transcript, turn_id="turn-partial", is_final=False)
        assert frame.route == "clarify_or_abstain"
        assert frame.matched_rule == "non_final_transcript"


@pytest.mark.parametrize("transcript", ["use sport", "Use RL backend"])
def test_backend_selection_is_a_reviewed_direct_command(transcript: str) -> None:
    frame = DeterministicIntentRouter().route(transcript, turn_id="turn-backend")

    assert frame.route == "direct_skill"
    assert frame.matched_rule == "motion_backend_selection"


@pytest.mark.parametrize(
    ("transcript", "references"),
    [
        ("Go to the store and wait outside.", ("store",)),
        ("Go to the sidewalk after you move away from me.", ("sidewalk", "owner")),
        ("Walk around me once and follow behind me.", ("owner",)),
    ],
)
def test_multi_action_phrasing_cannot_be_absorbed_into_one_navigation_target(
    transcript: str,
    references: tuple[str, ...],
) -> None:
    frame = DeterministicIntentRouter().route(transcript, turn_id="turn-compound")

    assert frame.route == "deliberative_plan"
    assert frame.speech_act == "request"
    assert frame.matched_rule == "compound_physical_request"
    assert frame.spatial_references == references
    assert frame.requires_fresh_scene is True
