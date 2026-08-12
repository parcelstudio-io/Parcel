"""RM-1 place graph: MAP-frame ingestion, recorded-edges-only routing, persistence.

Card RM-1 of ``scrum/20260811/task_2/SLAM_M_PLAN.md``.  Every gate item the card
names is a property test here, and every property test is paired with a
**seeded-failure proof**: a companion case that constructs the exact failure the
property forbids and shows the assertion goes red on it.  A property test that
cannot be made to fail is not evidence, and this file is the evidence.

The pairs:

===========================  ==========================================
property                     seeded failure that proves it bites
===========================  ==========================================
no invented edges            a fabricated straight-line chain across the
                             U-corridor is fed to the same checker
fail-closed no-route         the same visits WITHOUT the track break do
                             produce a route
persistence round-trip       five distinct corruptions each refuse, and
                             the live graph is byte-unchanged after
MAP frame in schema          an ODOM pose and an ODOM file both refuse
derived spacing              pinned against the live GridPlannerConfig,
                             plus the "one cell finer overlaps" check
determinism                  a different visit order serialises
                             differently, so equality has discriminating
                             power
re-anchor jump               the same geometry sampled contiguously
                             routes fine
===========================  ==========================================
"""

from __future__ import annotations

import ast
import itertools
import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.navigation.grid_planner import GridPlannerConfig
from parcel_robot.pose import Frame, PoseEstimate, PoseHealth
from parcel_robot.route_memory import (
    DEFAULT_ATTACH_RADIUS_M,
    DEFAULT_KEYFRAME_SPACING_M,
    DEFAULT_MAX_CONTIGUOUS_STEP_M,
    PLACE_GRAPH_SCHEMA,
    PlaceEdge,
    RouteKeyframe,
    RoutePlaceGraph,
    stub_embed_image,
)
from parcel_robot.route_memory import place_graph as place_graph_module
from parcel_robot.route_memory.place_graph import (
    GRID_GOAL_TOLERANCE_M,
    GRID_RESOLUTION_M,
    GRID_SIZE_CELLS,
    KEYFRAME_SPACING_CELLS,
    MAX_CONTIGUOUS_STEP_SPACINGS,
    NAV_CONTROL_DT_S,
    PLATFORM_MAX_VX_MPS,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def map_pose(x: float, y: float, yaw: float = 0.0, **kw: Any) -> PoseEstimate:
    return PoseEstimate(x=x, y=y, yaw=yaw, frame=Frame.MAP, **kw)


def walk(
    graph: RoutePlaceGraph,
    legs: Sequence[tuple[tuple[float, float], tuple[float, float]]],
    *,
    step_m: float = 0.25,
    start_tick: int = 0,
) -> int:
    """Drive ``graph`` along straight legs, sampling every ``step_m``."""

    tick = start_tick
    for a, b in legs:
        span = math.dist(a, b)
        n = max(1, round(span / step_m))
        for i in range(n + 1):
            f = i / n
            graph.record_visit(
                map_pose(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f),
                timestamp_tick=tick,
            )
            tick += 1
    return tick


def u_corridor_graph() -> RoutePlaceGraph:
    """(0,0) -> (10,0) -> (10,10) -> (0,10): 30 m walked, 10 m straight across."""

    graph = RoutePlaceGraph()
    walk(
        graph,
        [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (10.0, 10.0)), ((10.0, 10.0), (0.0, 10.0))],
    )
    return graph


def index_of(graph: RoutePlaceGraph, keyframe: RouteKeyframe) -> int:
    for i, cand in enumerate(graph.keyframes):
        if cand is keyframe or cand == keyframe:
            return i
    raise AssertionError("chain contains a keyframe that is not in the graph")


def assert_chain_uses_only_recorded_edges(
    graph: RoutePlaceGraph, chain: Sequence[RouteKeyframe]
) -> None:
    """THE property: every hop in a returned chain is an edge the robot walked.

    Recorded, routable (not laid across a MAP re-anchor), and present in the
    graph's own edge set.  Anything else is an invented shortcut.
    """

    assert chain, "empty chain — nothing to check; call this only on a real route"
    recorded = {edge.key for edge in graph.edges if edge.routable}
    indices = [index_of(graph, kf) for kf in chain]
    for a, b in itertools.pairwise(indices):
        key = (a, b) if a < b else (b, a)
        assert key in recorded, (
            f"chain hop {a}->{b} is not a recorded routable edge: invented shortcut"
        )


def chain_length_m(chain: Sequence[RouteKeyframe]) -> float:
    return sum(math.dist(chain[i].xy, chain[i + 1].xy) for i in range(len(chain) - 1))


# ---------------------------------------------------------------------------
# GATE: derived spacing pinned by reference
# ---------------------------------------------------------------------------


def test_derived_keyframe_spacing_pinned_by_reference() -> None:
    """The default spacing derives from the LIVE planner config, not a literal.

    If someone retunes ``GridPlannerConfig``, this reddens instead of leaving
    the derivation quietly false.
    """

    cfg = GridPlannerConfig()
    assert GRID_RESOLUTION_M == cfg.resolution_m
    assert GRID_GOAL_TOLERANCE_M == cfg.goal_tolerance_m
    assert GRID_SIZE_CELLS == cfg.grid_size_cells

    # The stated derivation, re-run here: spacing is an integer number of grid
    # cells, and it is the SMALLEST such multiple whose neighbouring arrival
    # discs (radius = goal_tolerance_m) do not overlap.
    assert DEFAULT_KEYFRAME_SPACING_M == KEYFRAME_SPACING_CELLS * cfg.resolution_m
    assert DEFAULT_KEYFRAME_SPACING_M >= 2.0 * cfg.goal_tolerance_m
    one_cell_finer = (KEYFRAME_SPACING_CELLS - 1) * cfg.resolution_m
    assert one_cell_finer < 2.0 * cfg.goal_tolerance_m, (
        "a finer spacing would still satisfy the constraint — the stated "
        "'smallest integer multiple' derivation is wrong"
    )
    assert DEFAULT_KEYFRAME_SPACING_M == pytest.approx(0.50)


def test_derived_step_and_attach_radius_pinned_by_reference() -> None:
    """Contiguity threshold and attach radius derive from live sources too."""

    cfg = GridPlannerConfig()

    # Attach radius = half the rolling planner window, so the legs memory hands
    # back to the planner always lie inside one window of live occupancy.
    assert DEFAULT_ATTACH_RADIUS_M == cfg.grid_size_cells * cfg.resolution_m / 2.0
    assert DEFAULT_ATTACH_RADIUS_M == pytest.approx(8.05)

    # Contiguity threshold, and the platform numbers its derivation cites.
    assert DEFAULT_MAX_CONTIGUOUS_STEP_M == (
        MAX_CONTIGUOUS_STEP_SPACINGS * DEFAULT_KEYFRAME_SPACING_M
    )
    assert DEFAULT_MAX_CONTIGUOUS_STEP_M == pytest.approx(2.00)
    robot_yaml = Path(__file__).resolve().parents[1] / "configs" / "robot.yaml"
    max_vx_lines = [
        line for line in robot_yaml.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("max_vx:")
    ]
    assert max_vx_lines, "configs/robot.yaml no longer declares max_vx"
    assert float(max_vx_lines[0].split(":")[1]) == PLATFORM_MAX_VX_MPS
    # 2.00 m at 1.0 m/s is 2.0 s, i.e. 20 navigation ticks of unobserved motion.
    implied_ticks = DEFAULT_MAX_CONTIGUOUS_STEP_M / PLATFORM_MAX_VX_MPS / NAV_CONTROL_DT_S
    assert implied_ticks == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# GATE: MAP-frame discipline, recorded in the schema
# ---------------------------------------------------------------------------


def test_record_visit_refuses_odom_frame() -> None:
    graph = RoutePlaceGraph()
    assert graph.frame is Frame.MAP
    with pytest.raises(ValueError, match="MAP-frame poses only"):
        graph.record_visit(PoseEstimate(x=0.0, y=0.0, yaw=0.0, frame=Frame.ODOM))
    assert len(graph) == 0


def test_record_visit_refuses_non_pose_estimate() -> None:
    graph = RoutePlaceGraph()
    with pytest.raises(TypeError, match="sanctioned seam"):
        graph.record_visit((0.0, 0.0, 0.0))  # type: ignore[arg-type]


def test_map_frame_recorded_in_persisted_schema(tmp_path: Path) -> None:
    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (3.0, 0.0))])
    payload = json.loads(graph.save(tmp_path / "g.json").read_text(encoding="utf-8"))

    assert payload["schema_version"] == PLACE_GRAPH_SCHEMA
    assert payload["frame"] == "map"
    assert payload["keyframes"], "no keyframes to check"
    # Per-keyframe, not just on the container: a keyframe read out of this file
    # is self-describing and a loader need not trust its envelope.
    for kf in payload["keyframes"]:
        assert kf["frame"] == "map"


def test_load_refuses_a_graph_claiming_another_frame(tmp_path: Path) -> None:
    """SEEDED FAILURE for the frame gate: an odom-framed file must not load."""

    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (3.0, 0.0))])
    good = graph.save(tmp_path / "good.json")

    payload = json.loads(good.read_text(encoding="utf-8"))
    payload["frame"] = "odom"
    bad = tmp_path / "odom_graph.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="frame must be 'map'"):
        RoutePlaceGraph().load(bad)

    # ...and a container that lies while its keyframes tell the truth.
    payload = json.loads(good.read_text(encoding="utf-8"))
    payload["keyframes"][1]["frame"] = "odom"
    bad2 = tmp_path / "odom_keyframe.json"
    bad2.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="claims frame 'odom'"):
        RoutePlaceGraph().load(bad2)


# ---------------------------------------------------------------------------
# GATE: no invented edges
# ---------------------------------------------------------------------------


def test_waypoints_toward_never_invents_a_straight_line_shortcut() -> None:
    """The U-corridor: 10 m across, 30 m around.  Memory must answer 30 m."""

    graph = u_corridor_graph()
    chain = graph.waypoints_toward((0.0, 10.0), (0.0, 0.0))

    assert chain, "the recorded route exists; an empty answer would be a false negative"
    assert_chain_uses_only_recorded_edges(graph, chain)
    assert chain[0].xy == pytest.approx((0.0, 0.0))
    assert chain[-1].xy == pytest.approx((0.0, 10.0))
    assert chain_length_m(chain) == pytest.approx(30.0, abs=1e-6)
    # The straight line across the mouth of the U is 10 m and is NOT the answer.
    assert chain_length_m(chain) > 3.0 * math.dist((0.0, 0.0), (0.0, 10.0)) - 1e-6
    assert len(chain) > 2
    # Both corners are on the route — it goes around, not through.
    corners = {(round(kf.x, 6), round(kf.y, 6)) for kf in chain}
    assert (10.0, 0.0) in corners
    assert (10.0, 10.0) in corners


def test_seeded_straight_line_shortcut_is_rejected() -> None:
    """SEEDED FAILURE: hand the checker the shortcut a broken router would return.

    This is the proof that the no-invented-edges assertion above bites.  The
    two-element chain (start, goal) is exactly the output of an implementation
    that connects spatially-near nodes instead of walked ones; the same checker
    that passes on the real route must reject it.
    """

    graph = u_corridor_graph()
    start = graph.keyframes[0]
    goal = graph.keyframes[index_of(graph, graph.waypoints_toward((0.0, 10.0), (0.0, 0.0))[-1])]
    shortcut = (start, goal)

    assert math.dist(start.xy, goal.xy) == pytest.approx(10.0)
    with pytest.raises(AssertionError, match="invented shortcut"):
        assert_chain_uses_only_recorded_edges(graph, shortcut)


def test_seeded_near_miss_shortcut_is_rejected() -> None:
    """SEEDED FAILURE, second form: two nodes 0.6 m apart but never walked between.

    Proximity is the tempting heuristic and the wrong one.  These two keyframes
    are closer to each other than most walked edges are long, and there is still
    no edge between them.
    """

    graph = RoutePlaceGraph()
    # Two parallel corridors 0.6 m apart, joined only at the far end.
    walk(graph, [((0.0, 0.0), (6.0, 0.0))])
    graph.reset_track()
    walk(graph, [((0.0, 0.6), (6.0, 0.6))])

    lower = graph.nearest_index((0.0, 0.0))
    upper = graph.nearest_index((0.0, 0.6))
    assert lower is not None and upper is not None
    assert math.dist(graph.keyframes[lower].xy, graph.keyframes[upper].xy) == pytest.approx(0.6)
    fabricated = (graph.keyframes[lower], graph.keyframes[upper])
    with pytest.raises(AssertionError, match="invented shortcut"):
        assert_chain_uses_only_recorded_edges(graph, fabricated)
    # And the router itself refuses to produce it.
    assert graph.waypoints_toward((0.0, 0.6), (0.0, 0.0)) == ()


# ---------------------------------------------------------------------------
# GATE: fail-closed no-route
# ---------------------------------------------------------------------------


def test_disconnected_components_return_empty_tuple() -> None:
    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (6.0, 0.0))])
    graph.reset_track()  # episode boundary: the teleport is not a traversal
    walk(graph, [((6.0, 1.5), (0.0, 1.5))])

    assert graph.waypoints_toward((0.0, 1.5), (0.0, 0.0)) == ()


def test_seeded_control_same_visits_without_the_track_break_do_route() -> None:
    """SEEDED FAILURE for fail-closed: prove the empty tuple is caused by the
    missing edge, not by a router that never returns anything.

    Identical geometry, identical sampling — the only difference is that the
    robot actually walked the 1.5 m connector instead of being teleported across
    it.  Then a route exists.
    """

    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (6.0, 0.0))])
    # no reset_track(): the connector is walked, so it is a real edge
    walk(graph, [((6.0, 1.5), (0.0, 1.5))])

    chain = graph.waypoints_toward((0.0, 1.5), (0.0, 0.0))
    assert chain, "the control must route, or the fail-closed test above is vacuous"
    assert_chain_uses_only_recorded_edges(graph, chain)


def test_attach_radius_fails_closed_beyond_the_planner_window() -> None:
    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (6.0, 0.0))])

    # Goal 20 m off the end of everything ever walked: memory has nothing to say.
    assert graph.waypoints_toward((26.0, 0.0), (0.0, 0.0)) == ()
    # Robot 20 m away from anything walked: likewise.
    assert graph.waypoints_toward((6.0, 0.0), (0.0, -20.0)) == ()
    # Control: just inside the window, memory answers.
    inside = graph.waypoints_toward((6.0 + DEFAULT_ATTACH_RADIUS_M - 0.5, 0.0), (0.0, 0.0))
    assert inside, "control must route, or the two refusals above prove nothing"
    assert_chain_uses_only_recorded_edges(graph, inside)


def test_empty_graph_and_self_attachment() -> None:
    graph = RoutePlaceGraph()
    assert graph.waypoints_toward((1.0, 1.0), (0.0, 0.0)) == ()

    walk(graph, [((0.0, 0.0), (2.0, 0.0))])
    same = graph.waypoints_toward((0.05, 0.0), (0.0, 0.0))
    assert len(same) == 1, "already at the keyframe nearest the goal"


# ---------------------------------------------------------------------------
# GATE: MAP re-anchor jump behaviour
# ---------------------------------------------------------------------------


def test_reanchor_jump_flags_the_edge_and_blocks_routing() -> None:
    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (4.0, 0.0))])
    # MAP jumps 5 m sideways — further than max_contiguous_step_m (2.0 m).
    walk(graph, [((4.0, 5.0), (8.0, 5.0))])

    flagged = [e for e in graph.edges if e.crossed_reanchor]
    assert len(flagged) == 1, "exactly one edge straddles the jump"
    assert graph.reanchor_events == 1
    # The keyframes on both sides are kept — the history stays honest...
    assert graph.nearest_index((4.0, 0.0), max_radius_m=0.1) is not None
    assert graph.nearest_index((4.0, 5.0), max_radius_m=0.1) is not None
    # ...but the jump is not a walk, so nothing routes across it.
    assert graph.waypoints_toward((8.0, 5.0), (0.0, 0.0)) == ()


def test_seeded_control_contiguous_sampling_of_the_same_geometry_routes() -> None:
    """SEEDED FAILURE for the jump gate: same endpoints, walked instead of jumped."""

    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (4.0, 0.0)), ((4.0, 0.0), (4.0, 5.0)), ((4.0, 5.0), (8.0, 5.0))])

    assert all(e.routable for e in graph.edges)
    assert graph.reanchor_events == 0
    chain = graph.waypoints_toward((8.0, 5.0), (0.0, 0.0))
    assert chain, "walked geometry must route, or the refusal above proves nothing"
    assert_chain_uses_only_recorded_edges(graph, chain)


def test_explicit_reanchored_flag_is_authoritative() -> None:
    """A caller that KNOWS a correction happened does not depend on the heuristic."""

    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (2.0, 0.0))])
    # A sub-threshold step (0.6 m < 2.0 m) the distance heuristic would accept.
    graph.record_visit(map_pose(2.6, 0.0), reanchored=True)

    assert graph.reanchor_events == 1
    assert any(e.crossed_reanchor for e in graph.edges)
    assert graph.waypoints_toward((2.6, 0.0), (0.0, 0.0)) == ()


def test_lost_pose_is_not_a_place_and_breaks_the_track() -> None:
    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (2.0, 0.0))])
    before = len(graph)

    assert graph.record_visit(map_pose(2.5, 0.0, health=PoseHealth.LOST)) is None
    assert len(graph) == before, "a lost pose is not a place"
    # Recovery lands elsewhere; the reconnecting edge is flagged.
    graph.record_visit(map_pose(3.0, 0.0, health=PoseHealth.HEALTHY))
    assert any(e.crossed_reanchor for e in graph.edges)


def test_degraded_pose_is_recorded_with_its_health() -> None:
    graph = RoutePlaceGraph()
    kf = graph.record_visit(map_pose(0.0, 0.0, health=PoseHealth.DEGRADED))
    assert kf is not None
    assert kf.meta["pose_health"] == "degraded"


# ---------------------------------------------------------------------------
# ingestion / admission
# ---------------------------------------------------------------------------


def test_keyframe_admission_respects_spacing() -> None:
    graph = RoutePlaceGraph()
    assert graph.record_visit(map_pose(0.0, 0.0)) is not None  # first is always a place
    assert graph.record_visit(map_pose(0.2, 0.0)) is None  # inside the place
    assert graph.record_visit(map_pose(0.49, 0.0)) is None
    admitted = graph.record_visit(map_pose(0.5, 0.0))  # exactly one spacing: admit
    assert admitted is not None
    assert len(graph) == 2
    assert len(graph.edges) == 1
    assert graph.edges[0].length_m == pytest.approx(0.5)


def test_custom_spacing_is_honoured() -> None:
    graph = RoutePlaceGraph(keyframe_spacing_m=2.0, max_contiguous_step_m=8.0)
    walk(graph, [((0.0, 0.0), (10.0, 0.0))], step_m=0.25)
    assert len(graph) == 6  # 0, 2, 4, 6, 8, 10
    assert graph.keyframe_spacing_m == pytest.approx(2.0)


def test_revisiting_a_place_closes_the_loop_instead_of_duplicating_it() -> None:
    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (4.0, 0.0)), ((4.0, 0.0), (0.0, 0.0))])

    # The return leg re-enters the same places; it must not grow a parallel chain.
    assert len(graph) == 9, "0.0 .. 4.0 at 0.5 m spacing, walked twice"
    assert all(e.traversals == 2 for e in graph.edges)
    chain = graph.waypoints_toward((4.0, 0.0), (0.0, 0.0))
    assert_chain_uses_only_recorded_edges(graph, chain)
    assert chain_length_m(chain) == pytest.approx(4.0)


def test_labels_and_ticks_land_on_the_keyframe() -> None:
    graph = RoutePlaceGraph()
    kf = graph.record_visit(
        map_pose(0.0, 0.0), semantic_labels=["bench", "bench", " tree "], timestamp_tick=17
    )
    assert kf is not None
    assert kf.labels == ("bench", "tree"), "deduped, stripped, order preserved"
    assert kf.tick == 17
    assert kf.frame == "map"


def test_ingestion_input_validation() -> None:
    graph = RoutePlaceGraph()
    with pytest.raises(TypeError, match="not a string"):
        graph.record_visit(map_pose(0.0, 0.0), semantic_labels="bench")
    with pytest.raises(TypeError, match="timestamp_tick"):
        graph.record_visit(map_pose(0.0, 0.0), timestamp_tick=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="timestamp_tick"):
        graph.record_visit(map_pose(0.0, 0.0), timestamp_tick=-1)


def test_constructor_validation() -> None:
    with pytest.raises(ValueError, match="keyframe_spacing_m"):
        RoutePlaceGraph(keyframe_spacing_m=0.0)
    with pytest.raises(ValueError, match=">= keyframe_spacing_m"):
        RoutePlaceGraph(keyframe_spacing_m=2.0, max_contiguous_step_m=1.0)
    with pytest.raises(TypeError, match="embed_fn"):
        RoutePlaceGraph(embed_fn=object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# GATE: persistence
# ---------------------------------------------------------------------------


def test_persistence_round_trip_is_byte_exact(tmp_path: Path) -> None:
    graph = u_corridor_graph()
    first = graph.save(tmp_path / "a.json")

    reloaded = RoutePlaceGraph().load(first)
    second = reloaded.save(tmp_path / "b.json")

    assert first.read_bytes() == second.read_bytes()
    assert reloaded.keyframes == graph.keyframes
    assert reloaded.edges == graph.edges
    assert reloaded.keyframe_spacing_m == graph.keyframe_spacing_m
    assert reloaded.attach_radius_m == graph.attach_radius_m
    assert reloaded.reanchor_events == graph.reanchor_events
    # The query survives the round trip identically.
    assert reloaded.waypoints_toward((0.0, 10.0), (0.0, 0.0)) == graph.waypoints_toward(
        (0.0, 10.0), (0.0, 0.0)
    )


def test_from_file_matches_load(tmp_path: Path) -> None:
    graph = u_corridor_graph()
    saved = graph.save(tmp_path / "a.json")
    assert RoutePlaceGraph.from_file(saved).keyframes == graph.keyframes


def test_load_resets_the_ingestion_track(tmp_path: Path) -> None:
    """A loaded graph has no 'previous keyframe' to fabricate an edge from."""

    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (4.0, 0.0))])
    saved = graph.save(tmp_path / "a.json")

    reloaded = RoutePlaceGraph().load(saved)
    edges_before = len(reloaded.edges)
    reloaded.record_visit(map_pose(40.0, 40.0))  # somewhere else entirely
    assert len(reloaded.edges) == edges_before, (
        "loading then recording must not stitch the file's last keyframe to "
        "wherever the robot happens to be now"
    )


def _corruptions(good: dict[str, Any]) -> list[tuple[str, Any, type[Exception]]]:
    """(name, payload, expected exception) — one per refusal mode."""

    bad_schema = json.loads(json.dumps(good))
    bad_schema["schema_version"] = "parcel.route_memory.place_graph.v99"

    missing_keyframes = json.loads(json.dumps(good))
    del missing_keyframes["keyframes"]

    dangling_edge = json.loads(json.dumps(good))
    dangling_edge["edges"][0]["b"] = len(good["keyframes"]) + 5

    duplicate_edge = json.loads(json.dumps(good))
    duplicate_edge["edges"].append(json.loads(json.dumps(good["edges"][0])))

    bad_spacing = json.loads(json.dumps(good))
    bad_spacing["keyframe_spacing_m"] = -1.0

    truncated_keyframe = json.loads(json.dumps(good))
    del truncated_keyframe["keyframes"][1]["y"]

    return [
        ("schema", bad_schema, ValueError),
        ("missing-keyframes", missing_keyframes, TypeError),
        ("dangling-edge", dangling_edge, ValueError),
        ("duplicate-edge", duplicate_edge, ValueError),
        ("bad-spacing", bad_spacing, ValueError),
        ("truncated-keyframe", truncated_keyframe, KeyError),
    ]


def test_load_refuses_corrupt_files_without_partially_loading(tmp_path: Path) -> None:
    """SEEDED FAILURE for persistence: six corruptions, six refusals, zero damage.

    Each case is seeded by mutating a known-good payload in exactly one way.
    After every refusal the live graph must be bit-identical to what it was —
    a half-ingested place graph would route confidently over edges whose
    endpoints were never read.
    """

    donor = u_corridor_graph()
    good = json.loads(donor.save(tmp_path / "good.json").read_text(encoding="utf-8"))

    live = u_corridor_graph()
    baseline_bytes = live.save(tmp_path / "live_before.json").read_bytes()
    baseline_keyframes = live.keyframes
    baseline_edges = live.edges

    for name, payload, expected in _corruptions(good):
        target = tmp_path / f"corrupt_{name}.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(expected):
            live.load(target)
        assert live.keyframes == baseline_keyframes, f"{name}: keyframes mutated by a refused load"
        assert live.edges == baseline_edges, f"{name}: edges mutated by a refused load"
        assert live.save(tmp_path / f"live_after_{name}.json").read_bytes() == baseline_bytes

    # Not JSON at all.
    garbled = tmp_path / "garbled.json"
    garbled.write_text('{"schema_version": "parcel.route_mem', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        live.load(garbled)
    assert live.keyframes == baseline_keyframes

    with pytest.raises(FileNotFoundError):
        live.load(tmp_path / "nope.json")
    assert live.keyframes == baseline_keyframes

    # ...and the good file still loads, so the refusals above are not a
    # loader that simply rejects everything.
    assert RoutePlaceGraph().load(tmp_path / "good.json").keyframes == donor.keyframes


def test_save_creates_missing_parent_directories(tmp_path: Path) -> None:
    graph = RoutePlaceGraph()
    walk(graph, [((0.0, 0.0), (1.0, 0.0))])
    out = graph.save(tmp_path / "nested" / "deeper" / "g.json")
    assert out.is_file()


# ---------------------------------------------------------------------------
# GATE: determinism
# ---------------------------------------------------------------------------


def test_same_visits_give_the_same_graph_and_the_same_route(tmp_path: Path) -> None:
    a = u_corridor_graph()
    b = u_corridor_graph()

    assert a.as_dict() == b.as_dict()
    assert a.save(tmp_path / "a.json").read_bytes() == b.save(tmp_path / "b.json").read_bytes()
    assert a.keyframes == b.keyframes
    assert a.edges == b.edges

    route_a = a.waypoints_toward((0.0, 10.0), (0.0, 0.0))
    route_b = b.waypoints_toward((0.0, 10.0), (0.0, 0.0))
    assert route_a == route_b
    # Repeated queries on one graph are stable too (no iteration-order leak).
    for _ in range(5):
        assert a.waypoints_toward((0.0, 10.0), (0.0, 0.0)) == route_a


def test_seeded_determinism_check_has_discriminating_power(tmp_path: Path) -> None:
    """SEEDED FAILURE for determinism: a DIFFERENT history must serialise differently.

    Without this, ``a.as_dict() == b.as_dict()`` could be passing because the
    comparison is blind rather than because the graph is deterministic.
    """

    a = u_corridor_graph()
    reversed_walk = RoutePlaceGraph()
    walk(
        reversed_walk,
        [((0.0, 10.0), (10.0, 10.0)), ((10.0, 10.0), (10.0, 0.0)), ((10.0, 0.0), (0.0, 0.0))],
    )

    assert a.as_dict() != reversed_walk.as_dict()
    assert (
        a.save(tmp_path / "a.json").read_bytes()
        != reversed_walk.save(tmp_path / "r.json").read_bytes()
    )
    # Same walked ground, so the route between the same two points is the same
    # LENGTH even though the node ordering differs — the graph is deterministic,
    # not merely order-insensitive.
    forward = a.waypoints_toward((0.0, 10.0), (0.0, 0.0))
    backward = reversed_walk.waypoints_toward((0.0, 10.0), (0.0, 0.0))
    assert chain_length_m(forward) == pytest.approx(chain_length_m(backward))


def test_equal_cost_ties_break_deterministically() -> None:
    """A square loop offers two equal-length routes; the same one comes back."""

    graph = RoutePlaceGraph()
    walk(
        graph,
        [
            ((0.0, 0.0), (4.0, 0.0)),
            ((4.0, 0.0), (4.0, 4.0)),
            ((4.0, 4.0), (0.0, 4.0)),
            ((0.0, 4.0), (0.0, 0.0)),
        ],
    )
    first = graph.waypoints_toward((4.0, 4.0), (0.0, 0.0))
    assert_chain_uses_only_recorded_edges(graph, first)
    for _ in range(10):
        assert graph.waypoints_toward((4.0, 4.0), (0.0, 0.0)) == first


# ---------------------------------------------------------------------------
# GATE: embedding seam, no onnx in the pure module
# ---------------------------------------------------------------------------


def test_place_graph_imports_no_onnx_torch_or_navigation() -> None:
    """The pure module stays pure: the onnx import belongs at the injection site."""

    source = Path(place_graph_module.__file__).read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    for forbidden in ("onnx", "onnxruntime", "torch", "numpy", "siglip"):
        assert not any(forbidden in name for name in imported), (
            f"place_graph imports {forbidden!r}: {imported}"
        )
    forbidden_packages = (
        "parcel_robot.navigation",
        "parcel_robot.runtime",
        "parcel_robot.instructnav",
    )
    for forbidden in forbidden_packages:
        assert not any(name.startswith(forbidden) for name in imported), (
            f"place_graph imports {forbidden!r}: {imported}"
        )
    assert "parcel_robot.pose" in imported, "the pose seam is the point"


def test_embed_fn_seam_takes_one_image_like_embed_image() -> None:
    seen: list[Any] = []

    def fake_embed_image(image: Any) -> tuple[float, ...]:
        seen.append(image)
        return (0.25, 0.5, 0.75)

    graph = RoutePlaceGraph(embed_fn=fake_embed_image)
    kf = graph.record_visit(map_pose(0.0, 0.0), view_image=b"rgb-bytes")
    assert kf is not None
    assert kf.embedding == (0.25, 0.5, 0.75)
    assert seen == [b"rgb-bytes"]

    # An explicit embedding wins and the seam is not called again.
    kf2 = graph.record_visit(map_pose(1.0, 0.0), view_embedding=[1.0, 0.0], view_image=b"ignored")
    assert kf2 is not None
    assert kf2.embedding == (1.0, 0.0)
    assert seen == [b"rgb-bytes"]

    # No image, no embedding: the seam is never called speculatively.
    kf3 = graph.record_visit(map_pose(2.0, 0.0))
    assert kf3 is not None
    assert kf3.embedding == ()


def test_default_stub_embedder_is_deterministic_and_normalized() -> None:
    a = stub_embed_image(b"frame-1")
    b = stub_embed_image(b"frame-1")
    c = stub_embed_image(b"frame-2")
    assert a == b
    assert a != c
    assert math.isclose(math.sqrt(sum(v * v for v in a)), 1.0, rel_tol=1e-9)

    graph = RoutePlaceGraph()  # default embed_fn
    kf = graph.record_visit(map_pose(0.0, 0.0), view_image=b"frame-1")
    assert kf is not None
    assert kf.embedding == a


# ---------------------------------------------------------------------------
# edge type + honesty surface
# ---------------------------------------------------------------------------


def test_place_edge_validation() -> None:
    with pytest.raises(ValueError, match="a < b"):
        PlaceEdge(a=3, b=1, length_m=1.0)
    with pytest.raises(ValueError, match="a < b"):
        PlaceEdge(a=2, b=2, length_m=1.0)
    with pytest.raises(ValueError, match="traversals"):
        PlaceEdge(a=0, b=1, length_m=1.0, traversals=0)
    with pytest.raises(ValueError, match="length_m"):
        PlaceEdge(a=0, b=1, length_m=-1.0)
    with pytest.raises(TypeError, match="crossed_reanchor"):
        PlaceEdge.from_mapping({"a": 0, "b": 1, "length_m": 1.0, "crossed_reanchor": 1})
    with pytest.raises(ValueError, match="missing required key"):
        PlaceEdge.from_mapping({"a": 0, "b": 1})

    edge = PlaceEdge(a=0, b=1, length_m=1.0, crossed_reanchor=True)
    assert edge.routable is False
    assert PlaceEdge.from_mapping(edge.as_dict()) == edge


def test_stats_and_does_not_prove() -> None:
    graph = u_corridor_graph()
    stats = graph.stats()
    assert stats["frame"] == "map"
    assert stats["schema_version"] == PLACE_GRAPH_SCHEMA
    assert stats["keyframes"] == len(graph)
    assert stats["routable_edges"] == len(graph.edges)
    assert stats["reanchor_edges"] == 0
    assert stats["does_not_prove"]
    assert any("does not prove SLAM" in s for s in place_graph_module.DOES_NOT_PROVE)
