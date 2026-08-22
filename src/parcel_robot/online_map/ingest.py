"""The one sanctioned seam from C-1's detection stream into the map.

Why a seam rather than an import
--------------------------------
C-1's :class:`~parcel_robot.camera_channel.ingress.CameraDetectionRecord` is,
in its own words, "deliberately NOT the navigator's candidate dict: that shape
exists to be consumed as *grounding authority*, and C-1 publishes
*observations*." This module is where an observation is converted into
something the map may write down, and it is the only such place. Everything the
map is entitled to assume — that the geometry was checked, that the label was
normalized, that hygiene inputs were attached — is established here, once.

The freshness question C-1 left open
------------------------------------
C-1 measured, and reported as a pre-registered miss, that **every frame is
expired at publish on CPU** (capture-start -> publish p50 562.6 ms against a
300 ms TTL; 16/16 retained frames ``expired_at_publish``). Its own §7.1 says
the stream "is not fit for C-2 authority as measured."

That is a statement about *authority*, not about *mapping*, and the difference
matters. A stale frame is fatal to a reactive claim ("is there a person in
front of me right now") and largely harmless to a cumulative one ("there is a
lamppost at this corner"), because a lamppost that was there 600 ms ago is
still there. So :func:`observations_from_frame` accepts expired frames by
default and **stamps every observation with the frame's own expiry state**, and
:func:`map_freshness_report` counts them. The map is honest about being built
from stale pixels rather than pretending they were fresh — and a caller that
wants the strict reading passes ``require_fresh=True`` and gets nothing, which
is the correct answer for authority and the wrong one for a map.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .entries import EmbeddingStamp, MapObservation, WriterProvenance
from .hygiene import metric_extents, relief_from_depth_patch

#: Nominal D455 colour intrinsics, imported read-only from the camera channel so
#: the map's metric-size gate and the localizer cannot disagree about focal
#: length. Resolved lazily to keep this module import-cheap.
_INTRINSICS_CACHE: dict[str, tuple[float, float]] = {}


def default_focal_lengths() -> tuple[float, float]:
    """``(fx, fy)`` from the shipped D455 calibration. Read-only."""

    if "d455" not in _INTRINSICS_CACHE:
        from parcel_robot.camera_channel import d455_color_intrinsics

        intr = d455_color_intrinsics()
        _INTRINSICS_CACHE["d455"] = (float(intr.fx), float(intr.fy))
    return _INTRINSICS_CACHE["d455"]


def observation_from_record(
    record: Any,
    *,
    frame: Any,
    visit_id: str,
    provenance: WriterProvenance,
    fx: float | None = None,
    fy: float | None = None,
    embedding: Sequence[float] | None = None,
    embedding_stamp: EmbeddingStamp | None = None,
    thumbnail: bytes | None = None,
    depth_patch: Any = None,
) -> MapObservation:
    """Convert one ``CameraDetectionRecord`` + its frame into a MapObservation.

    ``record`` and ``frame`` are duck-typed rather than isinstance-checked so
    that fixtures can drive this seam without constructing the whole ingress —
    which is what makes C-2's tests offline-first. Every field read here is
    part of C-1's published contract.

    ``depth_patch``, when given, is the depth crop under the detection box; it
    is the ONLY source of a real relief measurement. Absent, the observation
    carries ``relief_m=None`` and the map marks the resulting entry
    ``relief_unverified`` rather than assuming solidity.
    """

    focal_x, focal_y = default_focal_lengths()
    if fx is not None:
        focal_x = float(fx)
    if fy is not None:
        focal_y = float(fy)

    width_m, height_m = metric_extents(
        record.box, float(record.depth_m), fx=focal_x, fy=focal_y
    )

    relief_m: float | None = None
    relief_samples = 0
    if depth_patch is not None:
        relief_m, relief_samples = relief_from_depth_patch(depth_patch)

    return MapObservation(
        label=str(record.label),
        score=float(record.score),
        surface_x=float(record.world_x),
        surface_y=float(record.world_y),
        surface_z=float(record.world_z),
        range_m=float(record.range_m),
        bearing_rad=float(record.bearing_rad),
        depth_m=float(record.depth_m),
        extent_w_m=width_m,
        extent_h_m=height_m,
        inlier_pixels=int(record.inlier_pixels),
        frame_id=str(frame.frame_id),
        visit_id=str(visit_id),
        observed_wall_s=float(frame.published_wall_s),
        robot_x=float(frame.robot_x),
        robot_y=float(frame.robot_y),
        provenance=provenance,
        embedding=(tuple(float(v) for v in embedding) if embedding is not None else None),
        embedding_stamp=embedding_stamp,
        thumbnail=thumbnail,
        relief_m=relief_m,
        relief_samples=relief_samples,
    )


def observations_from_frame(
    frame: Any,
    *,
    visit_id: str,
    provenance: WriterProvenance,
    require_fresh: bool = False,
    depth_patches: Mapping[int, Any] | None = None,
    **kwargs: Any,
) -> tuple[MapObservation, ...]:
    """Every detection in one frame, converted. Empty frames yield ``()``.

    An empty frame is a real observation and callers are expected to call
    ``OnlineSemanticMap.note_frame()`` for it regardless — "looked and saw
    nothing" is the denominator that makes detector support honest.
    """

    if require_fresh and bool(getattr(frame, "expired_at_publish", False)):
        return ()
    patches = depth_patches or {}
    out: list[MapObservation] = []
    for index, record in enumerate(frame.detections):
        out.append(
            observation_from_record(
                record,
                frame=frame,
                visit_id=visit_id,
                provenance=provenance,
                depth_patch=patches.get(index),
                **kwargs,
            )
        )
    return tuple(out)


def map_freshness_report(frames: Iterable[Any]) -> dict[str, Any]:
    """How stale were the pixels this map was built from?

    Reported next to every map claim in the status doc. The map does not get to
    be silently built out of expired frames.
    """

    total = 0
    expired = 0
    latencies: list[float] = []
    for frame in frames:
        total += 1
        if bool(getattr(frame, "expired_at_publish", False)):
            expired += 1
        latency = getattr(frame, "publish_latency_ns", None)
        if latency is not None:
            latencies.append(float(latency) / 1e6)
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else None
    return {
        "frames": total,
        "expired_at_publish": expired,
        "expired_fraction": (expired / total) if total else 0.0,
        "publish_latency_p50_ms": (round(p50, 3) if p50 is not None else None),
    }


__all__ = [
    "default_focal_lengths",
    "map_freshness_report",
    "observation_from_record",
    "observations_from_frame",
]
