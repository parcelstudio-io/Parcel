"""Card R1.6+R3 §E: the proof — the voice model moves the simulated dog.

WHAT THIS IS
------------
The owner's second directive, literally: *"The robot dog must ACTUALLY perform
gestures/poses (and bounded navigation) when the voice model proposes them."*
Everything else in this card is offline and fake-first. This file is the one
test that spends money, and it is the only place the whole arrow is real at
once:

    a typed sentence
      → the hosted gpt-realtime-2.1-mini session (real socket, real tokens)
      → the model proposes a tool call
      → ToolCall + SafetySupervisor.validate
      → the runtime's own doors (ActivityCoordinator / router → sketch admission)
      → a MuJoCo city world that actually steps
      → function_call_output back up, so the model narrates what really happened

DOUBLE-GATED, THE SAME WAY R1.5's LIVE TEST IS
----------------------------------------------
``pytest.mark.slow`` keeps it out of the commit tier (which runs
``-m "not slow"``), and two ``skipif``s keep it out of the nightly slow tier
unless an operator has BOTH opted in with ``PARCEL_REALTIME_LIVE=1`` and put a
credential in the environment. CI never needs a key; a machine without one
never goes red. The credential is read BY NAME and is never printed, asserted
against, or written anywhere.

WHAT IT DELIBERATELY DOES NOT ASSERT
------------------------------------
Arrival. The card says "mission state, not arrival" — grounding a semantic goal
and walking to it is a navigation-stack property with its own eval suite, and
hanging a paid test on it would be measuring the wrong thing. What is asserted
is that the mission was ADMITTED through the same sketch path a typed sentence
takes, and that the gesture actually left the coordinator and reached the dog.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import SimObservation
from parcel_robot.models import VelocityCommand
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV
from parcel_robot.realtime.cost import realtime_usage_totals
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]

LIVE_ENV = "PARCEL_REALTIME_LIVE"
KEY_ENV = os.environ.get("PARCEL_REALTIME_KEY_ENV", "").strip() or "OPENAI_API_KEY"
LIVE_MODEL = os.environ.get("PARCEL_REALTIME_MODEL", "").strip() or "gpt-realtime-2.1-mini"

#: Where the evidence pack is written for the status doc. Never in the repo by
#: default — the operator points it at a scratchpad.
EVIDENCE_ENV = "PARCEL_REALTIME_SMOKE_OUT"

#: Generous: this is a real network and a real model deciding to call a tool.
TURN_TIMEOUT_S = 60.0

LIVE = os.environ.get(LIVE_ENV, "").strip() == "1"
HAVE_KEY = bool(os.environ.get(KEY_ENV, "").strip())

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not LIVE, reason=f"live realtime smoke is opt-in: set {LIVE_ENV}=1"),
    pytest.mark.skipif(not HAVE_KEY, reason=f"no credential in ${KEY_ENV}"),
]

GESTURE_PROMPT = "Wave at me please."
NAVIGATE_PROMPT = "Go to the sidewalk."

#: Plain prose, no YAML profile. The owner's own example.
PERSONA = "You are a lively conversational agent that likes to go around New York."


class _MujocoCityBackend:
    """The headless MuJoCo city, presented as a ``SimulatorBackend``.

    Real geometry, real LiDAR, real semantic regions (which is what makes "the
    sidewalk" a place this robot can be asked about), and the base actually
    moves when the navigator commands it.

    One honest substitution, called out because an auditor will look for it:
    ``timestamp`` is re-stamped from ``time.monotonic()``. The world's own clock
    is MuJoCo sim time starting at zero, while the runtime's staleness gate
    compares observation timestamps against the wall-monotonic clock — feeding
    it sim time would make every observation look hours stale and refuse every
    mission for a reason that has nothing to do with this card. Joint-level
    ``pose``/``trajectory`` are recorded rather than simulated: this world is a
    kinematic base rig, so what a dispatched gesture proves here is that it left
    the coordinator and reached the dog, not that a leg moved.
    """

    name = "headless_mujoco_city"

    def __init__(self) -> None:
        from parcel_robot.simulation.headless_city import HeadlessCityWorld

        self.world = HeadlessCityWorld()
        self.poses: list[object] = []
        self.trajectories: list[object] = []
        self.commands: list[VelocityCommand] = []

    def observe(self) -> SimObservation:
        return replace(self.world.step(), timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        self.commands.append(command)
        self.world.apply(command)

    def stop(self) -> None:
        self.world.apply(VelocityCommand())

    def emergency_stop(self) -> None:
        self.world.apply(VelocityCommand())

    def pose(self, pose: object) -> None:
        self.poses.append(pose)

    def trajectory(self, skill: object) -> None:
        self.trajectories.append(skill)

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


def _runtime(tmp_path: Path, backend: _MujocoCityBackend) -> RobotRuntime:
    path = tmp_path / "live-smoke.yaml"
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
    return RobotRuntime(
        path,
        backend,
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="live-smoke",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="no audio hardware on this host",
        ),
    )


def _settle(lane, *, quiet_s: float = 3.0, timeout_s: float = 30.0) -> None:
    """Wait until the provider has stopped producing responses for a moment."""

    deadline = time.monotonic() + timeout_s
    last = len(lane.usage_rows)
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        if len(lane.usage_rows) != last:
            last = len(lane.usage_rows)
            stable_since = time.monotonic()
        elif time.monotonic() - stable_since >= quiet_s:
            return
        time.sleep(0.1)


def _wait_for(predicate, *, timeout_s: float = TURN_TIMEOUT_S, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out after {timeout_s:.0f}s waiting for {what}")


def test_the_voice_model_gestures_and_admits_a_mission_on_the_sim_dog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "realtime.yaml"
    # A FREE-TEXT persona, exercised end to end (owner directive 2026-08-18):
    # the words below are the only personality this session ever sees, and the
    # SI digest they produce is recorded in the evidence pack.
    config.write_text(
        "enabled: true\n"
        "mode: text\n"
        f"model: {LIVE_MODEL}\n"
        f'persona: "{PERSONA}"\n'
        "monthly_budget_usd: 5.0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))

    backend = _MujocoCityBackend()
    runtime = _runtime(tmp_path, backend)
    evidence: dict[str, object] = {"model": LIVE_MODEL, "persona": PERSONA}
    try:
        assert runtime.realtime_lane is not None, "the lane did not construct"
        assert runtime.realtime_broker is not None, "the broker did not construct"
        source = runtime.realtime_instructions
        assert source is not None
        rendered = source.current()
        assert PERSONA in rendered.si.text, "the free-text persona never reached the SI"
        evidence["prompt_provenance"] = rendered.provenance()
        runtime.bind_panel_token("live-smoke-token")
        runtime.start()
        broker = runtime.realtime_broker

        # ---------------------------------------------------------- gesture
        runtime.submit_realtime_text(GESTURE_PROMPT)
        _wait_for(
            lambda: any(row["tool"] == "play_gesture" for row in broker.calls),
            what="the model to propose play_gesture",
        )
        gesture_call = next(row for row in broker.calls if row["tool"] == "play_gesture")
        assert gesture_call["status"] in {"ok", "deferred"}, gesture_call
        _wait_for(
            lambda: bool(backend.trajectories or backend.poses),
            timeout_s=20.0,
            what="the gesture to reach the dog",
        )
        gesture_events = [
            event
            for event in runtime.snapshot()["events"]
            if "Executing" in str(event.get("text", ""))
        ]
        evidence["gesture"] = {
            "prompt": GESTURE_PROMPT,
            "call": gesture_call,
            "activity_events": [str(event.get("text")) for event in gesture_events],
            "dispatched_to_backend": len(backend.trajectories) + len(backend.poses),
        }
        assert gesture_events, "no activity actually executed on the dog"

        # ------------------------------------------------------- navigation
        # Let the gesture turn finish first. ``send_text`` issues its own
        # ``response.create``, and the provider refuses a second one while a
        # response is still in flight — which would look exactly like "the
        # model chose not to call the tool" and would be the wrong diagnosis.
        _settle(runtime.realtime_lane)
        runtime.submit_realtime_text(NAVIGATE_PROMPT)
        _wait_for(
            lambda: any(row["tool"] == "navigate_to" for row in broker.calls),
            what="the model to propose navigate_to",
        )
        navigate_call = next(row for row in broker.calls if row["tool"] == "navigate_to")
        assert navigate_call["status"] == "ok", navigate_call
        route = runtime.realtime_snapshot()["last_route"]
        assert route["route"] == "direct_skill"
        assert route["rule"] == "navigation_directive", "the ROUTER admitted this, not the model"
        tasks = runtime.task_executive.snapshot()["tasks"]
        assert tasks, "no navigation mission reached the task executive"
        evidence["navigation"] = {
            "prompt": NAVIGATE_PROMPT,
            "call": navigate_call,
            "route": route,
            "tasks": tasks,
            "navigation_detail": runtime.snapshot()["navigation"],
        }

        # ------------------------------------------------------------ record
        lane = runtime.realtime_lane
        evidence["ledger"] = [
            {"speaker": row["speaker"], "content": row["content"]}
            for row in runtime.agent.memory.realtime_turns()
        ]
        evidence["usage"] = realtime_usage_totals(lane.usage_rows)
        evidence["broker"] = broker.snapshot()
        evidence["lane"] = lane.snapshot()
        assert lane.protocol_errors == [], f"the codec refused live frames: {lane.protocol_errors}"
        speakers = {row["speaker"] for row in runtime.agent.memory.realtime_turns()}
        assert {"owner", "robot"} <= speakers, "both sides of the conversation must be ledgered"
    finally:
        lane = runtime.realtime_lane
        if lane is not None:
            evidence.setdefault(
                "server_errors",
                [{"code": error.code, "message": error.message} for error in lane.server_errors],
            )
            evidence.setdefault("lane_events", list(lane.events))
            evidence.setdefault("usage", realtime_usage_totals(lane.usage_rows))
            evidence.setdefault(
                "ledger",
                [
                    {"speaker": row["speaker"], "content": row["content"]}
                    for row in runtime.agent.memory.realtime_turns()
                ],
            )
            if runtime.realtime_broker is not None:
                evidence.setdefault("broker_calls", list(runtime.realtime_broker.calls))
        destination = os.environ.get(EVIDENCE_ENV, "").strip()
        if destination:
            Path(destination).write_text(json.dumps(evidence, indent=2, default=str), "utf-8")
        runtime.close()
