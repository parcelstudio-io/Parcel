"""Card F1-SI: the owner's voice, and the one thing it may never gate.

WHAT THIS FILE PINS
-------------------
1. **THE SAFETY ASYMMETRY, BOTH DIRECTIONS, IN ONE TEST.** A stranger's spoken
   emergency phrase latches the dog; the same stranger's "follow me" does not
   arm, and neither does the ``navigate_to`` the hosted model would issue for
   their "go to the bench". A regression in either direction is a red here,
   which is what "binding" has to mean to be worth writing down.
2. **The threshold is the line**, it comes from configuration, and nothing else
   in the module can arm a turn that scored below it.
3. **Fail-closed in four flavours**: no profile disarms and SAYS so; a corrupt
   profile is a refusal and never a silent absence; a verify that raises
   refuses to arm; a turn too short to embed refuses to arm.
4. **The refusal is never silent** — counter, panel event, and one spoken
   always-band fact per minute, with a hint that forbids the model from
   claiming strangers cannot stop it.
5. **The DoA prefilter cannot disturb the audio stream** (test double: EP0
   control reads only, no interface claim, no audio open) and cannot overturn a
   passing embedding.
6. **Every armed turn carries its verify score**, and EV-1's assertion suite
   catches a turn that does not.
7. **The relay contract**: one verify per TURN not per frame, and a gate that
   explodes costs a refusal rather than the conversation.
"""

from __future__ import annotations

import json
import struct
import time
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime import voice_identity as V
from parcel_robot.realtime.audio_gateway import BrowserAudioGateway
from parcel_robot.realtime.config import (
    REALTIME_CONFIG_ENV,
    RealtimeConfigError,
    VoiceIdentityConfig,
    realtime_config_from_mapping,
    voice_identity_config_from_mapping,
)
from parcel_robot.realtime.ingress import KIND_EMERGENCY
from parcel_robot.realtime.whisperer import (
    ALWAYS_BAND,
    CRITICAL_KINDS,
    HINTS,
    KIND_VOICE_REJECTED,
    band_of,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
RATE = 24_000
BACKEND_NAME = "f1si-voice"

#: Speaker tags for the fake embedder: an angle in thousandths of a right angle.
#: ``OWNER`` vs ``OWNER_ISH`` scores cos(9°) = 0.988; ``OWNER`` vs ``STRANGER``
#: scores cos(90°) = 0.000; ``OWNER`` vs ``NEIGHBOUR`` scores cos(54°) = 0.588,
#: which is the one that has to sit just above the 0.55 default.
OWNER = 0
OWNER_ISH = 100
NEIGHBOUR = 600
STRANGER = 1000
#: cos(81°) = 0.156 against the owner: refused at the default, armed at 0.10.
NEAR_STRANGER = 900


def speech(tag: int, seconds: float = 1.0, rate: int = RATE) -> bytes:
    """PCM16 whose first sample names the speaker. See ``FakeSpeakerEmbedder``."""

    samples = max(1, int(seconds * rate))
    return struct.pack("<h", tag) + b"\x05\x00" * (samples - 1)


def profile_for(tag: int, *, dim: int = 8, model: str = "fake.onnx") -> V.OwnerVoiceProfile:
    return V.OwnerVoiceProfile(
        embedding=V._fake_vector(tag, dim), model=model, utterances=6, created_at="now"
    )


def gate_for(
    tag: int | None = OWNER,
    **kwargs: object,
) -> V.VoiceIdentityGate:
    kwargs.setdefault("embedder", V.FakeSpeakerEmbedder())
    kwargs.setdefault("sample_rate_hz", RATE)
    # A frozen clock far past every ``wall=`` a turn is fed at, so a caller that
    # asks for a verdict WITHOUT naming a time (which is what the runtime does)
    # sees a turn the gap has already closed — exactly like a real transcript,
    # which only ever arrives after the owner has stopped talking.
    kwargs.setdefault("clock", lambda: 1_000.0)
    return V.VoiceIdentityGate(
        profile=None if tag is None else profile_for(tag),
        **kwargs,  # type: ignore[arg-type]
    )


def hear(gate: V.VoiceIdentityGate, tag: int, *, at: float = 0.0, seconds: float = 1.0) -> None:
    """One complete owner turn of ``seconds`` from speaker ``tag``."""

    gate.observe_frame(speech(tag, seconds), wall=at)


# ===========================================================================
# 1. THE ASYMMETRY — the card's binding constraint, both directions
# ===========================================================================
class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(x=0.0),
            owner=OwnerTrack(x=2.0, y=0.0, visible=True, confidence=0.95),
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
        del tools, context, transcript
        return AgentDecision("Understood.")


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    path = tmp_path / "f1si.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
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
  logging: false
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    session = RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="f1-si voice identity fixture",
        ),
    )
    session._observation = session.backend.observe()
    try:
        yield session
    finally:
        session.close()


def test_a_strangers_stop_still_latches_while_their_command_does_not_arm(runtime) -> None:
    """THE seed. Both directions of the asymmetry, on one enrolled runtime.

    ``SYNTHESIS_EVAL.md`` decision 2: *an unverified voice cannot start motion;
    it can always stop it.* Breaking either half must redden this test — the
    emergency half because a robot nobody can stop is the worst failure this
    project has, and the command half because that is the entire card.
    """

    gate = gate_for(OWNER, clock=lambda: 5.0)
    runtime.realtime_voice_identity = gate

    # A stranger is in the room and speaking.
    hear(gate, STRANGER)
    assert gate.current(wall=5.0).code == V.CODE_NOT_OWNER

    # ... their command does NOT arm.
    outcome = runtime.submit_realtime_transcript("follow me")
    assert outcome.executed is False
    assert "below the 0.55 threshold" in outcome.error
    assert runtime.agent.safety.emergency_stopped is False

    # ... and neither does the tool call the hosted model would make for
    # "go to the bench", which the local ingress reads as chit-chat.
    with pytest.raises(RuntimeError, match="did not recognise the voice"):
        runtime._gate_by_voice("navigate_to", lambda **_: "walking")(place="bench")

    # ... but their emergency phrase STOPS THE DOG.
    from parcel_robot.realtime.ingress import SPOKEN_EMERGENCY_PHRASE

    latched = runtime.submit_realtime_transcript(SPOKEN_EMERGENCY_PHRASE)
    assert latched.executed is True
    assert latched.kind == KIND_EMERGENCY
    assert runtime.agent.safety.emergency_stopped is True

    # The rejections were counted, and the latch was not.
    assert gate.voice_rejected == 2
    assert gate.voice_accepted == 0


def test_passing_identity_without_turn_binding_remains_disarmed(runtime) -> None:
    """Acoustic success alone cannot authorize an unbound hosted command."""

    gate = gate_for(OWNER, clock=lambda: 5.0)
    runtime.realtime_voice_identity = gate
    hear(gate, OWNER_ISH)  # the owner, on a different day
    assert gate.current(wall=5.0).code == V.CODE_ARMED

    outcome = runtime.submit_realtime_transcript("follow me")
    assert outcome.executed is False
    assert "no authenticated one-shot binding" in outcome.error
    with pytest.raises(RuntimeError, match="did not recognise the voice"):
        runtime._gate_by_voice("navigate_to", lambda **_: "walking")(place="bench")


def test_passing_verdict_is_fresh_one_shot_and_cannot_cross_ingress_classes() -> None:
    gate = gate_for(OWNER)
    hear(gate, OWNER, at=10.0)
    assert gate.decide("none", wall=11.0).armed is True
    duplicate = gate.decide("tool", wall=11.0)
    assert duplicate.armed is False
    assert "already consumed" in duplicate.reason

    stale = gate_for(OWNER)
    hear(stale, OWNER, at=10.0, seconds=1.5)
    delayed = stale.decide("follow", wall=13.0)
    assert delayed.armed is False
    assert "stale" in delayed.reason


def test_gates_kind_reads_the_ingress_emergency_class_and_gates_everything_else() -> None:
    """One definition of "emergency", read from ingress, never copied."""

    assert V.gates_kind(KIND_EMERGENCY) is False
    for kind in ("closed_intent", "follow", "hold", "none", "tool", ""):
        assert V.gates_kind(kind) is True


def test_the_emergency_class_never_reads_a_verdict_at_all() -> None:
    """Not "passes the check" — never reaches it. The embedder is never called."""

    class _Exploding:
        name = "exploding"

        def __init__(self) -> None:
            self.calls = 0

        def embed(self, pcm16: bytes, sample_rate_hz: int):
            self.calls += 1
            raise RuntimeError("this embedder is on fire")

    embedder = _Exploding()
    gate = gate_for(OWNER, embedder=embedder)
    decision = gate.decide(KIND_EMERGENCY)
    assert decision.armed is True
    assert decision.code == V.CODE_SAFETY_NEVER_GATED
    assert embedder.calls == 0

    # The short-circuit is in ``decide`` itself, not only in the pure function
    # underneath it: ``current()`` — which owns the buffer, the profile, the DoA
    # and every way this module can be slow or broken — is not reached at all.
    # A seed that deleted the short-circuit and let the latch fall through to
    # ``current()`` passed the assertions above; this is what caught it.
    def _unreachable(*_args, **_kwargs):
        raise AssertionError("the latch path must never consult a verdict")

    gate.current = _unreachable  # type: ignore[method-assign]
    assert gate.decide(KIND_EMERGENCY).armed is True

    # And with no gate object at all, the pure function says the same thing.
    assert V.gate_decision(KIND_EMERGENCY, None).armed is True
    broken = V.VoiceVerdict(code=V.CODE_VERIFY_ERROR, passed=False, detail="boom")
    assert V.gate_decision(KIND_EMERGENCY, broken).armed is True
    assert V.gate_decision("follow", broken).armed is False


# ===========================================================================
# 2. the threshold
# ===========================================================================
@pytest.mark.parametrize(
    ("tag", "threshold", "armed"),
    [
        (OWNER, 0.55, True),
        (OWNER_ISH, 0.55, True),
        (NEIGHBOUR, 0.55, True),  # cos(54°) = 0.588, just above the default
        (NEIGHBOUR, 0.70, False),  # ... and refused when the owner tightens it
        (STRANGER, 0.55, False),
        (NEAR_STRANGER, 0.10, True),  # the threshold really is the only line
    ],
)
def test_the_threshold_is_the_line_and_it_comes_from_configuration(
    tag: int, threshold: float, armed: bool
) -> None:
    gate = gate_for(OWNER, threshold=threshold)
    hear(gate, tag)
    verdict = gate.current(wall=5.0)
    assert verdict.passed is armed, verdict.as_dict()
    assert gate.decide("follow", wall=5.0).armed is armed


def test_a_verify_that_raises_refuses_to_arm_and_counts_itself() -> None:
    class _Broken:
        name = "broken"

        def embed(self, pcm16: bytes, sample_rate_hz: int):
            raise RuntimeError("onnx session died")

    gate = gate_for(OWNER, embedder=_Broken())
    hear(gate, OWNER)
    verdict = gate.current(wall=5.0)
    assert verdict.code == V.CODE_VERIFY_ERROR
    assert gate.decide("follow", wall=5.0).armed is False
    assert gate.verify_errors == 1


def test_an_embedder_from_another_model_refuses_rather_than_scoring() -> None:
    """A 4-dim vector against a 192-dim profile is not a low score. It is nonsense."""

    gate = gate_for(OWNER, embedder=V.FakeSpeakerEmbedder(dim=4))
    hear(gate, OWNER)
    verdict = gate.current(wall=5.0)
    assert verdict.code == V.CODE_VERIFY_ERROR
    assert "different embedding spaces" in verdict.detail


def test_an_utterance_too_short_to_embed_does_not_arm() -> None:
    gate = gate_for(OWNER, floor_utterance_s=0.35)
    hear(gate, OWNER, seconds=0.10)
    verdict = gate.current(wall=5.0)
    assert verdict.code == V.CODE_TOO_SHORT
    assert gate.decide("follow", wall=5.0).armed is False
    assert gate.turns_too_short == 1
    # ... and the latch is still not gated by it.
    assert gate.decide(KIND_EMERGENCY, wall=5.0).armed is True


def test_a_turn_that_has_not_been_verified_yet_does_not_arm() -> None:
    """Fail-closed on PENDING: silence is not a passing score."""

    gate = gate_for(OWNER, min_utterance_s=5.0, turn_gap_s=100.0)
    hear(gate, OWNER, seconds=0.5)
    verdict = gate.current(wall=0.1)  # inside the gap: the turn is still open
    assert verdict.code == V.CODE_PENDING
    assert gate.decide("follow", wall=0.1).armed is False


# ===========================================================================
# 3. the profile — fail-closed, four flavours
# ===========================================================================
def test_no_profile_disarms_commands_and_the_snapshot_says_so_loudly() -> None:
    gate = gate_for(None)
    assert gate.enabled is False
    hear(gate, STRANGER)
    decision = gate.decide("follow", wall=5.0)
    assert decision.armed is False
    assert decision.code == V.CODE_DISABLED
    snapshot = gate.snapshot()
    assert snapshot["enabled"] is False
    assert "NO ENROLLED OWNER VOICE PROFILE" in snapshot["reason"]
    assert "non-emergency motion is DISARMED" in snapshot["reason"]


def test_runtime_missing_or_broken_identity_fails_closed_except_emergency(runtime) -> None:
    runtime.realtime_voice_identity = None
    assert runtime._voice_arming_for("follow").armed is False
    assert runtime._voice_arming_for(KIND_EMERGENCY).armed is True

    class _BrokenGate:
        def decide(self, _kind: str):
            raise RuntimeError("verifier unavailable")

    runtime.realtime_voice_identity = _BrokenGate()
    assert runtime._voice_arming_for("follow").armed is False
    # Runtime must short-circuit the latch before calling even a broken gate.
    assert runtime._voice_arming_for(KIND_EMERGENCY).armed is True


def test_an_absent_profile_is_none_and_a_broken_one_is_a_refusal(tmp_path: Path) -> None:
    """The two cases are deliberately different. Collapsing them turns the
    feature off while every surface still says it is configured."""

    assert V.load_owner_profile(tmp_path / "nothing.json") is None

    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(V.VoiceIdentityError, match="cannot be read"):
        V.load_owner_profile(bad)


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"schema": "wrong", "embedding": [1.0], "model": "m", "utterances": 5}, "schema"),
        ({"schema": V.VOICE_PROFILE_SCHEMA, "model": "m", "utterances": 5}, "no embedding"),
        (
            {
                "schema": V.VOICE_PROFILE_SCHEMA,
                "embedding": [0.0, 0.0],
                "model": "m",
                "utterances": 5,
            },
            "zero vector",
        ),
        (
            {"schema": V.VOICE_PROFILE_SCHEMA, "embedding": [1.0], "utterances": 5},
            "does not name the model",
        ),
        (
            {"schema": V.VOICE_PROFILE_SCHEMA, "embedding": [1.0], "model": "m", "utterances": 0},
            "enrollment utterances",
        ),
        (
            {
                "schema": V.VOICE_PROFILE_SCHEMA,
                "embedding": [1.0, "x"],
                "model": "m",
                "utterances": 5,
            },
            "non-numeric",
        ),
    ],
)
def test_a_profile_that_cannot_be_trusted_is_refused(
    tmp_path: Path, payload: dict, fragment: str
) -> None:
    target = tmp_path / "profile.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(V.VoiceIdentityError, match=fragment):
        V.load_owner_profile(target)


def test_the_profile_is_written_at_mode_600_and_re_enrollment_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "owner_voice_profile.json"
    first = profile_for(OWNER)
    V.save_owner_profile(first, target)
    assert target.stat().st_mode & 0o777 == V.VOICE_PROFILE_MODE

    second = V.OwnerVoiceProfile(
        embedding=V._fake_vector(NEIGHBOUR, 8), model="fake.onnx", utterances=9
    )
    V.save_owner_profile(second, target)
    loaded = V.load_owner_profile(target)
    assert loaded is not None
    assert loaded.utterances == 9
    assert loaded.score(V._fake_vector(NEIGHBOUR, 8)) == pytest.approx(1.0, abs=1e-6)
    assert target.stat().st_mode & 0o777 == V.VOICE_PROFILE_MODE
    assert not list(target.parent.glob("*.tmp"))


def test_the_profile_never_leaves_its_embedding_in_a_snapshot() -> None:
    gate = gate_for(OWNER)
    described = gate.snapshot()["profile"]
    assert described is not None
    assert "embedding" not in described
    assert json.dumps(gate.snapshot())  # the whole snapshot is still serialisable


def test_the_default_profile_path_sits_beside_the_realtime_config(tmp_path: Path) -> None:
    config = tmp_path / "cfg" / "realtime.yaml"
    assert V.default_profile_path(config) == config.parent / V.VOICE_PROFILE_NAME
    assert V.default_profile_path(None).name == V.VOICE_PROFILE_NAME
    assert ".config" in str(V.default_profile_path(None))


def test_the_enroller_refuses_to_write_inside_the_repository() -> None:
    import tools.enroll_owner_voice as enroll

    with pytest.raises(enroll.EnrollmentRefusal):
        enroll.refuse_repo_path(REPO / "models" / "leaked.json")
    # A path outside the tree is fine.
    enroll.refuse_repo_path(Path("/tmp/parcel-f1si-ok.json"))


def test_the_enroller_refuses_too_few_utterances() -> None:
    import tools.enroll_owner_voice as enroll

    with pytest.raises(enroll.EnrollmentRefusal, match="at least"):
        enroll.enroll(
            [("a.wav", speech(OWNER), RATE)],
            model_path=Path("/nonexistent.onnx"),
            threshold=0.55,
        )


# ===========================================================================
# 4. the refusal is never silent
# ===========================================================================
def test_the_rejection_class_is_always_band_and_is_not_a_budget_bypass() -> None:
    assert KIND_VOICE_REJECTED in ALWAYS_BAND
    assert band_of(KIND_VOICE_REJECTED) == "always"
    # Deliberately NOT critical: the critical set bypasses the OWNER's cost
    # budget for facts about the OWNER's own requests, and this is by
    # construction a fact about somebody else's.
    assert KIND_VOICE_REJECTED not in CRITICAL_KINDS


def test_the_narration_hint_forbids_claiming_strangers_cannot_stop_the_robot() -> None:
    hint = HINTS[KIND_VOICE_REJECTED]
    assert "stop" in hint.lower()
    assert "anyone may still stop you" in hint.lower()


def test_the_rejection_fact_names_what_was_refused_and_what_was_not() -> None:
    fact = V.rejection_fact("follow", "walk with me")
    assert "did NOT recognise" in fact
    assert "walk with me" in fact
    assert "emergency stop is not identity-checked" in fact


def test_a_rejection_is_counted_every_time_and_spoken_once_per_minute() -> None:
    now = [1000.0]
    gate = gate_for(OWNER, narration_interval_s=60.0, clock=lambda: now[0])
    assert gate.note_rejection() is True  # the first one always speaks
    assert gate.note_rejection() is False
    now[0] += 59.0
    assert gate.note_rejection() is False
    now[0] += 2.0
    assert gate.note_rejection() is True
    assert gate.voice_rejected == 4  # every one counted
    assert gate.narrations == 2  # only two spoken


def test_the_runtime_speaks_the_refusal_and_still_writes_the_ledger(runtime) -> None:
    gate = gate_for(OWNER)
    runtime.realtime_voice_identity = gate
    spoken: list[str] = []
    ledgered: list[tuple[str, str]] = []
    runtime._whisper = lambda event: spoken.append(event.kind) or True  # type: ignore[assignment]
    runtime._write_realtime_ledger = (  # type: ignore[assignment]
        lambda speaker, text, **_: ledgered.append((speaker, text))
    )
    hear(gate, STRANGER)

    outcome = runtime.submit_realtime_transcript("follow me")
    assert outcome.executed is False
    assert spoken == [KIND_VOICE_REJECTED]
    # The record still holds what was said: a transcript hidden because the
    # product distrusted the speaker is a record that lies by omission, and the
    # F1 story is entirely about a record that could not tell speakers apart.
    assert ledgered == [("owner", "follow me")]
    # The panel saw it too.
    assert any(
        "REFUSED to arm" in str(row.get("text", "")) for row in runtime.snapshot()["events"]
    )


# ===========================================================================
# 5. the DoA prefilter
# ===========================================================================
class _AuditedUsb:
    """A pyusb device double that records every method anyone calls on it."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[tuple[str, tuple]] = []

    def ctrl_transfer(self, request_type, request, value, index, length, timeout=None):
        self.calls.append(("ctrl_transfer", (request_type, request, value, index, length)))
        return bytearray(self.payload[:length])

    def __getattr__(self, name):  # anything else is a disturbance
        def _forbidden(*args, **kwargs):
            self.calls.append((name, args))
            raise AssertionError(f"the DoA reader must never call {name}()")

        return _forbidden


def test_the_doa_reader_only_ever_issues_ep0_control_reads(monkeypatch) -> None:
    """Non-disruption, the bench's way, with a double that would tell on us.

    Bench A measured the real thing (ALSA stream ``closed -> closed``, no
    re-enumeration). This asserts the MECHANISM that made it true: a vendor IN
    control transfer on endpoint zero and nothing else — no
    ``set_configuration``, no ``claim_interface``, no audio device.
    """

    device = _AuditedUsb(struct.pack("<HH", 137, 1))
    reader = V.UsbDoaReader()
    monkeypatch.setattr(reader, "_ensure_device", lambda: device)

    sample = reader.read()
    assert sample is not None
    assert sample.angle_deg == 137
    assert sample.vad is True
    assert [name for name, _ in device.calls] == ["ctrl_transfer"]
    (_, args) = device.calls[0]
    assert args[0] == 0xC0  # vendor IN, device-to-host, EP0
    assert args[2] == 0x80 | V.DOA_COMMAND_ID
    assert args[3] == V.DOA_RESOURCE_ID
    assert reader.reads_ok == 1


def test_the_doa_reader_tolerates_the_optional_status_byte(monkeypatch) -> None:
    device = _AuditedUsb(b"\x00" + struct.pack("<HH", 42, 0))
    reader = V.UsbDoaReader()
    monkeypatch.setattr(reader, "_ensure_device", lambda: device)
    sample = reader.read()
    assert sample is not None and sample.angle_deg == 42 and sample.vad is False


def test_a_doa_read_that_fails_is_none_and_never_an_exception(monkeypatch) -> None:
    """This is the state of THIS host: Errno 13 until the owner adds a udev rule."""

    reader = V.UsbDoaReader()

    def _denied():
        raise PermissionError(13, "Access denied (insufficient permissions)")

    monkeypatch.setattr(reader, "_ensure_device", _denied)
    assert reader.read() is None
    assert reader.reads_failed == 1
    assert "PermissionError" in reader.last_error


@pytest.mark.parametrize(
    ("angle", "start", "end", "inside"),
    [
        (20, 10, 40, True),
        (5, 10, 40, False),
        (355, 350, 10, True),  # wrap
        (5, 350, 10, True),  # wrap
        (180, 350, 10, False),  # the wrap does NOT invert the sector
    ],
)
def test_a_sector_wraps_without_inverting(angle, start, end, inside) -> None:
    assert V.sector_contains(angle, start, end) is inside


def test_a_rejected_sector_refuses_only_what_the_embedding_already_refused() -> None:
    """Belt AND suspenders, in that order: the embedding is the authority."""

    tv = V.FakeDoaReader([V.DoaSample(angle_deg=95, vad=True)])
    gate = gate_for(OWNER, doa=tv, rejected_sector=(80.0, 110.0))
    hear(gate, STRANGER)
    verdict = gate.current(wall=5.0)
    assert verdict.code == V.CODE_REJECTED_SECTOR
    assert verdict.doa_deg == 95
    assert gate.sector_rejected == 1
    assert gate.decide("follow", wall=5.0).armed is False
    assert tv.opened_audio is False

    # The owner, speaking from the same direction as the television, is armed:
    # a sector may never overturn a passing embedding.
    tv2 = V.FakeDoaReader([V.DoaSample(angle_deg=95, vad=True)])
    owner_gate = gate_for(OWNER, doa=tv2, rejected_sector=(80.0, 110.0))
    hear(owner_gate, OWNER_ISH)
    assert owner_gate.current(wall=5.0).code == V.CODE_ARMED
    assert owner_gate.sector_rejected == 0


def test_an_unreadable_doa_contributes_nothing_rather_than_refusing_everything() -> None:
    """The udev rule is not in place on this host; that must not brick commands."""

    blocked = V.FakeDoaReader([None])
    gate = gate_for(OWNER, doa=blocked, rejected_sector=(80.0, 110.0))
    hear(gate, OWNER)
    assert gate.decide("follow", wall=5.0).armed is True
    assert gate.sector_rejected == 0


def test_the_doa_is_not_read_at_all_without_a_configured_sector() -> None:
    reader = V.FakeDoaReader([V.DoaSample(angle_deg=95, vad=True)])
    gate = gate_for(OWNER, doa=reader, rejected_sector=None)
    hear(gate, OWNER)
    gate.current(wall=5.0)
    assert reader.calls == 0


# ===========================================================================
# 6. provenance — refused turns cannot masquerade as armed
# ===========================================================================
def test_unbound_passing_turn_never_records_false_arming_provenance(runtime) -> None:
    gate = gate_for(OWNER)
    runtime.realtime_voice_identity = gate
    hear(gate, OWNER_ISH)
    runtime.submit_realtime_transcript("follow me")

    rows = [
        row["text"]
        for row in runtime.snapshot()["events"]
        if runtime.VOICE_PROVENANCE_PREFIX in str(row.get("text", ""))
    ]
    assert rows == []
    assert any(
        "voice identity REFUSED" in str(row.get("text", ""))
        for row in runtime.snapshot()["events"]
    )


def test_the_latch_writes_a_provenance_row_that_proves_it_was_not_gated(runtime) -> None:
    from parcel_robot.realtime.ingress import SPOKEN_EMERGENCY_PHRASE

    gate = gate_for(OWNER)
    runtime.realtime_voice_identity = gate
    hear(gate, STRANGER)
    runtime.submit_realtime_transcript(SPOKEN_EMERGENCY_PHRASE)

    from evals.assertions.checks import VOICE_ARMED_RE, VOICE_CODE_SAFETY

    rows = [
        VOICE_ARMED_RE.search(str(row.get("text", "")))
        for row in runtime.snapshot()["events"]
    ]
    matches = [row for row in rows if row is not None]
    assert matches, "the latch wrote no provenance row"
    assert matches[-1].group("code") == VOICE_CODE_SAFETY
    assert matches[-1].group("score") == "none"


def _evidence(events: list[dict], *, enabled: bool):
    from evals.assertions.evidence import EVIDENCE_STREAM, SessionEvidence

    return SessionEvidence(
        name="f1si",
        path=Path("/nonexistent"),
        events=events,
        state={
            "realtime": {"gateway": {"voice_identity": {"enabled": enabled}}},
        },
        event_source=EVIDENCE_STREAM,
    )


def test_the_assertion_suite_catches_a_score_dropped_from_provenance() -> None:
    from evals.assertions.checks import check_voice_provenance

    dropped = [
        {
            "text": "voice identity armed 'follow': score=none threshold=0.55 "
            "code=armed turn=3",
            "wall": "2026-08-20 10:00:00",
        }
    ]
    findings = check_voice_provenance(_evidence(dropped, enabled=True))
    assert [f.check for f in findings] == ["armed_turn_without_verify_score"]
    assert findings[0].kind == "verdict"


def test_the_assertion_suite_catches_an_arm_below_its_own_threshold() -> None:
    from evals.assertions.checks import check_voice_provenance

    rows = [
        {
            "text": "voice identity armed 'follow': score=0.2000 threshold=0.55 "
            "code=armed turn=3",
            "wall": "2026-08-20 10:00:00",
        }
    ]
    findings = check_voice_provenance(_evidence(rows, enabled=True))
    assert [f.check for f in findings] == ["armed_below_threshold"]
    assert findings[0].dimension == "safety"


def test_the_assertion_suite_catches_a_latch_that_went_through_an_identity_check() -> None:
    from evals.assertions.checks import check_voice_provenance

    rows = [
        {
            "text": "voice identity armed 'emergency': score=0.9000 threshold=0.55 "
            "code=armed turn=3",
            "wall": "2026-08-20 10:00:00",
        }
    ]
    findings = check_voice_provenance(_evidence(rows, enabled=True))
    assert "latch_was_identity_gated" in [f.check for f in findings]


def test_an_unverified_session_is_a_review_candidate_and_never_a_verdict() -> None:
    """Nobody has enrolled on this host. That is not a product defect."""

    from evals.assertions.checks import check_voice_provenance

    rows = [
        {
            "text": "voice identity armed 'follow': score=none threshold=0.55 "
            "code=verify_disabled turn=1",
            "wall": "2026-08-20 10:00:00",
        }
    ]
    findings = check_voice_provenance(_evidence(rows, enabled=False))
    assert [f.check for f in findings] == ["armed_turns_unattributed"]
    assert findings[0].kind == "review"


def test_a_clean_verified_session_produces_no_findings() -> None:
    from evals.assertions.checks import check_voice_provenance

    rows = [
        {
            "text": "voice identity armed 'follow': score=0.8100 threshold=0.55 "
            "code=armed turn=2",
            "wall": "2026-08-20 10:00:00",
        },
        {
            "text": "voice identity armed 'emergency': score=none threshold=0.55 "
            "code=safety_never_gated turn=3",
            "wall": "2026-08-20 10:00:05",
        },
    ]
    assert check_voice_provenance(_evidence(rows, enabled=True)) == []


# ===========================================================================
# 7. the relay contract
# ===========================================================================
def test_a_long_turn_is_re_verified_on_its_whole_audio() -> None:
    """The fix the FAR/FRR measurement forced, pinned so it cannot be undone.

    A provisional embedding over the first 1.2 s of a sentence is an opinion
    about a fragment. Measured on this host's gold set through this code path,
    a single early verify cost **FRR 38.5 %** at FAR 0 %; verifying the whole
    turn again at settle time brought that to 15.4 % with the margin positive.
    So the second look is not a nicety — it is most of the accuracy.

    The double also proves the verdict is REPLACED and not max()'d: the tail of
    this turn is a different speaker, and the final verdict follows the audio
    rather than keeping the flattering early score.
    """

    class _Turncoat:
        """Owner on the first look, stranger on the second. The fake embedder
        keys on the FIRST PCM sample and so cannot express "the turn changed";
        this one can, which is what makes the replacement observable."""

        name = "turncoat"

        def __init__(self) -> None:
            self.calls = 0
            self.seen: list[int] = []

        def embed(self, pcm16: bytes, sample_rate_hz: int):
            self.calls += 1
            self.seen.append(len(pcm16))
            return V._fake_vector(OWNER if self.calls == 1 else STRANGER, 8)

    embedder = _Turncoat()
    gate = gate_for(OWNER, embedder=embedder, min_utterance_s=1.0, turn_gap_s=0.75)
    gate.observe_frame(speech(OWNER, 1.5), wall=0.0)  # provisional: the owner
    assert embedder.calls == 1
    assert gate.snapshot()["verdict"]["code"] == V.CODE_ARMED

    # ... the turn keeps going, and turns out not to be the owner after all.
    gate.observe_frame(speech(STRANGER, 4.0), wall=0.1)
    verdict = gate.current(wall=10.0)  # settle: re-verified on the WHOLE turn
    assert embedder.calls == 2
    assert embedder.calls <= V.MAX_VERIFIES_PER_TURN
    # The second embedding saw the whole 5.5 s, not the 1.5 s fragment.
    assert embedder.seen[1] > embedder.seen[0] * 3
    assert verdict.seconds == pytest.approx(5.5, abs=0.05)
    # ... and the LATER verdict replaced the earlier one rather than being
    # max()'d against it, which would be a gate that lowers its own threshold
    # by sampling twice.
    assert verdict.code == V.CODE_NOT_OWNER
    assert gate.decide("follow", wall=10.0).armed is False


def test_the_counters_count_turns_and_not_embeddings() -> None:
    """Found by the end-to-end proof, not by a test: a three-turn session read
    ``turns_verified: 5, voice_accepted: 2`` for ONE accepted turn, because the
    provisional and the final look at the same sentence were counted as two
    votes. A panel number that double-counts is worse than no number."""

    embedder = V.FakeSpeakerEmbedder()
    gate = gate_for(OWNER, embedder=embedder, min_utterance_s=1.0, turn_gap_s=0.75)
    # One long owner turn: two embeddings, one turn.
    gate.observe_frame(speech(OWNER_ISH, 1.2), wall=0.0)
    gate.observe_frame(speech(OWNER_ISH, 4.0), wall=0.1)
    gate.current(wall=10.0)
    # One stranger turn.
    gate.observe_frame(speech(STRANGER, 2.0), wall=20.0)
    gate.current(wall=30.0)

    assert embedder.calls == 3  # 2 + 1
    assert gate.turns_seen == 2
    assert gate.turns_verified == 2  # turns, not embeddings
    assert gate.voice_accepted == 1
    snapshot = gate.snapshot()
    assert snapshot["turns_verified"] <= snapshot["turns_seen"]
    assert snapshot["voice_accepted"] <= snapshot["turns_verified"]


def test_a_turn_that_barely_grew_is_not_re_verified() -> None:
    """The second embedding costs ~27 ms and must be earned."""

    embedder = V.FakeSpeakerEmbedder()
    gate = gate_for(OWNER, embedder=embedder, min_utterance_s=1.0)
    gate.observe_frame(speech(OWNER, 1.2), wall=0.0)
    gate.observe_frame(speech(OWNER, 0.1), wall=0.1)  # +8%, far below 1.5x
    gate.current(wall=10.0)
    assert embedder.calls == 1


def test_the_enroller_refuses_recordings_that_are_not_one_voice(monkeypatch) -> None:
    """A profile averaged over two speakers scores wrong for the rest of time."""

    import tools.enroll_owner_voice as enroll

    monkeypatch.setattr(enroll, "SherpaSpeakerEmbedder", lambda *_a, **_k: V.FakeSpeakerEmbedder())
    sources = [
        (f"{index}.wav", speech(tag), RATE)
        for index, tag in enumerate([OWNER, OWNER, OWNER, OWNER, OWNER, STRANGER])
    ]
    with pytest.raises(enroll.EnrollmentRefusal, match="not one voice"):
        enroll.enroll(sources, model_path=Path("fake.onnx"), threshold=0.55)

    # ... and one speaker's six utterances enroll cleanly.
    same = [(f"{index}.wav", speech(OWNER_ISH), RATE) for index in range(6)]
    profile, scores = enroll.enroll(same, model_path=Path("fake.onnx"), threshold=0.55)
    assert profile.utterances == 6
    assert all(score > 0.99 for _name, score in scores)


def test_one_verify_per_turn_and_not_one_per_frame() -> None:
    """27 ms once a turn is the budget; 27 ms per 20 ms frame is a broken relay."""

    embedder = V.FakeSpeakerEmbedder()
    gate = gate_for(OWNER, embedder=embedder, min_utterance_s=0.2)
    frame = speech(OWNER, 0.25)
    for index in range(20):
        gate.observe_frame(frame, wall=index * 0.02)
    assert embedder.calls == 1
    assert gate.turns_seen == 1


def test_turns_are_cut_on_the_same_silence_gap_the_capture_tee_uses() -> None:
    embedder = V.FakeSpeakerEmbedder()
    gate = gate_for(OWNER, embedder=embedder, turn_gap_s=0.75)
    gate.observe_frame(speech(OWNER, 1.0), wall=0.0)
    gate.observe_frame(speech(OWNER, 1.0), wall=0.5)  # same turn: inside the gap
    assert gate.turns_seen == 1
    gate.observe_frame(speech(STRANGER, 1.0), wall=2.0)  # new turn: past the gap
    assert gate.turns_seen == 2
    assert gate.current(wall=10.0).code == V.CODE_NOT_OWNER
    assert V.DEFAULT_TURN_GAP_S == 0.75


def test_the_gate_never_raises_into_the_relay() -> None:
    """The R17 tee's law, inherited. A broken gate costs a refusal, not a call."""

    class _Hostile:
        name = "hostile"

        def embed(self, pcm16: bytes, sample_rate_hz: int):
            raise MemoryError("everything is on fire")

    gate = gate_for(OWNER, embedder=_Hostile())
    gate.observe_frame(speech(OWNER), wall=0.0)  # must not raise
    gate.end_turn(wall=5.0)  # must not raise
    assert gate.current(wall=5.0).passed is False
    assert gate.decide("follow", wall=5.0).armed is False

    # The OUTER firewall, not just the one around ``embed()``. A seed that made
    # ``observe_frame`` re-raise passed the assertions above, because the only
    # exception they produce is caught one level deeper — so this breaks the
    # gate's own bookkeeping instead of the embedder's, and the frame still has
    # to come back cleanly to the socket reader thread.
    broken = gate_for(OWNER)
    broken.bytes_per_second = 0.0  # every duration this object computes now /0
    broken.observe_frame(speech(OWNER), wall=0.0)  # must not raise
    assert broken.verify_errors >= 1
    assert broken.decide("follow", wall=5.0).armed is False


def test_the_gateway_feeds_the_gate_and_still_hands_every_frame_to_the_lane() -> None:
    """The ear records WHO; it never decides WHETHER. A stranger's audio still
    reaches the transcriber, which is what makes their stop possible at all."""

    gate = gate_for(OWNER)
    delivered: list[bytes] = []
    gateway = BrowserAudioGateway(
        on_audio=delivered.append,
        on_mic=lambda _open: None,
        voice_identity=gate,
        sample_rate_hz=RATE,
    )
    gateway.bind_token("tok")
    gateway.start()
    conn = gateway.attach("tok")
    gateway.set_mic(conn, True)
    frame = speech(STRANGER, 0.02)
    for index in range(60):
        assert gateway.accept_audio(conn, frame) is True
        del index
    assert len(delivered) == 60  # every frame went up, stranger or not
    assert gate.turns_seen == 1
    assert gateway.voice_identity is gate
    assert gateway.snapshot()["voice_identity"]["enabled"] is True
    gateway.stop()


def test_a_gateway_without_a_gate_says_so_and_behaves_exactly_as_before() -> None:
    gateway = BrowserAudioGateway(on_audio=lambda _payload: None)
    snapshot = gateway.snapshot()["voice_identity"]
    assert snapshot["enabled"] is False
    assert "non-emergency motion is disarmed" in snapshot["reason"]
    assert gateway.voice_identity is None


def test_the_latency_budget_is_measured_and_reported() -> None:
    gate = gate_for(OWNER, embedder=V.FakeSpeakerEmbedder(latency_s=0.02), budget_ms=5.0)
    hear(gate, OWNER)
    gate.current(wall=5.0)
    latency = gate.latency_ms()
    assert latency["n"] == 1
    assert latency["max"] >= 20.0
    assert gate.budget_exceeded == 1
    assert gate.snapshot()["budget_ms"] == 5.0


# ===========================================================================
# 8. configuration
# ===========================================================================
def test_voice_identity_defaults_are_on_and_inert() -> None:
    config = realtime_config_from_mapping({"enabled": True})
    assert config.voice_identity == VoiceIdentityConfig()
    assert config.voice_identity.enabled is True
    assert config.voice_identity.threshold == 0.55
    assert config.voice_identity.doa is False
    assert config.voice_identity.rejected_sector is None
    assert "voice_identity" in config.as_dict()


@pytest.mark.parametrize(
    ("block", "fragment"),
    [
        ({"treshold": 0.6}, "unknown realtime.voice_identity key"),
        ({"threshold": 55}, "cosine similarity"),
        ({"threshold": 0.0}, "cosine similarity"),
        ({"threshold": "high"}, "must be a number"),
        ({"enabled": "yes"}, "must be a boolean"),
        ({"rejected_sector": [10, 40]}, "doa is false"),
        ({"doa": True, "rejected_sector": [10]}, "two-element"),
        ({"doa": True, "rejected_sector": [10, 400]}, "degrees in"),
        ({"min_utterance_s": 0}, "greater than zero"),
        ({"narration_interval_s": -1}, "must not be negative"),
    ],
)
def test_a_typo_in_the_voice_identity_block_is_a_refusal(block: dict, fragment: str) -> None:
    with pytest.raises(RealtimeConfigError, match=fragment):
        voice_identity_config_from_mapping(block)


def test_a_sector_with_a_doa_reader_is_accepted() -> None:
    config = voice_identity_config_from_mapping({"doa": True, "rejected_sector": [350, 10]})
    assert config.rejected_sector == (350.0, 10.0)
    assert config.as_dict()["rejected_sector"] == [350.0, 10.0]


def test_the_block_can_be_turned_off_and_then_no_gate_is_built(runtime) -> None:
    runtime.realtime_config = dataclasses_replace_voice(runtime.realtime_config, enabled=False)
    assert runtime._build_voice_identity_gate() is None


def dataclasses_replace_voice(config, **kwargs):
    import dataclasses

    return dataclasses.replace(
        config, voice_identity=dataclasses.replace(config.voice_identity, **kwargs)
    )


def test_the_vendored_model_is_pinned_with_a_provenance_lock() -> None:
    """Like the judge: the digest is committed even though the bytes are not."""

    lock = json.loads(
        (REPO / "models" / "speaker_id" / "models.lock.json").read_text(encoding="utf-8")
    )
    entry = lock["models"]["nemo_en_titanet_small"]
    assert entry["license"] == "Apache-2.0"
    assert entry["size_bytes"] == 40_257_283
    assert len(entry["sha256"]) == 64
    assert entry["url"].startswith("https://github.com/k2-fsa/sherpa-onnx/releases/download/")
    assert "never_the_emergency_latch" in entry["activation"]
