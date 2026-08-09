"""Card C1: conversation-reactive emotes through the validated Gesture skill."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.compiler import compile_plan_contracts
from parcel_robot.brain.contracts import (
    FrozenDict,
    GoalSpec,
    GoalTarget,
    PlanIR,
    PlanStep,
    SuccessCondition,
)
from parcel_robot.brain.executive import DispatchRequest
from parcel_robot.brain.runtime_adapter import (
    SemanticRuntimeState,
    SemanticTaskRuntimeAdapter,
)
from parcel_robot.brain.validator import (
    PlanValidationError,
    PlanValidator,
    SkillContractRegistry,
)
from parcel_robot.dynamic_prompting import EmotePolicySource
from parcel_robot.providers import SentenceChunkedSynthesizer, strip_emote_tags
from parcel_robot.runtime import RobotRuntime
from parcel_robot.voice_pipeline import VoiceTurn

REPO = Path(__file__).resolve().parents[1]
EMOTES = ("bow", "paw_wave", "play_bow")


# --- contract validation ----------------------------------------------------


def _gesture_plan(name: str, **arguments: object) -> PlanIR:
    registry = SkillContractRegistry.default(
        owner_heading_supported=True, gesture_names=EMOTES
    )
    return compile_plan_contracts(
        PlanIR(
            schema_version=1,
            task_id="task-emote-1",
            plan_revision=1,
            source_turn_id="turn-emote-1",
            goal=GoalSpec(relation="hold", target=GoalTarget(kind="current_pose")),
            invariants=(),
            steps=(
                PlanStep(
                    step_id="s1",
                    skill="Gesture",
                    arguments=FrozenDict({"name": name, **arguments}),
                    success=SuccessCondition(fact="skill_completed"),
                ),
            ),
        ),
        registry,
    )


def _validator() -> PlanValidator:
    return PlanValidator(
        SkillContractRegistry.default(owner_heading_supported=True, gesture_names=EMOTES)
    )


def test_gesture_validates_with_and_without_intensity() -> None:
    validator = _validator()
    plain = validator.validate(_gesture_plan("play_bow"))
    assert plain.steps[0].step.skill == "Gesture"
    scaled = validator.validate(_gesture_plan("play_bow", intensity=1.4))
    assert scaled.steps[0].step.arguments["intensity"] == 1.4


def test_gesture_rejects_out_of_range_intensity() -> None:
    validator = _validator()
    for bad in (0.2, 1.9, "loud"):
        with pytest.raises(PlanValidationError) as excinfo:
            validator.validate(_gesture_plan("play_bow", intensity=bad))
        assert excinfo.value.code == "invalid_argument_value"


def test_gesture_rejects_a_clip_outside_the_admitted_catalog() -> None:
    with pytest.raises(PlanValidationError) as excinfo:
        _validator().validate(_gesture_plan("backflip"))
    assert excinfo.value.code == "invalid_argument_value"
    assert "admitted gesture catalog" in str(excinfo.value)


def test_gesture_contract_compiles_the_stationary_gate() -> None:
    """Emotes may only run from a stopped robot — compiled, not requested."""

    step = _gesture_plan("bow").steps[0]
    assert "robot_stopped" in step.preconditions
    assert "posture_available" in step.preconditions


def test_empty_catalog_admits_no_gesture_at_all() -> None:
    validator = PlanValidator(SkillContractRegistry.default(owner_heading_supported=True))
    with pytest.raises(PlanValidationError, match="no gesture catalog"):
        validator.validate(_gesture_plan("bow"))


# --- adapter dispatch + verified completion ---------------------------------


def _request(
    name: str, intensity: float | None = None, *, step_id: str = "s1"
) -> DispatchRequest:
    arguments = {"name": name}
    if intensity is not None:
        arguments["intensity"] = intensity
    return DispatchRequest(
        task_id="task-emote-1",
        plan_revision=1,
        step_id=step_id,
        attempt=1,
        skill="Gesture",
        arguments=FrozenDict(arguments),
        success=SuccessCondition(fact="skill_completed"),
        resources=("base", "posture"),
        timeout_s=30.0,
    )


def _adapter(calls: list[tuple[str, float]]) -> SemanticTaskRuntimeAdapter:
    return SemanticTaskRuntimeAdapter(
        navigate=lambda directive: None,
        follow_formation=lambda relation, distance: None,
        spatial_behavior=lambda intent: None,
        hold=lambda: None,
        vocalize=lambda text: None,
        gesture=lambda name, intensity: calls.append((name, intensity)),
    )


def test_adapter_dispatches_gesture_with_default_intensity() -> None:
    calls: list[tuple[str, float]] = []
    adapter = _adapter(calls)
    assert adapter.dispatch(_request("paw_wave"), now=1.0) is None
    assert calls == [("paw_wave", 1.0)]
    assert adapter.dispatch(_request("bow", 0.6, step_id="s2"), now=2.0) is None
    assert calls[-1] == ("bow", 0.6)


def test_gesture_completion_requires_the_coordinator_to_confirm() -> None:
    calls: list[tuple[str, float]] = []
    adapter = _adapter(calls)
    adapter.dispatch(_request("paw_wave"), now=1.0)

    running = SemanticRuntimeState(
        snapshot_id="s", activity_name="paw_wave", activity_status="running",
        activity_created_at=1.05,
    )
    assert adapter.poll(running, now=1.1)[0].status == "in_progress"

    # A *different* activity completing must not satisfy this gesture.
    other = SemanticRuntimeState(
        snapshot_id="s", activity_name="bow", activity_status="completed",
        activity_created_at=1.05,
    )
    assert adapter.poll(other, now=1.2)[0].status == "in_progress"

    # 2026-08-04 review fix: a terminal record from an EARLIER same-name
    # emote (created before this dispatch) must not complete it.
    stale = SemanticRuntimeState(
        snapshot_id="s", activity_name="paw_wave", activity_status="completed",
        activity_created_at=0.4,
    )
    assert adapter.poll(stale, now=1.25)[0].status == "in_progress"

    done = SemanticRuntimeState(
        snapshot_id="s", activity_name="paw_wave", activity_status="completed",
        activity_created_at=1.05,
    )
    result = adapter.poll(done, now=1.3)[0]
    assert result.status == "succeeded"
    fact = result.verified_facts[0]
    assert fact.fact == "skill_completed"
    assert fact.target == "paw_wave"
    assert fact.source == "activity_coordinator"
    assert adapter.active() == ()


@pytest.mark.parametrize("status", ["cancelled", "expired", "rejected", "failed"])
def test_gesture_terminal_failures_are_reported(status: str) -> None:
    adapter = _adapter([])
    adapter.dispatch(_request("bow"), now=1.0)
    state = SemanticRuntimeState(
        snapshot_id="s",
        activity_name="bow",
        activity_status=status,
        activity_detail=f"preempted_by_{status}",
        activity_created_at=1.05,
    )
    assert adapter.poll(state, now=1.1)[0].status == "failed"


def test_gesture_without_a_runtime_callback_fails_closed() -> None:
    adapter = SemanticTaskRuntimeAdapter(
        navigate=lambda directive: None,
        follow_formation=lambda relation, distance: None,
        spatial_behavior=lambda intent: None,
        hold=lambda: None,
        vocalize=lambda text: None,
    )
    with pytest.raises(RuntimeError, match="no runtime callback"):
        adapter.dispatch(_request("bow"), now=1.0)


# --- inline speech tags -----------------------------------------------------


def test_strip_emote_tags_extracts_and_tidies() -> None:
    spoken, emotes = strip_emote_tags(
        "That is wonderful! [emote:play_bow] I am glad [emote:shake:0.8], truly."
    )
    assert spoken == "That is wonderful! I am glad, truly."
    assert emotes == [("play_bow", 1.0), ("shake", 0.8)]
    assert strip_emote_tags("nothing here") == ("nothing here", [])
    # A malformed intensity degrades to the default rather than breaking speech.
    assert strip_emote_tags("[emote:bow:abc]hi")[1] == []


class _EchoSynth:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.spoken.append(text)
        return text.encode()


def test_streaming_attaches_each_emote_to_its_own_chunk() -> None:
    """Card W8: the tag travels with its sentence's audio, it does not fire."""

    synth = _EchoSynth()
    chunked = SentenceChunkedSynthesizer(synth)
    chunks = list(
        chunked.synthesize_stream(
            "Hello there. [emote:play_bow] I missed you. See you soon."
        )
    )
    assert len(chunks) == 3
    # Nothing spoken contains a tag.
    assert all("[emote:" not in text for text in synth.spoken)
    # The emote rides the sentence it was authored in, and no other.
    assert [chunk.emotes for chunk in chunks] == [(), (("play_bow", 1.0),), ()]
    # Still ordinary audio bytes for every downstream consumer.
    assert chunks[1] == b"I missed you."


def test_blocking_synthesize_strips_tags_and_keeps_their_emotes() -> None:
    synth = _EchoSynth()
    chunk = SentenceChunkedSynthesizer(synth).synthesize("[emote:bow] Hi there.")
    assert synth.spoken == ["Hi there."]
    assert chunk.emotes == (("bow", 1.0),)


# --- prompt policy ----------------------------------------------------------


def test_emote_policy_lists_the_catalog_and_the_rules() -> None:
    text = EmotePolicySource(EMOTES).snapshot(None)
    assert text is not None
    assert "[emote:" in text
    assert "play_bow" in text and "bow" in text
    assert "at most one" in text
    assert EmotePolicySource(()).snapshot(None) is None


# --- runtime wiring ---------------------------------------------------------


class _Backend:
    name = "emote-test"

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            backend=self.name,
        )

    def move(self, command: object) -> None:
        del command

    def stop(self) -> None:
        pass

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


def _config(tmp_path: Path, *, emotes: str = "") -> Path:
    path = tmp_path / "emote-runtime.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
  brain:
    enabled: true
{emotes}
# Declared, not inferred. These cases are about the *text-only* reply path, and
# they used to get it by accident: `build_speech_stack` defaults to `auto`, so
# whether a synthesizer (and therefore a `_speaker_sink`) existed depended on
# whether `models/piper/voice.onnx` happened to be on the disk. It appeared
# mid-session on 2026-08-07 and reddened
# `test_text_only_path_fires_emotes_immediately`, which asserts there is no
# speaker sink. A test that flips with an unrelated asset download is not
# testing what it says.
speech:
  mode: text
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


def _audio() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="test",
    )


def test_runtime_admits_only_the_curated_emote_catalog(tmp_path: Path) -> None:
    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        catalog = runtime._emote_catalog
        assert "play_bow" in catalog and "paw_wave" in catalog
        # Locomotion and postural skills are deliberately excluded.
        assert "trot" not in catalog and "walk_forward" not in catalog
        assert "sit" not in catalog and "lie_down" not in catalog
        assert runtime.brain_registry.gesture_names == frozenset(catalog)
    finally:
        runtime.close()


def test_runtime_rejects_a_configured_emote_that_is_not_bounded(tmp_path: Path) -> None:
    config = _config(tmp_path, emotes="    emotes: [trot]\n")
    with pytest.raises(ValueError, match="must be bounded"):
        RobotRuntime(config, _Backend(), audio_status=_audio())


def test_runtime_rejects_an_unknown_configured_emote(tmp_path: Path) -> None:
    config = _config(tmp_path, emotes="    emotes: [backflip]\n")
    with pytest.raises(ValueError, match="unknown emote skill"):
        RobotRuntime(config, _Backend(), audio_status=_audio())


def test_runtime_gesture_dispatch_goes_through_the_proposal_arbiter(
    tmp_path: Path,
) -> None:
    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        detail = runtime._brain_gesture("paw_wave", 1.2)
        assert "Accepted" in detail or "Deferred" in detail
        running = runtime.activities.snapshot()
        names = [
            record["name"]
            for record in ([running["running"]] if running["running"] else [])
            + list(running["pending"])
        ]
        assert "paw_wave" in names
        # The unadmitted and the out-of-range both fail closed.
        with pytest.raises(ValueError, match="unknown emote"):
            runtime._brain_gesture("backflip", 1.0)
        with pytest.raises(ValueError, match="intensity"):
            runtime._brain_gesture("paw_wave", 9.0)
    finally:
        runtime.close()


# --- card W8: emotes ride the playback clock --------------------------------


class _CapturingSink:
    """Stands in for ``SpeakerSink`` without opening an audio device."""

    def __init__(self) -> None:
        self.queued: list[tuple[bytes, object]] = []

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        self.queued.append((chunk, token))

    def close(self, timeout: float = 3.0) -> None:
        pass


def _pending_activities(runtime: RobotRuntime) -> list[str]:
    snapshot = runtime.activities.snapshot()
    running = [snapshot["running"]] if snapshot["running"] else []
    return [str(record["name"]) for record in running + list(snapshot["pending"])]


def test_emote_fires_at_playback_start_not_at_synthesis(tmp_path: Path) -> None:
    """U6: with a deep queue, synthesis time is seconds ahead of the words."""

    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        sink = _CapturingSink()
        runtime._speaker_sink = sink
        chunked = SentenceChunkedSynthesizer(_EchoSynth())
        for chunk in chunked.synthesize_stream("[emote:paw_wave] Hello there."):
            runtime._enqueue_speech_chunk(chunk)

        assert sink.queued, "chunk was never queued"
        assert _pending_activities(runtime) == [], "emote fired at synthesis time"
        token = sink.queued[0][1]
        assert token == (None, runtime.expression.speech_epoch, (("paw_wave", 1.0),))

        runtime._audio_chunk_started(token)
        assert "paw_wave" in _pending_activities(runtime)
    finally:
        runtime.close()


def test_superseded_sentence_fires_no_emote(tmp_path: Path) -> None:
    """Barge-in supersedes the epoch, so pending gestures die with their audio."""

    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        sink = _CapturingSink()
        runtime._speaker_sink = sink
        chunked = SentenceChunkedSynthesizer(_EchoSynth())
        for chunk in chunked.synthesize_stream("Sure. [emote:play_bow] Here you go."):
            runtime._enqueue_speech_chunk(chunk)
        token = next(item for _chunk, item in sink.queued if item is not None)

        runtime.expression.supersede_speech()
        runtime._audio_chunk_started(token)
        assert _pending_activities(runtime) == []
    finally:
        runtime.close()


def test_text_only_path_fires_emotes_immediately(tmp_path: Path) -> None:
    """No synthesizer means no playback clock to anchor to — documented in
    ``_fire_text_mode_emotes``."""

    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        assert runtime._speaker_sink is None
        runtime._voice_turn_completed(
            VoiceTurn(1, "hello", "Hello! [emote:paw_wave]", False)
        )
        assert "paw_wave" in _pending_activities(runtime)
    finally:
        runtime.close()


def test_a_superseded_text_reply_fires_no_emote(tmp_path: Path) -> None:
    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        runtime._voice_turn_completed(
            VoiceTurn(1, "hello", "Hello! [emote:paw_wave]", True)
        )
        assert _pending_activities(runtime) == []
    finally:
        runtime.close()


def test_playback_start_survives_an_inadmissible_emote(tmp_path: Path) -> None:
    """Speech and nods must never fail because a gesture could not run."""

    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        runtime._audio_chunk_started(
            (None, runtime.expression.speech_epoch, (("backflip", 1.0),))
        )
        warnings = [
            event
            for event in runtime.snapshot()["events"]
            if "backflip" in str(event.get("text", ""))
        ]
        assert warnings, "an unknown emote was dropped silently"
        assert _pending_activities(runtime) == []
    finally:
        runtime.close()


def test_runtime_prompt_exposes_the_emote_policy(tmp_path: Path) -> None:
    runtime = RobotRuntime(_config(tmp_path), _Backend(), audio_status=_audio())
    try:
        prompt = runtime._render_system_prompt()
        assert "[emote:" in prompt
        assert "play_bow" in prompt
        sources = runtime.prompt_inspection()["registered_sources"]
        assert "emote_policy" in sources
    finally:
        runtime.close()
