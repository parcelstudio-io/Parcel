"""Seeded episode generator for NAV_INSTRUCT_V1 (pure; no runtime imports).

Families × tiers A–E. Deterministic: same seed → byte-identical episode set.
Counts: ≥20 episodes per family (spread across tiers).
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from parcel_robot.instructnav.scoring import GoalRegion

FAMILIES: tuple[str, ...] = (
    "region_goal",
    "object_goal",
    "object_relative",
    "follow_owner",
    "circle_owner",
)

TIERS: tuple[str, ...] = ("A", "B", "C", "D", "E")

# Canonical city landmarks (match city_block.xml nominal poses).
_LANDMARKS: dict[str, dict[str, Any]] = {
    "sidewalk": {
        "kind": "region",
        "label": "sidewalk",
        "polygon": ((-8.0, 2.4), (8.0, 2.4), (8.0, 3.6), (-8.0, 3.6)),
    },
    "sidewalk_south": {
        "kind": "region",
        "label": "sidewalk",
        "polygon": ((-8.0, -3.6), (8.0, -3.6), (8.0, -2.4), (-8.0, -2.4)),
    },
    "crosswalk": {
        "kind": "region",
        "label": "crosswalk",
        "polygon": ((2.3, -0.4), (3.9, -0.4), (3.9, 2.0), (2.3, 2.0)),
    },
    "lamp_post_1": {
        "kind": "object",
        "label": "lamppost",
        "position": (0.2, 3.15),
        "radius_m": 0.06,
    },
    "lamp_post_2": {
        "kind": "object",
        "label": "lamppost",
        "position": (-6.7, -2.9),
        "radius_m": 0.06,
    },
    "bench_1": {
        "kind": "object",
        "label": "bench",
        "position": (-2.5, 3.0),
        "radius_m": 0.7,
    },
    "tree_1": {
        "kind": "object",
        "label": "tree",
        "position": (-5.0, 3.15),
        "radius_m": 0.45,
    },
    "planter_1": {
        "kind": "object",
        "label": "planter",
        "position": (-5.0, 3.15),
        "radius_m": 0.45,
    },
    "bldg_1": {
        "kind": "object",
        "label": "building",
        "position": (-4.5, 5.5),
        "radius_m": 1.8,
    },
}

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
) -> tuple[EpisodeSpec, ...]:
    """Build the full seeded matrix (≥20/family × tiers A–E)."""

    if per_family < EPISODES_PER_FAMILY_MIN:
        raise ValueError(f"per_family must be ≥ {EPISODES_PER_FAMILY_MIN}")
    rng = _SeedSeq(seed)
    episodes: list[EpisodeSpec] = []
    for family in FAMILIES:
        family_eps = _generate_family(family, per_family=per_family, rng=rng)
        episodes.extend(family_eps)
    return tuple(episodes)


def generate_minival(*, seed: int = 20260804, count: int = 25) -> tuple[EpisodeSpec, ...]:
    """Frozen 25-episode CI minival: one cell from each family×tier slice."""

    full = generate_episode_matrix(seed=seed, per_family=25)
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
) -> list[Path]:
    """Emit one JSON file per episode; returns written paths."""

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
    manifest = {
        "count": len(episodes),
        "episode_ids": [ep.episode_id for ep in episodes],
        "sha256": _matrix_digest(episodes),
    }
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
) -> EpisodeSpec:
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
        target_id, goal = _region_goal(instruction, tier=tier, absent=absent)
        if "pavement" in instruction:
            synonym = "pavement"
    elif family == "object_goal":
        target_id, goal = _object_goal(instruction, tier=tier, absent=absent)
        if "streetlight" in instruction or "lamp post" in instruction:
            synonym = "streetlight" if "streetlight" in instruction else "lamp post"
    elif family == "object_relative":
        target_id, goal = _relative_goal(instruction, tier=tier, absent=absent)
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

    shortest = _approx_shortest_path_m(start_pose[:2], goal)
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
) -> tuple[str, GoalRegion]:
    if "crosswalk" in instruction:
        landmark = _LANDMARKS["crosswalk"]
        entity_id = "crosswalk"
    else:
        landmark = _LANDMARKS["sidewalk" if tier != "C" else "sidewalk_south"]
        entity_id = "sidewalk" if tier != "C" else "sidewalk_south"
    polygon = landmark["polygon"]
    if absent:
        # Unreachable: empty/off-map disc the agent should not invent.
        return entity_id, GoalRegion(kind="disc", center=(40.0, 40.0), radius_m=0.5)
    return entity_id, GoalRegion(kind="polygon", polygon=polygon)


def _object_goal(
    instruction: str,
    *,
    tier: str,
    absent: bool,
) -> tuple[str, GoalRegion]:
    if "tree" in instruction:
        entity_id = "tree_1"
        landmark = _LANDMARKS["tree_1"]
    else:
        entity_id = "lamp_post_2" if tier == "C" else "lamp_post_1"
        landmark = _LANDMARKS[entity_id]
    pos = landmark["position"]
    radius = float(landmark["radius_m"]) + 1.4  # vicinity / stop-short envelope
    if "towards" in instruction:
        # Towards: stop-short disc around target.
        radius = max(1.0, radius)
    if absent:
        return entity_id, GoalRegion(kind="disc", center=(40.0, 40.0), radius_m=0.5)
    return entity_id, GoalRegion(kind="disc", center=pos, radius_m=radius)


def _relative_goal(
    instruction: str,
    *,
    tier: str,
    absent: bool,
) -> tuple[str, GoalRegion]:
    if "planter" in instruction:
        entity_id = "planter_1"
        landmark = _LANDMARKS["planter_1"]
    else:
        entity_id = "bench_1"
        landmark = _LANDMARKS["bench_1"]
    pos = landmark["position"]
    footprint = float(landmark["radius_m"]) * 0.5
    if absent:
        return entity_id, GoalRegion(
            kind="relative_band",
            center=(40.0, 40.0),
            band_m=(0.4, 1.5),
            anchor_entity=entity_id,
            anchor_footprint_m=0.3,
        )
    return entity_id, GoalRegion(
        kind="relative_band",
        center=pos,
        band_m=(0.4, 1.5),
        anchor_entity=entity_id,
        anchor_footprint_m=footprint,
    )


def _approx_shortest_path_m(
    start: tuple[float, float],
    goal: GoalRegion,
) -> float:
    """Grid A* path length to the nearest admissible goal sample (pure).

    Obstacles are the building footprint from the landmark table. When A*
    finds no path, fall back to Euclidean distance-to-region (admissible
    lower bound) without claiming a grid path.
    """

    target = _goal_sample_point(start, goal)
    if target is None:
        return 0.0
    grid_len = _grid_astar_length_m(start, target)
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
) -> float | None:
    """4-connected A* on a free grid with the building footprint blocked."""

    min_x, min_y, max_x, max_y = bounds
    res = resolution_m
    blocked = _blocked_cells(res)
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


def _blocked_cells(resolution_m: float) -> set[tuple[int, int]]:
    """Block the building landmark footprint on the generator grid."""

    building = _LANDMARKS["bldg_1"]
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
