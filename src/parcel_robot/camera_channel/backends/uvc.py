"""UVC / V4L2 webcam ``CameraBackend`` — RGB only, real photons (card P1-A).

The cheapest possible real venue: any USB webcam Linux exposes as
``/dev/videoN``. Opened through OpenCV's ``VideoCapture`` (the
``opencv-python-headless`` extra), converted BGR→RGB once, stamped
:attr:`~parcel_robot.evidence_origin.EvidenceOrigin.PHYSICAL`, and handed out
as a :class:`~parcel_robot.camera_channel.backends.physical.PhysicalCaptureBuffers`.

**RGB only, and that is a real limitation, stated rather than papered over.**
A webcam has no depth. ``depth_m_f32`` is ``None``, so the localizer
(``localize_detection``, which needs metric depth to place a box in the world)
cannot run on this venue and
:class:`~parcel_robot.camera_channel.ingress.CameraIngress` will count a poll
error rather than invent a range. That is the correct failure: a constant
"assumed depth plane" would produce world coordinates that look like
measurements and are not. The D455 backend
(:mod:`~parcel_robot.camera_channel.backends.realsense`) is the venue that
localizes; UVC is the venue that proves detection on real pixels and drives the
detector daemon end to end.

**Intrinsics.** A webcam ships no calibration. Give one in the config block and
it is used verbatim; give nothing and
:func:`~parcel_robot.camera_channel.backends.physical.uncalibrated_intrinsics`
derives a pinhole guess from a stated horizontal FOV and stamps
``uvc-uncalibrated-hfov60`` as the calibration id. The nominal D455 id is
REFUSED for a config-supplied calibration, so a webcam can never claim the
sim's contract calibration.

**Negotiated resolution.** V4L2 devices routinely ignore a requested size. The
backend therefore asks, then READS BACK what it got, and rescales the
intrinsics to the raster it actually receives — with ``-scaled`` appended to the
calibration id so the rescale is visible.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

from parcel_robot.camera_channel.backends.physical import (
    PhysicalCameraBackendBase,
    PhysicalCameraUnavailable,
    scale_intrinsics,
    spec_from_config,
)
from parcel_robot.camera_channel.channel import CameraChannelSpec
from parcel_robot.evidence_origin import EvidenceOrigin

logger = logging.getLogger(__name__)

#: cv2.CAP_PROP_* ids, spelled out so this module imports without cv2 present.
_CAP_PROP_FRAME_WIDTH = 3
_CAP_PROP_FRAME_HEIGHT = 4
_CAP_PROP_FPS = 5

DEFAULT_WIDTH_PX = 1280
DEFAULT_HEIGHT_PX = 720
DEFAULT_FPS = 30

#: Consecutive empty reads tolerated before the backend declares the device
#: gone. A UVC device drops a frame now and then; it does not drop five in a
#: row unless it has been unplugged.
MAX_CONSECUTIVE_READ_FAILURES = 5


class UvcCameraUnavailable(PhysicalCameraUnavailable):
    """No UVC device, no OpenCV, or the device refused to deliver frames."""


def opencv_available() -> bool:
    """True when ``cv2`` imports. Never raises."""

    try:  # pragma: no cover - import probe
        import cv2  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _default_capture_factory(device: int | str) -> Any:  # pragma: no cover - needs hardware
    try:
        import cv2
    except Exception as exc:
        raise UvcCameraUnavailable(
            "opencv is required for the UVC backend: pip install '.[camera]'"
        ) from exc
    return cv2.VideoCapture(device)


class UvcCameraBackend(PhysicalCameraBackendBase):
    """RGB frames from a V4L2/UVC device, stamped PHYSICAL.

    ``capture_factory`` exists so the contract can be tested without hardware:
    it returns any object with ``isOpened()``, ``read() -> (ok, bgr)``,
    ``get(prop)``, ``set(prop, value)`` and ``release()``. The production
    default builds a ``cv2.VideoCapture``.
    """

    origin = EvidenceOrigin.PHYSICAL
    kind = "uvc"

    def __init__(
        self,
        device: int | str = 0,
        *,
        width_px: int = DEFAULT_WIDTH_PX,
        height_px: int = DEFAULT_HEIGHT_PX,
        fps: int = DEFAULT_FPS,
        intrinsics: Mapping[str, Any] | None = None,
        mount: Mapping[str, Any] | None = None,
        depth: Mapping[str, Any] | None = None,
        capture_factory: Callable[[int | str], Any] | None = None,
        bgr_input: bool = True,
        **clock_kwargs: Any,
    ) -> None:
        if isinstance(device, bool) or not isinstance(device, (int, str)):
            raise TypeError("device must be a V4L2 index or a /dev/video path")
        self._device = device
        self._requested = (int(width_px), int(height_px))
        self._fps = int(fps)
        self._config: dict[str, Any] = {
            "fps": self._fps,
            "intrinsics": dict(intrinsics) if intrinsics else None,
            "mount": dict(mount) if mount else None,
            "depth": dict(depth) if depth else None,
        }
        self._capture_factory = capture_factory or _default_capture_factory
        self._bgr_input = bool(bgr_input)
        self._cap: Any = None
        self._consecutive_failures = 0
        spec = spec_from_config(
            self._config, width_px=self._requested[0], height_px=self._requested[1], has_depth=False
        )
        super().__init__(
            spec=spec,
            origin_label=f"uvc:{device}",
            **clock_kwargs,
        )

    @property
    def has_depth(self) -> bool:
        """A webcam never has depth. Stated as a property so callers can ask."""

        return False

    @property
    def device(self) -> int | str:
        return self._device

    def _open(self) -> None:
        cap = self._capture_factory(self._device)
        if cap is None:
            raise UvcCameraUnavailable(f"capture factory returned nothing for {self._device!r}")
        is_open = getattr(cap, "isOpened", None)
        if callable(is_open) and not is_open():
            try:
                cap.release()
            except Exception:
                logger.debug("releasing an unopenable UVC handle failed", exc_info=True)
            raise UvcCameraUnavailable(
                f"cannot open UVC device {self._device!r} (no /dev/video* on this host?)"
            )
        want_w, want_h = self._requested
        for prop, value in (
            (_CAP_PROP_FRAME_WIDTH, want_w),
            (_CAP_PROP_FRAME_HEIGHT, want_h),
            (_CAP_PROP_FPS, self._fps),
        ):
            try:
                cap.set(prop, float(value))
            except Exception:  # noqa: BLE001 - a device may refuse any property
                logger.debug("UVC device refused property %s=%s", prop, value)
        got_w = self._read_prop(cap, _CAP_PROP_FRAME_WIDTH, want_w)
        got_h = self._read_prop(cap, _CAP_PROP_FRAME_HEIGHT, want_h)
        self._cap = cap
        self._consecutive_failures = 0
        if (got_w, got_h) != (want_w, want_h):
            # The device negotiated a different raster. Move the intrinsics with
            # it rather than validating frames against a size nothing produces.
            self._renegotiate(got_w, got_h)

    @staticmethod
    def _read_prop(cap: Any, prop: int, fallback: int) -> int:
        try:
            value = round(float(cap.get(prop)))
        except Exception:  # noqa: BLE001
            return fallback
        return value if value > 0 else fallback

    def _renegotiate(self, width_px: int, height_px: int) -> None:
        """Rebuild the channel spec around the raster the device really sends."""

        current = self._channel.spec
        spec = CameraChannelSpec(
            intrinsics=scale_intrinsics(
                current.intrinsics, width_px=width_px, height_px=height_px
            ),
            mount=current.mount,
            depth_min_m=current.depth_min_m,
            depth_max_m=current.depth_max_m,
            rgb_fps=current.rgb_fps,
            depth_fps=current.depth_fps,
            include_segmentation=False,
        )
        from parcel_robot.camera_channel.channel import CameraChannel

        self._channel = CameraChannel(spec)

    def _close(self) -> None:
        cap, self._cap = self._cap, None
        if cap is None:
            return
        release = getattr(cap, "release", None)
        if callable(release):
            try:
                release()
            except Exception:
                logger.debug("releasing the UVC handle failed", exc_info=True)

    def _read_frame(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        cap = self._cap
        if cap is None:
            raise UvcCameraUnavailable("UVC backend is not open")
        ok, frame = cap.read()
        if not ok or frame is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                raise UvcCameraUnavailable(
                    f"UVC device {self._device!r} returned no frame "
                    f"{self._consecutive_failures} times in a row; treat it as gone"
                )
            raise UvcCameraUnavailable(f"UVC device {self._device!r} returned no frame")
        self._consecutive_failures = 0
        arr = np.asarray(frame)
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise UvcCameraUnavailable(
                f"UVC device {self._device!r} returned a {arr.shape} frame; expected HxWx3"
            )
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        rgb = arr[:, :, ::-1] if self._bgr_input else arr
        height, width = rgb.shape[:2]
        intr = self._channel.spec.intrinsics
        if (width, height) != (intr.width_px, intr.height_px):
            # The device changed raster mid-stream (some UVC devices do this on
            # a format switch). Follow it, loudly in the calibration id, rather
            # than dropping every frame from here on.
            self._renegotiate(width, height)
        return np.ascontiguousarray(rgb), None


def open_uvc_backend(
    device: int | str = 0,
    *,
    config: Mapping[str, Any] | None = None,
    **overrides: Any,
) -> UvcCameraBackend:
    """Build and OPEN a UVC backend, or raise :class:`UvcCameraUnavailable`."""

    settings = dict(config or {})
    settings.pop("kind", None)
    settings.pop("device", None)
    settings.update(overrides)
    backend = UvcCameraBackend(device, **settings)
    backend.open()
    return backend


__all__ = [
    "DEFAULT_FPS",
    "DEFAULT_HEIGHT_PX",
    "DEFAULT_WIDTH_PX",
    "MAX_CONSECUTIVE_READ_FAILURES",
    "UvcCameraBackend",
    "UvcCameraUnavailable",
    "open_uvc_backend",
    "opencv_available",
]
