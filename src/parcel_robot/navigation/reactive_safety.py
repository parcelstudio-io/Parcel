from __future__ import annotations

import math
import time
from dataclasses import dataclass

from parcel_robot.authority import CLEARANCE_CONVENTION, DEFAULT_SAFETY_ENVELOPE
from parcel_robot.backends.base import SimObservation
from parcel_robot.core.input_health import (
    InputEvidence,
    InputOrigin,
    RequiredInput,
    RequiredInputSpec,
    evaluate_input_health,
)
from parcel_robot.models import VelocityCommand

#: robot.yaml ``safety.obstacle_stop_m`` commissioning floor. Stricter than
#: ``SafetyEnvelope.obstacle_stop_floor_m`` (0.6); unifying downward would
#: loosen the live reactive gate (forbidden). Under
#: :data:`~parcel_robot.authority.CLEARANCE_CONVENTION` both thresholds are
#: base-center-to-surface metres; consumers must not re-add the footprint.
_REACTIVE_OBSTACLE_STOP_FLOOR_M = 0.65


@dataclass(frozen=True)
class ReactiveSafetyPolicy:
    """Final body-frame proximity gate; distances from :class:`SafetyEnvelope`.

    Clearance convention matches :data:`~parcel_robot.authority.CLEARANCE_CONVENTION`
    (``base_center_to_obstacle_surface``). Person/obstacle slow bands and the
    reaction horizon are envelope-derived; obstacle stop keeps the stricter
    commissioning floor via ``max(envelope.floor, 0.65)``.
    """

    clearance_convention: str = CLEARANCE_CONVENTION
    obstacle_stop_m: float = max(
        DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m,
        _REACTIVE_OBSTACLE_STOP_FLOOR_M,
    )
    obstacle_slow_m: float = DEFAULT_SAFETY_ENVELOPE.obstacle_comfort_band_m
    person_stop_m: float = DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
    person_slow_m: float = DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m
    telemetry_stale_s: float = 0.6
    owner_collision_envelope_m: float = 0.55
    orbit_clearance_margin_m: float = 0.10
    orbit_waypoint_tolerance_m: float = 0.16
    reaction_time_s: float = DEFAULT_SAFETY_ENVELOPE.reaction_latency_s

    def __post_init__(self) -> None:
        if self.clearance_convention != CLEARANCE_CONVENTION:
            raise ValueError(
                "reactive safety clearance_convention must be "
                f"{CLEARANCE_CONVENTION!r} (got {self.clearance_convention!r})"
            )
        values = (
            self.obstacle_stop_m,
            self.obstacle_slow_m,
            self.person_stop_m,
            self.person_slow_m,
            self.telemetry_stale_s,
            self.owner_collision_envelope_m,
            self.orbit_clearance_margin_m,
            self.orbit_waypoint_tolerance_m,
            self.reaction_time_s,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("reactive safety limits must be positive and finite")
        if self.obstacle_stop_m >= self.obstacle_slow_m:
            raise ValueError("obstacle stop distance must be below slow distance")
        if self.person_stop_m >= self.person_slow_m:
            raise ValueError("person stop distance must be below slow distance")
        if self.obstacle_stop_m + 1e-12 < DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m:
            raise ValueError(
                "reactive obstacle_stop_m must not undercut "
                "SafetyEnvelope.obstacle_stop_floor_m"
            )


def apply_reactive_safety(
    command: VelocityCommand,
    observation: SimObservation | None,
    *,
    policy: ReactiveSafetyPolicy,
    owner_orbit: bool = False,
    orbit_radius_m: float = 0.0,
    now: float | None = None,
    require_fresh_telemetry: bool = True,
) -> tuple[VelocityCommand, str]:
    """Apply the final body-frame safety gate used in runtime and quality tests."""

    if observation is None:
        return _stop_translation(command) if _translating(command) else (command, "clear")
    timestamp = time.monotonic() if now is None else now
    if require_fresh_telemetry and timestamp - observation.timestamp > policy.telemetry_stale_s:
        return _stop_translation(command) if _translating(command) else (command, "clear")

    translating = _translating(command)
    # P0-B: a present observation with no scan must not authorize translation.
    # Route through the core input-health join (missing → HOLD), never "clear".
    if translating and not _scan_health_allows_translation(observation, now=timestamp):
        return _stop_translation(command)
    predictive_state = "clear"
    owner_dx = observation.owner.x - observation.robot.x
    owner_dy = observation.owner.y - observation.robot.y
    owner_center_distance = math.hypot(owner_dx, owner_dy)
    people: list[tuple[float, float | None]] = []
    if observation.nearest_person_m is not None:
        people.append(
            (observation.nearest_person_m, observation.nearest_person_bearing_rad)
        )
    if observation.owner.visible and not owner_orbit:
        owner_clearance = max(
            0.0,
            owner_center_distance - policy.owner_collision_envelope_m,
        )
        people.append(
            (
                owner_clearance,
                _wrap(math.atan2(owner_dy, owner_dx) - observation.robot.yaw),
            )
        )
    for person_distance, person_bearing in people if translating else ():
        toward_person = _toward(command, person_bearing)
        predictive_person_stop = (
            policy.person_stop_m
            + math.hypot(command.vx, command.vy) * policy.reaction_time_s
        )
        if toward_person and person_distance <= predictive_person_stop:
            return _stop_translation(command)
        if toward_person and person_distance < policy.person_slow_m:
            scale = max(
                0.15,
                (person_distance - policy.person_stop_m)
                / (policy.person_slow_m - policy.person_stop_m),
            )
            command = _scale_translation(command, scale)
            predictive_state = "slowing"

    if owner_orbit and translating:
        minimum_center_distance = max(
            policy.obstacle_stop_m
            + policy.owner_collision_envelope_m
            + policy.orbit_clearance_margin_m,
            orbit_radius_m - policy.orbit_waypoint_tolerance_m,
        )
        owner_bearing = _wrap(
            math.atan2(owner_dy, owner_dx) - observation.robot.yaw
        )
        if owner_center_distance <= minimum_center_distance and _toward(
            command,
            owner_bearing,
            half_angle=math.pi / 2.0,
        ):
            return _stop_translation(command)

    person_ttc = observation.nearest_person_ttc_s
    if translating and person_ttc is not None:
        if person_ttc <= 0.8:
            return _stop_translation(command)
        if person_ttc < 1.8:
            command = _scale_translation(
                command,
                max(0.15, (person_ttc - 0.8) / 1.0),
            )
            predictive_state = "slowing"
    if not translating:
        return command, "clear"

    toward_obstacle = True
    distance: float | None
    if observation.lidar_obstacles:
        directional = [
            item
            for item in observation.lidar_obstacles
            if not (
                owner_orbit
                and item.obstacle_id is not None
                and item.obstacle_id.startswith("owner_")
            )
            if _toward(command, item.bearing_rad)
        ]
        if not directional:
            return command, predictive_state
        distance = min(directional, key=lambda item: item.distance_m).distance_m
    else:
        distance = observation.nearest_obstacle_m
        bearing = observation.nearest_obstacle_bearing_rad
        # A sparse range without a bearing fails closed for every translation.
        toward_obstacle = bearing is None or _toward(command, bearing)
    if observation.collision and toward_obstacle:
        return _stop_translation(command)
    if not toward_obstacle or distance is None:
        return command, predictive_state
    if distance <= policy.obstacle_stop_m:
        return _stop_translation(command)
    predictive_obstacle_stop = (
        policy.obstacle_stop_m
        + math.hypot(command.vx, command.vy) * policy.reaction_time_s
    )
    if distance <= predictive_obstacle_stop:
        return _stop_translation(command)
    if distance < policy.obstacle_slow_m:
        scale = max(
            0.15,
            (distance - policy.obstacle_stop_m)
            / (policy.obstacle_slow_m - policy.obstacle_stop_m),
        )
        return _scale_translation(command, scale), "slowing"
    return command, predictive_state


def _translating(command: VelocityCommand) -> bool:
    return math.hypot(command.vx, command.vy) > 1e-6


def scan_present(observation: SimObservation) -> bool:
    """True when any commissioned scan channel carries a sample this tick."""

    if observation.lidar_obstacles:
        return True
    if observation.nearest_obstacle_m is not None:
        return True
    return bool(observation.lidar_ranges)


def scan_evidence_from_observation(observation: SimObservation) -> InputEvidence | None:
    """Build scan ``InputEvidence`` for the core health join, or ``None`` if missing."""

    if not scan_present(observation):
        return None
    backend = str(observation.backend or "")
    # Simulated backends are labeled fixtures; unlabeled sim is rejected by the
    # health join. Physical / unknown backends stay unlabeled physical samples.
    if backend and backend not in {"unknown", "physical"}:
        return InputEvidence(
            captured_at=observation.timestamp,
            frame_id="base_link",
            payload_valid=True,
            origin=InputOrigin.SIM_FIXTURE,
            fixture_label=backend,
        )
    return InputEvidence(
        captured_at=observation.timestamp,
        frame_id="base_link",
        payload_valid=True,
        origin=InputOrigin.PHYSICAL,
    )


def _scan_health_allows_translation(observation: SimObservation, *, now: float) -> bool:
    """Fail closed on missing/stale/malformed scan via the core health join."""

    verdict = evaluate_input_health(
        {RequiredInput.SCAN: scan_evidence_from_observation(observation)},
        now=now,
        requirements={
            RequiredInput.SCAN: RequiredInputSpec(
                frame_id="base_link",
                max_age_s=0.25,
                sim_fixture_allowed=True,
            ),
        },
    )
    return verdict.translation_allowed


def _toward(
    command: VelocityCommand,
    bearing: float | None,
    *,
    half_angle: float = 1.15,
) -> bool:
    if bearing is None:
        return True
    travel_angle = math.atan2(command.vy, command.vx)
    return abs(_wrap(bearing - travel_angle)) < half_angle


def _scale_translation(command: VelocityCommand, scale: float) -> VelocityCommand:
    return VelocityCommand(
        vx=command.vx * scale,
        vy=command.vy * scale,
        vyaw=command.vyaw,
    )


def _stop_translation(command: VelocityCommand) -> tuple[VelocityCommand, str]:
    return VelocityCommand(vyaw=command.vyaw), "stopped"


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
