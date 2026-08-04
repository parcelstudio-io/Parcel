"""Closed-loop FOLLOW_BENCH_V1 episode driver over :class:`HeadlessCityWorld`.

Follow episodes replicate the production runtime loop exactly (observe ->
``FollowOwnerController.observe_owner`` -> ``step`` -> the shared
``apply_reactive_safety`` actuator gate); navigate episodes replicate the
headless quality-harness navigation loop around ``DirectiveNavigator`` with
``model_id="grid_v1"``. Scripted owner and pedestrian motion is written into
the scene's mocap bodies each 0.1 s control step, so pedestrians are real
capsules for the raycast scan and the owner line-of-sight ray while remaining
outside the analytic nearest-obstacle telemetry and the static-collision truth
oracle (that limitation is documented loudly in results/README.md).
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import mujoco
import numpy as np

from evals.companion_nav.metrics import EpisodeResult, StepRecord
from evals.companion_nav.scenarios import (
    CONTROL_DT_S,
    Scenario,
    interpolate_position,
    interpolate_velocity,
)
from parcel_robot.backends.base import DynamicAgentTrack, SimObservation
from parcel_robot.config import ConfigStore
from parcel_robot.dynamic_city import select_social_collision_candidate

# Production-parity helpers are imported (not forked) from the headless rig so
# this eval cannot drift from the observation contract the runtime harness
# uses; they are module-private there but stable and covered by its tests.
from parcel_robot.headless_city import (
    DEFAULT_ROBOT_CONFIG,
    HeadlessCityWorld,
    _nav_observation,
    _navigation_config_from_store,
    _reactive_safety_from_store,
    _spatial_config_from_store,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.follow import FollowConfig, FollowOwnerController
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import apply_reactive_safety

RUNNER_VERSION = "follow-bench-v1.0"
GRID_MODEL_ID = "grid_v1"
# Owner-visibility ray height: torso height of the owner capsule, deliberately
# above the robot silhouette so the ray never self-returns.
LINE_OF_SIGHT_HEIGHT_M = 1.0
# Slack for rays that hit the owner capsule surface instead of its axis.
LINE_OF_SIGHT_SLACK_M = 0.45
# Scene mocap actors available for scripted pedestrians, in assignment order.
ACTOR_BODY_NAMES = tuple(f"pedestrian_{index}" for index in range(1, 8)) + ("cyclist_1",)
# Far outside the 30 m scan range from anywhere on the 20x20 m block.
PARKED_ACTOR_POSITION = (60.0, 60.0)


class FollowBenchRunner:
    """Deterministic scenario executor configured from ``configs/robot.yaml``."""

    def __init__(self, robot_config: str | Path = DEFAULT_ROBOT_CONFIG):
        store = ConfigStore(robot_config)
        spatial = _spatial_config_from_store(store)
        self.reactive_safety = _reactive_safety_from_store(store, spatial)
        self.navigation_config = _navigation_config_from_store(store)
        self.follow_config = _follow_config_from_store(store, spatial)
        control = store.section("control")
        self._settled_linear_speed_mps = float(
            control.get("settled_linear_speed_mps", 0.08)
        )
        self._settled_yaw_speed_rad_s = float(
            control.get("settled_yaw_speed_rad_s", 0.12)
        )
        if any(
            not math.isfinite(value) or value < 0.0
            for value in (self._settled_linear_speed_mps, self._settled_yaw_speed_rad_s)
        ):
            raise ValueError("settled-speed thresholds must be finite and nonnegative")

    def run(self, scenario: Scenario) -> EpisodeResult:
        # A fresh world per episode keeps every scenario deterministic
        # regardless of suite order; the scan RNG is reseeded from the scenario
        # seed (eval-only access to a private field, so scan noise/dropout is a
        # scenario property rather than a run-order property).
        world = HeadlessCityWorld()
        world._scan_rng = np.random.default_rng(int(scenario.seed))
        world.reset(
            robot=scenario.robot_start,
            owner=interpolate_position(scenario.owner_waypoints, 0.0),
        )
        rig = _ActorRig(world, scenario)
        if scenario.directive_kind == "follow":
            return self._run_follow(world, rig, scenario)
        return self._run_navigate(world, rig, scenario)

    def _run_follow(
        self, world: HeadlessCityWorld, rig: _ActorRig, scenario: Scenario
    ) -> EpisodeResult:
        follow = FollowOwnerController(
            self.follow_config, safety_policy=self.reactive_safety
        )
        follow.start("direct")
        steps: list[StepRecord] = []
        try:
            for _ in range(scenario.control_steps):
                now = float(world.data.time)
                rig.apply(now)
                observation = self._observe(world, rig, now)
                # Production order (runtime.py): passive owner-track update,
                # then the follow decision, then the shared actuator gate.
                follow.observe_owner(observation, now=now)
                decision = follow.step(observation, now=now)
                command, safety_state = apply_reactive_safety(
                    decision.command,
                    observation,
                    policy=self.reactive_safety,
                    now=now,
                )
                steps.append(
                    _record(
                        world,
                        rig,
                        observation,
                        command,
                        state=decision.state,
                        note=f"{decision.reason}|{safety_state}",
                    )
                )
                world.apply(command)
                world.step()
        finally:
            world.stop()
            follow.stop()
        return self._result(
            world, scenario, steps, status="completed", reason="duration_elapsed"
        )

    def _run_navigate(
        self, world: HeadlessCityWorld, rig: _ActorRig, scenario: Scenario
    ) -> EpisodeResult:
        navigator = DirectiveNavigator.from_config(
            self.navigation_config, model_id=GRID_MODEL_ID
        )
        mission = navigator.start(scenario.directive)
        steps: list[StepRecord] = []
        reason = "navigation_step_limit"
        status = mission.status
        try:
            for _ in range(scenario.control_steps):
                now = float(world.data.time)
                rig.apply(now)
                observation = self._observe(world, rig, now)
                command = navigator.step(
                    _nav_observation(
                        observation,
                        measured_velocity=world.command,
                        stop_confirmed=world.stopped,
                        settled_linear_speed_mps=self._settled_linear_speed_mps,
                        settled_yaw_speed_rad_s=self._settled_yaw_speed_rad_s,
                    )
                )
                requested = (
                    VelocityCommand()
                    if command.stop
                    else VelocityCommand(command.vx, command.vy, command.vyaw)
                )
                velocity, _ = apply_reactive_safety(
                    requested,
                    observation,
                    policy=self.reactive_safety,
                    owner_orbit=False,
                    orbit_radius_m=0.0,
                    now=observation.timestamp,
                    require_fresh_telemetry=False,
                )
                steps.append(
                    _record(
                        world,
                        rig,
                        observation,
                        velocity,
                        state=mission.status,
                        note=command.note,
                    )
                )
                world.apply(velocity)
                if (command.stop and mission.status != "verifying") or navigator.done():
                    reason = command.note
                    status = mission.status
                    break
                world.step()
            else:
                mission.status = "failed"
                status = "timed_out"
        finally:
            world.stop()
            navigator.close()
        return self._result(world, scenario, steps, status=status, reason=reason)

    def _observe(
        self, world: HeadlessCityWorld, rig: _ActorRig, now: float
    ) -> SimObservation:
        raw = world.observe()
        owner = replace(
            raw.owner, visible=_owner_line_of_sight(world.model, world.data, raw)
        )
        tracks = rig.pedestrian_tracks(now)
        agents = tuple(
            DynamicAgentTrack(
                agent_id=str(track["agent_id"]),
                kind="pedestrian",
                x=float(track["x"]),
                y=float(track["y"]),
                vx=float(track["vx"]),
                vy=float(track["vy"]),
                radius_m=float(track["radius_m"]),
                yaw=(
                    math.atan2(float(track["vy"]), float(track["vx"]))
                    if math.hypot(float(track["vx"]), float(track["vy"])) > 1e-9
                    else 0.0
                ),
                confidence=1.0,
            )
            for track in tracks
        )
        cosine, sine = math.cos(raw.robot.yaw), math.sin(raw.robot.yaw)
        candidate = select_social_collision_candidate(
            tracks,
            robot_x=raw.robot.x,
            robot_y=raw.robot.y,
            robot_heading_rad=raw.robot.yaw,
            robot_vx=cosine * world.command.vx - sine * world.command.vy,
            robot_vy=sine * world.command.vx + cosine * world.command.vy,
            robot_radius_m=world.robot_radius_m,
        )
        ttc = candidate.get("time_to_collision_s") if candidate else None
        return replace(
            raw,
            owner=owner,
            dynamic_agents=agents,
            nearest_person_m=(
                float(candidate["distance_m"]) if candidate is not None else None
            ),
            nearest_person_bearing_rad=(
                float(candidate["bearing_rad"]) if candidate is not None else None
            ),
            nearest_person_id=(
                str(candidate["agent_id"]) if candidate is not None else None
            ),
            nearest_person_ttc_s=float(ttc) if ttc is not None else None,
        )

    def _result(
        self,
        world: HeadlessCityWorld,
        scenario: Scenario,
        steps: list[StepRecord],
        *,
        status: str,
        reason: str,
    ) -> EpisodeResult:
        return EpisodeResult(
            scenario_id=scenario.scenario_id,
            directive_kind=scenario.directive_kind,
            control_dt_s=CONTROL_DT_S,
            steps=tuple(steps),
            status=status,
            reason=reason,
            static_collision_count=world.collision_count,
            minimum_static_clearance_m=world.minimum_clearance_m,
        )


class _ActorRig:
    """Owns owner/pedestrian mocap bodies for one scripted episode."""

    def __init__(self, world: HeadlessCityWorld, scenario: Scenario):
        self._world = world
        self._scenario = scenario
        self._owner_mocap_id = _mocap_id(world.model, "owner")
        if self._owner_mocap_id < 0:
            raise ValueError("city scene must provide an 'owner' mocap body")
        actor_ids = [
            mocap_id
            for name in ACTOR_BODY_NAMES
            if (mocap_id := _mocap_id(world.model, name)) >= 0
        ]
        if len(scenario.pedestrians) > len(actor_ids):
            raise ValueError(
                "scenario requires more scripted pedestrians than the scene provides"
            )
        # Park every city actor far outside sensor range, then assign the
        # scripted pedestrians to the first bodies so unused extras cannot
        # appear as phantom people in the raycast scan.
        for mocap_id in actor_ids:
            world.data.mocap_pos[mocap_id, :2] = PARKED_ACTOR_POSITION
        self._pedestrian_mocap_ids = tuple(actor_ids[: len(scenario.pedestrians)])
        self.apply(0.0)

    def apply(self, time_s: float) -> None:
        """Advance scripted actors kinematically and refresh derived poses."""

        world = self._world
        owner = interpolate_position(self._scenario.owner_waypoints, time_s)
        world.data.mocap_pos[self._owner_mocap_id, :2] = owner
        for script, mocap_id in zip(
            self._scenario.pedestrians, self._pedestrian_mocap_ids
        ):
            world.data.mocap_pos[mocap_id, :2] = interpolate_position(
                script.waypoints, time_s
            )
        mujoco.mj_forward(world.model, world.data)

    def pedestrian_tracks(self, time_s: float) -> list[dict[str, object]]:
        tracks: list[dict[str, object]] = []
        for script in self._scenario.pedestrians:
            x, y = interpolate_position(script.waypoints, time_s)
            vx, vy = interpolate_velocity(script.waypoints, time_s)
            tracks.append(
                {
                    "agent_id": script.agent_id,
                    "kind": "pedestrian",
                    "x": x,
                    "y": y,
                    "vx": vx,
                    "vy": vy,
                    "radius_m": script.radius_m,
                }
            )
        return tracks

    def nearest_pedestrian(
        self, time_s: float, robot_x: float, robot_y: float
    ) -> tuple[float | None, float | None]:
        """(center distance, surface separation) to the closest scripted pedestrian."""

        center: float | None = None
        surface: float | None = None
        for script in self._scenario.pedestrians:
            x, y = interpolate_position(script.waypoints, time_s)
            distance = math.hypot(x - robot_x, y - robot_y)
            separation = distance - script.radius_m - self._world.robot_radius_m
            if center is None or distance < center:
                center = distance
            if surface is None or separation < surface:
                surface = separation
        return center, surface


def _record(
    world: HeadlessCityWorld,
    rig: _ActorRig,
    observation: SimObservation,
    command: VelocityCommand,
    *,
    state: str,
    note: str,
) -> StepRecord:
    center, surface = rig.nearest_pedestrian(
        observation.timestamp, observation.robot.x, observation.robot.y
    )
    return StepRecord(
        time_s=observation.timestamp,
        robot_x=observation.robot.x,
        robot_y=observation.robot.y,
        robot_yaw=observation.robot.yaw,
        owner_x=observation.owner.x,
        owner_y=observation.owner.y,
        owner_visible=observation.owner.visible,
        owner_distance_m=math.hypot(
            observation.owner.x - observation.robot.x,
            observation.owner.y - observation.robot.y,
        ),
        command_vx=command.vx,
        command_vy=command.vy,
        command_vyaw=command.vyaw,
        state=state,
        note=note,
        nearest_pedestrian_center_m=center,
        nearest_pedestrian_surface_m=surface,
        cumulative_static_collisions=world.collision_count,
    )


def _owner_line_of_sight(
    model: mujoco.MjModel, data: mujoco.MjData, observation: SimObservation
) -> bool:
    """True when a torso-height ray from the robot reaches the owner first."""

    dx = observation.owner.x - observation.robot.x
    dy = observation.owner.y - observation.robot.y
    distance = math.hypot(dx, dy)
    if distance <= 1e-6:
        return True
    origin = np.array(
        [observation.robot.x, observation.robot.y, LINE_OF_SIGHT_HEIGHT_M],
        dtype=np.float64,
    )
    direction = np.array([dx / distance, dy / distance, 0.0], dtype=np.float64)
    geom_id = np.full(1, -1, dtype=np.int32)
    hit_distance = mujoco.mj_ray(model, data, origin, direction, None, 1, -1, geom_id)
    if geom_id[0] < 0:
        return True
    name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, int(geom_id[0])) or ""
    if name.startswith("owner_"):
        return True
    return hit_distance >= distance - LINE_OF_SIGHT_SLACK_M


def _follow_config_from_store(store: ConfigStore, spatial) -> FollowConfig:
    """Replicate the runtime's authoritative owner-follow configuration merge."""

    safety = store.section("safety")
    person_stop_m = float(safety.get("person_stop_m", 1.0))
    person_slow_m = float(safety.get("person_slow_m", 2.0))
    follow_raw = store.section("owner_follow")
    follow_raw.update(
        {
            "person_stop_m": person_stop_m,
            "person_slow_m": person_slow_m,
            "owner_collision_envelope_m": spatial.owner_collision_envelope_m,
        }
    )
    minimum_keepout = person_stop_m + spatial.owner_collision_envelope_m
    configured_keepout = float(follow_raw.get("owner_keepout_m", minimum_keepout))
    if configured_keepout + 1e-9 < minimum_keepout:
        raise ValueError(
            "owner_follow.owner_keepout_m must include the person stop distance "
            "and owner collision envelope"
        )
    follow_raw["owner_keepout_m"] = configured_keepout
    return FollowConfig.from_mapping(follow_raw)


def _mocap_id(model: mujoco.MjModel, body_name: str) -> int:
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    return int(model.body_mocapid[body_id]) if body_id >= 0 else -1
