"""Sim → DetectionMsg bridge (Opus wiring over Sol DetectionNoiseAdapter).

Privileged GT may be built inside scorer/test helpers. The **agent path**
always returns noisy ``DetectionMsg`` from ``DetectionNoiseAdapter`` — never
raw oracle tracks.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from parcel_robot.contracts import DetectionMsg
from parcel_robot.detection_adapter.adapter import (
    DetectionNoiseAdapter,
    GroundTruthDetection,
)
from parcel_robot.detection_adapter.noise import DetectionNoiseConfig, default_person_confusion

DOES_NOT_PROVE = (
    "Sim DetectionMsg noise is Habitat-style honesty for hillclimb rung-7, not a "
    "fitted field detector (HR-4 / K5).",
    "Privileged GT helpers are scorer/test-only; agent path must consume adapter output.",
)

_DEFAULT_EMBED_DIMS = 8


@dataclass(frozen=True, slots=True)
class SimTrackObservation:
    """Minimal track shape for the bridge (avoids hard backend import)."""

    track_id: str
    class_id: str
    x: float
    y: float
    z: float = 0.0
    score: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.track_id, str) or not self.track_id:
            raise ValueError("track_id must be non-empty")
        if not isinstance(self.class_id, str) or not self.class_id:
            raise ValueError("class_id must be non-empty")
        for name, value in (("x", self.x), ("y", self.y), ("z", self.z), ("score", self.score)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("score must be in [0, 1]")


def label_embedding(class_id: str, *, dims: int = _DEFAULT_EMBED_DIMS) -> tuple[float, ...]:
    """Deterministic unit-ish embedding from class id (no vision model)."""

    if not isinstance(class_id, str) or not class_id:
        raise ValueError("class_id must be non-empty")
    if isinstance(dims, bool) or not isinstance(dims, int) or dims < 1 or dims > 2048:
        raise ValueError("dims must be in 1..2048")
    digest = hashlib.sha256(class_id.encode("utf-8")).digest()
    values: list[float] = []
    for i in range(dims):
        # Map bytes to [-1, 1].
        values.append((digest[i % len(digest)] / 127.5) - 1.0)
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return tuple(v / norm for v in values)


def track_from_semantic_object(obj: Any) -> SimTrackObservation:
    """Lift ``SemanticObjectTrack`` (or duck-typed equivalent) to SimTrackObservation."""

    object_id = str(getattr(obj, "object_id"))
    label = str(getattr(obj, "label"))
    position = getattr(obj, "position")
    confidence = float(getattr(obj, "confidence", 1.0))
    return SimTrackObservation(
        track_id=object_id,
        class_id=label,
        x=float(position[0]),
        y=float(position[1]),
        z=float(position[2]) if len(position) > 2 else 0.0,
        score=confidence,
    )


def track_from_owner(owner: Any, *, class_id: str = "owner") -> SimTrackObservation | None:
    """Lift ``OwnerTrack`` when visible; otherwise None."""

    if not bool(getattr(owner, "visible", False)):
        return None
    return SimTrackObservation(
        track_id=str(getattr(owner, "owner_id", "owner-1")),
        class_id=class_id,
        x=float(getattr(owner, "x")),
        y=float(getattr(owner, "y")),
        z=0.0,
        score=float(getattr(owner, "confidence", 1.0)),
    )


def bearing_range_from_pose(
    *,
    robot_x: float,
    robot_y: float,
    robot_yaw_rad: float,
    target_x: float,
    target_y: float,
) -> tuple[float, float]:
    """Body-relative bearing ([-π, π]) and planar range."""

    dx = float(target_x) - float(robot_x)
    dy = float(target_y) - float(robot_y)
    range_m = math.hypot(dx, dy)
    world_bearing = math.atan2(dy, dx)
    bearing = (world_bearing - float(robot_yaw_rad) + math.pi) % (2.0 * math.pi) - math.pi
    return bearing, range_m


def privileged_gt_from_tracks(
    tracks: Sequence[SimTrackObservation | Mapping[str, object] | Any],
    *,
    robot_x: float,
    robot_y: float,
    robot_yaw_rad: float,
    embed_dims: int = _DEFAULT_EMBED_DIMS,
) -> list[GroundTruthDetection]:
    """Scorer/test helper: oracle tracks → ``GroundTruthDetection``.

    Must not be fed to the agent decision path without the noise adapter.
    """

    out: list[GroundTruthDetection] = []
    for raw in tracks:
        track = _coerce_track(raw)
        bearing, range_m = bearing_range_from_pose(
            robot_x=robot_x,
            robot_y=robot_y,
            robot_yaw_rad=robot_yaw_rad,
            target_x=track.x,
            target_y=track.y,
        )
        out.append(
            GroundTruthDetection(
                class_id=track.class_id,
                embedding=label_embedding(track.class_id, dims=embed_dims),
                bearing_rad=bearing,
                range_m=range_m,
                track_id=track.track_id,
                score=track.score,
            )
        )
    return out


def detections_for_agent(
    tracks: Sequence[SimTrackObservation | Mapping[str, object] | Any],
    *,
    robot_x: float,
    robot_y: float,
    robot_yaw_rad: float,
    rng: random.Random,
    received_monotonic_ns: int,
    adapter: DetectionNoiseAdapter | None = None,
    source_timestamp_ns: int | None = None,
    scene_revision: int = 0,
    embed_dims: int = _DEFAULT_EMBED_DIMS,
) -> list[DetectionMsg]:
    """Agent path: privileged GT → ``DetectionNoiseAdapter`` → DetectionMsg."""

    noise = adapter or DetectionNoiseAdapter(
        DetectionNoiseConfig(confusion=default_person_confusion())
    )
    gt = privileged_gt_from_tracks(
        tracks,
        robot_x=robot_x,
        robot_y=robot_y,
        robot_yaw_rad=robot_yaw_rad,
        embed_dims=embed_dims,
    )
    return noise.adapt_ground_truth(
        gt,
        rng=rng,
        received_monotonic_ns=received_monotonic_ns,
        source_timestamp_ns=source_timestamp_ns,
        scene_revision=scene_revision,
        evidence_id_prefix="sim-det",
    )


def detections_from_observation(
    observation: Any,
    *,
    rng: random.Random,
    received_monotonic_ns: int,
    adapter: DetectionNoiseAdapter | None = None,
    include_owner: bool = True,
    source_timestamp_ns: int | None = None,
) -> list[DetectionMsg]:
    """Convenience: ``SimObservation`` semantic objects (+ owner) → agent detections."""

    robot = getattr(observation, "robot")
    tracks: list[SimTrackObservation] = []
    for obj in getattr(observation, "semantic_objects", ()) or ():
        tracks.append(track_from_semantic_object(obj))
    if include_owner:
        owner = getattr(observation, "owner", None)
        if owner is not None:
            lifted = track_from_owner(owner)
            if lifted is not None:
                tracks.append(lifted)
    ts = source_timestamp_ns
    if ts is None:
        # Convert observation timestamp seconds → ns when present.
        raw_ts = getattr(observation, "timestamp", None)
        if isinstance(raw_ts, (int, float)) and math.isfinite(float(raw_ts)):
            ts = int(float(raw_ts) * 1e9)
    return detections_for_agent(
        tracks,
        robot_x=float(robot.x),
        robot_y=float(robot.y),
        robot_yaw_rad=float(robot.yaw),
        rng=rng,
        received_monotonic_ns=received_monotonic_ns,
        adapter=adapter,
        source_timestamp_ns=ts,
    )


def _coerce_track(raw: SimTrackObservation | Mapping[str, object] | Any) -> SimTrackObservation:
    if isinstance(raw, SimTrackObservation):
        return raw
    if isinstance(raw, Mapping):
        if "position" in raw:
            pos = raw["position"]
            x, y = float(pos[0]), float(pos[1])
            z = float(pos[2]) if len(pos) > 2 else float(raw.get("z", 0.0))
        else:
            x, y, z = float(raw["x"]), float(raw["y"]), float(raw.get("z", 0.0))
        return SimTrackObservation(
            track_id=str(raw.get("track_id") or raw.get("object_id") or raw["id"]),
            class_id=str(raw.get("class_id") or raw.get("label")),
            x=x,
            y=y,
            z=z,
            score=float(raw.get("score", raw.get("confidence", 1.0))),
        )
    if hasattr(raw, "object_id") and hasattr(raw, "label") and hasattr(raw, "position"):
        return track_from_semantic_object(raw)
    if hasattr(raw, "owner_id") and hasattr(raw, "x") and hasattr(raw, "y"):
        lifted = track_from_owner(raw)
        if lifted is None:
            raise ValueError("owner track is not visible")
        return lifted
    raise TypeError(f"unsupported track type: {type(raw)!r}")
