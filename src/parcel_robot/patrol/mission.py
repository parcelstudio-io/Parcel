"""The patrol policy, its sensing adapter, and the mission runner.

Split deliberately into a **pure policy** and a **thin driver** so the
behaviour that matters — "do not command a heading the safety gate will
refuse" — is decidable in a unit test with no simulator, no socket and no
clock, and the driver contains only I/O.

Nothing here re-implements or weakens a safety gate. The policy is a
*proposer* that keeps the body out of situations the reactive gate would have
to veto; the gate remains the unconditional last line of defence and is
untouched. A patrol that ignores this simply burns its budget on refused
commands, which is precisely what E2-D2 measured.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

# E2-D3, the T1 detector query vocabulary. No sidecar by design: this list is
# carried by the runner, never read from ``scenes/`` truth or a scene digest.
# Place-like, non-volatile nouns only — C-2's hygiene gate refuses people and
# other volatile classes, and a patrol that spends its detector budget
# proposing them learns nothing it is allowed to keep.
DEFAULT_MAP_SWEEP_VOCABULARY: tuple[str, ...] = (
    "building",
    "storefront",
    "door",
    "window",
    "lamppost",
    "bench",
    "tree",
    "planter",
    "bollard",
    "traffic sign",
    "bicycle rack",
    "trash can",
)

#: The detector query the camera channel REQUIRES, for safety rather than for
#: mapping. ``CameraStreamConfig.from_section`` refuses a batch without the
#: whole word "person": a camera that never asks about people must not claim
#: the person-relevant admission path (PG-1's safety lease). Measured by
#: running it, card MOVE-1.
SAFETY_LEASE_QUERY = "person"

#: Body-forward half-angle of the lane the patrol treats as "ahead". Matches
#: the reactive gate's own ``_toward`` half-angle so the clearance the policy
#: reads is the clearance the gate will judge.
FORWARD_HALF_ANGLE_RAD = 1.15


def ingress_queries(limit: int = 8) -> tuple[str, ...]:
    """The detector batch to hand the camera channel, safety query first.

    E2-D3's answer in one function: the **query** vocabulary and the **map**
    vocabulary are different sets, and conflating them is a safety bug in one
    direction and a hygiene bug in the other.

    * ``person`` must be asked, or the camera channel refuses to start.
    * ``person`` must never become a place — C-2's hygiene gate refuses
      volatile classes, and the patrol relies on that refusal rather than on
      not asking.
    """

    if limit < 1:
        raise ValueError("ingress_queries limit must be at least 1")
    sweep = DEFAULT_MAP_SWEEP_VOCABULARY[: max(0, limit - 1)]
    return (SAFETY_LEASE_QUERY, *sweep)


@dataclass(frozen=True)
class PatrolSense:
    """Everything the policy is allowed to see. One control tick's worth."""

    elapsed_s: float
    x: float
    y: float
    yaw: float
    forward_clearance_m: float | None = None
    person_clearance_m: float | None = None
    #: Bearing to the nearest person, in the BODY frame (0 = dead ahead).
    #: ``None`` means the bearing is unknown, which fails closed: an
    #: unlocated person blocks translation exactly like one dead ahead.
    person_bearing_rad: float | None = None
    collision: bool = False

    def __post_init__(self) -> None:
        for name in ("elapsed_s", "x", "y", "yaw"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"PatrolSense.{name} must be a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"PatrolSense.{name} must be finite")
        if self.person_bearing_rad is not None and not math.isfinite(
            float(self.person_bearing_rad)
        ):
            raise ValueError("PatrolSense.person_bearing_rad must be finite")
        for name in ("forward_clearance_m", "person_clearance_m"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"PatrolSense.{name} must be a number or None")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"PatrolSense.{name} must be finite and non-negative")


@dataclass(frozen=True)
class PatrolCommand:
    """A proposal, with the reason it was proposed. The reason is evidence."""

    vx: float = 0.0
    vy: float = 0.0
    vyaw: float = 0.0
    reason: str = "idle"

    @property
    def translating(self) -> bool:
        return math.hypot(self.vx, self.vy) > 1e-9


@dataclass(frozen=True)
class PatrolLimits:
    """Bounds. Every one of these is a refusal threshold, not a target."""

    budget_s: float = 120.0
    cruise_vx: float = 0.25
    turn_vyaw: float = 0.8
    #: Do not drive into a lane shorter than this. The reactive gate stops
    #: translation at ``obstacle_stop_m`` (0.65 m) and starts scaling it at
    #: ``obstacle_slow_m`` (1.2 m); commanding into anything under this
    #: threshold buys refused ticks, not distance.
    min_forward_clearance_m: float = 1.5
    #: Person standoff. The gate's ``person_stop_m`` is 1.2 m and the owner
    #: carries a further 0.55 m collision envelope; this is the *clearance*
    #: (already envelope-adjusted) below which the patrol turns away rather
    #: than be refused. E2-D2's exact failure.
    min_person_clearance_m: float = 1.35
    #: Hysteresis: once turning, keep turning until the lane is this much
    #: better than the threshold, so the patrol cannot chatter on the boundary.
    clearance_release_margin_m: float = 0.35
    #: A turn that has not found a lane in this long flips direction.
    turn_flip_after_s: float = 4.0
    #: Cap on one continuous turn, so a boxed-in patrol still ends.
    turn_giveup_after_s: float = 12.0

    def __post_init__(self) -> None:
        positive = (
            "budget_s",
            "cruise_vx",
            "turn_vyaw",
            "min_forward_clearance_m",
            "min_person_clearance_m",
            "turn_flip_after_s",
            "turn_giveup_after_s",
        )
        for name in positive:
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"PatrolLimits.{name} must be a number")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"PatrolLimits.{name} must be positive and finite")
        if not math.isfinite(self.clearance_release_margin_m) or self.clearance_release_margin_m < 0.0:
            raise ValueError("PatrolLimits.clearance_release_margin_m must be >= 0")
        if self.turn_flip_after_s > self.turn_giveup_after_s:
            raise ValueError("turn_flip_after_s must not exceed turn_giveup_after_s")


class PatrolPolicy:
    """Pure decision function plus its own small, explicit state.

    Ordering is a priority ladder and is part of the contract: budget, then
    contact, then people, then geometry, then hysteresis, then cruise.
    """

    def __init__(self, limits: PatrolLimits | None = None, *, turn_sign: int = 1) -> None:
        self.limits = limits or PatrolLimits()
        if turn_sign not in (-1, 1):
            raise ValueError("turn_sign must be -1 or 1")
        self._turn_sign = turn_sign
        self._turning_since: float | None = None

    @property
    def turning_since(self) -> float | None:
        return self._turning_since

    @property
    def turn_sign(self) -> int:
        return self._turn_sign

    @staticmethod
    def _person_blocks(sense: PatrolSense, threshold_m: float) -> bool:
        """Does the person stand between the patrol and where it wants to go?

        Distance alone is the wrong question, and asking it is what deadlocked
        the first live patrol (``patrol_city_block_20260822T034036Z``): a robot
        turning in place never changes its distance to a stationary owner, so a
        distance-only standoff can never release and the patrol spins out its
        whole budget. The product's own reactive gate asks about the travel
        DIRECTION (``reactive_safety._toward``); so does this.
        """

        clearance = sense.person_clearance_m
        if clearance is None or clearance >= threshold_m:
            return False
        bearing = sense.person_bearing_rad
        if bearing is None:
            return True  # unknown bearing fails closed
        wrapped = math.atan2(math.sin(bearing), math.cos(bearing))
        return abs(wrapped) < FORWARD_HALF_ANGLE_RAD

    def _turn(self, sense: PatrolSense, reason: str) -> PatrolCommand:
        limits = self.limits
        if self._turning_since is None:
            self._turning_since = sense.elapsed_s
        turning_for = sense.elapsed_s - self._turning_since
        if turning_for >= limits.turn_giveup_after_s:
            # Boxed in. Stop proposing; the runner ends the mission and the
            # report says why, rather than spinning out the whole budget.
            return PatrolCommand(reason="boxed_in")
        if turning_for >= limits.turn_flip_after_s:
            self._turn_sign = -self._turn_sign
            self._turning_since = sense.elapsed_s
        sign = self._turn_sign
        if reason == "turn_person" and sense.person_bearing_rad is not None:
            # Turn AWAY from the person rather than whichever way the counter
            # happens to point: a person to port is cleared by turning to
            # starboard, and the other way round takes the long way past them.
            bearing = math.atan2(
                math.sin(sense.person_bearing_rad), math.cos(sense.person_bearing_rad)
            )
            if bearing != 0.0:
                sign = -1 if bearing > 0.0 else 1
        return PatrolCommand(vyaw=limits.turn_vyaw * sign, reason=reason)

    def step(self, sense: PatrolSense) -> PatrolCommand:
        limits = self.limits
        if sense.elapsed_s >= limits.budget_s:
            self._turning_since = None
            return PatrolCommand(reason="budget_exhausted")
        if sense.collision:
            return self._turn(sense, "turn_contact")
        if self._person_blocks(sense, limits.min_person_clearance_m):
            return self._turn(sense, "turn_person")
        forward = sense.forward_clearance_m
        if forward is not None and forward < limits.min_forward_clearance_m:
            return self._turn(sense, "turn_blocked")
        if self._turning_since is not None:
            release = limits.min_forward_clearance_m + limits.clearance_release_margin_m
            person_release = limits.min_person_clearance_m + limits.clearance_release_margin_m
            forward_ok = forward is None or forward >= release
            person_ok = not self._person_blocks(sense, person_release)
            if not (forward_ok and person_ok):
                return self._turn(sense, "turn_hold")
            self._turning_since = None
        return PatrolCommand(vx=limits.cruise_vx, reason="advance")


@dataclass(frozen=True)
class PathSample:
    t_s: float
    x: float
    y: float
    yaw: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_s": round(self.t_s, 4),
            "x": round(self.x, 6),
            "y": round(self.y, 6),
            "yaw": round(self.yaw, 6),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MapGrowthSample:
    t_s: float
    entries: int
    labels: tuple[str, ...]
    frames_seen: int
    detections_seen: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_s": round(self.t_s, 4),
            "entries": self.entries,
            "labels": list(self.labels),
            "frames_seen": self.frames_seen,
            "detections_seen": self.detections_seen,
        }


@dataclass
class PatrolReport:
    scene: str
    budget_s: float
    elapsed_s: float = 0.0
    stopped_reason: str = "unknown"
    path: list[PathSample] = field(default_factory=list)
    map_growth: list[MapGrowthSample] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=dict)
    submitted: int = 0
    refused: int = 0
    collision_ticks: int = 0

    @property
    def path_length_m(self) -> float:
        total = 0.0
        for before, after in zip(self.path, self.path[1:], strict=False):
            total += math.hypot(after.x - before.x, after.y - before.y)
        return total

    @property
    def net_displacement_m(self) -> float:
        if len(self.path) < 2:
            return 0.0
        return math.hypot(self.path[-1].x - self.path[0].x, self.path[-1].y - self.path[0].y)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "budget_s": self.budget_s,
            "elapsed_s": round(self.elapsed_s, 4),
            "stopped_reason": self.stopped_reason,
            "path_length_m": round(self.path_length_m, 6),
            "net_displacement_m": round(self.net_displacement_m, 6),
            "path_samples": len(self.path),
            "reasons": dict(sorted(self.reasons.items())),
            "submitted": self.submitted,
            "refused": self.refused,
            "collision_ticks": self.collision_ticks,
            "map_entries_final": (
                self.map_growth[-1].entries if self.map_growth else 0
            ),
            "map_labels_final": (
                list(self.map_growth[-1].labels) if self.map_growth else []
            ),
            "path": [sample.as_dict() for sample in self.path],
            "map_growth": [sample.as_dict() for sample in self.map_growth],
        }


def forward_clearance_from_scan(
    ranges: Sequence[float],
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    range_max_m: float | None = None,
    half_angle_rad: float = FORWARD_HALF_ANGLE_RAD,
) -> float | None:
    """Shortest ray inside the body-forward cone, or ``None`` if none is valid.

    NaN rays are ignored (dropout / self-return), matching the scan contract;
    a cone with no valid ray returns ``None``, which the policy treats as
    "unknown", never as "clear".
    """

    if not ranges or not math.isfinite(angle_increment_rad) or angle_increment_rad == 0.0:
        return None
    best: float | None = None
    for index, value in enumerate(ranges):
        try:
            distance = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(distance) or not math.isfinite(distance):
            continue
        if range_max_m is not None and distance >= range_max_m:
            continue
        angle = angle_min_rad + index * angle_increment_rad
        angle = math.atan2(math.sin(angle), math.cos(angle))
        if abs(angle) >= half_angle_rad:
            continue
        if best is None or distance < best:
            best = distance
    return best


def sense_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    elapsed_s: float,
    owner_envelope_m: float = 0.55,
) -> PatrolSense | None:
    """Build a :class:`PatrolSense` from the runtime's public state snapshot.

    Returns ``None`` when the snapshot carries no robot pose — an absent pose
    is not a pose at the origin, and the runner must not drive on one.
    """

    robot = snapshot.get("robot")
    if not isinstance(robot, Mapping):
        return None
    try:
        x = float(robot["x"])
        y = float(robot["y"])
        # ``RobotRuntime.snapshot`` publishes the heading in DEGREES
        # (``runtime.py``: ``"heading": math.degrees(observation.robot.yaw)``).
        # Reading it as radians silently corrupts every bearing computed from
        # it — measured on a live patrol, which produced a "bearing" of
        # -81.9 rad and a person predicate that decided nothing.
        yaw = math.radians(float(robot.get("heading", 0.0)))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x, y, yaw)):
        return None

    forward: float | None = None
    scan = snapshot.get("lidar_scan")
    if isinstance(scan, Mapping) and isinstance(scan.get("ranges"), Sequence):
        forward = forward_clearance_from_scan(
            scan["ranges"],
            angle_min_rad=float(scan.get("angle_min_rad", -math.pi)),
            angle_increment_rad=float(scan.get("angle_increment_rad", 0.0)),
            range_max_m=(
                float(scan["range_max_m"]) if scan.get("range_max_m") is not None else None
            ),
        )
    if forward is None:
        obstacle = snapshot.get("obstacle_distance_m")
        if isinstance(obstacle, (int, float)) and not isinstance(obstacle, bool):
            forward = float(obstacle)

    # People, including the owner. The owner is a person for standoff purposes
    # and carries an extra collision envelope; forgetting that is exactly what
    # parked C-1's robot 0.31 m from the origin.
    clearances: list[tuple[float, float | None]] = []
    nearest = snapshot.get("nearest_person")
    if isinstance(nearest, Mapping):
        distance = nearest.get("distance_m")
        if isinstance(distance, (int, float)) and not isinstance(distance, bool):
            bearing = nearest.get("bearing_rad")
            clearances.append(
                (
                    float(distance),
                    float(bearing)
                    if isinstance(bearing, (int, float))
                    and not isinstance(bearing, bool)
                    else None,
                )
            )
    owner = snapshot.get("owner")
    if isinstance(owner, Mapping) and owner.get("visible"):
        try:
            owner_dx = float(owner["x"]) - x
            owner_dy = float(owner["y"]) - y
        except (KeyError, TypeError, ValueError):
            owner_dx = owner_dy = None
        if owner_dx is not None and owner_dy is not None:
            owner_distance = math.hypot(owner_dx, owner_dy)
            if math.isfinite(owner_distance):
                clearances.append(
                    (
                        max(0.0, owner_distance - owner_envelope_m),
                        math.atan2(owner_dy, owner_dx) - yaw,
                    )
                )

    # Keyed on distance: a tuple compare would reach the bearing on a tie
    # and raise when one of them is None.
    nearest_person = (
        min(clearances, key=lambda item: item[0]) if clearances else (None, None)
    )
    return PatrolSense(
        elapsed_s=elapsed_s,
        x=x,
        y=y,
        yaw=yaw,
        forward_clearance_m=forward,
        person_clearance_m=nearest_person[0] if clearances else None,
        person_bearing_rad=nearest_person[1] if clearances else None,
        collision=bool(snapshot.get("collision")),
    )


class PatrolRunner:
    """Drives one bounded patrol and returns its record.

    Deliberately I/O-only: it owns the clock, the submit call and the two
    recorders, and delegates every decision to :class:`PatrolPolicy`.
    """

    def __init__(
        self,
        *,
        scene: str,
        sense_provider: Callable[[float], PatrolSense | None],
        submit: Callable[[PatrolCommand], bool],
        map_probe: Callable[[], MapGrowthSample] | None = None,
        policy: PatrolPolicy | None = None,
        limits: PatrolLimits | None = None,
        tick_s: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if tick_s <= 0.0 or not math.isfinite(tick_s):
            raise ValueError("tick_s must be positive and finite")
        self.scene = scene
        self.limits = limits or (policy.limits if policy else PatrolLimits())
        self.policy = policy or PatrolPolicy(self.limits)
        self._sense_provider = sense_provider
        self._submit = submit
        self._map_probe = map_probe
        self._tick_s = tick_s
        self._clock = clock
        self._sleep = sleep

    def run(self) -> PatrolReport:
        report = PatrolReport(scene=self.scene, budget_s=self.limits.budget_s)
        started = self._clock()
        stopped_reason = "budget_exhausted"
        while True:
            elapsed = self._clock() - started
            if elapsed >= self.limits.budget_s:
                stopped_reason = "budget_exhausted"
                break
            sense = self._sense_provider(elapsed)
            if sense is None:
                # No pose this tick. Do not drive blind, do not end the
                # mission on one gap; skip and let the budget run.
                report.reasons["no_sense"] = report.reasons.get("no_sense", 0) + 1
                self._sleep(self._tick_s)
                continue
            if sense.collision:
                report.collision_ticks += 1
            command = self.policy.step(sense)
            report.reasons[command.reason] = report.reasons.get(command.reason, 0) + 1
            report.path.append(
                PathSample(
                    t_s=sense.elapsed_s,
                    x=sense.x,
                    y=sense.y,
                    yaw=sense.yaw,
                    reason=command.reason,
                )
            )
            if self._map_probe is not None:
                report.map_growth.append(
                    replace(self._map_probe(), t_s=sense.elapsed_s)
                )
            if command.reason == "boxed_in":
                stopped_reason = "boxed_in"
                break
            if command.reason == "budget_exhausted":
                stopped_reason = "budget_exhausted"
                break
            report.submitted += 1
            if not self._submit(command):
                report.refused += 1
            self._sleep(self._tick_s)
        report.elapsed_s = self._clock() - started
        report.stopped_reason = stopped_reason
        return report
