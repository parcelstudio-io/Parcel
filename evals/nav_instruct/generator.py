"""Seeded episode generator for NAV_INSTRUCT (pure; no runtime imports).

Families × tiers A–E. Deterministic: same seed → byte-identical episode set.
Counts: ≥20 episodes per family (spread across tiers).

Two episode-set versions live here and both are reproducible from this file
alone (see :data:`EPISODE_SETS`):

``v1``
    The frozen 2026-08-05/06 set. Digest
    ``cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf``. It is
    **immutable**: every default in this module still resolves to v1, so no
    edit for v2 may move a single byte of it. Pinned by
    ``tests/test_nav_instruct_scene_truth.py``.
``v2``
    The 2026-08-07 re-freeze. Three approved corrections, and only three:

    (a) **derived scene truth** — the landmark table is the ``derived`` section
        of ``scene_truth.json`` (the scene's own geometry) instead of the
        ``transcribed`` one, which is wrong in seven fields across five
        entities (the north sidewalk is 0.8 m narrower than the sidewalk the
        robot actually stands on, etc.);
    (b) **episode spec fixes** — class matching becomes word-boundary
        (``"walk towards the s|tree|tlight"`` no longer matches the tree class,
        which is why ``nav-object_goal-B-05`` scored a streetlight instruction
        against a tree), and a definite-article object reference anchors to the
        instance that is *visible from the episode's start pose* (which is why
        ``nav-object_goal-D-15``'s "walk towards the tree" no longer scores
        against a ``tree_1`` that is not in frame while ``tree_2`` is);
    (c) the corrected arrival-hold rule, which lives in the runner
        (``evals/nav_instruct/runner.py``), not here.

``v3``
    The 2026-08-09 re-freeze. One approved correction, and only one:

    (d) **surface-anchored ``next_to`` band** — the band is measured to the
        anchor's surface instead of its centre. Carries (a) + (b) unchanged.

``v4``
    The 2026-08-11 re-freeze. One approved correction, and only one:

    (e) **derived ``follow_owner`` goal radius** — the disc the owner sits in
        stops being the bare literal ``1.8`` and becomes a derivation from the
        same authority terms the follow controller obeys (see
        :data:`FOLLOW_OWNER_GOAL_RADIUS_M`). Carries (a) + (b) + (d) unchanged.

        Authorized by the owner on 2026-08-11 after lane E7 measured what the
        literal had become: the owner-authorized person-clearance retune (E5,
        2026-08-10) raised ``person_stop_m`` 1.0 -> 1.2, which raised the owner
        keepout ring 1.55 -> 1.75 and with it the follow stand-off 1.60 -> 1.85.
        A compliant follow controller therefore holds out to
        ``1.85 + 0.18 = 2.03 m`` from the owner, which is **outside** a 1.8 m
        disc centred on the owner — so the controller terminated
        ``at_follow_distance`` (a system arrival claim) while the K0 predicate
        said no, i.e. ``FALSE_ARRIVAL: claim_without_predicate`` on three of the
        five ``follow_owner`` minival episodes. With E5's settled clearance the
        v3 episode is unsatisfiable by ANY compliant robot, so the eval region
        is what went stale, not the robot. Full diagnosis:
        ``scrum/20260809/task_15/E7_FALSE_ARRIVAL_STATUS.md``; the re-freeze and
        its attribution: ``scrum/20260809/task_15/E8_V4_REFREEZE_STATUS.md`` and
        ``evals/nav_instruct/bridge_v3_v4.py``.

A third, bridge-only set — :data:`EPISODE_SET_V1A` — carries correction (a)
alone. It exists so ``bridge_v1_v2.py`` can attribute every moved goal to one
correction rather than to "the re-freeze"; it is never run and never frozen.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from evals.nav_instruct.scene_truth import (
    V2_LANDMARK_IDS,
    derived_landmark_table,
    landmark_table,
    load_artifact,
)
from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE, DEFAULT_STAND_OFF_ENVELOPE
from parcel_robot.instructnav.scan import full_turn_scan_spec
from parcel_robot.instructnav.scoring import (
    NEXT_TO_BAND_M,
    GoalRegion,
    arrival_goal_region_for_relation,
    object_near_goal_region,
    object_towards_goal_region,
    region_inside_goal_region,
)

FAMILIES: tuple[str, ...] = (
    "region_goal",
    "object_goal",
    "object_relative",
    "follow_owner",
    "circle_owner",
)

TIERS: tuple[str, ...] = ("A", "B", "C", "D", "E")

# Canonical city landmarks, read from the checked-in scene-truth artifact
# (`scene_truth.json`) rather than typed in here. The artifact carries BOTH the
# values below (`transcribed`) and the values derived from `city_block.xml`
# (`derived`), and a PR-tier test regenerates it from the scene — so a scene
# edit is now a red build instead of a silent goal shift.
#
# It deliberately still reads `transcribed`, not `derived`: the two disagree in
# seven fields across five entities (sidewalk / sidewalk_south / crosswalk
# polygons, bench_1 position+radius, tree_1 radius, bldg_1 radius — see
# `scene_truth.json` `transcription_deltas`). Adopting the derived values would
# move every affected episode goal and change the frozen minival digest, i.e. it
# needs a re-freeze, which is a separate card. Until then the delta is pinned by
# `tests/test_nav_instruct_scene_truth.py` so it can neither grow nor be
# silently adopted.
_LANDMARKS: dict[str, dict[str, Any]] = landmark_table()

EPISODE_SET_V1 = "v1"
EPISODE_SET_V2 = "v2"
EPISODE_SET_V3 = "v3"
EPISODE_SET_V4 = "v4"
#: Bridge-only intermediate: correction (a) with the v1 spec logic. Never run,
#: never frozen — it exists so a moved goal can be attributed to (a) or to (b).
EPISODE_SET_V1A = "v1a-scene-truth-only"
#: Card VS-6's ADDITIVE search tier. Not a re-freeze and not a baseline: it adds
#: episodes the frozen matrix does not contain (targets the opening scan cannot
#: see) so the visual-search rework has something to move. It carries v4's
#: corrections verbatim and moves not one byte of v1-v4 — the ``v\d+`` shape of
#: its name is deliberately NOT matched, so
#: ``tests/test_mutation_panel_freshness.py``'s "newest frozen set" scan still
#: resolves to ``v4``. See :func:`generate_v4s_matrix`.
EPISODE_SET_V4S = "v4s"

#: The three v4s axes, used as the ``tier`` code so the runner's existing
#: ``by_family_tier`` dashboard reports per-axis cells with no scoring change.
#:
#: ``LA``  look-around: the target is out of the start frustum AND beyond the
#:        world's visibility RANGE, so the opening full-turn scan cannot see it
#:        from the start pose; the straight corridor to it is clear of every
#:        building (no detour needed — the missing ingredient is *looking*).
#: ``BB``  beyond-the-block: same invisibility, but the straight corridor is
#:        blocked by a building footprint, so the frontier direction is what has
#:        to be got right.
#: ``PH``  phantom: an ``LA`` cell plus a same-class distractor at the corridor
#:        midpoint — inside the opening scan's range while the real target is
#:        outside it. The distractor has no MuJoCo geometry, so it is a
#:        detection with nothing behind it: a phantom, and committing to it is a
#:        false arrival against K0's untouched region.
V4S_AXIS_LOOK_AROUND = "LA"
V4S_AXIS_BEYOND_BLOCK = "BB"
V4S_AXIS_PHANTOM = "PH"
V4S_SEARCH_AXES: tuple[str, ...] = (
    V4S_AXIS_LOOK_AROUND,
    V4S_AXIS_BEYOND_BLOCK,
    V4S_AXIS_PHANTOM,
)

DEFAULT_EPISODE_SET_VERSION = EPISODE_SET_V1

#: The frozen v1 digest. Any change to this module that moves it is a bug.
FROZEN_V1_MINIVAL_DIGEST = (
    "cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf"
)

# ---------------------------------------------------------------------------
# The ``follow_owner`` goal disc, DERIVED — correction (e), v4.
#
# WHAT THE REGION HAS TO ADMIT.  ``FollowOwnerController.step``'s holding branch
# is ``distance - desired_distance_m <= distance_deadband_m``, so the set of
# owner distances at which a compliant controller may report
# ``at_follow_distance`` — a reason in ``SYSTEM_ARRIVAL_REASONS``, i.e. a system
# arrival CLAIM — is ``(0, desired_distance_m + distance_deadband_m]``. Its
# supremum is the hold band's OUTER edge, and that is the ring the eval region
# must contain, because approaching from outside the band is how every one of
# these episodes starts: the controller stops at the first distance that
# satisfies the predicate, which is the outer edge.
#
# WHICH TERMS.  Every one of them is read from the same authority the controller
# obeys, never typed as a target:
#
#   owner_keepout_m   = SafetyEnvelope.person_stop(0.0) + owner_collision_envelope
#                       — the ring ``apply_reactive_safety`` refuses to translate
#                         through (it subtracts the envelope from the owner CENTRE
#                         distance and compares the remainder to person_stop_m)
#   stand_off         = owner_keepout_m + OWNER_STAND_OFF_MARGIN_M   (lane E5)
#   hold band outer   = stand_off + distance_deadband_m
#
# WHICH MARGIN, AND WHY THAT ONE.  ``StandOffEnvelope`` already fixes the margin
# this codebase puts between a ring that must be cleared and the region that
# wraps it:
#
#     stand_off(r) - minimum_vicinity(r) == arrival_radius_m + stand_off_margin_m
#
# — ``arrival_radius_m`` (0.06) is, verbatim from ``authority.FIELD_META``,
# "Controller position tolerance at the terminal pose", and ``stand_off_margin_m``
# (0.04) is the authority's standing trailing margin on every stand-off. That is
# exactly the pair lane E5 named ``OWNER_STAND_OFF_MARGIN_M`` and applied to the
# owner keepout ring to get the stand-off. Correction (e) applies the SAME pair,
# one ring further out, to the hold band's outer edge to get the eval region:
# the region must tolerate the controller's own terminal position error on top
# of its nominal hold band, or the eval sits exactly on the controller's worst
# case and one tick of overshoot re-opens the false arrival.
#
#     radius = (desired_distance_m + distance_deadband_m) + OWNER_STAND_OFF_MARGIN_M
#            = (1.85 + 0.18) + 0.10   =   2.13 m
#
# WHAT THIS IS NOT.  It is not a number chosen to make an episode pass. The three
# measured false arrivals sit at 2.0070 / 2.0190 / 2.0282 m of owner distance;
# any radius from 2.0282 up would have turned them green, and 2.13 is not the
# smallest such number — it is what the derivation yields. Nor is it applied only
# to the three that failed: the radius is a family-level constant and the defect
# is family-level (E7 §3.4), so all five ``follow_owner`` episodes take it.
# ``circle_owner`` is deliberately NOT touched — see :data:`CIRCLE_OWNER_GOAL_RADIUS_M`.
#
# WHY THIS IS BETTER THAN THE LITERAL IT REPLACES.  v1-v3's ``1.8`` had no
# relationship to the controller, so E5's authorized retune could invalidate it
# silently and the failure surfaced three lanes later as a false arrival. As a
# live derivation, the same class of retune now moves this value and reddens the
# v4 digest pin immediately, naming the cause.

#: The owner's body envelope on the person channel. Restated here (not imported)
#: because this module is deliberately sim-free; it is the same 0.55 as
#: ``navigation.follow._OWNER_COLLISION_ENVELOPE_M`` and
#: ``navigation.spatial.SpatialBehaviorConfig.owner_collision_envelope_m``, and
#: ``tests/test_nav_instruct_episodes_v4.py`` pins the equality — the same
#: convention :data:`VISIBILITY_MAX_RANGE_M` below already uses.
FOLLOW_OWNER_COLLISION_ENVELOPE_M = 0.55
#: ``FollowConfig.distance_deadband_m``. Restated + pinned, as above.
FOLLOW_DISTANCE_DEADBAND_M = 0.18
#: ``arrival_radius_m`` + ``stand_off_margin_m`` — the authority's own margin
#: between a ring and the region that wraps it. Read from the authority, not
#: restated (lane E5 exports the identical expression as
#: ``navigation.reactive_safety.OWNER_STAND_OFF_MARGIN_M``).
OWNER_STAND_OFF_MARGIN_M = (
    DEFAULT_STAND_OFF_ENVELOPE.arrival_radius_m
    + DEFAULT_STAND_OFF_ENVELOPE.stand_off_margin_m
)
#: The ring the final safety gate refuses to translate through.
OWNER_KEEPOUT_M = (
    DEFAULT_SAFETY_ENVELOPE.person_stop(0.0) + FOLLOW_OWNER_COLLISION_ENVELOPE_M
)
#: ``FollowConfig.desired_distance_m`` — the nominal follow stand-off.
FOLLOW_STAND_OFF_M = OWNER_KEEPOUT_M + OWNER_STAND_OFF_MARGIN_M
#: The farthest owner distance at which a compliant controller may still claim
#: ``at_follow_distance``.
FOLLOW_HOLD_BAND_OUTER_M = FOLLOW_STAND_OFF_M + FOLLOW_DISTANCE_DEADBAND_M
#: v4's ``follow_owner`` goal radius: the hold band's outer edge, wrapped by the
#: authority's own stand-off margin.
FOLLOW_OWNER_GOAL_RADIUS_M = FOLLOW_HOLD_BAND_OUTER_M + OWNER_STAND_OFF_MARGIN_M
#: v1/v2/v3's ``follow_owner`` goal radius. A bare literal, frozen; kept so those
#: three sets still regenerate byte-identically.
FROZEN_FOLLOW_OWNER_GOAL_RADIUS_M = 1.8

#: ``circle_owner``'s goal radius, UNCHANGED in v4 and deliberately so. Its
#: compliant terminal ring is ``SpatialBehaviorConfig.default_orbit_radius_m``
#: (1.6) ± ``waypoint_tolerance_m`` (0.16) = 1.76 m at most, and even the widest
#: orbit the config permits (``max_orbit_radius_m`` 2.0) tops out at 2.16 m —
#: both inside 2.2. Not one term feeding that ring (orbit radii, waypoint
#: tolerance, ``owner_collision_envelope_m``, ``orbit_clearance_margin_m``) moved
#: under E5 or E6, and E7 measured the five ``circle_owner`` episodes reproducing
#: the frozen baseline exactly (4 ``authority_disagreement`` + 1 ``agreement``,
#: 0 false arrivals, dtg 0.0000). The retuned stand-off did not invalidate this
#: region, so correction (e) does not reach it.
CIRCLE_OWNER_GOAL_RADIUS_M = 2.2

#: The observation frustum the *world* reports through — the defaults of
#: ``parcel_robot.perception.city_semantics.visible_city_semantics``. They are repeated
#: here because this module is deliberately sim-free (``city_semantics``
#: imports ``mujoco`` at module scope), and they are pinned equal to the world's
#: by ``tests/test_nav_instruct_episodes_v2.py::
#: test_visibility_constants_match_the_world`` so the copy cannot drift.
VISIBILITY_MAX_RANGE_M = 12.0
VISIBILITY_HALF_FOV_RAD = math.radians(70.0)


@dataclass(frozen=True)
class EpisodeSetSpec:
    """What makes one episode-set version differ from another.

    Every field is a *named correction*, not a knob: reading this dataclass is
    the complete statement of what a re-freeze changed.
    """

    version: str
    #: Which section of ``scene_truth.json`` the landmark table comes from.
    landmark_section: str
    #: ``True`` → class words match on word boundaries (``\btree\b``);
    #: ``False`` → v1's bare substring test, which matches "s*tree*tlight".
    word_boundary_class_match: bool
    #: ``True`` → a definite-article object reference anchors to the instance
    #: visible from the start pose; ``False`` → v1's fixed first instance.
    visible_instance_anchoring: bool
    provenance: str
    #: What the ``next_to`` band is measured from. ``"surface"`` is the live K0
    #: definition (:func:`~parcel_robot.instructnav.scoring.next_to_band_from_centre`).
    #: ``"centre"`` is the superseded encoding v1 and v2 were frozen under and
    #: exists only so those sets still regenerate byte-identically — see
    #: :func:`_superseded_centre_anchored_next_to_region`.
    next_to_band_reference: str = "centre"
    #: Where the ``follow_owner`` goal radius comes from. ``"frozen_literal"`` is
    #: v1/v2/v3's bare ``1.8``; ``"follow_hold_band"`` is v4's derivation from the
    #: controller's own hold band — see :data:`FOLLOW_OWNER_GOAL_RADIUS_M`.
    follow_goal_radius_reference: str = "frozen_literal"
    #: Non-empty ONLY for an additive SEARCH tier (card VS-6's ``v4s``): the axes
    #: its episodes are built along. Empty for every frozen ``vN`` baseline set,
    #: which is what keeps this field off their manifests and out of their
    #: digests — see :func:`write_episode_files` and :data:`V4S_SEARCH_AXES`.
    search_axes: tuple[str, ...] = ()


EPISODE_SETS: dict[str, EpisodeSetSpec] = {
    EPISODE_SET_V1: EpisodeSetSpec(
        version=EPISODE_SET_V1,
        landmark_section="transcribed",
        word_boundary_class_match=False,
        visible_instance_anchoring=False,
        provenance="frozen 2026-08-05 baseline / 2026-08-06 candidate; immutable",
    ),
    EPISODE_SET_V1A: EpisodeSetSpec(
        version=EPISODE_SET_V1A,
        landmark_section="derived",
        word_boundary_class_match=False,
        visible_instance_anchoring=False,
        provenance="bridge-only: correction (a) isolated; never run, never frozen",
    ),
    EPISODE_SET_V2: EpisodeSetSpec(
        version=EPISODE_SET_V2,
        landmark_section="derived",
        word_boundary_class_match=True,
        visible_instance_anchoring=True,
        provenance="2026-08-07 re-freeze: corrections (a) + (b)",
    ),
    EPISODE_SET_V3: EpisodeSetSpec(
        version=EPISODE_SET_V3,
        landmark_section="derived",
        word_boundary_class_match=True,
        visible_instance_anchoring=True,
        provenance=(
            "2026-08-09 re-freeze: correction (d) surface-anchored next_to band; "
            "carries (a) + (b) unchanged from v2"
        ),
        next_to_band_reference="surface",
    ),
    EPISODE_SET_V4: EpisodeSetSpec(
        version=EPISODE_SET_V4,
        landmark_section="derived",
        word_boundary_class_match=True,
        visible_instance_anchoring=True,
        provenance=(
            "2026-08-11 re-freeze: correction (e) derived follow_owner goal "
            "radius (owner-authorized 2026-08-11, on lane E7's false-arrival "
            "diagnosis); carries (a) + (b) + (d) unchanged from v3"
        ),
        next_to_band_reference="surface",
        follow_goal_radius_reference="follow_hold_band",
    ),
    EPISODE_SET_V4S: EpisodeSetSpec(
        version=EPISODE_SET_V4S,
        landmark_section="derived",
        word_boundary_class_match=True,
        visible_instance_anchoring=True,
        provenance=(
            "2026-08-11 ADDITIVE search tier (card VS-6): new cells whose target "
            "is beyond the opening scan's reach. Carries v4's corrections "
            "(a) + (b) + (d) + (e) verbatim; adds no correction and re-freezes "
            "nothing — v1-v4 are byte-untouched"
        ),
        next_to_band_reference="surface",
        follow_goal_radius_reference="follow_hold_band",
        search_axes=V4S_SEARCH_AXES,
    ),
}

#: The ``follow_owner`` goal radius each episode-set version was frozen under.
FOLLOW_GOAL_RADIUS_BY_REFERENCE: dict[str, float] = {
    "frozen_literal": FROZEN_FOLLOW_OWNER_GOAL_RADIUS_M,
    "follow_hold_band": FOLLOW_OWNER_GOAL_RADIUS_M,
}


def follow_owner_goal_radius_m(spec: EpisodeSetSpec) -> float:
    """The ``follow_owner`` disc radius this episode-set version generates."""

    try:
        return FOLLOW_GOAL_RADIUS_BY_REFERENCE[spec.follow_goal_radius_reference]
    except KeyError:
        raise ValueError(
            "unknown follow_goal_radius_reference "
            f"{spec.follow_goal_radius_reference!r}; known: "
            f"{sorted(FOLLOW_GOAL_RADIUS_BY_REFERENCE)}"
        ) from None


def episode_set_spec(version: str = DEFAULT_EPISODE_SET_VERSION) -> EpisodeSetSpec:
    try:
        return EPISODE_SETS[version]
    except KeyError:
        raise ValueError(
            f"unknown episode set version {version!r}; known: {sorted(EPISODE_SETS)}"
        ) from None


def landmarks_for(spec: EpisodeSetSpec) -> dict[str, dict[str, Any]]:
    """The landmark table this episode-set version generates against."""

    if spec.landmark_section == "transcribed":
        return _LANDMARKS
    if spec.search_axes:
        # v4s routes are long enough to meet buildings the frozen ids never
        # name, so the search tier reads a WIDER slice of the same derived
        # section — same artifact, same reshaping, more ids. No frozen set can
        # see this table: their specs carry no search axes.
        return derived_landmark_table(ids=V4S_LANDMARK_IDS)
    return derived_landmark_table()


_FAMILY_TEMPLATES: dict[str, tuple[str, ...]] = {
    "region_goal": (
        "go to the sidewalk",
        "walk onto the sidewalk",
        "go to the pavement",
        "go to the crosswalk",
    ),
    "object_goal": (
        "can you walk towards the lamppost",
        "walk towards the streetlight",
        "go to the lamp post",
        "walk towards the tree",
    ),
    "object_relative": (
        "sit next to the bench",
        "wait by the bench",
        "stand next to the seat",
        "go next to the planter",
    ),
    "follow_owner": (
        "follow the owner",
        "follow me",
        "come with me",
        "stay with the owner",
    ),
    "circle_owner": (
        "circle around the owner",
        "orbit the owner",
        "walk around me",
        "circle me",
    ),
}

# Start poses keyed by tier relative to a target.
_TIER_STARTS: dict[str, tuple[tuple[float, float, float], ...]] = {
    # A: visible <5 m, facing target.
    "A": ((0.0, 0.0, 1.5708), (1.0, 0.5, 1.2), (-1.0, 0.0, 1.4)),
    # B: in-range outside frustum (behind the robot) — the reported bug.
    "B": ((0.0, 0.0, -1.5708), (0.5, 0.2, 3.1416), (-0.5, -0.2, 0.0)),
    # C: requires search (far / occluded side of block).
    "C": ((6.0, -6.0, 0.0), (-6.0, -6.0, 1.0), (7.0, 0.0, 2.5)),
    # D: ambiguity + synonyms (same starts as A; distractors added).
    "D": ((0.0, 0.0, 1.0), (1.5, -1.0, 1.2), (-1.5, 0.5, 0.8)),
    # E: absent / unreachable target.
    "E": ((0.0, 0.0, 1.5708), (2.0, -2.0, 0.5), (-2.0, 2.0, -0.5)),
}

EPISODES_PER_FAMILY_MIN = 20


@dataclass(frozen=True)
class EpisodeSpec:
    episode_id: str
    family: str
    tier: str
    instruction: str
    seed: int
    start_pose: tuple[float, float, float]  # x, y, yaw_rad
    goal: GoalRegion
    target_entity_id: str | None
    shortest_path_m: float
    distractors: tuple[str, ...]
    placement_overrides: dict[str, Any]
    synonym: str | None
    absent_target: bool
    notes: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["goal"] = self.goal.as_dict()
        payload["start_pose"] = list(self.start_pose)
        payload["distractors"] = list(self.distractors)
        return payload


def generate_episode_matrix(
    *,
    seed: int = 20260804,
    per_family: int = 25,
    version: str = DEFAULT_EPISODE_SET_VERSION,
    landmarks: dict[str, dict[str, Any]] | None = None,
) -> tuple[EpisodeSpec, ...]:
    """Build the full seeded matrix (≥20/family × tiers A–E).

    ``version`` selects the episode-set version (:data:`EPISODE_SETS`). The
    default is ``v1`` and is byte-frozen; nothing about a later version may
    reach this path.

    ``landmarks`` overrides the table the goals are built from. It exists for
    the scene-generalization split: the *same* episode logic against a
    *different* scene's derived truth is what makes the seen/unseen gap a
    statement about scenes rather than about episodes. Leave it ``None`` for
    any frozen set.
    """

    if per_family < EPISODES_PER_FAMILY_MIN:
        raise ValueError(f"per_family must be ≥ {EPISODES_PER_FAMILY_MIN}")
    spec = episode_set_spec(version)
    if spec.search_axes:
        # A search tier is not a family x tier matrix and must never be produced
        # by the frozen entrypoint: silently returning the v4 matrix under a v4s
        # label is exactly the "two rows that are not comparable" failure the
        # version stamps exist to prevent.
        raise ValueError(
            f"{version!r} is an additive search tier, not a frozen matrix; "
            "use generate_v4s_matrix()"
        )
    if landmarks is None:
        landmarks = landmarks_for(spec)
    rng = _SeedSeq(seed)
    episodes: list[EpisodeSpec] = []
    for family in FAMILIES:
        family_eps = _generate_family(
            family, per_family=per_family, rng=rng, spec=spec, landmarks=landmarks
        )
        episodes.extend(family_eps)
    return tuple(episodes)


def generate_minival(
    *,
    seed: int = 20260804,
    count: int = 25,
    version: str = DEFAULT_EPISODE_SET_VERSION,
    landmarks: dict[str, dict[str, Any]] | None = None,
) -> tuple[EpisodeSpec, ...]:
    """25-episode CI minival: one cell from each family×tier slice."""

    full = generate_episode_matrix(
        seed=seed, per_family=25, version=version, landmarks=landmarks
    )
    # Take first episode per (family, tier) then pad.
    seen: set[tuple[str, str]] = set()
    picked: list[EpisodeSpec] = []
    for ep in full:
        key = (ep.family, ep.tier)
        if key in seen:
            continue
        seen.add(key)
        picked.append(ep)
        if len(picked) >= count:
            break
    while len(picked) < count:
        picked.append(full[len(picked) % len(full)])
    return tuple(picked[:count])


def write_episode_files(
    episodes: Sequence[EpisodeSpec],
    out_dir: str | Path,
    *,
    version: str | None = None,
    seed: int | None = None,
) -> list[Path]:
    """Emit one JSON file per episode + a manifest; returns written paths.

    ``version``/``seed`` are recorded in the manifest only. They are
    deliberately kept off :class:`EpisodeSpec`, whose JSON form *is* the
    episode digest — adding a field there would move the frozen v1 digest.
    """

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ep in episodes:
        path = root / f"{ep.episode_id}.json"
        path.write_text(
            json.dumps(ep.as_dict(), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        paths.append(path)
    manifest: dict[str, Any] = {
        "count": len(episodes),
        "episode_ids": [ep.episode_id for ep in episodes],
        "sha256": _matrix_digest(episodes),
    }
    if version is not None:
        spec = episode_set_spec(version)
        manifest["episode_set_version"] = spec.version
        manifest["landmark_section"] = spec.landmark_section
        manifest["word_boundary_class_match"] = spec.word_boundary_class_match
        manifest["visible_instance_anchoring"] = spec.visible_instance_anchoring
        manifest["provenance"] = spec.provenance
        if spec.search_axes:
            # Conditional, like ``navigator_flags`` on a ledger row: a frozen
            # baseline manifest keeps the exact key set it was frozen with.
            manifest["search_axes"] = list(spec.search_axes)
            manifest["episodes_per_axis"] = {
                axis: sum(1 for ep in episodes if ep.tier == axis)
                for axis in spec.search_axes
            }
    if seed is not None:
        manifest["seed"] = int(seed)
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return paths


def matrix_digest(episodes: Sequence[EpisodeSpec]) -> str:
    return _matrix_digest(episodes)


def _generate_family(
    family: str,
    *,
    per_family: int,
    rng: _SeedSeq,
    spec: EpisodeSetSpec,
    landmarks: dict[str, dict[str, Any]],
) -> list[EpisodeSpec]:
    templates = _FAMILY_TEMPLATES[family]
    # Spread across tiers as evenly as possible; guarantee every tier appears.
    tier_quota = {tier: per_family // len(TIERS) for tier in TIERS}
    for tier in TIERS[: per_family % len(TIERS)]:
        tier_quota[tier] += 1
    out: list[EpisodeSpec] = []
    index = 0
    for tier in TIERS:
        for _ in range(tier_quota[tier]):
            instruction = templates[index % len(templates)]
            ep = _build_episode(
                family=family,
                tier=tier,
                instruction=instruction,
                index=index,
                rng=rng,
                spec=spec,
                landmarks=landmarks,
            )
            out.append(ep)
            index += 1
    return out


def _build_episode(
    *,
    family: str,
    tier: str,
    instruction: str,
    index: int,
    rng: _SeedSeq,
    spec: EpisodeSetSpec = EPISODE_SETS[EPISODE_SET_V1],
    landmarks: dict[str, dict[str, Any]] | None = None,
) -> EpisodeSpec:
    if landmarks is None:
        landmarks = landmarks_for(spec)
    ep_seed = rng.randint(0, 2**31 - 1)
    starts = _TIER_STARTS[tier]
    start = starts[index % len(starts)]
    # Small deterministic jitter so episodes aren't identical poses.
    jitter = ((ep_seed % 7) - 3) * 0.05
    start_pose = (start[0] + jitter, start[1] - jitter * 0.5, start[2])

    distractors: tuple[str, ...] = ()
    synonym: str | None = None
    absent = tier == "E" and family in {"region_goal", "object_goal", "object_relative"}
    placement: dict[str, Any] = {"robot": {"x": start_pose[0], "y": start_pose[1], "yaw": start_pose[2]}}

    if family == "region_goal":
        target_id, goal = _region_goal(
            instruction, tier=tier, absent=absent, landmarks=landmarks
        )
        if "pavement" in instruction:
            synonym = "pavement"
    elif family == "object_goal":
        target_id, goal = _object_goal(
            instruction,
            tier=tier,
            absent=absent,
            landmarks=landmarks,
            spec=spec,
            start_pose=start_pose,
        )
        if "streetlight" in instruction or "lamp post" in instruction:
            synonym = "streetlight" if "streetlight" in instruction else "lamp post"
    elif family == "object_relative":
        target_id, goal = _relative_goal(
            instruction, tier=tier, absent=absent, landmarks=landmarks, spec=spec
        )
        if "seat" in instruction:
            synonym = "seat"
        if tier == "D":
            distractors = ("bench_distractor",)
            placement["distractors"] = {
                "bench_distractor": {"x": -4.0, "y": 3.0, "label": "bench"}
            }
    elif family == "follow_owner":
        target_id = "owner"
        # Correction (e), v4: the radius is the version's, not a literal. v1/v2/v3
        # still resolve to 1.8 through ``follow_goal_radius_reference``.
        goal = GoalRegion(
            kind="disc", center=(2.0, -0.5), radius_m=follow_owner_goal_radius_m(spec)
        )
        if tier in {"C", "D", "E"}:
            placement["owner_path"] = "corner_occlusion" if tier != "E" else "absent"
            absent = tier == "E"
    else:  # circle_owner
        target_id = "owner"
        goal = GoalRegion(
            kind="disc", center=(2.0, -0.5), radius_m=CIRCLE_OWNER_GOAL_RADIUS_M
        )
        if tier in {"C", "D", "E"}:
            placement["pedestrian_distractors"] = 2 if tier == "D" else 0
            absent = tier == "E"

    if absent:
        placement["absent_target"] = True
        if target_id and target_id not in {"owner"}:
            placement["remove_entities"] = [target_id]

    shortest = _approx_shortest_path_m(start_pose[:2], goal, landmarks=landmarks)
    episode_id = f"nav-{family}-{tier}-{index:02d}-{ep_seed:08x}"
    notes = _tier_note(tier, family, absent=absent)
    return EpisodeSpec(
        episode_id=episode_id,
        family=family,
        tier=tier,
        instruction=instruction,
        seed=ep_seed,
        start_pose=start_pose,
        goal=goal,
        target_entity_id=None if absent else target_id,
        shortest_path_m=shortest,
        distractors=distractors,
        placement_overrides=placement,
        synonym=synonym,
        absent_target=absent,
        notes=notes,
    )


def _region_goal(
    instruction: str,
    *,
    tier: str,
    absent: bool,
    landmarks: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, GoalRegion]:
    landmarks = _LANDMARKS if landmarks is None else landmarks
    if "crosswalk" in instruction:
        landmark = landmarks["crosswalk"]
        entity_id = "crosswalk"
    else:
        landmark = landmarks["sidewalk" if tier != "C" else "sidewalk_south"]
        entity_id = "sidewalk" if tier != "C" else "sidewalk_south"
    polygon = landmark["polygon"]
    if absent:
        # Unreachable: empty/off-map disc the agent should not invent.
        return entity_id, GoalRegion(kind="disc", center=(40.0, 40.0), radius_m=0.5)
    return entity_id, region_inside_goal_region(polygon, entity_id=entity_id)


def _object_goal(
    instruction: str,
    *,
    tier: str,
    absent: bool,
    landmarks: dict[str, dict[str, Any]] | None = None,
    spec: EpisodeSetSpec = EPISODE_SETS[EPISODE_SET_V1],
    start_pose: tuple[float, float, float] | None = None,
) -> tuple[str, GoalRegion]:
    """Object-goal anchor for one instruction.

    v2 corrections, both inside correction (b):

    * **word-boundary class match.** ``"tree" in instruction`` is ``True`` for
      "walk towards the streetlight" — the substring test is why the frozen
      ``nav-object_goal-B-05`` asks for a streetlight and scores against a tree
      5.3 m away. v2 matches ``\\btree\\b``.
    * **visible-instance anchoring.** The scene holds two geometrically
      identical trees. A definite article ("*the* tree") that the generator
      resolves to a fixed instance can anchor the goal to a tree that is not in
      frame while the other one is — the frozen ``nav-object_goal-D-15``. v2
      resolves it to the instance actually visible from the start pose.
    """

    landmarks = _LANDMARKS if landmarks is None else landmarks
    if _mentions_class(instruction, "tree", spec):
        entity_id = _definite_instance(
            "tree",
            landmarks,
            start_pose=start_pose,
            spec=spec,
            fallback_id="tree_1",
        )
        landmark = landmarks[entity_id]
    else:
        # Instance choice here is tier-driven and deliberate: tier C exists to
        # force a search, so it names the *far* lamppost. Visible-instance
        # anchoring must not override a qualified selection — it only resolves
        # references the generator would otherwise leave ambiguous.
        entity_id = "lamp_post_2" if tier == "C" else "lamp_post_1"
        landmark = landmarks[entity_id]
    pos = landmark["position"]
    object_radius = float(landmark["radius_m"])
    label = str(landmark["label"])
    if absent:
        return entity_id, GoalRegion(kind="disc", center=(40.0, 40.0), radius_m=0.5)
    if "towards" in instruction:
        # Shared towards band with pipeline terminal verification (K0).
        return entity_id, object_towards_goal_region(pos, entity_id=entity_id)
    return entity_id, object_near_goal_region(
        pos,
        object_radius,
        label=label,
        entity_id=entity_id,
    )


def _superseded_centre_anchored_next_to_region(
    center: tuple[float, float],
    radius_m: float,
    *,
    entity_id: str,
) -> GoalRegion:
    """The ``next_to`` region **as v1 and v2 were frozen**, and nothing else.

    ``NEXT_TO_BAND_M`` is measured to the anchor's SURFACE since 2026-08-09
    (card S-1), so the live builder
    :func:`~parcel_robot.instructnav.scoring.object_next_to_goal_region` now
    stamps ``(0.4 + R, 1.5 + R)`` where the frozen sets carry ``(0.4, 1.5)``.
    A frozen episode set has to keep regenerating byte-identically or every
    comparison ever made against it is void, so the superseded encoding is
    written down here, once, in the only place that is allowed to reproduce a
    historical artifact.

    **It is not a second arrival authority.** No episode set generated from now
    on may use it (``next_to_band_reference="surface"`` is the live value), it
    is unreachable for any version whose spec says ``surface``, and the two
    frozen digests are what pin it. If it is ever deleted, v1 and v2 stop
    regenerating and ``tests/test_nav_instruct_episodes_v2.py`` says so.
    """

    return GoalRegion(
        kind="relative_band",
        center=(float(center[0]), float(center[1])),
        band_m=(float(NEXT_TO_BAND_M[0]), float(NEXT_TO_BAND_M[1])),
        anchor_entity=entity_id,
        anchor_footprint_m=float(radius_m),
    )


def _relative_goal(
    instruction: str,
    *,
    tier: str,
    absent: bool,
    landmarks: dict[str, dict[str, Any]] | None = None,
    spec: EpisodeSetSpec = EPISODE_SETS[EPISODE_SET_V1],
) -> tuple[str, GoalRegion]:
    """``next_to`` goal for one instruction, at this version's band definition.

    v3's correction (d): the band is measured to the anchor's **surface**, so
    the region is built by the live K0 builder and the band it stamps scales
    with the anchor. v1/v2 keep the centre-anchored encoding they were frozen
    under (:func:`_superseded_centre_anchored_next_to_region`) — a frozen set
    that silently adopts a new K0 definition is not frozen.
    """

    landmarks = _LANDMARKS if landmarks is None else landmarks
    if "planter" in instruction:
        entity_id = "planter_1"
        landmark = landmarks["planter_1"]
    else:
        entity_id = "bench_1"
        landmark = landmarks["bench_1"]
    # Same next_to builder the navigator uses (full radius_m; no ×0.5 shrink).
    radius_m = float(landmark["radius_m"])
    center: tuple[float, float] = tuple(landmark["position"])  # type: ignore[assignment]
    if absent:
        center, radius_m = (40.0, 40.0), 0.3
    if spec.next_to_band_reference == "centre":
        return entity_id, _superseded_centre_anchored_next_to_region(
            center, radius_m, entity_id=entity_id
        )
    if spec.next_to_band_reference != "surface":
        raise ValueError(
            f"unknown next_to_band_reference {spec.next_to_band_reference!r}"
        )
    return entity_id, arrival_goal_region_for_relation(
        "next_to",
        center=center,
        object_radius_m=radius_m,
        entity_id=entity_id,
        metadata={"radius_m": radius_m},
    )


def _mentions_class(instruction: str, word: str, spec: EpisodeSetSpec) -> bool:
    """Does this instruction name ``word`` as a class?

    v1 asked ``word in instruction`` and got "s(tree)tlight". v2 asks for a
    word boundary, which is the whole of the B-05 fix.
    """

    if spec.word_boundary_class_match:
        return re.search(rf"\b{re.escape(word)}\b", instruction) is not None
    return word in instruction


def _instance_ids_with_label(
    landmarks: dict[str, dict[str, Any]],
    label: str,
) -> list[str]:
    return sorted(
        entity_id
        for entity_id, entry in landmarks.items()
        if entry.get("kind") == "object" and entry.get("label") == label
    )


def visible_from_start(
    start_pose: tuple[float, float, float],
    position: tuple[float, float],
) -> bool:
    """The world's own visibility predicate, evaluated on an episode start pose.

    Identical in form to ``city_semantics._visible`` at the defaults
    ``visible_city_semantics`` uses; the constants are pinned equal to it by a
    test so this copy cannot drift from what the robot will actually see.
    """

    dx = float(position[0]) - float(start_pose[0])
    dy = float(position[1]) - float(start_pose[1])
    bearing = (
        math.atan2(dy, dx) - float(start_pose[2]) + math.pi
    ) % (2.0 * math.pi) - math.pi
    return (
        math.hypot(dx, dy) <= VISIBILITY_MAX_RANGE_M
        and abs(bearing) <= VISIBILITY_HALF_FOV_RAD
    )


def _definite_instance(
    label: str,
    landmarks: dict[str, dict[str, Any]],
    *,
    start_pose: tuple[float, float, float] | None,
    spec: EpisodeSetSpec,
    fallback_id: str,
) -> str:
    """Resolve "*the* <label>" to one instance, honestly.

    The rule, stated once: **prefer the instances visible from the episode's
    start pose; among those, take the nearest; break ties by entity id.** When
    nothing of that label is visible, fall back to the nearest instance overall
    — an unobservable goal is then a deliberate, recorded choice rather than an
    accident of table order.

    Disabled for v1 (``visible_instance_anchoring=False``), which always takes
    ``fallback_id`` — that is what makes v1 byte-reproducible.
    """

    if not spec.visible_instance_anchoring or start_pose is None:
        return fallback_id
    candidates = _instance_ids_with_label(landmarks, label)
    if not candidates:
        return fallback_id
    if len(candidates) == 1:
        return candidates[0]
    visible = [
        entity_id
        for entity_id in candidates
        if visible_from_start(start_pose, landmarks[entity_id]["position"])
    ]
    pool = visible or candidates
    return min(
        pool,
        key=lambda entity_id: (
            math.hypot(
                landmarks[entity_id]["position"][0] - start_pose[0],
                landmarks[entity_id]["position"][1] - start_pose[1],
            ),
            entity_id,
        ),
    )


def _approx_shortest_path_m(
    start: tuple[float, float],
    goal: GoalRegion,
    *,
    landmarks: dict[str, dict[str, Any]] | None = None,
) -> float:
    """Grid A* path length to the nearest admissible goal sample (pure).

    Obstacles are the building footprint from the landmark table. When A*
    finds no path, fall back to Euclidean distance-to-region (admissible
    lower bound) without claiming a grid path.
    """

    target = _goal_sample_point(start, goal)
    if target is None:
        return 0.0
    grid_len = _grid_astar_length_m(start, target, landmarks=landmarks)
    if grid_len is not None:
        return grid_len
    return _euclidean_to_goal(start, goal)


def _goal_sample_point(
    start: tuple[float, float],
    goal: GoalRegion,
) -> tuple[float, float] | None:
    if goal.kind == "disc" and goal.center is not None and goal.radius_m is not None:
        cx, cy = goal.center
        dist = math.hypot(start[0] - cx, start[1] - cy)
        if dist <= goal.radius_m:
            return start
        # Nearest point on the disc boundary toward the start.
        scale = goal.radius_m / dist
        return (cx + (start[0] - cx) * scale, cy + (start[1] - cy) * scale)
    if goal.kind == "polygon" and goal.polygon is not None:
        # Nearest vertex (generator stays pure; edge projection is optional).
        return min(
            goal.polygon,
            key=lambda p: math.hypot(start[0] - p[0], start[1] - p[1]),
        )
    if goal.center is not None and goal.band_m is not None:
        cx, cy = goal.center
        dist = math.hypot(start[0] - cx, start[1] - cy)
        lo = float(goal.band_m[0])
        target_r = max(lo, float(goal.anchor_footprint_m))
        if dist <= 1e-9:
            return (cx + target_r, cy)
        scale = target_r / dist
        return (cx + (start[0] - cx) * scale, cy + (start[1] - cy) * scale)
    return None


def _euclidean_to_goal(start: tuple[float, float], goal: GoalRegion) -> float:
    if goal.kind == "disc" and goal.center is not None and goal.radius_m is not None:
        return max(
            0.0,
            math.hypot(start[0] - goal.center[0], start[1] - goal.center[1])
            - goal.radius_m,
        )
    if goal.kind == "polygon" and goal.polygon is not None:
        return min(math.hypot(start[0] - p[0], start[1] - p[1]) for p in goal.polygon)
    if goal.center is not None and goal.band_m is not None:
        dist = math.hypot(start[0] - goal.center[0], start[1] - goal.center[1])
        lo = float(goal.band_m[0])
        return max(0.0, dist - lo)
    return 0.0


def _grid_astar_length_m(
    start: tuple[float, float],
    goal: tuple[float, float],
    *,
    resolution_m: float = 0.5,
    bounds: tuple[float, float, float, float] = (-10.0, -10.0, 10.0, 10.0),
    landmarks: dict[str, dict[str, Any]] | None = None,
) -> float | None:
    """4-connected A* on a free grid with the building footprint blocked."""

    min_x, min_y, max_x, max_y = bounds
    res = resolution_m
    blocked = _blocked_cells(res, landmarks=landmarks)
    start_cell = (
        math.floor((start[0] - min_x) / res),
        math.floor((start[1] - min_y) / res),
    )
    goal_cell = (
        math.floor((goal[0] - min_x) / res),
        math.floor((goal[1] - min_y) / res),
    )
    width = math.ceil((max_x - min_x) / res)
    height = math.ceil((max_y - min_y) / res)
    if not (0 <= start_cell[0] < width and 0 <= start_cell[1] < height):
        return None
    if not (0 <= goal_cell[0] < width and 0 <= goal_cell[1] < height):
        return None
    if start_cell in blocked or goal_cell in blocked:
        # Nudge goal off a blocked cell toward free space.
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1)):
            alt = (goal_cell[0] + dx, goal_cell[1] + dy)
            if 0 <= alt[0] < width and 0 <= alt[1] < height and alt not in blocked:
                goal_cell = alt
                break
        else:
            return None

    open_heap: list[tuple[float, float, tuple[int, int]]] = []
    heapq.heappush(open_heap, (0.0, 0.0, start_cell))
    g_score = {start_cell: 0.0}
    while open_heap:
        _, cost, current = heapq.heappop(open_heap)
        if current == goal_cell:
            return cost
        if cost > g_score.get(current, float("inf")) + 1e-12:
            continue
        cx, cy = current
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cx + dx, cy + dy)
            if not (0 <= nxt[0] < width and 0 <= nxt[1] < height):
                continue
            if nxt in blocked:
                continue
            tentative = cost + res
            if tentative + 1e-12 < g_score.get(nxt, float("inf")):
                g_score[nxt] = tentative
                heuristic = res * (abs(nxt[0] - goal_cell[0]) + abs(nxt[1] - goal_cell[1]))
                heapq.heappush(open_heap, (tentative + heuristic, tentative, nxt))
    return None


def _blocked_cells(
    resolution_m: float,
    *,
    landmarks: dict[str, dict[str, Any]] | None = None,
) -> set[tuple[int, int]]:
    """Block the building landmark footprint on the generator grid."""

    building = (_LANDMARKS if landmarks is None else landmarks)["bldg_1"]
    bx, by = building["position"]
    radius = float(building["radius_m"])
    min_x = -10.0
    min_y = -10.0
    blocked: set[tuple[int, int]] = set()
    r_cells = math.ceil(radius / resolution_m)
    cx = math.floor((bx - min_x) / resolution_m)
    cy = math.floor((by - min_y) / resolution_m)
    for ix in range(cx - r_cells, cx + r_cells + 1):
        for iy in range(cy - r_cells, cy + r_cells + 1):
            wx = min_x + (ix + 0.5) * resolution_m
            wy = min_y + (iy + 0.5) * resolution_m
            if math.hypot(wx - bx, wy - by) <= radius:
                blocked.add((ix, iy))
    return blocked


def _tier_note(tier: str, family: str, *, absent: bool) -> str:
    if absent:
        return "tier_E_absent_unreachable"
    return {
        "A": "visible_under_5m",
        "B": "in_range_outside_frustum",
        "C": "requires_search",
        "D": "ambiguity_or_synonym",
        "E": "absent_unreachable",
    }[tier] + f"|{family}"


# ---------------------------------------------------------------------------
# v4s — the ADDITIVE search tier (card VS-6)
#
# WHY A NEW SET AT ALL.  Lane V-D measured the value-directed-search flag as a
# structural no-op on the frozen matrix, and one leg of the diagnosis is that
# the frozen cells cannot exercise a search: the GP-UCB look block only runs
# AFTER the opening full turn, so any target the opening turn can see is already
# found and every extra look is redundant by construction. A cell that can move
# under a search rework therefore has to put the target OUTSIDE the opening
# scan's reach. No frozen episode does that, and editing one to do it would move
# a frozen digest. So the cells are new, and v1-v4 are byte-untouched.
#
# WHAT "OUTSIDE THE OPENING SCAN'S REACH" MEANS, EXACTLY.  The world reports
# semantics through one frustum — range :data:`VISIBILITY_MAX_RANGE_M` and
# half-FOV :data:`VISIBILITY_HALF_FOV_RAD`, both pinned equal to the world's own
# by ``tests/test_nav_instruct_episodes_v2.py``. An in-place full turn sweeps
# every bearing, so the ONLY thing it cannot overcome is range. Every v4s cell
# therefore asserts BOTH halves: the target is out of the start frustum
# (:func:`visible_from_start` false, so it is not visible at t=0) AND farther
# than the frustum's range (so the opening turn does not find it either). That
# is the whole of the "look-around-required beyond the initial scan pose"
# property, stated as geometry rather than as a hope.
# ---------------------------------------------------------------------------

#: The owner the headless world places in EVERY nav_instruct episode. The runner
#: resets with ``owner=None`` and the world still puts one here, which is what
#: lane D-15 traced its regression to. It is the same point the ``follow_owner``
#: and ``circle_owner`` goal discs are centred on above; pinned equal by
#: ``tests/test_v4s_search_cells.py``.
DEFAULT_OWNER_XY: tuple[float, float] = (2.0, -0.5)

#: How far a v4s corridor and route stay from the default owner's CENTRE:
#: :data:`FOLLOW_HOLD_BAND_OUTER_M`, the farthest distance at which a compliant
#: follow controller may still hold — so a v4s corridor never comes closer to
#: the owner than the follow stack's own outermost holding ring.
#:
#: WHY THAT RING.  D-15 is the lesson: an episode whose route runs into the
#: reactive gate's owner ring measures the GATE, not the search (the robot
#: hard-stopped every tick and the pipeline never saw a veto). 2.03 m from the
#: owner's centre is 1.48 m of surface clearance, which clears both rings the
#: gate applies to the owner — the slow band (``owner_slow_m`` = person_stop +
#: the authority's stand-off margin = 1.30 m) and the predictive stop
#: (``person_stop_m`` + cruise x reaction = 1.2 + 0.85 x 0.12 = 1.302 m). It is
#: a generation-time filter, so being generous only removes candidate corridors.
OWNER_CORRIDOR_KEEPOUT_M = FOLLOW_HOLD_BAND_OUTER_M

#: The owner's entry in the blocking-disc set. Named because the axis rule turns
#: on it: the owner ring blocks every axis equally (no v4s corridor may pass
#: through it), so only BUILDINGS can put a cell on the beyond-the-block axis.
V4S_OWNER_DISC_ID = "owner"

#: Clearance every v4s point (start pose, phantom, route cell, corridor) keeps
#: from a landmark disc: the robot's own body plus the obstacle gate's stop
#: floor, both read from the authority. Standing or translating outside it means
#: the obstacle branch of ``apply_reactive_safety`` does not bind — measured as
#: needed: at bare-disc clearance a start pose 0.38 m from ``bldg_6``'s surface
#: and a phantom placed against ``bldg_5``'s corner both produced stalls that
#: measure the obstacle gate rather than the search.
V4S_CLEARANCE_MARGIN_M = (
    DEFAULT_SAFETY_ENVELOPE.footprint_radius_m
    + DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m
)

#: Minimum angular separation between two admissible views — 2π / the full-turn
#: scan's own stop count, consumed BY REFERENCE from
#: ``instructnav.scan.full_turn_scan_spec``. §2.2(b) of the design record makes
#: this the view-admission authority; v4s uses the same quantity, one level up,
#: as the only start-heading offset it will apply, so the three headings a v4s
#: cell can start at are exactly three of the opening scan's own stops.
V4S_VIEW_SEPARATION_RAD = 2.0 * math.pi / float(full_turn_scan_spec().n_stops)

#: Start-pose lattice: a half-integer grid, so no start coincides with a
#: landmark centre or a scene obstacle's axis. Bounded by the A* grid the
#: routability assertion runs on (:func:`_grid_astar_length_m` bounds), one
#: lattice step inside it.
V4S_START_LATTICE_STEP_M = 1.0
V4S_START_LATTICE_LIMIT_M = 9.5

#: The landmark ids v4s generates against: the v2 ten, plus every BUILDING the
#: scene's derived truth knows about. The frozen sets name exactly one building
#: (``bldg_1``) because no frozen route is long enough to meet another; a v4s
#: route crosses the block, so "the straight corridor is clear" is only a true
#: claim if it is checked against all of them. Read from the artifact, never
#: transcribed: a scene edit that adds a building widens this list on its own.
V4S_LANDMARK_IDS: tuple[str, ...] = V2_LANDMARK_IDS + tuple(
    entity_id
    for entity_id, entry in sorted(load_artifact()["derived"].items())
    if entry.get("label") == "building" and entity_id not in V2_LANDMARK_IDS
)

#: v4s's own seed. A new set gets a new seed; nothing about it can reach v1-v4.
V4S_SEED = 20260811
#: Episodes per axis. The card's floor is 20; 60 is what VS-5's pre-registered
#: statistics want (6 net paired flips = exact-McNemar p ≤ 0.031 makes +10pp
#: detectable at n ≥ 60). Generation RAISES rather than silently shrinking when
#: an axis cannot be filled — open question 8 is a STOP-and-report, not a
#: margin to quietly lower.
V4S_EPISODES_PER_AXIS = 60


@dataclass(frozen=True)
class V4sTarget:
    """One v4s search target: what is asked for, and what it resolves to.

    ``twin_entity_ids`` are the OTHER instances of the same class. They are
    removed from the episode's perception specs (the tier-E ``remove_entities``
    mechanism, unchanged) so "the tree" has exactly one referent. Without that a
    v4s cell measures instance disambiguation — a different, already-owned
    problem (§2.2(a)(i)) — instead of search.
    """

    entity_id: str
    family: str
    instruction: str
    twin_entity_ids: tuple[str, ...] = ()


#: Every instruction below is a string the frozen matrix already runs, so v4s
#: adds ZERO new natural-language surface: the parser, the grounder vocabulary
#: and the relation are all exercised identically to v1-v4.
V4S_TARGETS: tuple[V4sTarget, ...] = (
    V4sTarget("tree_1", "object_goal", "walk towards the tree", ("tree_2",)),
    V4sTarget("tree_2", "object_goal", "walk towards the tree", ("tree_1",)),
    V4sTarget(
        "lamp_post_1", "object_goal", "walk towards the streetlight", ("lamp_post_2",)
    ),
    V4sTarget(
        "lamp_post_2", "object_goal", "can you walk towards the lamppost", ("lamp_post_1",)
    ),
    V4sTarget("bench_1", "object_relative", "wait by the bench", ()),
    V4sTarget("planter_1", "object_relative", "go next to the planter", ("planter_2",)),
)


def _v4s_blocking_discs(
    landmarks: dict[str, dict[str, Any]],
) -> tuple[tuple[str, float, float, float], ...]:
    """``(id, x, y, radius)`` discs a v4s corridor and route may not cross.

    The buildings at their landmark radius — the same convention
    :func:`_blocked_cells` already uses for ``bldg_1``, widened to all of them
    because a v4s route is long enough to meet any of them — plus the default
    owner at :data:`OWNER_CORRIDOR_KEEPOUT_M`.
    """

    discs = [
        (entity_id, float(entry["position"][0]), float(entry["position"][1]), float(entry["radius_m"]))
        for entity_id, entry in sorted(landmarks.items())
        if entry.get("kind") == "object" and entry.get("label") == "building"
    ]
    discs.append(
        (
            V4S_OWNER_DISC_ID,
            DEFAULT_OWNER_XY[0],
            DEFAULT_OWNER_XY[1],
            OWNER_CORRIDOR_KEEPOUT_M,
        )
    )
    return tuple(discs)


def _v4s_point_is_free(
    point: tuple[float, float],
    discs: Sequence[tuple[str, float, float, float]],
    *,
    margin_m: float = V4S_CLEARANCE_MARGIN_M,
) -> bool:
    return all(
        math.hypot(point[0] - x, point[1] - y) > radius + margin_m
        for _, x, y, radius in discs
    )


def _v4s_segment_blockers(
    start: tuple[float, float],
    end: tuple[float, float],
    discs: Sequence[tuple[str, float, float, float]],
    *,
    margin_m: float = 0.0,
) -> tuple[str, ...]:
    """Which discs the straight corridor ``start -> end`` passes through.

    Bare disc by default. The landmark radius is the CIRCUMSCRIBED radius of a
    box, so it already over-approximates every building by up to ~40% off the
    diagonal; adding the placement margin on top rejects every clear corridor in
    the scene (measured: LA yield 105 -> 0). The corridor test states which axis
    a cell belongs to — whether the straight line to the target crosses the
    block — not how close the robot may drive.
    """

    hits: list[str] = []
    ax, ay = float(start[0]), float(start[1])
    bx, by = float(end[0]), float(end[1])
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    for entity_id, cx, cy, radius in discs:
        if length_sq <= 1e-12:
            closest = (ax, ay)
        else:
            t = ((cx - ax) * dx + (cy - ay) * dy) / length_sq
            t = min(1.0, max(0.0, t))
            closest = (ax + t * dx, ay + t * dy)
        if math.hypot(cx - closest[0], cy - closest[1]) <= radius + margin_m:
            hits.append(entity_id)
    return tuple(hits)


def _v4s_route_length_m(
    start: tuple[float, float],
    goal: GoalRegion,
    discs: Sequence[tuple[str, float, float, float]],
    *,
    resolution_m: float = 0.5,
    bounds: tuple[float, float, float, float] = (-10.0, -10.0, 10.0, 10.0),
) -> float | None:
    """Grid route length from ``start`` INTO ``goal``, or ``None`` if unroutable.

    Stronger than :func:`_approx_shortest_path_m`, deliberately: that one routes
    to one sampled point and, when the sample lands on an obstacle, NUDGES the
    goal cell to a free neighbour. A generation-time routability assertion may
    not nudge. This one expands until it reaches a free cell the episode's own
    ``GoalRegion`` predicate accepts — so "routable" means "a route into the
    scored region exists", which is the claim the card asks for. Tier C's
    measured ``no_path|obstacle_stop`` domination is what makes it worth
    asserting per episode instead of assuming it.
    """

    min_x, min_y, max_x, max_y = bounds
    res = float(resolution_m)
    width = math.ceil((max_x - min_x) / res)
    height = math.ceil((max_y - min_y) / res)

    def centre(cell: tuple[int, int]) -> tuple[float, float]:
        return (min_x + (cell[0] + 0.5) * res, min_y + (cell[1] + 0.5) * res)

    def free(cell: tuple[int, int]) -> bool:
        if not (0 <= cell[0] < width and 0 <= cell[1] < height):
            return False
        # Bare disc, no clearance margin: the same convention
        # :func:`_blocked_cells` uses. A goal region may legitimately hug its
        # anchor (``tree_2`` sits 0.16 m outside ``bldg_4``'s circumscribed
        # disc), and this is an existence proof about the route, not a pose the
        # robot is asked to stand at.
        return _v4s_point_is_free(centre(cell), discs, margin_m=0.0)

    start_cell = (
        math.floor((start[0] - min_x) / res),
        math.floor((start[1] - min_y) / res),
    )
    if not free(start_cell):
        return None
    open_heap: list[tuple[float, tuple[int, int]]] = [(0.0, start_cell)]
    best: dict[tuple[int, int], float] = {start_cell: 0.0}
    while open_heap:
        cost, current = heapq.heappop(open_heap)
        if cost > best.get(current, float("inf")) + 1e-12:
            continue
        point = centre(current)
        if goal.contains(point[0], point[1], anchor_xy=goal.center):
            return cost
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (current[0] + dx, current[1] + dy)
            if not free(nxt):
                continue
            tentative = cost + res
            if tentative + 1e-12 < best.get(nxt, float("inf")):
                best[nxt] = tentative
                heapq.heappush(open_heap, (tentative, nxt))
    return None


def _v4s_start_lattice(
    discs: Sequence[tuple[str, float, float, float]],
) -> tuple[tuple[float, float], ...]:
    """Free half-integer lattice points inside the routability grid."""

    step = V4S_START_LATTICE_STEP_M
    limit = V4S_START_LATTICE_LIMIT_M
    count = round(2.0 * limit / step) + 1
    axis = [round(-limit + index * step, 6) for index in range(count)]
    return tuple(
        (x, y) for x in axis for y in axis if _v4s_point_is_free((x, y), discs)
    )


def _v4s_goal_for(
    target: V4sTarget,
    landmarks: dict[str, dict[str, Any]],
) -> tuple[GoalRegion, float, str]:
    """``(goal region, object radius, label)`` for one v4s target.

    Built by the SAME K0 builders the frozen sets use, selected by the same
    ``"towards"`` test as :func:`_object_goal` — v4s changes where the robot
    starts and what it can see, never what arrival means.
    """

    landmark = landmarks[target.entity_id]
    position: tuple[float, float] = (
        float(landmark["position"][0]),
        float(landmark["position"][1]),
    )
    radius_m = float(landmark["radius_m"])
    label = str(landmark["label"])
    if target.family == "object_relative":
        goal = arrival_goal_region_for_relation(
            "next_to",
            center=position,
            object_radius_m=radius_m,
            entity_id=target.entity_id,
            metadata={"radius_m": radius_m},
        )
    elif "towards" in target.instruction:
        goal = object_towards_goal_region(position, entity_id=target.entity_id)
    else:
        goal = object_near_goal_region(
            position, radius_m, label=label, entity_id=target.entity_id
        )
    return goal, radius_m, label


def _v4s_synonym(instruction: str) -> str | None:
    for token in ("streetlight", "lamp post", "pavement", "seat"):
        if token in instruction:
            return token
    return None


@dataclass(frozen=True)
class _V4sCell:
    """One admissible (axis, target, start) triple with its measured evidence."""

    axis: str
    target: V4sTarget
    start_xy: tuple[float, float]
    yaw_rad: float
    range_m: float
    route_length_m: float
    blockers: tuple[str, ...]
    phantom_xy: tuple[float, float] | None


def _v4s_admissible_cells(
    axis: str,
    *,
    starts: Sequence[tuple[float, float]],
    discs: Sequence[tuple[str, float, float, float]],
    landmarks: dict[str, dict[str, Any]],
) -> list[_V4sCell]:
    """Every (target, start) this axis admits, round-robin across targets.

    Two ordering decisions, both declared here rather than discovered later:

    * **Round-robin across targets**, not target-major, so that taking the first
      ``per_axis`` of the list spreads the axis over every target instead of
      exhausting one.
    * **Nearest-first within a target.** Every admitted cell is beyond the
      frustum's range by construction; among those, the ones just past the
      threshold are the ones a better search can plausibly convert, and a target
      19 m away tests the step budget rather than the search. This is a
      difficulty rule fixed at generation time, applied uniformly to all three
      axes, and chosen before any flag-on arm existed to tune it against.
    """

    per_target: list[list[_V4sCell]] = []
    for target_index, target in enumerate(V4S_TARGETS):
        goal, _radius_m, _label = _v4s_goal_for(target, landmarks)
        landmark = landmarks[target.entity_id]
        position = (float(landmark["position"][0]), float(landmark["position"][1]))
        admitted: list[_V4sCell] = []
        for start_index, start in enumerate(starts):
            range_m = math.hypot(position[0] - start[0], position[1] - start[1])
            # Beyond the opening full turn's reach: range is the only thing an
            # in-place turn cannot beat.
            if range_m <= VISIBILITY_MAX_RANGE_M:
                continue
            blockers = _v4s_segment_blockers(start, position, discs)
            # The owner ring blocks EVERY axis: a corridor that runs through it
            # measures the reactive gate, not the search (D-15). So the axis
            # distinction is about buildings alone, and "beyond the block" means
            # a BUILDING is in the way — never "a person is standing there".
            if V4S_OWNER_DISC_ID in blockers:
                continue
            if axis == V4S_AXIS_BEYOND_BLOCK and not blockers:
                continue
            if axis in {V4S_AXIS_LOOK_AROUND, V4S_AXIS_PHANTOM} and blockers:
                continue
            phantom_xy: tuple[float, float] | None = None
            if axis == V4S_AXIS_PHANTOM:
                midpoint = (
                    0.5 * (start[0] + position[0]),
                    0.5 * (start[1] + position[1]),
                )
                # The phantom must be inside the opening scan's range while the
                # real target is outside it — that asymmetry IS the cell.
                if 0.5 * range_m > VISIBILITY_MAX_RANGE_M:
                    continue
                if not _v4s_point_is_free(midpoint, discs):
                    continue
                if goal.contains(midpoint[0], midpoint[1], anchor_xy=goal.center):
                    continue
                phantom_xy = midpoint
            # Heading: face directly away from the target, offset by one of the
            # opening scan's own stop separations.
            bearing = math.atan2(position[1] - start[1], position[0] - start[0])
            offset = (start_index + target_index) % 3 - 1
            yaw = (
                bearing + math.pi + offset * V4S_VIEW_SEPARATION_RAD + math.pi
            ) % (2.0 * math.pi) - math.pi
            if visible_from_start((start[0], start[1], yaw), position):
                continue
            route = _v4s_route_length_m(start, goal, discs)
            if route is None:
                continue
            admitted.append(
                _V4sCell(
                    axis=axis,
                    target=target,
                    start_xy=start,
                    yaw_rad=yaw,
                    range_m=range_m,
                    route_length_m=route,
                    blockers=blockers,
                    phantom_xy=phantom_xy,
                )
            )
        admitted.sort(key=lambda cell: (cell.range_m, cell.start_xy))
        per_target.append(admitted)

    interleaved: list[_V4sCell] = []
    depth = max((len(items) for items in per_target), default=0)
    for index in range(depth):
        for items in per_target:
            if index < len(items):
                interleaved.append(items[index])
    return interleaved


def _build_v4s_episode(
    cell: _V4sCell,
    *,
    index: int,
    rng: _SeedSeq,
    landmarks: dict[str, dict[str, Any]],
) -> EpisodeSpec:
    ep_seed = rng.randint(0, 2**31 - 1)
    target = cell.target
    goal, radius_m, label = _v4s_goal_for(target, landmarks)
    start_pose = (cell.start_xy[0], cell.start_xy[1], cell.yaw_rad)
    placement: dict[str, Any] = {
        "robot": {"x": start_pose[0], "y": start_pose[1], "yaw": start_pose[2]},
    }
    if target.twin_entity_ids:
        placement["remove_entities"] = list(target.twin_entity_ids)
    distractors: tuple[str, ...] = ()
    evidence: dict[str, Any] = {
        "axis": cell.axis,
        "target_entity_id": target.entity_id,
        "start_target_range_m": cell.range_m,
        "beyond_scan_range": True,
        "visible_from_start": False,
        "corridor_blocked_by": list(cell.blockers),
        "route_length_m": cell.route_length_m,
        "detour_ratio": cell.route_length_m / cell.range_m,
        "routability": "astar_into_goal_region",
    }
    if cell.phantom_xy is not None:
        phantom_id = f"{target.entity_id}_phantom"
        distractors = (phantom_id,)
        placement["distractors"] = {
            phantom_id: {
                "x": cell.phantom_xy[0],
                "y": cell.phantom_xy[1],
                "label": label,
                "radius_m": radius_m,
            }
        }
        evidence["phantom_entity_id"] = phantom_id
        evidence["phantom_range_from_start_m"] = 0.5 * cell.range_m
        evidence["phantom_offset_from_target_m"] = 0.5 * cell.range_m
    placement["search_cell"] = evidence
    return EpisodeSpec(
        episode_id=f"nav-{target.family}-{cell.axis}-{index:02d}-{ep_seed:08x}",
        family=target.family,
        tier=cell.axis,
        instruction=target.instruction,
        seed=ep_seed,
        start_pose=start_pose,
        goal=goal,
        target_entity_id=target.entity_id,
        shortest_path_m=cell.route_length_m,
        distractors=distractors,
        placement_overrides=placement,
        synonym=_v4s_synonym(target.instruction),
        absent_target=False,
        notes=f"{_V4S_AXIS_NOTES[cell.axis]}|{target.family}",
    )


_V4S_AXIS_NOTES: dict[str, str] = {
    V4S_AXIS_LOOK_AROUND: "search_beyond_opening_scan",
    V4S_AXIS_BEYOND_BLOCK: "search_beyond_the_block_frontier",
    V4S_AXIS_PHANTOM: "search_beyond_opening_scan_with_view_consistent_phantom",
}


def generate_v4s_matrix(
    *,
    seed: int = V4S_SEED,
    per_axis: int = V4S_EPISODES_PER_AXIS,
    landmarks: dict[str, dict[str, Any]] | None = None,
) -> tuple[EpisodeSpec, ...]:
    """The additive v4s search tier: ``per_axis`` episodes on each of three axes.

    Every returned episode carries, in ``placement_overrides["search_cell"]``,
    the measured evidence for the three claims the card makes about it: the
    target's range from the start (> the frustum's range), which discs the
    straight corridor crosses (none for ``LA``/``PH``, at least one for ``BB``),
    and the grid route length INTO the goal region (never ``None`` — an
    unroutable candidate is dropped at generation, never emitted).

    Raises when an axis cannot be filled. That is deliberate: the pre-registered
    n is what makes VS-5's effect measurable, and a silently smaller set would
    turn a power failure into a null result.
    """

    spec = episode_set_spec(EPISODE_SET_V4S)
    if landmarks is None:
        landmarks = landmarks_for(spec)
    if per_axis < 1:
        raise ValueError("per_axis must be ≥ 1")
    discs = _v4s_blocking_discs(landmarks)
    starts = _v4s_start_lattice(discs)
    rng = _SeedSeq(seed)
    episodes: list[EpisodeSpec] = []
    for axis in V4S_SEARCH_AXES:
        admissible = _v4s_admissible_cells(
            axis, starts=starts, discs=discs, landmarks=landmarks
        )
        if len(admissible) < per_axis:
            raise ValueError(
                f"v4s axis {axis!r} yields only {len(admissible)} routable "
                f"episodes, below the pre-registered {per_axis} — STOP and "
                "report (design record §8 open question 8), never shrink"
            )
        for index, cell in enumerate(admissible[:per_axis]):
            episodes.append(
                _build_v4s_episode(cell, index=index, rng=rng, landmarks=landmarks)
            )
    return tuple(episodes)


def _matrix_digest(episodes: Sequence[EpisodeSpec]) -> str:
    blob = json.dumps(
        [ep.as_dict() for ep in episodes],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class _SeedSeq:
    """Tiny deterministic RNG (stdlib only; no numpy dependency)."""

    def __init__(self, seed: int) -> None:
        self._state = int(seed) & 0xFFFFFFFF

    def randint(self, lo: int, hi: int) -> int:
        # xorshift32
        x = self._state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17) & 0xFFFFFFFF
        x ^= (x << 5) & 0xFFFFFFFF
        self._state = x & 0xFFFFFFFF
        span = hi - lo + 1
        return lo + (self._state % span)
