"""Shared base for camera backends that read pixels from OUTSIDE the simulator.

Card P1-A ("real eyes"). Three backends land on top of this module —
:mod:`~parcel_robot.camera_channel.backends.uvc` (any V4L2/UVC webcam),
:mod:`~parcel_robot.camera_channel.backends.realsense` (D455 RGB + aligned
depth) and :mod:`~parcel_robot.camera_channel.backends.recorded` (a committed
clip, for CI) — and every one of them needs the same three things:

1. **A declared :class:`~parcel_robot.evidence_origin.EvidenceOrigin`.** The
   whole point of the card is that a desk frame must never be confusable with a
   MuJoCo frame anywhere downstream. ``EvidenceOrigin`` is DECLARED, never
   inferred (card W0-A), so :class:`PhysicalCaptureBuffers` refuses to exist
   without one, refuses :attr:`EvidenceOrigin.UNKNOWN`, and refuses a bare
   string that merely *spells* an origin. A backend that forgets to declare
   cannot produce a frame at all.
2. **A wall-clock capture stamp and a strictly increasing monotonic stamp.**
   The sim backends stamp ``time.time_ns()`` inside the ingress; a physical
   camera has its own arrival order and a replayed clip has none, so the stamp
   is enforced HERE: two frames may never carry the same monotonic instant, and
   a clock that goes backwards is a refusal rather than a warning. Freshness
   (``CameraDetectionFrame.expired_at_publish``) is computed from capture start,
   so a stamp that can repeat or regress is a causality corruption.
3. **An intrinsics/mount spec built from CONFIG, not from the D455 nominal
   constants.** A webcam is not a commissioned D455. When a caller supplies no
   calibration this module derives a pinhole guess from a stated horizontal FOV
   and names the result ``uvc-uncalibrated-hfov<deg>`` — a calibration id that
   can never be mistaken for :data:`CALIBRATION_ID_NOMINAL` by
   ``assert_nominal_d455_contract`` or by anything reading ``calibration_id``.

Why this file exists at all (declared deviation, P1-A OWNS): the card names
``backends/{uvc,realsense,recorded}.py``. All three need items 1–3 verbatim,
and duplicating the origin guard into three files is exactly how one of the
three quietly loses it. The shared base is a fourth new file inside the same
package; it is imported by nothing outside these three modules and the P1-A
daemon.

HONESTY
-------
Nothing here proves a camera works. It proves that IF pixels arrive they carry
a declared origin, a monotonic stamp and an intrinsics block that describes the
optics they actually came through. Recognition quality on real pixels is a
separate, hardware-gated measurement.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from parcel_robot.camera_channel.channel import CameraChannel, CameraChannelSpec
from parcel_robot.camera_channel.d455 import (
    CALIBRATION_ID_NOMINAL,
    D455_DEPTH_FPS,
    D455_DEPTH_MAX_M,
    D455_DEPTH_MIN_M,
    D455_RGB_FPS,
    CameraIntrinsics,
    CameraMountGeometry,
    go2_d455_mount,
)
from parcel_robot.camera_channel.frames import CameraFrameEnvelope
from parcel_robot.evidence_origin import EvidenceOrigin

# ---- CARD HW-1 py310-clean (scrum/20260822/task_35) ----
# ``typing.Self`` is 3.11+ and the dog's Orin NX runs JetPack's CPython 3.10
# (WAVE3_HW_DESIGN_FABLE.md §5.1, seam S22). This module opens with ``from
# __future__ import annotations``, so its one use of the name — the return
# annotation of ``PhysicalCameraBackendBase.__enter__`` — is a *string* at
# runtime and no ``typing.Self`` object is ever built. The ``TYPE_CHECKING``
# form (already used by ``commissioning/session.py:77`` before this card)
# therefore leaves ``__annotations__`` byte-for-byte what it was.
if TYPE_CHECKING:  # pragma: no cover - annotations only; never evaluated at runtime
    from typing import Self
# ---- END CARD HW-1 py310-clean ----

#: The backend kinds the ``--camera`` launcher switch accepts. ``synthetic`` and
#: ``mujoco_egl`` are deliberately NOT here: they are selected by the existing
#: sim factory and are not physical venues.
PHYSICAL_BACKEND_KINDS: tuple[str, ...] = ("uvc", "realsense", "recorded")

#: The env var the ``--camera`` switch on ``scripts/launch_stack.sh`` exports.
#: One spelling, per the card's "do not add a fourth spelling" rule: the flag
#: sets this, and every consumer reads this.
CAMERA_BACKEND_ENV = "PARCEL_CAMERA_BACKEND"

#: Optional JSON/YAML file describing the attached camera (see
#: :func:`spec_from_config`). Deliberately NOT a ``configs/robot.yaml`` section:
#: that file is SHA-locked and P0-A's overlay key-walk refuses any key path the
#: base does not define, so growing it from this card would either break the
#: digest or need an escape-hatch entry. A camera is host hardware, not robot
#: policy.
CAMERA_CONFIG_ENV = "PARCEL_CAMERA_CONFIG"

#: Fallback horizontal field of view for a webcam that ships no calibration.
#: 60° is the common UVC default; the number is stamped INTO the calibration id
#: so a consumer can see it was assumed.
DEFAULT_UNCALIBRATED_HFOV_DEG = 60.0

DOES_NOT_PROVE: tuple[str, ...] = (
    "A declared PHYSICAL origin proves provenance, not recognition quality.",
    (
        "Uncalibrated UVC intrinsics are a stated-FOV pinhole guess, not a "
        "commissioned calibration; metric localization from them is approximate."
    ),
    "A recorded clip replays REPLAY-origin frames. It can never mint PHYSICAL.",
)


class PhysicalCameraUnavailable(RuntimeError):
    """A physical capture device could not be opened or read.

    Raised by the concrete backends' ``open`` paths. It is a distinct type so a
    caller can tell "no camera on this host" apart from "the camera lied".
    """


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class PhysicalCaptureBuffers:
    """Pixel payloads from a non-simulated venue, with provenance attached.

    Field-compatible with
    :class:`~parcel_robot.camera_channel.backends.synthetic.CaptureBuffers`
    (``color_rgb8`` / ``depth_m_f32`` / ``seg_u16``) so
    :class:`~parcel_robot.camera_channel.ingress.CameraIngress` consumes it
    unchanged — and strictly richer, because it also says WHERE the pixels came
    from and WHEN they were true.

    ``origin`` must be an :class:`EvidenceOrigin` MEMBER. A string that happens
    to spell ``"physical"`` is refused: ``EvidenceOrigin`` exists precisely
    because an unattributed producer used to be able to mint physical authority
    (card W0-A, defect P0-2), and re-opening that hole from the camera layer
    would defeat the point of this card.
    """

    color_rgb8: np.ndarray | None
    depth_m_f32: np.ndarray | None
    origin: EvidenceOrigin
    origin_label: str
    capture_monotonic_ns: int
    capture_wall_ns: int
    sequence: int
    seg_u16: np.ndarray | None = None

    def __post_init__(self) -> None:
        # ``EvidenceOrigin`` is a str-Enum, so a bare "physical" IS a str but is
        # NOT a member — which is exactly the distinction being enforced.
        if not isinstance(self.origin, EvidenceOrigin):
            raise TypeError(
                "origin must be an EvidenceOrigin member, not "
                f"{type(self.origin).__name__} — provenance is declared, never spelled"
            )
        if self.origin is EvidenceOrigin.UNKNOWN:
            raise ValueError(
                "a capture must declare a real origin; UNKNOWN is the fail-closed "
                "default and is never authority"
            )
        if not isinstance(self.origin_label, str) or not self.origin_label:
            raise ValueError("origin_label must name the venue (device path, clip id)")
        if len(self.origin_label) > 128:
            raise ValueError("origin_label exceeds 128 characters")
        for name in ("capture_monotonic_ns", "capture_wall_ns", "sequence"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.color_rgb8 is None and self.depth_m_f32 is None:
            raise ValueError("a capture must carry at least one pixel buffer")
        if self.color_rgb8 is not None:
            arr = np.asarray(self.color_rgb8)
            if arr.ndim != 3 or arr.shape[2] != 3:
                raise ValueError("color_rgb8 must be HxWx3")
            if arr.dtype != np.uint8:
                raise TypeError("color_rgb8 must be uint8 (RGB, not BGR)")
        if self.depth_m_f32 is not None:
            depth = np.asarray(self.depth_m_f32)
            if depth.ndim != 2:
                raise ValueError("depth_m_f32 must be HxW")

    @property
    def is_physical(self) -> bool:
        """True only for live hardware. A replay is never physical."""

        return self.origin is EvidenceOrigin.PHYSICAL

    def as_dict(self) -> dict[str, Any]:
        """Metadata only — never the pixels."""

        return {
            "origin": self.origin.value,
            "origin_label": self.origin_label,
            "capture_monotonic_ns": self.capture_monotonic_ns,
            "capture_wall_ns": self.capture_wall_ns,
            "sequence": self.sequence,
            "has_color": self.color_rgb8 is not None,
            "has_depth": self.depth_m_f32 is not None,
            "color_shape": (
                None if self.color_rgb8 is None else list(np.asarray(self.color_rgb8).shape)
            ),
            "depth_shape": (
                None if self.depth_m_f32 is None else list(np.asarray(self.depth_m_f32).shape)
            ),
        }


def uncalibrated_intrinsics(
    width_px: int,
    height_px: int,
    *,
    hfov_deg: float = DEFAULT_UNCALIBRATED_HFOV_DEG,
) -> CameraIntrinsics:
    """Pinhole guess from a stated horizontal FOV, NAMED as a guess.

    The calibration id carries the assumed FOV, so a downstream reader can tell
    a guess from a commissioned calibration by inspection and
    ``assert_nominal_d455_contract`` still refuses it.
    """

    width = _positive_int(width_px, "width_px")
    height = _positive_int(height_px, "height_px")
    fov = _finite(hfov_deg, "hfov_deg")
    if not 1.0 < fov < 179.0:
        raise ValueError("hfov_deg must be within (1, 179)")
    fx = width / (2.0 * math.tan(math.radians(fov) / 2.0))
    return CameraIntrinsics(
        width_px=width,
        height_px=height,
        fx=fx,
        fy=fx,
        cx=width / 2.0,
        cy=height / 2.0,
        calibration_id=f"uvc-uncalibrated-hfov{fov:g}",
    )


def scale_intrinsics(
    intrinsics: CameraIntrinsics, *, width_px: int, height_px: int
) -> CameraIntrinsics:
    """Rescale a calibration to a different negotiated capture resolution.

    A webcam that was asked for 1280×720 and delivered 640×480 has not changed
    optics, but the pixel-space numbers must move with the raster. The
    calibration id gains a ``-scaled`` suffix so the rescale is visible rather
    than implied.
    """

    width = _positive_int(width_px, "width_px")
    height = _positive_int(height_px, "height_px")
    if width == intrinsics.width_px and height == intrinsics.height_px:
        return intrinsics
    sx = width / intrinsics.width_px
    sy = height / intrinsics.height_px
    cal = intrinsics.calibration_id
    if not cal.endswith("-scaled"):
        cal = f"{cal}-scaled"
    return CameraIntrinsics(
        width_px=width,
        height_px=height,
        fx=intrinsics.fx * sx,
        fy=intrinsics.fy * sy,
        cx=intrinsics.cx * sx,
        cy=intrinsics.cy * sy,
        calibration_id=cal,
    )


def intrinsics_from_config(
    config: Mapping[str, Any] | None,
    *,
    width_px: int,
    height_px: int,
) -> CameraIntrinsics:
    """Build intrinsics from an ``intrinsics:`` block, or guess and say so."""

    if not config:
        return uncalibrated_intrinsics(width_px, height_px)
    if not isinstance(config, Mapping):
        raise TypeError("intrinsics config must be a mapping")
    unknown = set(config) - {"fx", "fy", "cx", "cy", "calibration_id", "hfov_deg"}
    if unknown:
        raise ValueError(f"unknown intrinsics keys: {sorted(unknown)}")
    if "fx" not in config:
        return uncalibrated_intrinsics(
            width_px,
            height_px,
            hfov_deg=_finite(config.get("hfov_deg", DEFAULT_UNCALIBRATED_HFOV_DEG), "hfov_deg"),
        )
    fx = _finite(config["fx"], "fx")
    fy = _finite(config.get("fy", fx), "fy")
    cx = _finite(config.get("cx", width_px / 2.0), "cx")
    cy = _finite(config.get("cy", height_px / 2.0), "cy")
    calibration_id = str(config.get("calibration_id", "camera-config"))
    if calibration_id == CALIBRATION_ID_NOMINAL:
        raise ValueError(
            "refusing to stamp the nominal D455 calibration id on a config-supplied "
            "calibration: the nominal id is the SIM contract constant and claiming it "
            "would make a desk camera indistinguishable from the simulator"
        )
    return CameraIntrinsics(
        width_px=_positive_int(width_px, "width_px"),
        height_px=_positive_int(height_px, "height_px"),
        fx=fx,
        fy=fy,
        cx=cx,
        cy=cy,
        calibration_id=calibration_id,
    )


def mount_from_config(config: Mapping[str, Any] | None) -> CameraMountGeometry:
    """Build the mount geometry from a ``mount:`` block; default = Go2 D455."""

    if not config:
        return go2_d455_mount()
    if not isinstance(config, Mapping):
        raise TypeError("mount config must be a mapping")
    allowed = {"height_m", "forward_m", "lateral_m", "pitch_up_deg", "pitch_up_rad"}
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"unknown mount keys: {sorted(unknown)}")
    if "pitch_up_deg" in config and "pitch_up_rad" in config:
        raise ValueError("give pitch_up_deg or pitch_up_rad, not both")
    base = go2_d455_mount()
    pitch = base.pitch_up_rad
    if "pitch_up_deg" in config:
        pitch = math.radians(_finite(config["pitch_up_deg"], "pitch_up_deg"))
    elif "pitch_up_rad" in config:
        pitch = _finite(config["pitch_up_rad"], "pitch_up_rad")
    return CameraMountGeometry(
        height_m=_finite(config.get("height_m", base.height_m), "height_m"),
        forward_m=_finite(config.get("forward_m", base.forward_m), "forward_m"),
        lateral_m=_finite(config.get("lateral_m", base.lateral_m), "lateral_m"),
        pitch_up_rad=pitch,
    )


def spec_from_config(
    config: Mapping[str, Any] | None,
    *,
    width_px: int,
    height_px: int,
    has_depth: bool,
) -> CameraChannelSpec:
    """Assemble the :class:`CameraChannelSpec` a physical backend validates against.

    ``include_segmentation`` is always False: no physical camera produces a
    segmentation buffer, and an envelope that claimed one would be a stub
    masquerading as a sensor.
    """

    config = config or {}
    if not isinstance(config, Mapping):
        raise TypeError("camera config must be a mapping")
    depth_cfg = config.get("depth") or {}
    if not isinstance(depth_cfg, Mapping):
        raise TypeError("camera depth config must be a mapping")
    unknown = set(depth_cfg) - {"min_m", "max_m"}
    if unknown:
        raise ValueError(f"unknown depth keys: {sorted(unknown)}")
    depth_min = _finite(depth_cfg.get("min_m", D455_DEPTH_MIN_M), "depth.min_m")
    depth_max = _finite(depth_cfg.get("max_m", D455_DEPTH_MAX_M), "depth.max_m")
    fps = config.get("fps", D455_RGB_FPS)
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1:
        raise ValueError("fps must be a positive integer")
    return CameraChannelSpec(
        intrinsics=intrinsics_from_config(
            config.get("intrinsics"), width_px=width_px, height_px=height_px
        ),
        mount=mount_from_config(config.get("mount")),
        depth_min_m=depth_min,
        depth_max_m=depth_max,
        rgb_fps=fps,
        depth_fps=fps if has_depth else D455_DEPTH_FPS,
        include_segmentation=False,
    )


def load_camera_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Read the camera-hardware config file, or return ``{}``.

    JSON or YAML, selected by suffix. Absent file with no explicit ``path`` is
    an empty config (every backend then falls back to documented defaults);
    an explicitly-named missing file is a refusal, because a caller who typed a
    path and got silent defaults would never find out.
    """

    from pathlib import Path

    explicit = path is not None
    if path is None:
        env = os.environ.get(CAMERA_CONFIG_ENV, "").strip()
        if not env:
            return {}
        path = env
        explicit = True
    resolved = Path(path)
    if not resolved.is_file():
        if explicit:
            raise FileNotFoundError(f"camera config not found: {resolved}")
        return {}
    text = resolved.read_text(encoding="utf-8")
    if resolved.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        data = yaml.safe_load(text) or {}
    else:
        import json

        data = json.loads(text or "{}")
    if not isinstance(data, Mapping):
        raise TypeError(f"camera config must be a mapping: {resolved}")
    return dict(data)


class PhysicalCameraBackendBase:
    """``CameraBackend`` for a venue that is not the simulator.

    Subclasses implement :meth:`_read_frame` (and usually :meth:`_open` /
    :meth:`_close`). Everything provenance- and clock-shaped happens here so a
    subclass cannot forget it.
    """

    #: MUST be overridden with a real :class:`EvidenceOrigin` member.
    origin: EvidenceOrigin = EvidenceOrigin.UNKNOWN
    kind: str = "physical"

    def __init__(
        self,
        *,
        spec: CameraChannelSpec,
        origin_label: str,
        clock: Callable[[], int] = time.monotonic_ns,
        wall_clock: Callable[[], int] = time.time_ns,
    ) -> None:
        # The origin guard runs at CONSTRUCTION, not at first capture: a backend
        # that never declared one must fail where it is built, in the launcher,
        # not fifty frames into a mission.
        if not isinstance(self.origin, EvidenceOrigin) or self.origin is EvidenceOrigin.UNKNOWN:
            raise TypeError(
                f"{type(self).__name__} must declare a real EvidenceOrigin class "
                "attribute (PHYSICAL for live hardware, REPLAY for a clip)"
            )
        if not isinstance(origin_label, str) or not origin_label:
            raise ValueError("origin_label must name the venue")
        self._channel = CameraChannel(spec)
        self._origin_label = origin_label
        self._clock = clock
        self._wall_clock = wall_clock
        self._last_capture_monotonic_ns: int = -1
        self._last: PhysicalCaptureBuffers | None = None
        self._buffers: dict[str, np.ndarray] = {}
        self._captures = 0
        self._read_failures = 0
        self._opened = False

    # -- introspection ------------------------------------------------------
    @property
    def spec(self) -> CameraChannelSpec:
        return self._channel.spec

    @property
    def origin_label(self) -> str:
        return self._origin_label

    @property
    def last_buffers(self) -> PhysicalCaptureBuffers | None:
        return self._last

    @property
    def captures(self) -> int:
        return self._captures

    @property
    def read_failures(self) -> int:
        return self._read_failures

    def get_buffer(self, blob_ref: str) -> np.ndarray:
        try:
            return self._buffers[blob_ref]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"unknown blob_ref: {blob_ref!r}") from exc

    def health(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "origin": self.origin.value,
            "origin_label": self._origin_label,
            "opened": self._opened,
            "captures": self._captures,
            "read_failures": self._read_failures,
            "spec": self._channel.spec.as_dict(),
            "does_not_prove": list(DOES_NOT_PROVE),
        }

    # -- lifecycle ----------------------------------------------------------
    def open(self) -> None:
        if self._opened:
            return
        self._open()
        self._opened = True

    def close(self) -> None:
        if not self._opened:
            return
        try:
            self._close()
        finally:
            self._opened = False

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _open(self) -> None:  # pragma: no cover - trivial default
        return None

    def _close(self) -> None:  # pragma: no cover - trivial default
        return None

    def _read_frame(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Return ``(rgb_uint8_hwc, depth_m_f32_hw | None)``."""

        raise NotImplementedError

    # -- capture ------------------------------------------------------------
    def capture(
        self,
        *,
        source_timestamp_ns: int | None = None,
        sequence: int | None = None,
        scene_revision: int = 0,
        robot_x: float | None = None,
        robot_y: float | None = None,
        robot_yaw_rad: float | None = None,
    ) -> CameraFrameEnvelope:
        """Read one frame, stamp it, and return the validated envelope.

        ``robot_*`` are accepted and ignored: the ingress passes the mount pose
        so a RENDERER can place a virtual camera. A physical camera is already
        wherever it is — accepting the kwargs keeps the call site identical for
        both venues instead of forking it, and silently pretending the pose
        changed the pixels would be the lie this card exists to prevent.
        """

        if not self._opened:
            self.open()
        monotonic_ns = int(self._clock())
        if monotonic_ns <= self._last_capture_monotonic_ns:
            raise ValueError(
                "capture stamps must strictly increase: "
                f"{monotonic_ns} <= {self._last_capture_monotonic_ns}; a repeated or "
                "regressing stamp makes frame age uncomputable and would let a stale "
                "frame report itself as fresh"
            )
        wall_ns = int(self._wall_clock())
        if wall_ns < 0:
            raise ValueError("wall clock must be non-negative")
        try:
            rgb, depth = self._read_frame()
        except PhysicalCameraUnavailable:
            self._read_failures += 1
            raise
        if rgb is None and depth is None:
            self._read_failures += 1
            raise PhysicalCameraUnavailable(
                f"{self.kind} backend produced no pixels ({self._origin_label})"
            )
        self._last_capture_monotonic_ns = monotonic_ns
        self._captures += 1
        seq = self._captures if sequence is None else int(sequence)
        if seq < 0:
            raise ValueError("sequence must be non-negative")
        source_ts = int(wall_ns if source_timestamp_ns is None else source_timestamp_ns)
        source_ts %= 1 << 62

        rgb_arr = None if rgb is None else np.ascontiguousarray(rgb, dtype=np.uint8)
        depth_arr = None if depth is None else np.ascontiguousarray(depth, dtype=np.float32)
        self._validate_shapes(rgb_arr, depth_arr)

        color_ref = f"{self.kind}://{self._origin_label}/color/{seq}"
        depth_ref = f"{self.kind}://{self._origin_label}/depth/{seq}"
        if rgb_arr is not None:
            self._buffers[color_ref] = rgb_arr
        if depth_arr is not None:
            self._buffers[depth_ref] = depth_arr
        self._last = PhysicalCaptureBuffers(
            color_rgb8=rgb_arr,
            depth_m_f32=depth_arr,
            origin=self.origin,
            origin_label=self._origin_label,
            capture_monotonic_ns=monotonic_ns,
            capture_wall_ns=wall_ns,
            sequence=seq,
        )
        envelope = self._channel.wrap_stub_envelope(
            source_timestamp_ns=source_ts,
            sequence=seq,
            scene_revision=scene_revision,
            class_ids=(),
            color_blob_ref=color_ref if rgb_arr is not None else None,
            depth_blob_ref=depth_ref if depth_arr is not None else None,
        )
        self._channel.validate_envelope(envelope)
        return envelope

    def _validate_shapes(
        self, rgb: np.ndarray | None, depth: np.ndarray | None
    ) -> None:
        intr = self._channel.spec.intrinsics
        if rgb is not None and rgb.shape[:2] != (intr.height_px, intr.width_px):
            raise ValueError(
                f"{self.kind} frame is {rgb.shape[1]}x{rgb.shape[0]} but the channel "
                f"spec says {intr.width_px}x{intr.height_px}; intrinsics and raster "
                "must describe the same image"
            )
        if depth is not None and depth.shape[:2] != (intr.height_px, intr.width_px):
            raise ValueError(
                "depth raster disagrees with the color intrinsics; a physical depth "
                "frame must be ALIGNED to color before it leaves the backend"
            )


def resolve_backend_kind(
    kind: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """The selected physical backend kind, or ``None`` for "no camera".

    Precedence: the explicit argument, then :data:`CAMERA_BACKEND_ENV`. An
    unknown name is a refusal that lists the accepted ones — a typo at the
    launcher must not come up on a different venue than the operator asked for.
    """

    environ = os.environ if env is None else env
    raw = kind if kind is not None else environ.get(CAMERA_BACKEND_ENV, "")
    text = str(raw or "").strip().lower()
    if not text or text in {"none", "off"}:
        return None
    if text not in PHYSICAL_BACKEND_KINDS:
        raise ValueError(
            f"unknown camera backend {text!r}; expected one of "
            f"{', '.join(PHYSICAL_BACKEND_KINDS)}"
        )
    return text


def open_physical_backend(
    kind: str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    **overrides: Any,
) -> tuple[PhysicalCameraBackendBase, Literal["uvc", "realsense", "recorded"]]:
    """Construct the selected physical backend. Imports lazily, per kind.

    Lazy imports matter: ``cv2`` and ``pyrealsense2`` are optional extras, and a
    host that has neither must still be able to select ``recorded``.
    """

    selected = resolve_backend_kind(kind)
    if selected is None:
        raise ValueError(
            "no camera backend selected; pass a kind or set "
            f"{CAMERA_BACKEND_ENV}={'|'.join(PHYSICAL_BACKEND_KINDS)}"
        )
    settings = dict(load_camera_config(config_path) if config is None else config)
    settings.pop("kind", None)
    settings.update(overrides)
    if selected == "uvc":
        from parcel_robot.camera_channel.backends.uvc import UvcCameraBackend

        return UvcCameraBackend(**settings), "uvc"
    if selected == "realsense":
        from parcel_robot.camera_channel.backends.realsense import RealSenseCameraBackend

        return RealSenseCameraBackend(**settings), "realsense"
    from parcel_robot.camera_channel.backends.recorded import RecordedCameraBackend

    return RecordedCameraBackend(**settings), "recorded"


def camera_ingress_kwargs(backend: PhysicalCameraBackendBase) -> dict[str, Any]:
    """The ``CameraIngress`` kwargs a physical backend implies — ``origin`` INCLUDED.

    **This exists because forgetting one keyword silently defeats the whole
    card.** :class:`~parcel_robot.camera_channel.ingress.CameraIngress` carries
    its own ``origin`` field, defaulting to ``"unknown"``, and the published
    :class:`~parcel_robot.camera_channel.ingress.CameraDetectionFrame` is
    stamped from ``self.origin`` — the ingress never reads the backend's
    ``PhysicalCaptureBuffers.origin`` (P1-B owns that file; the default is
    ``unknown`` on purpose, because a renderer that could mint ``physical`` by
    default is the W0-A defect). So an ingress built over a real webcam WITHOUT
    ``origin=`` publishes every frame as ``unknown``: the buffers are honest and
    every derived record downstream is not.

    Fable's P1-A verification caught exactly that in this card's own handoff
    snippet. The fix is not "remember the keyword" — it is to derive the
    declaration from the backend that is producing the pixels, which is what
    this function does. Every composition root that attaches a physical backend
    should build its ingress through it.

    ``depth_max_m`` is passed WITHOUT the 1 cm trim ``CameraIngress.from_model_data``
    applies: that trim exists because MuJoCo clips background depth to exactly
    ``depth_max_m`` and the far wall would otherwise be counted as a surface. A
    physical sensor has no such clip — a D455 reports 0 for invalid depth — so
    trimming here would discard real far returns for a rendering artefact that
    is not present.
    """

    if not isinstance(backend, PhysicalCameraBackendBase):
        raise TypeError("camera_ingress_kwargs expects a physical CameraBackend")
    spec = backend.spec
    return {
        "backend": backend,
        "intrinsics": spec.intrinsics,
        "mount": spec.mount,
        "depth_min_m": float(spec.depth_min_m),
        "depth_max_m": float(spec.depth_max_m),
        # The one line this helper exists for.
        "origin": backend.origin.value,
    }


__all__ = [
    "CAMERA_BACKEND_ENV",
    "CAMERA_CONFIG_ENV",
    "DEFAULT_UNCALIBRATED_HFOV_DEG",
    "DOES_NOT_PROVE",
    "PHYSICAL_BACKEND_KINDS",
    "PhysicalCameraBackendBase",
    "PhysicalCameraUnavailable",
    "PhysicalCaptureBuffers",
    "camera_ingress_kwargs",
    "intrinsics_from_config",
    "load_camera_config",
    "mount_from_config",
    "open_physical_backend",
    "resolve_backend_kind",
    "scale_intrinsics",
    "spec_from_config",
    "uncalibrated_intrinsics",
]
