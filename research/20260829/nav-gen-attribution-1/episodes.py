"""NAV-GEN-1 — the episode set, the scene recipe, and the goal geometry.

Pre-registration: ``DESIGN.md`` (FROZEN).  This module builds the two episode
sets the DESIGN names and nothing else; ``run.py`` executes them.

WHAT IS PRODUCT AND WHAT IS HARNESS
-----------------------------------
Product (never modified, only imported): ``DirectiveNavigator`` + the grid
planner + the semantic ladder + ``apply_reactive_safety``, driven through
``HeadlessCityQualityHarness.run(text)``; ``HeadlessCityWorld``;
``evals.nav_instruct.scene_gen.build_scene``.

Harness: this file, ``run.py``, ``analyze.py``, and the per-arm navigation
config trees written under ``~/.cache/parcel-0e/ng1/navcfg/``.  Nothing under
``src/``, ``evals/``, ``configs/`` or any other research folder is touched.

The scene recipe is MA-1's, reused by importing ``model-a-stream-1/teacher.py``
BY PATH and read-only: ``build_scene_path`` (the cached accepted MJCF variant),
``target_geometry`` / ``inside_goal_band`` (the truth oracle), ``TARGETS``,
``prepare_episode`` (the start-pose sampler), ``START_MIN_M`` / ``START_MAX_M``.

Evidence tier: ``desktop-sim``.  No sockets, no subprocess simulator, no hosted
call, no GPU.  The NAV evals' held-out scene is never loaded and never named.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MA1_DIR = REPO / "research" / "20260829" / "model-a-stream-1"
SCRATCH = Path(os.environ.get("NG1_SCRATCH", Path.home() / ".cache/parcel-0e/ng1"))

# The MA-1 recipe writes its scene tree under ``MA1_SCRATCH``; we point it at
# OUR OWN scratch so nothing of MA-1's is written, read-modify-write, or moved.
os.environ.setdefault("MA1_SCRATCH", str(SCRATCH / "ma1recipe"))
os.environ.setdefault("PARCEL_MEMORY_PATH", str(SCRATCH / "scratch_memory.sqlite3"))

# NOTE: MA1_DIR is deliberately NOT put on sys.path — a bare
# ``import run`` would then resolve to MA-1's run.py, not ours.
for _p in (str(REPO / "src"), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def load_ma1_teacher():
    """Import MA-1's ``teacher.py`` by path, read-only, as ``ma1_teacher``."""

    if "ma1_teacher" in sys.modules:
        return sys.modules["ma1_teacher"]
    spec = importlib.util.spec_from_file_location("ma1_teacher", MA1_DIR / "teacher.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ma1_teacher"] = module      # dataclasses need the registration
    spec.loader.exec_module(module)
    return module


T = load_ma1_teacher()

# ===========================================================================
# Seeds.  DISJOINT from MA-1's own ranges (train 770000-770600, dev
# 780000-780060, held 790000-790120), from the reserved foreign block
# (91000-91100) and from ``scene_gen.VAL_UNSEEN_SEEDS`` (91011-91015).
# ===========================================================================

SEED_LO = 880_000
N_SCENES = 30
SCENE_SEEDS: tuple[int, ...] = tuple(range(SEED_LO, SEED_LO + N_SCENES))

#: DESIGN: the five DEMONSTRABLE targets, exactly MA-1's vocabulary.
TARGETS: tuple[str, ...] = tuple(T.TARGETS)

#: >= 2 per (scene, target) is the DESIGN floor; 3 is what we run.
POSES_PER_PAIR = 3

#: The CONTROL set on the frozen demo block.  16 per target reproduces the
#: episode count of MA-1's pre-generation probe (>= 10 is the DESIGN floor).
CONTROL_POSES_PER_TARGET = 16
#: MA-1's probe code is not in the repo (only its numbers, RESULTS.md 2), so
#: the RNG stream is reconstructed, not replayed: the sampler is MA-1's
#: ``prepare_episode`` with this stand-in scene seed for the frozen block.
CONTROL_SCENE_KEY = 0

#: Episode-id bases keep every start-pose RNG stream disjoint.
GEN_EPISODE_BASE = 5_000_000
CONTROL_EPISODE_BASE = 9_000_000


@dataclass(frozen=True)
class Episode:
    episode_id: str
    block: str            # "generated" | "frozen"
    scene_seed: int       # generated seed, or CONTROL_SCENE_KEY on the block
    target: str
    pose_index: int
    rng_episode_id: int   # what MA-1's prepare_episode keys the pose RNG on

    @property
    def directive(self) -> str:
        return f"go to the {self.target}"


def _episode_rng_id(base: int, target: str, k: int) -> int:
    return base + TARGETS.index(target) * 1000 + k


def generated_episodes() -> tuple[Episode, ...]:
    out = []
    for seed in SCENE_SEEDS:
        for target in TARGETS:
            for k in range(POSES_PER_PAIR):
                rid = _episode_rng_id(GEN_EPISODE_BASE, target, k)
                out.append(
                    Episode(
                        episode_id=f"gen:{seed}:{target}:{k}",
                        block="generated",
                        scene_seed=seed,
                        target=target,
                        pose_index=k,
                        rng_episode_id=rid,
                    )
                )
    return tuple(out)


def control_episodes() -> tuple[Episode, ...]:
    out = []
    for target in TARGETS:
        for k in range(CONTROL_POSES_PER_TARGET):
            rid = _episode_rng_id(CONTROL_EPISODE_BASE, target, k)
            out.append(
                Episode(
                    episode_id=f"frozen:{target}:{k}",
                    block="frozen",
                    scene_seed=CONTROL_SCENE_KEY,
                    target=target,
                    pose_index=k,
                    rng_episode_id=rid,
                )
            )
    return tuple(out)


# ===========================================================================
# Worlds.  ``build_scene_path`` is MA-1's cached, byte-stable accepted MJCF.
# ===========================================================================


def scene_path(scene_seed: int) -> Path:
    return T.build_scene_path(scene_seed)


def frozen_scene_path() -> Path:
    from parcel_robot.simulation.headless_city import DEFAULT_CITY_SCENE

    return Path(DEFAULT_CITY_SCENE)


def world_for(block: str, scene_seed: int):
    """A fresh ``HeadlessCityWorld`` for one block/seed."""

    from parcel_robot.simulation.headless_city import HeadlessCityWorld

    path = frozen_scene_path() if block == "frozen" else scene_path(scene_seed)
    return HeadlessCityWorld(scene=path)


def start_pose(world, episode: Episode) -> tuple[float, float, float]:
    """MA-1's own start-pose sampler, unmodified (``prepare_episode``)."""

    script = T.EpisodeScript(
        episode_id=episode.rng_episode_id,
        scene_seed=episode.scene_seed,
        kind=T.KIND_PLAIN,
        target_a=episode.target,
        target_b=episode.target,
    )
    return tuple(T.prepare_episode(world, script).start)


# ===========================================================================
# Goal geometry — the truth oracle and the DTG / band predicates.
#
# ``target_geometry`` returns ((cx, cy), (lo, hi), "object") for bench /
# lamppost / planter and ((cx, cy), (0, 0), "region") for sidewalk / crosswalk;
# a region's band is its POLYGON, so DTG for a region is polygon distance and
# the band radius is its area-equivalent radius.
# ===========================================================================


def region_polygon(world, target: str):
    for item in world._region_specs:
        if str(item["label"]) == target:
            return [(float(x), float(y)) for x, y in item["polygon"]]
    return None


def _point_segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    t = 0.0 if den <= 0.0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / den))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _polygon_area(poly) -> float:
    a = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def _point_in_polygon(px, py, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            xint = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < xint:
                inside = not inside
    return inside


@dataclass(frozen=True)
class GoalGeometry:
    target: str
    kind: str                       # "object" | "region"
    centre: tuple[float, float]
    band: tuple[float, float]       # object annulus (lo, hi); (0,0) for regions
    polygon: tuple                  # region polygon, () for objects
    band_radius_m: float            # the characteristic radius; see below

    def distance_to_band(self, x: float, y: float) -> float:
        """DTG: metres from (x, y) to the nearest point of the STRICT band."""

        if self.kind == "object":
            d = math.hypot(x - self.centre[0], y - self.centre[1])
            lo, hi = self.band
            if d < lo:
                return lo - d
            if d > hi:
                return d - hi
            return 0.0
        poly = self.polygon
        if not poly:
            return float("inf")
        if _point_in_polygon(x, y, poly):
            return 0.0
        n = len(poly)
        return min(
            _point_segment_distance(x, y, poly[i][0], poly[i][1],
                                    poly[(i + 1) % n][0], poly[(i + 1) % n][1])
            for i in range(n)
        )

    def inside_two_x_band(self, x: float, y: float) -> bool:
        """DESIGN's "inside 2x the goal band".

        Doubling a band about its own goal means adding one band radius to its
        outer edge, so the uniform predicate over both goal kinds is
        ``DTG <= band_radius_m``: for an object that is exactly the doubled
        vicinity radius (``2 * hi``), for a region the polygon dilated by its
        own area-equivalent radius.
        """

        return self.distance_to_band(x, y) <= self.band_radius_m + 1e-9


def goal_geometry(world, target: str) -> GoalGeometry | None:
    geo = T.target_geometry(world, target)
    if geo is None:
        return None
    (cx, cy), (lo, hi), kind = geo
    if kind == "object":
        return GoalGeometry(target, "object", (cx, cy), (lo, hi), (),
                            band_radius_m=float(hi))
    poly = region_polygon(world, target) or []
    r_eq = math.sqrt(_polygon_area(poly) / math.pi) if len(poly) >= 3 else 0.0
    return GoalGeometry(target, "region", (cx, cy), (0.0, 0.0), tuple(poly),
                        band_radius_m=float(r_eq))


def instances(world, target: str):
    """EVERY scene entity that carries the requested LABEL, with its band.

    MA-1's truth oracle scores an object goal against ONE hardcoded id
    (``bench_1`` / ``lamp_post_1`` / ``planter_1``), so a robot that correctly
    walks to ``planter_2`` is scored as a failure.  This function is what lets
    the results carry the fairer "any legal instance" oracle beside MA-1's, and
    it is also the authority for WRONG INSTANCE: a resolved ``target_id`` that
    is not one of these ids did not come from the scene at all.
    """

    out = []
    for item in world._object_specs:
        if str(item.get("label")) != target:
            continue
        meta = dict(item.get("metadata") or {})
        region = dict(meta.get("goal_region") or {})
        band = region.get("band_m") or (0.0, float(meta.get("vicinity_radius_m", 1.2)))
        out.append((str(item["id"]), GoalGeometry(
            target, "object",
            (float(item["position"][0]), float(item["position"][1])),
            (float(band[0]), float(band[1])), (), band_radius_m=float(band[1]))))
    for item in world._region_specs:
        if str(item.get("label")) != target:
            continue
        poly = [(float(x), float(y)) for x, y in item["polygon"]]
        if len(poly) < 3:
            continue
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        r_eq = math.sqrt(_polygon_area(poly) / math.pi)
        out.append((str(item["id"]), GoalGeometry(target, "region", (cx, cy),
                                                  (0.0, 0.0), tuple(poly),
                                                  band_radius_m=r_eq)))
    return out


def inside_any_instance(insts, x: float, y: float) -> bool:
    for _entity_id, geo in insts:
        if geo.distance_to_band(x, y) <= 1e-9:
            return True
    return False


def band_sample_points(geo: GoalGeometry, n: int = 72):
    """Points the robot could legally STAND on to satisfy the strict band."""

    if geo.kind == "object":
        cx, cy = geo.centre
        lo, hi = geo.band
        radii = [lo + (hi - lo) * f for f in (0.0, 0.25, 0.5, 0.75, 1.0)]
        return [
            (cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
            for r in radii
            for i in range(n)
        ]
    poly = geo.polygon
    if not poly:
        return []
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    step = 0.15
    pts = []
    x = min(xs)
    while x <= max(xs):
        y = min(ys)
        while y <= max(ys):
            if _point_in_polygon(x, y, poly):
                pts.append((x, y))
            y += step
        x += step
    return pts or [geo.centre]


def goal_clearance_stats(world, geo: GoalGeometry) -> dict:
    """Truth clearance available inside the goal band.

    ``truth_minimum_clearance`` is a SIGNED BODY-SURFACE clearance (the robot
    radius is already subtracted), so a band point is passable to the grid
    planner exactly when its clearance is >= that planner's
    ``map_safety_margin_m``, and the reactive gate will drive there only when
    it is >= ``obstacle_stop_m``.  That single mapping is why this row can say
    which arms could possibly reach a goal at all.
    """

    pts = band_sample_points(geo)
    vals = [world.truth_minimum_clearance(px, py) for px, py in pts]
    vals = [v for v in vals if math.isfinite(v)]
    if not vals:
        return {"band_points": 0, "band_clearance_max_m": None,
                "band_clearance_median_m": None, "goal_nearest_obstacle_m": None}
    vals.sort()
    cx, cy = geo.centre
    return {
        "band_points": len(vals),
        "band_clearance_max_m": round(vals[-1], 4),
        "band_clearance_median_m": round(vals[len(vals) // 2], 4),
        "goal_nearest_obstacle_m": round(world.truth_minimum_clearance(cx, cy), 4),
        "band_clearance_sorted": [round(v, 4) for v in vals],
    }


# ===========================================================================
# Scene facts: obstacle density from the generator's own params, plus an
# empirical blocked-fraction over the start-sampling rectangle.
# ===========================================================================

#: MA-1's start rectangle (``prepare_episode``), reused as the density window.
DENSITY_X = (-6.6, 6.6)
DENSITY_Y = (-3.0, 1.6)


def scene_params(scene_seed: int) -> dict:
    """The generator's own accepted ``SceneParams`` for this seed."""

    from evals.nav_instruct.scene_gen import build_scene

    # The generated MJCF includes ``../../../third_party``, so the proposal
    # must be written in the tree MA-1's ``ensure_scene_tree`` symlinks — the
    # same directory ``build_scene_path`` caches into.
    T.ensure_scene_tree()
    params, _xml, derived, _rec = build_scene(scene_seed, scratch_dir=T.SCENE_DIR)
    d = params.as_dict()
    buildings = d["buildings"]
    area = sum(4.0 * b[2] * b[3] for b in buildings)
    corridor = abs(d["north_y"] - d["south_y"]) * (DENSITY_X[1] - DENSITY_X[0])
    return {
        "n_buildings": len(buildings),
        "building_footprint_m2": round(area, 3),
        "corridor_area_m2": round(corridor, 3),
        "params_obstacle_density": round(area / corridor, 5) if corridor > 0 else None,
        "north_y": d["north_y"], "south_y": d["south_y"],
        "n_derived_entities": len(derived.get("entities", []) or []) if isinstance(derived, dict) else None,
    }


def empirical_density(world, step: float = 0.2) -> dict:
    """Fraction of the start rectangle where the BODY does not fit."""

    blocked = tight = total = 0
    x = DENSITY_X[0]
    while x <= DENSITY_X[1]:
        y = DENSITY_Y[0]
        while y <= DENSITY_Y[1]:
            c = world.truth_minimum_clearance(x, y)
            total += 1
            if c < 0.0:
                blocked += 1
            if math.isfinite(c) and c < 0.65:
                tight += 1
            y += step
        x += step
    return {
        "grid_points": total,
        "blocked_fraction": round(blocked / total, 5) if total else None,
        "inside_stop_band_fraction": round(tight / total, 5) if total else None,
    }


def scene_manifest(seeds=SCENE_SEEDS) -> dict:
    rows = []
    for s in seeds:
        p = scene_path(s)
        rows.append({"seed": s, "file": p.name,
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    blob = json.dumps(rows, sort_keys=True).encode()
    return {"scenes": rows, "n": len(rows),
            "manifest_sha256": hashlib.sha256(blob).hexdigest()}


def summary() -> dict:
    gen = generated_episodes()
    ctl = control_episodes()
    return {
        "scene_seeds": [SCENE_SEEDS[0], SCENE_SEEDS[-1]],
        "n_scenes": len(SCENE_SEEDS),
        "targets": list(TARGETS),
        "poses_per_pair": POSES_PER_PAIR,
        "generated_episodes": len(gen),
        "control_poses_per_target": CONTROL_POSES_PER_TARGET,
        "control_episodes": len(ctl),
        "disjoint_from": {
            "ma1_train": list(T.SEED_TRAIN), "ma1_dev": list(T.SEED_DEV),
            "ma1_held": list(T.SEED_HELD), "reserved_foreign": [91_000, 91_100],
        },
    }


if __name__ == "__main__":
    print(json.dumps(summary(), indent=2))
