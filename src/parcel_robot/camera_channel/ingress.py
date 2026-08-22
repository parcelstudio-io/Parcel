"""Camera-ingress wiring: put the DETECTOR on the mission path (Card B4).

This is the seam that makes the dog **search with its camera** instead of reading
the ground-truth frustum oracle. It renders RGB(+depth) through the proven
:class:`~parcel_robot.camera_channel.backends.mujoco_egl.MujocoEglCameraBackend`,
runs an open-vocab :class:`~parcel_robot.detection_adapter.pixel_detections.Detector`
(the B3 :class:`OwlV2Detector`) for the *active semantic goal*, localizes each box to
a metric world point via ``localize_frame`` (B2), and turns those
:class:`LocalizedDetection` rows into the SAME ``semantic_candidates`` dict payload
the navigator's grounding already consumes — only now sourced from **pixels**, not
the ``SimObservation`` oracle.

Placement — off the reactive 10 Hz path
---------------------------------------
OWLv2 costs ~559 ms/query on CPU (B3), so it must never run inline on the reactive
control tick. :class:`CameraIngress` runs the render→detect→localize pipeline on a
**background worker** at a bounded cadence and publishes the latest candidate list to
a lock-guarded buffer. The runtime's 10 Hz path only ever calls
:meth:`latest_candidates` (a non-blocking snapshot read) and :meth:`set_pose` /
:meth:`set_query` (cheap setters). The reactive gate + A* consume whatever the
detector last PROPOSED; they never wait on a detection.

Thread-safety / MuJoCo
----------------------
The worker renders from its **own** ``MjData`` (a static, once-forwarded copy of the
scene) so it never races the control loop's live ``MjData``. The free camera is
placed from the robot pose passed to ``capture(...)`` — objects are static, the
camera moves — so a separate data buffer renders the correct scene from the current
mount pose without touching the simulation's physics state.

EGL-before-import constraint
----------------------------
``MUJOCO_GL`` binds the offscreen GL backend at the **first** ``import mujoco`` in a
process and cannot change afterwards. :class:`CameraIngress` imports MuJoCo (via the
backend) only when constructed, so the *entry point* that builds the ingress must set
``MUJOCO_GL=egl`` before it — the runtime never imports MuJoCo itself, keeping the
constraint at the sim/gate boundary where the model/data already live.

HONESTY (P0)
------------
Rendered MuJoCo textures are NOT photoreal, so OWLv2 recall here tests the
pixels→localize→ground→lock-on pipeline + a FLOOR of recognition, not real-world D455
recognition (a hardware re-earn). No field recall/precision is claimed.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.authority import DEFAULT_STAND_OFF_ENVELOPE

logger = logging.getLogger(__name__)

#: Card C-1. Detection freshness budget, mirroring
#: ``contracts.freshness.DEFAULT_DETECTION_TTL_NS`` (300 ms) and
#: ``perception_contention.DETECTION_TTL_MS``. Imported as a plain constant so
#: this module stays importable without the contracts package, exactly as the
#: contention guard does it. A frame published later than this after its own
#: capture STARTED is expired on arrival — and says so about itself rather than
#: being silently treated as current.
DEFAULT_DETECTION_TTL_NS = 300_000_000

#: Hard ceiling on detections retained per frame. The queue is bounded in
#: frames; without a per-frame cap one pathological frame could still carry an
#: unbounded row count into the runtime and the evidence log.
MAX_RETAINED_DETECTIONS = 256

#: Default worker cadence floor. OWLv2 detect itself is ~559 ms, so the effective
#: rate is detector-bound; this only caps the *minimum* gap between polls so the
#: worker never busy-spins and stays comfortably off the 10 Hz reactive path.
DEFAULT_MIN_POLL_INTERVAL_S = 0.25

#: Candidate source tag so downstream logging / the arbiter can tell a pixel
#: proposal apart from the GT-frustum oracle.
PIXEL_SOURCE = "pixel_detector"

#: The detector query the camera channel may never stop asking. Card P0-D.
#:
#: ``CameraStreamConfig.from_section`` already refuses a configured batch that
#: does not name the whole word "person": a camera that never asks about people
#: must not claim the person-relevant admission path (PG-1's safety lease), and
#: ``patrol/mission.py`` requires it. That check guards the CONFIG. It did not
#: guard :meth:`CameraIngress.set_query`, which *replaced* the batch — so one
#: navigation directive ("go to the bench") took the lease away at runtime,
#: measured and reported by card MOVE-1. The pin below is that same rule,
#: applied where the batch is actually set.
#:
#: Matched as a WHOLE WORD, exactly as the config check matches it, so a batch
#: that already says "a person" is satisfied and "personnel carrier" is not.
SAFETY_LEASE_QUERY = "person"

#: Arrival / clearance metadata stamped on pixel candidates.
#:
#: These are read by the SAME approach planner and terminal verifier that consume
#: ``city_semantics`` object metadata, so a pixel candidate and a GT-oracle
#: candidate must describe the same physical bands. They were introduced as bare
#: literals duplicating values ``parcel_robot.authority`` already owns; Fable's
#: independent audit of task_15 flagged that (the no-literal-drift ratchet did not
#: yet scan this tree). They now DERIVE, so re-tuning the envelope moves the pixel
#: path with everything else instead of leaving it silently pinned to old numbers.
_PIXEL_ARRIVAL_RADIUS_M = DEFAULT_STAND_OFF_ENVELOPE.arrival_radius_m
_PIXEL_TARGET_MIN_SURFACE_CLEARANCE_M = DEFAULT_STAND_OFF_ENVELOPE.target_surface_clearance_m
_PIXEL_TERMINAL_SUPPORT_CLEARANCE_M = DEFAULT_STAND_OFF_ENVELOPE.footprint_radius_m

#: The one band that does NOT derive, deliberately and for a measured reason.
#:
#: ``city_semantics`` stamps 1.25 for non-target obstacles. That is the stand-off
#: composite plus commissioning margin, but the composite is NOT 1.25 in IEEE-754:
#: ``DEFAULT_STAND_OFF_ENVELOPE.stand_off(0.0)`` is ``1.2200000000000002`` in the
#: authority's canonical left-to-right association, so ``stand_off(0.0) + 0.03``
#: is ``1.2500000000000002`` — NOT equal to the ``1.25`` the oracle path stamps.
#: A pixel candidate and a GT-oracle candidate for the same object would then
#: carry different clearances and compare unequal. Reassociating the sum until it
#: happens to land on 1.25 would be derivation theatre, so the literal stays and
#: is allowlisted by name in ``tests/test_authority_no_literal_drift.py``, exactly
#: as ``city_semantics.py``'s own 1.25 already is. Owner: the scene-metadata /
#: sidecar lane, which owns both copies and must retire them together.
_PIXEL_NON_TARGET_OBSTACLE_CLEARANCE_M = 1.25


def radius_m_from_box_depth(
    box: Sequence[int] | Sequence[float],
    depth_m: float,
    fx: float,
) -> float:
    """Honest object footprint radius from detection box angular width × depth / 2.

    Half the larger box side in pixels, back-projected at the localized depth
    through the camera's horizontal focal length: ``r = (side_px / 2) * D / fx``.
    That is the planar footprint a sphere (or the object's projected half-width)
    subtends at that range — the same lever city objects get from geom size.
    """

    if len(box) != 4:
        raise ValueError("box must be (u0, v0, u1, v1)")
    u0, v0, u1, v1 = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    depth = float(depth_m)
    focal = float(fx)
    if not math.isfinite(depth) or depth <= 0.0:
        raise ValueError("depth_m must be finite and positive")
    if not math.isfinite(focal) or focal <= 0.0:
        raise ValueError("fx must be finite and positive")
    half_w = 0.5 * abs(u1 - u0)
    half_h = 0.5 * abs(v1 - v0)
    return max(0.0, max(half_w, half_h) * depth / focal)


def _near_envelope_metadata(radius_m: float, label: str) -> dict[str, Any]:
    """City-object near-envelope field set, derived from an honest footprint.

    Consumes :func:`instructnav.scoring.object_near_envelope_m` (read-only) so
    approach planning and arrival verification cannot disagree with city objects.
    """

    from parcel_robot.instructnav.scoring import object_near_envelope_m

    radius = max(0.0, float(radius_m))
    stand_off, minimum, vicinity = object_near_envelope_m(radius, label=label)
    return {
        "radius_m": round(radius, 4),
        "stand_off_m": float(stand_off),
        "arrival_radius_m": _PIXEL_ARRIVAL_RADIUS_M,
        "minimum_vicinity_radius_m": float(minimum),
        "vicinity_radius_m": float(vicinity),
        "target_min_surface_clearance_m": _PIXEL_TARGET_MIN_SURFACE_CLEARANCE_M,
        "non_target_obstacle_clearance_m": _PIXEL_NON_TARGET_OBSTACLE_CLEARANCE_M,
        "terminal_support_clearance_m": _PIXEL_TERMINAL_SUPPORT_CLEARANCE_M,
    }


def _front_surface_world_xy(
    box: Sequence[int] | Sequence[float],
    depth: Any,
    *,
    intrinsics: Any,
    extrinsics: Any,
    depth_min_m: float,
    depth_max_m: float,
) -> tuple[float, float, float] | None:
    """Back-project the box centre at the FRONT (min valid) depth.

    Median-inlier depth (what ``localize_detection`` uses) sits inside curved
    bodies; the near-envelope treats ``position`` as the object CENTRE, so the
    surface point used for centre recovery must be the nearest face.
    """

    import numpy as np

    from parcel_robot.detection_adapter.pixel_detections import back_project

    depth_arr = np.asarray(depth, dtype=np.float64)
    if depth_arr.ndim != 2:
        return None
    h, w = depth_arr.shape
    u0 = max(0, min(int(box[0]), w))
    u1 = max(0, min(int(box[2]), w))
    v0 = max(0, min(int(box[1]), h))
    v1 = max(0, min(int(box[3]), h))
    if u1 <= u0 or v1 <= v0:
        return None
    patch = depth_arr[v0:v1, u0:u1]
    valid = np.isfinite(patch) & (patch > max(0.0, float(depth_min_m)))
    if math.isfinite(float(depth_max_m)):
        valid &= patch <= float(depth_max_m)
    if not valid.any():
        return None
    front_d = float(patch[valid].min())
    u_c = 0.5 * (u0 + u1)
    v_c = 0.5 * (v0 + v1)
    world = extrinsics.camera_to_world(back_project(u_c, v_c, front_d, intrinsics))
    return (float(world[0]), float(world[1]), front_d)


def _bounded_text(value: object, name: str, *, limit: int = 128) -> str:
    text = str(value)
    if not text:
        raise ValueError(f"{name} must be non-empty")
    if len(text) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    return text


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _nonneg_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class CameraDetectionRecord:
    """One localized open-vocab detection, as the runtime stream carries it.

    Card C-1. This is deliberately NOT the navigator's candidate dict: that
    shape exists to be consumed as *grounding authority*, and C-1 publishes
    *observations*. Keeping them separate types is what stops a diagnostic
    stream from being mistaken for a map fact by a later reader.
    """

    label: str
    score: float
    box: tuple[float, float, float, float]
    world_x: float
    world_y: float
    world_z: float
    range_m: float
    bearing_rad: float
    depth_m: float
    sigma_range_m: float
    inlier_pixels: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _bounded_text(self.label, "label", limit=64))
        score = _finite_float(self.score, "score")
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be within [0, 1]")
        object.__setattr__(self, "score", score)
        box = tuple(_finite_float(v, "box") for v in self.box)
        if len(box) != 4:
            raise ValueError("box must be (u0, v0, u1, v1)")
        object.__setattr__(self, "box", box)
        for name in (
            "world_x",
            "world_y",
            "world_z",
            "range_m",
            "bearing_rad",
            "depth_m",
            "sigma_range_m",
        ):
            object.__setattr__(self, name, _finite_float(getattr(self, name), name))
        if self.range_m < 0.0 or self.depth_m < 0.0 or self.sigma_range_m < 0.0:
            raise ValueError("range/depth/sigma must be non-negative")
        object.__setattr__(
            self, "inlier_pixels", _nonneg_int(self.inlier_pixels, "inlier_pixels")
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "score": round(self.score, 6),
            "box": [round(v, 3) for v in self.box],
            "world_x": round(self.world_x, 4),
            "world_y": round(self.world_y, 4),
            "world_z": round(self.world_z, 4),
            "range_m": round(self.range_m, 4),
            "bearing_rad": round(self.bearing_rad, 4),
            "depth_m": round(self.depth_m, 4),
            "sigma_range_m": round(self.sigma_range_m, 4),
            "inlier_pixels": self.inlier_pixels,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CameraDetectionRecord:
        if not isinstance(value, Mapping):
            raise TypeError("detection record must be a mapping")
        expected = {
            "label",
            "score",
            "box",
            "world_x",
            "world_y",
            "world_z",
            "range_m",
            "bearing_rad",
            "depth_m",
            "sigma_range_m",
            "inlier_pixels",
        }
        unknown = set(value) - expected
        if unknown:
            raise ValueError(f"unknown detection keys: {sorted(unknown)}")
        missing = expected - set(value)
        if missing:
            raise ValueError(f"missing detection keys: {sorted(missing)}")
        box = value["box"]
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ValueError("box must be a 4-sequence")
        return cls(
            label=str(value["label"]),
            score=float(value["score"]),
            box=(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
            world_x=float(value["world_x"]),
            world_y=float(value["world_y"]),
            world_z=float(value["world_z"]),
            range_m=float(value["range_m"]),
            bearing_rad=float(value["bearing_rad"]),
            depth_m=float(value["depth_m"]),
            sigma_range_m=float(value["sigma_range_m"]),
            inlier_pixels=int(value["inlier_pixels"]),
        )


@dataclass(frozen=True, slots=True)
class CameraDetectionFrame:
    """One completed render→detect→localize cycle, timestamped and camera-posed.

    Card C-1, work item 2. Every field here answers a question an auditor would
    otherwise have to guess at: WHEN the pixels were captured (not when the
    answer arrived), WHERE the camera was, WHAT was asked, WHICH provider
    answered, and HOW MANY detections were dropped on the way. A frame with
    zero detections is a real observation and is published like any other — an
    empty frame is evidence of looking and seeing nothing, which is not the
    same as not looking.
    """

    frame_id: str
    sequence: int
    source_timestamp_ns: int
    capture_started_monotonic_ns: int
    capture_completed_monotonic_ns: int
    published_monotonic_ns: int
    published_wall_s: float
    detection_ttl_ns: int
    width_px: int
    height_px: int
    robot_x: float
    robot_y: float
    robot_yaw_rad: float
    queries: tuple[str, ...]
    detections: tuple[CameraDetectionRecord, ...]
    raw_detections: int
    localized_detections: int
    rejected_detections: int
    truncated_detections: int
    render_ms: float
    detect_ms: float
    total_ms: float
    detector_name: str
    provider_profile: str
    active_providers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "frame_id", _bounded_text(self.frame_id, "frame_id"))
        object.__setattr__(
            self, "detector_name", _bounded_text(self.detector_name, "detector_name")
        )
        object.__setattr__(
            self,
            "provider_profile",
            _bounded_text(self.provider_profile, "provider_profile"),
        )
        for name in (
            "sequence",
            "source_timestamp_ns",
            "capture_started_monotonic_ns",
            "capture_completed_monotonic_ns",
            "published_monotonic_ns",
            "detection_ttl_ns",
            "raw_detections",
            "localized_detections",
            "rejected_detections",
            "truncated_detections",
        ):
            object.__setattr__(self, name, _nonneg_int(getattr(self, name), name))
        for name in ("width_px", "height_px"):
            value = _nonneg_int(getattr(self, name), name)
            if value < 1:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        for name in (
            "published_wall_s",
            "robot_x",
            "robot_y",
            "robot_yaw_rad",
            "render_ms",
            "detect_ms",
            "total_ms",
        ):
            object.__setattr__(self, name, _finite_float(getattr(self, name), name))
        if self.render_ms < 0.0 or self.detect_ms < 0.0 or self.total_ms < 0.0:
            raise ValueError("latencies must be non-negative")
        if self.capture_completed_monotonic_ns < self.capture_started_monotonic_ns:
            raise ValueError("capture cannot complete before it starts")
        if self.published_monotonic_ns < self.capture_completed_monotonic_ns:
            raise ValueError("a frame cannot publish before its capture completes")
        queries = tuple(_bounded_text(q, "query", limit=64) for q in self.queries)
        if not queries:
            raise ValueError("a frame must record the query batch it answered")
        if len(queries) > 16:
            raise ValueError("query batch exceeds 16 phrases")
        object.__setattr__(self, "queries", queries)
        detections = tuple(self.detections)
        for item in detections:
            if not isinstance(item, CameraDetectionRecord):
                raise TypeError("detections must be CameraDetectionRecord")
        if len(detections) > MAX_RETAINED_DETECTIONS:
            raise ValueError("retained detections exceed the per-frame ceiling")
        object.__setattr__(self, "detections", detections)
        if len(detections) + self.truncated_detections != self.localized_detections:
            raise ValueError(
                "retained + truncated detections must equal the localized count; "
                "a frame that loses rows without counting them is not evidence"
            )
        if self.localized_detections + self.rejected_detections != self.raw_detections:
            raise ValueError("localized + rejected must equal the raw detection count")
        providers = tuple(
            _bounded_text(p, "active_provider", limit=64) for p in self.active_providers
        )
        if len(providers) > 8:
            raise ValueError("active_providers exceeds 8 entries")
        object.__setattr__(self, "active_providers", providers)

    # -- freshness, measured against the frame's OWN clocks ------------------
    @property
    def publish_latency_ns(self) -> int:
        """Capture-START to publish. The honest age of the pixels on arrival."""

        return self.published_monotonic_ns - self.capture_started_monotonic_ns

    @property
    def expired_at_publish(self) -> bool:
        """True when the pixels were already past TTL the moment they landed.

        Deliberately computed from capture START, not from capture completion
        or publish time. Measuring age from the moment the ANSWER appeared
        would make every frame look fresh and would be a causality corruption,
        not an optimisation.
        """

        return self.publish_latency_ns > self.detection_ttl_ns

    def age_ns(self, now_monotonic_ns: int) -> int:
        return int(now_monotonic_ns) - self.capture_started_monotonic_ns

    def is_expired(self, now_monotonic_ns: int) -> bool:
        return self.age_ns(now_monotonic_ns) > self.detection_ttl_ns

    def class_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.detections:
            counts[record.label] = counts.get(record.label, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "sequence": self.sequence,
            "source_timestamp_ns": self.source_timestamp_ns,
            "capture_started_monotonic_ns": self.capture_started_monotonic_ns,
            "capture_completed_monotonic_ns": self.capture_completed_monotonic_ns,
            "published_monotonic_ns": self.published_monotonic_ns,
            "published_wall_s": round(self.published_wall_s, 6),
            "detection_ttl_ns": self.detection_ttl_ns,
            "publish_latency_ms": round(self.publish_latency_ns / 1e6, 3),
            "expired_at_publish": self.expired_at_publish,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "robot_x": round(self.robot_x, 4),
            "robot_y": round(self.robot_y, 4),
            "robot_yaw_rad": round(self.robot_yaw_rad, 4),
            "queries": list(self.queries),
            "detections": [record.as_dict() for record in self.detections],
            "raw_detections": self.raw_detections,
            "localized_detections": self.localized_detections,
            "rejected_detections": self.rejected_detections,
            "truncated_detections": self.truncated_detections,
            "render_ms": round(self.render_ms, 3),
            "detect_ms": round(self.detect_ms, 3),
            "total_ms": round(self.total_ms, 3),
            "detector_name": self.detector_name,
            "provider_profile": self.provider_profile,
            "active_providers": list(self.active_providers),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CameraDetectionFrame:
        """Exact-key decode. Derived fields are recomputed, never trusted."""

        if not isinstance(value, Mapping):
            raise TypeError("frame must be a mapping")
        derived = {"publish_latency_ms", "expired_at_publish"}
        required = {
            "frame_id",
            "sequence",
            "source_timestamp_ns",
            "capture_started_monotonic_ns",
            "capture_completed_monotonic_ns",
            "published_monotonic_ns",
            "published_wall_s",
            "detection_ttl_ns",
            "width_px",
            "height_px",
            "robot_x",
            "robot_y",
            "robot_yaw_rad",
            "queries",
            "detections",
            "raw_detections",
            "localized_detections",
            "rejected_detections",
            "truncated_detections",
            "render_ms",
            "detect_ms",
            "total_ms",
            "detector_name",
            "provider_profile",
            "active_providers",
        }
        unknown = set(value) - required - derived
        if unknown:
            raise ValueError(f"unknown frame keys: {sorted(unknown)}")
        missing = required - set(value)
        if missing:
            raise ValueError(f"missing frame keys: {sorted(missing)}")
        detections = value["detections"]
        if not isinstance(detections, (list, tuple)):
            raise TypeError("detections must be a sequence")
        queries = value["queries"]
        if not isinstance(queries, (list, tuple)):
            raise TypeError("queries must be a sequence")
        providers = value["active_providers"]
        if not isinstance(providers, (list, tuple)):
            raise TypeError("active_providers must be a sequence")
        return cls(
            frame_id=str(value["frame_id"]),
            sequence=int(value["sequence"]),
            source_timestamp_ns=int(value["source_timestamp_ns"]),
            capture_started_monotonic_ns=int(value["capture_started_monotonic_ns"]),
            capture_completed_monotonic_ns=int(value["capture_completed_monotonic_ns"]),
            published_monotonic_ns=int(value["published_monotonic_ns"]),
            published_wall_s=float(value["published_wall_s"]),
            detection_ttl_ns=int(value["detection_ttl_ns"]),
            width_px=int(value["width_px"]),
            height_px=int(value["height_px"]),
            robot_x=float(value["robot_x"]),
            robot_y=float(value["robot_y"]),
            robot_yaw_rad=float(value["robot_yaw_rad"]),
            queries=tuple(str(q) for q in queries),
            detections=tuple(
                CameraDetectionRecord.from_mapping(item) for item in detections
            ),
            raw_detections=int(value["raw_detections"]),
            localized_detections=int(value["localized_detections"]),
            rejected_detections=int(value["rejected_detections"]),
            truncated_detections=int(value["truncated_detections"]),
            render_ms=float(value["render_ms"]),
            detect_ms=float(value["detect_ms"]),
            total_ms=float(value["total_ms"]),
            detector_name=str(value["detector_name"]),
            provider_profile=str(value["provider_profile"]),
            active_providers=tuple(str(p) for p in providers),
        )


@dataclass
class IngressStats:
    """Cheap health/telemetry for /api/ or a gate report (never blocks a read)."""

    polls: int = 0
    detections_last: int = 0
    candidates_last: int = 0
    last_latency_ms: float = 0.0
    last_detect_ms: float = 0.0
    errors: int = 0
    last_error: str | None = None
    last_query: tuple[str, ...] = ()
    reactive_reads: int = 0
    #: Card C-1. Frames handed to the runtime's publish seam, and the count of
    #: consumer callbacks that raised. A publish seam whose failures are
    #: invisible is a stream with a silent hole in it.
    frames_published: int = 0
    frame_callback_errors: int = 0
    #: Detections dropped by the per-frame retention cap, cumulative.
    detections_truncated: int = 0
    #: Cycles whose inference ran while a PG-1 mission lease was held.
    leased_inferences: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "polls": self.polls,
            "detections_last": self.detections_last,
            "candidates_last": self.candidates_last,
            "last_latency_ms": round(self.last_latency_ms, 2),
            "last_detect_ms": round(self.last_detect_ms, 2),
            "errors": self.errors,
            "last_error": self.last_error,
            "last_query": list(self.last_query),
            "reactive_reads": self.reactive_reads,
            "frames_published": self.frames_published,
            "frame_callback_errors": self.frame_callback_errors,
            "detections_truncated": self.detections_truncated,
            "leased_inferences": self.leased_inferences,
        }


@dataclass(frozen=True, slots=True)
class _Pose:
    x: float
    y: float
    yaw: float


@dataclass
class CameraIngress:
    """Async pixel→``semantic_candidates`` producer for the mission path.

    Construct with :meth:`from_model_data` (the normal path — it defers the EGL
    backend to the worker thread and loads the detector), or inject a ``backend`` +
    ``detector`` directly for a deterministic offline test. All setters are cheap and
    thread-safe; the detector only runs inside :meth:`poll_once`, never on a read.

    EGL is thread-affine: a MuJoCo GL context can only be made current on the thread
    that created it. So the backend is created **lazily on the first poll** — when
    the worker runs, the context is born on the worker thread and every render stays
    there. ``backend_factory`` (set by :meth:`from_model_data`) builds it once; an
    injected ``backend`` skips the factory entirely (offline tests, single-threaded).
    """

    backend: Any = None
    detector: Any = None
    intrinsics: Any = None
    mount: Any = None
    depth_min_m: float = 0.4
    depth_max_m: float = 6.0
    embed_fn: Callable[[Any], Sequence[float]] | None = None
    min_poll_interval_s: float = DEFAULT_MIN_POLL_INTERVAL_S
    backend_factory: Callable[[], Any] | None = None
    #: Card C-1. The runtime's bounded publish seam. Invoked once per COMPLETED
    #: cycle — including cycles that found nothing — from the worker thread and
    #: deliberately OUTSIDE ``_lock``: the consumer takes the runtime's own
    #: lock, and holding an ingress lock across a foreign lock is the lock-order
    #: edge R24's roster exists to prevent. A raising callback is counted and
    #: swallowed; a consumer bug must never kill the camera worker.
    on_frame: Callable[[CameraDetectionFrame], None] | None = None
    #: Card C-1, work item 3. PG-1's admission mechanism. While a cycle's
    #: inference runs, a mission lease is held, so ``try_admit_generation``
    #: refuses a competing generation. The detector never asks permission — it
    #: declares the window and runs. That asymmetry IS the priority pin.
    contention_guard: Any = None
    #: Card C-1. When set, the worker PULLS one fresh pose per cycle instead of
    #: the control loop PUSHING into this object. That inversion is the point:
    #: the 10 Hz safety path then never calls a producer method at all, so no
    #: amount of producer-side slowness can be in front of it. Returning
    #: ``None`` (no new pose, or a stale one) skips the capture rather than
    #: re-rendering a pose the robot has already left.
    pose_source: Callable[[], tuple[float, float, float] | None] | None = None
    #: Per-frame retention cap. Overflow is TRUNCATED and COUNTED, never
    #: silently dropped.
    max_detections_per_frame: int = 16
    detection_ttl_ns: int = DEFAULT_DETECTION_TTL_NS
    #: Card P0-D. Phrases every :meth:`set_query` keeps, whatever it is asked
    #: for — the operator's ``perception.camera_ingress_queries`` batch. A
    #: navigation directive NARROWS what the detector is looking for; it must
    #: never be able to narrow away the things the mission needs seen. Empty by
    #: default, because :data:`SAFETY_LEASE_QUERY` is pinned unconditionally and
    #: a bare ingress has no operator batch to protect.
    pinned_queries: tuple[str, ...] = ()
    # runtime state ---------------------------------------------------------
    _query: tuple[str, ...] = field(default=(), init=False)
    _pose: _Pose | None = field(default=None, init=False)
    _latest: list[dict[str, Any]] | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _seq: int = field(default=0, init=False)
    stats: IngressStats = field(default_factory=IngressStats, init=False)

    # -- construction -------------------------------------------------------
    @classmethod
    def from_model_data(
        cls,
        model: Any,
        data: Any,
        *,
        spec: Any | None = None,
        detector: Any | None = None,
        robot_body_name: str | None = None,
        class_ids: tuple[str, ...] = ("background", "object"),
        threshold: float | None = None,
        embed_fn: Callable[[Any], Sequence[float]] | None = None,
        min_poll_interval_s: float = DEFAULT_MIN_POLL_INTERVAL_S,
    ) -> CameraIngress:
        """Build the EGL backend + OWLv2 detector for an in-process MuJoCo scene.

        ``data`` should be a MuJoCo ``MjData`` the ingress may render from freely
        (a static/once-forwarded copy is ideal — the worker calls ``mj_forward``
        on it). The EGL backend is created lazily on the first poll so its GL
        context is born on whichever thread renders (the worker), never on this
        constructing thread. When ``detector`` is None it loads :class:`OwlV2Detector`
        via the opt-in ``PARCEL_OWLV2_ONNX`` env gate — and raises if it is
        unavailable, so a caller that asked for camera ingress hears about a missing
        detector loudly (that check is eager; only the GL backend is deferred).
        """

        from parcel_robot.camera_channel.channel import CameraChannelSpec

        spec = spec if spec is not None else CameraChannelSpec.d455_go2_nominal()

        def _factory() -> Any:
            from parcel_robot.camera_channel.backends.factory import open_camera_backend

            backend, kind = open_camera_backend(
                spec,
                prefer="mujoco_egl",
                model=model,
                data=data,
                class_ids=class_ids,
                robot_body_name=robot_body_name,
            )
            if kind != "mujoco_egl":  # pragma: no cover - factory raises first
                raise RuntimeError(f"camera ingress requires the mujoco_egl backend, got {kind}")
            return backend

        if detector is None:
            from parcel_robot.detection_adapter.owlv2_onnx import load_owlv2_detector

            detector = load_owlv2_detector(threshold=threshold)
            if detector is None:
                raise RuntimeError(
                    "camera ingress requested but the OWLv2 detector is unavailable "
                    "(set PARCEL_OWLV2_ONNX=1 and run scripts/fetch_owlv2.sh)"
                )

        return cls(
            backend=None,
            detector=detector,
            intrinsics=spec.intrinsics,
            mount=spec.mount,
            depth_min_m=float(spec.depth_min_m),
            # Drop the backend's depth-clip sentinel: MuJoCo clips background to
            # exactly ``depth_max_m``, so a ``<= depth_max_m`` inlier filter would
            # count that far wall as a surface and drag a thin object's box-interior
            # median depth outward. Trimming a hair below the clip excludes it.
            depth_max_m=float(spec.depth_max_m) - 1e-2,
            embed_fn=embed_fn,
            min_poll_interval_s=float(min_poll_interval_s),
            backend_factory=_factory,
        )

    def _ensure_backend(self) -> Any:
        """Build the deferred backend on the calling (worker) thread, once."""

        backend = self.backend
        if backend is not None:
            return backend
        factory = self.backend_factory
        if factory is None:
            raise RuntimeError("camera ingress has no backend and no backend_factory")
        backend = factory()
        self.backend = backend
        return backend

    # -- cheap thread-safe setters (called from the 10 Hz path) -------------
    def set_query(self, query: str | Sequence[str] | None) -> None:
        """Set the active open-vocab query, UNIONED with the pinned batch.

        Card P0-D. A caller asking for one noun is asking the detector to look
        for that noun *as well*, not to stop looking for everything else: the
        batch it would otherwise replace is the one carrying
        :data:`SAFETY_LEASE_QUERY`, and losing that at runtime is the defect
        MOVE-1 measured. So the result is :attr:`pinned_queries`, then the
        request, de-duplicated in that order, with ``person`` guaranteed
        present.

        ``None`` (and an empty request) still means *no query at all* — see
        :meth:`clear_query`. The pin protects a narrowing, not the off switch.
        """

        if query is None:
            phrases: tuple[str, ...] = ()
        elif isinstance(query, str):
            phrases = tuple(p for p in (query.strip(),) if p)
        else:
            phrases = tuple(str(q).strip() for q in query if str(q).strip())
        self._set_query_batch(self._with_pinned(phrases))

    def _with_pinned(self, phrases: tuple[str, ...]) -> tuple[str, ...]:
        """``pinned_queries`` + ``phrases``, de-duplicated, ``person`` assured."""

        if not phrases:
            return ()
        ordered: list[str] = []
        for phrase in (*self.pinned_queries, *phrases):
            text = " ".join(str(phrase).split())
            if text and text not in ordered:
                ordered.append(text)
        # Whole-word, matching CameraStreamConfig.from_section's own check, so
        # the two guards cannot disagree about what counts as asking.
        if not any(SAFETY_LEASE_QUERY in text.lower().split() for text in ordered):
            ordered.insert(0, SAFETY_LEASE_QUERY)
        return tuple(ordered)

    def _set_query_batch(self, phrases: tuple[str, ...]) -> None:
        with self._lock:
            self._query = phrases
            self.stats.last_query = phrases

    def clear_query(self) -> None:
        """Stop asking for anything. The one call the safety pin does not apply
        to: this is an operator switching the eye off, not a directive
        narrowing it, and a ``person`` that survived here would leave the
        detector polling forever."""

        self._set_query_batch(())

    def set_pose(self, x: float, y: float, yaw: float) -> None:
        """Set the mount pose the next render captures from (robot base pose)."""

        with self._lock:
            self._pose = _Pose(float(x), float(y), float(yaw))

    @property
    def has_query(self) -> bool:
        with self._lock:
            return bool(self._query)

    def latest_candidates(self) -> list[dict[str, Any]] | None:
        """Non-blocking snapshot of the most recent pixel candidates.

        Returns ``None`` when the detector has not yet produced a frame (the
        caller then keeps whatever fallback it uses). A copy is returned so the
        reactive path never mutates the published buffer.
        """

        with self._lock:
            self.stats.reactive_reads += 1
            if self._latest is None:
                return None
            return [dict(item) for item in self._latest]

    # -- the detector pipeline (worker thread only) -------------------------
    def poll_once(self) -> list[dict[str, Any]] | None:
        """Render → detect → localize → publish once. Returns the new candidates.

        Never raises: any failure is counted in :attr:`stats` and leaves the last
        good buffer in place (a transient render/detect error must not blank the
        map mid-mission). Returns ``None`` when there is no query/pose yet.
        """

        with self._lock:
            query = self._query
            pose = self._pose
        if not query or pose is None:
            return None
        try:
            candidates, frame = self._detect_and_localize(query, pose)
        except Exception as exc:  # noqa: BLE001 - a detect error must not crash the mission
            with self._lock:
                self.stats.errors += 1
                self.stats.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("camera ingress poll failed: %s", exc)
            return None
        with self._lock:
            self._latest = candidates
            self.stats.polls += 1
            self.stats.candidates_last = len(candidates)
        # Card C-1. Published OUTSIDE the ingress lock: the runtime's publish
        # seam takes the runtime's own stream lock, and taking a foreign lock
        # while holding ours would add exactly the lock-order edge R24's roster
        # forbids. A consumer that raises is counted, never propagated — the
        # camera worker outlives a broken consumer.
        if frame is not None:
            self._publish_frame(frame)
        return candidates

    def _publish_frame(self, frame: CameraDetectionFrame) -> None:
        callback = self.on_frame
        if callback is None:
            return
        try:
            callback(frame)
        except Exception as exc:  # noqa: BLE001 - a consumer must not kill the worker
            with self._lock:
                self.stats.frame_callback_errors += 1
                self.stats.last_error = f"on_frame {type(exc).__name__}: {exc}"
            logger.warning("camera ingress frame publish failed: %s", exc)
            return
        with self._lock:
            self.stats.frames_published += 1

    def _detect_and_localize(
        self, query: tuple[str, ...], pose: _Pose
    ) -> tuple[list[dict[str, Any]], CameraDetectionFrame | None]:
        import numpy as np

        from parcel_robot.detection_adapter.pixel_detections import (
            CameraExtrinsics,
            localize_detection,
        )

        t0 = time.perf_counter()
        self._seq += 1
        seq = self._seq
        source_ts = time.time_ns()
        recv_ns = time.monotonic_ns()
        # Card C-1. The freshness clock starts HERE — before the render, before
        # inference — because that is when the photons this frame describes were
        # true. Starting it after inference would make a half-second-old frame
        # report itself as new.
        capture_started_ns = recv_ns

        backend = self._ensure_backend()
        # Render RGB+depth from the current mount pose (worker's own MjData).
        backend.capture(
            source_timestamp_ns=source_ts % (1 << 62),
            sequence=seq,
            robot_x=pose.x,
            robot_y=pose.y,
            robot_yaw_rad=pose.yaw,
        )
        buffers = backend.last_buffers
        if buffers is None or buffers.color_rgb8 is None or buffers.depth_m_f32 is None:
            raise RuntimeError("camera backend produced no RGB/depth buffers")
        rgb = np.asarray(buffers.color_rgb8)
        depth = np.asarray(buffers.depth_m_f32, dtype=np.float64)

        extrinsics = CameraExtrinsics.from_mount_pose(
            robot_x=pose.x,
            robot_y=pose.y,
            robot_yaw_rad=pose.yaw,
            mount=self.mount,
        )

        capture_completed_ns = time.monotonic_ns()
        render_ms = (capture_completed_ns - capture_started_ns) / 1e6

        # Detect then localize per-box so the candidate can carry an honest
        # box+depth footprint (``localize_frame`` drops the box after localization).
        #
        # Card C-1, work item 3: the inference window is DECLARED to PG-1's
        # guard, so a generation cannot start underneath a safety-relevant
        # detection. The guard is optional so offline tests stay deterministic;
        # when it is absent the detector simply runs, which is the incumbent
        # behaviour, not a silent downgrade of a guard that was supposed to be
        # there (the runtime always supplies one when it attaches ingress).
        t_detect = time.perf_counter()
        guard = self.contention_guard
        lease_ctx = getattr(guard, "mission_lease", None) if guard is not None else None
        if callable(lease_ctx):
            with lease_ctx("camera-ingress"):
                detections = self.detector.detect(
                    rgb=rgb, depth=depth, seg=None, query=list(query)
                )
            with self._lock:
                self.stats.leased_inferences += 1
        else:
            detections = self.detector.detect(
                rgb=rgb, depth=depth, seg=None, query=list(query)
            )
        detect_ms = (time.perf_counter() - t_detect) * 1000.0

        fx = float(getattr(self.intrinsics, "fx", 0.0) or 0.0)
        candidates: list[dict[str, Any]] = []
        records: list[CameraDetectionRecord] = []
        raw_count = len(detections)
        localized_count = 0
        for offset, detection in enumerate(detections):
            loc = localize_detection(
                detection,
                depth=depth,
                seg=None,  # a real open-vocab detector is box-only (seg_id=None)
                intrinsics=self.intrinsics,
                extrinsics=extrinsics,
                source_timestamp_ns=source_ts % (1 << 62),
                received_monotonic_ns=recv_ns,
                sequence=int(seq) * 1000 + offset,
                rgb=rgb,
                embed_fn=self.embed_fn,
                detector_name=getattr(self.detector, "name", "detector"),
                depth_min_m=self.depth_min_m,
                depth_max_m=self.depth_max_m,
            )
            if loc is None:
                continue
            localized_count += 1
            front = _front_surface_world_xy(
                detection.box,
                depth,
                intrinsics=self.intrinsics,
                extrinsics=extrinsics,
                depth_min_m=self.depth_min_m,
                depth_max_m=self.depth_max_m,
            )
            candidates.append(
                self._candidate_from_localized(
                    loc,
                    seq,
                    len(candidates),
                    box=detection.box,
                    fx=fx,
                    robot_xy=(pose.x, pose.y),
                    front_surface_xy=None if front is None else (front[0], front[1]),
                    front_depth_m=None if front is None else front[2],
                )
            )
            # Card C-1. The typed observation row, retained up to the per-frame
            # cap. Overflow is counted below, not discarded in silence.
            if len(records) < max(1, int(self.max_detections_per_frame)):
                records.append(
                    CameraDetectionRecord(
                        label=str(loc.label),
                        score=min(1.0, max(0.0, float(loc.score))),
                        box=(
                            float(detection.box[0]),
                            float(detection.box[1]),
                            float(detection.box[2]),
                            float(detection.box[3]),
                        ),
                        world_x=float(loc.world_x),
                        world_y=float(loc.world_y),
                        world_z=float(loc.world_z),
                        range_m=abs(float(loc.message.range_m)),
                        bearing_rad=float(loc.message.bearing_rad),
                        depth_m=abs(float(loc.depth_m)),
                        sigma_range_m=abs(float(loc.sigma_range_m)),
                        inlier_pixels=max(0, int(loc.inlier_pixels)),
                    )
                )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        truncated = localized_count - len(records)
        published_ns = time.monotonic_ns()
        frame = CameraDetectionFrame(
            frame_id=f"cam-{seq}-{source_ts % (1 << 62)}",
            sequence=seq,
            source_timestamp_ns=source_ts % (1 << 62),
            capture_started_monotonic_ns=capture_started_ns,
            capture_completed_monotonic_ns=capture_completed_ns,
            published_monotonic_ns=published_ns,
            published_wall_s=time.time(),
            detection_ttl_ns=int(self.detection_ttl_ns),
            width_px=int(rgb.shape[1]),
            height_px=int(rgb.shape[0]),
            robot_x=pose.x,
            robot_y=pose.y,
            robot_yaw_rad=pose.yaw,
            queries=tuple(query),
            detections=tuple(records),
            raw_detections=raw_count,
            localized_detections=localized_count,
            rejected_detections=raw_count - localized_count,
            truncated_detections=truncated,
            render_ms=render_ms,
            detect_ms=detect_ms,
            total_ms=latency_ms,
            detector_name=str(getattr(self.detector, "name", "detector")),
            # PG-1's resolved (provider, artifact) pair, recorded per frame so a
            # latency number can never be read without knowing which provider
            # produced it. ``selected`` is the profile name (``cuda_fp16`` /
            # ``cpu_int8``); ``execution_providers`` is what ORT actually ran.
            provider_profile=str(
                getattr(getattr(self.detector, "resolution", None), "selected", None)
                or "unknown"
            ),
            active_providers=tuple(
                str(p)
                for p in (
                    getattr(
                        getattr(self.detector, "resolution", None),
                        "execution_providers",
                        (),
                    )
                    or ()
                )
            )[:8],
        )
        with self._lock:
            self.stats.detections_last = localized_count
            self.stats.last_latency_ms = latency_ms
            self.stats.last_detect_ms = detect_ms
            self.stats.detections_truncated += max(0, truncated)
        return candidates, frame

    @staticmethod
    def _candidate_from_localized(
        loc: Any,
        seq: int,
        offset: int,
        *,
        box: Sequence[int] | Sequence[float] | None = None,
        fx: float = 0.0,
        robot_xy: tuple[float, float] = (0.0, 0.0),
        front_surface_xy: tuple[float, float] | None = None,
        front_depth_m: float | None = None,
    ) -> dict[str, Any]:
        """One :class:`LocalizedDetection` → the navigator's candidate dict shape.

        Matches ``navigation.semantic_map._candidate`` / city_semantics objects:
        an ``object`` candidate with a world ``position``, the detector ``score``
        as confidence, ``source=pixel_detector``, and the full near-envelope
        metadata (``radius_m`` from box angular width × depth / 2, plus
        ``stand_off_m`` / vicinity fields from ``object_near_envelope_m``) so
        surface-anchored band math can verify arrival the same way city objects do.

        ``position`` is the estimated object CENTRE: front-surface back-projection
        advanced along the robot→surface ray by ``radius_m``. Median-inlier depth
        alone sits inside curved bodies and would mis-place the centre.
        """

        confidence = float(loc.score)
        confidence = 0.0 if confidence < 0.0 else min(confidence, 1.0)
        depth_for_radius = (
            float(front_depth_m)
            if front_depth_m is not None and math.isfinite(float(front_depth_m))
            else float(loc.depth_m)
        )
        if (
            box is not None
            and float(fx) > 0.0
            and math.isfinite(depth_for_radius)
            and depth_for_radius > 0.0
        ):
            radius_m = radius_m_from_box_depth(box, depth_for_radius, float(fx))
        else:
            radius_m = 0.0
        envelope = _near_envelope_metadata(radius_m, label=str(loc.label))
        if front_surface_xy is not None:
            world_x = float(front_surface_xy[0])
            world_y = float(front_surface_xy[1])
        else:
            world_x = float(loc.world_x)
            world_y = float(loc.world_y)
        world_z = float(loc.world_z)
        if radius_m > 0.0:
            dx = world_x - float(robot_xy[0])
            dy = world_y - float(robot_xy[1])
            dist = math.hypot(dx, dy)
            if dist > 1e-6:
                world_x += (dx / dist) * radius_m
                world_y += (dy / dist) * radius_m
        return {
            "id": f"pxdet-{seq}-{offset}",
            "label": str(loc.label),
            "position": [world_x, world_y, world_z],
            "confidence": confidence,
            "kind": "object",
            "source": PIXEL_SOURCE,
            "reachable": True,
            "metadata": {
                "detector": getattr(loc, "instance_key", None) or PIXEL_SOURCE,
                "range_m": round(float(loc.message.range_m), 4),
                "bearing_rad": round(float(loc.message.bearing_rad), 4),
                "sigma_range_m": round(float(loc.sigma_range_m), 4),
                "inlier_pixels": int(loc.inlier_pixels),
                "depth_m": round(float(loc.depth_m), 4),
                "front_depth_m": round(depth_for_radius, 4),
                **envelope,
            },
        }

    # -- background worker --------------------------------------------------
    def start(self) -> None:
        """Start the background detect worker (idempotent)."""

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="camera-ingress", daemon=True
        )
        self._thread.start()

    def _refresh_pose_from_source(self) -> bool:
        """Pull one fresh pose, if a source is wired. True when a capture may run."""

        source = self.pose_source
        if source is None:
            with self._lock:
                return self._pose is not None
        try:
            pose = source()
        except Exception as exc:  # noqa: BLE001 - a pose read must not kill the worker
            with self._lock:
                self.stats.errors += 1
                self.stats.last_error = f"pose_source {type(exc).__name__}: {exc}"
            return False
        if pose is None:
            # No new pose: do NOT reuse the last one. Clear it so a stalled
            # simulator produces no frames rather than confident stale ones.
            with self._lock:
                self._pose = None
            return False
        with self._lock:
            self._pose = _Pose(float(pose[0]), float(pose[1]), float(pose[2]))
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.perf_counter()
            if self.has_query and self._refresh_pose_from_source():
                self.poll_once()
            # Sleep at least the floor between polls so the worker never busy-spins
            # while idle (no query) and stays off the reactive path when active.
            elapsed = time.perf_counter() - started
            wait = max(0.0, self.min_poll_interval_s - elapsed)
            if self._stop.wait(timeout=max(wait, 0.02)):
                break

    def stop(self) -> None:
        """Stop the worker and release the renderer (idempotent, best-effort)."""

        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        close = getattr(self.backend, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001, S110 - teardown best-effort
                pass


__all__ = [
    "DEFAULT_DETECTION_TTL_NS",
    "DEFAULT_MIN_POLL_INTERVAL_S",
    "MAX_RETAINED_DETECTIONS",
    "PIXEL_SOURCE",
    "CameraDetectionFrame",
    "CameraDetectionRecord",
    "CameraIngress",
    "IngressStats",
    "radius_m_from_box_depth",
]
