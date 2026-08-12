"""DR-2 drift cells — the TRAVEL-HEAVY substrate the degraded-pose arms run on.

Why a new cell set exists at all
--------------------------------
Card DR-2 (``scrum/20260811/task_2/SLAM_M_PLAN.md`` Wave 2) needs a substrate on
which injected odometry drift can actually change an outcome. The two sets the
repo already owns do not qualify, for measured reasons:

* the **v4 minival** travels 13.5 m *in total* across 25 episodes (~0.54 m per
  episode). Lane B's own smoke measured an SPL delta of 0.0003 under drift. The
  plan therefore registers it as a **tripwire only** — reported, never floored.
* the **v4s search cells** are built so the target is *beyond* the opening
  scan's reach. Their default-matcher flag-off SR is 0.000 by construction and
  the ``LA`` axis carries 10 pre-existing ``false_arrival`` verdicts that are a
  matcher artefact (``episodes/V4S_MATCHER_ARM.md``). A floor derived from an
  SR that is structurally zero is vacuous, and DR-2's hard ``false_arrival = 0``
  invariant would redden on a defect that has nothing to do with pose.

So this module builds the third thing the card allows: **new long-travel
scenario cells**, whose one job is to make the robot integrate odometry over a
long walk to a target it can already see.

The admission rule, stated once
-------------------------------
A cell is admitted iff, from a free lattice start:

1. the target is **within** the frustum's range and the start yaw faces it, so
   ``visible_from_start`` is True — grounding resolves on the first tick and the
   cell measures TRAVEL, not search (that is v4s's job, and this set is its
   deliberate complement);
2. the straight corridor to the target crosses **no** building disc and **not**
   the owner keep-out ring — a corridor through the owner ring measures the
   reactive gate (D-15), and a blocked corridor measures the planner;
3. a grid route from the start **into the scored** ``GoalRegion`` exists and is
   at least :data:`DRIFT_MIN_ROUTE_M`.

and the cell then makes its referent unique in perception (see
:func:`_removed_entity_ids`), because the default matcher's cross-class commits
otherwise manufacture ``false_arrival`` verdicts that have nothing to do with
pose — measured, twice in the first ten episodes.

Every geometry primitive is imported from :mod:`evals.nav_instruct.generator`
rather than re-derived, so "routable", "free", "visible" and the K0 goal
builders mean exactly what they mean for v1-v4s. Nothing here edits or
re-freezes any existing set: this is an additive, candidate-only namespace.

Determinism
-----------
Generation is a pure function of ``(seed, per_target)`` and the scene artifact.
There is no sampling: admission and ordering are total, so the same call always
returns the same tuple in the same order. The seed only salts episode ids.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from evals.nav_instruct.generator import (
    EPISODE_SET_V4S,
    V4S_TARGETS,
    VISIBILITY_MAX_RANGE_M,
    EpisodeSpec,
    V4sTarget,
    _v4s_blocking_discs,
    _v4s_goal_for,
    _v4s_route_length_m,
    _v4s_segment_blockers,
    _v4s_start_lattice,
    _v4s_synonym,
    episode_set_spec,
    landmarks_for,
    load_artifact,
    visible_from_start,
)

#: The set's name. NOT a member of ``generator.EPISODE_SETS``: this is an
#: additive candidate namespace, and registering it as an episode-set *version*
#: would let ``--freeze`` and the frozen-baseline ledger flag reach it.
DRIFT_SET_NAME = "v4d"

#: This set's own seed. A new set gets a new seed; nothing about it can reach
#: v1-v4s.
DRIFT_SEED = 20260812

#: What a reader of a persisted row needs in order to know what they are
#: looking at, carried on the report and the ledger row like every episode set's
#: ``provenance``.
DRIFT_PROVENANCE = (
    "2026-08-12 ADDITIVE long-travel substrate (card DR-2): every scene cell "
    "whose target is visible from the start down a clear corridor at least "
    "10 m of grid route away, with the referent made unique in perception. "
    "Built by v4s's geometry and the live K0 goal builders; adds no arrival "
    "rule and re-freezes nothing. CANDIDATE-ONLY — never a frozen baseline"
)

#: Minimum grid route length INTO the scored region, in metres.
#:
#: Derived, not chosen: DR-1's ``*_lost`` profiles carry exactly one scheduled
#: dropout window at ``(start_s 4.0, duration_s 3.0)``, derived there against a
#: "~12 m at the ~1 m/s cruise ~= 12 s" episode so that the window has healthy
#: operation before it AND after it. DR1_STATUS.md §2 states the constraint
#: explicitly: "if a DR-2 substrate is materially shorter than ~10 s of travel
#: this window stops being derivable and needs a DR-1 handoff". At the harness's
#: 0.85 m/s cruise a 10 m route is ~11.8 s of pure travel before any alignment,
#: scan or settle time is counted, so 10.0 m is the smallest round route length
#: that keeps DR-1's window derivable on every admitted cell.
DRIFT_MIN_ROUTE_M = 10.0

#: Cap on cells per target. ``None`` — the default and the only value any DR-2
#: measurement uses — means **every** cell the admission rule admits, so the set
#: is fully determined by the rule and there is no per-target knob to tune a
#: result with. (A uniform cap was considered and rejected: the binding target
#: admits 7 cells at :data:`DRIFT_MIN_ROUTE_M`, so a uniform cap would discard
#: two thirds of the substrate to buy nothing.) The parameter exists so a test
#: can build a small deterministic prefix cheaply.
DRIFT_EPISODES_PER_TARGET: int | None = None

#: Targets. Reused verbatim from v4s (``V4S_TARGETS``) so this set adds ZERO new
#: natural-language surface and ZERO new arrival semantics — the parser, the
#: grounder vocabulary, the relation and the K0 goal builders are all exercised
#: identically to v1-v4s. ``lamp_post_2`` (the far lamppost) admits no cell under
#: rule 1 and is simply never selected; recorded here rather than discovered
#: later.
DRIFT_TARGETS: tuple[V4sTarget, ...] = V4S_TARGETS


@dataclass(frozen=True)
class DriftCell:
    """One admissible (target, start) pair with the evidence for its claims."""

    target: V4sTarget
    start_xy: tuple[float, float]
    yaw_rad: float
    range_m: float
    route_length_m: float


def _admissible_cells(
    target: V4sTarget,
    *,
    starts: tuple[tuple[float, float], ...],
    discs: tuple[tuple[str, float, float, float], ...],
    landmarks: dict[str, dict[str, Any]],
    min_route_m: float,
) -> list[DriftCell]:
    """Every start this target admits, LONGEST ROUTE FIRST.

    The ordering is a difficulty rule fixed at generation time and applied
    uniformly to every target: more travel is more integrated odometry, which is
    the quantity this set exists to stress. It was chosen before any drift arm
    was run and must never be re-ordered against a measured result.
    """

    goal, _radius_m, _label = _v4s_goal_for(target, landmarks)
    landmark = landmarks[target.entity_id]
    position = (float(landmark["position"][0]), float(landmark["position"][1]))
    admitted: list[DriftCell] = []
    for start in starts:
        range_m = math.hypot(position[0] - start[0], position[1] - start[1])
        # Rule 1a: inside the frustum's range (v4s admits only the complement).
        if range_m > VISIBILITY_MAX_RANGE_M:
            continue
        # Rule 2: a clear straight corridor, buildings AND the owner ring.
        if _v4s_segment_blockers(start, position, discs):
            continue
        # Rule 1b: face the target, and let the world's own predicate confirm it.
        yaw = math.atan2(position[1] - start[1], position[0] - start[0])
        if not visible_from_start((start[0], start[1], yaw), position):
            continue
        # Rule 3: a route INTO the scored region, long enough to be travel-heavy.
        route = _v4s_route_length_m(start, goal, discs)
        if route is None or route < min_route_m:
            continue
        admitted.append(
            DriftCell(
                target=target,
                start_xy=start,
                yaw_rad=yaw,
                range_m=range_m,
                route_length_m=route,
            )
        )
    admitted.sort(key=lambda cell: (-cell.route_length_m, cell.start_xy))
    return admitted


def _removed_entity_ids(target_entity_id: str) -> tuple[str, ...]:
    """Every non-building semantic object except the target — removed, and why.

    v4s already removes an instruction's class TWINS ("the tree" must have one
    referent). These cells remove every non-building object instead, and the
    reason is measured, not aesthetic. Under the DEFAULT matcher arm — the
    string/alias ``SigLIP2Matcher`` fallback that every ci_gate arm and every
    frozen row uses — the grounder admits **cross-class** commits:
    ``episodes/V4S_MATCHER_ARM.md`` records a real lamppost accepted for a
    "tree" query, and it is owner decision-queue item 4, an open and owned
    defect. On a first draft of these cells it fired twice in ten episodes: the
    robot committed to a tree 7 m away for "walk towards the streetlight",
    verified arrival there, and produced a ``false_arrival`` — a hard-floor red
    that has nothing whatever to do with pose.

    So the cells make the referent unique in perception. Buildings are KEPT:
    they are the scene's obstacles and the routes are planned around them, and
    hiding an obstacle from perception would change what the run measures in
    the one direction that flatters it.

    Geometry is untouched either way — ``apply_placement_overrides`` filters the
    perception specs only.

    **The set is read from the SCENE ARTIFACT, never from the landmark table.**
    That is not a stylistic preference, it is the fix for a measured defect: the
    landmark table a generator is handed is a *slice* (``V4S_LANDMARK_IDS`` =
    the v2 ids plus the buildings), and ``planter_2`` is in the scene but not in
    that slice. Deriving the removal set from the slice therefore left a second
    planter standing in perception, every ``go next to the planter`` cell
    resolved ``semantic_target_ambiguous`` on tick 1, and the module's own
    "unique in perception" claim was false for a sixth of the substrate. The
    artifact's ``derived`` section is what ``HeadlessCityWorld`` builds its
    perception specs from, so it is the only table that can make the claim true.
    """

    derived = load_artifact()["derived"]
    return tuple(
        entity_id
        for entity_id, entry in sorted(derived.items())
        if entry.get("kind") == "object"
        and entry.get("label") != "building"
        and entity_id != target_entity_id
    )


def _episode_id(cell: DriftCell, index: int, seed: int) -> str:
    digest = hashlib.sha256(
        f"{DRIFT_SET_NAME}|{seed}|{cell.target.entity_id}|"
        f"{cell.start_xy[0]:.6f}|{cell.start_xy[1]:.6f}".encode()
    ).hexdigest()[:8]
    return f"nav-drift-{cell.target.family}-{index:02d}-{digest}"


def _build_episode(
    cell: DriftCell,
    *,
    index: int,
    seed: int,
    landmarks: dict[str, dict[str, Any]],
) -> EpisodeSpec:
    goal, _radius_m, _label = _v4s_goal_for(cell.target, landmarks)
    start_pose = (float(cell.start_xy[0]), float(cell.start_xy[1]), float(cell.yaw_rad))
    placement: dict[str, Any] = {
        # The measured evidence for every claim this cell makes about itself.
        "drift_cell": {
            "set": DRIFT_SET_NAME,
            "target_entity_id": cell.target.entity_id,
            "range_m": round(cell.range_m, 6),
            "route_length_m": round(cell.route_length_m, 6),
            "visible_from_start": True,
            "corridor_blockers": [],
            "min_route_m": DRIFT_MIN_ROUTE_M,
        },
    }
    removed = _removed_entity_ids(cell.target.entity_id)
    if removed:
        placement["remove_entities"] = list(removed)
        placement["drift_cell"]["removed_entities"] = list(removed)
    return EpisodeSpec(
        episode_id=_episode_id(cell, index, seed),
        family=cell.target.family,
        # Not a v1-v4 difficulty tier: these cells are not a family x tier
        # matrix. "D" names the set, and no frozen tier statistic can absorb it.
        tier="D",
        instruction=cell.target.instruction,
        seed=seed,
        start_pose=start_pose,
        goal=goal,
        target_entity_id=cell.target.entity_id,
        shortest_path_m=float(cell.route_length_m),
        # No ADDED distractors: these cells subtract referents, never add them.
        distractors=(),
        placement_overrides=placement,
        synonym=_v4s_synonym(cell.target.instruction),
        absent_target=False,
        notes=f"drift_long_travel|{cell.target.family}|route={cell.route_length_m:.2f}m",
    )


def generate_drift_cells(
    *,
    seed: int = DRIFT_SEED,
    per_target: int | None = DRIFT_EPISODES_PER_TARGET,
    min_route_m: float = DRIFT_MIN_ROUTE_M,
    landmarks: dict[str, dict[str, Any]] | None = None,
) -> tuple[EpisodeSpec, ...]:
    """The DR-2 long-travel substrate — every cell the admission rule admits.

    Round-robin across targets (never target-major), so taking a prefix of the
    result spreads the set over every target instead of exhausting one. Targets
    that admit no cell are simply absent: that is a property of the scene and
    the rule, not a shrink of a pre-registered n.

    ``per_target`` caps each target's contribution. It is ``None`` for every
    measurement; an explicit cap that a target cannot fill RAISES rather than
    silently shrinking, so a small set can never be mistaken for the full one.
    """

    if per_target is not None and per_target < 1:
        raise ValueError("per_target must be >= 1 or None")
    spec = episode_set_spec(EPISODE_SET_V4S)
    if landmarks is None:
        landmarks = landmarks_for(spec)
    discs = _v4s_blocking_discs(landmarks)
    starts = _v4s_start_lattice(discs)
    per_target_cells: list[list[DriftCell]] = []
    for target in DRIFT_TARGETS:
        admitted = _admissible_cells(
            target,
            starts=starts,
            discs=discs,
            landmarks=landmarks,
            min_route_m=min_route_m,
        )
        if not admitted:
            continue
        if per_target is not None:
            if len(admitted) < per_target:
                raise ValueError(
                    f"drift target {target.entity_id!r} yields only "
                    f"{len(admitted)} cells at min_route_m={min_route_m}, below "
                    f"the requested {per_target} — STOP and report, never "
                    "silently shrink"
                )
            admitted = admitted[:per_target]
        per_target_cells.append(admitted)

    episodes: list[EpisodeSpec] = []
    depth = max((len(items) for items in per_target_cells), default=0)
    index = 0
    for position in range(depth):
        for items in per_target_cells:
            if position < len(items):
                episodes.append(
                    _build_episode(
                        items[position], index=index, seed=seed, landmarks=landmarks
                    )
                )
                index += 1
    if not episodes:
        raise ValueError("drift cell generation produced no episodes")
    return tuple(episodes)
