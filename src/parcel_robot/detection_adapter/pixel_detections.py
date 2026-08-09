"""Pixels -> ``contracts.DetectionMsg`` via a detector-agnostic localizer (B2).

This is the VISUAL-SEARCH FOUNDATION producer. It turns an RGB+depth(+seg)
frame plus a detector's boxes into contract-shaped :class:`DetectionMsg` rows,
each carrying a metric world point and a position covariance the later
confirmation/lock-on cards (D1/D2/D4) consume.

Design — **detector-agnostic behind a ``Detector`` protocol**
------------------------------------------------------------
``detect(rgb, depth, seg, query) -> list[PixelDetection]`` is the only seam a
real open-vocab detector (B3, awaiting the owner's pick) has to satisfy. The
first and only implementation shipped here is :class:`SegTruthDetector`, which
reads MuJoCo's segmentation buffer as a *perfect* detector — the sim ruler. It
localizes with ZERO recognition error by construction, so any localization
error a later real detector shows is attributable to recognition, and the
geometry/pipeline below it is already proven.

Localizer recipe (OpenNav, arXiv:2408.13936)
--------------------------------------------
For each detection box:

1. ``segment`` — the exact geom mask when the detector supplies a ``seg_id``
   (SegTruthDetector does), else the box interior restricted to valid depth;
2. ``erode 3x3`` — pull the mask off the object's depth-bleeding silhouette;
3. ``Z-score reject`` (``tau=2``) — drop depth outliers under the eroded mask;
4. ``back-project`` the inlier centroid pixel at its metric depth:
   ``Xc=(u-cx)*D/fx``, ``Yc=(v-cy)*D/fy``, ``Zc=D`` (OpenCV camera frame:
   +X right, +Y down, +Z forward — the convention the OpenNav formula is in);
5. ``camera extrinsic`` -> world point.

The emitted :class:`DetectionMsg` carries ``bearing_rad``/``range_m`` derived
from that same world point (so grounding sees a self-consistent bearing/range),
``score`` = detector confidence, ``class_id`` = detector label, and an
``embedding`` that is the optional SigLIP crop embedding when an ``embed_fn`` is
injected, else the deterministic label embedding (the DetectionMsg contract
requires a non-empty embedding — there is no ``None`` seam in the schema).

HONESTY (P0)
------------
This module + its gates prove GEOMETRY + localization + the DetectionMsg
pipeline + false-positive-handling machinery against MuJoCo segmentation-truth
as the ruler. They do **not** prove real-texture RECOGNITION — that is B3 + a
hardware re-earn. No detector recognition accuracy is claimed here.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from parcel_robot.camera_channel.d455 import (
    CALIBRATION_ID_NOMINAL,
    CameraIntrinsics,
    CameraMountGeometry,
    d455_color_intrinsics,
    go2_d455_mount,
)
from parcel_robot.contracts import (
    SCHEMA_VERSION,
    DetectionMsg,
    EvidenceEnvelopeV1,
    expires_from_ttl,
)
from parcel_robot.contracts.freshness import DEFAULT_DETECTION_TTL_NS
from parcel_robot.detection_adapter.perception_chain import (
    D455_DEPTH_SIGMA_COEFF_PER_M,
)
from parcel_robot.detection_adapter.sim_bridge import (
    bearing_range_from_pose,
    label_embedding,
)

DOES_NOT_PROVE = (
    (
        "SegTruthDetector reads MuJoCo segmentation-truth as a perfect detector: it "
        "proves box->world-point geometry + the DetectionMsg pipeline, NOT real-texture "
        "recognition (that is B3 + a hardware re-earn)."
    ),
    (
        "Localization error near zero here is by construction (the seg buffer IS the "
        "ruler); a real open-vocab detector adds recognition error on top of this "
        "already-proven geometry."
    ),
)

#: Default sub-pixel std of a box/mask centroid on the nominal D455 intrinsics,
#: mirroring perception_chain's ``2 / 674 ~ 3e-3 rad`` note. Feeds sigma_bearing.
DEFAULT_CENTROID_SIGMA_PX = 2.0

#: Z-score threshold for the depth-outlier reject stage (OpenNav ``tau=2``).
DEFAULT_Z_TAU = 2.0


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


@dataclass(frozen=True, slots=True)
class CameraExtrinsics:
    """Rigid camera pose in world for the OpenCV optical frame.

    ``rotation`` maps a camera-frame point (OpenCV: +X right, +Y down, +Z
    forward) to world; ``translation`` is the camera optical centre in world.
    ``robot_x/robot_y/robot_yaw_rad`` are the planar base pose the camera is
    mounted on, retained so bearing/range can be reported in the same
    body-relative convention the rest of the mission path uses.
    """

    rotation: tuple[float, ...]  # 9 floats, row-major 3x3 (camera -> world)
    translation: tuple[float, float, float]
    robot_x: float = 0.0
    robot_y: float = 0.0
    robot_yaw_rad: float = 0.0

    def __post_init__(self) -> None:
        if len(self.rotation) != 9:
            raise ValueError("rotation must be 9 row-major floats")
        for v in self.rotation:
            _finite(v, "rotation component")
        if len(self.translation) != 3:
            raise ValueError("translation must be 3 floats")
        for v in self.translation:
            _finite(v, "translation component")
        _finite(self.robot_x, "robot_x")
        _finite(self.robot_y, "robot_y")
        _finite(self.robot_yaw_rad, "robot_yaw_rad")

    @classmethod
    def from_mount_pose(
        cls,
        *,
        robot_x: float,
        robot_y: float,
        robot_yaw_rad: float,
        mount: CameraMountGeometry | None = None,
    ) -> CameraExtrinsics:
        """Build the extrinsic the MuJoCo-EGL backend's free camera renders at.

        Matches ``mujoco_egl.MujocoEglCameraBackend._free_camera``: the optical
        centre sits at the forward/lateral mount offset and mount height, the
        optical axis points along yaw at the mount's upward pitch, and world
        +Z is the up reference.
        """

        mount = mount if mount is not None else go2_d455_mount()
        yaw = _finite(robot_yaw_rad, "robot_yaw_rad")
        rx = _finite(robot_x, "robot_x")
        ry = _finite(robot_y, "robot_y")
        pitch = mount.pitch_up_rad

        cam_x = rx + mount.forward_m * math.cos(yaw) - mount.lateral_m * math.sin(yaw)
        cam_y = ry + mount.forward_m * math.sin(yaw) + mount.lateral_m * math.cos(yaw)
        cam_z = mount.height_m

        # Optical axis (camera +Z_cv, "forward") at azimuth=yaw, elevation=pitch.
        fwd = np.array(
            [
                math.cos(pitch) * math.cos(yaw),
                math.cos(pitch) * math.sin(yaw),
                math.sin(pitch),
            ],
            dtype=np.float64,
        )
        world_up = np.array([0.0, 0.0, 1.0])
        right = np.cross(fwd, world_up)  # camera +X_cv ("right")
        right /= np.linalg.norm(right)
        down = np.cross(fwd, right)  # camera +Y_cv ("down"); already unit
        # Columns of R_wc are the world images of the camera basis vectors.
        rot = np.column_stack([right, down, fwd]).reshape(-1)
        return cls(
            rotation=tuple(float(v) for v in rot),
            translation=(float(cam_x), float(cam_y), float(cam_z)),
            robot_x=rx,
            robot_y=ry,
            robot_yaw_rad=yaw,
        )

    def _rot(self) -> np.ndarray:
        return np.asarray(self.rotation, dtype=np.float64).reshape(3, 3)

    def camera_to_world(self, point_cv: Sequence[float]) -> tuple[float, float, float]:
        p = np.asarray(point_cv, dtype=np.float64)
        w = np.asarray(self.translation, dtype=np.float64) + self._rot() @ p
        return (float(w[0]), float(w[1]), float(w[2]))

    def world_to_camera(self, point_world: Sequence[float]) -> tuple[float, float, float]:
        p = np.asarray(point_world, dtype=np.float64) - np.asarray(
            self.translation, dtype=np.float64
        )
        c = self._rot().T @ p
        return (float(c[0]), float(c[1]), float(c[2]))


def back_project(
    u: float, v: float, depth_m: float, intrinsics: CameraIntrinsics
) -> tuple[float, float, float]:
    """Pixel (u, v) + metric optical-axis depth -> OpenCV camera-frame point.

    ``Xc=(u-cx)*D/fx``, ``Yc=(v-cy)*D/fy``, ``Zc=D``. ``D`` is the perpendicular
    (z) depth, which is exactly what MuJoCo's depth render returns.
    """

    d = _finite(depth_m, "depth_m")
    uu = _finite(u, "u")
    vv = _finite(v, "v")
    xc = (uu - intrinsics.cx) * d / intrinsics.fx
    yc = (vv - intrinsics.cy) * d / intrinsics.fy
    return (xc, yc, d)


def project(
    point_world: Sequence[float],
    intrinsics: CameraIntrinsics,
    extrinsics: CameraExtrinsics,
) -> tuple[float, float, float] | None:
    """World point -> (u, v, depth). ``None`` when the point is behind the camera."""

    xc, yc, zc = extrinsics.world_to_camera(point_world)
    if zc <= 1e-9:
        return None
    u = intrinsics.cx + intrinsics.fx * xc / zc
    v = intrinsics.cy + intrinsics.fy * yc / zc
    return (u, v, zc)


# ---------------------------------------------------------------------------
# detector protocol + detections
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PixelDetection:
    """One detector box on a frame (detector-agnostic).

    ``box`` is ``(u0, v0, u1, v1)`` pixel bounds (half-open on the high side).
    ``seg_id`` is the segmentation-buffer value the box came from when the
    detector reads a seg buffer (SegTruthDetector sets it so the localizer can
    take the exact geom mask); a real box-only detector leaves it ``None`` and
    the localizer falls back to the box interior. ``instance_key`` names the
    ground-truth entity for right-object scoring (the seg id for SegTruth).
    """

    label: str
    score: float
    box: tuple[int, int, int, int]
    seg_id: int | None = None
    instance_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("label must be a non-empty string")
        s = _finite(self.score, "score")
        if not 0.0 <= s <= 1.0:
            raise ValueError("score must be in [0, 1]")
        if len(self.box) != 4:
            raise ValueError("box must be (u0, v0, u1, v1)")
        u0, v0, u1, v1 = self.box
        for name, value in (("u0", u0), ("v0", v0), ("u1", u1), ("v1", v1)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"box.{name} must be an int")
        if u1 <= u0 or v1 <= v0:
            raise ValueError("box must have positive extent")
        if self.seg_id is not None and (
            isinstance(self.seg_id, bool) or not isinstance(self.seg_id, int)
        ):
            raise TypeError("seg_id must be an int or None")

    @property
    def u_center(self) -> float:
        return 0.5 * (self.box[0] + self.box[2])

    @property
    def v_center(self) -> float:
        return 0.5 * (self.box[1] + self.box[3])


@runtime_checkable
class Detector(Protocol):
    """Detector-agnostic seam. B3's real open-vocab model is a drop-in here.

    ``detect`` reads a rendered frame and returns boxes matching ``query`` (an
    open-vocab noun / phrase, or ``None`` for "everything"). ``seg`` may be
    ``None`` for a real detector; SegTruthDetector requires it.
    """

    name: str

    def detect(
        self,
        *,
        rgb: np.ndarray | None,
        depth: np.ndarray | None,
        seg: np.ndarray | None,
        query: str | Sequence[str] | None,
    ) -> list[PixelDetection]:
        ...


def _normalize_query(query: str | Sequence[str] | None) -> frozenset[str] | None:
    if query is None:
        return None
    if isinstance(query, str):
        items = [query]
    else:
        items = list(query)
    out = {str(q).strip().lower() for q in items if str(q).strip()}
    return frozenset(out) if out else None


class SegTruthDetector:
    """A perfect detector that reads the MuJoCo segmentation buffer (the ruler).

    Each distinct segmentation id is one instance. ``id_to_label`` maps a seg
    value (``geom_id + 1``; ``0`` is background, matching
    ``mujoco_egl``'s packing) to a class label. A detection is emitted for every
    instance whose label matches ``query`` (exact, case-insensitive), with
    ``score=1.0`` — recognition is perfect *by construction*, which is the whole
    point: it isolates geometry from recognition.
    """

    name = "seg_truth"

    def __init__(
        self,
        id_to_label: Mapping[int, str],
        *,
        min_pixels: int = 1,
    ) -> None:
        table: dict[int, str] = {}
        for key, value in id_to_label.items():
            if isinstance(key, bool) or not isinstance(key, int) or key <= 0:
                raise ValueError("id_to_label keys must be positive ints (0 = background)")
            if not isinstance(value, str) or not value:
                raise ValueError("id_to_label values must be non-empty strings")
            table[int(key)] = value
        self._table = table
        if isinstance(min_pixels, bool) or not isinstance(min_pixels, int) or min_pixels < 1:
            raise ValueError("min_pixels must be a positive int")
        self._min_pixels = min_pixels

    @property
    def id_to_label(self) -> dict[int, str]:
        return dict(self._table)

    def detect(
        self,
        *,
        rgb: np.ndarray | None,
        depth: np.ndarray | None,
        seg: np.ndarray | None,
        query: str | Sequence[str] | None,
    ) -> list[PixelDetection]:
        if seg is None:
            raise ValueError("SegTruthDetector requires a segmentation buffer")
        seg_arr = np.asarray(seg)
        if seg_arr.ndim != 2:
            raise ValueError("seg must be a 2D (H, W) id buffer")
        wanted = _normalize_query(query)
        out: list[PixelDetection] = []
        present = np.unique(seg_arr)
        for raw_id in present:
            seg_id = int(raw_id)
            if seg_id <= 0:
                continue
            label = self._table.get(seg_id)
            if label is None:
                continue
            if wanted is not None and label.lower() not in wanted:
                continue
            ys, xs = np.where(seg_arr == seg_id)
            if xs.size < self._min_pixels:
                continue
            u0, u1 = int(xs.min()), int(xs.max()) + 1
            v0, v1 = int(ys.min()), int(ys.max()) + 1
            out.append(
                PixelDetection(
                    label=label,
                    score=1.0,
                    box=(u0, v0, u1, v1),
                    seg_id=seg_id,
                    instance_key=f"seg:{seg_id}",
                )
            )
        out.sort(key=lambda d: (d.box[1], d.box[0], d.seg_id or 0))
        return out


# ---------------------------------------------------------------------------
# localizer
# ---------------------------------------------------------------------------


def _erode_3x3(mask: np.ndarray) -> np.ndarray:
    """Full 3x3 binary erosion (8-neighborhood). Border pixels erode off."""

    h, w = mask.shape
    padded = np.zeros((h + 2, w + 2), dtype=bool)
    padded[1:-1, 1:-1] = mask
    out = np.ones_like(mask, dtype=bool)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out &= padded[dy : dy + h, dx : dx + w]
    return out


@dataclass(frozen=True, slots=True)
class LocalizedDetection:
    """A DetectionMsg plus the metric world point + covariance the schema omits.

    ``message`` is the contract-shaped output the mission path consumes.
    ``world_x/world_y/world_z`` is the back-projected point (the localization-
    error ruler compares against MuJoCo seg-truth). ``covariance_xy`` is the
    2x2 world position covariance (row-major) D2/D4 fuse; ``sigma_range_m`` and
    ``sigma_bearing_rad`` are its polar generators. ``instance_key`` /
    ``seg_id`` carry the ground-truth identity for right-object scoring.
    """

    message: DetectionMsg
    world_x: float
    world_y: float
    world_z: float
    depth_m: float
    sigma_range_m: float
    sigma_bearing_rad: float
    covariance_xy: tuple[tuple[float, float], tuple[float, float]]
    label: str
    score: float
    seg_id: int | None
    instance_key: str | None
    inlier_pixels: int


def _polar_covariance_xy(
    *,
    world_bearing_rad: float,
    range_m: float,
    sigma_range_m: float,
    sigma_bearing_rad: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """2x2 world (x, y) covariance from range/cross-range polar sigmas."""

    var_range = sigma_range_m * sigma_range_m
    var_cross = (range_m * sigma_bearing_rad) ** 2
    c, s = math.cos(world_bearing_rad), math.sin(world_bearing_rad)
    # R = [[c, -s], [s, c]]; Cov = R diag(var_range, var_cross) R^T
    c00 = c * c * var_range + s * s * var_cross
    c01 = c * s * (var_range - var_cross)
    c11 = s * s * var_range + c * c * var_cross
    return ((c00, c01), (c01, c11))


def localize_detection(
    detection: PixelDetection,
    *,
    depth: np.ndarray,
    seg: np.ndarray | None,
    intrinsics: CameraIntrinsics,
    extrinsics: CameraExtrinsics,
    source_timestamp_ns: int,
    received_monotonic_ns: int,
    sequence: int,
    scene_revision: int = 0,
    rgb: np.ndarray | None = None,
    embed_fn: Callable[[np.ndarray], Sequence[float]] | None = None,
    detector_name: str = "seg_truth",
    z_tau: float = DEFAULT_Z_TAU,
    centroid_sigma_px: float = DEFAULT_CENTROID_SIGMA_PX,
    depth_min_m: float = 0.0,
    depth_max_m: float = math.inf,
    ttl_ns: int = DEFAULT_DETECTION_TTL_NS,
    source: str = "sim.pixel_detections",
    frame_id: str = "base_link",
    calibration_id: str = CALIBRATION_ID_NOMINAL,
) -> LocalizedDetection | None:
    """One box -> ``LocalizedDetection`` (segment/erode/Z-score/back-project).

    Returns ``None`` when the box has no valid inlier depth (a fully occluded or
    out-of-band box), which is a legitimate "cannot localize" outcome.
    """

    depth_arr = np.asarray(depth, dtype=np.float64)
    if depth_arr.ndim != 2:
        raise ValueError("depth must be a 2D (H, W) array")
    h, w = depth_arr.shape
    u0, v0, u1, v1 = detection.box
    u0 = max(0, min(u0, w))
    u1 = max(0, min(u1, w))
    v0 = max(0, min(v0, h))
    v1 = max(0, min(v1, h))
    if u1 <= u0 or v1 <= v0:
        return None

    # 1) segment: exact geom mask when available, else the box interior.
    mask = np.zeros((h, w), dtype=bool)
    if detection.seg_id is not None and seg is not None:
        seg_arr = np.asarray(seg)
        mask = seg_arr == detection.seg_id
    else:
        mask[v0:v1, u0:u1] = True

    valid = np.isfinite(depth_arr) & (depth_arr > max(0.0, depth_min_m))
    if math.isfinite(depth_max_m):
        valid &= depth_arr <= depth_max_m
    mask &= valid
    if not mask.any():
        return None

    # 2) erode 3x3 (fall back to the raw mask if erosion empties a small object).
    eroded = _erode_3x3(mask)
    if not eroded.any():
        eroded = mask

    # 3) Z-score depth-outlier reject (tau) under the eroded mask.
    ys, xs = np.where(eroded)
    depths = depth_arr[ys, xs]
    mu = float(depths.mean())
    sigma = float(depths.std())
    if sigma > 0.0:
        keep = np.abs(depths - mu) <= z_tau * sigma
        if keep.any():
            ys, xs, depths = ys[keep], xs[keep], depths[keep]
    if xs.size == 0:
        return None

    # 4) inlier centroid pixel + robust representative depth -> back-project.
    u_c = float(xs.mean())
    v_c = float(ys.mean())
    d_c = float(np.median(depths))
    world = extrinsics.camera_to_world(back_project(u_c, v_c, d_c, intrinsics))

    # bearing/range from the world point, in the body-relative convention the
    # rest of the mission path uses (self-consistent with the world point).
    bearing_rad, range_m = bearing_range_from_pose(
        robot_x=extrinsics.robot_x,
        robot_y=extrinsics.robot_y,
        robot_yaw_rad=extrinsics.robot_yaw_rad,
        target_x=world[0],
        target_y=world[1],
    )
    range_m = max(0.0, range_m)

    # covariance: D455 quadratic range sigma + box-centroid pixel -> bearing sigma.
    sigma_range_m = D455_DEPTH_SIGMA_COEFF_PER_M * range_m * range_m
    sigma_bearing_rad = math.atan2(max(0.0, centroid_sigma_px), intrinsics.fx)
    world_bearing = extrinsics.robot_yaw_rad + bearing_rad
    covariance_xy = _polar_covariance_xy(
        world_bearing_rad=world_bearing,
        range_m=range_m,
        sigma_range_m=sigma_range_m,
        sigma_bearing_rad=sigma_bearing_rad,
    )

    # embedding: injected crop embedding, else the deterministic label embedding
    # (DetectionMsg requires a non-empty embedding — no None seam in the schema).
    embedding = _crop_embedding(
        rgb=rgb,
        box=(u0, v0, u1, v1),
        label=detection.label,
        embed_fn=embed_fn,
    )

    envelope = EvidenceEnvelopeV1(
        schema_version=SCHEMA_VERSION,
        evidence_id=f"pxdet-{sequence}",
        source=source,
        source_timestamp_ns=int(source_timestamp_ns),
        received_monotonic_ns=int(received_monotonic_ns),
        sequence=int(sequence),
        frame_id=frame_id,
        scene_revision=int(scene_revision),
        expires_monotonic_ns=expires_from_ttl(
            received_monotonic_ns=int(received_monotonic_ns), ttl_ns=int(ttl_ns)
        ),
        calibration_id=calibration_id,
        provenance=("pixel_detections_v1", str(detector_name)),
    )
    message = DetectionMsg(
        envelope=envelope,
        class_id=detection.label,
        embedding=embedding,
        bearing_rad=_wrap(bearing_rad),
        range_m=range_m,
        score=float(detection.score),
        track_id=str(detection.instance_key or ""),
    )
    return LocalizedDetection(
        message=message,
        world_x=world[0],
        world_y=world[1],
        world_z=world[2],
        depth_m=d_c,
        sigma_range_m=sigma_range_m,
        sigma_bearing_rad=sigma_bearing_rad,
        covariance_xy=covariance_xy,
        label=detection.label,
        score=float(detection.score),
        seg_id=detection.seg_id,
        instance_key=detection.instance_key,
        inlier_pixels=int(xs.size),
    )


def localize_frame(
    detector: Detector,
    *,
    rgb: np.ndarray | None,
    depth: np.ndarray,
    seg: np.ndarray | None,
    query: str | Sequence[str] | None,
    intrinsics: CameraIntrinsics,
    extrinsics: CameraExtrinsics,
    source_timestamp_ns: int,
    received_monotonic_ns: int,
    sequence: int = 0,
    scene_revision: int = 0,
    embed_fn: Callable[[np.ndarray], Sequence[float]] | None = None,
    z_tau: float = DEFAULT_Z_TAU,
    centroid_sigma_px: float = DEFAULT_CENTROID_SIGMA_PX,
    depth_min_m: float = 0.0,
    depth_max_m: float = math.inf,
) -> list[LocalizedDetection]:
    """Run ``detector`` on a frame and localize every box to a DetectionMsg."""

    detections = detector.detect(rgb=rgb, depth=depth, seg=seg, query=query)
    out: list[LocalizedDetection] = []
    for offset, detection in enumerate(detections):
        localized = localize_detection(
            detection,
            depth=depth,
            seg=seg,
            intrinsics=intrinsics,
            extrinsics=extrinsics,
            source_timestamp_ns=source_timestamp_ns,
            received_monotonic_ns=received_monotonic_ns,
            sequence=int(sequence) * 1000 + offset,
            scene_revision=scene_revision,
            rgb=rgb,
            embed_fn=embed_fn,
            detector_name=getattr(detector, "name", "detector"),
            z_tau=z_tau,
            centroid_sigma_px=centroid_sigma_px,
            depth_min_m=depth_min_m,
            depth_max_m=depth_max_m,
        )
        if localized is not None:
            out.append(localized)
    return out


def _crop_embedding(
    *,
    rgb: np.ndarray | None,
    box: tuple[int, int, int, int],
    label: str,
    embed_fn: Callable[[np.ndarray], Sequence[float]] | None,
) -> tuple[float, ...]:
    if embed_fn is not None and rgb is not None:
        u0, v0, u1, v1 = box
        crop = np.asarray(rgb)[v0:v1, u0:u1]
        if crop.size:
            vec = tuple(float(x) for x in embed_fn(crop))
            if vec:
                return vec
    return label_embedding(label)


def _wrap(bearing: float) -> float:
    wrapped = (bearing + math.pi) % (2.0 * math.pi) - math.pi
    return max(-math.pi, min(math.pi, wrapped))


def default_intrinsics() -> CameraIntrinsics:
    return d455_color_intrinsics()
