"""Card P2-B — the dog notices you: identity as a label, affect, and initiative.

WHAT THIS FILE IS FOR
---------------------
Three defects from the 2026-08-22 audit, and one absolute constraint that binds
all three.

1. **Identity was wired and inert.** ``realtime/voice_identity.py`` boots
   ``verify_disabled`` with no enrolled profile, and nothing anywhere recorded
   WHOSE voice a ledger row was. Card P2-B stamps a label on every row — and the
   absolute is that it is a LABEL: the emergency class stays ungated, no refusal
   path is added, and computing a label may never change an arming decision.
2. **"I'm feeling sad" did nothing on the lane that ships.** P0-B reached the
   grammar from the hosted ingress; this card gives the reach a name in
   ``brain/router.py`` and keeps the rolling history P2-A's distiller reads.
3. **The dog never went first.** Every whisperer class had the ROBOT as its
   subject, so there was no vocabulary for "you just walked in".

THE THREE SEEDS THIS FILE EXISTS TO KEEP RED
--------------------------------------------
* **gate-becomes-blocking** — a build where a label can refuse anything, or
  where the emergency class stops arming, fails
  ``test_a_label_can_never_change_an_arming_decision`` and
  ``test_no_state_of_the_gate_can_make_the_emergency_class_blocking``.
* **affect-on-legacy-only** — a build where the hosted ``KIND_NONE`` path
  records nothing fails ``test_i_am_sad_yields_one_row_and_one_gesture``.
* **greeting storms past the cap** — a watcher that could bypass the whisperer's
  band, dedup, min-gap or per-window cap fails
  ``test_a_flapping_track_can_never_spend_past_the_owners_cap`` and
  ``test_no_owner_event_is_critical``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.router import (
    AFFECT_VERDICT_ADMITTED,
    AFFECT_VERDICT_BELOW_CONFIDENCE,
    AFFECT_VERDICT_NONE,
    affect_for_lane,
    lane_affect_from_evidence,
)
from parcel_robot.models import ActionProposal, AgentDecision
from parcel_robot.realtime.config import (
    OWNER_EVENTS_ALLOWED_KEYS,
    WHISPERER_ALLOWED_KEYS,
    OwnerEventsConfig,
    RealtimeConfigError,
    WhispererConfig,
    realtime_config_from_mapping,
    whisperer_config_from_mapping,
)
from parcel_robot.realtime.ingress import KIND_EMERGENCY, KIND_NONE
from parcel_robot.realtime.voice_identity import (
    CODE_ARMED,
    CODE_DISABLED,
    CODE_NOT_OWNER,
    CODE_PENDING,
    CODE_SAFETY_NEVER_GATED,
    CODE_TOO_SHORT,
    CODE_VERIFY_ERROR,
    LABEL_NOT_OWNER,
    LABEL_OWNER,
    LABEL_UNENROLLED,
    LABEL_UNGATED,
    LABEL_UNVERIFIED,
    SPEAKER_LABELS,
    VOICE_LABEL_KIND,
    FakeSpeakerEmbedder,
    OwnerVoiceProfile,
    SpeakerLabel,
    VoiceIdentityError,
    VoiceIdentityGate,
    VoiceVerdict,
    gate_decision,
    speaker_label,
    unenrolled_label,
)
from parcel_robot.realtime.whisperer import (
    ALWAYS_BAND,
    CRITICAL_KINDS,
    KIND_BATTERY_STATE,
    KIND_GREETING_DUE,
    KIND_OWNER_APPEARED,
    KIND_OWNER_RETURNED,
    KIND_QUESTION_OF_THE_DAY,
    OWNER_EVENT_KINDS,
    OwnerEventWatcher,
    OwnerPresence,
    StateEvent,
    Whisperer,
    band_of,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "test"
SAD = "I'm feeling sad today."


# ============================================================ 0. the fixtures
class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _Backend:
    """A backend whose owner track is scriptable. The P1-C drop-in, from below."""

    name = BACKEND_NAME

    def __init__(self) -> None:
        self.owner_visible = False
        self.owner_confidence = 1.0
        self.now = 0.0

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=self.now,
            robot=RobotPose(),
            owner=OwnerTrack(
                visible=self.owner_visible,
                confidence=self.owner_confidence if self.owner_visible else 0.0,
            ),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )

    def move(self, command: object) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del tools, context, transcript
        return AgentDecision("Understood.")


def _runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    backend: _Backend | None = None,
    hosted_affect: bool = True,
    owner_events: str = "",
) -> RobotRuntime:
    """A runtime with a REAL realtime config file and no socket anywhere.

    ``enabled: false`` throughout: every path this card adds is on the ingress,
    the ledger writer or the control loop, and not one of them needs an open
    hosted session. A test that could reach for one would be a test that can
    spend the owner's money.
    """

    from parcel_robot.realtime.config import REALTIME_CONFIG_ENV

    tmp_path.mkdir(parents=True, exist_ok=True)
    realtime = tmp_path / "p2b-realtime.yaml"
    realtime.write_text(
        "enabled: false\nmode: text\n"
        f"hosted_affect: {str(bool(hosted_affect)).lower()}\n" + owner_events,
        encoding="utf-8",
    )
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(realtime))
    path = tmp_path / "p2b-robot.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
  affect:
    minimum_confidence: 0.5
memory:
  path: ":memory:"
duplex:
  enabled: true
  logging: true
  log_dir: {tmp_path / "duplex-logs"}
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        backend or _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="p2b fixture",
        ),
    )


def _enrolled_gate(*, clock: _Clock | None = None) -> VoiceIdentityGate:
    embedder = FakeSpeakerEmbedder(dim=8)
    profile = OwnerVoiceProfile(
        embedding=embedder.embed(b"\x01\x02" * 32, 24_000),
        model="fake",
        utterances=3,
        created_at="2026-08-22T00:00:00+00:00",
    )
    return VoiceIdentityGate(
        embedder=embedder,
        profile=profile,
        clock=clock or _Clock(),
    )


def _unenrolled_gate() -> VoiceIdentityGate:
    return VoiceIdentityGate(embedder=None, profile=None)


# ================================== 1. identity is a LABEL (deliverable 1)
_VERDICTS = (
    None,
    VoiceVerdict(code=CODE_ARMED, passed=True, score=0.91),
    VoiceVerdict(code=CODE_NOT_OWNER, passed=False, score=0.12),
    VoiceVerdict(code=CODE_TOO_SHORT, passed=False),
    VoiceVerdict(code=CODE_PENDING, passed=False),
    VoiceVerdict(code=CODE_VERIFY_ERROR, passed=False),
    VoiceVerdict(code=CODE_DISABLED, passed=False),
)


@pytest.mark.parametrize("verdict", _VERDICTS)
@pytest.mark.parametrize("enrolled", [True, False])
@pytest.mark.parametrize("kind", [KIND_EMERGENCY, KIND_NONE, "tool", VOICE_LABEL_KIND])
def test_a_label_can_never_change_an_arming_decision(
    verdict: VoiceVerdict | None, enrolled: bool, kind: str
) -> None:
    """THE SEED: gate-becomes-blocking.

    Fifty-six combinations of class, verdict and enrolment (7 verdicts x 2
    enrolment states x 4 classes). In every one of
    them the arming decision is IDENTICAL before and after a label is computed,
    and the label itself is never blocking. A build in which identity became a
    gate fails here rather than in a live session.
    """

    before = gate_decision(kind, verdict)
    label = speaker_label(kind, verdict, enrolled=enrolled)
    after = gate_decision(kind, verdict)

    assert before.as_dict() == after.as_dict()
    assert label.blocking is False
    assert label.as_dict()["blocking"] is False
    assert label.label in SPEAKER_LABELS


@pytest.mark.parametrize("verdict", _VERDICTS)
@pytest.mark.parametrize("enrolled", [True, False])
def test_no_state_of_the_gate_can_make_the_emergency_class_blocking(
    verdict: VoiceVerdict | None, enrolled: bool
) -> None:
    """The asymmetry, from the LABEL side. A stranger still stops the dog."""

    decision = gate_decision(KIND_EMERGENCY, verdict)
    label = speaker_label(KIND_EMERGENCY, verdict, enrolled=enrolled)

    assert decision.armed is True
    assert decision.code == CODE_SAFETY_NEVER_GATED
    assert label.label == LABEL_UNGATED
    assert label.gated is False


def test_a_blocking_label_is_a_refusal_to_construct() -> None:
    """``blocking`` is on the record so an artifact can answer the question —
    and it is not a knob, which is why setting it is a construction error."""

    with pytest.raises(VoiceIdentityError):
        SpeakerLabel(
            label=LABEL_OWNER, code=CODE_ARMED, gated=True, enrolled=True, blocking=True
        )


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (CODE_ARMED, LABEL_OWNER),
        (CODE_NOT_OWNER, LABEL_NOT_OWNER),
        (CODE_TOO_SHORT, LABEL_UNVERIFIED),
        (CODE_PENDING, LABEL_UNVERIFIED),
        (CODE_VERIFY_ERROR, LABEL_UNVERIFIED),
        (CODE_DISABLED, LABEL_UNENROLLED),
    ],
)
def test_every_verdict_code_has_exactly_one_label(code: str, expected: str) -> None:
    verdict = VoiceVerdict(code=code, passed=code == CODE_ARMED, score=0.9)
    assert speaker_label(KIND_NONE, verdict, enrolled=True).label == expected


def test_an_unenrolled_build_labels_every_row_and_arms_everything() -> None:
    """Before ``tools/enroll_owner_voice.py`` is run, and after. Both correct."""

    gate = _unenrolled_gate()
    for kind in (KIND_EMERGENCY, KIND_NONE, "tool"):
        decision = gate.decide(kind)
        label = gate.label(kind)
        assert decision.armed is True, f"{kind} must still arm with no profile"
        assert label.enrolled is False
        expected = LABEL_UNGATED if kind == KIND_EMERGENCY else LABEL_UNENROLLED
        assert label.label == expected


def test_unenrolled_and_unverified_are_not_the_same_fact() -> None:
    """"the check ran and abstained" vs "there is no check". One label each."""

    pending = VoiceVerdict(code=CODE_PENDING, passed=False)
    assert speaker_label(KIND_NONE, pending, enrolled=True).label == LABEL_UNVERIFIED
    assert speaker_label(KIND_NONE, pending, enrolled=False).label == LABEL_UNENROLLED
    assert unenrolled_label(KIND_NONE).label == LABEL_UNENROLLED


def test_a_gate_that_explodes_still_produces_a_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """Totality. A row with no label is what this card exists to remove."""

    gate = _enrolled_gate()

    def _boom(wall: float | None = None) -> VoiceVerdict:
        raise RuntimeError("verdict exploded")

    monkeypatch.setattr(gate, "current", _boom)
    label = gate.label(KIND_NONE)
    assert label.label in SPEAKER_LABELS
    assert label.blocking is False


# ================== 2. zero whispers about the unenrolled gate (row 4)
def test_an_unenrolled_gate_never_buys_a_spoken_sentence() -> None:
    """PRE-REGISTERED ROW 4. The gate is silent about itself.

    With no profile the gate cannot refuse anything, so this is defence in
    depth — and it is the structural form of the row: there is no path from an
    unenrolled gate to a narration, and it does not depend on every caller
    remembering to check. The COUNT still moves, because a refusal that happened
    is a refusal that happened.
    """

    gate = _unenrolled_gate()
    spoke = [gate.note_rejection() for _ in range(5)]
    assert spoke == [False] * 5
    assert gate.voice_rejected == 5
    assert gate.narrations == 0


def test_an_enrolled_gate_still_speaks_the_first_refusal_of_each_minute() -> None:
    """The other direction: the silence above is about the UNENROLLED case only."""

    clock = _Clock()
    gate = _enrolled_gate(clock=clock)
    assert gate.note_rejection() is True
    assert gate.note_rejection() is False


def test_no_identity_whisper_reaches_the_whisperer_with_no_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The measurement behind row 4, on the product path.

    Mixed traffic through a runtime whose identity gate has no profile; the
    whisperer's own decision log is then read for any identity class at all.
    """

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        runtime.realtime_voice_identity = _unenrolled_gate()
        for text in ("stop", "how are you", SAD, "follow me", "sit down"):
            runtime.submit_realtime_transcript(text)
        rows = runtime.realtime_whisperer.decision_rows()
        identity_rows = [row for row in rows if "voice_rejected" in str(row["kind"])]
        assert identity_rows == [], identity_rows
    finally:
        runtime.close()


# ============================ 3. a verdict on every ledger row (row 3)
def test_every_ledger_row_carries_an_identity_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRE-REGISTERED ROW 3: 100 % of rows, as a RATIO and not a boolean."""

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        for text in ("hello there", SAD, "stop", "follow me"):
            runtime.submit_realtime_transcript(text)
        coverage = runtime.identity_label_coverage()
        assert coverage["rows_written"] > 0
        assert coverage["rows_labelled"] == coverage["rows_written"]
        assert coverage["coverage"] == 1.0
        assert coverage["blocking"] is False

        rows = runtime.speaker_label_rows()
        assert len(rows) == coverage["rows_written"]
        assert all(str(row["label"]) in SPEAKER_LABELS for row in rows)
        assert all(row["blocking"] is False for row in rows)
    finally:
        runtime.close()


def test_the_emergency_row_is_labelled_ungated_and_not_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The most important row in the record: proof the latch ran unchecked."""

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        runtime.submit_realtime_transcript("stop")
        rows = [row for row in runtime.speaker_label_rows() if row["speaker"] == "owner"]
        assert rows, "the owner's own words are always written down"
        assert rows[-1]["label"] == LABEL_UNGATED
        assert rows[-1]["gated"] is False
    finally:
        runtime.close()


def test_the_label_is_never_spliced_into_the_owners_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transcript is what was said. The verdict rides the RECORD, not the row.

    The memory tail replays these words to the model verbatim on every
    reconnect; a verdict spliced into them would be the product editing the
    owner. The one exception is the affect row, which is the product's own
    sentence to begin with.
    """

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        runtime.submit_realtime_transcript("please come here")
        owner_rows = [
            str(row["content"])
            for row in runtime.agent.memory.realtime_turns(limit=20)
            if str(row["speaker"]) == "owner"
        ]
        assert owner_rows == ["please come here"]
    finally:
        runtime.close()


# ============================== 4. affect on the hosted lane (row 2)
def test_i_am_sad_yields_one_row_and_one_gesture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRE-REGISTERED ROW 2, and THE SEED: affect-on-legacy-only.

    One turn in. One affect row and exactly one gesture proposal out — and the
    row carries the speaker's identity label, which is the join between this
    card's two halves.
    """

    runtime = _runtime(tmp_path, monkeypatch)
    proposals: list[ActionProposal] = []
    try:
        original = runtime.propose_action

        def _spy(proposal: ActionProposal) -> str:
            proposals.append(proposal)
            return original(proposal)

        monkeypatch.setattr(runtime, "propose_action", _spy)

        runtime.submit_realtime_transcript(SAD, session_id="rt_p2b")

        rows = [
            str(row["content"])
            for row in runtime.agent.memory.realtime_turns(limit=20)
            if str(row["content"]).startswith("[affect ")
        ]
        assert len(rows) == 1, rows
        assert rows[0].startswith("[affect sad]")
        assert "speaker=" in rows[0]
        assert len(proposals) == 1
        assert (proposals[0].kind, proposals[0].trigger) == ("skill", "inferred_affect")
    finally:
        runtime.close()


def test_the_affect_history_is_a_public_api_p2a_can_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deliverable 2's last clause: plain dicts, copied out, no runtime inside."""

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        runtime.submit_realtime_transcript(SAD, session_id="rt_p2b")
        history = runtime.affect_history()
        assert len(history) == 1
        row = history[0]
        assert row["label"] == "sad"
        assert row["lane"] == "hosted"
        assert row["speaker"] in SPEAKER_LABELS
        assert row["confidence"] >= 0.5
        # It is a COPY: mutating what a distiller was handed cannot reach us.
        row["label"] = "tampered"
        assert runtime.affect_history()[0]["label"] == "sad"
        # And it is JSON, because a distiller in another process is the point.
        json.dumps(history)
    finally:
        runtime.close()


def test_an_unenrolled_speaker_still_gets_the_comfort_gesture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identity says WHO, never WHETHER. The absolute, on the affect path."""

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        runtime.realtime_voice_identity = _unenrolled_gate()
        runtime.submit_realtime_transcript(SAD)
        history = runtime.affect_history()
        assert len(history) == 1
        assert history[0]["speaker"] == LABEL_UNENROLLED
        assert history[0]["action"], "a gesture was still offered"
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("text", "minimum", "verdict"),
    [
        (SAD, 0.5, AFFECT_VERDICT_ADMITTED),
        (SAD, 1.5, AFFECT_VERDICT_BELOW_CONFIDENCE),
        ("take me to the park", 0.5, AFFECT_VERDICT_NONE),
    ],
)
def test_the_lane_entry_has_one_verdict_vocabulary(
    text: str, minimum: float, verdict: str
) -> None:
    """One bar, one grammar, one set of words for the answer — for every lane."""

    reading = affect_for_lane(text, minimum_confidence=minimum)
    assert reading.verdict == verdict
    assert reading.admitted is (verdict == AFFECT_VERDICT_ADMITTED)
    assert reading.minimum_confidence == minimum
    # The evidence-side entry agrees with the text-side entry, by construction.
    assert (
        lane_affect_from_evidence(reading.evidence, minimum_confidence=minimum).verdict
        == verdict
    )


# ====================== 5. the owner-event bands (deliverable 3, rows 1 & 5)
def _watcher(**overrides: object) -> tuple[OwnerEventWatcher, _Clock]:
    clock = _Clock()
    settings: dict[str, object] = {
        "enabled": True,
        "appear_debounce_s": 2.0,
        "absence_s": 60.0,
        "long_absence_h": 3.0,
        "greeting_interval_s": 300.0,
    }
    settings.update(overrides)
    config = OwnerEventsConfig(**settings)  # type: ignore[arg-type]
    return OwnerEventWatcher(config=config, clock=clock, day_key=lambda: "2026-08-22"), clock


def _walk(
    watcher: OwnerEventWatcher,
    clock: _Clock,
    *,
    present: bool,
    seconds: float,
    step: float = 1.0,
    confidence: float = 1.0,
) -> list[tuple[float, StateEvent]]:
    seen: list[tuple[float, StateEvent]] = []
    elapsed = 0.0
    while elapsed < seconds:
        for event in watcher.observe(
            OwnerPresence(present=present, at_s=clock.now, confidence=confidence)
        ):
            seen.append((clock.now, event))
        clock.advance(step)
        elapsed += step
    return seen


def test_greet_on_appearance_fires_once_per_appearance_within_five_seconds() -> None:
    """PRE-REGISTERED ROW 1, on a scripted track and a frozen clock."""

    watcher, clock = _watcher()
    _walk(watcher, clock, present=False, seconds=10.0)

    arrived_at = clock.now
    seen = _walk(watcher, clock, present=True, seconds=30.0)

    greetings = [row for row in seen if row[1].kind in (KIND_OWNER_APPEARED, KIND_OWNER_RETURNED)]
    assert len(greetings) == 1, [row[1].kind for row in seen]
    latency = greetings[0][0] - arrived_at
    assert latency <= 5.0, f"greeted {latency}s after the owner appeared"


def test_a_second_visit_is_a_second_greeting() -> None:
    """Once per appearance, not once per session: the dog greets you again."""

    watcher, clock = _watcher()
    _walk(watcher, clock, present=False, seconds=5.0)
    first = _walk(watcher, clock, present=True, seconds=10.0)
    _walk(watcher, clock, present=False, seconds=120.0)
    second = _walk(watcher, clock, present=True, seconds=10.0)

    assert [row[1].kind for row in first].count(KIND_OWNER_APPEARED) == 1
    assert [row[1].kind for row in second].count(KIND_OWNER_APPEARED) == 1


def test_a_blink_of_the_tracker_does_not_buy_a_second_hello() -> None:
    """``absence_s``: the anti-flicker rule, and the one that reads like a dog."""

    watcher, clock = _watcher()
    _walk(watcher, clock, present=False, seconds=5.0)
    _walk(watcher, clock, present=True, seconds=10.0)
    _walk(watcher, clock, present=False, seconds=3.0)  # a chair, a dropped frame
    after = _walk(watcher, clock, present=True, seconds=20.0)

    assert [row[1].kind for row in after].count(KIND_OWNER_APPEARED) == 0


def test_a_long_absence_is_a_return_and_says_so_once() -> None:
    """The card's ``owner_returned_after_Nh``: same edge, different sentence."""

    watcher, clock = _watcher()
    _walk(watcher, clock, present=False, seconds=5.0)
    _walk(watcher, clock, present=True, seconds=10.0)
    # The owner LEAVES, and only then does the afternoon pass.
    watcher.observe(OwnerPresence(present=False, at_s=clock.now))
    clock.advance(4.0 * 3600.0)
    seen = _walk(watcher, clock, present=True, seconds=20.0)

    kinds = [row[1].kind for row in seen]
    assert kinds.count(KIND_OWNER_RETURNED) == 1
    assert KIND_OWNER_APPEARED not in kinds, "a return supersedes an arrival; never both"
    returned = next(row[1] for row in seen if row[1].kind == KIND_OWNER_RETURNED)
    assert "hours" in returned.fact
    assert returned.key.endswith("h")


def test_a_low_confidence_sighting_is_not_the_owner() -> None:
    """P1-C's measured similarity, consumed. A 0.2 stranger is not greeted."""

    watcher, clock = _watcher(min_confidence=0.6)
    _walk(watcher, clock, present=False, seconds=5.0)
    seen = _walk(watcher, clock, present=True, seconds=20.0, confidence=0.2)
    assert seen == []


def test_the_question_of_the_day_is_asked_once_a_day() -> None:
    day = ["2026-08-22"]
    clock = _Clock()
    watcher = OwnerEventWatcher(
        config=OwnerEventsConfig(enabled=True, appear_debounce_s=1.0, greeting_interval_s=0.0),
        clock=clock,
        day_key=lambda: day[0],
    )
    seen = _walk(watcher, clock, present=True, seconds=30.0)
    assert [row[1].kind for row in seen].count(KIND_QUESTION_OF_THE_DAY) == 1

    day[0] = "2026-08-23"
    tomorrow = _walk(watcher, clock, present=True, seconds=30.0)
    assert [row[1].kind for row in tomorrow].count(KIND_QUESTION_OF_THE_DAY) == 1


def test_a_greeting_is_due_after_silence_and_a_turn_resets_it() -> None:
    watcher, clock = _watcher(greeting_interval_s=100.0, question_of_the_day=False)
    _walk(watcher, clock, present=False, seconds=5.0)
    _walk(watcher, clock, present=True, seconds=10.0)  # the arrival greeting

    quiet = _walk(watcher, clock, present=True, seconds=200.0, step=10.0)
    assert [row[1].kind for row in quiet].count(KIND_GREETING_DUE) == 1

    # A conversation is company: the timer restarts from the last thing said.
    watcher.note_turn(clock.now)
    talking = _walk(watcher, clock, present=True, seconds=50.0, step=10.0)
    assert [row[1].kind for row in talking].count(KIND_GREETING_DUE) == 0


def test_one_observe_call_can_never_produce_two_sentences() -> None:
    """Rule 1 of the watcher, enforced as a return type and not as a policy."""

    watcher, clock = _watcher(greeting_interval_s=1.0, appear_debounce_s=0.5)
    _walk(watcher, clock, present=False, seconds=5.0)
    for _ in range(200):
        assert len(watcher.observe(OwnerPresence(present=True, at_s=clock.now))) <= 1
        clock.advance(0.5)


def test_owner_events_disabled_produces_nothing_at_all() -> None:
    """Not suppressed. Not deduped. Never produced — the shipped default."""

    clock = _Clock()
    watcher = OwnerEventWatcher(config=OwnerEventsConfig(), clock=clock)
    seen = _walk(watcher, clock, present=True, seconds=60.0)
    assert seen == []
    assert watcher.config.enabled is False


# =============================== 6. the storm bound (row 5, and the seed)
def test_no_owner_event_is_critical() -> None:
    """THE SEED: greeting storms. No greeting may spend past the owner's ceiling."""

    assert OWNER_EVENT_KINDS
    assert OWNER_EVENT_KINDS <= ALWAYS_BAND
    assert not (OWNER_EVENT_KINDS & CRITICAL_KINDS)
    for kind in OWNER_EVENT_KINDS:
        assert band_of(kind) == "always"


@pytest.mark.parametrize(
    ("cap", "window"),
    [(2, 60.0), (2, 30.0), (6, 60.0)],
)
def test_a_flapping_track_can_never_spend_past_the_owners_cap(
    cap: int, window: float
) -> None:
    """PRE-REGISTERED ROW 5, measured against the CONFIGURED cap.

    An owner track flapping every two seconds for ten minutes — the worst input
    the watcher can be given — offered through the real whisperer. The bound is
    the owner's own knob, and the prototype block (2 per 30 s = 4/min) is
    stricter than the card's 6/min ceiling.
    """

    clock = _Clock()
    whisperer = Whisperer(
        config=WhispererConfig(max_updates_per_minute=cap, min_gap_s=0.0, window_s=window),
        clock=clock,
    )
    watcher = OwnerEventWatcher(
        config=OwnerEventsConfig(
            enabled=True,
            appear_debounce_s=0.5,
            absence_s=1.0,
            greeting_interval_s=1.0,
        ),
        clock=clock,
        day_key=lambda: "2026-08-22",
    )

    forwarded_at: list[float] = []
    present = True
    for tick in range(600):
        if tick % 2 == 0:
            present = not present
        for event in watcher.observe(OwnerPresence(present=present, at_s=clock.now)):
            if whisperer.offer(event, now=clock.now).forwarded:
                forwarded_at.append(clock.now)
        clock.advance(1.0)

    assert forwarded_at, "the storm must actually have produced traffic"
    for start in forwarded_at:
        inside = [at for at in forwarded_at if start <= at < start + window]
        assert len(inside) <= cap, f"{len(inside)} forwards inside {window}s (cap {cap})"
    per_minute = max(
        len([at for at in forwarded_at if start <= at < start + 60.0]) for start in forwarded_at
    )
    assert per_minute <= 6, f"{per_minute}/min exceeds the card's prototype ceiling"


def test_an_owner_event_obeys_the_min_gap_like_every_other_fact() -> None:
    """It rides the existing machinery; it does not get its own."""

    clock = _Clock()
    whisperer = Whisperer(
        config=WhispererConfig(max_updates_per_minute=10, min_gap_s=15.0, window_s=60.0),
        clock=clock,
    )
    assert whisperer.offer(
        StateEvent(kind=KIND_BATTERY_STATE, key="b1", fact="battery note"), now=clock.now
    ).forwarded
    clock.advance(2.0)
    decision = whisperer.offer(
        StateEvent(kind=KIND_OWNER_APPEARED, key="owner_appeared:1", fact="you came in"),
        now=clock.now,
    )
    assert not decision.forwarded
    assert decision.rule == "min_gap"


# =========================================== 7. the runtime wiring (deliverable 3)
def test_the_runtime_offers_owner_events_through_the_one_whisper_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no second path to the model, and this is what proves it."""

    backend = _Backend()
    runtime = _runtime(
        tmp_path,
        monkeypatch,
        backend=backend,
        owner_events=(
            "whisperer:\n"
            "  owner_events:\n"
            "    enabled: true\n"
            "    appear_debounce_s: 1.0\n"
            "    absence_s: 5.0\n"
        ),
    )
    try:
        assert runtime.realtime_owner_events.config.enabled is True
        whispered: list[StateEvent] = []
        monkeypatch.setattr(
            runtime, "_whisper", lambda event: whispered.append(event) or False
        )

        now = 1_000.0
        backend.owner_visible = False
        for _ in range(3):
            runtime._step_owner_events(backend.observe(), now)
            now += 1.0
        backend.owner_visible = True
        for _ in range(10):
            observation = backend.observe()
            observation = SimObservation(
                timestamp=now,
                robot=observation.robot,
                owner=observation.owner,
                nearest_obstacle_m=10.0,
                backend=BACKEND_NAME,
            )
            runtime._step_owner_events(observation, now)
            now += 1.0

        kinds = [event.kind for event in whispered]
        assert kinds.count(KIND_OWNER_APPEARED) == 1, kinds
    finally:
        runtime.close()


def test_the_owner_tick_rides_the_whisperers_own_beat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One 1 Hz beat for both watchers: the greeting cadence and the state
    cadence must not be able to drift apart."""

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        ticks: list[float] = []
        monkeypatch.setattr(
            runtime,
            "_step_owner_events",
            lambda observation, now: ticks.append(now) or (),
        )
        runtime._step_whisperer(None, 5_000.0)
        runtime._step_whisperer(None, 5_000.4)  # inside the throttle
        runtime._step_whisperer(None, 5_002.0)
        assert ticks == [5_000.0, 5_002.0]
    finally:
        runtime.close()


def test_a_failing_owner_tick_can_never_stop_the_control_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A greeting is a nicety. The loop that keeps the robot upright is not."""

    runtime = _runtime(
        tmp_path,
        monkeypatch,
        owner_events="whisperer:\n  owner_events:\n    enabled: true\n",
    )
    try:

        def _boom(sample: object) -> tuple[StateEvent, ...]:
            raise RuntimeError("watcher exploded")

        monkeypatch.setattr(runtime.realtime_owner_events, "observe", _boom)
        assert runtime._step_owner_events(None, 1_000.0) == ()
    finally:
        runtime.close()


def test_a_stale_observation_is_not_a_sighting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The confidence-1.0 defect (audit §1) must not reappear as a greeting."""

    backend = _Backend()
    runtime = _runtime(tmp_path, monkeypatch, backend=backend)
    try:
        backend.owner_visible = True
        stale = SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(visible=True, confidence=1.0),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )
        sample = runtime.owner_presence_sample(stale, 10_000.0)
        assert sample.present is False
        assert runtime.owner_presence_sample(None, 10_000.0).present is False
    finally:
        runtime.close()


def test_the_panel_publishes_the_watcher_and_the_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A knob nobody can see is a knob nobody can turn down."""

    runtime = _runtime(tmp_path, monkeypatch)
    try:
        snapshot = runtime.realtime_snapshot()
        # Flag-off (no lane): the owner-event CONFIG is visible through the
        # config blob — "when may the robot greet me" is a fact about the file.
        # The per-session counters are not, because there is no session.
        assert snapshot["config"]["whisperer"]["owner_events"]["enabled"] is False
        assert "identity_labels" not in snapshot

        # The watcher and the coverage are readable directly either way, which
        # is what P2-A's distiller and the verifier actually consume.
        assert runtime.realtime_owner_events.snapshot()["config"]["enabled"] is False
        assert runtime.identity_label_coverage()["blocking"] is False
    finally:
        runtime.close()


# ============================================= 8. the config surface
def test_the_owner_event_keys_are_validated_and_default_off() -> None:
    assert "owner_events" in WHISPERER_ALLOWED_KEYS
    default = whisperer_config_from_mapping(None).owner_events
    assert default.enabled is False
    assert default.as_dict().keys() == OWNER_EVENTS_ALLOWED_KEYS


@pytest.mark.parametrize(
    "block",
    [
        {"enabld": True},
        {"enabled": "yes"},
        {"min_confidence": 1.5},
        {"appear_debounce_s": 0},
        {"absence_s": -1},
        {"long_absence_h": float("inf")},
        {"question_of_the_day": 1},
    ],
)
def test_a_typo_in_the_owner_event_block_is_a_refusal(block: dict[str, object]) -> None:
    """A companion greeting you on a schedule nobody wrote down is worse than one
    that refuses to boot."""

    with pytest.raises(RealtimeConfigError):
        whisperer_config_from_mapping({"owner_events": block})


def test_a_config_written_before_this_card_is_unchanged_by_it() -> None:
    """The P0-B discipline: absent key ⇒ the pre-card value, everywhere."""

    before = realtime_config_from_mapping(
        {"enabled": True, "whisperer": {"max_updates_per_minute": 3}}
    )
    assert before.whisperer.max_updates_per_minute == 3
    assert before.whisperer.owner_events.enabled is False
    assert before.whisperer.owner_events == OwnerEventsConfig()


def test_the_prototype_overlay_is_where_the_greeting_is_turned_on() -> None:
    """Prototype-only keys go in the overlay; the shipped file keeps its cost."""

    import yaml

    from parcel_robot.realtime.config import realtime_config_from_mapping as _load

    shipped = _load(
        yaml.safe_load((REPO / "configs" / "realtime.yaml.example").read_text("utf-8"))
    )
    prototype = _load(
        yaml.safe_load(
            (REPO / "configs" / "realtime.prototype.yaml.example").read_text("utf-8")
        )
    )
    assert shipped.whisperer.owner_events.enabled is False
    assert prototype.whisperer.owner_events.enabled is True
    # The card's stated prototype ceiling, read from the file rather than
    # asserted from the card: six spoken lines a minute, cap included.
    assert prototype.whisperer.max_updates_per_minute == 6
    assert prototype.whisperer.window_s == 60.0


def test_the_example_config_documents_the_owner_event_keys() -> None:
    text = (REPO / "configs" / "realtime.yaml.example").read_text(encoding="utf-8")
    assert "owner_events:" in text
    for key in OWNER_EVENTS_ALLOWED_KEYS:
        assert f"{key}:" in text, key


# ================================================ 9. the voice-tier A/B package
def test_the_tier_experiment_is_a_script_and_a_probe_list_and_not_a_session() -> None:
    """Deliverable 4. The owner runs the session; the tool cannot start one."""

    from tools import voice_tier_ab

    ids = [probe.probe_id for probe in voice_tier_ab.PROBES]
    assert len(ids) == len(set(ids)) >= 10
    assert set(voice_tier_ab.TIER_MODELS) == {"mini", "full"}
    source = (REPO / "tools" / "voice_tier_ab.py").read_text(encoding="utf-8")
    for forbidden in ("openai", "websocket", "RealtimeLane", "api_key", "Authorization"):
        assert forbidden not in source, f"the A/B script must not reach a provider: {forbidden}"


def test_the_tier_experiment_refuses_the_owners_own_port(tmp_path: Path) -> None:
    from tools import voice_tier_ab

    with pytest.raises(SystemExit):
        voice_tier_ab._capture("mini", voice_tier_ab.OWNER_PORT, tmp_path)


def test_the_plan_writes_the_probe_list_and_the_scoresheet(tmp_path: Path) -> None:
    from tools import voice_tier_ab

    voice_tier_ab.main(["--plan", "--out", str(tmp_path)])
    assert (tmp_path / "probes.tsv").exists()
    assert (tmp_path / "scoresheet.md").exists()
    rows = (tmp_path / "probes.tsv").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == len(voice_tier_ab.PROBES) + 1
