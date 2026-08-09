"""Traffic-aware goal placement and yield-advance pacing primitives (pure).

N11 pure layer (backlog/NEXT.md; scrum/20260805/task_2). The voice→nav e2e
gate pinned two defects behind the pedestrian xfail:

1. Approach-pose selection is traffic-blind — ``approach.safe_approach_pose``
   picks the statically nearest safe point, which lands the sidewalk goal
   beside the crosswalk pedestrian stream, and the person-stop gate then
   (correctly) refuses the final metre forever.
2. Between person-stops the controller re-ramps from zero (0.09 m/s per tick
   in ``grid_navigator``), so frequent pedestrian passes yield ~zero net
   progress even when the corridor is briefly clear.

This module provides the pure ingredients for both fixes:

- :func:`tracks_from_payload` — stdlib-pure adapter from the runtime
  ``extras['dynamic_agents']`` mapping list to :class:`TrackState` (sibling
  of ``dynamic_layer.tracks_from_payload``, without the numpy import).
- :func:`traffic_occupancy_cost` — time-integrated proximity of predicted
  constant-velocity agent paths to a candidate point.
- :func:`rank_approach_candidates` — combine caller-supplied static
  suitability with traffic cost, with a per-candidate breakdown. With no
  tracks the ordering is byte-identical to the static ordering (ladder rule:
  an inactive additive proposer must not change behavior).
- :class:`RampMemory` — remembers commanded-velocity ramp state across brief
  person-stop interruptions so the caller may resume from a fraction of the
  prior velocity instead of zero.

Safety argument for :class:`RampMemory`: it is memory, never a gate and never
a command source. ``note_stopped`` returns nothing — there is no API that
yields a non-zero velocity while a stop is in force. ``release`` is defined
as the caller's statement that the safety gate has *already* opened; the
value it returns is a seed for the controller's slew state, still subject to
every downstream authority on every tick (collision brake, reactive gate,
TTC, actuator shaper, arbiter bounds). It therefore changes only recovery
speed after the gate releases, never the gate itself.

Pure by contract: stdlib only, no I/O, no clocks (callers pass ``now_s``),
no imports from pipeline/runtime. Malformed input raises ``ValueError``
loudly at every public entry point, repo style (arbitration SB-3: caller
mistakes that would surface as ``TypeError`` are coerced to ``ValueError``
so one except clause covers the documented contract). Sibling numpy modules
``dynamic_costs`` / ``proxemic_approach`` serve the grid planner's cost
layer (``proxemic_approach`` is PARKED per arbitration 2026-08-06); this
module is the stdlib seam for approach-pose ranking and pacing, consumed by
the pipeline wiring (Opus lane) — the module itself stays import-pure.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# Cap matches ``dynamic_layer.MAX_TRACKS`` so approach ranking and the grid
# planner see the same agent set when both consume one extras payload.
DEFAULT_MAX_TRACKS = 16

# SB-2: hard ceiling on rollout samples per track. The effective substep is
# floored at ``horizon_s / MAX_SAMPLES_PER_TRACK`` so a config typo (e.g.
# ``step_s = 1e-5``) degrades resolution instead of stalling the control
# loop. Worst case per cost call: ``len(tracks) * (MAX_SAMPLES_PER_TRACK+1)``
# samples (16 tracks -> ~65k, single-digit milliseconds in CPython).
MAX_SAMPLES_PER_TRACK = 4096


@dataclass(frozen=True)
class TrackState:
    """Constant-velocity dynamic-agent state: metres, metres/second.

    ``age_s`` is the caller-supplied age of the underlying observation
    (seconds since last perception update, default 0.0 = fresh). It exists
    for the SB-5 staleness filter — constant-velocity extrapolation of a
    stale track is confidently wrong, not merely uninformative.
    """

    x: float
    y: float
    vx: float
    vy: float
    radius_m: float = 0.35
    age_s: float = 0.0

    def __post_init__(self) -> None:
        for name in ("x", "y", "vx", "vy", "radius_m", "age_s"):
            object.__setattr__(self, name, _finite_float(getattr(self, name), f"track {name}"))
        if self.radius_m < 0.0:
            raise ValueError("track radius_m must be non-negative")
        if self.age_s < 0.0:
            raise ValueError("track age_s must be non-negative")


@dataclass(frozen=True)
class RankedCandidate:
    """One approach candidate with its cost breakdown (lower is better)."""

    index: int  # position in the caller's candidate sequence
    x: float
    y: float
    static_cost: float
    traffic_cost: float  # weighted-exposure seconds, see traffic_occupancy_cost
    total_cost: float  # static_weight * static_cost + traffic_weight * traffic_cost


def coerce_tracks(tracks: Sequence[object]) -> tuple[TrackState, ...]:
    """Validate heterogeneous track inputs into :class:`TrackState` tuples.

    Accepts :class:`TrackState`, any object with ``x``/``y``/``vx``/``vy``
    (and optional ``radius_m`` / ``age_s``) attributes — e.g.
    ``dynamic_costs.AgentTrack`` — or ``(x, y, vx, vy[, radius])`` sequences
    (sequence form carries no age and is treated as fresh). Malformed
    entries, or a non-iterable ``tracks``, raise ``ValueError``.
    """

    try:
        items = list(tracks)
    except TypeError as error:
        raise ValueError("tracks must be an iterable of track states") from error
    out: list[TrackState] = []
    for index, item in enumerate(items):
        try:
            if isinstance(item, TrackState):
                out.append(item)
            elif hasattr(item, "x") and hasattr(item, "vx"):
                out.append(
                    TrackState(
                        x=float(item.x),  # type: ignore[attr-defined]
                        y=float(item.y),  # type: ignore[attr-defined]
                        vx=float(item.vx),  # type: ignore[attr-defined]
                        vy=float(item.vy),  # type: ignore[attr-defined]
                        radius_m=float(getattr(item, "radius_m", 0.35)),
                        age_s=float(getattr(item, "age_s", 0.0)),
                    )
                )
            else:
                parts = tuple(float(value) for value in item)  # type: ignore[union-attr]
                if len(parts) == 4:
                    out.append(TrackState(*parts))
                elif len(parts) == 5:
                    out.append(TrackState(*parts[:4], radius_m=parts[4]))
                else:
                    raise ValueError("sequence track needs 4 or 5 values")
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError(f"track {index} is malformed: {error}") from error
    return tuple(out)


def tracks_from_payload(
    payload: object,
    *,
    max_tracks: int = DEFAULT_MAX_TRACKS,
) -> tuple[TrackState, ...]:
    """Build :class:`TrackState` tuples from ``extras['dynamic_agents']``.

    Stdlib-pure sibling of ``dynamic_layer.tracks_from_payload`` (which
    returns numpy-backed ``AgentTrack``). Same field contract —
    ``x``/``y``/``vx``/``vy`` required, ``radius_m`` optional (default
    0.35), ``age_s`` optional (default 0.0) — and the same loud
    reject-on-malformed policy (``ValueError``, SB-3). ``None`` or an empty
    iterable yields ``()``. Caps at ``max_tracks`` (default 16, matching
    the planner). Used by the approach-ranking wiring at
    ``safe_approach_pose`` without importing ``dynamic_layer``.
    """

    if isinstance(max_tracks, bool) or not isinstance(max_tracks, int) or max_tracks < 0:
        raise ValueError("max_tracks must be a non-negative integer")
    if payload is None:
        return ()
    if isinstance(payload, (str, bytes)) or not isinstance(payload, Iterable):
        # SB-3 (arbitration 2026-08-06): the module contract is ValueError at
        # every public boundary, deliberately including wrong-type input.
        raise ValueError("dynamic agent payload must be an iterable of mappings")  # noqa: TRY004

    tracks: list[TrackState] = []
    for index, item in enumerate(payload):
        if len(tracks) >= max_tracks:
            break
        if not isinstance(item, Mapping):
            # SB-3: ValueError by contract, including wrong-type entries.
            raise ValueError(f"dynamic agent payload entry {index} is malformed")  # noqa: TRY004
        mapping: Mapping[str, Any] = item
        try:
            track = TrackState(
                x=float(mapping["x"]),
                y=float(mapping["y"]),
                vx=float(mapping["vx"]),
                vy=float(mapping["vy"]),
                radius_m=float(mapping.get("radius_m", 0.35)),
                age_s=float(mapping.get("age_s", 0.0)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"dynamic agent payload entry {index} is malformed"
            ) from error
        tracks.append(track)
    return tuple(tracks)


def traffic_occupancy_cost(
    point_xy: tuple[float, float],
    tracks: Sequence[object],
    *,
    horizon_s: float = 3.0,
    step_s: float = 0.25,
    influence_m: float = 0.9,
    decay_half_life_s: float | None = None,
    max_age_s: float | None = None,
) -> float:
    """Time-integrated proximity of predicted agent paths to ``point_xy``.

    Each track is rolled out at constant velocity over ``horizon_s``. Per
    sample, proximity is ``1`` at or inside the agent disc and falls
    linearly to ``0`` at ``influence_m`` beyond the disc surface. The cost
    is the rectangle-rule sum ``Σ proximity(t) · w(t) · dt`` over all tracks
    and samples, where ``w(t) = 1`` or ``2^(−t / decay_half_life_s)`` when a
    decay is configured.

    Sampling (SB-1/SB-2): the per-track substep is
    ``min(step_s, influence_m / (2·speed))`` — so no constant-velocity
    track can step across the influence band and score a spurious ``0.0``
    (the pre-SB-1 defect at ≥10 m/s) — floored at
    ``horizon_s / MAX_SAMPLES_PER_TRACK`` so pathological ``step_s`` values
    degrade resolution instead of stalling the caller. Pedestrian-speed
    tracks (≤ ``influence_m / (2·step_s)`` = 1.8 m/s at defaults) sample on
    exactly the ``step_s`` grid, so slow-track costs are unchanged by SB-1.

    Units: (weighted) *exposure seconds*. With no decay, a single agent
    parked on the point contributes ``≈ horizon_s + step_s`` (one closed
    sample grid); ``0.0`` means no predicted path enters the influence
    band. Note the coupling (SB-7): because the grid is closed, ``step_s``
    is not a pure resolution knob — a parked agent integrates to
    ``horizon_s + step_s``, so changing ``step_s`` at fixed weights slightly
    re-tunes the static↔traffic tradeoff.

    ``max_age_s`` (SB-5): when set, tracks with ``age_s > max_age_s`` are
    excluded before rollout — extrapolating a stale track is confidently
    wrong. ``None`` disables the filter.

    Deterministic: identical inputs give bit-identical output. Empty
    ``tracks`` returns exactly ``0.0``. Malformed input raises
    ``ValueError``.
    """

    try:
        px = _finite_float(point_xy[0], "point_xy[0]")
        py = _finite_float(point_xy[1], "point_xy[1]")
    except (TypeError, IndexError, KeyError) as error:
        raise ValueError("point_xy must be an (x, y) pair") from error
    horizon = _validated_positive(horizon_s, "horizon_s")
    step = _validated_positive(step_s, "step_s")
    influence = _validated_positive(influence_m, "influence_m")
    if step > horizon:
        raise ValueError("step_s must not exceed horizon_s")
    if decay_half_life_s is not None:
        _validated_positive(decay_half_life_s, "decay_half_life_s")
    _validated_max_age(max_age_s)
    validated = _fresh_tracks(coerce_tracks(tracks), max_age_s)
    if not validated:
        return 0.0

    floor_s = horizon / MAX_SAMPLES_PER_TRACK
    total = 0.0
    for track in validated:
        speed = math.hypot(track.vx, track.vy)
        sub = step
        if speed > 0.0:
            # SB-1: at most half the influence band per substep — a swept
            # path through the band cannot fall between samples.
            sub = min(sub, influence / (2.0 * speed))
        sub = max(sub, floor_s)
        steps = math.floor(horizon / sub + 1e-9)
        for k in range(steps + 1):
            t = k * sub
            cx = track.x + track.vx * t
            cy = track.y + track.vy * t
            surface = max(0.0, math.hypot(px - cx, py - cy) - track.radius_m)
            proximity = max(0.0, 1.0 - surface / influence)
            if proximity <= 0.0:
                continue
            weight = 1.0 if decay_half_life_s is None else 2.0 ** (-t / decay_half_life_s)
            total += proximity * weight * sub
    return total


def rank_approach_candidates(
    candidates: Sequence[tuple[float, float]],
    tracks: Sequence[object],
    *,
    static_cost_fn: Callable[[tuple[float, float]], float] | None = None,
    static_costs: Sequence[float] | None = None,
    static_weight: float = 1.0,
    traffic_weight: float = 1.0,
    horizon_s: float = 3.0,
    step_s: float = 0.25,
    influence_m: float = 0.9,
    decay_half_life_s: float | None = None,
    top_k: int | None = None,
    max_age_s: float | None = None,
) -> list[RankedCandidate]:
    """Rank candidate points best-first by static suitability + traffic cost.

    Static suitability comes from the caller — either ``static_cost_fn``
    (called once per candidate; must return a finite float, lower = better)
    or precomputed ``static_costs`` aligned with ``candidates``. Passing
    both, or a non-finite static cost, raises. With neither, static cost is
    ``0.0`` and traffic alone ranks.

    Ladder rule (pinned by tests): when ``tracks`` is empty every traffic
    cost is exactly ``0.0`` and the sort key ``(total, static, index)``
    reduces to the static ordering ``(static, index)`` — byte-identical, for
    any ``static_weight > 0``. The same holds for ``traffic_weight = 0``.

    ``top_k`` (SB-5): when set, only the ``top_k`` statically best
    candidates (by ``(static_cost, index)``) receive traffic evaluation and
    appear in the result — this bounds the rollout cost at large candidate
    grids (``approach.py`` can produce ~1.7k interior samples). The ladder
    rule still holds on the returned subset: with no tracks the result is
    exactly the static head. ``None`` ranks every candidate.

    ``max_age_s`` (SB-5): stale-track filter, forwarded to
    :func:`traffic_occupancy_cost`. If every track is stale the ranking
    degrades to the static ordering exactly as with empty ``tracks``.

    Returns candidates with their cost breakdown so eval tooling can
    attribute placement decisions. Malformed input raises ``ValueError``.
    """

    if static_cost_fn is not None and static_costs is not None:
        raise ValueError("pass static_cost_fn or static_costs, not both")
    weight_static = _finite_float(static_weight, "static_weight")
    if weight_static <= 0.0:
        raise ValueError("static_weight must be finite and positive")
    weight_traffic = _finite_float(traffic_weight, "traffic_weight")
    if weight_traffic < 0.0:
        raise ValueError("traffic_weight must be finite and non-negative")
    if top_k is not None and (
        isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1
    ):
        raise ValueError("top_k must be a positive integer or None")
    _validated_max_age(max_age_s)

    try:
        raw_candidates = list(candidates)
    except TypeError as error:
        raise ValueError("candidates must be an iterable of (x, y) pairs") from error
    points: list[tuple[float, float]] = []
    for index, candidate in enumerate(raw_candidates):
        try:
            x = _finite_float(candidate[0], f"candidate {index} x")
            y = _finite_float(candidate[1], f"candidate {index} y")
        except (TypeError, IndexError, KeyError) as error:
            raise ValueError(f"candidate {index} must be an (x, y) pair") from error
        points.append((x, y))
    if static_costs is not None and len(static_costs) != len(points):
        raise ValueError("static_costs length must match candidates")

    statics: list[float] = []
    for index, point in enumerate(points):
        if static_costs is not None:
            value = static_costs[index]
        elif static_cost_fn is not None:
            value = static_cost_fn(point)
        else:
            value = 0.0
        statics.append(_finite_float(value, f"static cost for candidate {index}"))

    selected = list(range(len(points)))
    if top_k is not None and top_k < len(selected):
        selected = sorted(selected, key=lambda i: (statics[i], i))[:top_k]
        selected.sort()  # deterministic evaluation order by original index

    validated = _fresh_tracks(coerce_tracks(tracks), max_age_s)
    ranked: list[RankedCandidate] = []
    for index in selected:
        point = points[index]
        static = statics[index]
        if validated and weight_traffic > 0.0:
            traffic = traffic_occupancy_cost(
                point,
                validated,
                horizon_s=horizon_s,
                step_s=step_s,
                influence_m=influence_m,
                decay_half_life_s=decay_half_life_s,
            )
        else:
            traffic = 0.0
        ranked.append(
            RankedCandidate(
                index=index,
                x=point[0],
                y=point[1],
                static_cost=static,
                traffic_cost=traffic,
                total_cost=weight_static * static + weight_traffic * traffic,
            )
        )
    ranked.sort(key=lambda item: (item.total_cost, item.static_cost, item.index))
    return ranked


class RampMemory:
    """Yield-advance pacing memory across brief person-stop interruptions.

    Protocol (caller = the layer that owns the stop decision, per tick):

    - moving tick → ``note_running(now_s, commanded_vx)`` with the pre-gate
      forward command;
    - gated tick (person_stop) → ``note_stopped(now_s)`` — returns nothing;
    - first tick after the gate opens → ``seed = release(now_s)`` and seed
      the controller's slew state with ``seed`` instead of zero.

    ``note_running`` ignores commands below ``min_record_vx`` (default
    0.05 m/s, SB-4): controller align/hold ticks legitimately command ~zero
    velocity, and recording them would wipe the very memory this class
    exists to hold across a corner-flap-plus-pedestrian sequence. Ignored
    ticks still validate their inputs and advance the time guard. (The
    wiring applies the same guard on its side — intentional defense in
    depth per arbitration OB-4/SB-4.)

    ``release`` returns ``held · resume_scale · 2^(−stop/decay_half_life_s)``
    for stops shorter than ``max_hold_s`` and exactly ``0.0`` otherwise,
    clearing the held memory — the monotonic time base survives; only
    ``reset()`` is a full reset. It never emits during a stop:
    ``note_stopped`` has no return value and no query yields a command
    while stopped — ``held_velocity_mps`` is telemetry, not a command. See
    the module docstring for the safety argument. Time is caller-supplied
    monotonic seconds; a regression raises ``ValueError``.
    """

    _IDLE = "idle"
    _RUNNING = "running"
    _STOPPED = "stopped"

    def __init__(
        self,
        *,
        max_hold_s: float = 2.5,
        decay_half_life_s: float = 1.5,
        resume_scale: float = 0.75,
        min_record_vx: float = 0.05,
    ) -> None:
        self.max_hold_s = _validated_positive(max_hold_s, "max_hold_s")
        self.decay_half_life_s = _validated_positive(decay_half_life_s, "decay_half_life_s")
        scale = _finite_float(resume_scale, "resume_scale")
        if not 0.0 < scale <= 1.0:
            raise ValueError("resume_scale must be finite and in (0, 1]")
        self.resume_scale = scale
        floor = _finite_float(min_record_vx, "min_record_vx")
        if floor < 0.0:
            raise ValueError("min_record_vx must be non-negative")
        self.min_record_vx = floor
        self._state = self._IDLE
        self._held_vx = 0.0
        self._stop_started_s: float | None = None
        self._last_now_s: float | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def held_velocity_mps(self) -> float:
        """Remembered pre-stop command (telemetry only — never a command)."""

        return self._held_vx

    def note_running(self, now_s: float, commanded_vx: float) -> None:
        """Record the pre-gate forward command for a moving (ungated) tick.

        Commands below ``min_record_vx`` are validated but not recorded
        (SB-4): an align/hold tick must not wipe the held ramp state.
        """

        self._advance_time(now_s)
        vx = _finite_float(commanded_vx, "commanded_vx")
        if vx < 0.0:
            raise ValueError("commanded_vx must be non-negative (forward ramps only)")
        if vx < self.min_record_vx:
            return
        self._state = self._RUNNING
        self._held_vx = vx
        self._stop_started_s = None

    def note_stopped(self, now_s: float) -> None:
        """Record a gated (person_stop) tick. Remembers; never emits."""

        self._advance_time(now_s)
        if self._state != self._STOPPED:
            self._state = self._STOPPED
            self._stop_started_s = now_s
            return
        assert self._stop_started_s is not None
        if now_s - self._stop_started_s >= self.max_hold_s:
            # Long stop: the world has changed; drop the memory entirely.
            self._held_vx = 0.0

    def release(self, now_s: float) -> float:
        """Seed velocity for the first tick after the gate has opened.

        Calling this is the caller's assertion that its own safety gate
        already released; the memory has no gate authority. Returns ``0.0``
        when there is nothing (or nothing recent enough) to resume. A long
        stop clears the held memory; the time base survives (only
        ``reset()`` clears everything).
        """

        self._advance_time(now_s)
        if self._state != self._STOPPED or self._stop_started_s is None:
            return 0.0
        elapsed = now_s - self._stop_started_s
        self._stop_started_s = None
        self._state = self._RUNNING
        if elapsed >= self.max_hold_s or self._held_vx <= 0.0:
            self._held_vx = 0.0
            return 0.0
        seed = self._held_vx * self.resume_scale * 2.0 ** (-elapsed / self.decay_half_life_s)
        # Remember the seed, not the stale pre-stop command: an immediate
        # second stop must decay from what was actually resumed.
        self._held_vx = seed
        return seed

    def reset(self) -> None:
        """Full reset (mission change, emergency stop, new time base)."""

        self._state = self._IDLE
        self._held_vx = 0.0
        self._stop_started_s = None
        self._last_now_s = None

    def _advance_time(self, now_s: float) -> None:
        now = _finite_float(now_s, "now_s")
        if self._last_now_s is not None and now < self._last_now_s:
            raise ValueError(
                "now_s must be monotonically non-decreasing (reset() for a new time base)"
            )
        self._last_now_s = now


def _finite_float(value: object, name: str) -> float:
    """SB-3 boundary coercion: any non-numeric or non-finite input is ValueError."""

    if isinstance(value, bool):
        # SB-3: ValueError by contract, including wrong-type input.
        raise ValueError(f"{name} must be a finite number")  # noqa: TRY004
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite number") from error
    if not math.isfinite(out):
        raise ValueError(f"{name} must be a finite number")
    return out


def _validated_positive(value: float, name: str) -> float:
    out = _finite_float(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return out


def _validated_max_age(max_age_s: float | None) -> None:
    if max_age_s is None:
        return
    if _finite_float(max_age_s, "max_age_s") < 0.0:
        raise ValueError("max_age_s must be non-negative")


def _fresh_tracks(
    tracks: tuple[TrackState, ...],
    max_age_s: float | None,
) -> tuple[TrackState, ...]:
    if max_age_s is None:
        return tracks
    limit = float(max_age_s)
    return tuple(track for track in tracks if track.age_s <= limit)
