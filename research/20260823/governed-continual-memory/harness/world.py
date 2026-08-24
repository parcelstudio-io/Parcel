"""Replay a detection stream into a learned map, then ask it 30 questions.

DESIGN §Experiment item 6, and rows M6 / M7's map half.

THE ARCHIVED STREAM, AND WHY IT IS NOT ENOUGH ON ITS OWN
--------------------------------------------------------
``tests/data/c2_online_map_frames.json`` is the real C-1 artifact: 16
``CameraDetectionFrame`` rows published by the live stack against W-1's
textured ``city_block`` scene, OWLv2-b16 int8 on CPU. It is replayed here
exactly as ``tests/test_p1b_map_learns.py`` replays it.

Measured before anything was built on it: those 16 frames carry **one noun** —
40 ``lamppost`` detections and nothing else (the query batch was
``['person','lamppost']``, and ``person`` is a volatile label the map refuses by
design). A 30-question set with 20 present nouns cannot be asked of a map with
one noun in it, so the replay is the archived stream **plus** synthesized frames
in the identical ``CameraDetectionFrame`` schema, carrying the seven further
labels the map's own ``SIZE_PRIORS`` know how to screen. That extension is
declared here and in RESULTS.md rather than buried: the archived half is
``replay`` evidence, the synthesized half is a fixture, and the world-query
numbers are honest only as "a map of this shape answers this well".

THE QUESTION SET IS FIXED BEFORE THE MAP IS BUILT
--------------------------------------------------
:data:`PRESENT_QUERIES` and :data:`ABSENT_QUERIES` are literals, 20 and 10, and
the absent ten are ordinary street nouns the detector was never asked about —
which is exactly the state PG-3 refuses on (``asked=False``), and the reason
"has the robot seen a postbox" has a correct answer rather than a guess.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from parcel_robot.camera_channel.ingress import CameraDetectionFrame, CameraDetectionRecord
from parcel_robot.online_map.answers import PlaceSighting, sighting_from_candidate, where_is
from parcel_robot.online_map.entries import WriterProvenance
from parcel_robot.online_map.ingest import observations_from_frame
from parcel_robot.online_map.online_map import OnlineSemanticMap
from parcel_robot.online_map.store import OnlineMapStore
from parcel_robot.perception.abstention import AbstentionPolicy

REPO = Path(__file__).resolve().parents[4]
C1_FRAMES = REPO / "tests" / "data" / "c2_online_map_frames.json"

#: The archived stream's own noun, plus the seven synthesized ones. Every label
#: here has a ``SIZE_PRIORS`` entry, so the hygiene gate screens them on their
#: real metric extents rather than falling through to the default prior.
SYNTHETIC_LABELS: tuple[str, ...] = (
    "bench",
    "tree",
    "planter",
    "trash can",
    "fire hydrant",
    "door",
    "awning",
)

#: 20 questions the map should answer. Each present noun is asked twice — once
#: bare, once inside a sentence — because ``resolve`` tokenizes the query and a
#: renderer that only works on bare nouns is not a world-query path.
PRESENT_QUERIES: tuple[str, ...] = (
    "lamppost",
    "where is the lamppost",
    "bench",
    "where is the bench",
    "tree",
    "where is the tree",
    "planter",
    "where is the planter",
    "trash can",
    "where is the trash can",
    "fire hydrant",
    "where is the fire hydrant",
    "door",
    "where is the door",
    "awning",
    "where is the awning",
    "the bench near here",
    "that tree",
    "a trash can",
    "the door",
)

#: 10 nouns the detector was never asked about. The correct answer to all ten is
#: a refusal.
ABSENT_QUERIES: tuple[str, ...] = (
    "fountain",
    "postbox",
    "bicycle rack",
    "statue",
    "where is the fountain",
    "phone booth",
    "picnic table",
    "bus shelter",
    "where is the statue",
    "vending machine",
)

_NOUN_BY_QUERY: dict[str, str] = {}
for _label in ("lamppost",) + SYNTHETIC_LABELS:
    for _query in PRESENT_QUERIES:
        if _label in _query:
            _NOUN_BY_QUERY[_query] = _label


def _depth_patch(spread: float = 0.35) -> tuple[tuple[float, ...], ...]:
    """A patch with front-to-back relief: a solid object, not a painted decal."""

    return tuple(
        tuple(2.0 + spread * (row / 11.0) for _ in range(12)) for row in range(12)
    )


#: (label, world x, y, z, box height px, box width px, depth m, observing pose).
#: The geometry is chosen so ``metric_extents`` lands each detection inside its
#: own ``SIZE_PRIORS`` band, and so the observing pose is within
#: ``NAV_PROBE_RING_M + NAV_PROBE_TOLERANCE_M`` of the place — a fixture whose
#: places failed the hygiene or navigability gate would be measuring the gate
#: rather than the answer path.
_PLACES: tuple[tuple[str, float, float, float, float, float, float, tuple[float, float]], ...] = (
    ("bench", 6.2, -2.4, 0.5, 60.0, 220.0, 4.0, (5.4, -0.9)),
    ("tree", 9.5, 3.1, 2.0, 300.0, 120.0, 6.0, (8.6, 1.7)),
    ("planter", 4.4, 3.8, 0.35, 60.0, 90.0, 3.5, (3.9, 2.3)),
    ("trash can", 3.1, -1.6, 0.5, 90.0, 60.0, 3.0, (2.7, -0.2)),
    ("fire hydrant", 7.8, -3.9, 0.4, 100.0, 40.0, 3.4, (7.1, -2.5)),
    ("door", 12.0, 1.2, 1.1, 260.0, 120.0, 6.5, (10.7, 1.0)),
    ("awning", 11.2, -1.0, 2.6, 40.0, 400.0, 6.0, (10.2, -0.6)),
)

#: The lamppost the archived C-1 stream localizes, so the patrol walks past it
#: too. Taken from the fixture's own detections, not invented: every archived
#: row puts it at roughly (3.9, 2.1).
_ARCHIVED_LAMPPOST_XY = (3.9, 2.1)

#: Frames per place per visit. The shipped abstention operating point wants
#: ``min_evidence_frames = 7``; four visits x three frames gives 12, so the
#: evidence gate is cleared by the replay and is not the variable under test.
FRAMES_PER_PLACE_PER_VISIT = 3
DEFAULT_VISITS = 4


def patrol_path() -> tuple[tuple[float, float], ...]:
    """Poses the robot body occupied, one per place plus the lamppost.

    Navigability is the map's own claim about ground the robot has STOOD on, so
    a replay that never walks anywhere is correctly refused by PG-3. This is the
    walk that makes the fixture a patrol rather than a stare.
    """

    return tuple(place[7] for place in _PLACES) + (_ARCHIVED_LAMPPOST_XY,)


def synthesized_frames(
    *, visits: int = DEFAULT_VISITS, base_wall_s: float = 1_787_356_800.0
) -> list[CameraDetectionFrame]:
    """Frames in the archived stream's own schema, carrying the further nouns.

    ``visits`` frame-groups with distinct ``visit_id``s, because the map's name
    promotion and its ``visits`` counter both key on distinct visits and a
    single stare is not corroboration.
    """

    frames: list[CameraDetectionFrame] = []
    queries = tuple(SYNTHETIC_LABELS) + ("lamppost",)
    sequence = 1_000
    for visit in range(visits):
        for index, place in enumerate(_PLACES):
            label, wx, wy, wz, box_h, box_w, depth, (rx, ry) = place
            for repeat in range(FRAMES_PER_PLACE_PER_VISIT):
                bearing = math.atan2(wy - ry, wx - rx)
                record = CameraDetectionRecord(
                    label=label,
                    score=0.62,
                    box=(200.0, 100.0, 200.0 + box_w, 100.0 + box_h),
                    world_x=wx,
                    world_y=wy,
                    world_z=wz,
                    range_m=math.dist((rx, ry), (wx, wy)),
                    bearing_rad=bearing,
                    depth_m=depth,
                    sigma_range_m=0.02,
                    inlier_pixels=5_200,
                    depth_patch=_depth_patch(),
                )
                sequence += 1
                frames.append(
                    CameraDetectionFrame(
                        frame_id=f"h5-syn-{visit}-{index}-{repeat}",
                        sequence=sequence,
                        source_timestamp_ns=1,
                        capture_started_monotonic_ns=1_000,
                        capture_completed_monotonic_ns=2_000,
                        published_monotonic_ns=3_000,
                        published_wall_s=base_wall_s + visit * 3_600.0 + index * 10.0 + repeat,
                        detection_ttl_ns=300_000_000,
                        width_px=1280,
                        height_px=720,
                        robot_x=rx,
                        robot_y=ry,
                        robot_yaw_rad=0.0,
                        queries=queries,
                        detections=(record,),
                        raw_detections=1,
                        localized_detections=1,
                        rejected_detections=0,
                        truncated_detections=0,
                        render_ms=4.0,
                        detect_ms=30.0,
                        total_ms=34.0,
                        detector_name="owlv2-b16-fp16",
                        provider_profile="fixture",
                        active_providers=("CPUExecutionProvider",),
                        origin="unknown",
                        embedded_detections=0,
                        relief_measured_detections=1,
                    )
                )
    return frames


def archived_frames() -> list[CameraDetectionFrame]:
    """The 16 real C-1 rows, decoded exactly as ``test_p1b_map_learns`` does."""

    payload = json.loads(C1_FRAMES.read_text(encoding="utf-8"))
    return [CameraDetectionFrame.from_mapping(row) for row in payload["frames"]]


def build_map(
    store_path: str,
    *,
    visits: int = DEFAULT_VISITS,
    policy: AbstentionPolicy | None = None,
) -> tuple[OnlineSemanticMap, dict[str, Any]]:
    """Replay archived + synthesized frames into a map on ``store_path``."""

    provenance = WriterProvenance(
        session_id="h5-world",
        seat="runtime_camera",
        detector_name="owlv2-b16",
        scene_id="city_block",
        origin="unknown",
    )
    store = OnlineMapStore(store_path)
    semantic_map = OnlineSemanticMap(
        store, provenance=provenance, reload=False, policy=policy
    )

    archived = archived_frames()
    synthetic = synthesized_frames(visits=visits)
    counts: dict[str, Any] = {
        "archived_frames": len(archived),
        "synthesized_frames": len(synthetic),
    }

    for frame in archived:
        _ingest(semantic_map, frame, visit_id="c1-replay")
    for frame in synthetic:
        visit = frame.frame_id.split("-")[2]
        _ingest(semantic_map, frame, visit_id=f"h5-visit-{visit}", depth=True)
    # The walk itself, so navigability is a measurement and not a zero.
    for pose in patrol_path():
        semantic_map.note_pose(*pose)

    counts["entries"] = len(semantic_map)
    counts["active_entries"] = len(semantic_map.active_entries())
    counts["labels"] = sorted({e.label for e in semantic_map.active_entries()})
    counts["path_poses"] = semantic_map.path_length
    counts["evidence_frames"] = {
        e.label: e.evidence_frames for e in semantic_map.active_entries()
    }
    counts["navigability"] = {
        e.label: round(semantic_map.navigability(e)[0], 3)
        for e in semantic_map.active_entries()
    }
    return semantic_map, counts


def _ingest(
    semantic_map: OnlineSemanticMap, frame: CameraDetectionFrame, *, visit_id: str, depth: bool = False
) -> None:
    semantic_map.note_frame(queries=frame.queries)
    semantic_map.note_pose(frame.robot_x, frame.robot_y)
    patches = {0: _depth_patch()} if depth else None
    for observation in observations_from_frame(
        frame, visit_id=visit_id, provenance=semantic_map.provenance, depth_patches=patches
    ):
        semantic_map.observe(observation)


def sightings_for(
    semantic_map: OnlineSemanticMap,
    query: str,
    *,
    robot_xy: tuple[float, float] = (0.0, 0.0),
    robot_yaw_rad: float = 0.0,
) -> tuple[bool, tuple[PlaceSighting, ...], str, tuple[str, ...]]:
    """Query the map and adapt the result into rows the renderer can read."""

    result = semantic_map.resolve(query, robot_xy=robot_xy)
    entries = {entry.entry_id: entry for entry in semantic_map.entries()}
    rows = tuple(
        sighting_from_candidate(
            candidate,
            last_seen_wall_s=entries[candidate.entry_id].last_seen_wall_s,
            robot_xy=robot_xy,
            robot_yaw_rad=robot_yaw_rad,
        )
        for candidate in result.candidates
    )
    return result.admitted, rows, result.verdict.reason, tuple(result.verdict.alternatives)


def ask(
    semantic_map: OnlineSemanticMap,
    query: str,
    *,
    now_wall_s: float,
    robot_xy: tuple[float, float] = (0.0, 0.0),
) -> dict[str, Any]:
    """One world question, from query to spoken sentence."""

    admitted, rows, reason, alternatives = sightings_for(
        semantic_map, query, robot_xy=robot_xy
    )
    answer = where_is(
        query,
        rows,
        now_wall_s=now_wall_s,
        answered=admitted,
        reason=reason,
        alternatives=alternatives,
    )
    payload = answer.as_dict()
    payload["expected_label"] = _NOUN_BY_QUERY.get(query, "")
    payload["top1_correct"] = bool(
        answer.answered
        and answer.place is not None
        and payload["expected_label"]
        and payload["expected_label"] in answer.place.label
    )
    return payload


def ask_all(
    semantic_map: OnlineSemanticMap,
    *,
    now_wall_s: float,
    queries: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    wanted: Sequence[str] = tuple(queries) if queries is not None else (
        PRESENT_QUERIES + ABSENT_QUERIES
    )
    return [ask(semantic_map, query, now_wall_s=now_wall_s) for query in wanted]


__all__ = [
    "ABSENT_QUERIES",
    "C1_FRAMES",
    "PRESENT_QUERIES",
    "SYNTHETIC_LABELS",
    "archived_frames",
    "ask",
    "ask_all",
    "build_map",
    "sightings_for",
    "synthesized_frames",
]
