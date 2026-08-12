"""Card VS-6 — the additive v4s search tier, the phantom mutant, and the gate.

Four things are pinned here, and they are deliberately in one file because they
are one claim: *the frozen matrix did not move, and something new exists that
can actually exercise a search.*

1. **Nothing frozen moved.** All four ``DIGEST_SENTINELS`` are byte-identical to
   their pins (the v4 manifest ``b2945444…`` among them) and the E8
   minival-report digest ``4113607b…`` still reproduces from the generator. Both
   are asserted here, not read out of a status doc — adjudication #18 exists
   because the wrong one of those two hashes was once pinned as the other.
2. **The v4s cells are what they claim to be.** Every episode's target is beyond
   the world frustum's RANGE and outside the start frustum, so no opening
   full-turn scan at the start pose can see it; the axis a cell sits on is a
   statement about its straight corridor; and a route into the SCORED goal
   region exists on the generator's grid. All three are re-derived per episode
   here, never taken from the recorded evidence dict.
3. **The mutation panel grew by exactly one row.** ``phantom_view_consistent``
   is registered, killed, and kills through the differential-authority
   ``no_false_arrival`` channel; the six pre-existing mutants keep their
   verdicts.
4. **The phantom gate cannot pass vacuously** (adjudication #19). The gate VS-4
   will run is implemented here as a pure function over trace-derived outcomes,
   and each of its three conjuncts is shown failing on a seeded violation —
   including the one that matters most, an EMPTY arm, which is the V-D lesson:
   "no phantom arrivals" is also what "nothing happened" looks like.

``does_not_prove``: the v4s cells are not run here. What a flag-on arm does with
them is VS-4's and VS-5's measurement; this file pins the substrate.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from evals.nav_instruct.generator import (
    DEFAULT_OWNER_XY,
    EPISODE_SET_V4,
    EPISODE_SET_V4S,
    OWNER_CORRIDOR_KEEPOUT_M,
    V4S_AXIS_BEYOND_BLOCK,
    V4S_AXIS_LOOK_AROUND,
    V4S_AXIS_PHANTOM,
    V4S_EPISODES_PER_AXIS,
    V4S_OWNER_DISC_ID,
    V4S_SEARCH_AXES,
    V4S_SEED,
    V4S_VIEW_SEPARATION_RAD,
    VISIBILITY_MAX_RANGE_M,
    EpisodeSpec,
    _v4s_blocking_discs,
    _v4s_route_length_m,
    _v4s_segment_blockers,
    episode_set_spec,
    generate_episode_matrix,
    generate_minival,
    generate_v4s_matrix,
    landmarks_for,
    matrix_digest,
    visible_from_start,
    write_episode_files,
)
from parcel_robot.instructnav.scan import full_turn_scan_spec
from parcel_robot.instructnav.scoring import (
    ApproachVerifyState,
    GoalRegion,
    object_near_envelope_m,
    object_near_goal_region,
)

#: The states that mean "this session committed to a hypothesis and is acting on
#: it". Read from the scorer's own approach/verify enum, which VS-1's landed
#: ``LockOnVerifySession`` already reports — the gate invents no vocabulary.
COMMITTED_STATES = (
    ApproachVerifyState.APPROACH,
    ApproachVerifyState.VERIFY,
    ApproachVerifyState.VERIFIED,
)

REPO = Path(__file__).resolve().parents[1]
EPISODES_DIR = REPO / "evals" / "nav_instruct" / "episodes"
PANEL_JSON = REPO / "evals" / "nav_instruct" / "results" / "mutation_panel.json"

#: The v4 episode-set manifest hash, i.e. the ``DIGEST_SENTINELS`` entry. NOT the
#: minival digest below — that confusion is adjudication #18.
FROZEN_V4_MANIFEST_SHA256 = (
    "b29454443e93b68d238c11d31298e81c2e9cae89d7669d9d6556405e9b7388ec"
)
#: The E8 minival-report digest: ``matrix_digest`` over the 25-episode v4
#: minival, the number every v4 report and ledger row carries as
#: ``episode_digest``. Kept as a second invariant.
FROZEN_V4_MINIVAL_DIGEST = (
    "4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222"
)
#: The v4s manifest digest as generated and checked in by this card. v4s is NOT
#: frozen this cycle (no sentinel, ``--freeze`` refuses it); this pin exists so
#: an accidental regeneration is a red test rather than a silent new set.
V4S_MATRIX_DIGEST = (
    "0f19350d29887d5fcd3905a4683ed88725eba259396320bcf8021a850bfc2811"
)

#: The card's floor. ``V4S_EPISODES_PER_AXIS`` is what generation actually aims
#: for; this is the number below which the tier stops being a measurement.
MIN_EPISODES_PER_AXIS = 20


def _bits(value: float) -> bytes:
    return struct.pack("<d", float(value))


@pytest.fixture(scope="module")
def v4s_episodes() -> tuple[EpisodeSpec, ...]:
    return generate_v4s_matrix()


# ---------------------------------------------------------------------------
# 1. nothing frozen moved
# ---------------------------------------------------------------------------


def test_all_four_digest_sentinels_are_byte_identical_to_their_pins() -> None:
    """The gate's own sentinel evaluation, run here so the claim is measured."""

    from scripts.ci_gate import DIGEST_SENTINELS, evaluate_frozen_digest_sentinels

    result = evaluate_frozen_digest_sentinels(DIGEST_SENTINELS)
    assert result.status == "pass", result.detail
    assert result.extra["checked"] == 4
    assert (
        DIGEST_SENTINELS["evals/nav_instruct/episodes/v4/manifest.json"]
        == FROZEN_V4_MANIFEST_SHA256
    )


def test_v4_manifest_file_still_hashes_to_the_pin() -> None:
    path = EPISODES_DIR / EPISODE_SET_V4 / "manifest.json"
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest() == FROZEN_V4_MANIFEST_SHA256
    )


def test_v4_minival_report_digest_is_unmoved() -> None:
    """The second invariant: the number every v4 report carries."""

    assert (
        matrix_digest(generate_minival(version=EPISODE_SET_V4))
        == FROZEN_V4_MINIVAL_DIGEST
    )


def test_checked_in_v4_episode_files_still_equal_a_fresh_generation(
    tmp_path: Path,
) -> None:
    """v4s must not have moved a byte of v4 — proven file by file, not by hash."""

    write_episode_files(
        generate_minival(version=EPISODE_SET_V4),
        tmp_path,
        version=EPISODE_SET_V4,
        seed=20260804,
    )
    checked_in = EPISODES_DIR / EPISODE_SET_V4
    for path in sorted(tmp_path.iterdir()):
        assert path.read_bytes() == (checked_in / path.name).read_bytes(), (
            f"v4/{path.name} moved"
        )


def test_the_search_tier_is_not_a_frozen_baseline_name() -> None:
    """``v4s`` must not be picked up as "the newest frozen vN set"."""

    import re

    from evals.nav_instruct.generator import EPISODE_SETS

    plain = {v for v in EPISODE_SETS if re.fullmatch(r"v\d+", v)}
    assert EPISODE_SET_V4S not in plain
    assert max(plain, key=lambda v: int(v[1:])) == EPISODE_SET_V4


def test_frozen_matrix_entrypoint_refuses_the_search_tier() -> None:
    with pytest.raises(ValueError, match="additive search tier"):
        generate_episode_matrix(version=EPISODE_SET_V4S)


# ---------------------------------------------------------------------------
# 2. the v4s cells are what they claim to be
# ---------------------------------------------------------------------------


def test_v4s_has_at_least_the_pre_registered_episodes_per_axis(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    counts = {axis: sum(1 for ep in v4s_episodes if ep.tier == axis) for axis in V4S_SEARCH_AXES}
    assert set(counts) == set(V4S_SEARCH_AXES)
    for axis, count in counts.items():
        assert count >= MIN_EPISODES_PER_AXIS, f"axis {axis} below the card's floor"
        assert count == V4S_EPISODES_PER_AXIS
    assert len({ep.episode_id for ep in v4s_episodes}) == len(v4s_episodes)


def test_every_v4s_target_is_beyond_the_opening_scans_reach(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    """Both halves, re-derived: out of the start frustum AND out of range.

    Range is the load-bearing half. An in-place full turn sweeps every bearing,
    so a target inside :data:`VISIBILITY_MAX_RANGE_M` is found by the opening
    scan no matter where the robot is looking at t=0 — and a cell like that
    cannot measure a search rework (design record §2.1(2b)).
    """

    landmarks = landmarks_for(episode_set_spec(EPISODE_SET_V4S))
    for ep in v4s_episodes:
        entry = landmarks[str(ep.target_entity_id)]
        position = (float(entry["position"][0]), float(entry["position"][1]))
        range_m = math.hypot(
            position[0] - ep.start_pose[0], position[1] - ep.start_pose[1]
        )
        assert range_m > VISIBILITY_MAX_RANGE_M, ep.episode_id
        assert not visible_from_start(ep.start_pose, position), ep.episode_id


def test_every_v4s_episode_is_astar_routable_into_its_goal_region(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    """The card's generation-time routability assertion, re-run per episode.

    Re-derived rather than read from ``search_cell``: an evidence dict that
    asserts itself proves nothing. ``shortest_path_m`` must BE that route, since
    it is what SPL and the scaled step budget are computed from.
    """

    landmarks = landmarks_for(episode_set_spec(EPISODE_SET_V4S))
    discs = _v4s_blocking_discs(landmarks)
    for ep in v4s_episodes:
        route = _v4s_route_length_m(ep.start_pose[:2], ep.goal, discs)
        assert route is not None, f"{ep.episode_id} is not routable"
        assert route == pytest.approx(ep.shortest_path_m)
        assert ep.shortest_path_m > 0.0


def test_each_v4s_axis_means_what_it_says(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    """LA/PH: straight corridor clear. BB: it crosses a BUILDING.

    And on every axis the corridor clears the owner ring — "beyond the block"
    must mean a building is in the way, never that a person is standing there
    (which would measure the reactive gate, D-15).
    """

    landmarks = landmarks_for(episode_set_spec(EPISODE_SET_V4S))
    discs = _v4s_blocking_discs(landmarks)
    for ep in v4s_episodes:
        entry = landmarks[str(ep.target_entity_id)]
        position = (float(entry["position"][0]), float(entry["position"][1]))
        blockers = _v4s_segment_blockers(ep.start_pose[:2], position, discs)
        assert V4S_OWNER_DISC_ID not in blockers, ep.episode_id
        buildings = [
            item
            for item in blockers
            if landmarks[item].get("label") == "building"
        ]
        assert sorted(buildings) == sorted(blockers), ep.episode_id
        if ep.tier == V4S_AXIS_BEYOND_BLOCK:
            assert buildings, f"{ep.episode_id} claims beyond-the-block but is clear"
        else:
            assert not blockers, f"{ep.episode_id} claims a clear corridor but hits {blockers}"


def test_v4s_corridors_stay_outside_the_owner_ring(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    """The D-15 lesson, applied at generation: no cell dies on the owner.

    The default owner the headless world places in every nav_instruct episode is
    at :data:`DEFAULT_OWNER_XY`, which is also where the frozen ``follow_owner``
    and ``circle_owner`` goal discs are centred — pinned equal here so the two
    cannot drift apart.
    """

    frozen_owner_goal = [
        ep.goal.center
        for ep in generate_minival(version=EPISODE_SET_V4)
        if ep.family in {"follow_owner", "circle_owner"}
    ]
    assert frozen_owner_goal
    assert all(centre == DEFAULT_OWNER_XY for centre in frozen_owner_goal)

    for ep in v4s_episodes:
        distance = math.hypot(
            ep.start_pose[0] - DEFAULT_OWNER_XY[0],
            ep.start_pose[1] - DEFAULT_OWNER_XY[1],
        )
        assert distance > OWNER_CORRIDOR_KEEPOUT_M, ep.episode_id


def test_v4s_start_headings_are_opening_scan_stops(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    """The only heading offset v4s applies is 2π / the full turn's stop count.

    Bit-identical to the authority, by reference (E5/E6/E8 pattern): the same
    quantity §2.2(b) makes the view-admission rule, so a scan re-spec moves both
    together or neither.
    """

    assert _bits(V4S_VIEW_SEPARATION_RAD) == _bits(
        2.0 * math.pi / full_turn_scan_spec().n_stops
    )
    landmarks = landmarks_for(episode_set_spec(EPISODE_SET_V4S))
    for ep in v4s_episodes:
        entry = landmarks[str(ep.target_entity_id)]
        bearing = math.atan2(
            float(entry["position"][1]) - ep.start_pose[1],
            float(entry["position"][0]) - ep.start_pose[0],
        )
        error = abs(
            (ep.start_pose[2] - (bearing + math.pi) + math.pi) % (2.0 * math.pi)
            - math.pi
        )
        assert min(
            abs(error - offset * V4S_VIEW_SEPARATION_RAD) for offset in (0, 1)
        ) < 1e-9, ep.episode_id


def test_v4s_phantom_cells_carry_a_reachable_same_class_phantom(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    """The PH axis: a same-class detection with nothing behind it, on the way.

    Inside the opening scan's range while the real target is outside it — that
    asymmetry is the trap. Outside the scored goal region — so committing to it
    can never be a real arrival. Same label as the target — so the query
    matches it. And no MuJoCo geometry: ``apply_placement_overrides`` adds a
    perception spec only, which is what makes it a phantom rather than a
    distractor object.
    """

    landmarks = landmarks_for(episode_set_spec(EPISODE_SET_V4S))
    for ep in v4s_episodes:
        distractors = ep.placement_overrides.get("distractors") or {}
        if ep.tier != V4S_AXIS_PHANTOM:
            assert not distractors, f"{ep.episode_id} is not a phantom cell"
            continue
        assert len(distractors) == 1
        (phantom_id, spec), = distractors.items()
        assert tuple(ep.distractors) == (phantom_id,)
        entry = landmarks[str(ep.target_entity_id)]
        assert spec["label"] == entry["label"]
        assert spec["radius_m"] == pytest.approx(float(entry["radius_m"]))
        phantom = (float(spec["x"]), float(spec["y"]))
        assert not ep.goal.contains(
            phantom[0], phantom[1], anchor_xy=ep.goal.center
        ), f"{ep.episode_id}: phantom inside the real goal region"
        start_range = math.hypot(
            phantom[0] - ep.start_pose[0], phantom[1] - ep.start_pose[1]
        )
        assert start_range <= VISIBILITY_MAX_RANGE_M, ep.episode_id


def test_v4s_generation_is_deterministic() -> None:
    assert matrix_digest(generate_v4s_matrix()) == matrix_digest(generate_v4s_matrix())
    assert matrix_digest(generate_v4s_matrix()) == V4S_MATRIX_DIGEST


def test_checked_in_v4s_files_equal_a_fresh_generation(
    tmp_path: Path, v4s_episodes: tuple[EpisodeSpec, ...]
) -> None:
    write_episode_files(
        v4s_episodes, tmp_path, version=EPISODE_SET_V4S, seed=V4S_SEED
    )
    checked_in = EPISODES_DIR / EPISODE_SET_V4S
    fresh = sorted(path.name for path in tmp_path.iterdir())
    assert fresh == sorted(path.name for path in checked_in.iterdir())
    for name in fresh:
        assert (tmp_path / name).read_bytes() == (checked_in / name).read_bytes(), name
    manifest = json.loads((checked_in / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == V4S_MATRIX_DIGEST
    assert manifest["episode_set_version"] == EPISODE_SET_V4S
    assert manifest["search_axes"] == list(V4S_SEARCH_AXES)
    assert manifest["episodes_per_axis"] == {
        axis: V4S_EPISODES_PER_AXIS for axis in V4S_SEARCH_AXES
    }


def test_frozen_manifests_carry_no_search_axes_key() -> None:
    """The additive manifest fields must not have reached a frozen manifest."""

    for version in ("v1", "v2", "v3", "v4"):
        manifest = json.loads(
            (EPISODES_DIR / version / "manifest.json").read_text(encoding="utf-8")
        )
        assert "search_axes" not in manifest
        assert "episodes_per_axis" not in manifest


@pytest.mark.slow
def test_every_v4s_start_pose_is_collision_free_in_the_world(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    """Purity has a price: the generator is sim-free, so the world checks it here.

    ``truth_minimum_clearance`` is surface clearance from the robot's own
    footprint, so ``> 0`` is "the robot fits". Marked slow: it builds the MuJoCo
    world, which the pure tests above deliberately do not.
    """

    from parcel_robot.headless_city import HeadlessCityWorld

    world = HeadlessCityWorld()
    for start in {(ep.start_pose[0], ep.start_pose[1]) for ep in v4s_episodes}:
        assert world.truth_minimum_clearance(*start) > 0.0, start


# ---------------------------------------------------------------------------
# 3. the mutation panel grew by exactly one row
# ---------------------------------------------------------------------------

#: The six the panel shipped with, in order. Their verdicts may not move.
PRE_EXISTING_MUTANTS = (
    "arrival_radius_x2",
    "reactive_gate_disabled",
    "pose_offset_0m5",
    "inverted_relation",
    "dropped_detections",
    "doubled_envelope",
)
PHANTOM_MUTANT = "phantom_view_consistent"


def test_phantom_mutant_is_registered_last() -> None:
    from scripts.mutation_panel import MUTATIONS

    assert tuple(MUTATIONS) == PRE_EXISTING_MUTANTS + (PHANTOM_MUTANT,)


def test_committed_panel_gained_exactly_one_row_and_kills_through_false_arrival() -> None:
    payload = json.loads(PANEL_JSON.read_text(encoding="utf-8"))
    rows = payload["mutants"]
    assert tuple(row["mutation"] for row in rows) == PRE_EXISTING_MUTANTS + (
        PHANTOM_MUTANT,
    )
    for row in rows[: len(PRE_EXISTING_MUTANTS)]:
        assert row["verdict"] == "killed", row["mutation"]
    phantom = rows[-1]
    assert phantom["verdict"] == "killed"
    # The card's channel, named: differential authority, not a paired-geometry
    # check that any perturbation would trip.
    assert "no_false_arrival" in phantom["checks_reddened"]
    assert phantom["run"]["authority"].get("false_arrival", 0) >= 1
    assert payload["clean_checks"]["no_false_arrival"] is True
    assert payload["survivors"] == []


def test_phantom_reflection_moves_every_geometry_the_payload_carries() -> None:
    """A phantom whose goal_region still pointed at the real object is a no-op."""

    from scripts.mutation_panel import _reflected_phantom

    item = {
        "id": "tree_2",
        "label": "tree",
        "position": [4.0, 2.0, 0.0],
        "confidence": 0.98,
        "kind": "object",
        "metadata": {
            "radius_m": 0.58,
            "goal_region": {"kind": "disc", "center": [4.0, 2.0], "radius_m": 1.9},
        },
    }
    phantom = _reflected_phantom(item, (1.0, 1.0))
    assert phantom["id"] == "phantom-tree_2"
    assert phantom["confidence"] == 1.0
    assert phantom["position"][:2] == [-2.0, 0.0]
    assert phantom["metadata"]["goal_region"]["center"] == [-2.0, 0.0]
    # the source payload is untouched
    assert item["position"] == [4.0, 2.0, 0.0]
    assert item["confidence"] == 0.98


# ---------------------------------------------------------------------------
# 4. the phantom gate, and its non-vacuity conjuncts (adjudication #19)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhantomCellOutcome:
    """One v4s phantom episode, as VS-4's wiring will report it.

    The three telemetry fields are the CONTRACT this card hands to VS-4, and
    they are stated in the vocabulary that already exists rather than a new one:

    ``lock_on_states``
        ordered ``(session_id, ApproachVerifyState)`` pairs, i.e. the state each
        ``LockOnVerifySession.observe`` verdict reported, in tick order. That is
        the stratum-2 approach/verify enum in ``instructnav.scoring`` which
        VS-1's landed session already speaks. A COMMIT-then-REFUTATION is one
        session that entered a committed state (``APPROACH``/``VERIFY``/
        ``VERIFIED``) and LATER reported ``REJECTED`` — the verify-on-approach
        channel actually firing on a phantom it had already committed to.
    ``fp_memory_suppressions``
        how many ``NegativeEvidenceMemory.consult(...)`` answers came back with
        ``Suppression.suppressed`` true on a RE-encounter (VS-2's surface).
    ``system_arrival`` / ``final_xy`` / ``phantom_xy`` / ``phantom_vicinity_m``
        the navigator's own arrival claim, where it stopped, and the phantom's
        own vicinity envelope — see :func:`phantom_vicinity_m`.
    """

    episode_id: str
    phantom_xy: tuple[float, float]
    phantom_vicinity_m: float
    final_xy: tuple[float, float]
    system_arrival: bool
    lock_on_states: tuple[tuple[str, ApproachVerifyState], ...] = ()
    fp_memory_suppressions: int = 0


def phantom_goal_region(episode: EpisodeSpec) -> GoalRegion:
    """The region the phantom would generate, built by the world's own builder.

    Same call ``HeadlessCityWorld.apply_placement_overrides`` makes for a
    distractor, so the phantom's geometry is read in exactly the terms the robot
    was given it.
    """

    (entity_id, spec), = (episode.placement_overrides["distractors"]).items()
    return object_near_goal_region(
        (float(spec["x"]), float(spec["y"])),
        float(spec["radius_m"]),
        label=str(spec["label"]),
        entity_id=str(entity_id),
    )


def phantom_vicinity_m(episode: EpisodeSpec) -> float:
    """The radius inside which the robot counts as standing AT the phantom.

    ``object_near_envelope_m(...)[2]`` — the same ``vicinity_radius_m`` the world
    stamps into the distractor's own metadata, so this is the navigator's own
    notion of "at this object", not a threshold invented for the gate.

    Deliberately the vicinity and NOT the near-goal band. The band is an
    ANNULUS: it has an inner edge, because it describes where a compliant
    approach *stops*. A robot that drove closer than the inner edge and then
    claimed arrival has still arrived at the phantom — measured, and not
    hypothetical: on the flag-off control arm both phantom arrivals sit at
    0.452 and 1.222 m from the phantom, i.e. both INSIDE the band's 1.7 m inner
    edge. A band predicate would have scored that arm zero and made VS-4's first
    conjunct vacuous before it was ever run.
    """

    (spec,) = (episode.placement_overrides["distractors"]).values()
    return float(
        object_near_envelope_m(float(spec["radius_m"]), label=str(spec["label"]))[2]
    )


def phantom_cell_gate(
    outcomes: tuple[PhantomCellOutcome, ...],
) -> tuple[str, ...]:
    """VS-4 gate (4) over one arm's v4s phantom cells; ``()`` means PASS.

    Three conjuncts, and the last two are the non-vacuity ones (adjudication
    #19). "Zero phantom arrivals" is also what "the feature never engaged", "the
    episodes never ran" and "the phantom was never seen" look like — the V-D
    no-op lesson. So the gate additionally demands that the machinery be
    OBSERVED working: at least one commit-then-refutation, and at least one
    false-positive-memory suppression on re-encounter. An empty arm fails.
    """

    failures: list[str] = []
    for outcome in outcomes:
        if not outcome.system_arrival:
            continue
        if (
            math.dist(outcome.final_xy, outcome.phantom_xy)
            <= outcome.phantom_vicinity_m
        ):
            failures.append(f"phantom_arrival:{outcome.episode_id}")

    commit_then_refutation = 0
    for outcome in outcomes:
        by_session: dict[str, list[ApproachVerifyState]] = {}
        for session_id, state in outcome.lock_on_states:
            by_session.setdefault(session_id, []).append(ApproachVerifyState(state))
        for states in by_session.values():
            committed = [
                index for index, state in enumerate(states) if state in COMMITTED_STATES
            ]
            if not committed:
                continue
            if any(
                state is ApproachVerifyState.REJECTED
                for state in states[committed[0] + 1 :]
            ):
                commit_then_refutation += 1
    if commit_then_refutation < 1:
        failures.append("non_vacuity: no lock-on commit-then-refutation event")

    suppressions = sum(int(outcome.fp_memory_suppressions) for outcome in outcomes)
    if suppressions < 1:
        failures.append("non_vacuity: no FP-memory suppression on re-encounter")
    return tuple(failures)


_COMMIT_THEN_REFUTE: tuple[tuple[str, ApproachVerifyState], ...] = (
    ("s1", ApproachVerifyState.APPROACH),
    ("s1", ApproachVerifyState.REJECTED),
)


#: A tree-sized phantom, the commonest v4s case: vicinity 1.9 m.
_TREE_PHANTOM_VICINITY_M = object_near_envelope_m(0.58, label="tree")[2]


def _outcome(
    episode_id: str = "cell",
    *,
    final_xy: tuple[float, float] = (100.0, 100.0),
    system_arrival: bool = False,
    states: tuple[tuple[str, ApproachVerifyState], ...] = _COMMIT_THEN_REFUTE,
    suppressions: int = 1,
) -> PhantomCellOutcome:
    return PhantomCellOutcome(
        episode_id=episode_id,
        phantom_xy=(0.0, 0.0),
        phantom_vicinity_m=_TREE_PHANTOM_VICINITY_M,
        final_xy=final_xy,
        system_arrival=system_arrival,
        lock_on_states=states,
        fp_memory_suppressions=suppressions,
    )


def test_phantom_gate_passes_only_on_a_compliant_arm() -> None:
    assert phantom_cell_gate((_outcome(),)) == ()


def test_phantom_gate_fails_on_an_empty_arm() -> None:
    """The V-D lesson: nothing-happened must not read as success."""

    assert phantom_cell_gate(()) == (
        "non_vacuity: no lock-on commit-then-refutation event",
        "non_vacuity: no FP-memory suppression on re-encounter",
    )


def test_phantom_gate_fails_when_the_robot_arrives_at_the_phantom() -> None:
    """Seeded violation 1: a claimed arrival inside the phantom's vicinity.

    Both radii are seeded: one at the approach band the navigator aims for, and
    one INSIDE the band's inner edge, which is where both measured flag-off
    phantom arrivals actually landed.
    """

    for radius in (1.8, 0.452):
        failures = phantom_cell_gate(
            (
                _outcome(
                    "cell-7", final_xy=(radius, 0.0), system_arrival=True
                ),
            )
        )
        assert failures == ("phantom_arrival:cell-7",), radius
    # A claim far from the phantom is a false arrival somewhere else — a real
    # defect, but not THIS gate's, and it must not be counted as one.
    assert phantom_cell_gate(
        (_outcome("cell-8", final_xy=(6.0, 0.0), system_arrival=True),)
    ) == ()


def test_phantom_gate_fails_without_a_commit_then_refutation() -> None:
    """Seeded violation 2: the lock-on channel never engaged.

    A commit with no later refutation, and a refutation that precedes its own
    commit, must both fail — otherwise "the session did something" would pass
    for "the session rejected the phantom".
    """

    missing = "non_vacuity: no lock-on commit-then-refutation event"
    # committed, never refuted
    assert missing in phantom_cell_gate(
        (_outcome(states=(("s1", ApproachVerifyState.VERIFIED),)),)
    )
    # refuted before it ever committed — order is load-bearing
    assert missing in phantom_cell_gate(
        (
            _outcome(
                states=(
                    ("s1", ApproachVerifyState.REJECTED),
                    ("s1", ApproachVerifyState.APPROACH),
                )
            ),
        )
    )
    # one session committed and a DIFFERENT one refuted
    assert missing in phantom_cell_gate(
        (
            _outcome(
                states=(
                    ("s1", ApproachVerifyState.APPROACH),
                    ("s2", ApproachVerifyState.REJECTED),
                )
            ),
        )
    )


def test_phantom_gate_fails_without_an_fp_memory_suppression() -> None:
    """Seeded violation 3: nothing was ever remembered as refuted."""

    assert phantom_cell_gate((_outcome(suppressions=0),)) == (
        "non_vacuity: no FP-memory suppression on re-encounter",
    )


def test_phantom_goal_region_is_built_from_the_episodes_own_distractor(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    """The gate's region and the world's spec are the same call, per episode."""

    cells = [ep for ep in v4s_episodes if ep.tier == V4S_AXIS_PHANTOM]
    assert cells
    for ep in cells[:5]:
        region = phantom_goal_region(ep)
        (spec,) = (ep.placement_overrides["distractors"]).values()
        assert region.center == (float(spec["x"]), float(spec["y"]))
        assert not ep.goal.contains(
            float(spec["x"]), float(spec["y"]), anchor_xy=ep.goal.center
        )
        # The vicinity the gate uses is wider than the band's inner edge, which
        # is the whole reason it is the vicinity and not the band.
        assert region.band_m is not None
        assert phantom_vicinity_m(ep) >= float(region.band_m[0])


def test_look_around_and_beyond_block_cells_carry_no_phantom(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    for ep in v4s_episodes:
        if ep.tier in {V4S_AXIS_LOOK_AROUND, V4S_AXIS_BEYOND_BLOCK}:
            assert not ep.placement_overrides.get("distractors")


def test_v4s_episodes_record_their_own_evidence(
    v4s_episodes: tuple[EpisodeSpec, ...],
) -> None:
    """Every cell carries the three measurements its axis claim rests on.

    Recorded, not asserted-from: the tests above re-derive all three. This one
    only pins that a reader of one episode file can see them, and that the
    evidence dict cannot be mistaken for an entity pose override (it carries no
    ``x``/``y``, which is the key shape ``apply_placement_overrides`` acts on).
    """

    for ep in v4s_episodes:
        evidence: dict[str, Any] = ep.placement_overrides["search_cell"]
        assert evidence["axis"] == ep.tier
        assert evidence["target_entity_id"] == ep.target_entity_id
        assert evidence["start_target_range_m"] > VISIBILITY_MAX_RANGE_M
        assert evidence["route_length_m"] == pytest.approx(ep.shortest_path_m)
        assert evidence["routability"] == "astar_into_goal_region"
        assert "x" not in evidence and "y" not in evidence
