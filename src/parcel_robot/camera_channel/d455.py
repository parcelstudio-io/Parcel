"""D455-like intrinsics and Go2 low-viewpoint mount constants (pure).

Nominal values match the K2′ bag ``camera/color/meta`` envelope so sim and
bag paths share one calibration id. These are **design constants for the
sim/CameraChannel contract**, not commissioned hardware calibration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Intel RealSense D455–shaped RGB (1280×720 nominal), matching bag MVP.
D455_WIDTH_PX = 1280
D455_HEIGHT_PX = 720
D455_FX_PX = 644.0
D455_FY_PX = 644.0
D455_CX_PX = 640.0
D455_CY_PX = 360.0

# Practical stereo depth band for D455-class sensors (vendor ballpark).
D455_DEPTH_MIN_M = 0.4
D455_DEPTH_MAX_M = 6.0
D455_RGB_FPS = 30
D455_DEPTH_FPS = 30

CALIBRATION_ID_NOMINAL = "d455-intrinsics-nominal"
CAMERA_COLOR_FRAME_ID = "camera_color_optical_frame"
CAMERA_DEPTH_FRAME_ID = "camera_depth_optical_frame"
CAMERA_SEG_FRAME_ID = "camera_seg_optical_frame"
BASE_FRAME_ID = "base_link"

# Go2 head mount ≈ dog height (StreamVLN-style D455 rig pattern donor).
MOUNT_HEIGHT_M = 0.35
MOUNT_FORWARD_OFFSET_M = 0.18
MOUNT_LATERAL_OFFSET_M = 0.0
# Slight upward pitch so storefront signs enter the frustum from 35 cm.
MOUNT_PITCH_UP_RAD = math.radians(12.0)
MOUNT_ROLL_RAD = 0.0
MOUNT_YAW_RAD = 0.0


@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    """Pinhole intrinsics shared by RGB / depth / seg envelopes."""

    width_px: int
    height_px: int
    fx: float
    fy: float
    cx: float
    cy: float
    calibration_id: str = CALIBRATION_ID_NOMINAL

    def __post_init__(self) -> None:
        if isinstance(self.width_px, bool) or not isinstance(self.width_px, int) or self.width_px < 1:
            raise ValueError("width_px must be a positive integer")
        if (
            isinstance(self.height_px, bool)
            or not isinstance(self.height_px, int)
            or self.height_px < 1
        ):
            raise ValueError("height_px must be a positive integer")
        for name, value in (
            ("fx", self.fx),
            ("fy", self.fy),
            ("cx", self.cx),
            ("cy", self.cy),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be a finite positive number")
        if not isinstance(self.calibration_id, str) or not self.calibration_id:
            raise ValueError("calibration_id must be a non-empty string")

    def horizontal_fov_rad(self) -> float:
        return 2.0 * math.atan(self.width_px / (2.0 * self.fx))

    def vertical_fov_rad(self) -> float:
        return 2.0 * math.atan(self.height_px / (2.0 * self.fy))

    def as_dict(self) -> dict[str, object]:
        return {
            "width_px": self.width_px,
            "height_px": self.height_px,
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "calibration_id": self.calibration_id,
        }


@dataclass(frozen=True, slots=True)
class CameraMountGeometry:
    """Rigid mount of the camera optical frame relative to ``base_link``.

    Heights and pitch are the low-viewpoint contract Opus must honor when
    wiring MuJoCo EGL; Sol owns the numbers, not the renderer.
    """

    height_m: float = MOUNT_HEIGHT_M
    forward_m: float = MOUNT_FORWARD_OFFSET_M
    lateral_m: float = MOUNT_LATERAL_OFFSET_M
    pitch_up_rad: float = MOUNT_PITCH_UP_RAD
    roll_rad: float = MOUNT_ROLL_RAD
    yaw_rad: float = MOUNT_YAW_RAD
    base_frame_id: str = BASE_FRAME_ID
    camera_frame_id: str = CAMERA_COLOR_FRAME_ID

    def __post_init__(self) -> None:
        for name, value in (
            ("height_m", self.height_m),
            ("forward_m", self.forward_m),
            ("lateral_m", self.lateral_m),
            ("pitch_up_rad", self.pitch_up_rad),
            ("roll_rad", self.roll_rad),
            ("yaw_rad", self.yaw_rad),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.height_m <= 0.0 or self.height_m > 2.0:
            raise ValueError("height_m must be in (0, 2] meters")
        if not isinstance(self.base_frame_id, str) or not self.base_frame_id:
            raise ValueError("base_frame_id must be non-empty")
        if not isinstance(self.camera_frame_id, str) or not self.camera_frame_id:
            raise ValueError("camera_frame_id must be non-empty")

    def is_dog_height(self, *, tolerance_m: float = 0.05) -> bool:
        return abs(self.height_m - MOUNT_HEIGHT_M) <= tolerance_m

    def as_dict(self) -> dict[str, object]:
        return {
            "height_m": self.height_m,
            "forward_m": self.forward_m,
            "lateral_m": self.lateral_m,
            "pitch_up_rad": self.pitch_up_rad,
            "roll_rad": self.roll_rad,
            "yaw_rad": self.yaw_rad,
            "base_frame_id": self.base_frame_id,
            "camera_frame_id": self.camera_frame_id,
        }


def d455_color_intrinsics() -> CameraIntrinsics:
    return CameraIntrinsics(
        width_px=D455_WIDTH_PX,
        height_px=D455_HEIGHT_PX,
        fx=D455_FX_PX,
        fy=D455_FY_PX,
        cx=D455_CX_PX,
        cy=D455_CY_PX,
        calibration_id=CALIBRATION_ID_NOMINAL,
    )


def go2_d455_mount() -> CameraMountGeometry:
    return CameraMountGeometry()
