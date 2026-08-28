"""Card R9: the owner's e-stop — local-first, and releasable.

THE RULING
----------
Owner policy ruling, 2026-08-19, verbatim: "Space bar should be the e-stop. In
voice command it should be 'Die Stop'."

WHAT THIS FILE PINS THAT NOTHING ELSE DOES
------------------------------------------
``test_realtime_ingress.py`` pins the GRAMMAR — what "Die Stop" matches and what
it refuses to match. ``test_prod_default_path.py`` pins the PANEL — that Space
posts the emergency latch and that the latch announces itself with a way out.
Neither of them pins the two properties that make the latch worth having:

1. **LOCAL-FIRST.** The latch fires on the owner's words BEFORE the cloud is
   asked for anything. On the typed origin that ordering is a real, observable
   sequence of frames on the wire — the restricted ingress runs, and only then
   does ``response.create`` go up — and it is the one that can silently invert
   in an edit, because both calls live in one method. An e-stop that waits for a
   round-trip is an e-stop with a network partition in front of it.
2. **RELEASABLE.** A latch with no way out is not a safety device, it is a
   brick. The asymmetric-cost argument for latching aggressively ("a false latch
   is a stopped dog you release in one click") is only honest if the click
   exists and actually re-arms the dog. So the release is proven the only way it
   can be proven: latch, watch a motion command be refused, release, and watch
   the SAME command be accepted.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from commissioned_sim import commissioned_runtime_kwargs

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV, RealtimeConfig
from parcel_robot.realtime.ingress import (
    SPOKEN_EMERGENCY_PHRASE,
    RealtimeTranscriptOutcome,
)
from parcel_robot.realtime.lane import RealtimeLane
from parcel_robot.realtime.transport import transport_pair
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r9-estop"

#: What the owner says, spelled as the ruling spells it. Read from the module
#: rather than typed again — U33 cost a stop that stopped nothing because a
#: grammar had three copies, and a test is as good a place as any to grow a
#: fourth.
SPOKEN = SPOKEN_EMERGENCY_PHRASE


# ------------------------------------------------------------------ fixtures
class _Backend:
    """A simulator that records what it was actually told to do."""

    name = BACKEND_NAME

    def __init__(self) -> None:
        self.moves: list[VelocityCommand] = []
        self.stops = 0
        self.emergencies = 0

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        self.stops += 1

    def emergency_stop(self) -> None:
        self.emergencies += 1

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


def _runtime(tmp_path: Path, backend: _Backend) -> RobotRuntime:
    path = tmp_path / "r9.yaml"
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
        backend,
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r9 e-stop fixture",
        ),
        **commissioned_runtime_kwargs(path),
    )


def _safety_events(runtime: RobotRuntime) -> list[str]:
    return [
        str(event.get("text", ""))
        for event in runtime.snapshot()["events"]  # type: ignore[index]
        if isinstance(event, dict) and event.get("role") == "safety"
    ]


# ================================================== 1. local-first, on the wire
def test_the_typed_origin_latches_before_the_cloud_is_asked_for_a_reply() -> None:
    """THE seed catcher for "the latch moved AFTER the cloud round-trip".

    ``RealtimeLane.send_text`` does three things with the owner's sentence: it
    creates the conversation item, it runs the restricted ingress, and it asks
    the provider for a response. The ingress call is where the emergency latch
    happens, and it MUST precede the ``response.create`` — otherwise a spoken or
    typed "die stop" is queued behind a network round-trip, and a provider that
    is slow, rate-limited or unreachable becomes a dog that does not stop.

    Observed on the wire rather than by reading the source: the recording
    ingress snapshots the frames sent SO FAR at the moment it is called, so an
    inverted order shows up as ``response.create`` already being there.
    """

    seen_at_call: list[list[str]] = []

    def _ingress(text: str, **kwargs: object) -> RealtimeTranscriptOutcome:
        transport = lane.transport
        assert transport is not None
        seen_at_call.append([str(frame.get("type")) for frame in transport.sent])  # type: ignore[attr-defined]
        return RealtimeTranscriptOutcome(
            kind="emergency", name="stop", transcript=text, reply="Stopping.", executed=True
        )

    lane = RealtimeLane(
        config=RealtimeConfig(enabled=True, source="test"),
        instructions="be a good dog",
        transport_factory=lambda: transport_pair()[0],
        ingress=_ingress,
    )
    lane.open_session(handshake_token="csrf-token", mic_gesture=True)
    lane.send_text(f"{SPOKEN.capitalize()}.")

    assert len(seen_at_call) == 1, "the typed sentence must reach the ingress exactly once"
    assert "response.create" not in seen_at_call[0], (
        "the emergency latch ran only AFTER the provider was asked for a reply"
    )
    transport = lane.transport
    assert transport is not None
    after = [str(frame.get("type")) for frame in transport.sent]  # type: ignore[attr-defined]
    assert "response.create" in after, "the pin above would be vacuous without this"


def test_the_transcript_origin_latches_without_sending_the_provider_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other origin: a hosted transcript latches as a purely local decision.

    ``submit_realtime_transcript`` is the ONLY door a hosted transcript has, and
    the emergency branch is the first thing in it. Nothing in that branch asks
    the provider anything or waits for it — the words have already crossed the
    network to become text, and the card does not pretend otherwise (see
    ``does_not_prove`` in R9_STATUS.md), but from the transcript onward the
    decision is taken here, on this machine, before any reply is considered.
    """

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    backend = _Backend()
    runtime = _runtime(tmp_path, backend)
    try:
        lane = runtime.realtime_lane
        assert lane is not None
        assert lane._ingress == runtime.submit_realtime_transcript
        assert lane.transport is None, "no session is open, so there is no cloud to ask"

        outcome = runtime.submit_realtime_transcript(f"{SPOKEN.capitalize()}!")

        assert outcome.kind == "emergency"
        assert outcome.executed is True
        assert runtime.agent.safety.emergency_stopped is True
        assert runtime.snapshot()["emergency_stopped"] is True
        assert lane.transport is None, "the latch must not have needed a session"
    finally:
        runtime.close()


def test_the_latch_names_the_words_that_caused_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A latch nobody can attribute is a latch somebody will clear blindly.

    The panel log has to answer "why is the dog stopped?" for someone who does
    not know which lane latched it, at the level that is actually read (error,
    on the safety channel), naming the words.
    """

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    backend = _Backend()
    runtime = _runtime(tmp_path, backend)
    try:
        runtime.submit_realtime_transcript("Die stop, please!")
        messages = _safety_events(runtime)
        attributed = [line for line in messages if "Emergency stop latched by voice" in line]
        assert attributed, f"no attributed latch in the safety log: {messages}"
        assert "Die stop, please" in attributed[0], "the owner's words are the reason"
    finally:
        runtime.close()


# ============================================================ 2. releasable
def test_the_spoken_latch_stops_the_dog_and_the_release_makes_it_drivable_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE seed catcher for "release path broken (latch is forever)".

    The whole asymmetric-cost argument — latch eagerly, because a false latch is
    cheap — rests on the release being real. So: drive, latch by voice, watch
    the SAME motion command be refused, release through the same action door the
    panel's banner button posts to, and watch it be accepted again.
    """

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    backend = _Backend()
    runtime = _runtime(tmp_path, backend)
    try:
        runtime.manual_motion(0.2, 0.0, 0.0)

        runtime.submit_realtime_transcript("Die stop.")
        assert runtime.snapshot()["emergency_stopped"] is True
        with pytest.raises(RuntimeError, match="emergency stop"):
            runtime.manual_motion(0.2, 0.0, 0.0)

        # The panel banner's release button posts {action: "clear_emergency_stop"}
        # and this is the method that door lands on.
        assert runtime.action("clear_emergency_stop") == "Emergency stop cleared"
        assert runtime.snapshot()["emergency_stopped"] is False

        # THE point of the whole test: the dog takes orders again.
        runtime.manual_motion(0.2, 0.0, 0.0)
        assert any("cleared by operator" in line for line in _safety_events(runtime))
    finally:
        runtime.close()


def test_the_panel_button_and_the_spoken_phrase_reach_the_same_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One latch, two doors — not two latches that happen to look alike.

    Space and the red button post ``emergency_stop``; the spoken phrase goes
    through the ingress. If those ever became separate states, releasing one
    would leave the other engaged and the panel would say "clear" about a dog
    that will not move.
    """

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    backend = _Backend()
    runtime = _runtime(tmp_path, backend)
    try:
        assert runtime.action("emergency_stop") == "Emergency stop latched"
        assert runtime.snapshot()["emergency_stopped"] is True
        runtime.action("clear_emergency_stop")

        runtime.submit_realtime_transcript("Die stop.")
        assert runtime.snapshot()["emergency_stopped"] is True
        # The SAME release clears the SAME state.
        runtime.action("clear_emergency_stop")
        assert runtime.snapshot()["emergency_stopped"] is False
        assert runtime.agent.safety.emergency_stopped is False
    finally:
        runtime.close()


# ================================================ 3. the negative, end-to-end
def test_an_ordinary_sentence_with_stop_in_it_leaves_the_dog_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE seed catcher for "the negative case latches", at runtime level.

    ``test_realtime_ingress.py`` pins that the SCAN returns nothing for these.
    This pins the consequence: the arbiter never engaged, the backend was never
    told to emergency-stop, and a motion command issued straight afterwards is
    still accepted. "let's stop by the store" is a sentence, not a command.
    """

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    backend = _Backend()
    runtime = _runtime(tmp_path, backend)
    try:
        before = backend.emergencies
        outcome = runtime.submit_realtime_transcript("Let's stop by the store on the way home.")
        assert outcome.kind == "none"
        assert outcome.executed is False
        assert runtime.snapshot()["emergency_stopped"] is False
        assert backend.emergencies == before, "the backend was told to emergency-stop"
        runtime.manual_motion(0.2, 0.0, 0.0)
    finally:
        runtime.close()


# ================================ 4. card R12: the terminal names the latch
# The owner's ruling on AUDIT_R9_FABLE owner-gated finding 2, verbatim: "rename
# to emergency stop". R9 proved the latch fires from every origin; it did NOT
# prove what the mission that was running at the time is recorded as. It was
# recorded as ``navigation_disabled`` — the navigation-detail default — because
# ``NavigationChannel.stop`` discarded the reason ``preempt("safety", …)``
# handed it.
#
# These tests are here rather than in ``test_mission_log.py`` because the claim
# is about the OWNER'S DOORS: every way a person can latch the e-stop must
# produce the same record. ``test_mission_log.py`` owns the propagation
# mechanism; this owns the doors.
def _arm_mission(runtime: RobotRuntime, *, goal: str = "the sidewalk") -> None:
    """Leave the runtime in the state a mission in flight leaves behind."""

    runtime._navigation_directive = f"navigate to {goal}"
    runtime._navigation_detail = {
        "enabled": True,
        "state": "navigating",
        "directive": f"navigate to {goal}",
        "goal": goal,
        "reason": "grid_track err=0.10 goal=0.8 route=2 status=planned",
    }


def _terminals(runtime: RobotRuntime) -> list[dict[str, object]]:
    return [row for row in runtime.mission_log() if row["kind"] == "ended"]


@pytest.mark.parametrize(
    ("door", "why"),
    [
        ("action", "Space and the panel's red button both POST {action: emergency_stop}"),
        ("spoken", 'the ruling\'s spoken phrase, through the restricted ingress'),
        ("method", "the in-process door the supervisor and the sim-adopt path use"),
    ],
)
def test_every_estop_door_ends_the_running_mission_as_an_emergency_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, door: str, why: str
) -> None:
    """One record, whichever door the owner used.

    A latch that stops the dog but files the mission under a config-flag name
    is a latch the owner cannot audit afterwards — and "why did it stop?" is
    the first question asked after any e-stop.
    """

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    backend = _Backend()
    runtime = _runtime(tmp_path, backend)
    try:
        _arm_mission(runtime)

        if door == "action":
            runtime.action("emergency_stop")
        elif door == "spoken":
            runtime.submit_realtime_transcript(f"{SPOKEN.capitalize()}.")
        else:
            runtime.emergency_stop()

        assert runtime.snapshot()["emergency_stopped"] is True, why
        terminals = _terminals(runtime)
        assert terminals, "an e-stopped mission left no terminal in the log at all"
        assert terminals[-1]["reason"] == "emergency_stop", (
            "the mission that was running when the owner hit the e-stop is "
            f"recorded as {terminals[-1]['reason']!r}"
        )
        assert terminals[-1]["goal"] == "the sidewalk"
        assert "emergency_stop" in str(terminals[-1]["text"])
        nav_events = [
            str(event.get("text", ""))
            for event in runtime.snapshot()["events"]  # type: ignore[index]
            if isinstance(event, dict) and event.get("role") == "navigation"
        ]
        assert any("emergency_stop" in line for line in nav_events), (
            "the panel event stream never named the cause either"
        )
    finally:
        runtime.close()


def test_the_estop_reason_does_not_stick_to_the_next_mission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Latch, record, release — and the NEXT mission is judged on its own.

    The failure mode a propagation fix invites is a reason that becomes sticky:
    the detail keeps the last word it was given and the following terminal
    inherits it. Then the log grows a second emergency stop that never
    happened, which is worse than the gap this card closed.
    """

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    backend = _Backend()
    runtime = _runtime(tmp_path, backend)
    try:
        _arm_mission(runtime)
        runtime.action("emergency_stop")
        assert _terminals(runtime)[-1]["reason"] == "emergency_stop"

        assert runtime.action("clear_emergency_stop") == "Emergency stop cleared"
        assert runtime.snapshot()["emergency_stopped"] is False
        # The dog takes orders again (R9's release claim) — and a fresh mission
        # is admitted, runs, and ends on its OWN cause.
        runtime.manual_motion(0.2, 0.0, 0.0)
        _arm_mission(runtime, goal="the bench")

        runtime.preempt("manual", reason="operator_stop", targets=("navigation",))

        terminals = _terminals(runtime)
        assert len(terminals) == 2
        assert terminals[-1]["goal"] == "the bench"
        assert terminals[-1]["reason"] == "operator_stop", (
            "the previous mission's emergency stop leaked onto this one"
        )
    finally:
        runtime.close()
