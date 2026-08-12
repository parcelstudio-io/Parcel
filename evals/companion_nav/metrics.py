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
    # --- card W9 -----------------------------------------------------------
    # The geometric proximity gate's verdict for this step, recorded as a field
    # rather than parsed back out of ``note`` so the intervention count is a
    # measurement and not a string match.
    proximity_state: str = "clear"
    # Geometric reactive gate only (pre-TTC). Distinguishes U15: the composed
    # proximity_state after the predictive brake may replace reactive stops.
    reactive_proximity_state: str = "clear"
    # Predicted contact for the outgoing command; ``None`` when the predictive
    # brake is switched off, which is not the same as "no contact predicted".
    time_to_collision_s: float | None = None
    # Owner-search phase, or the empty string when no search is running.
    search_state: str = ""
    # Head yaw actually commanded by the expression stack this step.
    expression_head_yaw_rad: float = 0.0
    expression_producer: str = "none"
    # Label of the scripted gesture holding the base, if any.
    emote_label: str | None = None
    # --- card J-C (additive, report-only) ----------------------------------
    # Did this step take the shaper's hard-stop bypass? Recorded so the comfort
    # metric can be split into "what the stop contract costs" and "what the
    # smoothing costs" mechanically, instead of the two being re-argued from
    # traces every time the mean moves (design record §3.2 part 3).
    emergency: bool = False


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
    # Card J-C, additive and report-only: the same RMS over the windows that
    # contain no emergency-bypass step. ``None`` when every window touches one.
    rms_commanded_jerk_nominal_mps3: float | None
    path_irregularity_rad_per_m: float
    navigate_success: bool | None
    time_to_goal_s: float | None
    min_static_clearance_m: float | None
    # --- card W9 -----------------------------------------------------------
    turn_mean_band_error_m: float | None
    turn_time_outside_band_s: float | None
    reactive_gate_intervention_count: int
    reactive_gate_stop_count: int
    reactive_gate_intervention_time_s: float
    # Composed post-TTC gate (may include predictive brake). Kept for continuity;
    # prefer the reactive_* fields above when judging U15.
    composed_gate_intervention_count: int
    composed_gate_stop_count: int
    min_time_to_collision_s: float | None
    time_to_reacquire_s: float | None
    search_distance_m: float | None
    search_gave_up: bool | None
    acknowledgment_latency_s: float | None
    expression_blend_jerk_rad_s3: float | None
    emote_duty_cycle: float | None
    emote_active_time_s: float
    emote_hard_collision_count: int
    expression_gated_fraction: float | None

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


def rms_commanded_jerk_nominal_mps3(
    vx: Sequence[float],
    vy: Sequence[float],
    emergency: Sequence[bool],
    dt_s: float,
) -> float | None:
    """Card J-C: the same RMS, over NON-emergency windows only.

    Report-only and strictly additive — ``rms_commanded_jerk_mps3`` above is the
    gated metric and is untouched. This variant exists because the diagnosis
    behind the jerk re-pin (§3.1) found 96%+ of the summed squared jerk sitting
    on emergency-ADJACENT ticks: without the split, a comfort ratchet would be
    pressuring the hard-stop contract instead of the smoothing.

    A window is the same three-sample second difference used above; it counts
    only when NONE of its three samples is an emergency step, because the
    discontinuity a hard stop introduces is visible from either side of it.
    ``None`` means no window qualified — not zero.
    """

    if dt_s <= 0.0 or not math.isfinite(dt_s):
        raise ValueError("dt_s must be positive and finite")
    if not len(vx) == len(vy) == len(emergency):
        raise ValueError("vx, vy and emergency sequences must have equal length")
    if len(vx) < 3:
        return None
    total = 0.0
    count = 0
    for index in range(1, len(vx) - 1):
        if emergency[index - 1] or emergency[index] or emergency[index + 1]:
            continue
        jerk_x = (vx[index + 1] - 2.0 * vx[index] + vx[index - 1]) / (dt_s * dt_s)
        jerk_y = (vy[index + 1] - 2.0 * vy[index] + vy[index - 1]) / (dt_s * dt_s)
        total += jerk_x * jerk_x + jerk_y * jerk_y
        count += 1
    return math.sqrt(total / count) if count else None


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


def distance_band_error_m(
    distance_m: float, *, band_min_m: float, band_max_m: float
) -> float:
    """How far outside the follow band one owner distance sits; 0 inside it.

    A signed error against the band *centre* would punish a follower for
    holding a perfectly acceptable 1.3 m, so the error is measured against the
    nearer band edge and is exactly zero anywhere inside.
    """

    if band_min_m >= band_max_m:
        raise ValueError("band minimum must be below band maximum")
    if not math.isfinite(distance_m):
        raise ValueError("owner distance must be finite")
    if distance_m < band_min_m:
        return band_min_m - distance_m
    if distance_m > band_max_m:
        return distance_m - band_max_m
    return 0.0


def gate_intervention_spans(states: Sequence[str], *, only: str | None = None) -> int:
    """Distinct entries into a non-clear proximity state.

    Counting entries rather than steps is what makes the number comparable
    between a run that brakes once for four seconds and a run that brakes
    forty times for a tenth of a second each. Pass ``only="stopped"`` to count
    just the hard interventions: during a follow the owner is themselves a
    person to the geometric gate, so a follower holding station sits in
    ``slowing`` for most of an episode and the slowing count says more about
    the band than about anything the robot had to avoid.
    """

    entries = 0
    engaged = False
    for state in states:
        active = (state == only) if only is not None else (state != "clear")
        if active and not engaged:
            entries += 1
        engaged = active
    return entries


def time_to_reacquire_s(visibility: Sequence[bool], dt_s: float) -> float | None:
    """Time from the first loss of the owner to the first recovery after it.

    ``None`` means the owner was never recovered — which is the honest answer
    for a fail-closed follower parked in front of a wall, and must not be
    confused with a fast reacquisition.
    """

    if dt_s <= 0.0 or not math.isfinite(dt_s):
        raise ValueError("dt_s must be positive and finite")
    first_loss: int | None = None
    for index, visible in enumerate(visibility):
        if not visible and first_loss is None:
            first_loss = index
        elif visible and first_loss is not None:
            return (index - first_loss) * dt_s
    return None


def path_length_m(
    xs: Sequence[float], ys: Sequence[float], mask: Sequence[bool]
) -> float:
    """Executed path length over the steps ``mask`` selects."""

    if not (len(xs) == len(ys) == len(mask)):
        raise ValueError("xs, ys, and mask must have equal length")
    total = 0.0
    for index in range(1, len(xs)):
        if mask[index] and mask[index - 1]:
            total += math.hypot(xs[index] - xs[index - 1], ys[index] - ys[index - 1])
    return total


def blend_continuity_jerk_rad_s3(
    values: Sequence[float], producers: Sequence[str], dt_s: float
) -> float:
    """RMS third difference of an expression channel *at producer hand-offs*.

    The expression stack swaps between an idle, a reaction, a beat, and a
    gated-off producer. A hand-off that is merely continuous in position still
    reads as a twitch, so the discontinuity worth measuring is in the third
    derivative, and it is worth measuring only where the swap happens:
    averaging over a whole episode of smooth breathing hides exactly the
    transient this metric exists to find. Returns 0.0 when nothing handed off.
    """

    if dt_s <= 0.0 or not math.isfinite(dt_s):
        raise ValueError("dt_s must be positive and finite")
    if len(values) != len(producers):
        raise ValueError("value and producer sequences must have equal length")
    if len(values) < 4:
        return 0.0
    scale = dt_s**3
    # A hand-off at step i first shows up in the third difference that spans
    # it, so score the window of differences that see the change.
    scored: set[int] = set()
    for index in range(1, len(producers)):
        if producers[index] == producers[index - 1]:
            continue
        for offset in range(4):
            candidate = index + offset
            if 3 <= candidate < len(values):
                scored.add(candidate)
    if not scored:
        return 0.0
    total = 0.0
    for index in sorted(scored):
        third = (
            values[index]
            - 3.0 * values[index - 1]
            + 3.0 * values[index - 2]
            - values[index - 3]
        ) / scale
        total += third * third
    return math.sqrt(total / len(scored))


def acknowledgment_latency_s(
    times_s: Sequence[float],
    head_yaw_rad: Sequence[float],
    producers: Sequence[str],
    *,
    onset_s: float,
    threshold_rad: float = 0.02,
) -> float | None:
    """Delay from a speech onset to a visible, reaction-driven head orient.

    Requiring the reaction producer matters: the idle layer's look-around will
    eventually push the head past any small threshold on its own, and counting
    that as an acknowledgment would report a latency for a robot that never
    acknowledged anything. ``None`` means the orient never became visible,
    which is the failure this metric exists to surface, not a zero.
    """

    if not (len(times_s) == len(head_yaw_rad) == len(producers)):
        raise ValueError("time, head-yaw, and producer sequences must have equal length")
    if not math.isfinite(threshold_rad) or threshold_rad <= 0.0:
        raise ValueError("threshold_rad must be positive and finite")
    for moment, yaw, producer in zip(times_s, head_yaw_rad, producers):
        if moment < onset_s:
            continue
        if producer == "reaction" and abs(yaw) >= threshold_rad:
            return moment - onset_s
    return None


def _expression_metrics(
    steps: Sequence[StepRecord], dt_s: float, scenario
) -> dict[str, object]:
    """Score the scripted-conversation channels, or return not-applicable."""

    script = getattr(scenario, "expression", None)
    turns = tuple(getattr(script, "speech_turns", ()) or ())
    emotes = tuple(getattr(script, "emotes", ()) or ())
    emote_steps = [item for item in steps if item.emote_label is not None]
    emote_time = len(emote_steps) * dt_s
    # A hard collision "during" an emote is one whose static-collision counter
    # advanced on a step the gesture owned, plus any pedestrian contact on such
    # a step: both are attributable to motion the gesture was responsible for.
    emote_collisions = 0
    previous_static = steps[0].cumulative_static_collisions if steps else 0
    for item in steps:
        advanced = item.cumulative_static_collisions - previous_static
        previous_static = item.cumulative_static_collisions
        if item.emote_label is None:
            continue
        touching = (
            item.nearest_pedestrian_surface_m is not None
            and item.nearest_pedestrian_surface_m <= 0.0
        )
        if advanced > 0 or touching:
            emote_collisions += 1

    if not turns and not emotes:
        return {
            "acknowledgment_latency_s": None,
            "expression_blend_jerk_rad_s3": None,
            "emote_duty_cycle": None,
            "emote_active_time_s": 0.0,
            "emote_hard_collision_count": 0,
            "expression_gated_fraction": None,
        }

    times = [item.time_s for item in steps]
    yaws = [item.expression_head_yaw_rad for item in steps]
    producers = [item.expression_producer for item in steps]
    latencies = [
        value
        for turn in turns
        if (
            value := acknowledgment_latency_s(
                times, yaws, producers, onset_s=turn.onset_s
            )
        )
        is not None
    ]
    # Duty cycle is fraction of *conversation* time in gesture, not of episode
    # time: an emote budget is annoying relative to how long the robot has been
    # talking to you, not relative to how long the episode happened to run.
    span = getattr(script, "conversation_span_s", 0.0) or 0.0
    duty_base = span if span > 0.0 else len(steps) * dt_s
    return {
        "acknowledgment_latency_s": (
            sum(latencies) / len(latencies) if latencies else None
        ),
        "expression_blend_jerk_rad_s3": blend_continuity_jerk_rad_s3(
            yaws, producers, dt_s
        ),
        "emote_duty_cycle": (emote_time / duty_base) if duty_base > 0.0 else None,
        "emote_active_time_s": emote_time,
        "emote_hard_collision_count": emote_collisions,
        # Companion to the latency: the expression gate takes the whole stack
        # to MODE_OFF whenever the proximity gate is not clear, and during a
        # close follow that is most of an episode. Without this number a
        # ``None`` latency reads as a broken reaction rather than as a robot
        # that was never allowed to react.
        "expression_gated_fraction": (
            sum(1 for name in producers if name in {"gated", "disabled"}) / len(producers)
            if producers
            else None
        ),
    }


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

    turn_error: float | None = None
    turn_outside: float | None = None
    window = getattr(scenario, "turn_window_s", None)
    if window is not None:
        start, end = window
        errors = [
            distance_band_error_m(
                item.owner_distance_m,
                band_min_m=scenario.band_min_m,
                band_max_m=scenario.band_max_m,
            )
            for item in steps
            if start <= item.time_s <= end
        ]
        if errors:
            turn_error = sum(errors) / len(errors)
            turn_outside = dt * sum(1 for value in errors if value > 0.0)

    gate_states = [item.reactive_proximity_state for item in steps]
    composed_states = [item.proximity_state for item in steps]
    predicted = [
        item.time_to_collision_s
        for item in steps
        if item.time_to_collision_s is not None and math.isfinite(item.time_to_collision_s)
    ]
    searching = [bool(item.search_state) for item in steps]
    search_distance = (
        path_length_m(
            [item.robot_x for item in steps], [item.robot_y for item in steps], searching
        )
        if any(searching)
        else None
    )
    gave_up: bool | None = None
    if any(searching):
        gave_up = any(item.search_state == "gave_up" for item in steps)

    expression = _expression_metrics(steps, dt, scenario)
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
        rms_commanded_jerk_nominal_mps3=rms_commanded_jerk_nominal_mps3(
            [item.command_vx for item in steps],
            [item.command_vy for item in steps],
            [item.emergency for item in steps],
            dt,
        ),
        path_irregularity_rad_per_m=path_irregularity_rad_per_m(
            [item.robot_x for item in steps],
            [item.robot_y for item in steps],
        ),
        navigate_success=navigate_success,
        time_to_goal_s=time_to_goal,
        min_static_clearance_m=minimum_clearance,
        turn_mean_band_error_m=turn_error,
        turn_time_outside_band_s=turn_outside,
        reactive_gate_intervention_count=gate_intervention_spans(gate_states),
        reactive_gate_stop_count=gate_intervention_spans(gate_states, only="stopped"),
        reactive_gate_intervention_time_s=dt
        * sum(1 for state in gate_states if state != "clear"),
        composed_gate_intervention_count=gate_intervention_spans(composed_states),
        composed_gate_stop_count=gate_intervention_spans(
            composed_states, only="stopped"
        ),
        min_time_to_collision_s=min(predicted, default=None),
        time_to_reacquire_s=time_to_reacquire_s(visibility, dt),
        search_distance_m=search_distance,
        search_gave_up=gave_up,
        **expression,  # type: ignore[arg-type]
    )


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
