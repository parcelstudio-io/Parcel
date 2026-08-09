"""Pure CameraChannel model + backend protocol for Opus MuJoCo wiring.

Sol owns intrinsics, mount geometry, and frame envelopes. Opus implements
``CameraBackend`` with offscreen EGL RGB + metric depth + segmentation; this
module never imports MuJoCo or EGL.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from parcel_robot.camera_channel.d455 import (
    CALIBRATION_ID_NOMINAL,
    D455_DEPTH_MAX_M,
    D455_DEPTH_MIN_M,
    D455_DEPTH_FPS,
    D455_RGB_FPS,
    MOUNT_HEIGHT_M,
    CameraIntrinsics,
    CameraMountGeometry,
    d455_color_intrinsics,
    go2_d455_mount,
)
from parcel_robot.camera_channel.frames import (
    CameraFrameEnvelope,
    ColorFrameMeta,
    DepthFrameMeta,
    SegFrameMeta,
)


@runtime_checkable
class CameraBackend(Protocol):
    """Opus-facing capture surface. Pure layer only defines the contract."""

    def capture(
        self,
        *,
        source_timestamp_ns: int,
        sequence: int,
        scene_revision: int = 0,
    ) -> CameraFrameEnvelope:
        """Return a synchronized RGB+depth(+seg) envelope at the channel pose."""


@dataclass(frozen=True, slots=True)
class CameraChannelSpec:
    """Static CameraChannel configuration (D455 @ 35 cm by default)."""

    intrinsics: CameraIntrinsics
    mount: CameraMountGeometry
    depth_min_m: float = D455_DEPTH_MIN_M
    depth_max_m: float = D455_DEPTH_MAX_M
    rgb_fps: int = D455_RGB_FPS
    depth_fps: int = D455_DEPTH_FPS
    include_segmentation: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.intrinsics, CameraIntrinsics):
            raise TypeError("intrinsics must be CameraIntrinsics")
        if not isinstance(self.mount, CameraMountGeometry):
            raise TypeError("mount must be CameraMountGeometry")
        for name, value in (("depth_min_m", self.depth_min_m), ("depth_max_m", self.depth_max_m)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.depth_min_m < 0.0 or self.depth_max_m <= self.depth_min_m:
            raise ValueError("depth band must satisfy 0 ≤ min < max")
        for name, value in (("rgb_fps", self.rgb_fps), ("depth_fps", self.depth_fps)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.include_segmentation, bool):
            raise TypeError("include_segmentation must be a boolean")

    @classmethod
    def d455_go2_nominal(cls) -> CameraChannelSpec:
        return cls(intrinsics=d455_color_intrinsics(), mount=go2_d455_mount())

    def as_dict(self) -> dict[str, object]:
        return {
            "intrinsics": self.intrinsics.as_dict(),
            "mount": self.mount.as_dict(),
            "depth_min_m": self.depth_min_m,
            "depth_max_m": self.depth_max_m,
            "rgb_fps": self.rgb_fps,
            "depth_fps": self.depth_fps,
            "include_segmentation": self.include_segmentation,
            "calibration_id": self.intrinsics.calibration_id,
            "does_not_prove": (
                "Nominal D455 intrinsics and 35 cm mount are sim/contract constants; "
                "they do not prove commissioned hardware calibration or real optics."
            ),
        }


class CameraChannel:
    """Pure channel: validates envelopes and builds metadata stubs for backends.

    Call ``attach_backend`` from Opus once an EGL renderer exists. Without a
    backend, ``capture`` raises — Sol never fakes pixels.
    """

    def __init__(self, spec: CameraChannelSpec | None = None) -> None:
        self._spec = spec if spec is not None else CameraChannelSpec.d455_go2_nominal()
        self._backend: CameraBackend | None = None

    @property
    def spec(self) -> CameraChannelSpec:
        return self._spec

    @property
    def calibration_id(self) -> str:
        return self._spec.intrinsics.calibration_id

    @property
    def mount_height_m(self) -> float:
        return self._spec.mount.height_m

    def attach_backend(self, backend: CameraBackend) -> None:
        if not isinstance(backend, CameraBackend):
            raise TypeError("backend must satisfy CameraBackend protocol")
        self._backend = backend

    def detach_backend(self) -> None:
        self._backend = None

    @property
    def has_backend(self) -> bool:
        return self._backend is not None

    def make_color_meta(self, *, blob_ref: str | None = None) -> ColorFrameMeta:
        return ColorFrameMeta.from_intrinsics(
            self._spec.intrinsics,
            mount_height_m=self._spec.mount.height_m,
            blob_ref=blob_ref,
            frame_id=self._spec.mount.camera_frame_id,
        )

    def make_depth_meta(self, *, blob_ref: str | None = None) -> DepthFrameMeta:
        return DepthFrameMeta.from_intrinsics(
            self._spec.intrinsics,
            mount_height_m=self._spec.mount.height_m,
            depth_min_m=self._spec.depth_min_m,
            depth_max_m=self._spec.depth_max_m,
            blob_ref=blob_ref,
        )

    def make_seg_meta(
        self,
        class_ids: Sequence[str],
        *,
        blob_ref: str | None = None,
    ) -> SegFrameMeta:
        return SegFrameMeta.from_intrinsics(
            self._spec.intrinsics,
            mount_height_m=self._spec.mount.height_m,
            class_ids=class_ids,
            blob_ref=blob_ref,
        )

    def wrap_stub_envelope(
        self,
        *,
        source_timestamp_ns: int,
        sequence: int,
        scene_revision: int = 0,
        class_ids: Sequence[str] = (),
        color_blob_ref: str | None = None,
        depth_blob_ref: str | None = None,
        seg_blob_ref: str | None = None,
    ) -> CameraFrameEnvelope:
        """Build a metadata-only envelope (no pixels) for bag/tests/adapters."""

        seg: SegFrameMeta | None = None
        if self._spec.include_segmentation:
            seg = self.make_seg_meta(class_ids, blob_ref=seg_blob_ref)
        return CameraFrameEnvelope(
            source_timestamp_ns=source_timestamp_ns,
            sequence=sequence,
            color=self.make_color_meta(blob_ref=color_blob_ref),
            depth=self.make_depth_meta(blob_ref=depth_blob_ref),
            segmentation=seg,
            scene_revision=scene_revision,
        )

    def validate_envelope(self, envelope: CameraFrameEnvelope) -> None:
        """Fail closed if an Opus/backend envelope disagrees with channel spec."""

        if not isinstance(envelope, CameraFrameEnvelope):
            raise TypeError("envelope must be CameraFrameEnvelope")
        intr = self._spec.intrinsics
        color = envelope.color
        if (
            color.width_px != intr.width_px
            or color.height_px != intr.height_px
            or color.fx != intr.fx
            or color.fy != intr.fy
            or color.cx != intr.cx
            or color.cy != intr.cy
        ):
            raise ValueError("envelope color intrinsics disagree with CameraChannelSpec")
        if color.calibration_id != intr.calibration_id:
            raise ValueError("envelope calibration_id disagrees with CameraChannelSpec")
        if abs(color.mount_height_m - self._spec.mount.height_m) > 1e-9:
            raise ValueError("envelope mount_height_m disagrees with CameraChannelSpec")
        if abs(envelope.depth.mount_height_m - self._spec.mount.height_m) > 1e-9:
            raise ValueError("depth mount_height_m disagrees with CameraChannelSpec")

    def capture(
        self,
        *,
        source_timestamp_ns: int,
        sequence: int,
        scene_revision: int = 0,
    ) -> CameraFrameEnvelope:
        if self._backend is None:
            raise RuntimeError(
                "CameraChannel has no backend; Opus must attach a MuJoCo/EGL "
                "CameraBackend before capture (pure layer never synthesizes pixels)"
            )
        envelope = self._backend.capture(
            source_timestamp_ns=source_timestamp_ns,
            sequence=sequence,
            scene_revision=scene_revision,
        )
        self.validate_envelope(envelope)
        return envelope

    def elevation_angle_to_point_rad(
        self,
        *,
        horizontal_range_m: float,
        target_height_m: float,
    ) -> float:
        """Upward elevation from optical axis to a world point (approx pinhole).

        Positive = above the optical axis. Used by low-viewpoint OCR gates.
        """

        if (
            isinstance(horizontal_range_m, bool)
            or not isinstance(horizontal_range_m, (int, float))
            or not math.isfinite(float(horizontal_range_m))
            or float(horizontal_range_m) <= 0.0
        ):
            raise ValueError("horizontal_range_m must be a finite positive number")
        if (
            isinstance(target_height_m, bool)
            or not isinstance(target_height_m, (int, float))
            or not math.isfinite(float(target_height_m))
        ):
            raise ValueError("target_height_m must be finite")
        cam_z = self._spec.mount.height_m
        pitch = self._spec.mount.pitch_up_rad
        # World elevation from camera, then subtract mount pitch.
        raw = math.atan2(float(target_height_m) - cam_z, float(horizontal_range_m))
        return raw - pitch


def assert_nominal_d455_contract(spec: CameraChannelSpec) -> None:
    """Guardrail: K5 / bag / HR-4 share one nominal D455@35cm contract."""

    if spec.intrinsics.calibration_id != CALIBRATION_ID_NOMINAL:
        raise ValueError("expected d455-intrinsics-nominal calibration_id")
    if abs(spec.mount.height_m - MOUNT_HEIGHT_M) > 1e-9:
        raise ValueError("expected 0.35 m mount height")
