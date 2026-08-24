"""Arm A (the retained navigator) and arm B (metric point-goal), one loop each.

Both arms drive the same body through the same room, over the same drifting
pose, the same scan with the same injected gap and the same reactive safety
gate.  The ONLY difference is what decides where to go:

* **A** — ``DirectiveNavigator`` with the full semantic ladder, resolving the
  goal from detector-shaped learned-map candidates each tick.
* **B** — ``GridNavigator`` given the place's stored coordinate as a metric
  point goal at mission start, with a chance-constrained arrival check.  The
  semantic ladder is bypassed; the map is read once, not tracked.

Nothing here edits product code: arm B is assembled from
``ModelRegistry.create`` and ``pose.p_inside_disc``, both public.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from detector import DetectorNoise
from relocalize import ArmingLatch
from room import PLACES_BY_ID, RoomWorld
from stack import (
    CONTROL_DT_S,
    Body,
    PoseStack,
    dropout_window,
    nav_observation,
    sim_observation,
)

from parcel_robot.backends.base import VelocityCommand
from parcel_robot.navigation.base import GoalPose, Mission
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import apply_reactive_safety
from parcel_robot.navigation.registry import ModelRegistry
from parcel_robot.navigation.semantic_map import learned_map_candidates
from parcel_robot.pose import PoseHealth, p_inside_disc

#: Pre-registered arrival band.
ARRIVAL_BAND_M = 0.50
#: Arm B's chance constraint: ``configs/navigation/pose.yaml``'s shipped
#: ``chance_constrained.inside_probability_threshold``.
ARRIVAL_CONFIDENCE = 0.90
#: The product's own typed non-arrival reasons.  Anything else on a
#: non-arrival is a silent stall.
TYPED_FAILURES = frozenset(
    {
        "not_found",
        "ambiguous",
        "unreachable",
        "stalled",
        "pose_lost",
        "unresolved",
        "verification_failed",
        "stop_not_confirmed",
        "pose_unhealthy",
        "arming_latched",
    }
)
#: 90 s at 10 Hz.  The longest optimal path in this room is under 8 m.
MAX_STEPS = 900
#: Refuter 2's forced gap: past ``degraded_after_s`` (0.5 s), short of
#: ``lost_after_s`` (3.0 s), so the arm is asked about DEGRADED and not LOST.
DEGRADE_WINDOW_S = 2.5


@dataclass
class EpisodeResult:
    """One episode, scored against truth the arms never saw."""

    arm: str
    episode: int
    seed: int
    layout: Any
    goal_id: str
    declared_arrival: bool = False
    truth_distance_m: float = math.inf
    arrived: bool = False
    false_arrival: bool = False
    contacts: int = 0
    steps: int = 0
    time_to_goal_s: float = math.inf
    path_m: float = 0.0
    optimal_m: float = 0.0
    failure_type: str = ""
    note: str = ""
    status: str = ""
    hold_ticks: int = 0
    gap_ticks: int = 0
    gap_translating_ticks: int = 0
    degraded_ticks: int = 0
    post_kidnap_path_m: float = 0.0
    post_kidnap_healthy_ticks: int = 0
    post_kidnap_ticks: int = 0
    max_jump_m: float = 0.0
    final_health: str = ""
    latched: bool = False
    detector_dropout: float = 0.0
    detector_jitter_rms_m: float = 0.0
    journal: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        row = dict(self.__dict__)
        row["layout"] = str(self.layout)
        for key in ("truth_distance_m", "time_to_goal_s"):
            if not math.isfinite(row[key]):
                row[key] = None
        return row


#: The clearance the reactive gate actually demands head-on at grid_v1's
#: cruise speed: ``obstacle_stop_m + cruise_vx * reaction_time_s``
#: = 0.65 + 0.85 * 0.12.  The shipped planner inflates by 0.42 m
#: (footprint 0.32 + ``map_safety_margin_m`` 0.10), so it plans routes the gate
#: refuses to drive.  See RESULTS' fix list.
GATE_DEMAND_M = 0.752


def patched_registry(hard_margin_m: float | None) -> tuple[ModelRegistry, str]:
    """The shipped registry, optionally with a WIDER planner hard margin.

    Why the margin and not ``map_gate_clearance_m``.  The obvious wire is the
    one ``ReactiveSafetyPolicy.planner_inflation_m`` documents — hand the gate's
    ring to ``GridPlannerConfig.gate_clearance_m``.  It does nothing:
    ``grid_navigator._planner_coupling_ring_m`` caps the requested ring at what
    the profile's own hard margin already covers, "tighter-only, deliberately",
    because raising an inflation would re-cut the frozen navigation baselines
    (card DOOR-1's halted item H-2).  So there is no configuration that makes
    the shipped planner respect the gate's ring, and the fix witness has to
    move the hard margin itself, which is a shipped controller knob.  ``None``
    reproduces the shipped stack byte for byte.
    """

    from dataclasses import replace

    registry, active = _navigation_registry()
    if hard_margin_m is None:
        return registry, active
    models = {
        model_id: replace(
            spec,
            controller={
                **spec.controller,
                "map_safety_margin_m": float(hard_margin_m),
                "map_hard_safety_margin_m": float(hard_margin_m),
            },
        )
        for model_id, spec in registry._models.items()
    }
    return ModelRegistry(models, root=registry.root), active


@dataclass
class EpisodeSpec:
    """Everything an episode needs that is not the arm."""

    episode: int
    seed_index: int
    seed: int
    layout: Any
    goal_id: str
    start: tuple[float, float, float]
    directive: str
    learned_map: Any
    scan_gap: tuple[float, float] | None = None
    kidnap_at_s: float | None = None
    gate: bool = False
    operator_rescue_at_s: float | None = None
    moved_obstacle_at_s: float | None = None
    degrade_within_m: float | None = None
    hard_margin_m: float | None = None


def _safety_policy() -> Any:
    from parcel_robot.config import ConfigStore
    from parcel_robot.simulation.headless_city import (
        DEFAULT_ROBOT_CONFIG,
        _reactive_safety_from_store,
        _spatial_config_from_store,
    )

    store = ConfigStore(DEFAULT_ROBOT_CONFIG)
    spatial = _spatial_config_from_store(store)
    return _reactive_safety_from_store(store, spatial)


class _Runner:
    """The shared loop.  Subclasses decide the command and the arrival claim."""

    arm = "?"

    def __init__(self, spec: EpisodeSpec) -> None:
        self.spec = spec
        self.world = RoomWorld(spec.layout)
        self.body = Body(*spec.start)
        self.stack = PoseStack(spec.seed_index)
        self.detector = DetectorNoise(spec.seed + spec.episode)
        self.scan_rng = np.random.default_rng(spec.seed * 1000 + spec.episode)
        self.policy = _safety_policy()
        self.gap = spec.scan_gap or dropout_window(spec.episode, spec.seed_index)
        self.latch: ArmingLatch | None = None
        if spec.gate:
            from relocalize import GlobalMatcher

            self.latch = ArmingLatch(GlobalMatcher(self.world), enabled=True)
        self.result = EpisodeResult(
            arm=self.arm,
            episode=spec.episode,
            seed=spec.seed,
            layout=spec.layout,
            goal_id=spec.goal_id,
        )
        goal = PLACES_BY_ID[spec.goal_id]
        self.result.optimal_m = math.hypot(goal.x - spec.start[0], goal.y - spec.start[1])
        self._kidnapped = False
        self._moved = False
        self._degrade_until: float | None = None
        self._path_at_kidnap: float | None = None

    # -- hooks -------------------------------------------------------------

    def command(self, observation: Any, t_s: float) -> tuple[VelocityCommand, bool, str]:
        raise NotImplementedError

    def finish(self) -> None:
        return None

    # -- the loop ----------------------------------------------------------

    def run(self) -> EpisodeResult:
        spec = self.spec
        goal = PLACES_BY_ID[spec.goal_id]
        measured = VelocityCommand()
        for tick in range(MAX_STEPS):
            t_s = tick * CONTROL_DT_S
            if spec.kidnap_at_s is not None and not self._kidnapped and t_s >= spec.kidnap_at_s:
                self._apply_kidnap()
            if (
                spec.moved_obstacle_at_s is not None
                and not self._moved
                and t_s >= spec.moved_obstacle_at_s
            ):
                self._move_obstacle()
            silent = self.gap[0] <= t_s < self.gap[1]
            near_goal = math.hypot(self.body.x - goal.x, self.body.y - goal.y)
            if (
                spec.degrade_within_m is not None
                and self._degrade_until is None
                and near_goal <= spec.degrade_within_m
            ):
                self._degrade_until = t_s + DEGRADE_WINDOW_S
            if self._degrade_until is not None and t_s < self._degrade_until:
                silent = True
            scan = None if silent else self.world.scan(*self.body.pose, self.scan_rng)
            update = self.stack.update(self.body.pose, scan, t_s)
            if self.latch is not None:
                self.latch.observe(update=update, scan=scan, t_s=t_s)
                if spec.operator_rescue_at_s is not None and t_s >= spec.operator_rescue_at_s:
                    self.latch.try_rearm_by_operator(
                        scan, self.stack, self.body.pose, t_s
                    )
                else:
                    self.latch.try_rearm_by_margin(scan, self.stack, t_s)
            believed = self.stack.map_pose()
            contact = self.world.in_contact(self.body.x, self.body.y)
            sim_obs = sim_observation(
                believed=believed, scan=scan, contact=contact, t_s=t_s
            )
            rows = self.detector.apply(list(learned_map_candidates(sim_obs)))
            nav_obs = nav_observation(
                stack=self.stack,
                scan=scan,
                candidates=rows,
                contact=contact,
                t_s=t_s,
                measured=measured,
                stopped=abs(measured.vx) + abs(measured.vy) + abs(measured.vyaw) < 1e-6,
            )
            requested, declared, note = self.command(nav_obs, t_s)
            if self.latch is not None and self.latch.latched:
                requested, declared = VelocityCommand(), False
                note = "arming_latched"
            velocity, _ = apply_reactive_safety(
                requested,
                sim_obs,
                policy=self.policy,
                now=t_s,
                require_fresh_telemetry=False,
            )
            measured = velocity
            translating = math.hypot(velocity.vx, velocity.vy) > 1e-9
            if not translating and abs(velocity.vyaw) < 1e-9:
                self.result.hold_ticks += 1
            if silent:
                self.result.gap_ticks += 1
                self.result.gap_translating_ticks += int(translating)
            if believed.health is not PoseHealth.HEALTHY:
                self.result.degraded_ticks += 1
            if self._kidnapped:
                self.result.post_kidnap_ticks += 1
                self.result.post_kidnap_healthy_ticks += int(
                    believed.health is PoseHealth.HEALTHY
                )
            self.body.step(self.world, velocity)
            self.result.steps = tick + 1
            self.result.note = note
            if declared:
                self.result.declared_arrival = True
                self.result.time_to_goal_s = t_s
                break
            if self.done():
                break
        self.finish()
        truth_distance = math.hypot(self.body.x - goal.x, self.body.y - goal.y)
        self.result.truth_distance_m = truth_distance
        self.result.arrived = (
            self.result.declared_arrival and truth_distance <= ARRIVAL_BAND_M
        )
        self.result.false_arrival = (
            self.result.declared_arrival and truth_distance > ARRIVAL_BAND_M
        )
        self.result.contacts = self.body.contacts
        self.result.path_m = self.body.path_m
        if self._path_at_kidnap is not None:
            self.result.post_kidnap_path_m = self.body.path_m - self._path_at_kidnap
        self.result.max_jump_m = float(self.stack.provider.max_jump_m)
        self.result.final_health = self.stack.map_pose().health.value
        self.result.detector_dropout = self.detector.measured_dropout
        self.result.detector_jitter_rms_m = self.detector.measured_jitter_rms_m
        if self.latch is not None:
            self.result.latched = self.latch.latched
            self.result.journal = [record.__dict__ for record in self.latch.journal]
        if not self.result.declared_arrival and (
            self.result.failure_type not in TYPED_FAILURES
        ):
            # A run that used its whole step budget without the arm naming a
            # reason is a SILENT stall, and N4 has to count it as one; the
            # mission's own metadata ("resolved", "running") is a state, not a
            # typed failure.
            self.result.failure_type = (
                "arming_latched"
                if (self.latch is not None and self.latch.latched)
                else "silent_stall_step_limit"
            )
        return self.result

    def done(self) -> bool:
        return False

    def _apply_kidnap(self) -> None:
        from room import c2_image

        before = self.body.pose
        after = c2_image(before)
        self.stack.kidnap(before, after)
        self.body.x, self.body.y, self.body.yaw = after
        self._kidnapped = True
        self._path_at_kidnap = self.body.path_m
        self.result.extra["kidnap_displacement_m"] = math.hypot(
            after[0] - before[0], after[1] - before[1]
        )

    def _move_obstacle(self) -> None:
        """Refuter 3: a box appears across the committed route, mid-episode."""

        from room import Box

        ahead = 1.1
        cx = self.body.x + ahead * math.cos(self.body.yaw)
        cy = self.body.y + ahead * math.sin(self.body.yaw)
        blocker = Box("moved_obstacle", cx, cy, 0.45, 0.45)
        self.world.add_blocker(blocker)
        self._moved = True
        self.result.extra["moved_obstacle_xy"] = [round(cx, 3), round(cy, 3)]


class ArmA(_Runner):
    """The retained navigator, unchanged, on physical-shaped inputs."""

    arm = "A"

    def __init__(self, spec: EpisodeSpec) -> None:
        super().__init__(spec)
        self.navigator = DirectiveNavigator.from_config()
        if spec.hard_margin_m is not None:
            self.navigator.registry, active = patched_registry(spec.hard_margin_m)
            self.navigator.set_model(active)
        self.mission = self.navigator.start(spec.directive)

    def command(self, observation: Any, t_s: float) -> tuple[VelocityCommand, bool, str]:
        cmd = self.navigator.step(observation)
        status = self.mission.status_value()
        declared = status == "arrived"
        requested = (
            VelocityCommand()
            if cmd.stop
            else VelocityCommand(cmd.vx, cmd.vy, cmd.vyaw)
        )
        self.result.status = status
        return requested, declared, cmd.note

    def done(self) -> bool:
        status = self.mission.status_value()
        if status == "failed":
            self.result.failure_type = str(
                self.mission.metadata.get("resolution_state") or self.result.note
            )
            return True
        return bool(self.navigator.done())

    def finish(self) -> None:
        self.result.status = self.mission.status_value()
        if not self.result.failure_type:
            self.result.failure_type = str(
                self.mission.metadata.get("resolution_state") or ""
            )
        self.navigator.close()


class ArmB(_Runner):
    """Metric point goal: grid planner plus a chance-constrained arrival."""

    arm = "B"

    def __init__(self, spec: EpisodeSpec) -> None:
        super().__init__(spec)
        registry, target = patched_registry(spec.hard_margin_m)
        self.navigator = registry.create(target, arrive_radius_m=ARRIVAL_BAND_M)
        self.goal_xy = _stored_goal(spec.learned_map, spec.goal_id)
        self.mission = Mission(
            directive=spec.directive,
            goal=GoalPose(x=self.goal_xy[0], y=self.goal_xy[1]),
            status="running",
        )
        self.navigator.reset(self.mission)
        self.result.extra["stored_goal_xy"] = [round(v, 3) for v in self.goal_xy]

    def command(self, observation: Any, t_s: float) -> tuple[VelocityCommand, bool, str]:
        believed = self.stack.map_pose()
        if believed.health is PoseHealth.LOST:
            self.result.status = "hold_localization_lost"
            return VelocityCommand(), False, "pose_lost_hold"
        cmd = self.navigator.act(observation, self.mission)
        confidence = p_inside_disc(believed, self.goal_xy, ARRIVAL_BAND_M)
        declared = (
            believed.health is PoseHealth.HEALTHY and confidence >= ARRIVAL_CONFIDENCE
        )
        self.result.status = "arrived" if declared else "running"
        self.result.extra["arrival_confidence"] = round(float(confidence), 4)
        requested = (
            VelocityCommand()
            if cmd.stop
            else VelocityCommand(cmd.vx, cmd.vy, cmd.vyaw)
        )
        return requested, declared, cmd.note

    def finish(self) -> None:
        if not self.result.declared_arrival and not self.result.failure_type:
            believed = self.stack.map_pose()
            if believed.health is not PoseHealth.HEALTHY:
                self.result.failure_type = "pose_unhealthy"
        self.navigator.close()


def _stored_goal(learned_map: Any, place_id: str) -> tuple[float, float]:
    """Arm B reads the map ONCE — the stored coordinate, no ladder, no tracking."""

    from world_map import entry_id_for

    place = PLACES_BY_ID[place_id]
    entry_id = entry_id_for(learned_map, place)
    for entry in learned_map.active_entries():
        if str(entry.entry_id) == entry_id:
            return (float(entry.surface_x), float(entry.surface_y))
    raise LookupError(f"{place_id} is not in the learned map")


def _navigation_registry() -> tuple[ModelRegistry, str]:
    """The same registry and active model ``DirectiveNavigator.from_config``
    builds, so arm B's controller is arm A's controller and only the goal
    source differs."""

    import yaml

    from parcel_robot.navigation.pipeline import REPO_ROOT

    config = (REPO_ROOT / "configs/navigation/default.yaml").resolve()
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    root = (REPO_ROOT / str(data.get("models_root"))).resolve()
    return ModelRegistry.load(root), str(data.get("active_model"))
