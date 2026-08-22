"""Card R2-C: the SI + DI prompt plane.

WHAT THESE TESTS ARE DEFENDING
------------------------------
Three properties, each of which is worthless unless a test would notice it
breaking:

1. **SI changes are visible.** The system instruction is assembled from three
   files — ``realtime/prompting.py``, a personality YAML, and ``lane.GUARDRAILS``
   — so an edit to any of them silently changes what a hosted model was told.
   The digest is pinned per ``si_version``. Editing the text without bumping the
   version reddens ``test_the_si_digest_is_pinned_per_personality``; bumping the
   version without registering digests reddens ``si_pin`` outright.
2. **DI is deterministic.** ``render_developer_instruction`` is a pure function
   of a snapshot. Nothing reads a clock, an environment variable or the disk. A
   pinned digest built from a FIXED injected instant is the catcher: swap the
   injected clock for ``datetime.now()`` and the pin moves the same day.
3. **DI enters at session boundaries only.** The lane re-sends
   ``self.instructions`` on open, rollover and reconnect. It does not re-derive
   them, so ``InstructionSource.refresh`` is the mechanism, and the rollover
   test proves the second session really does carry the newer note while a
   mid-session change alone sends nothing at all.

Time and prompts are injected. No network, no credential, no sleeps.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.prompting import PromptLibrary
from parcel_robot.realtime import lane as lane_module
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV, RealtimeConfig
from parcel_robot.realtime.fake_server import FakeRealtimeServer, Step, handshake, pcm_tone
from parcel_robot.realtime.lane import RealtimeLane
from parcel_robot.realtime.prompting import (
    ABILITY_WORDING,
    COMPANION_CONTRACT,
    COMPANION_PREAMBLE,
    DI_VERSION,
    MAX_HISTORY_LINES,
    MAX_OWNER_NOTES,
    SI_DIGESTS,
    SI_V1,
    SI_V2,
    SI_V3,
    SI_VERSION,
    SUPERSEDED_ABILITY_RULE,
    SUPERSEDED_ACK_RULE,
    TOOL_TURN_CADENCE,
    UNKNOWN_LOCATION,
    UNKNOWN_OWNER,
    DeveloperContext,
    DeveloperFlags,
    InstructionSource,
    PromptPlaneError,
    default_prompt_library,
    history_digest_from_turns,
    render_developer_instruction,
    render_session_instructions,
    render_system_instruction,
    si_guardrails,
    si_pin,
    time_of_day,
)
from parcel_robot.realtime.transport import transport_pair
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r2c-prompting"

PERSONALITIES = ("calm_guardian", "gentle_companion", "playful_companion")

#: The canonical DI snapshot. Built from a FIXED instant, which is the whole
#: point: this digest is stable in 2026 and in 2036, and stops being stable the
#: moment the renderer reads a clock of its own.
PINNED_CLOCK = datetime.fromisoformat("2026-08-17 19:05")
PINNED_DI_DIGEST = "1144cad421e9186598a32c7235744aad0c6a17fee2515440525543317c5687d7"
#: Moved by the SI v2 bump (card R5). The DI half is unchanged — that is the
#: point of pinning both: an SI edit must move exactly one of these two.
PINNED_SESSION_DIGEST = "997aab7309174f7863deb75442d72936abffe4877e9f3b2371a204fe28fa07c0"


@pytest.fixture(scope="module")
def library() -> PromptLibrary:
    return PromptLibrary(REPO / "prompts")


def pinned_context() -> DeveloperContext:
    """The context behind :data:`PINNED_DI_DIGEST`. Every source injected."""

    return DeveloperContext(
        clock=lambda: PINNED_CLOCK,
        location=lambda: "sidewalk near home",
        owner_name="Jae",
        owner_notes=lambda: ["walks the robot after dinner"],
        history=lambda: [
            "they said: that was a horrible day",
            "you said: I'm here. We can just sit.",
        ],
    )


# =========================================================== SI: the pinning
@pytest.mark.parametrize("profile_id", PERSONALITIES)
def test_the_si_digest_is_pinned_per_personality(profile_id: str, library: PromptLibrary) -> None:
    """THE seed catcher: any SI text edit without an ``SI_VERSION`` bump.

    The SI is not one file. Bump ``COMPANION_PREAMBLE``, reword
    ``lane.GUARDRAILS``, or add a ``reply_style`` line to a personality YAML and
    this reddens — which is exactly the point of calling the SI "periodic".
    """

    rendered = render_system_instruction(profile_id=profile_id, library=library)
    assert rendered.version == SI_VERSION
    assert rendered.profile_id == profile_id
    assert rendered.digest == si_pin(profile_id), (
        f"the rendered SI for {profile_id} no longer matches its pin. If the change "
        f"was intended: bump SI_VERSION and register the new digests in SI_DIGESTS."
    )


def test_every_personality_in_the_repo_is_pinned(library: PromptLibrary) -> None:
    """A NEW personality YAML must be pinned too, not silently unpinned."""

    on_disk = {profile.id for profile in library.list_personalities()}
    assert on_disk == set(SI_DIGESTS[SI_VERSION]), (
        "prompts/personalities and SI_DIGESTS have diverged; a personality "
        "without a pinned SI digest can drift under a green gate"
    )
    assert on_disk == set(PERSONALITIES)


def test_bumping_the_version_without_registering_digests_refuses() -> None:
    """Half a change is a refusal. The bump and the pin land together."""

    with pytest.raises(PromptPlaneError) as caught:
        si_pin("gentle_companion", version="si-companion-v99")
    assert "SI_DIGESTS" in str(caught.value)

    with pytest.raises(PromptPlaneError):
        si_pin("no_such_personality")


def test_the_si_carries_the_companion_framing_and_the_lane_guardrails(
    library: PromptLibrary,
) -> None:
    """The companion rules are the LANE's, imported rather than restated.

    Card R5 supersedes exactly two of the lane's sentences (see
    :func:`si_guardrails`); every OTHER rule is still the lane's single copy,
    asserted here sentence by sentence rather than by whole-block identity.
    """

    rendered = render_system_instruction(profile_id="gentle_companion", library=library)
    assert COMPANION_PREAMBLE in rendered.text
    assert COMPANION_CONTRACT in rendered.text
    assert si_guardrails() in rendered.text
    # The persona and its reply style, from the YAML rather than from here.
    personality = library.personality("gentle_companion")
    assert personality.instruction in rendered.text
    for rule in personality.reply_style:
        assert f"- {rule}" in rendered.text
    # The lane's UNSUPERSEDED sentences, taken from lane.GUARDRAILS itself so a
    # reword there is still caught rather than duplicated into this file.
    for sentence in lane_module.GUARDRAILS.split(". "):
        if not sentence.strip():
            continue
        if sentence + ". " in (SUPERSEDED_ACK_RULE, SUPERSEDED_ABILITY_RULE):
            continue
        if sentence in SUPERSEDED_ACK_RULE or sentence in SUPERSEDED_ABILITY_RULE:
            continue
        assert sentence in rendered.text, (
            f"the lane's guardrail sentence {sentence!r} is not in the shipped SI; "
            f"only the two superseded rules may be missing"
        )
    # And the rules the card names, as substrings of the shipped text.
    for phrase in (
        "short spoken sentences",
        # Case-free: v1 had this mid-sentence, v2 starts a sentence with it.
        "claim to have arrived anywhere or completed a physical action",
        "mention tools, sessions, or transcripts",
    ):
        assert phrase in rendered.text


# ============================================================ SI v2 (card R5)
def test_the_shipped_si_states_the_tool_turn_cadence_once_rule(
    library: PromptLibrary,
) -> None:
    """THE seed catcher for "the cadence rule dropped from the SI".

    The owner's 20:45 defect was two acknowledgment beats for one navigation
    turn — "Got it, I'll head toward that sidewalk" and, a second later, "Okay,
    let's walk over there together…". The v1 rule ("Acknowledge a request before
    anything happens") is what asked for the first beat while nothing suppressed
    the second, so the v2 SI must carry the once-rule and must NOT carry the v1
    sentence.

    The rule must also NAME which beat survives. A prompt that offers a choice
    ("either before or after") was tried live and the model took both, because
    the lane's post-tool ``response.create`` makes the after-beat unconditional;
    only the pre-call beat is actually suppressible. So "do not announce it
    first" is asserted as text, not left to the model's discretion.
    """

    rendered = render_system_instruction(profile_id="gentle_companion", library=library)
    assert TOOL_TURN_CADENCE in rendered.text
    assert SUPERSEDED_ACK_RULE not in rendered.text, (
        "the v1 acknowledge-before-anything rule is the two-beat defect itself"
    )
    for phrase in (
        "do not speak first",
        "ONE short thing",
        # "one TURN, one line", not "one action": a turn that calls two tools
        # gets two lane-forced responses and would otherwise buy two beats.
        "One turn, one spoken line",
        "even when you used more than one system",
        "never a line before it and another after",
        # Concrete anti-examples, verbatim from the live runs. The abstract
        # rule alone did not stop the model opening with "let me…".
        "let me",
        "I'll",
        # The honest-difference channel: a result that DIFFERS must be narrated,
        # or "say it once" would silently become "never correct yourself".
        "say plainly what actually happened",
    ):
        assert phrase in rendered.text, phrase
    assert "either" not in TOOL_TURN_CADENCE, (
        "an either/or is not a constraint here: the lane forces the post-result "
        "beat, so a choice resolves to both. Name the beat that survives."
    )


def test_the_shipped_si_never_tells_the_robot_it_cannot_act(
    library: PromptLibrary,
) -> None:
    """THE seed catcher for "the ability wording regressed".

    AUDIT_R16_R3 §Carry-forwards 2: the model said "I can't physically move your
    way" in the same turn its gesture executed. The rule is "never claim an
    outcome the tools have not confirmed", never "you cannot act".
    """

    rendered = render_system_instruction(profile_id="gentle_companion", library=library)
    assert ABILITY_WORDING in rendered.text
    assert SUPERSEDED_ABILITY_RULE not in rendered.text
    assert "never say you cannot move, walk, turn, look, or gesture" in rendered.text
    # The half that must survive the rewrite: honesty about OUTCOMES.
    assert "claim an outcome those systems have not reported" in rendered.text


@pytest.mark.xfail(strict=True, reason="FZ-1 (scrum/20260822/task_13): the owner edited prompts/personalities on 2026-08-22; historical SI versions render from the LIVE persona files, so v1/v2 text is no longer reproducible from source until frozen per-version snapshots land. Digests stay registered so recorded sessions remain attributable. strict: flips to a failure the day FZ-1 restores it.")
def test_the_v1_si_still_renders_to_its_v1_pins(library: PromptLibrary) -> None:
    """The corpus's provenance chain stays REPRODUCIBLE, not grandfathered.

    The 25-thread corpus was captured under v1 and must not be re-scraped. From
    v2 on ``si_version`` selects the text, so this tree can still render the
    exact words those threads were captured under — which is what keeps every
    fixture's stored ``si_digest`` a checkable claim instead of a stale number.
    """

    for profile_id in PERSONALITIES:
        rendered = render_system_instruction(
            profile_id=profile_id, library=library, version=SI_V1
        )
        assert rendered.version == SI_V1
        assert rendered.digest == si_pin(profile_id, version=SI_V1), profile_id
        assert lane_module.GUARDRAILS in rendered.text, "v1 is the lane's text verbatim"
        assert SUPERSEDED_ACK_RULE in rendered.text, "v1 keeps the words it was captured with"


def test_v1_and_v2_are_different_text_under_different_pins(library: PromptLibrary) -> None:
    one = render_system_instruction(profile_id="gentle_companion", library=library, version=SI_V1)
    two = render_system_instruction(profile_id="gentle_companion", library=library, version=SI_V2)
    assert one.text != two.text
    assert one.digest != two.digest
    # v3 (2026-08-22) carries v2's fixed wording plus the owner's persona preludes;
    # the shipped default must never fall back to v1's superseded rules.
    assert SI_VERSION == SI_V3, "the shipped default is the fixed prompt, not the old one"
    assert SI_VERSION != SI_V1
    assert set(SI_DIGESTS) == {SI_V1, SI_V2, SI_V3}


def test_an_unregistered_si_version_refuses_at_render_not_only_at_pin() -> None:
    """A version with no text is a refusal. It used to be a silent relabel.

    Before v2 the ``version`` argument was a label beside whatever the tree
    rendered today, so ``version="si-companion-v99"`` produced real text under a
    fictional version. Now the version selects the words, so an unregistered one
    cannot render at all.
    """

    with pytest.raises(PromptPlaneError) as caught:
        si_guardrails("si-companion-v99")
    assert "si-companion-v99" in str(caught.value)
    with pytest.raises(PromptPlaneError):
        render_system_instruction(profile_id="gentle_companion", version="si-companion-v99")


def test_a_supersession_that_matches_nothing_refuses_rather_than_shipping_v1_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE fail-closed catcher for the supersession itself.

    ``str.replace`` with no match is a no-op: reword ``lane.GUARDRAILS`` and a
    naive v2 would ship the DEFECTIVE sentence under a v2 label, with a digest
    test that reddens for an unrelated-looking reason. This refuses by name.
    """

    monkeypatch.setattr(
        "parcel_robot.realtime.prompting.GUARDRAILS",
        "You are speaking aloud through a robot dog's speaker. Be brief.",
    )
    with pytest.raises(PromptPlaneError) as caught:
        si_guardrails(SI_V2)
    assert "tool-turn cadence" in str(caught.value)

    monkeypatch.setattr(
        "parcel_robot.realtime.prompting.GUARDRAILS",
        SUPERSEDED_ACK_RULE + "Be brief.",
    )
    with pytest.raises(PromptPlaneError) as caught:
        si_guardrails(SI_V2)
    assert "ability wording" in str(caught.value)


def test_two_personalities_produce_two_different_system_instructions(
    library: PromptLibrary,
) -> None:
    gentle = render_system_instruction(profile_id="gentle_companion", library=library)
    playful = render_system_instruction(profile_id="playful_companion", library=library)
    assert gentle.text != playful.text
    assert gentle.digest != playful.digest
    assert gentle.provenance()["si_version"] == playful.provenance()["si_version"]


# ==================================================== DI: the determinism pin
def test_the_di_render_is_pinned_for_a_fixed_injected_instant() -> None:
    """THE seed catcher for a renderer that grows its own clock.

    ``DeveloperContext`` takes the clock as a callable. Replace ``self._clock()``
    with ``datetime.now()`` and ``local_time`` becomes today, the text changes,
    and this digest stops matching within the same test run.
    """

    flags = pinned_context().flags()
    rendered = render_developer_instruction(flags)
    assert rendered.version == DI_VERSION
    assert rendered.digest == PINNED_DI_DIGEST, (
        "the DI no longer renders to its pin. If the LAYOUT changed on purpose, "
        "bump DI_VERSION and re-seal the fixtures; if it changed because the "
        "renderer read a clock of its own, that is the defect this test exists for."
    )
    assert "Location: sidewalk near home" in rendered.text
    assert "Local time: 2026-08-17 19:05 (evening)" in rendered.text


def test_the_same_flags_render_the_same_bytes_every_time() -> None:
    context = pinned_context()
    first = context.flags()
    second = context.flags()
    assert first == second
    assert render_developer_instruction(first).text == render_developer_instruction(second).text


def test_the_di_renderer_touches_no_clock_environment_or_disk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stated as an executable fact: break ``datetime.now`` and DI still renders.

    If the renderer ever grows an ambient time source, this raises rather than
    quietly producing different text.
    """

    flags = pinned_context().flags()

    class _Exploding(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
            raise AssertionError("the DI renderer must not read a wall clock")

    monkeypatch.setattr("parcel_robot.realtime.prompting.datetime", _Exploding)
    monkeypatch.delenv("TZ", raising=False)
    assert render_developer_instruction(flags).digest == PINNED_DI_DIGEST


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, "night"),
        (4, "night"),
        (5, "morning"),
        (11, "morning"),
        (12, "afternoon"),
        (16, "afternoon"),
        (17, "evening"),
        (20, "evening"),
        (21, "night"),
        (23, "night"),
    ],
)
def test_the_part_of_day_table_is_a_stated_table(hour: int, expected: str) -> None:
    assert time_of_day(datetime.fromisoformat(f"2026-08-17 {hour:02d}:30")) == expected


def test_a_location_provider_that_fails_reads_as_unknown_not_as_a_crash() -> None:
    """A location source is a sensor, and a sensor failure is a spoken 'I'm not sure'."""

    def _broken() -> str:
        raise RuntimeError("localization unavailable")

    context = DeveloperContext(clock=lambda: PINNED_CLOCK, location=_broken)
    flags = context.flags()
    assert flags.location == UNKNOWN_LOCATION
    assert flags.owner_name == UNKNOWN_OWNER
    assert "Location: unknown" in render_developer_instruction(flags).text


def test_a_clock_that_is_not_a_datetime_refuses_rather_than_renders() -> None:
    context = DeveloperContext(clock=lambda: "half past six")  # type: ignore[arg-type]
    with pytest.raises(PromptPlaneError):
        context.flags()


def test_the_history_and_owner_note_blocks_are_bounded() -> None:
    context = DeveloperContext(
        clock=lambda: PINNED_CLOCK,
        owner_notes=lambda: [f"note {n}" for n in range(20)],
        history=lambda: [f"they said: line {n}" for n in range(20)],
    )
    flags = context.flags()
    assert len(flags.owner_notes) == MAX_OWNER_NOTES
    assert len(flags.history_digest) == MAX_HISTORY_LINES


def test_the_ledger_tail_becomes_a_short_two_sided_digest() -> None:
    rows = [
        {"speaker": "owner", "content": "  that was  a horrible day "},
        {"speaker": "robot", "content": "I'm here."},
        {"speaker": "system", "content": "[session rollover] ignored"},
        {"speaker": "owner", "content": "x" * 400},
    ]
    digest = history_digest_from_turns(rows)
    assert digest[0] == "they said: that was a horrible day"
    assert digest[1] == "you said: I'm here."
    assert all(not line.startswith("system") for line in digest)
    assert digest[-1].endswith("…") and len(digest[-1]) <= 132
    assert len(history_digest_from_turns(rows, limit=1)) == 1


def test_developer_flags_refuse_an_unknown_key() -> None:
    with pytest.raises(PromptPlaneError) as caught:
        DeveloperFlags.from_mapping({"location": "kitchen", "mood": "sunny"})
    assert "mood" in str(caught.value)


def test_flags_round_trip_through_their_own_dict() -> None:
    flags = pinned_context().flags()
    assert DeveloperFlags.from_mapping(flags.as_dict()) == flags


# ================================================ SI + DI, one session's text
def test_the_session_text_is_si_then_di_and_carries_full_provenance(
    library: PromptLibrary,
) -> None:
    flags = pinned_context().flags()
    rendered = render_session_instructions(
        profile_id="gentle_companion", flags=flags, library=library
    )
    assert rendered.text.startswith(COMPANION_PREAMBLE)
    assert rendered.text.endswith(rendered.di.text)
    assert rendered.digest == PINNED_SESSION_DIGEST
    provenance = rendered.provenance()
    assert provenance["si_profile"] == "gentle_companion"
    assert provenance["si_version"] == SI_VERSION
    assert provenance["si_digest"] == si_pin("gentle_companion")
    assert provenance["di_version"] == DI_VERSION
    assert provenance["di_digest"] == PINNED_DI_DIGEST
    assert provenance["di_flags"]["location"] == "sidewalk near home"


# ============================================ DI enters at session boundaries
class _Clock:
    """Monotonic seconds a test advances by hand. No sleeps anywhere here."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _Sink:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.first_chunk_started_monotonic: float | None = None

    def begin_utterance(self) -> None:
        self.first_chunk_started_monotonic = None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del token
        self.chunks.append(chunk)

    def interrupt(self) -> None:
        return None


class _BoundaryRig:
    """A lane whose every reconnect gets a fresh scripted server."""

    def __init__(self, script: list[Step], *, session_max_s: float = 60.0) -> None:
        self.clock = _Clock()
        self.script = script
        self.servers: list[FakeRealtimeServer] = []
        self.lane = RealtimeLane(
            config=RealtimeConfig(enabled=True, session_max_s=session_max_s, source="test"),
            instructions="placeholder",
            transport_factory=self._factory,
            sink=_Sink(),
            clock=self.clock,
        )

    def _factory(self):
        lane_end, server_end = transport_pair(clock=self.clock)
        self.servers.append(
            FakeRealtimeServer(transport=server_end, script=list(self.script), clock=self.clock)
        )
        return lane_end

    def step(self) -> None:
        self.servers[-1].pump()
        self.lane.pump()

    def session_updates(self) -> list[str]:
        """Every ``instructions`` string this lane has ever put on a wire."""

        out: list[str] = []
        for server in self.servers:
            for frame in server.frames_of_type("session.update"):
                session = frame.get("session")
                if isinstance(session, dict):
                    out.append(str(session.get("instructions", "")))
        return out


def _source(library: PromptLibrary, location: list[str]) -> InstructionSource:
    return InstructionSource(
        profile_id="gentle_companion",
        context=DeveloperContext(
            clock=lambda: PINNED_CLOCK,
            location=lambda: location[0],
            owner_name="Jae",
        ),
        library=library,
    )


def test_a_rollover_carries_the_newer_developer_note(library: PromptLibrary) -> None:
    """The card's session-boundary rule, end to end against the real lane.

    The lane re-SENDS ``self.instructions`` inside ``_connect()``; it does not
    re-derive them. So a driver refreshes before each ``tick()``, and the
    rollover that ``tick()`` takes carries whatever the refresh just wrote.
    """

    location = ["living room"]
    source = _source(library, location)
    rig = _BoundaryRig(handshake(), session_max_s=60.0)
    source.refresh(rig.lane)
    rig.lane.open_session(handshake_token="csrf", mic_gesture=True)
    rig.step()
    assert rig.lane.rollovers == 0

    # The owner walks outside. The flag moves; nothing goes on the wire.
    before = len(rig.session_updates())
    assert before == 1, "the open sent exactly one session.update"
    location[0] = "front yard"
    rig.step()
    assert len(rig.session_updates()) == before, "a DI change alone must send nothing"

    # A driver refreshes, then ticks past the session cap.
    rig.clock.advance(61.0)
    assert source.refresh(rig.lane) is True
    assert rig.lane.tick() == "rollover"
    rig.step()

    updates = rig.session_updates()
    assert len(updates) == 2, "open + rollover, one session.update each"
    assert "Location: living room" in updates[0]
    assert "Location: front yard" in updates[1]
    assert rig.lane.rollovers == 1


def test_a_mid_session_di_change_is_not_an_instruction_rewrite(library: PromptLibrary) -> None:
    """Rewriting instructions mid-conversation busts the provider's prompt cache.

    So a mid-session refresh writes the ATTRIBUTE and sends nothing: the lane
    only puts instructions on the wire from ``_connect()``.
    """

    location = ["living room"]
    source = _source(library, location)
    rig = _BoundaryRig(handshake() + [Step("input_audio_buffer.append", (), label="quiet")])
    source.refresh(rig.lane)
    rig.lane.open_session(handshake_token="csrf", mic_gesture=True)
    rig.step()

    location[0] = "front yard"
    source.refresh(rig.lane)
    rig.lane.send_audio(pcm_tone(20))
    rig.step()

    assert len(rig.session_updates()) == 1, "no session.update may be sent mid-session"
    assert "Location: front yard" in rig.lane.instructions, "the NEXT boundary will carry it"


def test_refresh_reports_whether_the_text_actually_moved(library: PromptLibrary) -> None:
    location = ["living room"]
    source = _source(library, location)
    lane = RealtimeLane(config=RealtimeConfig(source="absent"), instructions="")
    assert source.refresh(lane) is True
    assert source.refresh(lane) is False, "an unchanged render must report unchanged"
    location[0] = "kitchen"
    assert source.refresh(lane) is True
    assert source.renders == 3


# ================================================== the runtime wiring, once
class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )

    def move(self, command: VelocityCommand) -> None:
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
        del transcript, tools, context
        return AgentDecision("Understood.")


def _runtime(tmp_path: Path) -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "r2c-prompting.yaml"
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
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r2c prompting fixture",
        ),
    )


def test_the_runtime_sources_lane_instructions_from_the_prompt_plane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag-on: the lane is told SI+DI, and the source is kept for refreshes."""

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        source = runtime.realtime_instructions
        lane = runtime.realtime_lane
        assert source is not None and lane is not None
        assert source.profile_id == "gentle_companion"
        assert lane.instructions.startswith(COMPANION_PREAMBLE)
        assert f"[developer note · {DI_VERSION}]" in lane.instructions
        # No place source exists in this runtime yet — stated, not invented.
        assert f"Location: {UNKNOWN_LOCATION}" in lane.instructions
        assert source.current().si.digest == si_pin("gentle_companion")
    finally:
        runtime.close()


def test_flag_off_leaves_the_prompt_plane_unconstructed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    runtime = _runtime(tmp_path)
    try:
        assert runtime.realtime_lane is None
        assert runtime.realtime_instructions is None
    finally:
        runtime.close()


def test_the_default_library_resolves_the_repository_prompts() -> None:
    assert (default_prompt_library().root / "personalities").is_dir()
