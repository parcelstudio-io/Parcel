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

from evals.nav_instruct.scene_truth import derived_landmark_table, landmark_table
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
#: Bridge-only intermediate: correction (a) with the v1 spec logic. Never run,
#: never frozen — it exists so a moved goal can be attributed to (a) or to (b).
EPISODE_SET_V1A = "v1a-scene-truth-only"

DEFAULT_EPISODE_SET_VERSION = EPISODE_SET_V1

#: The frozen v1 digest. Any change to this module that moves it is a bug.
FROZEN_V1_MINIVAL_DIGEST = (
    "cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf"
)

#: The observation frustum the *world* reports through — the defaults of
#: ``parcel_robot.city_semantics.visible_city_semantics``. They are repeated
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
}


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
        goal = GoalRegion(kind="disc", center=(2.0, -0.5), radius_m=1.8)
        if tier in {"C", "D", "E"}:
            placement["owner_path"] = "corner_occlusion" if tier != "E" else "absent"
            absent = tier == "E"
    else:  # circle_owner
        target_id = "owner"
        goal = GoalRegion(kind="disc", center=(2.0, -0.5), radius_m=2.2)
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
