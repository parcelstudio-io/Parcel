"""Tests for the N11 pure traffic-aware placement + pacing layer.

Pins the module contract before wiring: traffic cost geometry, the ladder
rule (empty tracks ⇒ byte-identical static ordering), RampMemory
hold/decay/reset semantics including never-emits-during-stop, determinism,
and loud rejection of malformed input.
"""

from __future__ import annotations

import math

import pytest

from parcel_robot.navigation.dynamic_costs import AgentTrack
from parcel_robot.navigation.traffic_aware import (
    DEFAULT_MAX_TRACKS,
    RampMemory,
    TrackState,
    coerce_tracks,
    rank_approach_candidates,
    tracks_from_payload,
    traffic_occupancy_cost,
)

# ---------------------------------------------------------------------------
# tracks_from_payload (stdlib-pure dynamic_agents adapter)
# ---------------------------------------------------------------------------


def test_tracks_from_payload_none_and_empty() -> None:
    assert tracks_from_payload(None) == ()
    assert tracks_from_payload([]) == ()
    assert tracks_from_payload(()) == ()


def test_tracks_from_payload_parses_runtime_shape() -> None:
    # Mirrors runtime._dynamic_agent_payload field set.
    tracks = tracks_from_payload(
        [
            {"x": 1.0, "y": 2.0, "vx": 0.5, "vy": -0.25, "radius_m": 0.4},
            {"x": -1.0, "y": 0.0, "vx": 0.0, "vy": 1.0},  # default radius
        ]
    )
    assert tracks == (
        TrackState(1.0, 2.0, 0.5, -0.25, radius_m=0.4),
        TrackState(-1.0, 0.0, 0.0, 1.0, radius_m=0.35),
    )


def test_tracks_from_payload_feeds_occupancy_cost() -> None:
    tracks = tracks_from_payload(
        [{"x": 0.0, "y": 0.0, "vx": 0.0, "vy": 0.0, "radius_m": 0.3}]
    )
    cost = traffic_occupancy_cost((0.0, 0.0), tracks, horizon_s=3.0, step_s=0.25)
    assert cost == pytest.approx(3.25)


def test_tracks_from_payload_caps_at_default_max() -> None:
    payload = [
        {"x": float(i), "y": 0.0, "vx": 0.0, "vy": 0.0} for i in range(DEFAULT_MAX_TRACKS + 5)
    ]
    tracks = tracks_from_payload(payload)
    assert len(tracks) == DEFAULT_MAX_TRACKS
    assert tracks[0].x == 0.0
    assert tracks[-1].x == float(DEFAULT_MAX_TRACKS - 1)


def test_tracks_from_payload_rejects_malformed() -> None:
    with pytest.raises(ValueError, match="entry 0 is malformed"):
        tracks_from_payload([{"x": 1.0, "y": 2.0}])  # missing vx/vy
    with pytest.raises(ValueError, match="entry 0"):
        tracks_from_payload([{"x": float("nan"), "y": 0.0, "vx": 0.0, "vy": 0.0}])
    with pytest.raises(ValueError, match="entry 0 is malformed"):
        tracks_from_payload([{"x": 0.0, "y": 0.0, "vx": 0.0, "vy": 0.0, "radius_m": -0.1}])
    # SB-3: malformed payload shapes raise ValueError, never TypeError.
    with pytest.raises(ValueError, match="entry 1 is malformed"):
        tracks_from_payload(
            [
                {"x": 0.0, "y": 0.0, "vx": 0.0, "vy": 0.0},
                "not-a-mapping",
            ]
        )
    with pytest.raises(ValueError, match="iterable of mappings"):
        tracks_from_payload("not-a-payload")
    with pytest.raises(ValueError, match="iterable of mappings"):
        tracks_from_payload(42)
    with pytest.raises(ValueError, match="max_tracks"):
        tracks_from_payload([], max_tracks=-1)
    with pytest.raises(ValueError, match="max_tracks"):
        tracks_from_payload([], max_tracks=True)  # bool is not an admissible count


# ---------------------------------------------------------------------------
# traffic_occupancy_cost
# ---------------------------------------------------------------------------


def test_empty_tracks_cost_is_exactly_zero() -> None:
    assert traffic_occupancy_cost((3.0, -2.0), []) == 0.0


def test_stationary_agent_on_point_integrates_full_horizon() -> None:
    track = TrackState(0.0, 0.0, 0.0, 0.0, radius_m=0.3)
    cost = traffic_occupancy_cost((0.0, 0.0), [track], horizon_s=3.0, step_s=0.25)
    # Closed sample grid: (horizon/step + 1) samples at proximity 1.
    assert cost == pytest.approx(3.25)


def test_cost_decreases_with_distance_from_path() -> None:
    walker = TrackState(0.0, 0.0, 1.0, 0.0, radius_m=0.3)
    near = traffic_occupancy_cost((2.0, 0.3), [walker])
    mid = traffic_occupancy_cost((2.0, 1.0), [walker])
    far = traffic_occupancy_cost((2.0, 6.0), [walker])
    assert near > mid > far
    assert far == 0.0


def test_point_on_predicted_path_beats_point_behind_agent() -> None:
    # Pedestrian walking +x: a point 2 m ahead is exposure; 2 m behind is not.
    walker = TrackState(0.0, 0.0, 1.2, 0.0, radius_m=0.3)
    ahead = traffic_occupancy_cost((2.4, 0.0), [walker])
    behind = traffic_occupancy_cost((-2.4, 0.0), [walker])
    assert ahead > behind


def test_horizon_extends_reach_of_swept_path() -> None:
    walker = TrackState(0.0, 0.0, 1.0, 0.0, radius_m=0.3)
    point = (3.5, 0.0)  # reached at t = 3.5 s
    short = traffic_occupancy_cost(point, [walker], horizon_s=2.0)
    long = traffic_occupancy_cost(point, [walker], horizon_s=5.0)
    assert short == 0.0
    assert long > 0.0


def test_decay_discounts_late_exposure() -> None:
    walker = TrackState(0.0, 0.0, 1.0, 0.0, radius_m=0.3)
    late_point = (2.5, 0.0)
    undecayed = traffic_occupancy_cost(late_point, [walker], horizon_s=4.0)
    decayed = traffic_occupancy_cost(
        late_point, [walker], horizon_s=4.0, decay_half_life_s=0.8
    )
    assert 0.0 < decayed < undecayed


def test_cost_sums_over_tracks() -> None:
    one = TrackState(0.0, 0.0, 0.0, 0.0, radius_m=0.3)
    single = traffic_occupancy_cost((0.0, 0.0), [one])
    double = traffic_occupancy_cost((0.0, 0.0), [one, one])
    assert double == pytest.approx(2.0 * single)


def test_accepts_agent_track_duck_types_and_tuples() -> None:
    duck = AgentTrack(1.0, 2.0, 0.5, 0.0, radius_m=0.4)
    native = TrackState(1.0, 2.0, 0.5, 0.0, radius_m=0.4)
    as_tuple = (1.0, 2.0, 0.5, 0.0, 0.4)
    point = (2.0, 2.0)
    reference = traffic_occupancy_cost(point, [native])
    assert traffic_occupancy_cost(point, [duck]) == reference
    assert traffic_occupancy_cost(point, [as_tuple]) == reference
    # 4-tuple takes the default radius.
    assert coerce_tracks([(1.0, 2.0, 0.5, 0.0)])[0].radius_m == 0.35


def test_cost_is_deterministic() -> None:
    tracks = [
        TrackState(0.3, -1.2, 0.7, 0.4, radius_m=0.31),
        TrackState(-2.0, 4.0, -0.3, -1.1, radius_m=0.27),
    ]
    first = traffic_occupancy_cost((1.234, -0.567), tracks, decay_half_life_s=0.9)
    second = traffic_occupancy_cost((1.234, -0.567), tracks, decay_half_life_s=0.9)
    assert first == second


@pytest.mark.parametrize(
    "kwargs",
    [
        {"horizon_s": 0.0},
        {"horizon_s": -1.0},
        {"horizon_s": math.nan},
        {"step_s": 0.0},
        {"step_s": math.inf},
        {"step_s": 5.0},  # step > horizon
        {"influence_m": 0.0},
        {"influence_m": -0.5},
        {"decay_half_life_s": 0.0},
        {"decay_half_life_s": -1.0},
    ],
)
def test_invalid_parameters_raise(kwargs: dict[str, float]) -> None:
    track = TrackState(0.0, 0.0, 1.0, 0.0)
    with pytest.raises(ValueError):
        traffic_occupancy_cost((0.0, 0.0), [track], **kwargs)


def test_invalid_point_and_tracks_raise() -> None:
    with pytest.raises(ValueError):
        traffic_occupancy_cost((math.nan, 0.0), [])
    with pytest.raises(ValueError):
        traffic_occupancy_cost((0.0, 0.0), [(0.0, math.nan, 0.0, 0.0)])
    with pytest.raises(ValueError):
        traffic_occupancy_cost((0.0, 0.0), [(0.0, 0.0, 0.0, 0.0, -0.1)])
    with pytest.raises(ValueError):
        traffic_occupancy_cost((0.0, 0.0), [(1.0, 2.0)])  # short sequence
    with pytest.raises(ValueError):
        TrackState(0.0, 0.0, math.inf, 0.0)


@pytest.mark.parametrize("speed", [10.0, 15.0])
def test_fast_agent_does_not_tunnel(speed: float) -> None:
    """SB-1 pin: a track crossing straight through the point must never
    score exactly 0.0, whatever its speed (pre-fix: 10 m/s -> 0.0)."""

    # Crossing at t = 0.375, the midpoint of a step_s = 0.25 grid interval:
    # the nearest fixed-grid samples sit at 0.125 s * speed >= 1.25 m from
    # the point, outside the radius+influence band (1.2 m), so the pre-SB-1
    # fixed grid scored exactly 0.0 here.
    track = TrackState(-speed * 0.375, 0.0, speed, 0.0, radius_m=0.3)
    cost = traffic_occupancy_cost((0.0, 0.0), [track])
    assert cost > 0.0


def test_adaptive_substep_leaves_pedestrian_costs_unchanged() -> None:
    """SB-1 tightens sampling only above influence_m/(2*step_s) = 1.8 m/s."""

    walker = TrackState(0.0, 0.0, 1.3, 0.0, radius_m=0.3)
    # 1.3 m/s < 1.8 m/s: the sample grid is exactly the step_s grid, so this
    # value is pinned to the pre-SB-1 fixed-grid result.
    fixed_grid = 0.0
    steps = math.floor(3.0 / 0.25 + 1e-9)
    for k in range(steps + 1):
        t = k * 0.25
        surface = max(0.0, math.hypot(2.4 - 1.3 * t, 0.3) - 0.3)
        fixed_grid += max(0.0, 1.0 - surface / 0.9) * 0.25
    assert traffic_occupancy_cost((2.4, 0.3), [walker]) == pytest.approx(fixed_grid)


def test_sample_count_is_capped() -> None:
    """SB-2 pin: a pathological step_s degrades resolution, not latency."""

    parked = TrackState(0.0, 0.0, 0.0, 0.0, radius_m=0.3)
    cost = traffic_occupancy_cost((0.0, 0.0), [parked], horizon_s=3.0, step_s=1e-6)
    # Substep floored at horizon/MAX_SAMPLES_PER_TRACK: ~4097 samples, and the
    # integral converges to ~horizon (+ one floored substep of closed-grid bias).
    assert cost == pytest.approx(3.0, abs=0.01)


def test_stale_tracks_are_excluded_by_max_age() -> None:
    """SB-5: CV-extrapolating a stale track is confidently wrong — filter it."""

    fresh = TrackState(0.0, 0.0, 0.0, 0.0, radius_m=0.3, age_s=0.2)
    stale = TrackState(0.0, 0.0, 0.0, 0.0, radius_m=0.3, age_s=5.0)
    both = traffic_occupancy_cost((0.0, 0.0), [fresh, stale])
    filtered = traffic_occupancy_cost((0.0, 0.0), [fresh, stale], max_age_s=1.0)
    only_fresh = traffic_occupancy_cost((0.0, 0.0), [fresh])
    assert filtered == pytest.approx(only_fresh)
    assert both == pytest.approx(2.0 * only_fresh)
    # All-stale degrades to exactly the empty-tracks result.
    assert traffic_occupancy_cost((0.0, 0.0), [stale], max_age_s=1.0) == 0.0
    with pytest.raises(ValueError):
        traffic_occupancy_cost((0.0, 0.0), [fresh], max_age_s=-1.0)
    with pytest.raises(ValueError):
        TrackState(0.0, 0.0, 0.0, 0.0, age_s=-0.1)


def test_age_travels_through_payload_and_duck_types() -> None:
    tracks = tracks_from_payload(
        [{"x": 0.0, "y": 0.0, "vx": 0.0, "vy": 0.0, "age_s": 2.5}]
    )
    assert tracks[0].age_s == 2.5
    # Duck types without age_s (e.g. AgentTrack) read as fresh.
    assert coerce_tracks([AgentTrack(0.0, 0.0, 0.0, 0.0)])[0].age_s == 0.0


# ---------------------------------------------------------------------------
# rank_approach_candidates
# ---------------------------------------------------------------------------


def _distance_from(origin: tuple[float, float]):
    def cost(point: tuple[float, float]) -> float:
        return math.hypot(point[0] - origin[0], point[1] - origin[1])

    return cost


def test_crossing_stream_ranks_below_clear_entry() -> None:
    # Two statically identical entries into the sidewalk region; a pedestrian
    # stream sweeps past one of them. The quiet entry must win.
    robot = (0.0, 0.0)
    busy = (4.0, 2.0)
    quiet = (4.0, -2.0)
    assert _distance_from(robot)(busy) == _distance_from(robot)(quiet)
    stream = [
        TrackState(4.0, 6.0, 0.0, -1.3, radius_m=0.3),
        TrackState(4.5, 8.0, 0.0, -1.3, radius_m=0.3),
    ]
    ranked = rank_approach_candidates([busy, quiet], stream, static_cost_fn=_distance_from(robot))
    assert (ranked[0].x, ranked[0].y) == quiet
    assert (ranked[1].x, ranked[1].y) == busy
    assert ranked[0].traffic_cost < ranked[1].traffic_cost
    assert ranked[1].traffic_cost > 0.0
    # Breakdown is attributable: total = static + traffic at unit weights.
    for item in ranked:
        assert item.total_cost == pytest.approx(item.static_cost + item.traffic_cost)


def test_traffic_cost_only_overrides_static_when_it_matters() -> None:
    # A slightly worse static candidate away from the stream must beat a
    # slightly better one inside it — the exact xfail geometry.
    robot = (0.0, 0.0)
    in_stream = (3.0, 0.0)
    off_stream = (3.2, -1.5)
    stream = [TrackState(3.0, 3.0, 0.0, -1.2, radius_m=0.3)]
    static = _distance_from(robot)
    assert static(in_stream) < static(off_stream)
    ranked = rank_approach_candidates([in_stream, off_stream], stream, static_cost_fn=static)
    assert (ranked[0].x, ranked[0].y) == off_stream


def test_empty_tracks_ordering_identical_to_static_ordering() -> None:
    robot = (0.5, -0.5)
    candidates = [
        (2.0, 1.0),
        (1.0, 1.0),
        (3.0, -1.0),
        (1.0, 1.0),  # exact duplicate: index tie-break must preserve order
        (0.6, -0.4),
    ]
    static = _distance_from(robot)
    ranked = rank_approach_candidates(candidates, [], static_cost_fn=static)
    expected = sorted(
        range(len(candidates)), key=lambda i: (static(candidates[i]), i)
    )
    assert [item.index for item in ranked] == expected
    assert all(item.traffic_cost == 0.0 for item in ranked)
    # Byte-identical points, not merely equivalent ordering.
    assert [(item.x, item.y) for item in ranked] == [candidates[i] for i in expected]


def test_zero_traffic_weight_degrades_to_static_even_with_tracks() -> None:
    robot = (0.0, 0.0)
    candidates = [(2.0, 2.0), (1.0, 0.0), (3.0, 0.0)]
    stream = [TrackState(1.0, 3.0, 0.0, -1.0, radius_m=0.3)]
    static = _distance_from(robot)
    with_tracks = rank_approach_candidates(
        candidates, stream, static_cost_fn=static, traffic_weight=0.0
    )
    without_tracks = rank_approach_candidates(candidates, [], static_cost_fn=static)
    assert [item.index for item in with_tracks] == [item.index for item in without_tracks]
    assert all(item.traffic_cost == 0.0 for item in with_tracks)


def test_precomputed_static_costs_match_callable_path() -> None:
    robot = (0.0, 0.0)
    candidates = [(2.0, 1.0), (1.0, -1.0), (4.0, 0.0)]
    stream = [TrackState(2.0, 4.0, 0.0, -1.0, radius_m=0.3)]
    static = _distance_from(robot)
    by_fn = rank_approach_candidates(candidates, stream, static_cost_fn=static)
    by_list = rank_approach_candidates(
        candidates, stream, static_costs=[static(point) for point in candidates]
    )
    assert [(item.index, item.total_cost) for item in by_fn] == [
        (item.index, item.total_cost) for item in by_list
    ]


def test_weights_scale_the_combination() -> None:
    candidates = [(1.0, 0.0)]
    stream = [TrackState(1.0, 0.5, 0.0, 0.0, radius_m=0.3)]
    ranked = rank_approach_candidates(
        candidates,
        stream,
        static_costs=[2.0],
        static_weight=3.0,
        traffic_weight=0.5,
    )
    item = ranked[0]
    assert item.total_cost == pytest.approx(3.0 * 2.0 + 0.5 * item.traffic_cost)
    assert item.traffic_cost > 0.0


def test_empty_candidates_returns_empty_list() -> None:
    assert rank_approach_candidates([], [TrackState(0.0, 0.0, 1.0, 0.0)]) == []


def test_ranking_is_deterministic() -> None:
    candidates = [(1.1, 0.2), (0.9, -0.4), (2.2, 1.7)]
    stream = [TrackState(0.5, 2.0, 0.3, -1.0, radius_m=0.28)]
    first = rank_approach_candidates(candidates, stream, static_costs=[0.4, 0.4, 0.1])
    second = rank_approach_candidates(candidates, stream, static_costs=[0.4, 0.4, 0.1])
    assert first == second


def test_top_k_bounds_traffic_evaluation_to_static_best() -> None:
    """SB-5: only the K statically best candidates are evaluated/returned."""

    robot = (0.0, 0.0)
    candidates = [(5.0, 0.0), (1.0, 0.0), (3.0, 0.0), (2.0, 0.0), (4.0, 0.0)]
    static = _distance_from(robot)
    stream = [TrackState(1.0, 2.0, 0.0, -1.0, radius_m=0.3)]
    limited = rank_approach_candidates(candidates, stream, static_cost_fn=static, top_k=2)
    assert len(limited) == 2
    # The kept pair is exactly the two statically best (indices 1 and 3).
    assert {item.index for item in limited} == {1, 3}
    # Their relative ranking matches the unrestricted ranking's restriction.
    full = rank_approach_candidates(candidates, stream, static_cost_fn=static)
    full_restricted = [item.index for item in full if item.index in {1, 3}]
    assert [item.index for item in limited] == full_restricted
    # Ladder rule on the subset: no tracks -> exactly the static head.
    head = rank_approach_candidates(candidates, [], static_cost_fn=static, top_k=2)
    assert [(item.x, item.y) for item in head] == [(1.0, 0.0), (2.0, 0.0)]
    assert all(item.traffic_cost == 0.0 for item in head)
    # top_k >= len is a no-op.
    assert len(
        rank_approach_candidates(candidates, [], static_cost_fn=static, top_k=99)
    ) == len(candidates)
    for bad in (0, -1, True):
        with pytest.raises(ValueError):
            rank_approach_candidates(candidates, [], top_k=bad)


def test_rank_stale_tracks_degrade_to_static_ordering() -> None:
    """SB-5: an all-stale track set behaves exactly like empty tracks."""

    robot = (0.0, 0.0)
    candidates = [(3.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    static = _distance_from(robot)
    stale = [TrackState(1.0, 0.5, 0.0, 0.0, radius_m=0.3, age_s=9.0)]
    with_filter = rank_approach_candidates(
        candidates, stale, static_cost_fn=static, max_age_s=1.0
    )
    without_tracks = rank_approach_candidates(candidates, [], static_cost_fn=static)
    assert with_filter == without_tracks
    assert all(item.traffic_cost == 0.0 for item in with_filter)
    with pytest.raises(ValueError):
        rank_approach_candidates(candidates, stale, max_age_s=math.nan)


def test_rank_rejects_malformed_inputs() -> None:
    good = [(1.0, 0.0)]
    with pytest.raises(ValueError):
        rank_approach_candidates([(math.nan, 0.0)], [])
    with pytest.raises(ValueError):
        rank_approach_candidates(good, [], static_costs=[1.0, 2.0])  # length mismatch
    with pytest.raises(ValueError):
        rank_approach_candidates(good, [], static_costs=[math.inf])
    with pytest.raises(ValueError):
        rank_approach_candidates(good, [], static_cost_fn=lambda p: math.nan)
    with pytest.raises(ValueError):
        rank_approach_candidates(
            good, [], static_cost_fn=lambda p: 0.0, static_costs=[0.0]
        )
    with pytest.raises(ValueError):
        rank_approach_candidates(good, [], static_weight=0.0)
    with pytest.raises(ValueError):
        rank_approach_candidates(good, [], static_weight=-1.0)
    with pytest.raises(ValueError):
        rank_approach_candidates(good, [], traffic_weight=-0.1)
    with pytest.raises(ValueError):
        rank_approach_candidates(good, [], traffic_weight=math.nan)
    with pytest.raises(ValueError):
        rank_approach_candidates(good, [(0.0, math.nan, 0.0, 0.0)])


def test_public_entry_points_raise_valueerror_never_typeerror() -> None:
    """SB-3 pin: the documented contract is ValueError at every public
    boundary — the exact calls Opus measured as TypeError must now raise
    ValueError."""

    ramp = RampMemory()
    for call in (
        lambda: ramp.note_running(None, 0.5),
        lambda: ramp.note_stopped(None),
        lambda: ramp.release(None),
        lambda: ramp.note_running(0.0, None),
        lambda: RampMemory(resume_scale=None),
        lambda: RampMemory(max_hold_s=None),
        lambda: traffic_occupancy_cost((None, 0.0), []),
        lambda: traffic_occupancy_cost(None, []),
        lambda: traffic_occupancy_cost((0.0, 0.0), None),
        lambda: rank_approach_candidates(None, []),
        lambda: rank_approach_candidates([(1.0, 0.0)], None),
        lambda: rank_approach_candidates([None], []),
        lambda: rank_approach_candidates([(1.0, 0.0)], [], static_cost_fn=lambda p: None),
        lambda: coerce_tracks(None),
        lambda: tracks_from_payload(42),
        lambda: TrackState(None, 0.0, 0.0, 0.0),
    ):
        with pytest.raises(ValueError):
            call()


# ---------------------------------------------------------------------------
# RampMemory
# ---------------------------------------------------------------------------


def test_brief_stop_resumes_scaled_decayed_fraction() -> None:
    ramp = RampMemory(max_hold_s=2.5, decay_half_life_s=1.5, resume_scale=0.75)
    ramp.note_running(0.0, 0.85)
    ramp.note_stopped(0.1)
    seed = ramp.release(0.85)  # 0.75 s stop < max_hold_s
    expected = 0.85 * 0.75 * 2.0 ** (-0.75 / 1.5)
    assert seed == pytest.approx(expected)
    assert 0.0 < seed < 0.85
    assert ramp.state == "running"


def test_long_stop_fully_resets() -> None:
    ramp = RampMemory(max_hold_s=2.0, decay_half_life_s=1.0)
    ramp.note_running(0.0, 0.8)
    ramp.note_stopped(0.1)
    assert ramp.release(2.5) == 0.0  # 2.4 s ≥ max_hold_s
    assert ramp.held_velocity_mps == 0.0


def test_long_stop_clears_memory_even_before_release() -> None:
    ramp = RampMemory(max_hold_s=1.0, decay_half_life_s=1.0)
    ramp.note_running(0.0, 0.7)
    ramp.note_stopped(0.1)
    ramp.note_stopped(1.2)  # held ≥ max_hold_s while still stopped
    assert ramp.held_velocity_mps == 0.0
    assert ramp.release(1.3) == 0.0


def test_longer_stops_resume_slower() -> None:
    seeds = []
    for stop_s in (0.2, 0.8, 1.6):
        ramp = RampMemory(max_hold_s=2.5, decay_half_life_s=1.0)
        ramp.note_running(0.0, 0.85)
        ramp.note_stopped(1.0)
        seeds.append(ramp.release(1.0 + stop_s))
    assert seeds[0] > seeds[1] > seeds[2] > 0.0


def test_never_emits_during_stop() -> None:
    ramp = RampMemory()
    ramp.note_running(0.0, 0.85)
    # note_stopped returns nothing on every gated tick, however many.
    for tick in range(1, 6):
        assert ramp.note_stopped(0.1 * tick) is None
    assert ramp.state == "stopped"
    # The only readable value while stopped is telemetry, not a command.
    assert ramp.held_velocity_mps == pytest.approx(0.85)


def test_release_without_history_returns_zero() -> None:
    ramp = RampMemory()
    assert ramp.release(0.0) == 0.0
    ramp.note_running(1.0, 0.5)
    # Release while running (caller mistake) yields no seed, not a command.
    assert ramp.release(2.0) == 0.0


def test_release_consumes_the_stop_and_second_stop_decays_from_seed() -> None:
    ramp = RampMemory(max_hold_s=5.0, decay_half_life_s=1.0, resume_scale=1.0)
    ramp.note_running(0.0, 0.8)
    ramp.note_stopped(0.0)
    first = ramp.release(1.0)  # 0.8 * 2^-1 = 0.4
    assert first == pytest.approx(0.4)
    # Immediately gated again without a running tick: decay from the seed.
    ramp.note_stopped(1.0)
    second = ramp.release(2.0)
    assert second == pytest.approx(0.2)


def test_zero_velocity_memory_resumes_zero() -> None:
    ramp = RampMemory()
    ramp.note_running(0.0, 0.0)
    ramp.note_stopped(0.1)
    assert ramp.release(0.2) == 0.0


def test_reset_clears_state_and_time_base() -> None:
    ramp = RampMemory()
    ramp.note_running(10.0, 0.6)
    ramp.note_stopped(10.5)
    ramp.reset()
    assert ramp.state == "idle"
    assert ramp.held_velocity_mps == 0.0
    # New (earlier) time base is legal after reset.
    ramp.note_running(0.0, 0.3)
    ramp.note_stopped(0.5)
    assert ramp.release(0.6) > 0.0


def test_align_tick_does_not_wipe_held_state() -> None:
    """SB-4 pin: a zero/near-zero command tick (controller align/hold) is
    ignored, so the corner-flap-plus-pedestrian sequence keeps its memory."""

    ramp = RampMemory(max_hold_s=2.5, decay_half_life_s=1.5, resume_scale=1.0)
    ramp.note_running(0.0, 0.85)
    ramp.note_running(0.1, 0.0)  # align tick: vx forced to zero upstream
    ramp.note_running(0.2, 0.04)  # below the 0.05 default floor
    assert ramp.held_velocity_mps == pytest.approx(0.85)
    ramp.note_stopped(0.3)
    seed = ramp.release(0.5)
    assert seed == pytest.approx(0.85 * 2.0 ** (-0.2 / 1.5))


def test_min_record_vx_floor_is_configurable_and_validated() -> None:
    ramp = RampMemory(min_record_vx=0.2)
    ramp.note_running(0.0, 0.5)
    ramp.note_running(0.1, 0.15)  # below the raised floor: ignored
    assert ramp.held_velocity_mps == pytest.approx(0.5)
    ramp.note_running(0.2, 0.25)  # above: recorded
    assert ramp.held_velocity_mps == pytest.approx(0.25)
    # Ignored ticks still validate input and advance the time guard.
    with pytest.raises(ValueError):
        ramp.note_running(0.3, -0.01)
    with pytest.raises(ValueError):
        ramp.note_running(0.1, 0.0)  # time regression, even below the floor
    with pytest.raises(ValueError):
        RampMemory(min_record_vx=-0.1)
    with pytest.raises(ValueError):
        RampMemory(min_record_vx=math.nan)


def test_ramp_memory_is_deterministic() -> None:
    def run() -> list[float]:
        ramp = RampMemory(max_hold_s=2.5, decay_half_life_s=1.2, resume_scale=0.8)
        out = []
        ramp.note_running(0.0, 0.85)
        ramp.note_stopped(0.4)
        out.append(ramp.release(1.1))
        ramp.note_running(1.2, 0.5)
        ramp.note_stopped(1.5)
        out.append(ramp.release(3.9))
        return out

    assert run() == run()


def test_ramp_memory_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        RampMemory(max_hold_s=0.0)
    with pytest.raises(ValueError):
        RampMemory(decay_half_life_s=-1.0)
    with pytest.raises(ValueError):
        RampMemory(resume_scale=0.0)
    with pytest.raises(ValueError):
        RampMemory(resume_scale=1.5)
    with pytest.raises(ValueError):
        RampMemory(resume_scale=math.nan)
    ramp = RampMemory()
    with pytest.raises(ValueError):
        ramp.note_running(math.nan, 0.5)
    with pytest.raises(ValueError):
        ramp.note_running(0.0, math.inf)
    with pytest.raises(ValueError):
        ramp.note_running(0.0, -0.1)
    ramp.note_running(5.0, 0.5)
    with pytest.raises(ValueError):
        ramp.note_stopped(4.0)  # time regression
    with pytest.raises(ValueError):
        ramp.release(math.nan)
