from __future__ import annotations

import math
import re
import time
from dataclasses import asdict, dataclass

from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE
from parcel_robot.backends.base import SimObservation
from parcel_robot.models import SpatialIntent, VelocityCommand
from parcel_robot.navigation.orbit_feasibility import (
    OrbitFeasibility,
    evaluate_orbit_annulus,
)

NUMBER_WORDS = {
    "once": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


@dataclass(frozen=True)
class SpatialBehaviorConfig:
    step_length_m: float = 0.25
    max_steps: int = 12
    default_orbit_radius_m: float = 1.6
    min_orbit_radius_m: float = 1.3
    max_orbit_radius_m: float = 2.0
    max_revolutions: float = 1.0
    owner_collision_envelope_m: float = 0.55
    orbit_clearance_margin_m: float = 0.10
    owner_anchor_tolerance_m: float = 0.60
    linear_speed_mps: float = 0.28
    max_yaw_rate: float = 0.7
    yaw_gain: float = 1.4
    align_enter_deg: float = 25.0
    align_exit_deg: float = 8.0
    waypoint_tolerance_m: float = 0.16
    owner_confidence_min: float = 0.6
    stall_timeout_s: float = 20.0
    timeout_s: float = 120.0
    #: Card R10. How far AHEAD along the ring the mid-orbit feasibility check
    #: looks, in degrees. 60 deg at the 1.6 m default radius is 1.68 m of arc —
    #: about six seconds at the 0.28 m/s orbit speed, which is enough warning to
    #: stop and SAY something rather than stall into ``spatial_stalled``.
    orbit_lookahead_deg: float = 60.0

    def __post_init__(self) -> None:
        positive = (
            self.step_length_m,
            self.default_orbit_radius_m,
            self.min_orbit_radius_m,
            self.max_orbit_radius_m,
            self.max_revolutions,
            self.owner_collision_envelope_m,
            self.orbit_clearance_margin_m,
            self.owner_anchor_tolerance_m,
            self.linear_speed_mps,
            self.max_yaw_rate,
            self.yaw_gain,
            self.waypoint_tolerance_m,
            self.stall_timeout_s,
            self.timeout_s,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ValueError("spatial behavior limits must be positive and finite")
        if not math.isfinite(self.orbit_lookahead_deg) or not 0.0 < self.orbit_lookahead_deg <= 360.0:
            raise ValueError("spatial orbit_lookahead_deg must be within (0, 360]")
        if self.max_steps <= 0:
            raise ValueError("spatial max_steps must be positive")
        if not self.min_orbit_radius_m <= self.default_orbit_radius_m <= self.max_orbit_radius_m:
            raise ValueError("default orbit radius must be within configured bounds")
        if not 0.0 <= self.owner_confidence_min <= 1.0:
            raise ValueError("owner confidence threshold must be between zero and one")
        if not 0.0 < self.align_exit_deg < self.align_enter_deg < 180.0:
            raise ValueError("spatial alignment thresholds are invalid")

    def minimum_safe_orbit_radius(self, obstacle_stop_m: float) -> float:
        """Return a center-to-center radius compatible with the reactive brake."""

        if not math.isfinite(obstacle_stop_m) or obstacle_stop_m <= 0.0:
            raise ValueError("obstacle stop distance must be positive and finite")
        return obstacle_stop_m + self.owner_collision_envelope_m + self.orbit_clearance_margin_m


@dataclass(frozen=True)
class SpatialDecision:
    command: VelocityCommand
    done: bool
    state: str
    reason: str
    progress: float = 0.0


def parse_spatial_intent(text: str) -> SpatialIntent | None:
    """Parse high-confidence relative commands before invoking an LLM."""

    clean = _imperative_body(text)
    if clean is None:
        return None

    away = re.fullmatch(
        r"(?:walk|move|go|back|take)"
        r"(?:\s+(?P<count_before>[a-z0-9]+)\s+steps?)?\s+away\s+from\s+"
        r"(?:me|owner|the owner)(?:(?:\s+by|\s+for)?\s+"
        r"(?P<count_after>[a-z0-9]+)\s+steps?)?",
        clean,
    )
    if away:
        count = _step_count(
            away.group("count_before") or away.group("count_after"),
            default=3,
        )
        if count is None:
            return None
        return SpatialIntent("move_steps", "away_from_owner", steps=count)

    orbit = re.fullmatch(
        r"(?:walk|move|go)(?:\s+in)?\s+(?:a\s+)?"
        r"(?:(?P<size>small|tight|wide)\s+)?"
        r"(?:(?P<direction_before>clockwise|counterclockwise)\s+)?circles?"
        r"(?:\s+(?P<direction_after>clockwise|counterclockwise))?\s+around\s+"
        r"(?:me|owner|the owner)"
        r"(?:\s+(?P<count>[a-z0-9]+)(?:\s+(?:times?|circles?))?)?",
        clean,
    )
    if orbit:
        size_word = orbit.group("size") or "normal"
        size = "small" if size_word == "tight" else size_word
        direction = (
            orbit.group("direction_before") or orbit.group("direction_after") or "counterclockwise"
        )
        count = _step_count(orbit.group("count"), default=1)
        if count != 1:
            return None
        return SpatialIntent(
            "orbit_owner",
            direction,
            size=size,
            revolutions=1.0,
        )

    around_owner = re.fullmatch(
        r"(?:walk|move|go)\s+around\s+(?:me|owner|the owner)"
        r"(?:\s+(?P<count>[a-z0-9]+)(?:\s+times?)?)?",
        clean,
    )
    if around_owner:
        count = _step_count(around_owner.group("count"), default=1)
        if count != 1:
            return None
        return SpatialIntent(
            "orbit_owner",
            "counterclockwise",
            size="normal",
            revolutions=1.0,
        )

    # Product-bar orbit phrasings: "circle around the owner", "orbit the owner",
    # "circle me" — must exercise the regression lane (task_6 arbitration).
    orbit_short = re.fullmatch(
        r"(?:circle|orbit)(?:\s+around)?\s+(?:me|owner|the owner)"
        r"(?:\s+(?P<count>[a-z0-9]+)(?:\s+(?:times?|circles?))?)?",
        clean,
    )
    if orbit_short:
        count = _step_count(orbit_short.group("count"), default=1)
        if count != 1:
            return None
        return SpatialIntent(
            "orbit_owner",
            "counterclockwise",
            size="normal",
            revolutions=1.0,
        )

    steps = re.fullmatch(
        r"(?:walk|move|go|take)\s+"
        r"(?:(?P<before>[a-z0-9]+)\s+steps?\s+)?"
        r"(?P<direction>forward|backward|back)"
        r"(?:\s+(?P<after>[a-z0-9]+)\s+steps?)?",
        clean,
    )
    if steps:
        count = _step_count(steps.group("before") or steps.group("after"), default=3)
        if count is None:
            return None
        direction = "backward" if steps.group("direction") in {"back", "backward"} else "forward"
        return SpatialIntent("move_steps", direction, steps=count)
    return None


def parse_follow_intent(text: str) -> bool:
    """True when the utterance is a high-confidence follow-owner command."""

    clean = _imperative_body(text)
    if clean is None:
        return False
    return (
        re.fullmatch(
            r"(?:follow(?:\s+(?:me|owner|the owner))?|"
            r"come\s+with\s+me|"
            r"stay\s+with(?:\s+(?:me|the owner|owner))?|"
            r"heel)",
            clean,
        )
        is not None
    )


def _imperative_body(text: str) -> str | None:
    raw = " ".join(str(text).lower().split())
    if not raw:
        return None
    if re.search(
        r"\b(?:do\s+not|don[' ]?t|never|not|should\s+not|shouldn[' ]?t|"
        r"must\s+not|mustn[' ]?t|cannot|can[' ]?t)\b",
        raw,
    ):
        return None
    clean = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    if re.match(
        r"^(?:what|why|how|when|where|if|suppose|imagine|pretend|describe|"
        r"tell me)\b",
        clean,
    ):
        return None
    clean = re.sub(r"^(?:hey\s+)?parcel\s+", "", clean, count=1)
    polite_prefixes = (
        r"^(?:please\s+)?(?:can|could|would|will)\s+you\s+(?:please\s+)?",
        r"^(?:please\s+)?i\s+(?:want|need)\s+you\s+to\s+",
        r"^(?:please\s+)?i\s+(?:d|would)\s+like\s+you\s+to\s+",
        r"^(?:please|kindly)\s+",
    )
    for prefix in polite_prefixes:
        updated = re.sub(prefix, "", clean, count=1)
        if updated != clean:
            clean = updated
            break
    clean = re.sub(r"\s+(?:please|thanks|thank you)$", "", clean).strip()
    return clean or None


def spatial_intent_from_arguments(arguments: dict[str, object]) -> SpatialIntent:
    behavior = str(arguments.get("behavior", ""))
    direction = str(arguments.get("direction", ""))
    if behavior == "move_steps":
        return SpatialIntent(
            behavior=behavior,
            direction=direction,
            steps=int(arguments.get("steps", 0)),
        )
    return SpatialIntent(
        behavior=behavior,
        direction=direction,
        size=str(arguments.get("size", "normal")),
        revolutions=float(arguments.get("revolutions", 1.0)),
    )


class SpatialBehaviorController:
    """Compile bounded owner/body-relative intents into safe velocity requests."""

    def __init__(self, config: SpatialBehaviorConfig | None = None):
        self.config = config or SpatialBehaviorConfig()
        self._intent: SpatialIntent | None = None
        self._started_at = 0.0
        self._start_x = 0.0
        self._start_y = 0.0
        self._heading = 0.0
        self._travel_heading = 0.0
        self._target_distance = 0.0
        self._center = (0.0, 0.0)
        self._owner_anchor: tuple[float, float] | None = None
        self._orbit_radius = 0.0
        self._orbit_phase = "idle"
        self._orbit_start_angle = 0.0
        self._last_angle = 0.0
        self._last_orbit_on_ring = False
        self._orbit_progress = 0.0
        self._aligning = True
        self._last_motion_at = 0.0
        self._last_motion_pose = (0.0, 0.0, 0.0)
        #: Card R10. The last infeasibility verdict, admission or mid-orbit, so
        #: the runtime can NARRATE why the circle stopped instead of the owner
        #: watching the dog give up in silence.
        self._last_refusal: OrbitFeasibility | None = None
        self._last_refusal_sentence = ""

    @property
    def active(self) -> bool:
        return self._intent is not None

    @property
    def last_refusal_sentence(self) -> str:
        return self._last_refusal_sentence

    # ------------------------------------------------------- feasibility (R10)
    def orbit_radius_for(self, intent: SpatialIntent) -> float:
        """The ring radius ``start`` would pick for this intent. Pure."""

        requested = {
            "small": self.config.min_orbit_radius_m,
            "normal": self.config.default_orbit_radius_m,
            "wide": self.config.max_orbit_radius_m,
        }.get(str(intent.size or "normal"), self.config.default_orbit_radius_m)
        return min(
            self.config.max_orbit_radius_m,
            max(self.config.min_orbit_radius_m, requested),
        )

    def assess_orbit(
        self,
        intent: SpatialIntent,
        observation: SimObservation,
        *,
        obstacle_stop_m: float,
    ) -> OrbitFeasibility:
        """Admission-time affordance test for an owner orbit — card R10 item 5.

        Called BEFORE :meth:`start`, so an impossible circle is refused with a
        sentence the owner can act on instead of being started and abandoned.
        This is SayCan's "Can" half computed locally: once ``circle_owner``
        exists on the hosted tool surface, "I can't walk around you here" has to
        be produced by geometry, because the bench measured the model both
        fabricating capability and falsely denying it.

        Never raises, never moves anything, never relaxes a keepout: it reports.
        """

        if intent.behavior != "orbit_owner":
            return OrbitFeasibility(feasible=True)
        owner = observation.owner
        centre: tuple[float, float] | None = None
        if owner.visible and owner.confidence >= self.config.owner_confidence_min:
            centre = (float(owner.x), float(owner.y))
        radius = self.orbit_radius_for(intent)
        verdict = evaluate_orbit_annulus(
            centre=centre,
            radius_m=radius,
            clearance_m=self._ring_clearance_m(),
            blocked_points=_surface_points(observation, exclude=centre),
            keepouts=_keepout_discs(observation, exclude=centre),
            arc_sweep_deg=360.0 * min(1.0, float(intent.revolutions or 1.0)),
            arc_start_deg=_ring_start_deg(observation, centre),
        )
        self._remember_refusal(verdict, observation, centre)
        return verdict

    def _ring_clearance_m(self) -> float:
        """Centre-to-surface clearance a ring sample must keep: DOES THE BODY FIT.

        Deliberately the FIT distance (footprint radius + the config's own orbit
        clearance margin) and deliberately NOT the reactive gate's stopping
        distance. The distinction is load-bearing and was measured, not guessed:
        the first draft of this check used the gate's brake distance and aborted
        ``test_orbit_the_owner_completes_one_revolution`` at 32% progress — an
        orbit the live sim completes with zero collisions. The gate is a speed
        governor; it slows the body near surfaces and that is correct behaviour,
        not an impossibility. Refusing every orbit the gate would slow for is a
        FALSE refusal, and a false "I can't walk around you here" is exactly the
        dishonesty this validator exists to prevent — the bench caught the model
        making that same false claim (``bench_navmodel.md`` §6, A3).

        So: refuse only when the body physically cannot occupy the ring.
        """

        return (
            DEFAULT_SAFETY_ENVELOPE.footprint_radius_m + self.config.orbit_clearance_margin_m
        )

    def _remember_refusal(
        self,
        verdict: OrbitFeasibility,
        observation: SimObservation,
        centre: tuple[float, float] | None,
    ) -> None:
        if verdict.feasible:
            self._last_refusal = None
            self._last_refusal_sentence = ""
            return
        self._last_refusal = verdict
        self._last_refusal_sentence = verdict.refusal_sentence(
            reference_deg=_owner_reference_deg(observation, centre)
        )

    def start(
        self,
        intent: SpatialIntent,
        observation: SimObservation,
        *,
        now: float | None = None,
    ) -> dict[str, object]:
        self._validate_intent(intent)
        timestamp = time.monotonic() if now is None else now
        robot = observation.robot
        self._intent = intent
        self._started_at = timestamp
        self._start_x = robot.x
        self._start_y = robot.y
        self._heading = robot.yaw
        self._aligning = True
        self._orbit_progress = 0.0
        self._last_orbit_on_ring = False
        self._owner_anchor = None
        self._last_motion_at = timestamp
        self._last_motion_pose = (robot.x, robot.y, robot.yaw)

        if intent.behavior == "move_steps":
            self._target_distance = intent.steps * self.config.step_length_m
            if intent.direction == "away_from_owner":
                self._require_owner(observation)
                self._owner_anchor = (observation.owner.x, observation.owner.y)
                self._heading = math.atan2(
                    observation.owner.y - robot.y,
                    observation.owner.x - robot.x,
                )
                self._travel_heading = _wrap(self._heading + math.pi)
            elif intent.direction == "backward":
                self._travel_heading = _wrap(robot.yaw + math.pi)
            else:
                self._travel_heading = robot.yaw
            self._orbit_phase = "idle"
        else:
            self._require_owner(observation)
            self._center = (observation.owner.x, observation.owner.y)
            self._owner_anchor = self._center
            dx = robot.x - self._center[0]
            dy = robot.y - self._center[1]
            distance = math.hypot(dx, dy)
            self._orbit_start_angle = (
                math.atan2(dy, dx) if distance > 0.1 else _wrap(robot.yaw + math.pi)
            )
            self._last_angle = self._orbit_start_angle
            requested = {
                "small": self.config.min_orbit_radius_m,
                "normal": self.config.default_orbit_radius_m,
                "wide": self.config.max_orbit_radius_m,
            }[intent.size]
            self._orbit_radius = min(
                self.config.max_orbit_radius_m,
                max(self.config.min_orbit_radius_m, requested),
            )
            self._orbit_phase = (
                "orbit"
                if abs(distance - self._orbit_radius) <= self.config.waypoint_tolerance_m
                else "approach_ring"
            )
            self._last_orbit_on_ring = self._orbit_phase == "orbit"
        return self.snapshot()

    def stop(self) -> None:
        self._intent = None
        self._orbit_phase = "idle"
        self._orbit_progress = 0.0
        self._last_orbit_on_ring = False
        self._aligning = True
        self._owner_anchor = None

    def step(
        self,
        observation: SimObservation,
        *,
        now: float | None = None,
    ) -> SpatialDecision:
        intent = self._intent
        if intent is None:
            return SpatialDecision(VelocityCommand(), True, "idle", "no_spatial_behavior")
        timestamp = time.monotonic() if now is None else now
        if timestamp - self._started_at >= self.config.timeout_s:
            return SpatialDecision(VelocityCommand(), True, "failed", "spatial_timeout")
        if intent.direction == "away_from_owner" or intent.behavior == "orbit_owner":
            try:
                self._require_owner(observation)
            except RuntimeError as error:
                return SpatialDecision(VelocityCommand(), True, "failed", str(error))
            if self._owner_moved(observation):
                return SpatialDecision(
                    VelocityCommand(),
                    True,
                    "failed",
                    "owner_moved_during_spatial_behavior",
                )
        if self._motion_stalled(observation, timestamp):
            return SpatialDecision(VelocityCommand(), True, "failed", "spatial_stalled")
        if intent.behavior == "move_steps":
            return self._step_distance(observation)
        return self._step_orbit(observation)

    def snapshot(self) -> dict[str, object]:
        intent = self._intent
        return {
            "enabled": intent is not None,
            "state": self._orbit_phase
            if intent and intent.behavior == "orbit_owner"
            else ("moving" if intent else "idle"),
            "intent": asdict(intent) if intent else None,
            "target_distance_m": round(self._target_distance, 3) if intent else None,
            "orbit_radius_m": round(self._orbit_radius, 3)
            if intent and intent.behavior == "orbit_owner"
            else None,
            "progress": round(self._orbit_progress, 4) if intent else 0.0,
        }

    def _step_distance(self, observation: SimObservation) -> SpatialDecision:
        assert self._intent is not None
        robot = observation.robot
        dx = robot.x - self._start_x
        dy = robot.y - self._start_y
        progress_m = max(
            0.0,
            dx * math.cos(self._travel_heading) + dy * math.sin(self._travel_heading),
        )
        fraction = min(1.0, progress_m / max(self._target_distance, 1e-6))
        if progress_m >= self._target_distance - 0.04:
            return SpatialDecision(VelocityCommand(), True, "completed", "distance_reached", 1.0)
        heading_error = _angle_error(self._heading, robot.yaw)
        if self._alignment_required(heading_error):
            return SpatialDecision(
                VelocityCommand(vyaw=self._yaw_command(heading_error)),
                False,
                "aligning",
                "align_before_relative_motion",
                fraction,
            )
        remaining = self._target_distance - progress_m
        speed = min(self.config.linear_speed_mps, max(0.10, remaining * 0.7))
        sign = -1.0 if self._intent.direction in {"backward", "away_from_owner"} else 1.0
        return SpatialDecision(
            VelocityCommand(vx=sign * speed, vyaw=self._yaw_command(heading_error)),
            False,
            "moving",
            "bounded_step_motion",
            fraction,
        )

    def _step_orbit(self, observation: SimObservation) -> SpatialDecision:
        assert self._intent is not None
        robot = observation.robot
        dx = robot.x - self._center[0]
        dy = robot.y - self._center[1]
        distance = math.hypot(dx, dy)
        angle = math.atan2(dy, dx) if distance > 0.05 else self._last_angle
        direction_sign = -1.0 if self._intent.direction == "clockwise" else 1.0

        if self._orbit_phase == "approach_ring":
            goal_x = self._center[0] + self._orbit_radius * math.cos(self._orbit_start_angle)
            goal_y = self._center[1] + self._orbit_radius * math.sin(self._orbit_start_angle)
            goal_distance = math.hypot(goal_x - robot.x, goal_y - robot.y)
            if goal_distance <= self.config.waypoint_tolerance_m:
                self._orbit_phase = "orbit"
                self._last_angle = angle
                self._last_orbit_on_ring = (
                    abs(distance - self._orbit_radius) <= self.config.waypoint_tolerance_m
                )
                self._aligning = True
            else:
                target_heading = math.atan2(goal_y - robot.y, goal_x - robot.x)
                return self._track_point(
                    target_heading,
                    robot.yaw,
                    goal_distance,
                    "approach_orbit_ring",
                    0.0,
                )

        on_ring = abs(distance - self._orbit_radius) <= self.config.waypoint_tolerance_m
        delta = _wrap(angle - self._last_angle)
        if self._last_orbit_on_ring and on_ring and abs(delta) < math.pi / 2.0:
            # Net signed phase prevents back-and-forth motion from looking like
            # repeated forward progress. Samples outside the requested radial
            # corridor establish a new phase baseline but receive no orbit credit.
            self._orbit_progress += direction_sign * delta
        self._last_angle = angle
        self._last_orbit_on_ring = on_ring
        target_progress = self._intent.revolutions * 2.0 * math.pi
        fraction = max(
            0.0,
            min(1.0, self._orbit_progress / max(target_progress, 1e-6)),
        )
        finish_angle = _wrap(self._orbit_start_angle + direction_sign * target_progress)
        finish_x = self._center[0] + self._orbit_radius * math.cos(finish_angle)
        finish_y = self._center[1] + self._orbit_radius * math.sin(finish_angle)
        finish_distance = math.hypot(robot.x - finish_x, robot.y - finish_y)
        finish_angle_tolerance = 2.0 * math.asin(
            min(1.0, self.config.waypoint_tolerance_m / (2.0 * self._orbit_radius))
        )
        if (
            self._orbit_progress >= target_progress - finish_angle_tolerance
            and finish_distance <= self.config.waypoint_tolerance_m
        ):
            return SpatialDecision(VelocityCommand(), True, "completed", "orbit_complete", 1.0)

        # Card R10 item 5 — mid-orbit abort WITH narration. The ring the orbit is
        # about to walk is re-tested every tick over a bounded lookahead arc. A
        # person who steps into the path used to produce nothing but a silent
        # 20 s ``spatial_stalled`` timeout; now it ends the behaviour with a
        # cause and a sentence the runtime can say. The check only ever STOPS
        # motion — it can never widen the ring, weaken a keepout, or continue an
        # orbit the geometry refuses.
        ahead = self._lookahead_feasibility(observation, angle, direction_sign)
        if ahead is not None and not ahead.feasible:
            return SpatialDecision(
                VelocityCommand(),
                True,
                "failed",
                ahead.cause or "orbit_annulus_blocked",
                fraction,
            )

        lookahead_angle = angle + direction_sign * 0.34
        target_x = self._center[0] + self._orbit_radius * math.cos(lookahead_angle)
        target_y = self._center[1] + self._orbit_radius * math.sin(lookahead_angle)
        target_heading = math.atan2(target_y - robot.y, target_x - robot.x)
        decision = self._track_point(
            target_heading,
            robot.yaw,
            math.hypot(target_x - robot.x, target_y - robot.y),
            "orbit_owner",
            fraction,
        )
        return SpatialDecision(
            decision.command,
            decision.done,
            "orbiting" if decision.state == "moving" else decision.state,
            decision.reason,
            fraction,
        )

    def _lookahead_feasibility(
        self,
        observation: SimObservation,
        angle: float,
        direction_sign: float,
    ) -> OrbitFeasibility | None:
        """Feasibility of the arc immediately ahead, or ``None`` when unknowable.

        ``None`` (rather than "infeasible") when there is nothing to test — no
        surfaces and no tracks — so a sensor-quiet tick never manufactures a
        refusal. Absence of evidence is reported as absence, which is the same
        polarity ``_pose_uncertainty_m`` uses one module over.
        """

        centre = self._center
        surfaces = _surface_points(observation, exclude=centre)
        keepouts = _keepout_discs(observation, exclude=centre)
        if not surfaces and not keepouts:
            return None
        sweep = float(self.config.orbit_lookahead_deg)
        start = math.degrees(angle)
        if direction_sign < 0.0:
            start -= sweep
        verdict = evaluate_orbit_annulus(
            centre=centre,
            radius_m=self._orbit_radius,
            clearance_m=self._ring_clearance_m(),
            blocked_points=surfaces,
            keepouts=keepouts,
            arc_start_deg=start,
            arc_sweep_deg=sweep,
        )
        self._remember_refusal(verdict, observation, centre)
        return verdict

    def _track_point(
        self,
        target_heading: float,
        current_heading: float,
        distance: float,
        reason: str,
        progress: float,
    ) -> SpatialDecision:
        heading_error = _angle_error(target_heading, current_heading)
        if self._alignment_required(heading_error):
            return SpatialDecision(
                VelocityCommand(vyaw=self._yaw_command(heading_error)),
                False,
                "aligning",
                reason,
                progress,
            )
        speed = min(self.config.linear_speed_mps, max(0.10, distance * 0.8))
        return SpatialDecision(
            VelocityCommand(vx=speed, vyaw=self._yaw_command(heading_error)),
            False,
            "moving",
            reason,
            progress,
        )

    def _alignment_required(self, heading_error: float) -> bool:
        degrees = abs(math.degrees(heading_error))
        if self._aligning and degrees <= self.config.align_exit_deg:
            self._aligning = False
        elif not self._aligning and degrees >= self.config.align_enter_deg:
            self._aligning = True
        return self._aligning

    def _yaw_command(self, heading_error: float) -> float:
        return max(
            -self.config.max_yaw_rate,
            min(self.config.max_yaw_rate, heading_error * self.config.yaw_gain),
        )

    def _require_owner(self, observation: SimObservation) -> None:
        owner = observation.owner
        if not owner.visible or owner.confidence < self.config.owner_confidence_min:
            raise RuntimeError("owner_not_visible_to_camera")

    def _owner_moved(self, observation: SimObservation) -> bool:
        if self._owner_anchor is None:
            return False
        return (
            math.hypot(
                observation.owner.x - self._owner_anchor[0],
                observation.owner.y - self._owner_anchor[1],
            )
            > self.config.owner_anchor_tolerance_m
        )

    def _motion_stalled(self, observation: SimObservation, timestamp: float) -> bool:
        previous_x, previous_y, previous_yaw = self._last_motion_pose
        robot = observation.robot
        translated = math.hypot(robot.x - previous_x, robot.y - previous_y) >= 0.025
        rotated = abs(_angle_error(robot.yaw, previous_yaw)) >= math.radians(2.0)
        if translated or rotated:
            self._last_motion_pose = (robot.x, robot.y, robot.yaw)
            self._last_motion_at = timestamp
            return False
        return timestamp - self._last_motion_at >= self.config.stall_timeout_s

    def _validate_intent(self, intent: SpatialIntent) -> None:
        if intent.behavior == "move_steps":
            if intent.direction not in {"forward", "backward", "away_from_owner"}:
                raise ValueError("unsupported step direction")
            if isinstance(intent.steps, bool) or not 1 <= intent.steps <= self.config.max_steps:
                raise ValueError(f"steps must be between 1 and {self.config.max_steps}")
            return
        if intent.behavior != "orbit_owner":
            raise ValueError("unsupported spatial behavior")
        if intent.direction not in {"clockwise", "counterclockwise"}:
            raise ValueError("unsupported orbit direction")
        if intent.size not in {"small", "normal", "wide"}:
            raise ValueError("unsupported orbit size")
        if not 0.25 <= intent.revolutions <= self.config.max_revolutions:
            raise ValueError("orbit revolutions are outside the safe range")


#: How close a surface/track has to be to the orbit centre to be treated as the
#: OWNER rather than an obstacle. The owner is the thing being circled; counting
#: their own body as a blocker would refuse every orbit ever requested.
_OWNER_MATCH_M = 0.6


def _surface_points(
    observation: SimObservation,
    *,
    exclude: tuple[float, float] | None,
) -> tuple[tuple[str, float, float], ...]:
    """Polar LiDAR returns lifted into MAP-frame surface points."""

    robot = observation.robot
    points: list[tuple[str, float, float]] = []
    for item in observation.lidar_obstacles[:64]:
        try:
            distance = float(item.distance_m)
            bearing = float(item.bearing_rad)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(distance) or not math.isfinite(bearing) or distance < 0.0:
            continue
        # The LiDAR contract reports FOOTPRINT-to-surface clearance, not range
        # from the body centre — the same lift ``approach._observed_obstacle_points``
        # performs. Omitting it put every surface 0.32 m too close to the robot
        # and was half of why the first draft of this check false-refused a
        # perfectly good orbit.
        ray = distance + DEFAULT_SAFETY_ENVELOPE.footprint_radius_m
        theta = robot.yaw + bearing
        x = robot.x + ray * math.cos(theta)
        y = robot.y + ray * math.sin(theta)
        if exclude is not None and math.hypot(x - exclude[0], y - exclude[1]) <= _OWNER_MATCH_M:
            continue
        points.append((str(item.obstacle_id or "something"), x, y))
    return tuple(points)


def _keepout_discs(
    observation: SimObservation,
    *,
    exclude: tuple[float, float] | None,
) -> tuple[tuple[str, float, float, float], ...]:
    """Dynamic agents as keepout discs. People are never ring surface."""

    discs: list[tuple[str, float, float, float]] = []
    for track in observation.dynamic_agents[:32]:
        try:
            x = float(track.x)
            y = float(track.y)
            radius = float(track.radius_m)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(radius)):
            continue
        if radius <= 0.0:
            continue
        if exclude is not None and math.hypot(x - exclude[0], y - exclude[1]) <= _OWNER_MATCH_M:
            continue
        label = "someone" if str(track.kind or "").lower() in {"person", "pedestrian"} else "something"
        discs.append((label, x, y, radius))
    return tuple(discs)


def _ring_start_deg(
    observation: SimObservation,
    centre: tuple[float, float] | None,
) -> float:
    """Where the ring sweep begins: the robot's own bearing about the centre."""

    if centre is None:
        return 0.0
    robot = observation.robot
    dx = robot.x - centre[0]
    dy = robot.y - centre[1]
    if math.hypot(dx, dy) <= 1e-6:
        return 0.0
    return math.degrees(math.atan2(dy, dx))


def _owner_reference_deg(
    observation: SimObservation,
    centre: tuple[float, float] | None,
) -> float | None:
    """The heading "on your left" is measured from.

    ``OwnerTrack`` carries no yaw, so the honest reference is the bearing from
    the owner to the robot — the direction they are being spoken to from. When
    even that is unavailable the refusal drops the side word rather than
    inventing a direction (see ``OrbitFeasibility.refusal_sentence``).
    """

    if centre is None:
        return None
    robot = observation.robot
    dx = robot.x - centre[0]
    dy = robot.y - centre[1]
    if math.hypot(dx, dy) <= 1e-6:
        return None
    return math.degrees(math.atan2(dy, dx))


def _step_count(value: str | None, *, default: int) -> int | None:
    if value is None:
        return default
    if value in NUMBER_WORDS:
        return NUMBER_WORDS[value]
    try:
        number = int(value)
    except ValueError:
        return None
    return number if 1 <= number <= 12 else None


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _angle_error(target: float, current: float) -> float:
    return _wrap(target - current)
