"""Eval integrity for the v4 re-freeze (one correction: the follow goal radius).

The same properties ``test_nav_instruct_episodes_v3.py`` pins for v3, plus the
one this re-freeze adds because it is the first one driven by a change in the
*authority* rather than in the eval or in a K0 builder:

1. **v1, v2 and v3 did not move.** A re-freeze that moves a superseded set makes
   every row ever measured against it mean something else.
2. **Regeneration diff.** The checked-in v4 files must equal a fresh generation.
3. **The correction is a DERIVATION, and the derivation is still true.** The
   frozen 2.13 m must equal what the live authority + the live ``FollowConfig``
   compute today. This is the test that fires the *next* time somebody retunes
   person clearance: it names the cause and demands a re-freeze, instead of
   letting the region go stale and surface three lanes later as a false arrival
   (which is exactly what happened to v3 — see
   ``scrum/20260809/task_15/E7_FALSE_ARRIVAL_STATUS.md``).
4. **The correction does what it says, and only that.** Only ``follow_owner``
   goals move, they move only in ``radius_m`` (plus the ``shortest_path_m`` that
   is *computed* from it), and ``circle_owner`` is untouched.
5. **The region actually admits the controller.** A compliant hold is inside the
   v4 disc and was outside the v3 one — stated as geometry, not as a run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.nav_instruct.bridge_v3_v4 import (
    RECORDED_OLD_CODE_CELLS,
    derivation_check,
    spec_bridge,
    verify_recorded_baseline_cell,
)
from evals.nav_instruct.generator import (
    CIRCLE_OWNER_GOAL_RADIUS_M,
    EPISODE_SET_V1,
    EPISODE_SET_V2,
    EPISODE_SET_V3,
    EPISODE_SET_V4,
    FOLLOW_DISTANCE_DEADBAND_M,
    FOLLOW_HOLD_BAND_OUTER_M,
    FOLLOW_OWNER_COLLISION_ENVELOPE_M,
    FOLLOW_OWNER_GOAL_RADIUS_M,
    FOLLOW_STAND_OFF_M,
    OWNER_KEEPOUT_M,
    OWNER_STAND_OFF_MARGIN_M,
    episode_set_spec,
    generate_minival,
    landmarks_for,
    matrix_digest,
    write_episode_files,
)
from evals.nav_instruct.runner import ARRIVAL_RULE_FOR_VERSION, DERIVED_ARRIVAL_RULE
from parcel_robot.instructnav.scoring import ARRIVAL_BOUNDARY_EPSILON_M
from parcel_robot.navigation.follow import FollowConfig
from parcel_robot.navigation.reactive_safety import (
    OWNER_STAND_OFF_MARGIN_M as RUNTIME_OWNER_STAND_OFF_MARGIN_M,
)
from parcel_robot.navigation.spatial import SpatialBehaviorConfig

REPO = Path(__file__).resolve().parents[1]
EPISODES_DIR = REPO / "evals" / "nav_instruct" / "episodes"
LEDGER = REPO / "evals" / "nav_instruct" / "results" / "ledger.jsonl"
BRIDGE = REPO / "evals" / "nav_instruct" / "results" / "bridge_v3_v4.json"

FROZEN_V1_DIGEST = "cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf"
FROZEN_V2_DIGEST = "a17c04dbec43a1749386c304060fb479a71f27d4b51b8c1b0fbb949753fc563d"
FROZEN_V3_DIGEST = "919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa"
FROZEN_V4_DIGEST = "4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222"

#: The radius the v4 set was frozen under, as a literal. The derivation below is
#: what SHOULD produce it; this is what it DID produce on 2026-08-11. Two
#: independent statements, so a silent authority move cannot satisfy both.
FROZEN_V4_FOLLOW_RADIUS_M = 2.1300000000000003
FROZEN_V3_FOLLOW_RADIUS_M = 1.8

FOLLOW_IDS = (
    "nav-follow_owner-A-00-40672702",
    "nav-follow_owner-B-05-334e8d3f",
    "nav-follow_owner-C-10-41c8032b",
    "nav-follow_owner-D-15-74a535dd",
    "nav-follow_owner-E-20-433c9247",
)

#: Owner distances the three false arrivals actually terminated at (E7's
#: measurement, reproduced by this lane). They are what the resize has to admit,
#: and they are also why 2.13 is demonstrably NOT the smallest number that
#: would have made them pass.
MEASURED_FALSE_ARRIVAL_OWNER_DISTANCES_M = (2.0070, 2.0190, 2.0282)


def _by_id(version: str) -> dict:
    return {ep.episode_id: ep for ep in generate_minival(version=version)}


# --------------------------------------------------------------------------
# 1. the superseded sets did not move
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "digest", "radius"),
    [
        (EPISODE_SET_V1, FROZEN_V1_DIGEST, FROZEN_V3_FOLLOW_RADIUS_M),
        (EPISODE_SET_V2, FROZEN_V2_DIGEST, FROZEN_V3_FOLLOW_RADIUS_M),
        (EPISODE_SET_V3, FROZEN_V3_DIGEST, FROZEN_V3_FOLLOW_RADIUS_M),
    ],
)
def test_the_radius_change_did_not_move_a_frozen_digest(
    version: str, digest: str, radius: float
) -> None:
    """v1/v2/v3 keep the 1.8 m literal they were frozen under.

    They are historical pins: every ledger row measured against them was scored
    by a 1.8 m disc, and re-deriving their radius from today's authority would
    silently restate what those rows mean.
    """

    episodes = generate_minival(version=version)
    assert matrix_digest(episodes) == digest
    for episode in episodes:
        if episode.family == "follow_owner":
            assert episode.goal.radius_m == radius


def test_v1_is_still_the_default_and_v4_must_be_asked_for_by_name() -> None:
    assert matrix_digest(generate_minival()) == FROZEN_V1_DIGEST
    assert episode_set_spec().version == EPISODE_SET_V1
    for version in (EPISODE_SET_V1, EPISODE_SET_V2, EPISODE_SET_V3):
        assert episode_set_spec(version).follow_goal_radius_reference == "frozen_literal"
    assert (
        episode_set_spec(EPISODE_SET_V4).follow_goal_radius_reference
        == "follow_hold_band"
    )


# --------------------------------------------------------------------------
# 2. regeneration diff over the checked-in v4 files
# --------------------------------------------------------------------------


def test_checked_in_v4_files_equal_a_fresh_generation(tmp_path: Path) -> None:
    episodes = generate_minival(version=EPISODE_SET_V4)
    assert matrix_digest(episodes) == FROZEN_V4_DIGEST
    write_episode_files(episodes, tmp_path, version=EPISODE_SET_V4, seed=20260804)
    checked_in = EPISODES_DIR / EPISODE_SET_V4
    fresh_names = sorted(p.name for p in tmp_path.iterdir())
    stored_names = sorted(p.name for p in checked_in.iterdir())
    assert fresh_names == stored_names
    for name in fresh_names:
        assert (tmp_path / name).read_bytes() == (checked_in / name).read_bytes(), (
            f"v4/{name} differs from a fresh generation — either it was "
            "hand-edited or the generator changed without regenerating"
        )


def test_v4_manifest_records_the_correction_it_carries() -> None:
    manifest = json.loads((EPISODES_DIR / EPISODE_SET_V4 / "manifest.json").read_text())
    assert manifest["sha256"] == FROZEN_V4_DIGEST
    assert manifest["episode_set_version"] == EPISODE_SET_V4
    # (a), (b) and (d) are carried unchanged from v3 — the re-freeze adds (e) and
    # nothing else, and the manifest has to say so.
    assert manifest["landmark_section"] == "derived"
    assert manifest["word_boundary_class_match"] is True
    assert manifest["visible_instance_anchoring"] is True
    assert "follow_owner goal radius" in manifest["provenance"]
    assert "owner-authorized 2026-08-11" in manifest["provenance"]


def test_episode_ids_are_identical_across_every_version() -> None:
    """The old→new mapping must stay total: a dropped id orphans a frozen row."""

    ids = {
        version: set(_by_id(version))
        for version in (
            EPISODE_SET_V1,
            EPISODE_SET_V2,
            EPISODE_SET_V3,
            EPISODE_SET_V4,
        )
    }
    assert len(set(map(frozenset, ids.values()))) == 1


def test_v4_landmark_table_is_v3s_so_the_radius_is_the_only_thing_that_moved() -> None:
    spec = episode_set_spec(EPISODE_SET_V4)
    assert spec.landmark_section == "derived"
    assert spec.next_to_band_reference == "surface"
    assert landmarks_for(spec) == landmarks_for(episode_set_spec(EPISODE_SET_V3))


# --------------------------------------------------------------------------
# 3. the correction is a DERIVATION, and it is still true
# --------------------------------------------------------------------------


def test_the_v4_radius_is_derived_from_the_authority_not_typed() -> None:
    """Every term re-read from the object the controller obeys.

    A red here means an authority term moved under the frozen set. The fix is a
    re-freeze with authorization, NOT editing this number: the checked-in v4
    files are the artifact, and they say 2.13.
    """

    check = derivation_check()
    assert check["owner_keepout_m"] == OWNER_KEEPOUT_M
    assert check["stand_off_m"] == FOLLOW_STAND_OFF_M
    assert check["hold_band_outer_m"] == FOLLOW_HOLD_BAND_OUTER_M
    assert check["goal_radius_m"] == FOLLOW_OWNER_GOAL_RADIUS_M
    assert check["matches_frozen_v4_radius"] is True
    assert check["stand_off_matches_follow_config"] is True
    assert FOLLOW_OWNER_GOAL_RADIUS_M == FROZEN_V4_FOLLOW_RADIUS_M


def test_the_generators_restated_terms_still_equal_the_live_controllers() -> None:
    """The sim-free copies cannot drift from the runtime they describe.

    ``generator.py`` is deliberately sim-free, so it restates two of the follow
    controller's terms rather than importing ``navigation.follow``. That is the
    same convention ``VISIBILITY_MAX_RANGE_M`` uses, and it is only safe with
    this test.
    """

    config = FollowConfig()
    assert FOLLOW_OWNER_COLLISION_ENVELOPE_M == config.owner_collision_envelope_m
    assert FOLLOW_DISTANCE_DEADBAND_M == config.distance_deadband_m
    assert OWNER_STAND_OFF_MARGIN_M == RUNTIME_OWNER_STAND_OFF_MARGIN_M
    assert OWNER_KEEPOUT_M == config.owner_keepout_m
    assert FOLLOW_STAND_OFF_M == config.desired_distance_m


def test_the_v4_disc_admits_every_compliant_hold_and_the_v3_disc_did_not() -> None:
    """The defect and its remedy, as geometry rather than as a run.

    ``FollowOwnerController.step`` holds when
    ``distance - desired_distance_m <= distance_deadband_m``, so the outer edge
    of the hold band is the farthest owner distance a compliant controller may
    claim ``at_follow_distance`` from. v3's disc excluded it — by more than the
    boundary epsilon, which is why the verdict was ``false_arrival`` and not
    ``tolerated_boundary``. v4's admits it with the authority's own margin to
    spare.
    """

    config = FollowConfig()
    hold_outer = config.desired_distance_m + config.distance_deadband_m
    assert hold_outer == FOLLOW_HOLD_BAND_OUTER_M

    # v3: unsatisfiable. Even the SMALLEST hold distance is outside the disc, so
    # no control improvement reaches it.
    assert config.desired_distance_m > FROZEN_V3_FOLLOW_RADIUS_M
    assert hold_outer > FROZEN_V3_FOLLOW_RADIUS_M + ARRIVAL_BOUNDARY_EPSILON_M

    # v4: the whole band is admitted, with the stand-off margin as headroom.
    assert hold_outer <= FOLLOW_OWNER_GOAL_RADIUS_M
    assert FOLLOW_OWNER_GOAL_RADIUS_M - hold_outer == pytest.approx(
        OWNER_STAND_OFF_MARGIN_M
    )
    for distance in MEASURED_FALSE_ARRIVAL_OWNER_DISTANCES_M:
        assert distance > FROZEN_V3_FOLLOW_RADIUS_M + ARRIVAL_BOUNDARY_EPSILON_M
        assert distance < FOLLOW_OWNER_GOAL_RADIUS_M


def test_the_radius_was_not_fitted_to_the_failing_episodes() -> None:
    """2.13 is not the smallest number that would have turned the tests green.

    If it were, "derived" would be a story told about a fitted constant. The
    smallest radius that passes all three measured false arrivals is 2.0282; the
    derivation lands 0.10 m past it, and past it by exactly the wrap margin
    applied to the band edge rather than to any measured pose.
    """

    smallest_passing = max(MEASURED_FALSE_ARRIVAL_OWNER_DISTANCES_M)
    assert FOLLOW_OWNER_GOAL_RADIUS_M > smallest_passing
    # ...and the derivation never reads a measured pose: it is a function of the
    # band edge alone.
    assert FOLLOW_OWNER_GOAL_RADIUS_M == (
        FOLLOW_HOLD_BAND_OUTER_M + OWNER_STAND_OFF_MARGIN_M
    )


# --------------------------------------------------------------------------
# 4. the correction does what it says, and only that
# --------------------------------------------------------------------------


def test_only_follow_owner_goals_moved_and_only_in_the_radius() -> None:
    v3, v4 = _by_id(EPISODE_SET_V3), _by_id(EPISODE_SET_V4)
    moved, unchanged = [], []
    for episode_id, before in v3.items():
        after = v4[episode_id]
        if before.as_dict() == after.as_dict():
            unchanged.append(episode_id)
            continue
        moved.append(episode_id)
        assert before.family == "follow_owner", episode_id
        # Inside the goal, ONLY the radius.
        before_goal, after_goal = before.goal.as_dict(), after.goal.as_dict()
        differing = {k for k in before_goal if before_goal[k] != after_goal[k]}
        assert differing == {"radius_m"}, (episode_id, differing)
        assert before_goal["radius_m"] == FROZEN_V3_FOLLOW_RADIUS_M
        assert after_goal["radius_m"] == FOLLOW_OWNER_GOAL_RADIUS_M
        # Everything about the episode except the goal and the path length
        # COMPUTED from the goal is untouched.
        assert after.instruction == before.instruction
        assert after.start_pose == before.start_pose
        assert after.target_entity_id == before.target_entity_id
        assert after.seed == before.seed
        assert after.placement_overrides == before.placement_overrides
        assert after.notes == before.notes
        assert after.tier == before.tier
        assert after.absent_target == before.absent_target
        assert after.distractors == before.distractors
        assert after.synonym == before.synonym
    assert sorted(moved) == sorted(FOLLOW_IDS), moved
    assert len(unchanged) == 20, len(unchanged)


def test_circle_owner_is_untouched_because_the_retune_never_reached_it() -> None:
    """Scope discipline, asserted rather than promised.

    The retuned stand-off invalidated the follow disc and not the orbit one: the
    widest orbit the config permits, plus its waypoint tolerance, is still
    inside 2.2 m, and no term feeding it moved under E5 or E6.
    """

    spatial = SpatialBehaviorConfig()
    widest_terminal_ring = spatial.max_orbit_radius_m + spatial.waypoint_tolerance_m
    nominal_terminal_ring = spatial.default_orbit_radius_m + spatial.waypoint_tolerance_m
    assert nominal_terminal_ring < widest_terminal_ring <= CIRCLE_OWNER_GOAL_RADIUS_M
    for version in (EPISODE_SET_V3, EPISODE_SET_V4):
        for episode in generate_minival(version=version):
            if episode.family == "circle_owner":
                assert episode.goal.radius_m == CIRCLE_OWNER_GOAL_RADIUS_M


def test_the_spec_bridge_says_only_follow_owner_moved() -> None:
    bridge = spec_bridge()
    assert bridge["id_mapping_is_total"]
    assert bridge["only_follow_owner_moved"]
    assert bridge["only_radius_and_derived_path_moved"]
    assert bridge["goal_fields_moved_anywhere"] == ["radius_m"]
    assert bridge["circle_owner_radius_unchanged"]
    assert bridge["counts_by_change"] == {"follow_goal_radius": 5, "unchanged": 20}
    assert bridge["digests"] == {
        EPISODE_SET_V3: FROZEN_V3_DIGEST,
        EPISODE_SET_V4: FROZEN_V4_DIGEST,
    }
    for row in bridge["changed_rows"]:
        # ``shortest_path_m`` is COMPUTED from the goal, so it moves on four of
        # the five; D-15 already started inside the smaller disc, so its path was
        # 0.0 and stays 0.0. No other field name may appear here.
        assert row["fields_changed"][0] == "goal"
        assert set(row["fields_changed"]) <= {"goal", "shortest_path_m"}
        assert row["instruction_unchanged"]
        assert row["start_pose_unchanged"]
        assert row["seed_unchanged"]
        assert row["target_unchanged"]
        assert row["placement_unchanged"]
        assert row["notes_unchanged"]


# --------------------------------------------------------------------------
# 5. ledger + bridge artifacts
# --------------------------------------------------------------------------


def test_the_v4_ledger_rows_declare_their_version_and_rule() -> None:
    rows = [
        json.loads(line)
        for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    v4_rows = [row for row in rows if row.get("baseline_version") == EPISODE_SET_V4]
    assert v4_rows, "expected at least the v4 frozen-baseline row"
    for row in v4_rows:
        assert row["episode_digest"] == FROZEN_V4_DIGEST
        # v4 changes the follow radius and nothing else — in particular not the
        # arrival rule, so a v3 -> v4 delta cannot contain a rule change.
        assert row["arrival_rule"] == DERIVED_ARRIVAL_RULE
        assert ARRIVAL_RULE_FOR_VERSION[EPISODE_SET_V4] == DERIVED_ARRIVAL_RULE
    frozen = [row for row in v4_rows if row.get("frozen_baseline")]
    assert len(frozen) == 1, "exactly one v4 frozen baseline"
    assert frozen[-1]["authority_histogram"]["false_arrival"] == 0
    assert frozen[-1]["collision_total"] == 0


def test_the_recorded_old_code_cell_still_matches_the_committed_frozen_row() -> None:
    """The load-bearing half of the 2x2 is falsifiable from this tree.

    ``(old episodes × old code)`` was measured on a detached worktree this
    process cannot reach, so it is recorded. Recorded is not trusted: it is
    compared against the committed frozen-baseline ledger row on every pinned
    quantity, so a mistyped number is a red test rather than a claim.
    """

    verify = verify_recorded_baseline_cell(LEDGER)
    assert verify["row_found"], verify
    assert verify["row_budget_policy"] == RECORDED_OLD_CODE_CELLS["provenance"][
        "budget_policy"
    ]
    assert verify["mismatches"] == {}
    assert verify["reproduces_historical_baseline"] is True


def test_the_bridge_artifact_carries_the_derivation_and_the_2x2_signature() -> None:
    """The bridge must show the resize is the whole delta, and prove it."""

    payload = json.loads(BRIDGE.read_text(encoding="utf-8"))
    assert payload["from_version"] == EPISODE_SET_V3
    assert payload["to_version"] == EPISODE_SET_V4
    assert set(payload["corrections"]) == {"e"}
    assert payload["follow_goal_radius_reference"] == {
        EPISODE_SET_V3: "frozen_literal",
        EPISODE_SET_V4: "follow_hold_band",
    }
    assert payload["derivation_check"]["goal_radius_m"] == FROZEN_V4_FOLLOW_RADIUS_M
    assert payload["recorded_baseline_cell_check"]["reproduces_historical_baseline"]

    measured = payload["measured_bridge"]
    signature = measured["signature"]
    # THE required signature: false arrivals live in exactly one cell.
    assert signature["false_arrival"] == {
        "old_episodes_x_old_code": 0,
        "old_episodes_x_new_code": 3,
        "new_episodes_x_old_code": 0,
        "new_episodes_x_new_code": 0,
    }
    assert signature["holds"] is True

    # The resize reaches only follow_owner, under BOTH code arms...
    assert measured["episode_axis"]["only_follow_owner_on_both_code_arms"] is True
    # ...and what E1-E6 moved is identical under both episode sets, which is what
    # proves the wider region is not hiding any of it.
    assert measured["code_axis"]["identical_outside_follow_owner"] is True
    assert measured["code_axis"]["non_follow_owner_under_v3"] == [
        "nav-object_goal-B-05-0ee314d5",
        "nav-object_goal-D-15-109547e2",
        "nav-object_relative-D-15-61f68ad6",
        "nav-region_goal-D-15-1b8b2361",
    ]

    delta = measured["deltas"]["e_follow_goal_radius"]
    assert delta["every_moved_episode_is_follow_owner"] is True
    assert delta["false_arrivals_after"] == []
    assert delta["episodes_lost"] == []
    assert delta["collisions_before"] == delta["collisions_after"] == 0
    # The strongest single fact in the bridge: the ROBOT's own arrival claim is
    # byte-identical across v3 and v4. Only K0's verdict on it moved, which is
    # what "the eval region went stale, not the robot" means when measured.
    assert delta["system_arrival_moved"] == []
