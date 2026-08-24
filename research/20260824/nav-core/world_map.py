"""The dog's own map of the room, built the way the product builds one.

No oracle is written here.  Each place is entered through
:meth:`OnlineSemanticMap.observe` as repeated detector-shaped observations, so
the entry's confidence is :func:`navigation.semantic_map.evidence_confidence`
of what it actually accumulated rather than a stamped constant, and its
admissible names are the ones the map earned.  That is the whole point of the
NAV-CORE input shaping: no ``associated_lidar_ids``, no polygons, no 0.98.

:func:`seed_room_map` is the nominal map.  :func:`seed_room_map` with
``omit`` is refuter 4's map — the goal place was never learned, so the
vocabulary the real door reads does not contain it and the refusal has to come
from perception rather than from a list the world file shipped.
"""

from __future__ import annotations

import math
from typing import Any

from room import PLACES, Place

from parcel_robot.online_map.entries import MapObservation, WriterProvenance
from parcel_robot.online_map.online_map import OnlineSemanticMap
from parcel_robot.online_map.store import OnlineMapStore

#: How many frames of evidence each place gets.  Seven is
#: ``semantic_map.EVIDENCE_SATURATION_FRAMES``, the point at which the earned
#: confidence stops climbing steeply; ten leaves the six places comfortably
#: above the ladder's 0.55 minimum without pinning them at the ceiling.
EVIDENCE_FRAMES = 10

PROVENANCE = WriterProvenance(
    session_id="navcore",
    seat="research",
    detector_name="navcore_sim_detector",
    scene_id="navcore_room",
)

#: Metric extents per place.  Ordinary furniture sizes; they clear the hygiene
#: gate's default prior and are never read as geometry by the navigator.
EXTENTS: dict[str, tuple[float, float]] = {
    "place_bed": (1.40, 0.60),
    "place_desk": (1.20, 0.75),
    "place_couch": (1.80, 0.85),
    "place_bowl": (0.30, 0.12),
    "place_shelf": (0.90, 1.80),
    "place_counter": (1.60, 0.95),
}


def _observation(place: Place, frame: int) -> MapObservation:
    """One frame of evidence for one place, seen from a plausible stand-off."""

    width, height = EXTENTS[place.place_id]
    # The observer stands a metre out along the room's inward normal, so the
    # bearing and range on the record are consistent with the geometry rather
    # than being zeros the map would have to trust.
    norm = math.hypot(place.x, place.y) or 1.0
    robot_x = place.x - place.x / norm
    robot_y = place.y - place.y / norm
    range_m = math.hypot(place.x - robot_x, place.y - robot_y)
    return MapObservation(
        label=place.label,
        score=0.55,
        surface_x=place.x,
        surface_y=place.y,
        surface_z=0.4,
        range_m=range_m,
        bearing_rad=0.0,
        depth_m=range_m,
        extent_w_m=width,
        extent_h_m=height,
        inlier_pixels=900,
        frame_id=f"{place.place_id}-{frame}",
        visit_id="navcore-visit-0",
        observed_wall_s=100.0 + frame,
        robot_x=robot_x,
        robot_y=robot_y,
        provenance=PROVENANCE,
        relief_m=0.15,
        relief_samples=32,
    )


def seed_room_map(*, omit: str = "") -> OnlineSemanticMap:
    """A fresh in-memory map holding the room's known places.

    ``omit`` drops one ``place_id`` entirely — the map never learned it.  The
    store is ``:memory:`` so the owner's ``parcel_memory.sqlite3`` and the
    shipped online-map file are never opened.
    """

    learned = OnlineSemanticMap(
        OnlineMapStore(":memory:"), provenance=PROVENANCE, reload=False
    )
    places = [place for place in PLACES if place.place_id != omit]
    labels = tuple(place.label for place in places)
    for frame in range(EVIDENCE_FRAMES):
        learned.note_frame(labels)
        for place in places:
            learned.note_pose(place.x, place.y)
            learned.observe(_observation(place, frame))
    return learned


def entry_id_for(learned: Any, place: Place) -> str:
    """The map's own id for a place, found by position rather than by name."""

    best_id = ""
    best_distance = math.inf
    for entry in learned.active_entries():
        distance = math.hypot(
            float(entry.surface_x) - place.x, float(entry.surface_y) - place.y
        )
        if distance < best_distance:
            best_id, best_distance = str(entry.entry_id), distance
    return best_id if best_distance <= 0.75 else ""
