"""Localization LOST at the runtime seam: a hold the owner is told about.

Lane B (B-3) made ``LOST`` stop the body without failing the mission — the goal
is still valid and health can return — and made walk_with_me surface it through
the existing failure machinery. Two things were left undone, and both were
measured here on the product path before they were fixed:

1. **The runtime treated the hold as a terminal failure.**
   ``_pose_lost_hold`` returns ``MidLevelCommand(stop=True,
   note="pose_lost_hold")`` with the mission left *running*. That fell into
   ``_step_navigation``'s generic ``command.stop`` arm, which cleared
   ``_navigation_directive``, published ``enabled=False``, restored the
   directive pace, cancelled the lease and emitted *"Navigation failed for
   sidewalk: pose_lost_hold"*. So the runtime destroyed the mission the
   navigator had deliberately kept alive, and it could never resume.

2. **Nobody told the owner.** Lane B's hand-off 2: the reply text existed on
   the walk_with_me trace sample, unspoken.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.models import MidLevelCommand
from parcel_robot.runtime import (
    POSE_LOST_HOLD_NOTE,
    POSE_LOST_UTTERANCE,
    POSE_REGAINED_UTTERANCE,
    RobotRuntime,
)

REPO = Path(__file__).resolve().parents[1]


class _Backend:
    name = "pose-health-test"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(owner_id="owner-test", x=3.0, y=0.0, visible=True, confidence=1.0),
            backend=self.name,
        )
        self.moves: list[VelocityCommand] = []
        self.stop_count = 0

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        self.stop_count += 1

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill


@pytest.fixture()
def runtime(tmp_path: Path):
    path = tmp_path / "robot-pose-health.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
  config: {REPO / "configs" / "navigation" / "default.yaml"}
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    audio_status = AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )
    backend = _Backend()
    session = RobotRuntime(path, backend, audio_status=audio_status)
    observation = backend.observe()
    session._observation = observation
    if session._control_state_source is not None:
        session._control_state_source.update_observation(observation)
    try:
        yield session
    finally:
        session.close()


def _lose_localization(runtime: RobotRuntime):
    """Substitute exactly what ``_pose_lost_hold`` returns, nothing more.

    The drift pose provider that can actually reach ``LOST`` is a navigation
    config concern; what is under test here is the runtime's response to the
    command the navigator emits, so that command is what is injected.
    """

    healthy = runtime.dog.navigate

    def held(directive: str, **kwargs: object):
        mission, _command = healthy(directive, **kwargs)
        mission.metadata["pose_health"] = "lost"
        mission.metadata["resolution_state"] = "pose_lost"
        return mission, MidLevelCommand(stop=True, note=POSE_LOST_HOLD_NOTE)

    runtime.dog.navigate = held
    return healthy


def _chat(runtime: RobotRuntime) -> list[str]:
    return [str(item["text"]) for item in (runtime.snapshot().get("chat") or [])]


def _start(runtime: RobotRuntime) -> None:
    reply = runtime.handle_text("go to the sidewalk")
    assert "couldn't admit" not in reply, reply
    runtime._step_brain()
    runtime._step_navigation(runtime._observation)
    assert runtime.snapshot()["navigation"]["enabled"] is True


def test_a_localization_hold_does_not_end_the_mission(runtime: RobotRuntime) -> None:
    _start(runtime)
    _lose_localization(runtime)
    for _ in range(3):
        runtime._step_navigation(runtime._observation)

    navigation = runtime.snapshot()["navigation"]
    assert navigation["reason"] == POSE_LOST_HOLD_NOTE
    assert navigation["enabled"] is True, "the channel still owns the mission"
    assert navigation["state"] == "waiting"
    assert runtime._navigation_directive == "go to the sidewalk"


def test_the_hold_is_not_reported_as_a_navigation_failure(runtime: RobotRuntime) -> None:
    """The old behaviour said the mission failed. It had not."""

    _start(runtime)
    _lose_localization(runtime)
    runtime._step_navigation(runtime._observation)

    failures = [
        item
        for item in runtime.snapshot()["events"]
        if item["level"] == "error" and "Navigation failed" in str(item["text"])
    ]
    assert failures == []


def test_the_plan_step_stays_in_progress_through_the_hold(runtime: RobotRuntime) -> None:
    """A hold must not fail the step that authorized the drive."""

    _start(runtime)
    _lose_localization(runtime)
    for _ in range(2):
        runtime._step_navigation(runtime._observation)
        runtime._step_brain()

    (task,) = runtime.task_executive.snapshot()["tasks"]
    assert task["state"] == "running", task


def test_the_owner_is_told_once_and_only_once(runtime: RobotRuntime) -> None:
    """Lane B hand-off 2. Edge-triggered: the hold fires every control tick."""

    _start(runtime)
    _lose_localization(runtime)
    for _ in range(5):
        runtime._step_navigation(runtime._observation)

    assert _chat(runtime).count(POSE_LOST_UTTERANCE) == 1


def test_recovery_is_announced_only_once_the_robot_is_driving_again(
    runtime: RobotRuntime,
) -> None:
    """The recovery line cannot outrun the fact it reports.

    It is reachable only from a tick on which the navigator issued a non-stop
    command, and ``_pose_lost_hold`` stops on every tick while health is
    ``LOST`` — so "I know where I am again" implies health returned.
    """

    _start(runtime)
    healthy = _lose_localization(runtime)
    for _ in range(3):
        runtime._step_navigation(runtime._observation)
    assert POSE_REGAINED_UTTERANCE not in _chat(runtime)

    runtime.dog.navigate = healthy
    for _ in range(3):
        runtime._step_navigation(runtime._observation)

    chat = _chat(runtime)
    assert chat.count(POSE_REGAINED_UTTERANCE) == 1
    assert chat.index(POSE_LOST_UTTERANCE) < chat.index(POSE_REGAINED_UTTERANCE)
    assert runtime.snapshot()["navigation"]["state"] != "waiting"


def test_nothing_is_announced_when_localization_never_drops(runtime: RobotRuntime) -> None:
    """No unsolicited localization chatter on a healthy run."""

    _start(runtime)
    for _ in range(4):
        runtime._step_navigation(runtime._observation)

    chat = _chat(runtime)
    assert POSE_LOST_UTTERANCE not in chat
    assert POSE_REGAINED_UTTERANCE not in chat
