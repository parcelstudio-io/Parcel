"""Opus CameraBackend implementations (MuJoCo EGL + CI synthetic).

Sol owns the pure ``CameraBackend`` protocol. This package fills envelopes:

- ``SyntheticCameraBackend`` — deterministic RGB/depth/seg for CI (always).
- ``MujocoEglCameraBackend`` — offscreen MuJoCo render when EGL/OSMesa works.

The real-EGL path is **sim evidence only** (hardware-readiness HR-4). It does
not validate D455 optics or field low-viewpoint perception.
"""

from __future__ import annotations

from parcel_robot.camera_channel.backends.factory import (
    BackendKind,
    ProbeResult,
    attach_preferred_backend,
    open_camera_backend,
    probe_mujoco_offscreen,
)
from parcel_robot.camera_channel.backends.mujoco_egl import (
    MujocoEglCameraBackend,
    MujocoEglUnavailable,
)
from parcel_robot.camera_channel.backends.synthetic import (
    CaptureBuffers,
    SyntheticCameraBackend,
)

__all__ = [
    "BackendKind",
    "CaptureBuffers",
    "MujocoEglCameraBackend",
    "MujocoEglUnavailable",
    "ProbeResult",
    "SyntheticCameraBackend",
    "attach_preferred_backend",
    "open_camera_backend",
    "probe_mujoco_offscreen",
]
