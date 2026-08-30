"""Card C5: the receipt-typed speech-act contract, and the flag that is OFF.

WHAT THIS FILE PROVES
---------------------
1. The contract is the enum MB-2 froze — nine acts, one template each, slots
   validated at construction, and a post-condition checker whose rejection
   reasons come from a closed list.
2. The checker refuses what MB-2 built it to refuse: an unlicensed claim class,
   a swapped destination, a deleted inability sentence, a missing offer, an
   invented number, a sentence over the word cap.
3. ``realtime.speech_acts.enabled`` exists, defaults OFF, and refuses a typo.
4. **Off-path byte-identical.** With the flag OFF, ``narrate_event``'s output
   over MB-1's corpus digests to the value measured against the UNEDITED tree
   at ``704ba5c``, before any file on this card was touched. Nothing this card
   landed changes a single frame the lane sends.
5. Nothing under ``src/`` imports the research tree at runtime.

WHY THE DIGEST IS TAKEN THE WAY IT IS
-------------------------------------
A fresh lane per narration, not one lane and 180 calls: ``narrate_event``
refuses while a response is outstanding (lane.py's four noes), so a single lane
would narrate once and skip 179 times and the digest would pin the skip path
rather than the narration path. The texts are arm T's 180 rendered sentences,
regenerated here by the product modules — so the digest pins the templates too,
and a one-character drift in the port moves it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_narration_matcher import (  # the reproduction harness C5 owns, not a copy
    run_arm_t,
    skip_unless_research_present,
)

from parcel_robot.realtime import narration_matcher as nm
from parcel_robot.realtime import speech_acts as sa
from parcel_robot.realtime.config import (
    SPEECH_ACTS_ALLOWED_KEYS,
    RealtimeConfig,
    RealtimeConfigError,
    SpeechActsConfig,
    realtime_config_from_mapping,
    speech_acts_config_from_mapping,
)
from parcel_robot.realtime.fake_server import FakeRealtimeServer, handshake
from parcel_robot.realtime.lane import RealtimeLane
from parcel_robot.realtime.transport import transport_pair

REPO = Path(__file__).resolve().parents[1]

#: Measured at HEAD ``704ba5c`` with ``lane.py`` and ``realtime/config.py``
#: clean, BEFORE any edit on this card — see ``scrum/20260829/task_2/C5_STATUS.md``
#: §0.1 for the recipe and the recorded value.
OFF_PATH_DIGEST = "edaa32ed66fca69be4fce66afb5e2a04f0c55487f3c357f41ffcd1ba698dcecb"

#: The 180 arm-T sentences themselves, pinned separately so a failure says WHICH
#: half moved: the templates, or the lane.
ARM_T_TEXT_DIGEST = "7e54e3c742bc576935d928dcadab92a15b9f9eece6105bf84395ac9b4891ba8a"

#: Research module names that must never end up in the product's ``sys.modules``.
RESEARCH_MODULES = ("events", "scorer", "narrate", "steer", "contract", "arms", "mb1")


# ----------------------------------------------------- the flag-OFF lane rig
class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class _Sink:
    """The three ``SpeakerSink`` calls the lane may make. None of them fire here."""

    def begin_utterance(self) -> None: ...

    def enqueue(self, chunk: bytes, token: object = None) -> None: ...

    def interrupt(self) -> None: ...


def _open_lane(config: RealtimeConfig | None = None) -> RealtimeLane:
    clock = _Clock()
    servers: list[FakeRealtimeServer] = []

    def factory():
        lane_end, server_end = transport_pair(clock=clock)
        servers.append(
            FakeRealtimeServer(transport=server_end, script=list(handshake()), clock=clock)
        )
        return lane_end

    lane = RealtimeLane(
        config=config or RealtimeConfig(enabled=True, source="test"),
        instructions="be a good dog",
        transport_factory=factory,
        sink=_Sink(),
        clock=clock,
        duplex_output_active=lambda: False,
        session_id_factory=lambda: "rt_session_1",
    )
    lane.open_session(handshake_token="csrf-token", mic_gesture=True)
    servers[-1].pump()
    lane.pump()
    return lane


def _off_path_rows(texts: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, text in enumerate(texts):
        lane = _open_lane()
        accepted = bool(lane.narrate_event(text))
        sent = list(lane.transport.sent)  # type: ignore[union-attr]
        rows.append(
            {
                "index": index,
                "accepted": accepted,
                "items": [
                    {
                        "role": frame["item"]["role"],
                        "text": frame["item"]["content"][0]["text"],
                    }
                    for frame in sent
                    if frame.get("type") == "conversation.item.create"
                ],
                "narrations": lane.narrations,
                "skipped": lane.narrations_skipped,
                "sent_types": [str(frame.get("type")) for frame in sent],
            }
        )
    return rows


def _digest(payload: object) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ==================================================== the acts and the slots
def test_the_contract_is_the_nine_acts_mb2_froze() -> None:
    """Nine speech acts, plus the declared non-speech ``ask_clarify`` row."""

    assert sa.SPEECH_ACTS == (
        "ack",
        "progress",
        "blocked",
        "completed",
        "failed",
        "cancelled",
        "resumed",
        "resume_offer",
        "capability_refusal",
    )
    assert len(sa.SPEECH_ACTS) == 9
    assert sa.ACT_ASK_CLARIFY not in sa.SPEECH_ACTS
    assert set(sa.ACT_SLOTS) == {*sa.SPEECH_ACTS, sa.ACT_ASK_CLARIFY}


def test_every_act_renders_exactly_one_deterministic_sentence() -> None:
    """``render`` is a pure function of the act and its slots."""

    cases = {
        sa.ACT_ACK: ({"goal": "the bench"}, "Okay, I'll head to the bench."),
        sa.ACT_PROGRESS: ({"goal": "the bench"}, "I'm still on my way to the bench."),
        sa.ACT_COMPLETED: ({"goal": "the bench"}, "I'm at the bench."),
        sa.ACT_CANCELLED: ({"goal": "the bench"}, "I've stopped, so the bench is off the list."),
        sa.ACT_RESUME_OFFER: ({"goal": "the bench"}, "Shall I go to the bench next?"),
    }
    for act_name, (slots, expected) in cases.items():
        act = sa.SpeechAct(act_name, slots)
        assert sa.render(act) == expected
        assert sa.render(act) == sa.render(sa.SpeechAct(act_name, dict(slots)))

    assert sa.render(sa.SpeechAct(sa.ACT_ACK, {"goal": "the tree", "queued": True})) == (
        "Okay, I'll check the tree after that."
    )
    assert sa.render(sa.SpeechAct(sa.ACT_BLOCKED, {"klass": sa.CLASS_PERSON})) == (
        "Someone is in the way, so I'm waiting for it to clear."
    )
    assert sa.render(sa.SpeechAct(sa.ACT_BLOCKED, {"klass": sa.CLASS_OBSTACLE})) == (
        "Something is in the way, so I'm waiting for it to clear."
    )
    assert sa.render(
        sa.SpeechAct(sa.ACT_CAPABILITY_REFUSAL, {"keys": (sa.CAP_VISION,)})
    ) == sa.CAPABILITY_REFUSAL_TEXT[sa.CAP_VISION]


def test_an_act_with_a_slot_the_contract_does_not_know_is_a_wiring_bug() -> None:
    """The contract is the schema, not a suggestion."""

    with pytest.raises(ValueError, match="no slot"):
        sa.SpeechAct(sa.ACT_COMPLETED, {"distance_m": 4.2})
    with pytest.raises(ValueError, match="unknown speech act"):
        sa.SpeechAct("improvise", {})
    with pytest.raises(ValueError, match="not a capability key"):
        sa.SpeechAct(sa.ACT_CAPABILITY_REFUSAL, {"keys": ("telepathy",)})
    with pytest.raises(ValueError, match="not a block class"):
        sa.SpeechAct(sa.ACT_BLOCKED, {"klass": "weather"})


def test_every_capability_key_has_a_refusal_that_states_its_own_inability() -> None:
    """A refusal that does not say the inability is not a refusal."""

    assert set(sa.CAPABILITY_KEYS) == set(sa.CAPABILITY_REFUSAL_TEXT)
    assert set(sa.CAPABILITY_KEYS) == set(sa.CAPABILITY_INABILITY)
    for key, text in sa.CAPABILITY_REFUSAL_TEXT.items():
        assert sa.CAPABILITY_INABILITY[key].search(nm.normalise(text)) is not None, key


# ============================================================== the checker
def _receipt(fact: str, *, t: float, goal: str, detail: str = "", queue=()):
    """A minimal duck-typed receipt — the five fields the rules actually read."""

    class _R:
        pass

    r = _R()
    r.t = t
    r.fact = fact
    r.goal = goal
    r.detail = detail
    r.queue = queue
    r.event_id = f"t1:{fact}@{t:.1f}"
    return r


def _check(text: str, acts, *, receipts=(), at_s: float = 10.0, places=("the bench", "the door")):
    return sa.check(
        text,
        acts=acts,
        receipts=receipts,
        at_s=at_s,
        registry=nm.default_registry(),
        places=places,
    )


def test_the_template_passes_its_own_checker_when_the_receipt_is_behind_it() -> None:
    arrived = _receipt(nm.FACT_COMPLETED, t=9.0, goal="the bench")
    act = sa.SpeechAct(sa.ACT_COMPLETED, {"goal": "the bench"})
    result = _check(sa.render(act), (act,), receipts=(arrived,))
    assert result.ok, result.reasons
    assert result.claims == [nm.CLAIM_ARRIVAL]


def test_a_swapped_destination_is_a_rejection_the_scorer_cannot_see() -> None:
    """Slot fidelity: "I'm at the door" for a bench receipt is a foreign place."""

    arrived = _receipt(nm.FACT_COMPLETED, t=9.0, goal="the bench")
    act = sa.SpeechAct(sa.ACT_COMPLETED, {"goal": "the bench"})
    result = _check("I'm at the door.", (act,), receipts=(arrived,))
    assert not result.ok
    assert f"{sa.REASON_FOREIGN_PLACE}:door" in result.reasons
    assert f"{sa.REASON_MISSING_GOAL}:bench" in result.reasons
    # ...and the matcher alone would have called it grounded, which is the point.
    verdict = nm.score_turn(
        "I'm at the door.", receipts=(arrived,), at_s=10.0, registry=nm.default_registry()
    )
    assert verdict.grounded


def test_a_deleted_inability_sentence_is_a_rejection() -> None:
    """MB-2's decisive finding: grounding is blind to omission, the checker is not."""

    act = sa.SpeechAct(sa.ACT_CAPABILITY_REFUSAL, {"keys": (sa.CAP_VISION,)})
    deleted = "I'm here at the bench. What would you like me to do next?"
    result = _check(deleted, (act, sa.SpeechAct(sa.ACT_COMPLETED, {"goal": "the bench"})),
                    receipts=(_receipt(nm.FACT_COMPLETED, t=9.0, goal="the bench"),))
    assert not result.ok
    assert f"{sa.REASON_MISSING_INABILITY}:{sa.CAP_VISION}" in result.reasons


def test_a_resume_offer_without_an_offer_and_a_clarify_without_a_question_refuse() -> None:
    offer = sa.SpeechAct(sa.ACT_RESUME_OFFER, {"goal": "the bench"})
    assert sa.REASON_MISSING_OFFER in _check("The bench is next.", (offer,)).reasons
    clarify = sa.SpeechAct(sa.ACT_ASK_CLARIFY, {"question": "Which one do you mean?"})
    assert sa.REASON_MISSING_QUESTION in _check("Tell me which one.", (clarify,)).reasons


def test_an_invented_number_and_an_over_long_sentence_refuse() -> None:
    """No receipt in this vocabulary carries a distance or a duration."""

    arrived = _receipt(nm.FACT_COMPLETED, t=9.0, goal="the bench")
    act = sa.SpeechAct(sa.ACT_COMPLETED, {"goal": "the bench"})
    numbered = _check("I'm at the bench, about 3 metres from you.", (act,), receipts=(arrived,))
    assert sa.REASON_UNLICENSED_NUMBER in numbered.reasons

    long_text = "I'm at the bench, " + " ".join(["and I waited here for you"] * 6)
    assert len(long_text.split()) > sa.MAX_WORDS
    result = _check(long_text, (act,), receipts=(arrived,))
    assert any(reason.startswith(sa.REASON_TOO_LONG) for reason in result.reasons)
    assert _check("", (act,)).reasons == [sa.REASON_EMPTY]


def test_a_claim_no_act_licenses_is_refused_even_when_a_receipt_supports_it() -> None:
    """Licensing and support are two different questions, asked in that order."""

    accepted = _receipt(nm.FACT_ACCEPTED, t=1.0, goal="the bench")
    arrived = _receipt(nm.FACT_COMPLETED, t=9.0, goal="the bench")
    act = sa.SpeechAct(sa.ACT_PROGRESS, {"goal": "the bench"})
    result = _check("I'm on my way to the bench. I'm at the bench.", (act,),
                    receipts=(accepted, arrived))
    assert f"{sa.REASON_UNLICENSED_CLAIM}:{nm.CLAIM_ARRIVAL}" in result.reasons


def test_every_rejection_reason_comes_from_the_closed_enum() -> None:
    """A reason nobody enumerated is a reason nobody can act on."""

    act = sa.SpeechAct(sa.ACT_CAPABILITY_REFUSAL, {"keys": (sa.CAP_VISION,)})
    result = _check("I'll go and look around the room for 5 minutes.", (act,))
    assert not result.ok
    for reason in result.reasons:
        assert reason.split(":", 1)[0] in sa.REJECTION_REASONS, reason


# ================================================================ the flag
def test_the_speech_acts_flag_exists_and_defaults_off() -> None:
    """The card's bar: "the flag exists and defaults OFF (test)"."""

    assert SpeechActsConfig().enabled is False
    assert RealtimeConfig().speech_acts == SpeechActsConfig()
    assert RealtimeConfig().speech_acts.enabled is False
    # Absent file, absent block and an empty body all mean the same OFF.
    assert realtime_config_from_mapping(None).speech_acts.enabled is False
    assert realtime_config_from_mapping({}).speech_acts.enabled is False
    assert realtime_config_from_mapping({"speech_acts": {}}).speech_acts.enabled is False
    assert speech_acts_config_from_mapping(None).enabled is False
    # NOT in ``as_dict()`` in wave A: ``/api/state``'s key set is card TURN-1's
    # pre-registered "+1 key, 0 changed" row, which C5 does not own. A flag
    # nothing reads yet is not worth churning a frozen row to display; the
    # wave-B install adds it and re-pins that row. See C5_STATUS.md §5.
    assert "speech_acts" not in RealtimeConfig().as_dict()
    assert SpeechActsConfig().as_dict() == {"enabled": False}
    assert set(SpeechActsConfig().as_dict()) == SPEECH_ACTS_ALLOWED_KEYS
    # And it is a real switch, not a decoration.
    assert realtime_config_from_mapping({"speech_acts": {"enabled": True}}).speech_acts.enabled


def test_the_flag_block_refuses_a_typo_rather_than_reading_it_as_off() -> None:
    """``enabled: ture`` must be loud. A silent off switch is the whole risk."""

    assert SPEECH_ACTS_ALLOWED_KEYS == {"enabled"}
    for body, needle in (
        ({"speech_acts": {"enabled": "ture"}}, "must be a boolean"),
        ({"speech_acts": {"enabld": True}}, "unknown realtime.speech_acts key"),
        ({"speech_acts": ["enabled"]}, "must be a mapping"),
    ):
        with pytest.raises(RealtimeConfigError, match=needle):
            realtime_config_from_mapping(body)


# ====================================== off-path byte-identical (the card's bar)
def test_the_off_path_narration_is_byte_identical_with_the_flag_off() -> None:
    """"Off-path digest unchanged with the flag OFF" — the card's second bar.

    ``OFF_PATH_DIGEST`` was measured at HEAD ``704ba5c`` before a line of this
    card existed. Reproducing it here means the two new modules, the new config
    block and the new tests changed nothing about what the lane puts on the
    wire when a caller narrates a fact.
    """

    skip_unless_research_present()
    texts = run_arm_t()["texts"]
    assert len(texts) == 180
    assert _digest(texts) == ARM_T_TEXT_DIGEST, (
        "the product templates no longer render MB-2's arm-T sentences; the "
        "off-path digest below cannot be read as a lane result until this is."
    )
    assert _digest(_off_path_rows(texts)) == OFF_PATH_DIGEST


def test_the_flag_being_off_is_what_the_lane_actually_sees() -> None:
    """The off-path digest above is taken under a config whose flag is OFF."""

    lane = _open_lane()
    assert lane.config.speech_acts.enabled is False
    assert lane.narrate_event("I'm at the bench.") is True
    items = [
        frame["item"]["content"][0]["text"]
        for frame in lane.transport.sent  # type: ignore[union-attr]
        if frame.get("type") == "conversation.item.create"
    ]
    assert items == ["I'm at the bench."], (
        "with the flag OFF the lane sends the caller's own text, unrewritten"
    )


# ============================================ no research import from src/
def test_the_product_modules_import_no_research_code_at_runtime() -> None:
    """"no research import from ``src/``" — the card's third bar.

    Proven by running, not by reading: a subprocess imports both modules with
    only ``src`` on the path and reports whether any research module name ended
    up in ``sys.modules``.
    """

    probe = (
        "import json, sys;"
        "sys.path.insert(0, 'src');"
        "import parcel_robot.realtime.speech_acts;"
        "import parcel_robot.realtime.narration_matcher as nm;"
        "nm.default_registry();"
        f"print(json.dumps(sorted(set(sys.modules) & set({RESEARCH_MODULES!r}))))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []
    for module in (sa, nm):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "sys.path" not in source, f"{module.__name__} manipulates sys.path"
