import hashlib
import json
from pathlib import Path

import pytest

from parcel_robot.brain.router import DeterministicIntentRouter

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


@pytest.mark.parametrize(
    ("transcript", "skill"),
    [
        ("Can you nod your head?", "head_nod"),
        ("Please shake your head no.", "head_shake"),
        ("Give me a chuckle", "chuckle"),
        ("Could you shrug?", "shrug"),
        ("Tilt your head like you're confused", "confused_head_tilt"),
        ("Look curious", "observing_head_tilt"),
    ],
)
def test_reviewed_gesture_aliases_route_to_exact_catalog_skills(
    transcript: str,
    skill: str,
) -> None:
    router = DeterministicIntentRouter(
        skill_ids=(
            "head_nod",
            "head_shake",
            "chuckle",
            "shrug",
            "confused_head_tilt",
            "observing_head_tilt",
        )
    )

    frame = router.route(transcript, turn_id=f"turn-{skill}")

    assert frame.route == "direct_skill"
    assert frame.matched_rule == f"catalog_skill:{skill}"
    assert frame.router_version == "deterministic-v1.2"


@pytest.mark.parametrize(
    "transcript",
    ["Don't shake your head.", "Never shrug.", "What would happen if you nod?"],
)
def test_gesture_aliases_do_not_bypass_non_authoritative_motion_guard(
    transcript: str,
) -> None:
    router = DeterministicIntentRouter(
        skill_ids=("head_nod", "head_shake", "shrug")
    )

    frame = router.route(transcript, turn_id="turn-no-gesture")

    assert frame.route == "conversation_only"
    assert frame.matched_rule == "non_authoritative_motion_mention"


@pytest.mark.parametrize(
    "transcript",
    [
        "I'm really excited!",
        "I cannot wait for tomorrow.",
        "I'm looking forward to our walk.",
    ],
)
def test_explicit_anticipation_is_distinct_from_general_happiness(transcript: str) -> None:
    frame = DeterministicIntentRouter().route(transcript, turn_id="turn-excited")

    assert frame.route == "conversation_only"
    assert frame.affect_evidence is not None
    assert frame.affect_evidence.label == "excited"
    assert frame.affect_evidence.confidence == 1.0


def test_wait_request_is_not_misclassified_as_excitement() -> None:
    frame = DeterministicIntentRouter().route(
        "Can you wait by the lamppost?", turn_id="turn-wait"
    )

    assert frame.affect_evidence is None


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


@pytest.mark.parametrize(
    "transcript",
    ["come here", "Come", "come to me", "Come over", "here boy"],
)
def test_come_is_a_reviewed_direct_command_so_its_system_sketch_can_admit(
    transcript: str,
) -> None:
    """COME must reach the *system* registry, not the model-facing one.

    Its cap is a system-authored PlanSketch with
    ``FollowFormation(relation="follow")``, and only ``system_authored``
    registries admit that relation (arbitration OB-2). Before 2026-08-06 the
    router let these phrases fall through to ``_PHYSICAL_CUE`` →
    ``deliberative_plan``, so every "come here" was validated against the
    model-facing registry, failed with ``invalid_argument_value`` and returned
    the generic refusal. The closed intent existed but was unreachable.
    """

    frame = DeterministicIntentRouter().route(transcript, turn_id="turn-come")

    assert frame.route == "direct_skill"
    assert frame.matched_rule == "come_to_owner"
    assert frame.speech_act == "request"
    assert frame.spatial_references == ("owner",)
    assert frame.requires_fresh_scene is True


@pytest.mark.parametrize(
    ("transcript", "route", "rule"),
    [
        # Negation and hypotheticals still lose motion authority.
        ("don't come here", "conversation_only", "non_authoritative_motion_mention"),
        # A second action still forces the deliberative lane.
        ("come here and sit", "deliberative_plan", "compound_physical_request"),
        # Free-form "come" phrasing outside the closed set is not a direct skill.
        ("come to the kitchen please", "deliberative_plan", "ambiguous_physical_request"),
    ],
)
def test_come_direct_routing_does_not_widen_beyond_the_closed_grammar(
    transcript: str,
    route: str,
    rule: str,
) -> None:
    frame = DeterministicIntentRouter().route(transcript, turn_id="turn-come-neg")

    assert frame.route == route
    assert frame.matched_rule == rule
