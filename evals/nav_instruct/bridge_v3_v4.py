"""v3 → v4 re-freeze bridge: ONE correction, isolated.

v4 carries exactly one change against v3 — correction **(e)**, the
``follow_owner`` goal disc re-derived from the follow controller's own hold band
instead of the bare literal ``1.8`` (owner-authorized 2026-08-11). Everything
else is v3 byte-for-byte: the same landmark table, the same word-boundary class
matching, the same visible-instance anchoring, the same surface-anchored
``next_to`` band, the same arrival rule, the same seed, the same 25 episode ids.

WHY THE RE-FREEZE EXISTS
------------------------
The owner-authorized person-clearance retune (lane E5, 2026-08-10) raised
``person_stop_m`` 1.0 -> 1.2, which raised ``owner_keepout_m`` 1.55 -> 1.75 and
with it ``FollowConfig.desired_distance_m`` 1.60 -> **1.85**. A compliant follow
controller therefore holds anywhere out to ``1.85 + 0.18 = 2.03 m`` from the
owner — **outside** a 1.8 m disc centred on the owner. So the controller
terminated ``completed``/``at_follow_distance`` (a reason in
``SYSTEM_ARRIVAL_REASONS``, i.e. a system arrival CLAIM) while the K0
``GoalRegion.contains`` predicate said no, producing
``FALSE_ARRIVAL: claim_without_predicate`` on three of the five ``follow_owner``
minival episodes. With E5's settled clearance the v3 episode is **unsatisfiable
by any compliant robot** (the smallest hold distance, 1.85 m, is already outside
the 1.80 m disc before the deadband is considered). The robot stands FARTHER
from the person and is strictly safer; the eval region is what went stale.
Diagnosis: ``scrum/20260809/task_15/E7_FALSE_ARRIVAL_STATUS.md``.

WHAT THIS BRIDGE HAS TO PROVE
-----------------------------
1. **Which episodes moved at all** (spec bridge, pure) — under (e) only goals
   built by the ``follow_owner`` branch can move, so the answer must be exactly
   the five ``follow_owner`` episodes, in exactly two fields
   (``goal.radius_m`` and the ``shortest_path_m`` that is *computed* from it),
   and nothing else. ``circle_owner`` must NOT move: see
   :data:`~evals.nav_instruct.generator.CIRCLE_OWNER_GOAL_RADIUS_M`.
2. **That the new radius is a derivation, not a fit** — :data:`DERIVATION`
   states every term, the margin, and where each is read from, and
   ``derivation_check()`` re-evaluates it against the live authority.
3. **That every v3 -> v4 verdict delta is the resize and none is a behaviour
   regression** — the 2x2 in :data:`RECORDED_OLD_CODE_CELLS` /
   :func:`measured_bridge`, whose required signature is: false arrivals exist
   ONLY in (old episodes × new code) and are absent in (new episodes × new
   code), while (old episodes × old code) reproduces the historical frozen
   baseline row bit-for-bit.

THE CODE AXIS
-------------
"old code" is commit ``6bd945d`` — the tree the historical frozen-baseline row
was measured on, and the tree the uncommitted repair lanes E1-E6 sit on top of.
"new code" is that tree plus E1-E6. The episodes are the DATA axis and the tree
is the CODE axis, so the v4 column on old code is the frozen v4 episode *data*
replayed there; ``6bd945d``'s generator has no v4 and, running the live
derivation against its own pre-retune authority, would produce 1.93 m rather
than the frozen 2.13 m. That is the point of freezing a set: the artifact is the
data, not the recipe.

The two old-code cells cannot be produced from this tree, so they are RECORDED
(with the exact command that produced them) rather than re-run. They are not
taken on trust: ``verify_recorded_baseline_cell()`` checks the (old × old) cell
against the committed frozen-baseline ledger row on every pinned quantity, from
this tree, so a mistyped recorded number is a red test rather than a claim.

Nothing here writes to the frozen ledger and nothing here is a baseline.

Usage::

    .parcel/bin/python -m evals.nav_instruct.bridge_v3_v4 --run
    .parcel/bin/python -m evals.nav_instruct.bridge_v3_v4 --spec-only
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.nav_instruct.generator import (
    CIRCLE_OWNER_GOAL_RADIUS_M,
    EPISODE_SET_V3,
    EPISODE_SET_V4,
    FOLLOW_DISTANCE_DEADBAND_M,
    FOLLOW_HOLD_BAND_OUTER_M,
    FOLLOW_OWNER_COLLISION_ENVELOPE_M,
    FOLLOW_OWNER_GOAL_RADIUS_M,
    FOLLOW_STAND_OFF_M,
    FROZEN_FOLLOW_OWNER_GOAL_RADIUS_M,
    OWNER_KEEPOUT_M,
    OWNER_STAND_OFF_MARGIN_M,
    EpisodeSpec,
    episode_set_spec,
    generate_minival,
    matrix_digest,
)
from evals.nav_instruct.runner import (
    ARRIVAL_RULE_FOR_VERSION,
    RUNNER_VERSION,
    NavInstructRunner,
    aggregate_results,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"
LEDGER = RESULTS_DIR / "ledger.jsonl"
BRIDGE_PATH = RESULTS_DIR / "bridge_v3_v4.json"

BRIDGE_VERSIONS: tuple[str, ...] = (EPISODE_SET_V3, EPISODE_SET_V4)

#: The budget policy the historical frozen-baseline row was measured under.
#: Every cell of the 2x2 uses it, or the cells are not comparable to each other
#: or to the row they must reproduce.
BRIDGE_BUDGET_POLICY = "scaled-path-v1"

#: The commit the "old code" column was measured on.
OLD_CODE_COMMIT = "6bd945d"

#: The frozen-baseline ledger row the (old episodes × old code) cell must
#: reproduce. E7 escalated that this row records ``false_arrival: 0`` while a
#: fresh run of the same 25 episodes on the working tree gives 3; the 2x2 is
#: what shows the row was true when it was written and that only the code axis
#: moved under it.
HISTORICAL_BASELINE_ROW_ID = "nav-instruct-v1-baseline-v3-20260809T161252Z"

CORRECTIONS: dict[str, str] = {
    "e": (
        "derived follow_owner goal radius — the disc centred on the owner stops "
        "being the bare literal 1.8 m and becomes "
        "(desired_distance_m + distance_deadband_m) + OWNER_STAND_OFF_MARGIN_M, "
        "i.e. the outer edge of the hold band a compliant follow controller may "
        "claim at_follow_distance from, wrapped by the same arrival_radius_m + "
        "stand_off_margin_m the authority already puts between a ring and the "
        "region that wraps it. 1.8 -> 2.13 m. circle_owner is NOT touched"
    ),
}

#: The derivation, stated as data so it can be re-evaluated rather than believed.
DERIVATION: dict[str, Any] = {
    "authorization": (
        "owner, 2026-08-11 — re-freeze the episodes to v4 so the follow goal "
        "radii match the retuned stand-off, keeping the pedestrian-clearance gain"
    ),
    "what_the_region_must_admit": (
        "FollowOwnerController.step's holding branch fires when "
        "distance - desired_distance_m <= distance_deadband_m and returns "
        "reason='at_follow_distance', which is in SYSTEM_ARRIVAL_REASONS. So the "
        "set of owner distances at which a COMPLIANT controller may claim "
        "arrival is (0, desired_distance_m + distance_deadband_m]. Approaching "
        "from outside — which is how every one of these episodes starts — the "
        "controller stops at the first distance satisfying the predicate, i.e. "
        "at the band's OUTER edge. That edge is the ring the eval region must "
        "contain."
    ),
    "terms": [
        {
            "name": "person_stop_m",
            "value": OWNER_KEEPOUT_M - FOLLOW_OWNER_COLLISION_ENVELOPE_M,
            "read_from": "authority.DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)",
            "why": "the authority's person clearance; E5 raised it 1.0 -> 1.2",
        },
        {
            "name": "owner_collision_envelope_m",
            "value": FOLLOW_OWNER_COLLISION_ENVELOPE_M,
            "read_from": "navigation.follow._OWNER_COLLISION_ENVELOPE_M",
            "why": (
                "apply_reactive_safety subtracts it from the owner CENTRE "
                "distance before comparing against person_stop_m"
            ),
        },
        {
            "name": "owner_keepout_m",
            "value": OWNER_KEEPOUT_M,
            "read_from": "person_stop_m + owner_collision_envelope_m",
            "why": "the ring the final safety gate refuses to translate through",
        },
        {
            "name": "OWNER_STAND_OFF_MARGIN_M",
            "value": OWNER_STAND_OFF_MARGIN_M,
            "read_from": (
                "authority.DEFAULT_STAND_OFF_ENVELOPE.arrival_radius_m (0.06) + "
                ".stand_off_margin_m (0.04)"
            ),
            "why": (
                "StandOffEnvelope already fixes this pair as the margin between "
                "a ring that must be cleared and the stand-off that wraps it "
                "(stand_off(r) - minimum_vicinity(r) == arrival_radius_m + "
                "stand_off_margin_m). arrival_radius_m is, verbatim from "
                "FIELD_META, 'Controller position tolerance at the terminal "
                "pose' — exactly what an eval region must tolerate on top of a "
                "nominal hold band. Lane E5 named this constant and applied it "
                "to the keepout ring; (e) applies the SAME pair one ring further "
                "out, to the hold band's outer edge"
            ),
        },
        {
            "name": "desired_distance_m",
            "value": FOLLOW_STAND_OFF_M,
            "read_from": "owner_keepout_m + OWNER_STAND_OFF_MARGIN_M  (lane E5)",
            "why": "the nominal follow stand-off; 1.60 -> 1.85 under E5",
        },
        {
            "name": "distance_deadband_m",
            "value": FOLLOW_DISTANCE_DEADBAND_M,
            "read_from": "navigation.follow.FollowConfig.distance_deadband_m",
            "why": "the half-width of the hold band; unchanged by E5/E6",
        },
    ],
    "formula": (
        "radius = (desired_distance_m + distance_deadband_m) "
        "+ OWNER_STAND_OFF_MARGIN_M"
    ),
    "hold_band_outer_m": FOLLOW_HOLD_BAND_OUTER_M,
    "v3_radius_m": FROZEN_FOLLOW_OWNER_GOAL_RADIUS_M,
    "v4_radius_m": FOLLOW_OWNER_GOAL_RADIUS_M,
    "not_a_fit": (
        "the three measured false arrivals sit at 2.0070 / 2.0190 / 2.0282 m of "
        "owner distance, so ANY radius from 2.0282 up turns them green and 2.13 "
        "is not the smallest such number — it is what the derivation yields. Nor "
        "is it applied only to the three that failed: the radius is a "
        "family-level constant and the defect is family-level (E7 §3.4), so all "
        "five follow_owner episodes take it"
    ),
    "circle_owner_unchanged": {
        "radius_m": CIRCLE_OWNER_GOAL_RADIUS_M,
        "why": (
            "its compliant terminal ring is default_orbit_radius_m (1.6) ± "
            "waypoint_tolerance_m (0.16) = 1.76 m, and even the widest orbit the "
            "config permits (max_orbit_radius_m 2.0) tops out at 2.16 m — both "
            "inside 2.2. Not one term feeding that ring moved under E5 or E6, "
            "and E7 measured the five circle_owner episodes reproducing the "
            "frozen baseline exactly (4 authority_disagreement + 1 agreement, 0 "
            "false arrivals). The retuned stand-off did not invalidate this "
            "region, so correction (e) does not reach it"
        ),
    },
}

#: The two cells that cannot be produced from this tree, recorded with the exact
#: command that produced them. Verified, not trusted — see
#: :func:`verify_recorded_baseline_cell`.
RECORDED_OLD_CODE_CELLS: dict[str, dict[str, Any]] = {
    "provenance": {
        "tree": (
            f"git worktree add --detach <scratch>/oldtree {OLD_CODE_COMMIT}; "
            "third_party/ symlinked in; run with "
            "PYTHONPATH=<oldtree>/src:<oldtree> and parcel_robot.__file__ "
            "asserted in-process to resolve inside the worktree (the editable "
            ".pth points at the main tree's src)"
        ),
        "import_order": (
            "parcel_robot.navigation.pipeline imported first, per E7 §2.1: at "
            f"{OLD_CODE_COMMIT} importing evals.nav_instruct.runner first hits the "
            "instructnav import cycle that lane E1 fixed. _HAS_INSTRUCTNAV was "
            "asserted True in BOTH arms, so the old-code column is not a "
            "degraded navigator"
        ),
        "data_axis": (
            "the v4 column on old code replays the FROZEN v4 episode data "
            f"(digest below); {OLD_CODE_COMMIT}'s generator has no v4 and its "
            "pre-retune authority would derive 1.93 m, not 2.13 m"
        ),
        "loader_control": (
            "v3 was ALSO run on old code through the same JSON episode loader "
            "the v4 column uses; the two v3 old-code runs are byte-identical, so "
            "the loader is not a confound"
        ),
        "budget_policy": BRIDGE_BUDGET_POLICY,
    },
    EPISODE_SET_V3: {
        "episode_digest": (
            "919a0fea836363a6f6d04d3fb186b0dcb493aa6c76357d8af2b0c05408c556aa"
        ),
        "sr": 0.2,
        "spl": 0.16016476583919256,
        "mean_dtg_m": 8.24432438739639,
        "collision_total": 0,
        "sr_frozen_rule": 0.04,
        "authority_histogram": {
            "agreement": 21,
            "tolerated_boundary": 0,
            "authority_disagreement": 4,
            "false_arrival": 0,
            "unknown": 0,
        },
        "failure_histogram": {
            "grounding_error": 3,
            "search_error": 0,
            "planning_error": 6,
            "control_error": 0,
            "termination": 5,
            "refusal": 6,
            "false_arrival": 0,
            "none": 5,
        },
        "arrival_branch_histogram": {"frozen_hold": 1, "none": 20, "trace_end_hold": 4},
        # [distance_to_goal_m, authority_category, failure_class, success]
        "per_episode": {
            "nav-circle_owner-A-00-6ba3a31d": [0.0, "authority_disagreement", "termination", False],
            "nav-circle_owner-B-05-4d7b5b21": [0.0, "authority_disagreement", "termination", False],
            "nav-circle_owner-C-10-4dd3449c": [7.508244, "agreement", "planning_error", False],
            "nav-circle_owner-D-15-717b5947": [0.0, "authority_disagreement", "termination", False],
            "nav-circle_owner-E-20-12e7db57": [0.0, "authority_disagreement", "termination", False],
            "nav-follow_owner-A-00-40672702": [0.031202, "agreement", "planning_error", False],
            "nav-follow_owner-B-05-334e8d3f": [0.031809, "agreement", "planning_error", False],
            "nav-follow_owner-C-10-41c8032b": [7.935406, "agreement", "planning_error", False],
            "nav-follow_owner-D-15-74a535dd": [0.0, "agreement", "none", True],
            "nav-follow_owner-E-20-433c9247": [1.257889, "agreement", "planning_error", False],
            "nav-object_goal-A-00-4caa923b": [0.0, "agreement", "none", True],
            "nav-object_goal-B-05-0ee314d5": [0.340725, "agreement", "termination", False],
            "nav-object_goal-C-10-68aa2ab8": [1.87, "agreement", "grounding_error", False],
            "nav-object_goal-D-15-109547e2": [0.0, "agreement", "none", True],
            "nav-object_goal-E-20-1a854173": [56.159537, "agreement", "refusal", False],
            "nav-object_relative-A-00-3efbba45": [0.0, "agreement", "none", True],
            "nav-object_relative-B-05-7d441aee": [1.483503, "agreement", "refusal", False],
            "nav-object_relative-C-10-0d3f5ebd": [7.470232, "agreement", "refusal", False],
            "nav-object_relative-D-15-61f68ad6": [4.330079, "agreement", "planning_error", False],
            "nav-object_relative-E-20-0c739ea2": [54.900336, "agreement", "refusal", False],
            "nav-region_goal-A-00-1c735162": [0.0, "agreement", "none", True],
            "nav-region_goal-B-05-586317e4": [2.425, "agreement", "refusal", False],
            "nav-region_goal-C-10-138643ba": [2.325, "agreement", "refusal", False],
            "nav-region_goal-D-15-1b8b2361": [1.89994, "agreement", "grounding_error", False],
            "nav-region_goal-E-20-6a95f8c4": [56.139209, "agreement", "grounding_error", False],
        },
    },
    EPISODE_SET_V4: {
        "episode_digest": (
            "4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222"
        ),
        "sr": 0.2,
        "spl": 0.16016476583919256,
        "mean_dtg_m": 8.215403974074324,
        "collision_total": 0,
        "sr_frozen_rule": 0.04,
        "authority_histogram": {
            "agreement": 19,
            "tolerated_boundary": 0,
            "authority_disagreement": 6,
            "false_arrival": 0,
            "unknown": 0,
        },
        "failure_histogram": {
            "grounding_error": 3,
            "search_error": 0,
            "planning_error": 4,
            "control_error": 0,
            "termination": 7,
            "refusal": 6,
            "false_arrival": 0,
            "none": 5,
        },
        "arrival_branch_histogram": {"frozen_hold": 1, "none": 20, "trace_end_hold": 4},
        # [distance_to_goal_m, authority_category, failure_class, success]
        "per_episode": {
            "nav-circle_owner-A-00-6ba3a31d": [0.0, "authority_disagreement", "termination", False],
            "nav-circle_owner-B-05-4d7b5b21": [0.0, "authority_disagreement", "termination", False],
            "nav-circle_owner-C-10-4dd3449c": [7.508244, "agreement", "planning_error", False],
            "nav-circle_owner-D-15-717b5947": [0.0, "authority_disagreement", "termination", False],
            "nav-circle_owner-E-20-12e7db57": [0.0, "authority_disagreement", "termination", False],
            "nav-follow_owner-A-00-40672702": [0.0, "authority_disagreement", "termination", False],
            "nav-follow_owner-B-05-334e8d3f": [0.0, "authority_disagreement", "termination", False],
            "nav-follow_owner-C-10-41c8032b": [7.605406, "agreement", "planning_error", False],
            "nav-follow_owner-D-15-74a535dd": [0.0, "agreement", "none", True],
            "nav-follow_owner-E-20-433c9247": [0.927889, "agreement", "planning_error", False],
            "nav-object_goal-A-00-4caa923b": [0.0, "agreement", "none", True],
            "nav-object_goal-B-05-0ee314d5": [0.340725, "agreement", "termination", False],
            "nav-object_goal-C-10-68aa2ab8": [1.87, "agreement", "grounding_error", False],
            "nav-object_goal-D-15-109547e2": [0.0, "agreement", "none", True],
            "nav-object_goal-E-20-1a854173": [56.159537, "agreement", "refusal", False],
            "nav-object_relative-A-00-3efbba45": [0.0, "agreement", "none", True],
            "nav-object_relative-B-05-7d441aee": [1.483503, "agreement", "refusal", False],
            "nav-object_relative-C-10-0d3f5ebd": [7.470232, "agreement", "refusal", False],
            "nav-object_relative-D-15-61f68ad6": [4.330079, "agreement", "planning_error", False],
            "nav-object_relative-E-20-0c739ea2": [54.900336, "agreement", "refusal", False],
            "nav-region_goal-A-00-1c735162": [0.0, "agreement", "none", True],
            "nav-region_goal-B-05-586317e4": [2.425, "agreement", "refusal", False],
            "nav-region_goal-C-10-138643ba": [2.325, "agreement", "refusal", False],
            "nav-region_goal-D-15-1b8b2361": [1.89994, "agreement", "grounding_error", False],
            "nav-region_goal-E-20-6a95f8c4": [56.139209, "agreement", "grounding_error", False],
        },
        "reading": (
            "the pre-retune controller stops at ~1.83 m from the owner, which is "
            "INSIDE the 2.13 m disc — so K0 says arrived — but it is still "
            "OUTSIDE its own 1.78 m hold band, so it never claims "
            "at_follow_distance. The honest verdict is authority_disagreement "
            "(scorer yes, system no), the SAFE direction, and the v4 region "
            "reports it rather than manufacturing a success. A-00 and B-05 do "
            "NOT flip to success on old code: the widened region alone does not "
            "buy them"
        ),
    },
}


def _goal_key(episode: EpisodeSpec) -> Any:
    return (episode.target_entity_id, json.dumps(episode.goal.as_dict(), sort_keys=True))


def derivation_check() -> dict[str, Any]:
    """Re-evaluate the derivation from the live authority, term by term."""

    chain = OWNER_KEEPOUT_M + OWNER_STAND_OFF_MARGIN_M
    hold = chain + FOLLOW_DISTANCE_DEADBAND_M
    radius = hold + OWNER_STAND_OFF_MARGIN_M
    return {
        "owner_keepout_m": OWNER_KEEPOUT_M,
        "stand_off_m": chain,
        "hold_band_outer_m": hold,
        "goal_radius_m": radius,
        "matches_frozen_v4_radius": radius == FOLLOW_OWNER_GOAL_RADIUS_M,
        "stand_off_matches_follow_config": chain == FOLLOW_STAND_OFF_M,
        "delta_from_v3_m": radius - FROZEN_FOLLOW_OWNER_GOAL_RADIUS_M,
    }


def spec_bridge(*, seed: int = 20260804) -> dict[str, Any]:
    """Per-episode goal changes from v3 to v4. Pure; no sim."""

    sets = {
        version: {ep.episode_id: ep for ep in generate_minival(seed=seed, version=version)}
        for version in BRIDGE_VERSIONS
    }
    rows: list[dict[str, Any]] = []
    counts = {"follow_goal_radius": 0, "unchanged": 0}
    fields_moved: set[str] = set()
    for episode_id, v3 in sets[EPISODE_SET_V3].items():
        v4 = sets[EPISODE_SET_V4][episode_id]
        before, after = v3.as_dict(), v4.as_dict()
        moved = sorted(
            field
            for field in before
            if json.dumps(before[field], sort_keys=True)
            != json.dumps(after[field], sort_keys=True)
        )
        if not moved:
            counts["unchanged"] += 1
            continue
        counts["follow_goal_radius"] += 1
        fields_moved.update(moved)
        goal_fields = sorted(
            field
            for field in before["goal"]
            if json.dumps(before["goal"][field], sort_keys=True)
            != json.dumps(after["goal"][field], sort_keys=True)
        )
        rows.append(
            {
                "episode_id": episode_id,
                "family": v3.family,
                "tier": v3.tier,
                "instruction": v3.instruction,
                "changed_by": "follow_goal_radius",
                "target": v3.target_entity_id,
                "fields_changed": moved,
                "goal_fields_changed": goal_fields,
                "v3_radius_m": v3.goal.radius_m,
                "v4_radius_m": v4.goal.radius_m,
                "v3_shortest_path_m": v3.shortest_path_m,
                "v4_shortest_path_m": v4.shortest_path_m,
                # Everything a reader might worry about, asserted unmoved.
                "instruction_unchanged": v3.instruction == v4.instruction,
                "start_pose_unchanged": v3.start_pose == v4.start_pose,
                "seed_unchanged": v3.seed == v4.seed,
                "target_unchanged": v3.target_entity_id == v4.target_entity_id,
                "placement_unchanged": v3.placement_overrides == v4.placement_overrides,
                "notes_unchanged": v3.notes == v4.notes,
            }
        )
    families_moved = sorted({row["family"] for row in rows})
    return {
        "seed": seed,
        "episode_count": len(sets[EPISODE_SET_V3]),
        "digests": {
            version: matrix_digest(tuple(sets[version].values()))
            for version in BRIDGE_VERSIONS
        },
        "id_mapping_is_total": set(sets[EPISODE_SET_V3]) == set(sets[EPISODE_SET_V4]),
        "counts_by_change": counts,
        # (e) can only reach goals built by the follow_owner branch. If any other
        # family shows up here, the change leaked.
        "families_moved": families_moved,
        "only_follow_owner_moved": families_moved == ["follow_owner"],
        # ...and within those, only the radius and the path length computed FROM
        # the radius. Any other field name here is an unattributable byte.
        "fields_moved_anywhere": sorted(fields_moved),
        "only_radius_and_derived_path_moved": sorted(fields_moved)
        == ["goal", "shortest_path_m"],
        "goal_fields_moved_anywhere": sorted(
            {field for row in rows for field in row["goal_fields_changed"]}
        ),
        "circle_owner_radius_unchanged": all(
            episode.goal.radius_m == CIRCLE_OWNER_GOAL_RADIUS_M
            for version in BRIDGE_VERSIONS
            for episode in sets[version].values()
            if episode.family == "circle_owner"
        ),
        "changed_rows": rows,
    }


def _cell(
    version: str, *, seed: int, max_steps: int, budget_policy: str
) -> dict[str, Any]:
    runner = NavInstructRunner(
        max_steps=max_steps,
        mode="baseline",
        arrival_rule=ARRIVAL_RULE_FOR_VERSION[version],
        budget_policy=budget_policy,
    )
    episodes = generate_minival(seed=seed, version=version)
    results = [runner.run_episode(ep) for ep in episodes]
    aggregate = aggregate_results(results, episode_set_version=version, scene=runner.scene)
    return {
        "episode_digest": matrix_digest(episodes),
        "arrival_rule": aggregate["arrival_rule"],
        "budget_policy": budget_policy,
        "sr": aggregate["sr"],
        "sr_frozen_rule": aggregate["sr_frozen_rule"],
        "spl": aggregate["spl"],
        "mean_dtg_m": aggregate["mean_dtg_m"],
        "collision_total": aggregate["collision_total"],
        "failure_histogram": aggregate["failure_histogram"],
        "authority_histogram": aggregate["authority_histogram"],
        "arrival_branch_histogram": aggregate["arrival_branch_histogram"],
        "successes": sorted(r.episode_id for r in results if r.score.success),
        "false_arrivals": sorted(
            r.episode_id
            for r in results
            if r.score.failure.value == "false_arrival"
        ),
        "scorer_arrival": sorted(r.episode_id for r in results if r.score.scorer_arrival),
        "system_arrival": sorted(r.episode_id for r in results if r.score.system_arrival),
        "dtg_by_episode": {r.episode_id: r.score.distance_to_goal_m for r in results},
        "authority_by_episode": {
            r.episode_id: r.score.authority_category.value for r in results
        },
        "terminal_by_episode": {
            r.episode_id: f"{r.mission_status}/{r.reason}" for r in results
        },
    }


def measured_bridge(
    *,
    seed: int = 20260804,
    max_steps: int = 200,
    budget_policy: str = BRIDGE_BUDGET_POLICY,
    versions: Sequence[str] = BRIDGE_VERSIONS,
) -> dict[str, Any]:
    """The two NEW-code cells, run here; the two old-code cells, recorded."""

    new_code = {
        version: _cell(
            version, seed=seed, max_steps=max_steps, budget_policy=budget_policy
        )
        for version in versions
    }
    v3, v4 = new_code[EPISODE_SET_V3], new_code[EPISODE_SET_V4]
    old_v3 = RECORDED_OLD_CODE_CELLS[EPISODE_SET_V3]
    old_v4 = RECORDED_OLD_CODE_CELLS[EPISODE_SET_V4]

    def _fa(cell: dict[str, Any]) -> int:
        return int(cell["authority_histogram"]["false_arrival"])

    signature = {
        "false_arrival": {
            "old_episodes_x_old_code": _fa(old_v3),
            "old_episodes_x_new_code": _fa(v3),
            "new_episodes_x_old_code": _fa(old_v4),
            "new_episodes_x_new_code": _fa(v4),
        },
        "required": (
            "false arrivals exist ONLY in (old episodes × new code) and are "
            "absent in (new episodes × new code); (old × old) reproduces the "
            "historical baseline"
        ),
    }
    fa = signature["false_arrival"]
    signature["holds"] = bool(
        fa["old_episodes_x_new_code"] > 0
        and fa["old_episodes_x_old_code"] == 0
        and fa["new_episodes_x_old_code"] == 0
        and fa["new_episodes_x_new_code"] == 0
    )

    def _live(cell: dict[str, Any], episode_id: str) -> list[Any]:
        return [
            round(float(cell["dtg_by_episode"][episode_id]), 6),
            cell["authority_by_episode"][episode_id],
        ]

    def _rec(cell: dict[str, Any], episode_id: str) -> list[Any]:
        return list(cell["per_episode"][episode_id][:2])

    # ---- the DATA axis, held at fixed code: which episodes the resize reaches.
    episode_axis = {
        "on_old_code": sorted(
            episode_id
            for episode_id in old_v3["per_episode"]
            if _rec(old_v3, episode_id) != _rec(old_v4, episode_id)
        ),
        "on_new_code": sorted(
            episode_id
            for episode_id in v3["dtg_by_episode"]
            if _live(v3, episode_id) != _live(v4, episode_id)
        ),
    }
    episode_axis["only_follow_owner_on_both_code_arms"] = all(
        episode_id.startswith("nav-follow_owner-")
        for column in ("on_old_code", "on_new_code")
        for episode_id in episode_axis[column]
    )

    # ---- the CODE axis, held at fixed episodes: what E1-E6 moved. The point of
    # this half is that the two lists are IDENTICAL outside follow_owner, which
    # is the proof the resize neither causes nor MASKS any of it.
    code_axis = {
        "under_v3_episodes": sorted(
            episode_id
            for episode_id in old_v3["per_episode"]
            if _rec(old_v3, episode_id) != _live(v3, episode_id)
        ),
        "under_v4_episodes": sorted(
            episode_id
            for episode_id in old_v4["per_episode"]
            if _rec(old_v4, episode_id) != _live(v4, episode_id)
        ),
    }
    code_axis["non_follow_owner_under_v3"] = [
        e for e in code_axis["under_v3_episodes"] if not e.startswith("nav-follow_owner-")
    ]
    code_axis["non_follow_owner_under_v4"] = [
        e for e in code_axis["under_v4_episodes"] if not e.startswith("nav-follow_owner-")
    ]
    code_axis["identical_outside_follow_owner"] = (
        code_axis["non_follow_owner_under_v3"] == code_axis["non_follow_owner_under_v4"]
    )
    code_axis["reading"] = (
        "these episodes move because of E1-E6, not because of the resize: they "
        "move by the SAME amount under both episode sets. They are pre-existing "
        "on this working tree (E7's panel reproduction already flagged "
        "nav-region_goal-D-15), they are NOT this lane's, and the v4 re-baseline "
        "carries them honestly rather than letting the wider region hide them. "
        "Measured non-causes: safety.person_slow_m (2.5 vs 2.0 is bit-identical "
        "on all four) and InstructNav ladder availability (_HAS_INSTRUCTNAV is "
        "True in both arms)"
    )

    delta = {
        "e_follow_goal_radius": {
            "sr_before": v3["sr"],
            "sr_after": v4["sr"],
            "sr_delta": v4["sr"] - v3["sr"],
            "mean_dtg_before_m": v3["mean_dtg_m"],
            "mean_dtg_after_m": v4["mean_dtg_m"],
            "collisions_before": v3["collision_total"],
            "collisions_after": v4["collision_total"],
            "false_arrivals_before": v3["false_arrivals"],
            "false_arrivals_after": v4["false_arrivals"],
            "episodes_gained": sorted(set(v4["successes"]) - set(v3["successes"])),
            "episodes_lost": sorted(set(v3["successes"]) - set(v4["successes"])),
            "k0_arrival_gained": sorted(
                set(v4["scorer_arrival"]) - set(v3["scorer_arrival"])
            ),
            "k0_arrival_lost": sorted(
                set(v3["scorer_arrival"]) - set(v4["scorer_arrival"])
            ),
            "system_arrival_moved": sorted(
                set(v3["system_arrival"]) ^ set(v4["system_arrival"])
            ),
            "verdict_changed": sorted(
                episode_id
                for episode_id, category in v4["authority_by_episode"].items()
                if v3["authority_by_episode"][episode_id] != category
            ),
            "dtg_changed": sorted(
                episode_id
                for episode_id, value in v4["dtg_by_episode"].items()
                if v3["dtg_by_episode"][episode_id] != value
            ),
            "rule": (
                "both sides on the v2/v3 arrival rule (v4 does not change it) and "
                f"on budget_policy={budget_policy!r}"
            ),
        }
    }
    moved = set(delta["e_follow_goal_radius"]["verdict_changed"]) | set(
        delta["e_follow_goal_radius"]["dtg_changed"]
    )
    delta["e_follow_goal_radius"]["every_moved_episode_is_follow_owner"] = all(
        episode_id.startswith("nav-follow_owner-") for episode_id in moved
    )
    return {
        "code_axis_definition": {
            "old_code": f"{OLD_CODE_COMMIT} (the tree the historical row was measured on)",
            "new_code": f"{OLD_CODE_COMMIT} + the uncommitted repair lanes E1-E6",
        },
        "cells": {
            "old_episodes_x_old_code": old_v3,
            "old_episodes_x_new_code": v3,
            "new_episodes_x_old_code": old_v4,
            "new_episodes_x_new_code": v4,
        },
        "old_code_provenance": RECORDED_OLD_CODE_CELLS["provenance"],
        "signature": signature,
        "episode_axis": episode_axis,
        "code_axis": code_axis,
        "deltas": delta,
    }


def verify_recorded_baseline_cell(ledger: Path = LEDGER) -> dict[str, Any]:
    """(old episodes × old code) vs the committed frozen-baseline ledger row.

    The recorded cell is the load-bearing half of the 2x2 and it was measured on
    a tree this process cannot reach. So it is checked against a committed
    artifact that *is* reachable here: a mistyped recorded number becomes a red
    test instead of an unfalsifiable claim.
    """

    rows = [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    row = next(
        (r for r in rows if r.get("report_id") == HISTORICAL_BASELINE_ROW_ID), None
    )
    if row is None:
        return {"row_found": False, "row_id": HISTORICAL_BASELINE_ROW_ID}
    cell = RECORDED_OLD_CODE_CELLS[EPISODE_SET_V3]
    compared = (
        "episode_digest",
        "sr",
        "spl",
        "mean_dtg_m",
        "collision_total",
        "sr_frozen_rule",
        "authority_histogram",
        "failure_histogram",
        "arrival_branch_histogram",
    )
    mismatches = {
        key: {"row": row.get(key), "recorded_cell": cell.get(key)}
        for key in compared
        if row.get(key) != cell.get(key)
    }
    return {
        "row_found": True,
        "row_id": HISTORICAL_BASELINE_ROW_ID,
        "row_budget_policy": row.get("budget_policy"),
        "compared_fields": list(compared),
        "mismatches": mismatches,
        "reproduces_historical_baseline": not mismatches,
    }


def build_bridge(
    *,
    seed: int = 20260804,
    run: bool,
    max_steps: int = 200,
    budget_policy: str = BRIDGE_BUDGET_POLICY,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "refreeze_bridge",
        "generated_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "runner_version": RUNNER_VERSION,
        "from_version": EPISODE_SET_V3,
        "to_version": EPISODE_SET_V4,
        "corrections": CORRECTIONS,
        "episode_set_provenance": {
            version: episode_set_spec(version).provenance for version in BRIDGE_VERSIONS
        },
        "follow_goal_radius_reference": {
            version: episode_set_spec(version).follow_goal_radius_reference
            for version in BRIDGE_VERSIONS
        },
        "next_to_band_reference": {
            version: episode_set_spec(version).next_to_band_reference
            for version in BRIDGE_VERSIONS
        },
        "derivation": DERIVATION,
        "derivation_check": derivation_check(),
        "frozen_baseline": False,
        "spec_bridge": spec_bridge(seed=seed),
        "recorded_baseline_cell_check": verify_recorded_baseline_cell(),
    }
    if run:
        payload["measured_bridge"] = {
            "measured_on": (
                "the two new-code cells in one process on this tree; the two "
                "old-code cells recorded from a detached worktree at "
                f"{OLD_CODE_COMMIT} (see old_code_provenance)"
            ),
            "why_not_the_frozen_v3_rows_alone": (
                "the v3 ledger rows were measured on 2026-08-09 code; "
                "differencing against them would charge everything E1-E6 landed "
                "to the resize. The 2x2 separates the two axes instead"
            ),
            **measured_bridge(
                seed=seed, max_steps=max_steps, budget_policy=budget_policy
            ),
        }
    return payload


def markdown_table(payload: dict[str, Any]) -> str:
    """The bridge as a table a human reads, not a JSON a script reads."""

    check = payload["derivation_check"]
    lines = [
        "DERIVATION — correction (e), the follow_owner goal disc",
        "",
        "| term | value (m) | read from |",
        "|---|---|---|",
    ]
    for term in payload["derivation"]["terms"]:
        lines.append(f"| `{term['name']}` | {term['value']} | {term['read_from']} |")
    lines += [
        "",
        (
            f"`{payload['derivation']['formula']}`  ->  "
            f"**{check['goal_radius_m']} m** (v3 was "
            f"{payload['derivation']['v3_radius_m']} m, "
            f"Δ {check['delta_from_v3_m']:+.4f} m)"
        ),
        "",
    ]
    measured = payload.get("measured_bridge") or {}
    if measured:
        cells = measured["cells"]
        lines += [
            "2x2 — episodes (data axis) × code (tree axis)",
            "",
            "| | v3 episodes | v4 episodes |",
            "|---|---|---|",
        ]
        for code, keys in (
            ("old code", ("old_episodes_x_old_code", "new_episodes_x_old_code")),
            ("new code", ("old_episodes_x_new_code", "new_episodes_x_new_code")),
        ):
            row = [f"| **{code}** "]
            for key in keys:
                cell = cells[key]
                hist = cell["authority_histogram"]
                row.append(
                    f"| SR {cell['sr']} · agreement {hist['agreement']} · "
                    f"**false_arrival {hist['false_arrival']}** "
                )
            lines.append("".join(row) + "|")
        signature = measured["signature"]
        lines += [
            "",
            (
                f"required signature holds: **{signature['holds']}**  "
                f"({signature['required']})"
            ),
            "",
        ]
        delta = measured["deltas"]["e_follow_goal_radius"]
        lines += [
            (
                f"v3 -> v4 on new code: SR {delta['sr_before']} -> "
                f"{delta['sr_after']}, false arrivals "
                f"{len(delta['false_arrivals_before'])} -> "
                f"{len(delta['false_arrivals_after'])}, collisions "
                f"{delta['collisions_before']} -> {delta['collisions_after']}"
            ),
            (
                "every moved episode is follow_owner: "
                f"**{delta['every_moved_episode_is_follow_owner']}**"
            ),
            "",
        ]
    spec = payload["spec_bridge"]
    lines += [
        (
            f"SPEC BRIDGE — {spec['counts_by_change']['follow_goal_radius']} moved, "
            f"{spec['counts_by_change']['unchanged']} unchanged; "
            f"only follow_owner moved: {spec['only_follow_owner_moved']}; "
            "only radius + derived path moved: "
            f"{spec['only_radius_and_derived_path_moved']}"
        ),
        "",
        "| episode | instruction | v3 R (m) | v4 R (m) | v3 path | v4 path |",
        "|---|---|---|---|---|---|",
    ]
    for row in spec["changed_rows"]:
        lines.append(
            f"| `{row['episode_id']}` | {row['instruction']} | "
            f"{row['v3_radius_m']} | {row['v4_radius_m']} | "
            f"{row['v3_shortest_path_m']} | {row['v4_shortest_path_m']} |"
        )
    verify = payload["recorded_baseline_cell_check"]
    lines += [
        "",
        (
            "(old episodes × old code) reproduces the committed frozen-baseline "
            f"row `{verify['row_id']}`: "
            f"**{verify.get('reproduces_historical_baseline')}**"
        ),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260804)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--budget-policy", default=BRIDGE_BUDGET_POLICY)
    parser.add_argument(
        "--run",
        action="store_true",
        help="also run the two new-code sim cells and difference them",
    )
    parser.add_argument(
        "--spec-only",
        action="store_true",
        help="pure spec bridge + derivation only; never touches the sim",
    )
    parser.add_argument("--out", type=Path, default=BRIDGE_PATH)
    parser.add_argument("--markdown", type=Path, default=None)
    args = parser.parse_args(argv)

    payload = build_bridge(
        seed=args.seed,
        run=args.run and not args.spec_only,
        max_steps=args.max_steps,
        budget_policy=args.budget_policy,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    table = markdown_table(payload)
    if args.markdown is not None:
        args.markdown.write_text(table + "\n", encoding="utf-8")
    print(table)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
