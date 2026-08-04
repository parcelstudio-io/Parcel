"""Pure, unit-testable episode metrics for FOLLOW_BENCH_V1 traces.

The functions here consume only recorded step data (no simulator handles) so
synthetic traces can exercise every branch. Definitions follow the 2026
person-following evaluation consensus (Follow-Bench, SocNavBench, Gervet et
al., SRCC): hard collisions with no wall-sliding forgiveness, band-based
following success, social-space occupancy, commanded-velocity smoothness, and
occlusion reacquisition. BARN-style speed scoring is deliberately absent.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import pairwise

# Social-space thresholds (center-to-center, Hall proxemics as used by
# SocNavBench-style scoring).
PERSONAL_SPACE_M = 1.2
INTIMATE_SPACE_M = 0.45


@dataclass(frozen=True)
class StepRecord:
    """One recorded control step of a FOLLOW_BENCH_V1 episode."""

    time_s: float
    robot_x: float
    robot_y: float
    robot_yaw: float
    owner_x: float
    owner_y: float
    owner_visible: bool
    owner_distance_m: float
    command_vx: float
    command_vy: float
    command_vyaw: float
    state: str
    note: str
    nearest_pedestrian_center_m: float | None
    nearest_pedestrian_surface_m: float | None
    cumulative_static_collisions: int


@dataclass(frozen=True)
class EpisodeResult:
    """A completed episode: the step trace plus terminal world truth."""

    scenario_id: str
    directive_kind: str
    control_dt_s: float
    steps: tuple[StepRecord, ...]
    status: str
    reason: str
    static_collision_count: int
    minimum_static_clearance_m: float


@dataclass(frozen=True)
class EpisodeMetrics:
    """Scored quantities for one episode; ``None`` marks not-applicable."""

    scenario_id: str
    directive_kind: str
    status: str
    reason: str
    steps: int
    duration_s: float
    hard_collision_count: int
    static_collision_count: int
    pedestrian_contact_count: int
    band_fraction: float | None
    following_success: bool | None
    max_time_owner_lost_s: float
    occlusion_count: int
    mean_time_to_reacquire_s: float | None
    max_time_to_reacquire_s: float | None
    min_pedestrian_center_m: float | None
    min_pedestrian_surface_m: float | None
    personal_space_time_s: float
    intimate_space_time_s: float
    rms_commanded_jerk_mps3: float
    path_irregularity_rad_per_m: float
    navigate_success: bool | None
    time_to_goal_s: float | None
    min_static_clearance_m: float | None

    def payload(self) -> dict[str, object]:
        """JSON-safe mapping; non-finite floats are encoded as ``None``."""

        result: dict[str, object] = {}
        for key, value in asdict(self).items():
            if isinstance(value, float) and not math.isfinite(value):
                result[key] = None
            else:
                result[key] = value
        return result


def band_fraction(
    distances: Sequence[float], *, band_min_m: float, band_max_m: float
) -> float:
    """Fraction of steps whose owner distance lies inside the follow band."""

    if band_min_m >= band_max_m:
        raise ValueError("band minimum must be below band maximum")
    if not distances:
        return 0.0
    inside = sum(1 for value in distances if band_min_m <= value <= band_max_m)
    return inside / len(distances)


def occlusion_spans_s(visibility: Sequence[bool], dt_s: float) -> list[float]:
    """Durations of maximal not-visible runs, in order (tail run included)."""

    if dt_s <= 0.0 or not math.isfinite(dt_s):
        raise ValueError("dt_s must be positive and finite")
    spans: list[float] = []
    run = 0
    for visible in visibility:
        if visible:
            if run:
                spans.append(run * dt_s)
            run = 0
        else:
            run += 1
    if run:
        spans.append(run * dt_s)
    return spans


def reacquire_times_s(visibility: Sequence[bool], dt_s: float) -> list[float]:
    """Occlusion spans that ended in reacquisition (open tail span excluded)."""

    spans = occlusion_spans_s(visibility, dt_s)
    if spans and visibility and not visibility[-1]:
        spans = spans[:-1]
    return spans


def social_space_time_s(
    center_distances: Sequence[float | None], dt_s: float, *, threshold_m: float
) -> float:
    """Total time with the nearest pedestrian center inside ``threshold_m``."""

    if dt_s <= 0.0 or not math.isfinite(dt_s):
        raise ValueError("dt_s must be positive and finite")
    if threshold_m <= 0.0 or not math.isfinite(threshold_m):
        raise ValueError("threshold_m must be positive and finite")
    return dt_s * sum(
        1 for value in center_distances if value is not None and value < threshold_m
    )


def pedestrian_contact_count(surface_separations: Sequence[float | None]) -> int:
    """Distinct entries into pedestrian contact (surface separation <= 0)."""

    contacts = 0
    in_contact = False
    for value in surface_separations:
        touching = value is not None and value <= 0.0
        if touching and not in_contact:
            contacts += 1
        in_contact = touching
    return contacts


def rms_commanded_jerk_mps3(
    vx: Sequence[float], vy: Sequence[float], dt_s: float
) -> float:
    """RMS magnitude of the second difference of the commanded velocity."""

    if dt_s <= 0.0 or not math.isfinite(dt_s):
        raise ValueError("dt_s must be positive and finite")
    if len(vx) != len(vy):
        raise ValueError("vx and vy sequences must have equal length")
    if len(vx) < 3:
        return 0.0
    total = 0.0
    count = 0
    for index in range(1, len(vx) - 1):
        jerk_x = (vx[index + 1] - 2.0 * vx[index] + vx[index - 1]) / (dt_s * dt_s)
        jerk_y = (vy[index + 1] - 2.0 * vy[index] + vy[index - 1]) / (dt_s * dt_s)
        total += jerk_x * jerk_x + jerk_y * jerk_y
        count += 1
    return math.sqrt(total / count) if count else 0.0


def path_irregularity_rad_per_m(
    xs: Sequence[float],
    ys: Sequence[float],
    *,
    minimum_segment_m: float = 1e-3,
    minimum_path_m: float = 0.2,
) -> float:
    """Accumulated absolute heading change per meter of executed path.

    Stationary jitter below ``minimum_segment_m`` is ignored; a path shorter
    than ``minimum_path_m`` scores zero because a ratio over near-zero length
    is meaningless.
    """

    if len(xs) != len(ys):
        raise ValueError("xs and ys sequences must have equal length")
    headings: list[float] = []
    length = 0.0
    previous = None
    for x, y in zip(xs, ys):
        if previous is not None:
            dx, dy = x - previous[0], y - previous[1]
            segment = math.hypot(dx, dy)
            if segment >= minimum_segment_m:
                headings.append(math.atan2(dy, dx))
                length += segment
        previous = (x, y)
    if length < minimum_path_m or len(headings) < 2:
        return 0.0
    turning = sum(abs(_wrap(later - earlier)) for earlier, later in pairwise(headings))
    return turning / length


def compute_episode_metrics(result: EpisodeResult, scenario) -> EpisodeMetrics:
    """Score one recorded episode against its scenario thresholds.

    ``scenario`` is any object exposing the FOLLOW_BENCH_V1 scenario fields
    (``band_min_m``, ``band_max_m``, ``min_band_fraction``,
    ``max_time_lost_s``); the loose typing keeps this module import-free of
    simulator code and easy to unit test.
    """

    dt = result.control_dt_s
    steps = result.steps
    distances = [item.owner_distance_m for item in steps]
    visibility = [item.owner_visible for item in steps]
    centers = [item.nearest_pedestrian_center_m for item in steps]
    surfaces = [item.nearest_pedestrian_surface_m for item in steps]

    contacts = pedestrian_contact_count(surfaces)
    hard_collisions = result.static_collision_count + contacts
    spans = occlusion_spans_s(visibility, dt)
    reacquisitions = reacquire_times_s(visibility, dt)
    max_lost = max(spans, default=0.0)

    fraction: float | None = None
    followed: bool | None = None
    if result.directive_kind == "follow":
        fraction = band_fraction(
            distances,
            band_min_m=scenario.band_min_m,
            band_max_m=scenario.band_max_m,
        )
        followed = (
            hard_collisions == 0
            and fraction >= scenario.min_band_fraction
            and max_lost <= scenario.max_time_lost_s
        )

    navigate_success: bool | None = None
    time_to_goal: float | None = None
    if result.directive_kind == "navigate":
        navigate_success = result.status == "arrived" and hard_collisions == 0
        if result.status == "arrived" and steps:
            time_to_goal = steps[-1].time_s

    known_centers = [value for value in centers if value is not None]
    known_surfaces = [value for value in surfaces if value is not None]
    minimum_clearance = (
        result.minimum_static_clearance_m
        if math.isfinite(result.minimum_static_clearance_m)
        else None
    )
    return EpisodeMetrics(
        scenario_id=result.scenario_id,
        directive_kind=result.directive_kind,
        status=result.status,
        reason=result.reason,
        steps=len(steps),
        duration_s=len(steps) * dt,
        hard_collision_count=hard_collisions,
        static_collision_count=result.static_collision_count,
        pedestrian_contact_count=contacts,
        band_fraction=fraction,
        following_success=followed,
        max_time_owner_lost_s=max_lost,
        occlusion_count=len(spans),
        mean_time_to_reacquire_s=(
            sum(reacquisitions) / len(reacquisitions) if reacquisitions else None
        ),
        max_time_to_reacquire_s=max(reacquisitions) if reacquisitions else None,
        min_pedestrian_center_m=min(known_centers, default=None),
        min_pedestrian_surface_m=min(known_surfaces, default=None),
        personal_space_time_s=social_space_time_s(
            centers, dt, threshold_m=PERSONAL_SPACE_M
        ),
        intimate_space_time_s=social_space_time_s(
            centers, dt, threshold_m=INTIMATE_SPACE_M
        ),
        rms_commanded_jerk_mps3=rms_commanded_jerk_mps3(
            [item.command_vx for item in steps],
            [item.command_vy for item in steps],
            dt,
        ),
        path_irregularity_rad_per_m=path_irregularity_rad_per_m(
            [item.robot_x for item in steps],
            [item.robot_y for item in steps],
        ),
        navigate_success=navigate_success,
        time_to_goal_s=time_to_goal,
        min_static_clearance_m=minimum_clearance,
    )


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
