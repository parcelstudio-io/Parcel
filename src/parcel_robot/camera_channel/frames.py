"""Frame envelope types for CameraChannel (RGB / depth / seg metadata).

Pure metadata only — no pixel buffers, no EGL. Opus backends may attach
blob refs or in-memory arrays behind the ``CameraBackend`` protocol without
pulling render deps into this layer.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from parcel_robot.camera_channel.d455 import (
    CAMERA_COLOR_FRAME_ID,
    CAMERA_DEPTH_FRAME_ID,
    CAMERA_SEG_FRAME_ID,
    D455_DEPTH_MAX_M,
    D455_DEPTH_MIN_M,
    CameraIntrinsics,
    d455_color_intrinsics,
)

FrameKind = Literal["rgb", "depth", "segmentation"]
FRAME_KINDS = frozenset({"rgb", "depth", "segmentation"})


def _finite(value: object, name: str) -> float:
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
class ColorFrameMeta:
    """RGB frame envelope — D455-shaped color stream metadata."""

    width_px: int
    height_px: int
    fx: float
    fy: float
    cx: float
    cy: float
    encoding: str = "rgb8"
    mount_height_m: float = 0.35
    blob_ref: str | None = None
    frame_id: str = CAMERA_COLOR_FRAME_ID
    calibration_id: str = "d455-intrinsics-nominal"

    def __post_init__(self) -> None:
        if self.width_px < 1 or self.height_px < 1:
            raise ValueError("color frame dimensions must be positive")
        for name, value in (
            ("fx", self.fx),
            ("fy", self.fy),
            ("cx", self.cx),
            ("cy", self.cy),
            ("mount_height_m", self.mount_height_m),
        ):
            _finite(value, name)
        if self.fx <= 0.0 or self.fy <= 0.0:
            raise ValueError("fx/fy must be positive")
        if self.mount_height_m <= 0.0:
            raise ValueError("mount_height_m must be positive")
        if not isinstance(self.encoding, str) or not self.encoding:
            raise ValueError("encoding must be non-empty")
        if self.blob_ref is not None and (
            not isinstance(self.blob_ref, str) or not self.blob_ref
        ):
            raise ValueError("blob_ref must be None or a non-empty string")

    @classmethod
    def from_intrinsics(
        cls,
        intrinsics: CameraIntrinsics,
        *,
        mount_height_m: float,
        encoding: str = "rgb8",
        blob_ref: str | None = None,
        frame_id: str = CAMERA_COLOR_FRAME_ID,
    ) -> ColorFrameMeta:
        return cls(
            width_px=intrinsics.width_px,
            height_px=intrinsics.height_px,
            fx=intrinsics.fx,
            fy=intrinsics.fy,
            cx=intrinsics.cx,
            cy=intrinsics.cy,
            encoding=encoding,
            mount_height_m=mount_height_m,
            blob_ref=blob_ref,
            frame_id=frame_id,
            calibration_id=intrinsics.calibration_id,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "width_px": self.width_px,
            "height_px": self.height_px,
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "encoding": self.encoding,
            "mount_height_m": self.mount_height_m,
            "blob_ref": self.blob_ref,
            "frame_id": self.frame_id,
            "calibration_id": self.calibration_id,
        }


@dataclass(frozen=True, slots=True)
class DepthFrameMeta:
    """Metric depth envelope — same optical center as color by contract."""

    width_px: int
    height_px: int
    fx: float
    fy: float
    cx: float
    cy: float
    depth_min_m: float = D455_DEPTH_MIN_M
    depth_max_m: float = D455_DEPTH_MAX_M
    encoding: str = "depth_m_f32"
    mount_height_m: float = 0.35
    blob_ref: str | None = None
    frame_id: str = CAMERA_DEPTH_FRAME_ID
    calibration_id: str = "d455-intrinsics-nominal"

    def __post_init__(self) -> None:
        if self.width_px < 1 or self.height_px < 1:
            raise ValueError("depth frame dimensions must be positive")
        for name, value in (
            ("fx", self.fx),
            ("fy", self.fy),
            ("cx", self.cx),
            ("cy", self.cy),
            ("depth_min_m", self.depth_min_m),
            ("depth_max_m", self.depth_max_m),
            ("mount_height_m", self.mount_height_m),
        ):
            _finite(value, name)
        if self.fx <= 0.0 or self.fy <= 0.0:
            raise ValueError("fx/fy must be positive")
        if self.depth_min_m < 0.0 or self.depth_max_m <= self.depth_min_m:
            raise ValueError("depth band must satisfy 0 ≤ min < max")
        if self.mount_height_m <= 0.0:
            raise ValueError("mount_height_m must be positive")
        if not isinstance(self.encoding, str) or not self.encoding:
            raise ValueError("encoding must be non-empty")

    @classmethod
    def from_intrinsics(
        cls,
        intrinsics: CameraIntrinsics,
        *,
        mount_height_m: float,
        depth_min_m: float = D455_DEPTH_MIN_M,
        depth_max_m: float = D455_DEPTH_MAX_M,
        encoding: str = "depth_m_f32",
        blob_ref: str | None = None,
        frame_id: str = CAMERA_DEPTH_FRAME_ID,
    ) -> DepthFrameMeta:
        return cls(
            width_px=intrinsics.width_px,
            height_px=intrinsics.height_px,
            fx=intrinsics.fx,
            fy=intrinsics.fy,
            cx=intrinsics.cx,
            cy=intrinsics.cy,
            depth_min_m=depth_min_m,
            depth_max_m=depth_max_m,
            encoding=encoding,
            mount_height_m=mount_height_m,
            blob_ref=blob_ref,
            frame_id=frame_id,
            calibration_id=intrinsics.calibration_id,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "width_px": self.width_px,
            "height_px": self.height_px,
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "depth_min_m": self.depth_min_m,
            "depth_max_m": self.depth_max_m,
            "encoding": self.encoding,
            "mount_height_m": self.mount_height_m,
            "blob_ref": self.blob_ref,
            "frame_id": self.frame_id,
            "calibration_id": self.calibration_id,
        }


@dataclass(frozen=True, slots=True)
class SegFrameMeta:
    """Instance/semantic segmentation envelope co-registered with RGB."""

    width_px: int
    height_px: int
    class_ids: tuple[str, ...]
    encoding: str = "seg_u16"
    mount_height_m: float = 0.35
    blob_ref: str | None = None
    frame_id: str = CAMERA_SEG_FRAME_ID
    calibration_id: str = "d455-intrinsics-nominal"
    fx: float = 644.0
    fy: float = 644.0
    cx: float = 640.0
    cy: float = 360.0

    def __post_init__(self) -> None:
        if self.width_px < 1 or self.height_px < 1:
            raise ValueError("seg frame dimensions must be positive")
        if not isinstance(self.class_ids, tuple):
            raise TypeError("class_ids must be a tuple")
        if len(self.class_ids) > 512:
            raise ValueError("class_ids exceeds 512 entries")
        for item in self.class_ids:
            if not isinstance(item, str) or not item:
                raise ValueError("class_ids entries must be non-empty strings")
        if len(set(self.class_ids)) != len(self.class_ids):
            raise ValueError("class_ids cannot contain duplicates")
        for name, value in (
            ("fx", self.fx),
            ("fy", self.fy),
            ("cx", self.cx),
            ("cy", self.cy),
            ("mount_height_m", self.mount_height_m),
        ):
            _finite(value, name)
        if self.mount_height_m <= 0.0:
            raise ValueError("mount_height_m must be positive")
        if not isinstance(self.encoding, str) or not self.encoding:
            raise ValueError("encoding must be non-empty")

    @classmethod
    def from_intrinsics(
        cls,
        intrinsics: CameraIntrinsics,
        *,
        mount_height_m: float,
        class_ids: Sequence[str],
        encoding: str = "seg_u16",
        blob_ref: str | None = None,
        frame_id: str = CAMERA_SEG_FRAME_ID,
    ) -> SegFrameMeta:
        return cls(
            width_px=intrinsics.width_px,
            height_px=intrinsics.height_px,
            class_ids=tuple(class_ids),
            encoding=encoding,
            mount_height_m=mount_height_m,
            blob_ref=blob_ref,
            frame_id=frame_id,
            calibration_id=intrinsics.calibration_id,
            fx=intrinsics.fx,
            fy=intrinsics.fy,
            cx=intrinsics.cx,
            cy=intrinsics.cy,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "width_px": self.width_px,
            "height_px": self.height_px,
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "class_ids": list(self.class_ids),
            "encoding": self.encoding,
            "mount_height_m": self.mount_height_m,
            "blob_ref": self.blob_ref,
            "frame_id": self.frame_id,
            "calibration_id": self.calibration_id,
        }


@dataclass(frozen=True, slots=True)
class CameraFrameEnvelope:
    """One synchronized RGB+depth(+optional seg) capture from CameraChannel.

    Timestamps are source-clock nanoseconds. Pixel payloads stay behind
    ``blob_ref`` / backend buffers — this type never requires EGL.
    """

    source_timestamp_ns: int
    sequence: int
    color: ColorFrameMeta
    depth: DepthFrameMeta
    segmentation: SegFrameMeta | None = None
    scene_revision: int = 0

    def __post_init__(self) -> None:
        _nonneg_int(self.source_timestamp_ns, "source_timestamp_ns")
        _nonneg_int(self.sequence, "sequence")
        if not isinstance(self.color, ColorFrameMeta):
            raise TypeError("color must be ColorFrameMeta")
        if not isinstance(self.depth, DepthFrameMeta):
            raise TypeError("depth must be DepthFrameMeta")
        if self.segmentation is not None and not isinstance(self.segmentation, SegFrameMeta):
            raise TypeError("segmentation must be SegFrameMeta or None")
        if (
            self.color.width_px != self.depth.width_px
            or self.color.height_px != self.depth.height_px
        ):
            raise ValueError("color and depth resolutions must match")
        if self.segmentation is not None and (
            self.segmentation.width_px != self.color.width_px
            or self.segmentation.height_px != self.color.height_px
        ):
            raise ValueError("segmentation resolution must match color")
        if isinstance(self.scene_revision, bool) or not isinstance(self.scene_revision, int):
            raise TypeError("scene_revision must be an integer")
        if self.scene_revision < 0:
            raise ValueError("scene_revision must be non-negative")

    def kinds(self) -> tuple[FrameKind, ...]:
        kinds: list[FrameKind] = ["rgb", "depth"]
        if self.segmentation is not None:
            kinds.append("segmentation")
        return tuple(kinds)

    def as_dict(self) -> dict[str, object]:
        return {
            "source_timestamp_ns": self.source_timestamp_ns,
            "sequence": self.sequence,
            "color": self.color.as_dict(),
            "depth": self.depth.as_dict(),
            "segmentation": (
                None if self.segmentation is None else self.segmentation.as_dict()
            ),
            "scene_revision": self.scene_revision,
        }


def color_meta_from_mapping(value: Mapping[str, object]) -> ColorFrameMeta:
    """Parse bag-shaped ``camera/color/meta`` payloads into ColorFrameMeta."""

    if not isinstance(value, Mapping):
        raise TypeError("color meta must be an object")
    required = {
        "width_px",
        "height_px",
        "fx",
        "fy",
        "cx",
        "cy",
        "mount_height_m",
        "encoding",
    }
    missing = required - set(value)
    if missing:
        raise ValueError(f"color meta missing fields: {sorted(missing)}")
    return ColorFrameMeta(
        width_px=int(value["width_px"]),  # validated in __post_init__
        height_px=int(value["height_px"]),
        fx=_finite(value["fx"], "fx"),
        fy=_finite(value["fy"], "fy"),
        cx=_finite(value["cx"], "cx"),
        cy=_finite(value["cy"], "cy"),
        encoding=str(value["encoding"]),
        mount_height_m=_finite(value["mount_height_m"], "mount_height_m"),
        blob_ref=None if value.get("blob_ref") is None else str(value["blob_ref"]),
        frame_id=str(value.get("frame_id", CAMERA_COLOR_FRAME_ID)),
        calibration_id=str(value.get("calibration_id", "d455-intrinsics-nominal")),
    )


def default_color_meta(*, mount_height_m: float = 0.35) -> ColorFrameMeta:
    return ColorFrameMeta.from_intrinsics(
        d455_color_intrinsics(), mount_height_m=mount_height_m
    )
