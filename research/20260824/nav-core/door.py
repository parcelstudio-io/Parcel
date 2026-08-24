"""The real door: a transcript becomes a validated ``NavigateTo``, or a refusal.

The DESIGN says the corpus goes through the product door, not through
synthetic goals, so this builds one ``RobotRuntime`` in text mode and asks it
``navigate_to`` for every episode.  That is the hosted rail —
``realtime_broker.handle`` -> ``_place_admission`` -> ``intent_router.route``
-> ``sketch_navigate`` -> ``_admit_local_sketch`` -> ``_accept_plan`` — and
it is the same ``_place_admission`` the typed panel asks, so nothing here is a
lane the product does not have.

The runtime is built once and reused: under the ``learned_map`` source its
whole place vocabulary comes from the process-installed map
(``runtime._learned_map_vocabulary``), so swapping the map is enough to ask the
door a different question.  Refuter 4's map, the one missing the goal place, is
therefore answered by the door itself rather than by anything in this folder.

The runtime never drives the body.  Its backend is inert; the room, the pose
stack and the arms live in ``arms.py``.  What the door produces is the
admission verdict and the validated directive text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class DoorVerdict:
    """What the product door said about one transcript."""

    transcript: str
    status: str
    detail: str
    route_rule: str
    admitted: bool
    directive: str


class _InertBackend:
    """A backend that observes nothing and moves nothing."""

    name = "navcore_inert"

    def observe(self) -> Any:
        import time

        from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation

        # A fresh monotonic stamp: the planning-context snapshot derives a
        # sensor age from it, and a zero stamp reads as an hour-old sensor and
        # fails admission with "sensor age must be between 0.0 and 3600000.0".
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(x=0.0, y=0.0, z=0.0, yaw=0.0),
            owner=OwnerTrack(x=60.0, y=60.0),
            backend=self.name,
        )

    def move(self, command: Any) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: Any) -> None:
        del pose

    def trajectory(self, skill: Any) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript: str, tools: Any, context: Any) -> Any:
        from parcel_robot.models import AgentDecision

        del tools, context
        return AgentDecision(f"Understood: {transcript}")


def build_runtime(scratch: Path) -> Any:
    """One text-mode runtime.  No credential, no audio, no hosted call."""

    import os

    from parcel_robot.audio.devices import AudioDeviceStatus
    from parcel_robot.realtime.config import REALTIME_CONFIG_ENV
    from parcel_robot.runtime import RobotRuntime

    scratch.mkdir(parents=True, exist_ok=True)
    realtime = scratch / "realtime.yaml"
    realtime.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    os.environ[REALTIME_CONFIG_ENV] = str(realtime)
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("PARCEL_REALTIME_KEY_ENV", None)
    config = scratch / "navcore_runtime.yaml"
    config.write_text(
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
    runtime = RobotRuntime(
        config,
        _InertBackend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="navcore",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="NAV-CORE door",
        ),
    )
    runtime._observation = runtime.backend.observe()
    return runtime


def ask(runtime: Any, place: str) -> DoorVerdict:
    """Push one transcript through ``navigate_to`` and read the verdict."""

    from parcel_robot.realtime.tool_broker import NAVIGATE_DIRECTIVE_TEMPLATE

    runtime._observation = runtime.backend.observe()
    raw = runtime.realtime_broker.handle(
        name="navigate_to", call_id="navcore", arguments=json.dumps({"place": place})
    )
    payload = json.loads(raw)
    route = runtime.realtime_snapshot().get("last_route") or {}
    status = str(payload.get("status", ""))
    return DoorVerdict(
        transcript=NAVIGATE_DIRECTIVE_TEMPLATE.format(place=place),
        status=status,
        detail=str(payload.get("detail", "")),
        route_rule=str(route.get("rule", "")),
        admitted=status == "ok",
        directive=NAVIGATE_DIRECTIVE_TEMPLATE.format(place=place),
    )
