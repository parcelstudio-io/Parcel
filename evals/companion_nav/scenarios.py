"""Declarative FOLLOW_BENCH_V1 scenarios for the headless city block.

Every scenario is fully deterministic: the robot start pose, a scripted owner
trajectory, and scripted pedestrian trajectories are given as timed waypoints
that are advanced by piecewise-linear interpolation each control step. All
coordinates are meters in the ``city_block.xml`` world frame and were checked
against the actual scene geometry (buildings, planters, bench, lamp posts,
signal post, crate, bollard); the scenario-validation test re-verifies that
scripted actors stay on free space.

Scenario notes call out the deliberate v1 sensing contract: scripted
pedestrians are embodied by the scene's existing pedestrian mocap bodies, so
they ARE visible to the occlusion-true raycast scan and to the owner
line-of-sight check, but they are NOT part of the analytic nearest-obstacle
telemetry nor of the static-collision truth oracle. Pedestrian contact is
therefore scored from the recorded separations, never from the world's
static collision counter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

CONTROL_DT_S = 0.1
MAX_SCENARIO_DURATION_S = 120.0
# pedestrian_1..7 plus cyclist_1 exist as mocap bodies in city_block.xml.
MAX_SCRIPTED_PEDESTRIANS = 7
DIRECTIVE_KINDS = frozenset({"follow", "navigate"})

# Follow-Bench-style distance band: the robot should keep the owner between
# these distances (center-to-center) for a scenario-specific fraction of steps.
DEFAULT_BAND_MIN_M = 1.2
DEFAULT_BAND_MAX_M = 3.0


@dataclass(frozen=True)
class TimedWaypoint:
    """One timed sample of a scripted piecewise-linear trajectory."""

    time_s: float
    x: float
    y: float

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) for value in (self.time_s, self.x, self.y)):
            raise ValueError("timed waypoint values must be finite")
        if self.time_s < 0.0:
            raise ValueError("timed waypoint time must be non-negative")


@dataclass(frozen=True)
class PedestrianScript:
    """A scripted pedestrian advanced kinematically along timed waypoints."""

    agent_id: str
    radius_m: float
    waypoints: tuple[TimedWaypoint, ...]

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("pedestrian agent_id must be non-empty")
        if not math.isfinite(self.radius_m) or not 0.05 <= self.radius_m <= 0.6:
            raise ValueError("pedestrian radius must be within [0.05, 0.6] m")
        _validate_waypoints(self.waypoints, label=f"pedestrian {self.agent_id!r}")


@dataclass(frozen=True)
class SpeechTurn:
    """One scripted conversational turn, used only by the expression metrics.

    The bench has no audio pipeline, so a turn is reduced to the two instants
    the expression layer actually reacts to: the owner starting to speak (the
    cue for the orient reaction) and stopping. Everything downstream of those
    two events — the acknowledgment latency, the blend continuity — is the
    real ``ExpressionEngine`` running on the episode clock.
    """

    onset_s: float
    end_s: float

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) for value in (self.onset_s, self.end_s)):
            raise ValueError("speech turn times must be finite")
        if self.onset_s < 0.0:
            raise ValueError("speech turn onset must be non-negative")
        if self.end_s <= self.onset_s:
            raise ValueError("speech turn must end after it starts")


@dataclass(frozen=True)
class EmoteWindow:
    """A scripted gesture occupying the base, as an activity skill would.

    The bench models the *arbitration* consequence of an emote — the activity
    owns the body, so the follower's command is preempted — and not the joint
    trajectory of the gesture itself. That boundary is stated in the eval's
    ``does_not_prove`` and is what makes the interruption-correctness metric
    a claim about the arbiter rather than about the choreography.
    """

    label: str
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("emote window label must be non-empty")
        if any(not math.isfinite(value) for value in (self.start_s, self.end_s)):
            raise ValueError("emote window times must be finite")
        if self.start_s < 0.0:
            raise ValueError("emote window start must be non-negative")
        if self.end_s <= self.start_s:
            raise ValueError("emote window must end after it starts")


@dataclass(frozen=True)
class ExpressionScript:
    """The scripted conversation an episode carries alongside its motion."""

    speech_turns: tuple[SpeechTurn, ...] = ()
    emotes: tuple[EmoteWindow, ...] = ()

    def __post_init__(self) -> None:
        for earlier, later in pairwise(self.speech_turns):
            if later.onset_s < earlier.end_s:
                raise ValueError("scripted speech turns must not overlap")
        for earlier, later in pairwise(self.emotes):
            if later.start_s < earlier.end_s:
                raise ValueError("scripted emote windows must not overlap")

    @property
    def conversation_span_s(self) -> float:
        """Wall time the robot spends in an interaction, gestures included.

        Measured from the first speech onset to the end of the last
        conversational event of either kind. Dividing gesture time by the
        speech time alone would make a single gesture after a short sentence
        read as a near-100% duty cycle, which says nothing about whether the
        robot is over-triggering.
        """

        if not self.speech_turns:
            return 0.0
        start = self.speech_turns[0].onset_s
        end = self.speech_turns[-1].end_s
        if self.emotes:
            end = max(end, self.emotes[-1].end_s)
        return end - start

    def emote_active(self, time_s: float) -> str | None:
        for window in self.emotes:
            if window.start_s <= time_s < window.end_s:
                return window.label
        return None


EMPTY_EXPRESSION_SCRIPT = ExpressionScript()


@dataclass(frozen=True)
class Scenario:
    """One deterministic FOLLOW_BENCH_V1 episode specification."""

    scenario_id: str
    description: str
    seed: int
    robot_start: tuple[float, float, float]
    owner_waypoints: tuple[TimedWaypoint, ...]
    pedestrians: tuple[PedestrianScript, ...]
    directive_kind: str
    directive: str
    duration_s: float
    band_min_m: float = DEFAULT_BAND_MIN_M
    band_max_m: float = DEFAULT_BAND_MAX_M
    min_band_fraction: float = 0.9
    max_time_lost_s: float = 5.0
    note: str = ""
    # Window over which the anticipatory-following metrics are scored. Scoring
    # the whole episode would drown a two-second turn in twenty seconds of
    # straight-line walking that no predictor can improve.
    turn_window_s: tuple[float, float] | None = None
    expression: ExpressionScript = EMPTY_EXPRESSION_SCRIPT

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.description or not self.directive:
            raise ValueError("scenario id, description, and directive must be non-empty")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ValueError("scenario seed must be a non-negative integer")
        if self.directive_kind not in DIRECTIVE_KINDS:
            raise ValueError(f"unknown directive kind: {self.directive_kind!r}")
        if len(self.robot_start) != 3 or any(
            not math.isfinite(value) for value in self.robot_start
        ):
            raise ValueError("robot start pose must be three finite values (x, y, yaw)")
        if not math.isfinite(self.duration_s) or not 0.0 < self.duration_s <= MAX_SCENARIO_DURATION_S:
            raise ValueError(
                f"scenario duration must be within (0, {MAX_SCENARIO_DURATION_S}] seconds"
            )
        _validate_waypoints(self.owner_waypoints, label="owner")
        if len(self.pedestrians) > MAX_SCRIPTED_PEDESTRIANS:
            raise ValueError(
                f"at most {MAX_SCRIPTED_PEDESTRIANS} scripted pedestrians are supported"
            )
        if len({item.agent_id for item in self.pedestrians}) != len(self.pedestrians):
            raise ValueError("pedestrian agent ids must be unique")
        band = (self.band_min_m, self.band_max_m)
        if any(not math.isfinite(value) or value <= 0.0 for value in band):
            raise ValueError("distance band limits must be positive and finite")
        if self.band_min_m >= self.band_max_m:
            raise ValueError("band minimum must be below band maximum")
        if not math.isfinite(self.min_band_fraction) or not 0.0 <= self.min_band_fraction <= 1.0:
            raise ValueError("min_band_fraction must be within [0, 1]")
        if not math.isfinite(self.max_time_lost_s) or self.max_time_lost_s <= 0.0:
            raise ValueError("max_time_lost_s must be positive and finite")
        if self.turn_window_s is not None:
            start, end = self.turn_window_s
            if any(not math.isfinite(value) for value in (start, end)):
                raise ValueError("turn window bounds must be finite")
            if not 0.0 <= start < end <= self.duration_s:
                raise ValueError("turn window must be an interval inside the episode")
        for window in self.expression.emotes:
            if window.end_s > self.duration_s:
                raise ValueError("scripted emotes must end inside the episode")
        for turn in self.expression.speech_turns:
            if turn.end_s > self.duration_s:
                raise ValueError("scripted speech turns must end inside the episode")

    @property
    def control_steps(self) -> int:
        return max(1, round(self.duration_s / CONTROL_DT_S))


def _validate_waypoints(waypoints: tuple[TimedWaypoint, ...], *, label: str) -> None:
    if len(waypoints) < 1:
        raise ValueError(f"{label} trajectory requires at least one waypoint")
    for earlier, later in pairwise(waypoints):
        if later.time_s <= earlier.time_s:
            raise ValueError(f"{label} waypoint times must be strictly increasing")
    if waypoints[-1].time_s > MAX_SCENARIO_DURATION_S:
        raise ValueError(f"{label} waypoint times must stay within the duration bound")


def interpolate_position(
    waypoints: tuple[TimedWaypoint, ...], time_s: float
) -> tuple[float, float]:
    """Clamped piecewise-linear position of a scripted trajectory at ``time_s``."""

    if not math.isfinite(time_s):
        raise ValueError("interpolation time must be finite")
    if time_s <= waypoints[0].time_s:
        return waypoints[0].x, waypoints[0].y
    for earlier, later in pairwise(waypoints):
        if time_s < later.time_s:
            span = later.time_s - earlier.time_s
            fraction = (time_s - earlier.time_s) / span
            return (
                earlier.x + fraction * (later.x - earlier.x),
                earlier.y + fraction * (later.y - earlier.y),
            )
    return waypoints[-1].x, waypoints[-1].y


def interpolate_velocity(
    waypoints: tuple[TimedWaypoint, ...], time_s: float
) -> tuple[float, float]:
    """World-frame velocity of the active segment; zero before/after the script."""

    if not math.isfinite(time_s):
        raise ValueError("interpolation time must be finite")
    if time_s < waypoints[0].time_s or time_s >= waypoints[-1].time_s:
        return 0.0, 0.0
    for earlier, later in pairwise(waypoints):
        if time_s < later.time_s:
            span = later.time_s - earlier.time_s
            return (later.x - earlier.x) / span, (later.y - earlier.y) / span
    return 0.0, 0.0


def _path(*points: tuple[float, float, float]) -> tuple[TimedWaypoint, ...]:
    return tuple(TimedWaypoint(time_s=t, x=x, y=y) for t, x, y in points)


_PEDESTRIAN_SENSING_NOTE = (
    "Scripted pedestrians are embodied as scene mocap capsules: visible to the "
    "raycast scan, the owner line-of-sight check, and the injected "
    "dynamic_agents/nearest_person telemetry, but absent from the analytic "
    "nearest-obstacle channel and the static-collision oracle."
)


FOLLOW_BENCH_V1: tuple[Scenario, ...] = (
    Scenario(
        scenario_id="straight_follow",
        description=(
            "Owner walks straight east along the open road at ~0.28 m/s; the robot "
            "starts 2.0 m behind and must hold the follow band without incident."
        ),
        seed=11,
        robot_start=(0.0, -0.4, 0.0),
        owner_waypoints=_path((0.0, 2.0, -0.4), (16.0, 6.4, -0.4), (20.0, 6.4, -0.4)),
        pedestrians=(),
        directive_kind="follow",
        directive="follow me",
        duration_s=20.0,
        min_band_fraction=0.9,
        note="Smoke scenario for the pytest gate. " + _PEDESTRIAN_SENSING_NOTE,
    ),
    Scenario(
        scenario_id="follow_turn_corner",
        description=(
            "Owner walks west, sprints, then turns south behind building 5 so "
            "line of sight breaks; after a pause the owner re-emerges and the "
            "robot must reacquire. Band membership is expected to collapse "
            "during the scripted sprint; reacquire time is the scored quantity."
        ),
        seed=12,
        robot_start=(-1.7, -2.0, math.pi),
        owner_waypoints=_path(
            (0.0, -3.5, -1.7),
            (6.0, -5.3, -1.7),
            (9.4, -8.4, -1.7),
            (12.9, -8.4, -4.9),
            (14.4, -8.4, -4.9),
            (17.9, -8.4, -1.9),
            (19.9, -8.0, -1.9),
            (24.0, -8.0, -1.9),
        ),
        pedestrians=(),
        directive_kind="follow",
        directive="follow me",
        duration_s=24.0,
        min_band_fraction=0.3,
        max_time_lost_s=6.0,
        note=(
            "The direct follow controller fails closed (zero motion) while the "
            "owner is occluded, so reacquisition is owner-driven in v1. "
            + _PEDESTRIAN_SENSING_NOTE
        ),
    ),
    Scenario(
        scenario_id="owner_stops",
        description=(
            "Owner walks east then stops abruptly mid-road; the robot must "
            "decelerate into the band and hold without creeping into the owner."
        ),
        seed=13,
        robot_start=(-1.0, 0.6, 0.0),
        owner_waypoints=_path(
            (0.0, 1.0, 0.6),
            (10.0, 3.8, 0.6),
            (14.0, 3.8, 0.6),
            (17.0, 4.6, 0.6),
            (18.0, 4.6, 0.6),
        ),
        pedestrians=(),
        directive_kind="follow",
        directive="follow me",
        duration_s=18.0,
        min_band_fraction=0.9,
        note="Smoke scenario for the pytest gate. " + _PEDESTRIAN_SENSING_NOTE,
    ),
    Scenario(
        scenario_id="pedestrian_group",
        description=(
            "Owner walks east through a loose group of three near-stationary "
            "pedestrians flanking the route; the robot must keep social "
            "distances while staying in the band."
        ),
        seed=14,
        robot_start=(-0.6, -0.65, 0.0),
        owner_waypoints=_path((0.0, 1.0, -0.7), (21.4, 7.0, -0.7), (25.0, 7.0, -0.7)),
        pedestrians=(
            PedestrianScript(
                agent_id="group_north",
                radius_m=0.2,
                waypoints=_path((0.0, 4.0, 1.2), (25.0, 3.6, 1.3)),
            ),
            PedestrianScript(
                agent_id="group_south",
                radius_m=0.2,
                waypoints=_path((0.0, 4.7, -2.2), (25.0, 4.4, -2.3)),
            ),
            PedestrianScript(
                agent_id="group_east",
                radius_m=0.2,
                waypoints=_path((0.0, 5.2, 1.5), (25.0, 5.0, 1.6)),
            ),
        ),
        directive_kind="follow",
        directive="follow me",
        duration_s=25.0,
        # Was 0.8 against runner 1.0. Runner 1.1 added the production
        # pre-gate acceleration smoother, which had been missing from the
        # bench, and the extra ramp costs this scenario about two and a half
        # points of band membership (0.776 measured). The threshold follows the
        # more faithful rig rather than the controller being called worse.
        min_band_fraction=0.75,
        note=_PEDESTRIAN_SENSING_NOTE,
    ),
    Scenario(
        scenario_id="doorway_gap",
        description=(
            "Owner crosses the ~1.9 m gap between the sidewalk bench and lamp "
            "post heading north; the robot threads the same constriction. The "
            "production keepout stops the robot short of full traversal, so the "
            "scored quantities are minimum clearance and band retention."
        ),
        seed=15,
        robot_start=(-0.83, -0.5, math.pi / 2.0),
        owner_waypoints=_path((0.0, -0.83, 1.2), (11.8, -0.83, 4.15), (20.0, -0.83, 4.15)),
        pedestrians=(),
        directive_kind="follow",
        directive="follow me",
        duration_s=20.0,
        min_band_fraction=0.7,
        note=(
            "The fail-closed obstacle keepout intentionally prevents the robot "
            "from finishing the narrowest section; this scenario documents that "
            "conservative behavior rather than hiding it. "
            + _PEDESTRIAN_SENSING_NOTE
        ),
    ),
    Scenario(
        scenario_id="pedestrian_cut_in",
        description=(
            "A pedestrian crosses north-to-south straight between the robot and "
            "the owner mid-follow; the robot must brake, keep social distance, "
            "tolerate the brief occlusion, and reacquire the owner."
        ),
        seed=16,
        robot_start=(-0.3, 1.5, 0.0),
        owner_waypoints=_path((0.0, 1.5, 1.5), (12.5, 5.0, 1.5), (20.0, 5.0, 1.5)),
        pedestrians=(
            PedestrianScript(
                agent_id="cut_in",
                radius_m=0.2,
                waypoints=_path(
                    (0.0, 2.6, 3.8),
                    (5.0, 2.6, 3.8),
                    (17.4, 2.6, -2.4),
                    (20.0, 2.6, -2.4),
                ),
            ),
        ),
        directive_kind="follow",
        directive="follow me",
        duration_s=20.0,
        min_band_fraction=0.6,
        note=_PEDESTRIAN_SENSING_NOTE,
    ),
    Scenario(
        scenario_id="navigate_crossing_ped",
        description=(
            "Point-goal directive to the south sidewalk while a pedestrian "
            "crosses the robot's route east-west; scored on success, "
            "time-to-goal, clearance, and social distances."
        ),
        seed=17,
        robot_start=(0.0, -1.0, -math.pi / 2.0),
        owner_waypoints=_path((0.0, 2.0, -0.5)),
        pedestrians=(
            PedestrianScript(
                agent_id="crosser",
                radius_m=0.2,
                waypoints=_path(
                    (1.0, -2.4, -2.05),
                    (10.6, 2.4, -2.05),
                    (16.0, 5.6, -2.05),
                    (45.0, 5.6, -2.05),
                ),
            ),
        ),
        directive_kind="navigate",
        directive="Can you go to the sidewalk so that you are not on the road. It's dangerous",
        duration_s=45.0,
        min_band_fraction=0.0,
        note=(
            "Owner stands still at the default commissioning location. "
            + _PEDESTRIAN_SENSING_NOTE
        ),
    ),
    Scenario(
        scenario_id="owner_turn_90",
        description=(
            "Owner walks 6 m east across the open south apron at 0.4 m/s, turns "
            "90 degrees north, and walks 6 m more. Scored on distance-band error "
            "through the turn window, where a follower aimed at the measured "
            "owner must overshoot and a follower aimed at a predicted lead point "
            "should not."
        ),
        seed=19,
        robot_start=(-6.4, -9.0, 0.0),
        owner_waypoints=_path(
            (0.0, -4.4, -9.0),
            (15.0, 1.6, -9.0),
            (30.0, 1.6, -3.0),
            (34.0, 1.6, -3.0),
        ),
        pedestrians=(),
        directive_kind="follow",
        directive="follow me",
        duration_s=34.0,
        min_band_fraction=0.8,
        # The corner instant plus the six seconds either side of it: long
        # enough for the overshoot to develop and decay, short enough that the
        # straight legs cannot dilute it.
        turn_window_s=(12.0, 24.0),
        expression=ExpressionScript(
            # The owner speaks just after the corner, while they are well off
            # the robot's heading: an acknowledgment latency measured with the
            # owner dead ahead would score a head that never had to move.
            speech_turns=(SpeechTurn(onset_s=16.0, end_s=19.0),),
            # Outside the turn window, so the gesture's base preemption cannot
            # contaminate the anticipation measurement.
            emotes=(EmoteWindow(label="nod", start_s=26.0, end_s=27.4),),
        ),
        note=(
            "Deliberately obstacle-free so the scored quantity is the follow "
            "law and not the keepout. " + _PEDESTRIAN_SENSING_NOTE
        ),
    ),
    Scenario(
        scenario_id="pedestrian_cut_in_predictive",
        description=(
            "Owner walks east across the open south apron; a pedestrian walks "
            "north on a course that is clear of the robot now and intersects "
            "the robot's corridor about six seconds ahead. Scored on hard "
            "collisions, geometric-gate interventions, and minimum TTC: a "
            "predictive brake should shed speed before the geometric gate has "
            "anything to react to."
        ),
        seed=20,
        # Heading offset at t=0 so the owner starts off-axis: an acknowledgment
        # latency measured with the owner already dead ahead would score a head
        # that never had to move.
        robot_start=(-6.0, -9.0, -0.6),
        owner_waypoints=_path((0.0, -4.0, -9.0), (20.0, 2.0, -9.0), (26.0, 2.0, -9.0)),
        pedestrians=(
            PedestrianScript(
                agent_id="predictive_crosser",
                radius_m=0.2,
                # Parked well south, then a brisk 1.1 m/s northbound crossing
                # timed to reach the follow corridor as the robot does. The
                # speed matters: at a stroll the relative closing rate is too
                # low for a two-second brake horizon to reach any further than
                # the geometric slow radius already does.
                # The crossing line sits east of where a correctly braking
                # robot comes to rest. A scripted pedestrian never yields, so
                # a line drawn through the robot's parking spot would score a
                # collision against a robot that did everything right.
                waypoints=_path(
                    (0.0, -1.0, -14.5),
                    (12.0, -1.0, -14.5),
                    (17.0, -1.0, -9.0),
                    (22.0, -1.0, -3.5),
                    (26.0, -1.0, -3.5),
                ),
            ),
        ),
        directive_kind="follow",
        directive="follow me",
        duration_s=26.0,
        min_band_fraction=0.6,
        expression=ExpressionScript(
            speech_turns=(SpeechTurn(onset_s=0.5, end_s=3.5),),
            # Deliberately placed inside the encounter: an emote that seizes
            # the base while a pedestrian is closing is the interruption case
            # the N8 correctness metric exists to catch.
            emotes=(EmoteWindow(label="tilt", start_s=15.0, end_s=16.6),),
        ),
        note=(
            "The crossing pedestrian is scripted and never yields. "
            + _PEDESTRIAN_SENSING_NOTE
        ),
    ),
    Scenario(
        scenario_id="owner_corner_loss",
        description=(
            "Owner walks west, sprints ahead, rounds the south-west building "
            "corner and keeps walking away instead of waiting. Line of sight "
            "does not come back on its own, so the scored quantities are "
            "time-to-reacquire, distance travelled while searching, and whether "
            "the search gave up inside its budget."
        ),
        seed=21,
        robot_start=(-1.0, 1.0, math.pi),
        # West along the open lane north of building 5, a sprint that opens the
        # gap, then down the building's west side and away to the south. The
        # sprint is what makes the corner bite: a follower holding two metres
        # rounds the same corner a moment later and never loses anybody.
        owner_waypoints=_path(
            (0.0, -3.0, 1.0),
            (6.0, -4.8, 1.0),
            (10.0, -9.0, 1.0),
            (19.0, -9.0, -8.0),
            (28.0, -5.0, -9.5),
            (58.0, -5.0, -9.5),
        ),
        pedestrians=(),
        directive_kind="follow",
        directive="follow me",
        # Long enough to contain a whole 45 s search budget, so the give-up
        # flag is a measurement rather than an episode that ran out first.
        duration_s=68.0,
        # The owner leaves and never comes back into the band; band membership
        # is not the claim this scenario makes, so it is not gated on.
        min_band_fraction=0.0,
        max_time_lost_s=68.0,
        expression=ExpressionScript(
            speech_turns=(SpeechTurn(onset_s=2.0, end_s=4.5),),
        ),
        note=(
            "Baseline behaviour is the documented fail-closed hold: the direct "
            "follow controller emits zero motion while the owner is occluded, so "
            "the baseline reacquire time is a timeout, not a search. "
            + _PEDESTRIAN_SENSING_NOTE
        ),
    ),
    Scenario(
        scenario_id="navigate_near_wall",
        description=(
            "Point-goal directive to the lamppost starting adjacent to the "
            "building envelope; scored on success and minimum clearance while "
            "moving out of the tight corridor."
        ),
        seed=18,
        robot_start=(3.2, 3.15, math.pi),
        owner_waypoints=_path((0.0, 2.0, -0.5)),
        pedestrians=(),
        directive_kind="navigate",
        directive="Can you wait by the lamppost?",
        duration_s=30.0,
        min_band_fraction=0.0,
        note=(
            "Owner stands still at the default commissioning location. "
            + _PEDESTRIAN_SENSING_NOTE
        ),
    ),
)


def scenario_by_id(scenario_id: str) -> Scenario:
    for scenario in FOLLOW_BENCH_V1:
        if scenario.scenario_id == scenario_id:
            return scenario
    known = ", ".join(item.scenario_id for item in FOLLOW_BENCH_V1)
    raise KeyError(f"unknown FOLLOW_BENCH_V1 scenario {scenario_id!r} (known: {known})")
