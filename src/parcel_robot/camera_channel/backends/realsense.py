"""Intel RealSense D455 ``CameraBackend`` — RGB + depth ALIGNED to color.

Card P1-A. This is the venue that can actually localize: every detection box
gets metric depth from the same optical raster, so
``localize_detection`` places it in the world from measurements rather than
from an assumed plane. Frames are stamped
:attr:`~parcel_robot.evidence_origin.EvidenceOrigin.PHYSICAL`.

Two things are worth reading before the code.

**1. There is no Python-3.11 sidecar, and that is a deliberate, measured
departure from the card's wording.** The card specified "``pyrealsense2`` in a
Python-3.11 sidecar process" because the venv is CPython 3.14 and the librealsense
wheels historically lagged. Measured on this host, 2026-08-22::

    $ .parcel/bin/pip install pyrealsense2
    pyrealsense2-2.58.3.10794-cp314-cp314-manylinux1_x86_64.whl
    $ .parcel/bin/python -c "import pyrealsense2 as rs; print(rs.__version__)"
    2.58.3

A cp314 wheel exists and imports in ``.parcel``. A sidecar would therefore buy
nothing and cost a process boundary, a serialization of every 1280×720 depth
frame, and a second failure mode — for an ABI problem that no longer exists.
The process boundary this card actually needs is around the GPU DETECTOR
(:mod:`parcel_robot.perception_daemon`), which is where it was put. If a future
host does need a sidecar, :class:`RealSenseCameraBackend` already takes a
``session_factory``: an out-of-process session is a drop-in for it.

**2. Depth is aligned to color IN the backend, not downstream.** The D455's
depth and color sensors are physically apart; unaligned depth would put every
box's range on the wrong pixels. ``rs.align(rs.stream.color)`` runs before the
frames leave here, and the base class refuses a depth raster whose shape
disagrees with the color intrinsics — so an alignment that silently stopped
happening becomes a refusal, not a quiet metric error.

**Intrinsics come from the DEVICE.** Unlike the webcam path, a RealSense
reports its factory calibration; it is read from the active color profile and
stamped ``d455-device-<serial>``. That is a real calibration and it is named as
one — and it is deliberately not the sim's ``d455-intrinsics-nominal``, so a
desk frame and a MuJoCo frame can never compare equal on calibration id.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from parcel_robot.camera_channel.backends.physical import (
    PhysicalCameraBackendBase,
    PhysicalCameraUnavailable,
    spec_from_config,
)
from parcel_robot.evidence_origin import EvidenceOrigin

logger = logging.getLogger(__name__)

DEFAULT_WIDTH_PX = 1280
DEFAULT_HEIGHT_PX = 720
DEFAULT_FPS = 30

#: How long ``wait_for_frames`` may block. Longer than a frame interval by a
#: wide margin, short enough that a dead device is noticed within one poll.
DEFAULT_FRAME_TIMEOUT_MS = 2000


class RealSenseUnavailable(PhysicalCameraUnavailable):
    """No ``pyrealsense2``, no device on the bus, or the stream stopped."""


def pyrealsense_available() -> bool:
    """True when ``pyrealsense2`` imports. Never raises."""

    try:  # pragma: no cover - import probe
        import pyrealsense2  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def connected_devices() -> list[str]:
    """Serial numbers of RealSense devices on the bus; ``[]`` when none.

    Used by the launcher and by the owner-gated live rows to say "no camera is
    attached" as a fact rather than as an inference from a failed open.
    """

    try:  # pragma: no cover - needs the library
        import pyrealsense2 as rs
    except Exception:  # noqa: BLE001
        return []
    try:  # pragma: no cover - needs the library
        return [
            str(dev.get_info(rs.camera_info.serial_number))
            for dev in rs.context().query_devices()
        ]
    except Exception:  # noqa: BLE001
        return []


@dataclass(frozen=True, slots=True)
class RealSenseProfile:
    """What a started session reports about itself."""

    width_px: int
    height_px: int
    fx: float
    fy: float
    cx: float
    cy: float
    depth_scale_m: float
    serial: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "width_px": self.width_px,
            "height_px": self.height_px,
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "depth_scale_m": self.depth_scale_m,
            "serial": self.serial,
        }


class _PyRealSenseSession:  # pragma: no cover - requires hardware
    """The real librealsense pipeline, behind the session seam.

    Everything hardware-specific is here so the backend above it is testable
    with an injected double and identical in shape either way.
    """

    def __init__(
        self,
        *,
        width_px: int,
        height_px: int,
        fps: int,
        serial: str | None,
        timeout_ms: int,
    ) -> None:
        self._width = width_px
        self._height = height_px
        self._fps = fps
        self._serial = serial
        self._timeout_ms = timeout_ms
        self._pipeline: Any = None
        self._align: Any = None
        self._depth_scale = 0.001

    def start(self) -> RealSenseProfile:
        try:
            import pyrealsense2 as rs
        except Exception as exc:
            raise RealSenseUnavailable(
                "pyrealsense2 is required for the realsense backend: "
                "pip install '.[camera-realsense]'"
            ) from exc
        config = rs.config()
        if self._serial:
            config.enable_device(str(self._serial))
        config.enable_stream(
            rs.stream.color, self._width, self._height, rs.format.rgb8, self._fps
        )
        config.enable_stream(
            rs.stream.depth, self._width, self._height, rs.format.z16, self._fps
        )
        pipeline = rs.pipeline()
        try:
            profile = pipeline.start(config)
        except Exception as exc:
            raise RealSenseUnavailable(f"cannot start the RealSense pipeline: {exc}") from exc
        self._pipeline = pipeline
        self._align = rs.align(rs.stream.color)
        device = profile.get_device()
        self._depth_scale = float(device.first_depth_sensor().get_depth_scale())
        color_stream = profile.get_stream(rs.stream.color).as_video_stream_profile()
        intr = color_stream.get_intrinsics()
        serial = str(device.get_info(rs.camera_info.serial_number))
        return RealSenseProfile(
            width_px=int(intr.width),
            height_px=int(intr.height),
            fx=float(intr.fx),
            fy=float(intr.fy),
            cx=float(intr.ppx),
            cy=float(intr.ppy),
            depth_scale_m=self._depth_scale,
            serial=serial,
        )

    def read(self) -> tuple[np.ndarray, np.ndarray]:
        pipeline = self._pipeline
        if pipeline is None:
            raise RealSenseUnavailable("RealSense session is not started")
        try:
            frames = pipeline.wait_for_frames(self._timeout_ms)
        except Exception as exc:
            raise RealSenseUnavailable(f"RealSense delivered no frameset: {exc}") from exc
        aligned = self._align.process(frames)
        color = aligned.get_color_frame()
        depth = aligned.get_depth_frame()
        if not color or not depth:
            raise RealSenseUnavailable("RealSense frameset is missing color or depth")
        rgb = np.asanyarray(color.get_data())
        depth_raw = np.asanyarray(depth.get_data())
        depth_m = depth_raw.astype(np.float32) * np.float32(self._depth_scale)
        return rgb, depth_m

    def stop(self) -> None:
        pipeline, self._pipeline = self._pipeline, None
        if pipeline is None:
            return
        try:
            pipeline.stop()
        except Exception:
            logger.debug("stopping the RealSense pipeline failed", exc_info=True)


class RealSenseCameraBackend(PhysicalCameraBackendBase):
    """D455 RGB + color-aligned metric depth, stamped PHYSICAL.

    ``session_factory`` returns any object with ``start() -> RealSenseProfile``,
    ``read() -> (rgb_uint8, depth_m_float32)`` and ``stop()``. That is the seam
    an out-of-process sidecar would implement if a host ever needs one, and the
    seam the contract tests use to run without hardware.
    """

    origin = EvidenceOrigin.PHYSICAL
    kind = "realsense"

    def __init__(
        self,
        *,
        width_px: int = DEFAULT_WIDTH_PX,
        height_px: int = DEFAULT_HEIGHT_PX,
        fps: int = DEFAULT_FPS,
        serial: str | None = None,
        timeout_ms: int = DEFAULT_FRAME_TIMEOUT_MS,
        intrinsics: Mapping[str, Any] | None = None,
        mount: Mapping[str, Any] | None = None,
        depth: Mapping[str, Any] | None = None,
        session_factory: Callable[..., Any] | None = None,
        **clock_kwargs: Any,
    ) -> None:
        self._requested = (int(width_px), int(height_px))
        self._fps = int(fps)
        self._serial = None if serial is None else str(serial)
        self._timeout_ms = int(timeout_ms)
        self._override_intrinsics = dict(intrinsics) if intrinsics else None
        self._config: dict[str, Any] = {
            "fps": self._fps,
            "intrinsics": self._override_intrinsics,
            "mount": dict(mount) if mount else None,
            "depth": dict(depth) if depth else None,
        }
        self._session_factory = session_factory or self._default_session_factory
        self._session: Any = None
        self._profile: RealSenseProfile | None = None
        spec = spec_from_config(
            self._config,
            width_px=self._requested[0],
            height_px=self._requested[1],
            has_depth=True,
        )
        super().__init__(
            spec=spec,
            origin_label=f"realsense:{self._serial or 'any'}",
            **clock_kwargs,
        )

    def _default_session_factory(self, **kwargs: Any) -> Any:  # pragma: no cover - hardware
        return _PyRealSenseSession(**kwargs)

    @property
    def has_depth(self) -> bool:
        return True

    @property
    def profile(self) -> RealSenseProfile | None:
        """The device's own reported calibration, once started."""

        return self._profile

    def _open(self) -> None:
        session = self._session_factory(
            width_px=self._requested[0],
            height_px=self._requested[1],
            fps=self._fps,
            serial=self._serial,
            timeout_ms=self._timeout_ms,
        )
        profile = session.start()
        if not isinstance(profile, RealSenseProfile):
            raise RealSenseUnavailable(
                "a RealSense session must report a RealSenseProfile from start()"
            )
        self._session = session
        self._profile = profile
        self._adopt_profile(profile)

    def _adopt_profile(self, profile: RealSenseProfile) -> None:
        """Rebuild the channel spec from the DEVICE's calibration.

        A config-supplied ``intrinsics`` block still wins — a commissioned
        calibration should beat the factory one — but with nothing configured
        the device's own numbers are used rather than the sim's nominal
        constants, and the calibration id names the serial that produced them.
        """

        from parcel_robot.camera_channel.channel import CameraChannel

        config = dict(self._config)
        if self._override_intrinsics is None:
            config["intrinsics"] = {
                "fx": profile.fx,
                "fy": profile.fy,
                "cx": profile.cx,
                "cy": profile.cy,
                "calibration_id": f"d455-device-{profile.serial}",
            }
        spec = spec_from_config(
            config,
            width_px=profile.width_px,
            height_px=profile.height_px,
            has_depth=True,
        )
        self._channel = CameraChannel(spec)
        self._origin_label = f"realsense:{profile.serial}"

    def _close(self) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        try:
            session.stop()
        except Exception:
            logger.debug("stopping the RealSense session failed", exc_info=True)

    def _read_frame(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        session = self._session
        if session is None:
            raise RealSenseUnavailable("RealSense backend is not open")
        rgb, depth = session.read()
        if rgb is None or depth is None:
            raise RealSenseUnavailable("RealSense session returned an incomplete frame")
        rgb_arr = np.asarray(rgb)
        depth_arr = np.asarray(depth, dtype=np.float32)
        if rgb_arr.shape[:2] != depth_arr.shape[:2]:
            raise RealSenseUnavailable(
                f"depth {depth_arr.shape[:2]} is not aligned to color {rgb_arr.shape[:2]}; "
                "rs.align(rs.stream.color) must run before frames leave the session"
            )
        return rgb_arr, depth_arr


def open_realsense_backend(
    *, config: Mapping[str, Any] | None = None, **overrides: Any
) -> RealSenseCameraBackend:
    """Build and START a RealSense backend, or raise :class:`RealSenseUnavailable`."""

    settings = dict(config or {})
    settings.pop("kind", None)
    settings.update(overrides)
    backend = RealSenseCameraBackend(**settings)
    backend.open()
    return backend


__all__ = [
    "DEFAULT_FPS",
    "DEFAULT_FRAME_TIMEOUT_MS",
    "DEFAULT_HEIGHT_PX",
    "DEFAULT_WIDTH_PX",
    "RealSenseCameraBackend",
    "RealSenseProfile",
    "RealSenseUnavailable",
    "connected_devices",
    "open_realsense_backend",
    "pyrealsense_available",
]
