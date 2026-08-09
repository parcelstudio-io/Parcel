"""Procedural city-block scene generator for the val_unseen split (instrument 1).

Why
---
NAV_INSTRUCT has always been measured on **one** scene. Every number it has ever
produced is therefore a number about ``city_block.xml``, and nothing in the repo
can tell the difference between "the stack navigates" and "the stack has
memorised a 16 m block". The scene-generalization split is the instrument that
separates them: the same episode logic, the same instructions, the same start
poses, run against scenes nobody tuned against.

What it generates
-----------------
Block *variants*, not new worlds. Same vocabulary, same entity ids, same
geom-name prefixes — so the semantics sidecar, the extraction path, the episode
generator and the scorer all work unchanged. What moves is geometry: sidewalk
offsets and widths, crosswalk placement, building rows, and where the furniture
sits on the pavement.

Acceptance (ProcTHOR-style rejection sampling)
----------------------------------------------
A proposal is written, **derived** (:func:`scene_truth.derive_scene_truth` over
the real MJCF — the generator never asserts geometry it did not read back), and
then must survive four filters or it is rejected and re-seeded:

1. **round-trip** — the derived table must agree with what the sampler wrote.
   A generator that cannot predict its own scene has no business filtering it.
2. **overlap** — furniture footprints disjoint with a margin, no furniture
   inside a building, buildings disjoint from each other and off the pavement.
   Buildings are tested as their **boxes**, not as bounding circles: a facade
   row is meant to sit shoulder to shoulder, and a circle test would reject the
   frozen city block itself.
3. **support** — every object that should be on a pavement is inside its
   sidewalk polygon, because ``city_semantics`` derives ``support_label`` from
   that containment and an object floating on the road changes what the episode
   means.
4. **navigability** — a 4-connected A* on a grid inflated by the **robot
   profile's** footprint radius plus the terminal clearance must reach every
   landmark's stand-off band from every episode start pose. A scene with an
   unreachable goal measures the sampler, not the robot.

Every accepted scene is emitted as **one artifact with three files**: the MJCF,
its semantics sidecar (re-emitted from the city-block sidecar with the scene
path swapped — the vocabulary is copied from the source of truth, never
retyped, and validated by the real loader before it is written), and its
derived scene-truth manifest with the acceptance record.

These scenes are **frozen and never tuned against**. Regenerating from the same
seeds reproduces them byte for byte; ``--check`` and a test assert it.

Usage::

    .parcel/bin/python -m evals.nav_instruct.scene_gen --emit
    .parcel/bin/python -m evals.nav_instruct.scene_gen --check
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "configs" / "scenes" / "generated"
SOURCE_SIDECAR = REPO_ROOT / "configs" / "scenes" / "city_block.semantics.yaml"

#: The five frozen val_unseen seeds. Chosen once, never re-rolled to chase a
#: number: changing them is changing the benchmark.
VAL_UNSEEN_SEEDS: tuple[int, ...] = (91011, 91012, 91013, 91014, 91015)

SPLIT_NAME = "val_unseen"

#: Clearance the navigability filter plans with — derived from the robot
#: profile, never a literal. 0.32 m is the same ``terminal_clearance_m`` that
#: ``city_semantics._region_metadata`` gives a region goal.
ROBOT_CLEARANCE_M = DEFAULT_ROBOT_PROFILE.footprint_radius_m + 0.32

#: Grid the navigability filter runs on. 0.25 m is half the episode generator's
#: own A* resolution, so a corridor this filter accepts is not one the
#: generator's shortest-path estimate will miss.
NAV_GRID_M = 0.25
NAV_BOUNDS = (-9.0, -9.0, 9.0, 9.0)

#: Start poses every generated scene must be navigable from — the exact tier
#: A–D starts ``generator._TIER_STARTS`` uses (tier E targets are absent by
#: construction and have nothing to reach).
REQUIRED_START_XY: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (1.0, 0.5),
    (-1.0, 0.0),
    (0.5, 0.2),
    (-0.5, -0.2),
    (6.0, -6.0),
    (-6.0, -6.0),
    (7.0, 0.0),
    (1.5, -1.0),
    (-1.5, 0.5),
)

#: The landmark ids a generated scene must supply for the v2 episode pack to be
#: buildable against it. Same ids as ``scene_truth.V2_LANDMARK_IDS``, which is
#: asserted by ``tests/test_nav_instruct_scene_gen.py`` rather than assumed.
V2_SCENE_TRUTH_IDS: tuple[str, ...] = (
    "sidewalk",
    "sidewalk_south",
    "crosswalk",
    "lamp_post_1",
    "lamp_post_2",
    "bench_1",
    "tree_1",
    "planter_1",
    "bldg_1",
    "tree_2",
)

#: Landmarks every accepted scene must expose and every start pose must reach.
REQUIRED_LANDMARKS: tuple[str, ...] = (
    "sidewalk",
    "sidewalk_south",
    "crosswalk",
    "lamp_post_1",
    "lamp_post_2",
    "bench_1",
    "tree_1",
    "tree_2",
    "planter_1",
)

MAX_PROPOSALS_PER_SEED = 400

#: Position tolerance for the round-trip filter. The MJCF carries 3 decimals.
ROUND_TRIP_TOL_M = 1e-3


class SceneRejected(ValueError):
    """A proposal that failed a filter. Always names which one."""


@dataclass(frozen=True)
class SceneParams:
    """Everything the sampler chooses. Reading this is reading the variation.

    Buildings are ``(x, y, half_x, half_y)`` boxes.
    """

    seed: int
    north_y: float
    north_half_width: float
    south_y: float
    south_half_width: float
    crosswalk_x0: float
    crosswalk_y: float
    crosswalk_half_height: float
    buildings: tuple[tuple[float, float, float, float], ...]
    lamp_post_1_x: float
    lamp_post_2_x: float
    bench_x: float
    tree_1_x: float
    tree_2_x: float
    owner_xy: tuple[float, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "north_y": self.north_y,
            "north_half_width": self.north_half_width,
            "south_y": self.south_y,
            "south_half_width": self.south_half_width,
            "crosswalk_x0": self.crosswalk_x0,
            "crosswalk_y": self.crosswalk_y,
            "crosswalk_half_height": self.crosswalk_half_height,
            "buildings": [list(item) for item in self.buildings],
            "lamp_post_1_x": self.lamp_post_1_x,
            "lamp_post_2_x": self.lamp_post_2_x,
            "bench_x": self.bench_x,
            "tree_1_x": self.tree_1_x,
            "tree_2_x": self.tree_2_x,
            "owner_xy": list(self.owner_xy),
        }


@dataclass
class AcceptanceRecord:
    """How hard the sampler had to work, and which filter did the rejecting."""

    proposals_tried: int = 0
    rejections: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        key = reason.split(":")[0]
        self.rejections[key] = self.rejections.get(key, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "proposals_tried": self.proposals_tried,
            "rejections_by_filter": dict(sorted(self.rejections.items())),
        }


def _round(value: float, places: int = 3) -> float:
    return round(float(value), places)


def sample_params(seed: int, attempt: int) -> SceneParams:
    """One proposal. Deterministic in ``(seed, attempt)`` and in nothing else."""

    rng = random.Random(f"{SPLIT_NAME}:{seed}:{attempt}")
    north_y = _round(rng.uniform(2.7, 4.1))
    north_half = _round(rng.uniform(0.85, 1.35))
    south_y = _round(rng.uniform(-4.1, -2.7))
    south_half = _round(rng.uniform(0.7, 1.2))
    north_row_y = north_y + north_half
    south_row_y = south_y - south_half
    buildings: list[tuple[float, float, float, float]] = []
    # Facade slots with bounded jitter. Slot spacing minus jitter exceeds the
    # widest pair of half-extents, so the box-disjointness filter is satisfiable
    # rather than a lottery; the filter still has the last word.
    for slot_x in (-6.0, -2.0, 2.0, 6.0):
        half_x = _round(rng.uniform(1.1, 1.5))
        half_y = _round(rng.uniform(1.1, 1.6))
        buildings.append(
            (
                _round(slot_x + rng.uniform(-0.3, 0.3)),
                _round(north_row_y + half_y + rng.uniform(0.6, 1.4)),
                half_x,
                half_y,
            )
        )
    # South facades stay clear of the tier-C start poses at (+-6, -6): a start
    # pose inside a building is a sampler defect, not a hard episode.
    for slot_x in (-2.5, 2.5):
        half_x = _round(rng.uniform(1.2, 1.6))
        half_y = _round(rng.uniform(1.2, 1.6))
        buildings.append(
            (
                _round(slot_x + rng.uniform(-0.4, 0.4)),
                _round(south_row_y - half_y - rng.uniform(0.6, 1.4)),
                half_x,
                half_y,
            )
        )
    return SceneParams(
        seed=seed,
        north_y=north_y,
        north_half_width=north_half,
        south_y=south_y,
        south_half_width=south_half,
        crosswalk_x0=_round(rng.uniform(-3.5, 3.0)),
        crosswalk_y=_round(rng.uniform(0.3, 1.0)),
        crosswalk_half_height=_round(rng.uniform(0.9, 1.4)),
        buildings=tuple(buildings),
        lamp_post_1_x=_round(rng.uniform(-1.0, 1.6)),
        lamp_post_2_x=_round(rng.uniform(-7.0, -5.0)),
        bench_x=_round(rng.uniform(-4.2, -2.8)),
        tree_1_x=_round(rng.uniform(-7.2, -6.0)),
        tree_2_x=_round(rng.uniform(4.4, 6.6)),
        owner_xy=(_round(rng.uniform(1.2, 2.8)), _round(rng.uniform(-1.4, -0.2))),
    )


# ---------------------------------------------------------------------------
# MJCF emission
# ---------------------------------------------------------------------------


def _geom(name: str, kind: str, pos: tuple[float, float, float], size: str, tail: str) -> str:
    return (
        f'    <geom name="{name}" type="{kind}" '
        f'pos="{pos[0]} {pos[1]} {pos[2]}" size="{size}" {tail}/>'
    )


_PREAMBLE: tuple[str, ...] = (
    '  <include file="../../../third_party/unitree_mujoco/unitree_robots/go2/go2.xml"/>',
    '  <compiler meshdir="../../../third_party/unitree_mujoco/unitree_robots/go2/assets"',
    '    angle="radian" autolimits="true"/>',
    '  <statistic center="0 0 0.4" extent="8"/>',
    "  <visual>",
    '    <headlight diffuse="0.6 0.6 0.6" ambient="0.35 0.35 0.35" specular="0 0 0"/>',
    '    <rgba haze="0.45 0.5 0.55 1"/>',
    '    <global azimuth="-140" elevation="-18"/>',
    "  </visual>",
    "  <asset>",
    '    <texture type="skybox" builtin="gradient" rgb1="0.45 0.62 0.82"',
    '      rgb2="0.08 0.12 0.18" width="512" height="3072"/>',
    '    <texture type="2d" name="asphalt" builtin="checker" mark="edge"',
    '      rgb1="0.22 0.22 0.24" rgb2="0.18 0.18 0.2" markrgb="0.3 0.3 0.32"',
    '      width="256" height="256"/>',
    '    <texture type="2d" name="sidewalk" builtin="flat" rgb1="0.55 0.55 0.52"',
    '      width="128" height="128"/>',
    '    <material name="asphalt" texture="asphalt" texuniform="true"',
    '      texrepeat="8 8" reflectance="0.05"/>',
    '    <material name="sidewalk" texture="sidewalk" reflectance="0.08"/>',
    '    <material name="building_a" rgba="0.62 0.58 0.52 1"/>',
    '    <material name="building_b" rgba="0.45 0.5 0.55 1"/>',
    '    <material name="building_c" rgba="0.7 0.68 0.64 1"/>',
    '    <material name="crosswalk" rgba="0.92 0.92 0.9 1"/>',
    '    <material name="bench" rgba="0.35 0.28 0.2 1"/>',
    '    <material name="city_grass" rgba="0.22 0.42 0.2 1"/>',
    '    <material name="city_metal" rgba="0.16 0.18 0.2 1"/>',
    "  </asset>",
    "  <worldbody>",
    '    <light pos="2 1 6" dir="-0.2 -0.1 -1" diffuse="0.8 0.8 0.75" castshadow="true"/>',
    '    <light pos="-3 -2 5" dir="0.3 0.2 -1" diffuse="0.35 0.35 0.4"/>',
)

_BUILDING_MATERIALS: tuple[str, ...] = (
    "building_a",
    "building_b",
    "building_c",
    "building_a",
    "building_b",
    "building_c",
)


def scene_xml(params: SceneParams, *, scene_id: str) -> str:
    """The MJCF for one proposal. Same prefixes and ids as the frozen block."""

    p = params
    lines: list[str] = [f'<mujoco model="parcel_{scene_id}">']
    lines.append(
        f"  <!-- GENERATED by evals/nav_instruct/scene_gen.py, seed {p.seed}."
        " Do not hand-edit. -->"
    )
    lines.extend(_PREAMBLE)
    lines.append(
        '    <geom name="road" type="plane" size="12 12 0.05" material="asphalt" friction="0.9"/>'
    )
    lines.append(
        _geom(
            "sidewalk",
            "box",
            (0.0, p.north_y, 0.06),
            f"8 {p.north_half_width} 0.06",
            'material="sidewalk"',
        )
    )
    lines.append(
        _geom(
            "sidewalk_south",
            "box",
            (0.0, p.south_y, 0.06),
            f"8 {p.south_half_width} 0.06",
            'material="sidewalk"',
        )
    )
    for index in range(4):
        lines.append(
            _geom(
                f"xw{index + 1}",
                "box",
                (_round(p.crosswalk_x0 + 0.4 * index), p.crosswalk_y, 0.002),
                f"0.15 {p.crosswalk_half_height} 0.002",
                'material="crosswalk"',
            )
        )
    for index, (bx, by, half_x, half_y) in enumerate(p.buildings, start=1):
        lines.append(
            _geom(
                f"bldg_{index}",
                "box",
                (bx, by, 2.0),
                f"{half_x} {half_y} 2.0",
                f'material="{_BUILDING_MATERIALS[(index - 1) % len(_BUILDING_MATERIALS)]}"',
            )
        )
    for suffix, tree_x in ((1, p.tree_1_x), (2, p.tree_2_x)):
        lines.append(
            _geom(
                f"planter_{suffix}",
                "cylinder",
                (tree_x, p.north_y, 0.18),
                "0.45 0.18",
                'material="city_grass"',
            )
        )
        lines.append(
            _geom(
                f"tree_{suffix}",
                "cylinder",
                (tree_x, p.north_y, 0.9),
                "0.10 0.75",
                'rgba="0.32 0.2 0.1 1"',
            )
        )
        lines.append(
            _geom(
                f"tree_top_{suffix}",
                "sphere",
                (tree_x, p.north_y, 1.85),
                "0.58",
                'rgba="0.18 0.48 0.19 1"',
            )
        )
    lines.append(
        _geom(
            "lamp_post_1",
            "cylinder",
            (p.lamp_post_1_x, p.north_y, 1.35),
            "0.06 1.35",
            'material="city_metal"',
        )
    )
    lines.append(
        _geom(
            "lamp_post_2",
            "cylinder",
            (p.lamp_post_2_x, p.south_y, 1.35),
            "0.06 1.35",
            'material="city_metal"',
        )
    )
    lines.append(
        _geom(
            "bench_seat",
            "box",
            (p.bench_x, p.north_y, 0.28),
            "0.7 0.22 0.06",
            'material="bench"',
        )
    )
    lines.append(
        _geom(
            "bench_back",
            "box",
            (p.bench_x, _round(p.north_y + 0.18), 0.42),
            "0.7 0.05 0.18",
            'material="bench"',
        )
    )
    lines.append(f'    <body name="owner" mocap="true" pos="{p.owner_xy[0]} {p.owner_xy[1]} 0">')
    lines.append('      <geom name="owner_body" type="capsule" fromto="0 0 0.1 0 0 1.55"')
    lines.append('        size="0.22" contype="0" conaffinity="0" rgba="0.15 0.68 0.95 1"/>')
    lines.append('      <geom name="owner_head" type="sphere" pos="0 0 1.78" size="0.2"')
    lines.append('        contype="0" conaffinity="0" rgba="0.92 0.72 0.55 1"/>')
    lines.append("    </body>")
    lines.append("  </worldbody>")
    lines.append("</mujoco>")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# acceptance filters
# ---------------------------------------------------------------------------


def _furniture(derived: dict[str, dict[str, Any]]) -> dict[str, tuple[float, float, float]]:
    """Non-building objects as ``(x, y, radius)``."""

    return {
        key: (entry["position"][0], entry["position"][1], float(entry["radius_m"]))
        for key, entry in derived.items()
        if entry.get("kind") == "object" and entry.get("label") != "building"
    }


def _polygon_bounds(polygon: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _boxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    *,
    margin_m: float,
) -> bool:
    return (
        abs(a[0] - b[0]) < a[2] + b[2] + margin_m
        and abs(a[1] - b[1]) < a[3] + b[3] + margin_m
    )


def _point_in_box(
    point: tuple[float, float],
    box: tuple[float, float, float, float],
    *,
    inflate_m: float,
) -> bool:
    return (
        abs(point[0] - box[0]) <= box[2] + inflate_m
        and abs(point[1] - box[1]) <= box[3] + inflate_m
    )


def check_round_trip(params: SceneParams, derived: dict[str, dict[str, Any]]) -> None:
    """The derived table must agree with what the sampler wrote."""

    expected = {
        "tree_1": (params.tree_1_x, params.north_y),
        "tree_2": (params.tree_2_x, params.north_y),
        "planter_1": (params.tree_1_x, params.north_y),
        "lamp_post_1": (params.lamp_post_1_x, params.north_y),
        "lamp_post_2": (params.lamp_post_2_x, params.south_y),
    }
    for entity_id, (x, y) in expected.items():
        entry = derived.get(entity_id)
        if entry is None:
            raise SceneRejected(f"round_trip: {entity_id} did not survive extraction")
        got = entry["position"]
        if abs(got[0] - x) > ROUND_TRIP_TOL_M or abs(got[1] - y) > ROUND_TRIP_TOL_M:
            raise SceneRejected(
                f"round_trip: {entity_id} extracted at {got}, sampler wrote ({x}, {y})"
            )


def check_overlap(
    params: SceneParams,
    derived: dict[str, dict[str, Any]],
    *,
    margin_m: float = 0.35,
) -> None:
    """Footprints must be disjoint, and no furniture may sit inside a building."""

    furniture = _furniture(derived)
    keys = sorted(furniture)
    for index, a in enumerate(keys):
        ax, ay, ar = furniture[a]
        for b in keys[index + 1 :]:
            bx, by, br = furniture[b]
            # tree_N and planter_N are co-located by design — the frozen block
            # does the same and the semantics sidecar documents it.
            if a.rsplit("_", 1)[-1] == b.rsplit("_", 1)[-1] and {
                a.rsplit("_", 1)[0],
                b.rsplit("_", 1)[0],
            } == {"tree", "planter"}:
                continue
            gap = math.hypot(ax - bx, ay - by)
            if gap < ar + br + margin_m:
                raise SceneRejected(f"overlap: {a} and {b} are {gap:.2f} m apart")

    for index, box_a in enumerate(params.buildings):
        for box_b in params.buildings[index + 1 :]:
            if _boxes_overlap(box_a, box_b, margin_m=0.2):
                raise SceneRejected(f"overlap: buildings {box_a} and {box_b} intersect")
        for name, (fx, fy, radius) in furniture.items():
            if _point_in_box((fx, fy), box_a, inflate_m=radius + margin_m):
                raise SceneRejected(f"overlap: {name} sits inside building {box_a}")
        for region_id in ("sidewalk", "sidewalk_south"):
            region = derived.get(region_id)
            if region is None:
                raise SceneRejected(f"overlap: region {region_id} is missing")
            min_x, min_y, max_x, max_y = _polygon_bounds(region["polygon"])
            region_box = (
                (min_x + max_x) / 2.0,
                (min_y + max_y) / 2.0,
                (max_x - min_x) / 2.0,
                (max_y - min_y) / 2.0,
            )
            if _boxes_overlap(box_a, region_box, margin_m=0.0):
                raise SceneRejected(f"overlap: building {box_a} covers {region_id}")


def check_layout(params: SceneParams, derived: dict[str, dict[str, Any]]) -> None:
    """The crosswalk must stay on the road, as it does in the frozen block.

    A crossing that runs up onto the pavement makes "go to the crosswalk" and
    "go to the sidewalk" partly the same instruction, which is a different
    episode from the one the family is named for.
    """

    crosswalk = derived.get("crosswalk")
    if crosswalk is None:
        raise SceneRejected("layout: the crosswalk region is missing")
    _, cw_min_y, _, cw_max_y = _polygon_bounds(crosswalk["polygon"])
    north_edge = params.north_y - params.north_half_width
    south_edge = params.south_y + params.south_half_width
    if cw_max_y > north_edge - 0.15 or cw_min_y < south_edge + 0.15:
        raise SceneRejected(
            f"layout: crosswalk y in [{cw_min_y}, {cw_max_y}] reaches a pavement"
        )


def check_support(derived: dict[str, dict[str, Any]]) -> None:
    """Pavement furniture must sit on a pavement, or its episode means something else."""

    north = derived.get("sidewalk")
    south = derived.get("sidewalk_south")
    if north is None or south is None:
        raise SceneRejected("support: a sidewalk region is missing from the scene")
    for entity_id, region in (
        ("bench_1", north),
        ("tree_1", north),
        ("tree_2", north),
        ("planter_1", north),
        ("lamp_post_1", north),
        ("lamp_post_2", south),
    ):
        entry = derived.get(entity_id)
        if entry is None:
            raise SceneRejected(f"support: {entity_id} is missing")
        min_x, min_y, max_x, max_y = _polygon_bounds(region["polygon"])
        x, y = entry["position"]
        if not (min_x <= x <= max_x and min_y <= y <= max_y):
            raise SceneRejected(f"support: {entity_id} at ({x}, {y}) is off its pavement")


def _grid_shape() -> tuple[float, float, int, int]:
    min_x, min_y, max_x, max_y = NAV_BOUNDS
    return (
        min_x,
        min_y,
        math.ceil((max_x - min_x) / NAV_GRID_M),
        math.ceil((max_y - min_y) / NAV_GRID_M),
    )


def blocked_grid(
    params: SceneParams,
    derived: dict[str, dict[str, Any]],
    *,
    clearance_m: float = ROBOT_CLEARANCE_M,
) -> set[tuple[int, int]]:
    """Cells the robot centre cannot occupy: furniture discs and building boxes."""

    min_x, min_y, width, height = _grid_shape()
    blocked: set[tuple[int, int]] = set()
    for cx, cy, radius in _furniture(derived).values():
        inflated = radius + clearance_m
        r_cells = math.ceil(inflated / NAV_GRID_M)
        gx = math.floor((cx - min_x) / NAV_GRID_M)
        gy = math.floor((cy - min_y) / NAV_GRID_M)
        for ix in range(gx - r_cells, gx + r_cells + 1):
            for iy in range(gy - r_cells, gy + r_cells + 1):
                if not (0 <= ix < width and 0 <= iy < height):
                    continue
                wx = min_x + (ix + 0.5) * NAV_GRID_M
                wy = min_y + (iy + 0.5) * NAV_GRID_M
                if math.hypot(wx - cx, wy - cy) <= inflated:
                    blocked.add((ix, iy))
    for bx, by, half_x, half_y in params.buildings:
        for ix in range(width):
            wx = min_x + (ix + 0.5) * NAV_GRID_M
            if abs(wx - bx) > half_x + clearance_m:
                continue
            for iy in range(height):
                wy = min_y + (iy + 0.5) * NAV_GRID_M
                if abs(wy - by) <= half_y + clearance_m:
                    blocked.add((ix, iy))
    return blocked


def _reachable(start: tuple[float, float], blocked: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """Every cell a 4-connected planner can reach from ``start``."""

    min_x, min_y, width, height = _grid_shape()
    start_cell = (
        math.floor((start[0] - min_x) / NAV_GRID_M),
        math.floor((start[1] - min_y) / NAV_GRID_M),
    )
    if start_cell in blocked:
        return set()
    heap: list[tuple[float, tuple[int, int]]] = [(0.0, start_cell)]
    seen = {start_cell}
    while heap:
        _, (cx, cy) = heapq.heappop(heap)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cx + dx, cy + dy)
            if nxt in seen or nxt in blocked:
                continue
            if not (0 <= nxt[0] < width and 0 <= nxt[1] < height):
                continue
            seen.add(nxt)
            heapq.heappush(heap, (0.0, nxt))
    return seen


def goal_cells(
    entry: dict[str, Any],
    *,
    band_m: tuple[float, float] = (0.6, 2.5),
) -> set[tuple[int, int]]:
    """Cells inside a landmark's stand-off band, or anywhere inside a region."""

    min_x, min_y, width, height = _grid_shape()
    cells: set[tuple[int, int]] = set()
    if entry["kind"] == "region":
        p_min_x, p_min_y, p_max_x, p_max_y = _polygon_bounds(entry["polygon"])
        for ix in range(width):
            wx = min_x + (ix + 0.5) * NAV_GRID_M
            if not p_min_x <= wx <= p_max_x:
                continue
            for iy in range(height):
                wy = min_y + (iy + 0.5) * NAV_GRID_M
                if p_min_y <= wy <= p_max_y:
                    cells.add((ix, iy))
        return cells
    cx, cy = entry["position"]
    lo = band_m[0] + float(entry["radius_m"])
    hi = band_m[1] + float(entry["radius_m"])
    r_cells = math.ceil(hi / NAV_GRID_M)
    gx = math.floor((cx - min_x) / NAV_GRID_M)
    gy = math.floor((cy - min_y) / NAV_GRID_M)
    for ix in range(gx - r_cells, gx + r_cells + 1):
        for iy in range(gy - r_cells, gy + r_cells + 1):
            if not (0 <= ix < width and 0 <= iy < height):
                continue
            wx = min_x + (ix + 0.5) * NAV_GRID_M
            wy = min_y + (iy + 0.5) * NAV_GRID_M
            if lo <= math.hypot(wx - cx, wy - cy) <= hi:
                cells.add((ix, iy))
    return cells


def check_navigability(
    params: SceneParams,
    derived: dict[str, dict[str, Any]],
    *,
    clearance_m: float = ROBOT_CLEARANCE_M,
) -> None:
    """Every landmark must be reachable from every episode start pose."""

    blocked = blocked_grid(params, derived, clearance_m=clearance_m)
    targets: dict[str, set[tuple[int, int]]] = {}
    for entity_id in REQUIRED_LANDMARKS:
        entry = derived.get(entity_id)
        if entry is None:
            raise SceneRejected(f"navigability: {entity_id} is missing from the scene")
        cells = goal_cells(entry) - blocked
        if not cells:
            raise SceneRejected(f"navigability: {entity_id} has no free stand-off cell")
        targets[entity_id] = cells
    for start in REQUIRED_START_XY:
        reachable = _reachable(start, blocked)
        if not reachable:
            raise SceneRejected(f"navigability: start pose {start} is inside an obstacle")
        for entity_id, cells in targets.items():
            if not cells & reachable:
                raise SceneRejected(f"navigability: {entity_id} unreachable from {start}")


# ---------------------------------------------------------------------------
# emission
# ---------------------------------------------------------------------------


def semantics_sidecar_text(scene_relpath: str) -> str:
    """Re-emit the city-block vocabulary against a generated scene.

    The vocabulary is *read from* ``configs/scenes/city_block.semantics.yaml``
    and re-serialised with one field changed. Nothing is retyped: a class added
    there appears here on the next regeneration, and the real loader validates
    the result before it is written.
    """

    raw = yaml.safe_load(SOURCE_SIDECAR.read_text(encoding="utf-8"))
    raw["scene"] = scene_relpath
    header = (
        "# GENERATED by evals/nav_instruct/scene_gen.py — do not hand-edit.\n"
        "# The vocabulary below is re-emitted verbatim from\n"
        f"# {SOURCE_SIDECAR.relative_to(REPO_ROOT)}; only `scene` differs. Geometry\n"
        "# is never carried here — it is read from the MJCF at extraction time.\n"
    )
    return header + yaml.safe_dump(raw, sort_keys=True, default_flow_style=False)


def build_scene(seed: int, *, scratch_dir: Path) -> tuple[SceneParams, str, dict[str, Any], AcceptanceRecord]:
    """Sample and filter until a proposal is accepted. Writes only to scratch."""

    from evals.nav_instruct.scene_truth import derive_scene_truth

    scratch_dir.mkdir(parents=True, exist_ok=True)
    scratch = scratch_dir / f".{SPLIT_NAME}_{seed}.proposal.xml"
    record = AcceptanceRecord()
    try:
        for attempt in range(MAX_PROPOSALS_PER_SEED):
            record.proposals_tried += 1
            params = sample_params(seed, attempt)
            xml = scene_xml(params, scene_id=f"{SPLIT_NAME}_{seed}")
            scratch.write_text(xml, encoding="utf-8")
            try:
                derived = derive_scene_truth(scratch)
                check_round_trip(params, derived)
                check_overlap(params, derived)
                check_layout(params, derived)
                check_support(derived)
                check_navigability(params, derived)
            except SceneRejected as rejection:
                record.reject(str(rejection))
                continue
            except ValueError as error:  # an MJCF MuJoCo refuses to compile
                record.reject(f"mjcf: {error}")
                continue
            return params, xml, derived, record
    finally:
        if scratch.exists():
            scratch.unlink()
    raise SceneRejected(
        f"seed {seed}: no proposal survived {MAX_PROPOSALS_PER_SEED} attempts "
        f"({record.as_dict()})"
    )


def generate_scene(seed: int, *, out_dir: Path = OUT_DIR, write: bool = True) -> dict[str, Any]:
    """Sample, filter and (optionally) emit one accepted scene. Returns its manifest."""

    scene_id = f"{SPLIT_NAME}_{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    params, xml, derived, record = build_scene(seed, scratch_dir=out_dir)
    scene_path = out_dir / f"{scene_id}.xml"
    sidecar_path = out_dir / f"{scene_id}.semantics.yaml"
    truth_path = out_dir / f"{scene_id}.truth.json"
    scene_relpath = str(scene_path.relative_to(REPO_ROOT))
    manifest = {
        "artifact_version": 1,
        "generated_by": "evals/nav_instruct/scene_gen.py",
        "do_not_hand_edit": (
            "regenerate with: .parcel/bin/python -m evals.nav_instruct.scene_gen --emit"
        ),
        "split": SPLIT_NAME,
        "scene_id": scene_id,
        "seed": seed,
        "params": params.as_dict(),
        "acceptance": record.as_dict(),
        "filters": [
            "round_trip: the derived table agrees with what the sampler wrote",
            (
                "overlap: furniture discs disjoint (0.35 m); buildings as boxes, "
                "disjoint from each other, from the furniture and from both pavements"
            ),
            "layout: the crosswalk stays on the road",
            "support: pavement furniture inside its sidewalk polygon",
            (
                f"navigability: 4-connected search at {NAV_GRID_M} m, obstacles "
                f"inflated by {ROBOT_CLEARANCE_M:.2f} m "
                "(RobotProfile.footprint_radius_m + terminal clearance), from "
                "every episode start pose to every landmark's stand-off band"
            ),
        ],
        "scene": {"path": scene_relpath, "sha256": hashlib.sha256(xml.encode()).hexdigest()},
        "semantics_sidecar": str(sidecar_path.relative_to(REPO_ROOT)),
        "derived": derived,
        "never_tuned_against": True,
    }
    if write:
        scene_path.write_text(xml, encoding="utf-8")
        sidecar_path.write_text(semantics_sidecar_text(scene_relpath), encoding="utf-8")
        _validate_sidecar(sidecar_path)
        truth_path.write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    return manifest


def _validate_sidecar(path: Path) -> None:
    """A sidecar that does not load is not an artifact — fail at emission time."""

    from parcel_robot.scene_semantics import load_scene_semantics

    load_scene_semantics(path)


def emit_split(
    *,
    out_dir: Path = OUT_DIR,
    seeds: tuple[int, ...] = VAL_UNSEEN_SEEDS,
) -> list[dict[str, Any]]:
    return [generate_scene(seed, out_dir=out_dir) for seed in seeds]


def split_manifests(out_dir: Path = OUT_DIR) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(out_dir.glob(f"{SPLIT_NAME}_*.truth.json"))
    ]


def scene_paths(out_dir: Path = OUT_DIR) -> list[Path]:
    return [REPO_ROOT / manifest["scene"]["path"] for manifest in split_manifests(out_dir)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", action="store_true", help="write the frozen val_unseen split")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if a checked-in scene differs from a fresh generation",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)

    if args.emit:
        manifests = emit_split(out_dir=args.out)
        print(
            json.dumps(
                [
                    {
                        "scene_id": item["scene_id"],
                        "seed": item["seed"],
                        "acceptance": item["acceptance"],
                        "sha256": item["scene"]["sha256"],
                    }
                    for item in manifests
                ],
                indent=2,
            )
        )
        return 0

    drifted: list[str] = []
    for seed in VAL_UNSEEN_SEEDS:
        fresh = generate_scene(seed, out_dir=args.out, write=False)
        stored_path = args.out / f"{fresh['scene_id']}.truth.json"
        stored = (
            json.loads(stored_path.read_text(encoding="utf-8")) if stored_path.exists() else None
        )
        if stored != fresh:
            drifted.append(fresh["scene_id"])
    print(json.dumps({"checked": len(VAL_UNSEEN_SEEDS), "drifted": drifted}, indent=2))
    return 1 if (args.check and drifted) else 0


if __name__ == "__main__":
    raise SystemExit(main())
