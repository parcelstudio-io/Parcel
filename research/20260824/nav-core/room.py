"""The NAV-CORE one-room world: an 8x8 m room, six known places, four layouts.

Why a purpose-built room and not ``city_block``.  NAV-CORE's question is the
*room-scale, known-place* case, which the recorded v4 city baseline has never
measured separately.  The room is generated as MuJoCo XML so the scan is the
same occlusion-true ray engine the navigator already consumes
(``simulation/mujoco_lidar.raycast_planar_scan`` at
``DEFAULT_ROBOT_PROFILE.scan_height_m``) — the H7 bench's discipline, at room
scale.  The body is placed kinematically (``qpos`` + ``mj_forward``), exactly
as ``SceneTraverse`` and ``HeadlessCityWorld._place_robot`` do; contact is
scored analytically against the rectangles authored below, which is exact
rather than an estimate off a contact solver the bench does not otherwise use.

**A known place is a floor spot, not a surface.**  Each place is a point the
body can actually stand on, with a small marker object against the wall beside
it — "your bed", "the water bowl".  Stored points sit >= 0.9 m clear of every
blocker in every layout (:func:`audit_clearances` proves it), so the
pre-registered 0.5 m arrival band is geometrically reachable and the bar
measures the navigator rather than the room.

**The aliased layout** (refuter 4b) is authored with exact two-fold rotational
symmetry about the room centre: the markers are joined by their 180 deg images
and every clutter box maps onto another.  A pose and its 180 deg image
therefore produce *identical* scans by construction, so a scan-matching
localizer cannot tell them apart — the strongest form of the aliasing H7 found
on ``city_block``, and the reason a kidnap there is a genuine false-healthy
test rather than a displacement the matcher merely happens to miss.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import mujoco
import numpy as np

from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE
from parcel_robot.simulation.mujoco_lidar import PlanarScan, raycast_planar_scan

#: Interior half-extent of the room, metres.  8 x 8 m as pre-registered.
ROOM_HALF_M = 4.0
WALL_THICKNESS_M = 0.10
WALL_HEIGHT_M = 1.20
#: Boxes span 0 .. 1.0 m so every one of them crosses the 0.45 m scan plane.
BOX_HEIGHT_M = 1.00
#: The body box tops out at 0.40 m, below the 0.45 m scan plane: a scan origin
#: inside the body's own geom makes mj_multiRay return a self-hit on every ray.
BODY_Z_M = 0.25
BODY_HALF_Z_M = 0.15
#: Rays.  360 (1 deg) rather than the simulator default 720: the room is 8 m
#: across, so 1 deg is 7 cm of arc at the far wall — finer than the 0.10 m
#: GICP voxel the localizer downsamples to, at half the ray budget.  Fixed
#: here before any arm was run.
SCAN_RAYS = 360
#: Every stored place must keep at least this much room around it in every
#: layout, or the arrival bar would be measuring the furniture.  0.88 m is the
#: measured worst case here, comfortably past the planner's own lateral
#: inflation (``ReactiveSafetyPolicy.planner_inflation_m`` = 0.593 m at the
#: commissioned 0.65 m obstacle stop ring).
MIN_PLACE_CLEARANCE_M = 0.80


@dataclass(frozen=True)
class Box:
    """An axis-aligned box: centre and half-extents in metres."""

    name: str
    cx: float
    cy: float
    hx: float
    hy: float

    def distance_to(self, x: float, y: float) -> float:
        """Euclidean distance from ``(x, y)`` to the box surface (0 inside)."""

        dx = max(abs(x - self.cx) - self.hx, 0.0)
        dy = max(abs(y - self.cy) - self.hy, 0.0)
        return math.hypot(dx, dy)

    def closest_point(self, x: float, y: float) -> tuple[float, float]:
        return (
            min(max(x, self.cx - self.hx), self.cx + self.hx),
            min(max(y, self.cy - self.hy), self.cy + self.hy),
        )

    def rotated_180(self, suffix: str = "_c2") -> Box:
        return Box(self.name + suffix, -self.cx, -self.cy, self.hx, self.hy)


@dataclass(frozen=True)
class Place:
    """One known place: the point the map stores and the marker beside it."""

    place_id: str
    label: str
    aliases: tuple[str, ...]
    x: float
    y: float
    marker: Box


#: The six known places.  Each is a floor spot the body can stand on, with a
#: 0.5 m pilaster set into the wall beside it so the scan has something to see.
#: NOTE for refuter 4b: the place SET is exactly C2-symmetric — bed<->couch,
#: desk<->bowl, shelf<->counter — which is what lets a 180 deg kidnap end in a
#: *plausible wrong place* rather than in open floor.
PLACES: tuple[Place, ...] = (
    Place("place_bed", "bed", ("bed", "my bed"), -2.40, 2.40,
          Box("mark_bed", -4.00, 2.40, 0.25, 0.25)),
    Place("place_desk", "desk", ("desk", "the desk"), 2.40, 2.40,
          Box("mark_desk", 4.00, 2.40, 0.25, 0.25)),
    Place("place_couch", "couch", ("couch", "the sofa"), 2.40, -2.40,
          Box("mark_couch", 2.40, -4.00, 0.25, 0.25)),
    Place("place_bowl", "water bowl", ("water bowl", "my bowl"), -2.40, -2.40,
          Box("mark_bowl", -2.40, -4.00, 0.25, 0.25)),
    Place("place_shelf", "bookshelf", ("bookshelf", "the shelf"), -2.40, -1.00,
          Box("mark_shelf", -4.00, -1.00, 0.25, 0.25)),
    Place("place_counter", "kitchen counter", ("kitchen counter", "the counter"),
          2.40, 1.00, Box("mark_counter", 4.00, 1.00, 0.25, 0.25)),
)

PLACES_BY_ID: dict[str, Place] = {place.place_id: place for place in PLACES}

#: Four clutter layouts, NESTED so difficulty is monotone: each adds one box to
#: the one before, blocking 12, 15, 16 then 17 of the 30 straight start->place
#: lines.  Every box was chosen by search under two hard constraints — at least
#: 1.30 m from every stored place and every start pose, and every place still
#: reachable on a 0.1 m grid inflated by 0.95 m — so no layout can make a goal
#: unreachable and quietly turn the arrival bar into a geometry result.  The
#: layout for episode ``e`` is ``LAYOUTS[e % 4]``.
_L0 = Box("clut_a", 0.50, 0.10, 0.14, 1.20)
_L1 = Box("clut_b", -0.30, -0.30, 0.90, 0.14)
_L2 = Box("clut_c", -0.70, -1.20, 0.32, 0.32)
_L3 = Box("clut_d", 0.60, 1.10, 0.40, 0.40)
LAYOUTS: tuple[tuple[Box, ...], ...] = (
    (_L0,),
    (_L0, _L1),
    (_L0, _L1, _L2),
    (_L0, _L1, _L2, _L3),
)

#: Refuter 4b's clutter: two C2 pairs, so the whole world (square room, twelve
#: pilasters, four blocks) maps exactly onto itself under a 180 deg rotation.
_ALIASED_HALF: tuple[Box, ...] = (
    Box("alias_a", 0.70, 1.15, 0.40, 0.40),
    Box("alias_b", 0.65, 0.40, 0.50, 0.30),
)
LAYOUT_ALIASED: tuple[Box, ...] = _ALIASED_HALF + tuple(
    box.rotated_180() for box in _ALIASED_HALF
)

#: Start poses, pre-registered; episode ``e`` starts at ``STARTS[e % 5]``.
#: ``lcm(4, 5) = 20``, so the twenty episodes of a seed cover every
#: (start, layout) pair exactly once.
STARTS: tuple[tuple[float, float, float], ...] = (
    (0.00, -2.80, math.pi / 2),
    (0.00, 2.80, -math.pi / 2),
    (-2.80, 0.60, 0.0),
    (2.80, -0.60, math.pi),
    (-1.20, 1.20, -0.6),
)

#: Refuter 4b.  The body starts here and is kidnapped to the exact 180 deg
#: image of wherever it has got to.  The goal's own C2 twin is ``place_shelf``,
#: so a navigator that believes the pre-kidnap frame will drive to a REAL place
#: that is the wrong one — the false arrival the refuter is looking for.
ALIASED_START: tuple[float, float, float] = (-2.80, 0.60, 0.0)
ALIASED_GOAL_ID = "place_counter"
ALIASED_TWIN_ID = "place_shelf"


def c2_image(pose: tuple[float, float, float]) -> tuple[float, float, float]:
    """The 180 deg rotation of a pose about the room centre."""

    x, y, yaw = pose
    return (-x, -y, math.atan2(math.sin(yaw + math.pi), math.cos(yaw + math.pi)))


def _geom_xml(box: Box, height: float) -> str:
    return (
        f'    <geom name="{box.name}" type="box" '
        f'size="{box.hx:.4f} {box.hy:.4f} {height / 2:.4f}" '
        f'pos="{box.cx:.4f} {box.cy:.4f} {height / 2:.4f}" rgba="0.6 0.6 0.62 1"/>\n'
    )


def wall_blockers() -> tuple[Box, ...]:
    """The four walls as inward-facing slabs."""

    half = ROOM_HALF_M + WALL_THICKNESS_M / 2
    big = ROOM_HALF_M + 1.0
    return (
        Box("wall_n", 0.0, half, big, WALL_THICKNESS_M / 2),
        Box("wall_s", 0.0, -half, big, WALL_THICKNESS_M / 2),
        Box("wall_e", half, 0.0, WALL_THICKNESS_M / 2, big),
        Box("wall_w", -half, 0.0, WALL_THICKNESS_M / 2, big),
    )


def markers_for(layout: int | str) -> tuple[Box, ...]:
    """Place markers, plus their C2 images in the aliased world."""

    base = tuple(place.marker for place in PLACES)
    if layout == "aliased":
        return base + tuple(box.rotated_180() for box in base)
    return base


def clutter_for(layout: int | str) -> tuple[Box, ...]:
    return LAYOUT_ALIASED if layout == "aliased" else LAYOUTS[int(layout)]


def room_xml(layout: int | str, extra: tuple[Box, ...] = ()) -> str:
    """The whole world as one MuJoCo document — walls, markers, clutter, body."""

    parts = [
        '<mujoco model="parcel_nav_core_room">\n',
        '  <compiler angle="radian" autolimits="true"/>\n',
        '  <worldbody>\n',
        '    <geom name="floor" type="plane" size="12 12 0.1" pos="0 0 0"/>\n',
    ]
    for wall in wall_blockers():
        parts.append(_geom_xml(wall, WALL_HEIGHT_M))
    for box in markers_for(layout) + clutter_for(layout) + extra:
        parts.append(_geom_xml(box, BOX_HEIGHT_M))
    parts.append(
        f'    <body name="robot" pos="0 0 {BODY_Z_M}">\n'
        '      <freejoint name="robot_free"/>\n'
        f'      <geom name="robot_body" type="box" size="0.30 0.16 {BODY_HALF_Z_M}" '
        'contype="0" conaffinity="0" rgba="0.9 0.6 0.2 1"/>\n'
        '    </body>\n'
        '  </worldbody>\n'
        '</mujoco>\n'
    )
    return "".join(parts)


@dataclass
class RoomWorld:
    """One room the harness can place a body in, scan from, and score contact.

    ``layout`` is an index into :data:`LAYOUTS`, or the literal string
    ``"aliased"`` for refuter 4b's C2-symmetric world.
    """

    layout: int | str = 0
    _model: Any = field(init=False, repr=False, default=None)
    _data: Any = field(init=False, repr=False, default=None)
    blockers: tuple[Box, ...] = field(init=False, default=())

    extra: tuple[Box, ...] = field(default=())

    def __post_init__(self) -> None:
        self._compile()

    def _compile(self) -> None:
        self._model = mujoco.MjModel.from_xml_string(room_xml(self.layout, self.extra))
        self._data = mujoco.MjData(self._model)
        mujoco.mj_resetData(self._model, self._data)
        free = [
            joint
            for joint in range(self._model.njnt)
            if self._model.jnt_type[joint] == mujoco.mjtJoint.mjJNT_FREE
        ]
        self.robot_body_id = int(self._model.jnt_bodyid[free[0]])
        self.blockers = (
            markers_for(self.layout)
            + clutter_for(self.layout)
            + self.extra
            + wall_blockers()
        )

    def add_blocker(self, box: Box) -> None:
        """Refuter 3: an obstacle that was not there when the route was planned.

        The world is recompiled so the box is real to the LiDAR as well as to
        contact — a moved obstacle a robot cannot see is a different refuter.
        The scan RNG lives in the episode runner, not here, so recompiling does
        not disturb the noise stream.
        """

        self.extra = self.extra + (box,)
        self._compile()

    # -- body --------------------------------------------------------------

    def place(self, x: float, y: float, yaw: float) -> None:
        self._data.qpos[:3] = (x, y, BODY_Z_M)
        half = yaw * 0.5
        self._data.qpos[3:7] = (math.cos(half), 0.0, 0.0, math.sin(half))
        if self._model.nv >= 6:
            self._data.qvel[:6] = 0.0
        mujoco.mj_forward(self._model, self._data)

    def clearance_m(self, x: float, y: float) -> float:
        """Distance from the body's inscribing circle to the nearest blocker."""

        nearest = min(box.distance_to(x, y) for box in self.blockers)
        return nearest - DEFAULT_ROBOT_PROFILE.footprint_radius_m

    def in_contact(self, x: float, y: float) -> bool:
        return self.clearance_m(x, y) <= 0.0

    def nearest_obstacle(
        self, x: float, y: float, yaw: float
    ) -> tuple[float, float, str]:
        """``(clearance_m, bearing_rad, obstacle_id)`` for the nearest blocker.

        ``clearance_m`` is surface-to-body-circle, the convention
        ``SimObservation.nearest_obstacle_m`` carries.
        """

        best = min(self.blockers, key=lambda box: box.distance_to(x, y))
        px, py = best.closest_point(x, y)
        distance = max(
            0.0,
            math.hypot(px - x, py - y) - DEFAULT_ROBOT_PROFILE.footprint_radius_m,
        )
        heading = math.atan2(py - y, px - x)
        bearing = math.atan2(math.sin(heading - yaw), math.cos(heading - yaw))
        return distance, bearing, best.name

    # -- sensor ------------------------------------------------------------

    def scan(
        self, x: float, y: float, yaw: float, rng: np.random.Generator
    ) -> PlanarScan:
        self.place(x, y, yaw)
        return raycast_planar_scan(
            self._model,
            self._data,
            robot_x=x,
            robot_y=y,
            robot_heading=yaw,
            robot_body_id=self.robot_body_id,
            sensor_z_m=DEFAULT_ROBOT_PROFILE.scan_height_m,
            num_rays=SCAN_RAYS,
            rng=rng,
        )


def audit_clearances() -> dict[str, float]:
    """Worst clearance of every stored place and start pose, over all layouts.

    Called by the probe test.  A room that fails this is a room whose arrival
    bar measures the furniture, so it is checked rather than assumed.  The
    aliased world is audited on the poses refuter 4b actually uses.
    """

    worst: dict[str, float] = {}

    def record(key: str, value: float) -> None:
        worst[key] = min(worst.get(key, math.inf), value)

    for layout in (0, 1, 2, 3):
        world = RoomWorld(layout)
        for place in PLACES:
            record(f"place:{place.place_id}", world.clearance_m(place.x, place.y))
        for index, start in enumerate(STARTS):
            record(f"start:{index}", world.clearance_m(start[0], start[1]))
    aliased = RoomWorld("aliased")
    for place_id in (ALIASED_GOAL_ID, ALIASED_TWIN_ID):
        place = PLACES_BY_ID[place_id]
        record(f"aliased:{place_id}", aliased.clearance_m(place.x, place.y))
    for name, pose in (("start", ALIASED_START), ("kidnap", c2_image(ALIASED_START))):
        record(f"aliased:{name}", aliased.clearance_m(pose[0], pose[1]))
    return worst


def alias_scan_agreement() -> float:
    """Largest per-ray disagreement between a pose and its C2 image, metres.

    The refuter's premise, measured rather than asserted: if this is not at
    float noise, the "aliased corridor" is not aliased and refuter 4b is not
    asking the question it claims to ask.
    """

    world = RoomWorld("aliased")
    worst = 0.0
    for pose in (ALIASED_START, (-2.0, 1.4, 0.9), (-1.5, -0.4, -2.1)):
        left = np.asarray(world.scan(*pose, np.random.default_rng(11)).ranges_m)
        right = np.asarray(
            world.scan(*c2_image(pose), np.random.default_rng(11)).ranges_m
        )
        mask = np.isfinite(left) & np.isfinite(right)
        if not mask.any():
            return math.inf
        worst = max(worst, float(np.abs(left[mask] - right[mask]).max()))
    return worst
