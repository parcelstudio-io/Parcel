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
from dataclasses import dataclass, fields, replace
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
from parcel_robot.core.motion_shaping import MotionShapingConfig
from parcel_robot.core.velocity_smoother import VelocitySmoother
from parcel_robot.dynamic_city import select_social_collision_candidate
from parcel_robot.expression import ExpressionEngine, ExpressionGate

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
from parcel_robot.navigation.dynamic_layer import (
    TimeToCollisionConfig,
    time_to_collision_verdict,
    tracks_from_payload,
)
from parcel_robot.navigation.follow import (
    FollowConfig,
    FollowOwnerController,
    FollowPredictionConfig,
)
from parcel_robot.navigation.owner_prediction import OwnerMotionPredictor, PredictedPath
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import apply_reactive_safety
from parcel_robot.navigation.search_owner import SearchOwnerConfig, SearchOwnerController
from parcel_robot.navigation.velocity_shaping import SCurveVelocityShaper
from parcel_robot.robot_profile import RobotProfile

# 1.1 adds the card-W9 dispatch replica (pre-gate smoother, predictive brake,
# actuator shaper), the owner-search trigger, and the expression channels.
# Numbers from 1.0 reports are therefore not comparable step-for-step.
RUNNER_VERSION = "follow-bench-v1.1"
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


@dataclass(frozen=True)
class BenchFeatures:
    """Which sprint features the episode runs with.

    Every W2/W4/W6/W7 claim in the ledger needs a before and an after measured
    on the same geometry, so the features are switches on the bench rather
    than edits to ``robot.yaml``: a baseline row is a real run of today's
    controllers with the new code paths turned off, not a stale number.

    The pre-gate acceleration smoother is deliberately *not* switchable — it
    has always been in the production dispatch path, and leaving it out of the
    bench was a fidelity gap rather than a feature.
    """

    owner_prediction: bool = True
    dynamic_costs: bool = True
    time_to_collision_gate: bool = True
    velocity_shaping: bool = True
    owner_search: bool = True

    def __post_init__(self) -> None:
        for item in fields(self):
            if not isinstance(getattr(self, item.name), bool):
                raise TypeError(f"bench feature {item.name!r} must be a boolean")

    @classmethod
    def baseline(cls) -> BenchFeatures:
        """Pre-sprint behaviour: every W2/W4/W6/W7 path switched off."""

        return cls(
            owner_prediction=False,
            dynamic_costs=False,
            time_to_collision_gate=False,
            velocity_shaping=False,
            owner_search=False,
        )

    @property
    def label(self) -> str:
        if self == BenchFeatures():
            return "shipped"
        if self == BenchFeatures.baseline():
            return "baseline"
        enabled = sorted(item.name for item in fields(self) if getattr(self, item.name))
        return "+".join(enabled) if enabled else "none"


class FollowBenchRunner:
    """Deterministic scenario executor configured from ``configs/robot.yaml``."""

    def __init__(
        self,
        robot_config: str | Path = DEFAULT_ROBOT_CONFIG,
        *,
        features: BenchFeatures | None = None,
    ):
        store = ConfigStore(robot_config)
        self.features = features or BenchFeatures()
        spatial = _spatial_config_from_store(store)
        self.reactive_safety = _reactive_safety_from_store(store, spatial)
        self.navigation_config = _navigation_config_from_store(store)
        self.follow_config, self.follow_prediction = _follow_config_from_store(store, spatial)
        if not self.features.owner_prediction:
            self.follow_prediction = replace(self.follow_prediction, enabled=False)
        self.time_to_collision = _time_to_collision_from_store(store)
        if not self.features.time_to_collision_gate:
            self.time_to_collision = replace(self.time_to_collision, enabled=False)
        self.motion_shaping = _motion_shaping_from_store(store)
        if not self.features.velocity_shaping:
            self.motion_shaping = replace(self.motion_shaping, enabled=False)
        self.smoother_limits = _smoother_limits_from_store(store)
        self.search_config = _search_config_from_store(store)
        self.profile = RobotProfile.go2()
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
            self.follow_config,
            safety_policy=self.reactive_safety,
            prediction=self.follow_prediction,
        )
        follow.start("direct")
        # The runtime owns the predictor and feeds it from the same owner
        # track; replicate that ownership so the bench measures the shipped
        # anticipatory path rather than the fallback.
        predictor = OwnerMotionPredictor()
        search = SearchOwnerController(
            self.search_config, safety_policy=self.reactive_safety
        )
        dispatch = _DispatchReplica(
            policy=self.reactive_safety,
            smoother_limits=self.smoother_limits,
            time_to_collision=self.time_to_collision,
            shaping=self.motion_shaping,
        )
        conversation = _ExpressionRig(scenario, self.profile)
        lost_since: float | None = None
        last_confident: tuple[float, float] | None = None
        steps: list[StepRecord] = []
        try:
            for _ in range(scenario.control_steps):
                now = float(world.data.time)
                rig.apply(now)
                observation = self._observe(world, rig, now)
                # Production order (runtime.py): passive owner-track update,
                # then the follow decision, then the shared actuator gate.
                follow.observe_owner(observation, now=now)
                prediction = self._predict_owner(predictor, observation, now)
                decision = follow.step(observation, now=now, prediction=prediction)
                if (
                    observation.owner.visible
                    and observation.owner.confidence >= self.follow_config.min_confidence
                ):
                    last_confident = (observation.owner.x, observation.owner.y)

                requested = decision.command
                state = decision.state
                note = decision.reason
                lost_since, search_state = self._service_owner_search(
                    search,
                    observation,
                    decision_state=decision.state,
                    now=now,
                    lost_since=lost_since,
                    last_confident=last_confident,
                )
                if search.enabled or search_state == "gave_up":
                    verdict = search.step(observation, now)
                    requested = verdict.command
                    state = f"search:{verdict.state}"
                    note = verdict.reason
                    search_state = verdict.state

                # A scripted gesture owns the base exactly as a running
                # activity does in the runtime: the follower keeps thinking,
                # but the arbiter hands the body to the skill.
                emote = scenario.expression.emote_active(now)
                if emote is not None:
                    requested = VelocityCommand()
                    note = f"{note}|emote:{emote}"

                command, proximity_state, ttc, reactive_proximity_state = dispatch.step(
                    requested, observation, now=now
                )
                offsets = conversation.step(
                    now,
                    proximity_clear=proximity_state == "clear",
                    follow_active=follow.enabled or search.enabled,
                    emote_active=emote is not None,
                    owner_bearing_rad=_owner_bearing_rad(observation),
                )
                steps.append(
                    _record(
                        world,
                        rig,
                        observation,
                        command,
                        state=state,
                        note=f"{note}|{proximity_state}",
                        proximity_state=proximity_state,
                        reactive_proximity_state=reactive_proximity_state,
                        time_to_collision_s=ttc,
                        search_state=search_state,
                        expression_head_yaw_rad=offsets.head_yaw_rad,
                        expression_producer=conversation.producer,
                        emote_label=emote,
                    )
                )
                world.apply(command)
                world.step()
        finally:
            world.stop()
            follow.stop()
            search.stop()
        return self._result(
            world, scenario, steps, status="completed", reason="duration_elapsed"
        )

    def _service_owner_search(
        self,
        search: SearchOwnerController,
        observation: SimObservation,
        *,
        decision_state: str,
        now: float,
        lost_since: float | None,
        last_confident: tuple[float, float] | None,
    ) -> tuple[float | None, str]:
        """Replicate the runtime's deterministic owner-search trigger.

        The runtime routes the search through a compiled plan and the
        executive; the bench drives the controller directly, so what this
        proves is the trigger and the search behaviour, not the plan path.
        That boundary is stated in the eval's ``does_not_prove``.
        """

        if not self.features.owner_search:
            return None, ""
        if search.enabled:
            return None, search.state
        if search.state == "gave_up":
            # Terminal: one give-up per episode, and no silent restart.
            return None, "gave_up"
        if decision_state != "lost":
            return None, ""
        if lost_since is None:
            return now, ""
        if now - lost_since < self.search_config.lost_timeout_s:
            return lost_since, ""
        if last_confident is None:
            return None, ""
        search.start(
            last_x=last_confident[0],
            last_y=last_confident[1],
            lost_at_s=lost_since,
            now=now,
        )
        return None, search.state

    def _predict_owner(
        self,
        predictor: OwnerMotionPredictor,
        observation,
        now: float,
    ) -> PredictedPath | None:
        if not self.follow_prediction.enabled:
            return None
        owner = observation.owner
        visible = (
            owner.visible
            and owner.confidence >= self.follow_config.min_confidence
            and math.isfinite(owner.x)
            and math.isfinite(owner.y)
        )
        predictor.observe(
            owner.x if visible else 0.0,
            owner.y if visible else 0.0,
            now_s=now,
            visible=visible,
        )
        return predictor.predict(now_s=now)

    def _run_navigate(
        self, world: HeadlessCityWorld, rig: _ActorRig, scenario: Scenario
    ) -> EpisodeResult:
        navigator = DirectiveNavigator.from_config(
            self.navigation_config, model_id=GRID_MODEL_ID
        )
        if not self.features.dynamic_costs:
            _disable_dynamic_costs(navigator)
        dispatch = _DispatchReplica(
            policy=self.reactive_safety,
            smoother_limits=self.smoother_limits,
            time_to_collision=self.time_to_collision,
            shaping=self.motion_shaping,
        )
        conversation = _ExpressionRig(scenario, self.profile)
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
                emote = scenario.expression.emote_active(now)
                if emote is not None:
                    requested = VelocityCommand()
                velocity, proximity_state, ttc, reactive_proximity_state = dispatch.step(
                    requested,
                    observation,
                    now=observation.timestamp,
                    require_fresh_telemetry=False,
                )
                offsets = conversation.step(
                    now,
                    proximity_clear=proximity_state == "clear",
                    navigation_active=True,
                    emote_active=emote is not None,
                    owner_bearing_rad=_owner_bearing_rad(observation),
                )
                steps.append(
                    _record(
                        world,
                        rig,
                        observation,
                        velocity,
                        state=mission.status,
                        note=command.note,
                        proximity_state=proximity_state,
                        reactive_proximity_state=reactive_proximity_state,
                        time_to_collision_s=ttc,
                        expression_head_yaw_rad=offsets.head_yaw_rad,
                        expression_producer=conversation.producer,
                        emote_label=emote,
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


class _DispatchReplica:
    """The runtime's actuator hand-off, reproduced stage for stage.

    ``runtime._dispatch_active`` runs: acceleration smoother, then the
    geometric collision gate, then the predictive brake, then the jerk-limited
    shaper, then the SE2 hand-off. Card W6's jerk claim and card W4's brake
    claim both live between those stages, so a bench that gates and then
    writes straight to the world cannot measure either of them (register entry
    U14). This class closes that gap; it adds no authority of its own.
    """

    def __init__(
        self,
        *,
        policy,
        smoother_limits: dict[str, float],
        time_to_collision: TimeToCollisionConfig,
        shaping: MotionShapingConfig,
    ):
        self._policy = policy
        self._smoother = VelocitySmoother(**smoother_limits)
        self._time_to_collision = time_to_collision
        self._shaping = shaping
        self._shaper = SCurveVelocityShaper(*shaping.limits())
        self._shaped_at: float | None = None

    def step(
        self,
        requested: VelocityCommand,
        observation: SimObservation,
        *,
        now: float,
        require_fresh_telemetry: bool = True,
    ) -> tuple[VelocityCommand, str, float | None, str]:
        command = self._smoother.step(requested, now=now)
        command, proximity_state = apply_reactive_safety(
            command,
            observation,
            policy=self._policy,
            owner_orbit=False,
            orbit_radius_m=0.0,
            now=now,
            require_fresh_telemetry=require_fresh_telemetry,
        )
        reactive_proximity_state = proximity_state
        ttc: float | None = None
        if self._time_to_collision.enabled:
            verdict = time_to_collision_verdict(
                config=self._time_to_collision,
                tracks=tracks_from_payload(_agent_payload(observation)),
                robot_xy=(observation.robot.x, observation.robot.y),
                robot_yaw_rad=observation.robot.yaw,
                command_vx=command.vx,
                command_vy=command.vy,
                proximity_state=proximity_state,
            )
            ttc = (
                verdict.time_to_collision_s
                if math.isfinite(verdict.time_to_collision_s)
                else None
            )
            if verdict.intervened:
                command = VelocityCommand(
                    vx=command.vx * verdict.scale,
                    vy=command.vy * verdict.scale,
                    vyaw=command.vyaw * verdict.scale,
                )
                proximity_state = verdict.proximity_state
        # The runtime re-synchronizes the smoother with whatever the gates
        # allowed, so the next tick ramps from the executed velocity rather
        # than from an intent that was never actuated.
        self._smoother.force(command, now=now)
        command = self._shape(command, now=now, proximity_state=proximity_state)
        return command, proximity_state, ttc, reactive_proximity_state

    def _shape(
        self, command: VelocityCommand, *, now: float, proximity_state: str
    ) -> VelocityCommand:
        if not self._shaping.enabled:
            self._shaped_at = now
            return command
        dt_s = 0.1 if self._shaped_at is None else max(1e-3, min(0.25, now - self._shaped_at))
        self._shaped_at = now
        vx, vy, vyaw = self._shaper.step(
            (command.vx, command.vy, command.vyaw),
            dt_s=dt_s,
            # Same bypass rule as the runtime: a gate stop and a zero command
            # are stop decisions and are never smoothed.
            emergency=proximity_state == "stopped" or _is_zero(command),
        )
        return VelocityCommand(vx=vx, vy=vy, vyaw=vyaw)


class _ExpressionRig:
    """Runs the real expression stack against a scripted conversation.

    Only the *inputs* are scripted. The orient reaction, the idle layer, and
    the gate arbitration are the production classes, so the acknowledgment
    latency and the blend-continuity jerk are properties of shipped code
    rather than of this harness.
    """

    def __init__(self, scenario: Scenario, profile: RobotProfile):
        self._engine = ExpressionEngine(profile)
        self._turns = tuple(scenario.expression.speech_turns)
        self._started = 0
        self._ended = 0

    @property
    def producer(self) -> str:
        return self._engine.producer

    def step(
        self,
        now: float,
        *,
        proximity_clear: bool,
        emote_active: bool,
        owner_bearing_rad: float,
        follow_active: bool = False,
        navigation_active: bool = False,
    ):
        while self._started < len(self._turns) and now >= self._turns[self._started].onset_s:
            self._engine.reactions.on_speech_start(now, owner_bearing_rad)
            self._started += 1
        while self._ended < len(self._turns) and now >= self._turns[self._ended].end_s:
            self._engine.reactions.on_speech_end(now)
            self._ended += 1
        gate = ExpressionGate(
            proximity_clear=proximity_clear,
            # A running gesture is an activity skill, and an activity owns the
            # whole body: that is what takes expression to MODE_OFF.
            skill_active=emote_active,
            follow_active=follow_active,
            navigation_active=navigation_active,
        )
        return self._engine.step(now, gate)


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


def _is_zero(command: VelocityCommand) -> bool:
    return all(abs(value) <= 1e-9 for value in (command.vx, command.vy, command.vyaw))


def _agent_payload(observation: SimObservation) -> tuple[dict[str, float], ...]:
    """The same serialization the runtime feeds its predictive brake."""

    return tuple(
        {
            "x": float(track.x),
            "y": float(track.y),
            "vx": float(track.vx),
            "vy": float(track.vy),
            "radius_m": float(track.radius_m),
        }
        for track in observation.dynamic_agents
    )


def _owner_bearing_rad(observation: SimObservation) -> float:
    """Owner bearing in the robot body frame; zero when the owner is unseen."""

    owner = observation.owner
    if not owner.visible:
        return 0.0
    dx = owner.x - observation.robot.x
    dy = owner.y - observation.robot.y
    if math.hypot(dx, dy) <= 1e-6:
        return 0.0
    bearing = math.atan2(dy, dx) - observation.robot.yaw
    return (bearing + math.pi) % (2.0 * math.pi) - math.pi


def _disable_dynamic_costs(navigator: DirectiveNavigator) -> None:
    """Switch the grid planner's dynamic-agent layer off for a baseline run.

    Reaching past ``DirectiveNavigator`` is deliberate: rewriting the model
    YAML into a temporary tree would also re-freeze the model lock hash, and a
    baseline row must differ from the shipped row in exactly one thing.
    """

    inner = getattr(navigator, "_navigator", None)
    config = getattr(inner, "dynamic_agents", None)
    if config is None:
        raise AttributeError("grid navigator does not expose a dynamic-agent config")
    inner.dynamic_agents = replace(config, enabled=False)


def _record(
    world: HeadlessCityWorld,
    rig: _ActorRig,
    observation: SimObservation,
    command: VelocityCommand,
    *,
    state: str,
    note: str,
    proximity_state: str = "clear",
    reactive_proximity_state: str = "clear",
    time_to_collision_s: float | None = None,
    search_state: str = "",
    expression_head_yaw_rad: float = 0.0,
    expression_producer: str = "none",
    emote_label: str | None = None,
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
        proximity_state=proximity_state,
        reactive_proximity_state=reactive_proximity_state,
        time_to_collision_s=time_to_collision_s,
        search_state=search_state,
        expression_head_yaw_rad=expression_head_yaw_rad,
        expression_producer=expression_producer,
        emote_label=emote_label,
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


def _follow_config_from_store(
    store: ConfigStore,
    spatial,
) -> tuple[FollowConfig, FollowPredictionConfig]:
    """Replicate the runtime's authoritative owner-follow configuration merge."""

    safety = store.section("safety")
    person_stop_m = float(safety.get("person_stop_m", 1.0))
    person_slow_m = float(safety.get("person_slow_m", 2.0))
    follow_raw = store.section("owner_follow")
    raw_prediction = follow_raw.pop("prediction", {})
    if not isinstance(raw_prediction, dict):
        raise TypeError("owner_follow.prediction must be a mapping")
    prediction = FollowPredictionConfig.from_mapping(raw_prediction)
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
    return FollowConfig.from_mapping(follow_raw), prediction


def _time_to_collision_from_store(store: ConfigStore) -> TimeToCollisionConfig:
    raw = store.section("safety").get("time_to_collision", {})
    if not isinstance(raw, dict):
        raise TypeError("safety.time_to_collision must be a mapping")
    return TimeToCollisionConfig.from_mapping(raw)


def _motion_shaping_from_store(store: ConfigStore) -> MotionShapingConfig:
    raw = store.section("motion").get("shaping", {})
    if not isinstance(raw, dict):
        raise TypeError("motion.shaping must be a mapping")
    return MotionShapingConfig.from_mapping(raw)


def _smoother_limits_from_store(store: ConfigStore) -> dict[str, float]:
    """The pre-gate acceleration limits the runtime builds its smoother from."""

    raw = store.section("motion").get("smoothing", {})
    if not isinstance(raw, dict):
        raise TypeError("motion.smoothing must be a mapping")
    return {
        "linear_accel": float(raw.get("linear_accel", 0.9)),
        "linear_decel": float(raw.get("linear_decel", 1.4)),
        "yaw_accel": float(raw.get("yaw_accel", 1.8)),
    }


def _search_config_from_store(store: ConfigStore) -> SearchOwnerConfig:
    raw = store.section("owner_search")
    if not isinstance(raw, dict):
        raise TypeError("owner_search must be a mapping")
    return SearchOwnerConfig.from_mapping(raw)


def _mocap_id(model: mujoco.MjModel, body_name: str) -> int:
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    return int(model.body_mocapid[body_id]) if body_id >= 0 else -1
