"""Replay a committed RGB(+depth) clip as a ``CameraBackend`` — CI's venue.

Card P1-A, work item 3. The contract tests for the physical path have to run on
a machine with no camera (which, measured 2026-08-22, is this one), so the
whole chain — capture → stamp → origin → daemon → detections — is exercised
against a small clip on disk instead of a device.

**A replay is REPLAY, never PHYSICAL, and no manifest can change that.**
:attr:`RecordedCameraBackend.origin` is
:attr:`~parcel_robot.evidence_origin.EvidenceOrigin.REPLAY`, full stop. The
clip manifest carries ``captured_origin`` for provenance — it records what the
pixels were when they were recorded — but that is a HISTORICAL fact about the
file, not the authority of the frame being handed out now. A clip recorded from
a real D455 still replays as REPLAY: the photons are hours old, the scene has
moved on, and letting a file mint live physical authority is precisely the
defect ``EvidenceOrigin`` was introduced to close (card W0-A, defect P0-2).
:meth:`RecordedCameraBackend.__init__` refuses an ``origin`` override for the
same reason.

Clip format
-----------
One ``.npz`` (``numpy.savez_compressed``) holding:

* ``color`` — ``(N, H, W, 3)`` uint8, RGB
* ``depth`` — ``(N, H, W)`` float32 metres, optional
* ``manifest`` — a 0-d array holding a JSON object (below)

The manifest is inside the same file on purpose: a clip whose metadata can be
separated from its pixels is a clip whose intrinsics can silently stop matching
its raster.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from parcel_robot.camera_channel.backends.physical import (
    PhysicalCameraBackendBase,
    PhysicalCameraUnavailable,
    spec_from_config,
)
from parcel_robot.evidence_origin import EvidenceOrigin

CLIP_FORMAT_VERSION = 1

#: Ceiling on frames held in memory from one clip. CI clips are tiny; this stops
#: a mistakenly-huge file from being loaded into a test process.
MAX_CLIP_FRAMES = 4096


class ClipExhausted(PhysicalCameraUnavailable):
    """A non-looping clip ran out of frames."""


class ClipInvalid(ValueError):
    """The clip file is not a well-formed P1-A clip."""


@dataclass(frozen=True, slots=True)
class ClipManifest:
    """What a clip says about itself. Validated on load, never trusted raw."""

    version: int
    clip_id: str
    frames: int
    width_px: int
    height_px: int
    has_depth: bool
    fps: int
    captured_origin: EvidenceOrigin
    captured_label: str
    notes: str = ""
    intrinsics: Mapping[str, Any] | None = None
    mount: Mapping[str, Any] | None = None
    depth: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "clip_id": self.clip_id,
            "frames": self.frames,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "has_depth": self.has_depth,
            "fps": self.fps,
            "captured_origin": self.captured_origin.value,
            "captured_label": self.captured_label,
            "notes": self.notes,
            "intrinsics": None if self.intrinsics is None else dict(self.intrinsics),
            "mount": None if self.mount is None else dict(self.mount),
            "depth": None if self.depth is None else dict(self.depth),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ClipManifest:
        if not isinstance(value, Mapping):
            raise ClipInvalid("clip manifest must be an object")
        required = {
            "version",
            "clip_id",
            "frames",
            "width_px",
            "height_px",
            "has_depth",
            "fps",
            "captured_origin",
            "captured_label",
        }
        missing = required - set(value)
        if missing:
            raise ClipInvalid(f"clip manifest missing keys: {sorted(missing)}")
        unknown = set(value) - required - {"notes", "intrinsics", "mount", "depth"}
        if unknown:
            raise ClipInvalid(f"unknown clip manifest keys: {sorted(unknown)}")
        version = int(value["version"])
        if version != CLIP_FORMAT_VERSION:
            raise ClipInvalid(
                f"clip format version {version} is not {CLIP_FORMAT_VERSION}"
            )
        try:
            captured = EvidenceOrigin(str(value["captured_origin"]))
        except ValueError as exc:
            raise ClipInvalid(
                f"captured_origin {value['captured_origin']!r} is not an EvidenceOrigin"
            ) from exc
        frames = int(value["frames"])
        if not 1 <= frames <= MAX_CLIP_FRAMES:
            raise ClipInvalid(f"frames must be within [1, {MAX_CLIP_FRAMES}]")
        return cls(
            version=version,
            clip_id=str(value["clip_id"]),
            frames=frames,
            width_px=int(value["width_px"]),
            height_px=int(value["height_px"]),
            has_depth=bool(value["has_depth"]),
            fps=int(value["fps"]),
            captured_origin=captured,
            captured_label=str(value["captured_label"]),
            notes=str(value.get("notes", "")),
            intrinsics=value.get("intrinsics"),
            mount=value.get("mount"),
            depth=value.get("depth"),
        )


def write_clip(
    path: str | Path,
    colors: Sequence[np.ndarray] | np.ndarray,
    *,
    clip_id: str,
    captured_origin: EvidenceOrigin,
    captured_label: str,
    depths: Sequence[np.ndarray] | np.ndarray | None = None,
    fps: int = 30,
    notes: str = "",
    intrinsics: Mapping[str, Any] | None = None,
    mount: Mapping[str, Any] | None = None,
    depth_band: Mapping[str, Any] | None = None,
) -> ClipManifest:
    """Write a P1-A clip. Returns the manifest that was stored."""

    if not isinstance(captured_origin, EvidenceOrigin):
        raise TypeError("captured_origin must be an EvidenceOrigin member")
    color = np.ascontiguousarray(np.asarray(colors), dtype=np.uint8)
    if color.ndim != 4 or color.shape[3] != 3:
        raise ClipInvalid("colors must be (N, H, W, 3) uint8 RGB")
    frames, height, width = color.shape[0], color.shape[1], color.shape[2]
    depth_arr: np.ndarray | None = None
    if depths is not None:
        depth_arr = np.ascontiguousarray(np.asarray(depths), dtype=np.float32)
        if depth_arr.shape != (frames, height, width):
            raise ClipInvalid("depths must be (N, H, W) float32 matching the colors")
    manifest = ClipManifest(
        version=CLIP_FORMAT_VERSION,
        clip_id=str(clip_id),
        frames=int(frames),
        width_px=int(width),
        height_px=int(height),
        has_depth=depth_arr is not None,
        fps=int(fps),
        captured_origin=captured_origin,
        captured_label=str(captured_label),
        notes=str(notes),
        intrinsics=None if intrinsics is None else dict(intrinsics),
        mount=None if mount is None else dict(mount),
        depth=None if depth_band is None else dict(depth_band),
    )
    payload: dict[str, Any] = {
        "color": color,
        "manifest": np.asarray(json.dumps(manifest.as_dict(), sort_keys=True)),
    }
    if depth_arr is not None:
        payload["depth"] = depth_arr
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        np.savez_compressed(handle, **payload)
    return manifest


def read_clip(path: str | Path) -> tuple[ClipManifest, np.ndarray, np.ndarray | None]:
    """Load a clip and check its manifest against its actual arrays."""

    target = Path(path)
    if not target.is_file():
        raise ClipInvalid(f"clip not found: {target}")
    with np.load(target, allow_pickle=False) as data:
        if "manifest" not in data or "color" not in data:
            raise ClipInvalid(f"clip {target} is missing 'manifest' or 'color'")
        manifest = ClipManifest.from_mapping(json.loads(str(data["manifest"])))
        color = np.ascontiguousarray(data["color"], dtype=np.uint8)
        depth = (
            np.ascontiguousarray(data["depth"], dtype=np.float32)
            if "depth" in data.files
            else None
        )
    if color.ndim != 4 or color.shape[3] != 3:
        raise ClipInvalid("clip color array must be (N, H, W, 3)")
    if (color.shape[0], color.shape[1], color.shape[2]) != (
        manifest.frames,
        manifest.height_px,
        manifest.width_px,
    ):
        raise ClipInvalid(
            "clip manifest disagrees with its own pixels: "
            f"manifest {manifest.frames}x{manifest.height_px}x{manifest.width_px} vs "
            f"array {color.shape[:3]}"
        )
    if manifest.has_depth != (depth is not None):
        raise ClipInvalid("clip manifest's has_depth disagrees with the stored arrays")
    if depth is not None and depth.shape != color.shape[:3]:
        raise ClipInvalid("clip depth array does not match the color array")
    return manifest, color, depth


class RecordedCameraBackend(PhysicalCameraBackendBase):
    """Replay a committed clip through the physical-backend contract."""

    origin = EvidenceOrigin.REPLAY
    kind = "recorded"

    def __init__(
        self,
        clip: str | Path,
        *,
        loop: bool = True,
        intrinsics: Mapping[str, Any] | None = None,
        mount: Mapping[str, Any] | None = None,
        depth: Mapping[str, Any] | None = None,
        **clock_kwargs: Any,
    ) -> None:
        if "origin" in clock_kwargs:
            raise TypeError(
                "a recorded clip may not choose its own origin: a replay is REPLAY, "
                "and letting a file declare PHYSICAL would let recorded pixels mint "
                "live authority"
            )
        manifest, color, depth_arr = read_clip(clip)
        self._clip_path = Path(clip)
        self._manifest = manifest
        self._color = color
        self._depth = depth_arr
        self._index = 0
        self._loop = bool(loop)
        config: dict[str, Any] = {
            "fps": manifest.fps,
            "intrinsics": dict(intrinsics) if intrinsics else (
                dict(manifest.intrinsics) if manifest.intrinsics else None
            ),
            "mount": dict(mount) if mount else (
                dict(manifest.mount) if manifest.mount else None
            ),
            "depth": dict(depth) if depth else (
                dict(manifest.depth) if manifest.depth else None
            ),
        }
        spec = spec_from_config(
            config,
            width_px=manifest.width_px,
            height_px=manifest.height_px,
            has_depth=manifest.has_depth,
        )
        super().__init__(
            spec=spec,
            origin_label=f"clip:{manifest.clip_id}",
            **clock_kwargs,
        )

    @property
    def manifest(self) -> ClipManifest:
        return self._manifest

    @property
    def clip_path(self) -> Path:
        return self._clip_path

    @property
    def has_depth(self) -> bool:
        return self._depth is not None

    @property
    def frames(self) -> int:
        return int(self._color.shape[0])

    @property
    def index(self) -> int:
        """Index of the frame the NEXT capture will return."""

        return self._index

    def rewind(self) -> None:
        self._index = 0

    def health(self) -> dict[str, Any]:
        info = super().health()
        info["clip"] = str(self._clip_path)
        info["manifest"] = self._manifest.as_dict()
        info["index"] = self._index
        info["loop"] = self._loop
        return info

    def _read_frame(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        total = self.frames
        if self._index >= total:
            if not self._loop:
                raise ClipExhausted(
                    f"clip {self._manifest.clip_id} has {total} frames and they are spent"
                )
            self._index = 0
        i = self._index
        self._index += 1
        rgb = self._color[i]
        depth = None if self._depth is None else self._depth[i]
        return rgb, depth


def open_recorded_backend(
    clip: str | Path, *, config: Mapping[str, Any] | None = None, **overrides: Any
) -> RecordedCameraBackend:
    """Build and open a recorded-clip backend."""

    settings = dict(config or {})
    settings.pop("kind", None)
    settings.pop("clip", None)
    settings.update(overrides)
    backend = RecordedCameraBackend(clip, **settings)
    backend.open()
    return backend


def record_clip(
    backend: PhysicalCameraBackendBase,
    path: str | Path,
    *,
    frames: int,
    clip_id: str,
    notes: str = "",
) -> ClipManifest:
    """Capture ``frames`` from a live backend into a replayable clip.

    This is how the owner turns one desk session into a CI fixture. The clip's
    ``captured_origin`` is the LIVE backend's origin, so a clip recorded from a
    webcam records that its pixels were physical — while still replaying as
    REPLAY, which is the whole point of keeping the two fields apart.
    """

    if frames < 1:
        raise ValueError("frames must be positive")
    colors: list[np.ndarray] = []
    depths: list[np.ndarray] = []
    backend.open()
    for _ in range(int(frames)):
        backend.capture()
        buffers = backend.last_buffers
        if buffers is None or buffers.color_rgb8 is None:
            raise PhysicalCameraUnavailable("backend produced no color buffer to record")
        colors.append(np.array(buffers.color_rgb8, copy=True))
        if buffers.depth_m_f32 is not None:
            depths.append(np.array(buffers.depth_m_f32, copy=True))
    if depths and len(depths) != len(colors):
        raise PhysicalCameraUnavailable("clip has depth for only some frames")
    spec = backend.spec
    return write_clip(
        path,
        colors,
        clip_id=clip_id,
        captured_origin=backend.origin,
        captured_label=backend.origin_label,
        depths=depths or None,
        fps=spec.rgb_fps,
        notes=notes,
        intrinsics={
            "fx": spec.intrinsics.fx,
            "fy": spec.intrinsics.fy,
            "cx": spec.intrinsics.cx,
            "cy": spec.intrinsics.cy,
            "calibration_id": spec.intrinsics.calibration_id,
        },
        mount={
            "height_m": spec.mount.height_m,
            "forward_m": spec.mount.forward_m,
            "lateral_m": spec.mount.lateral_m,
            "pitch_up_rad": spec.mount.pitch_up_rad,
        },
        depth_band={"min_m": spec.depth_min_m, "max_m": spec.depth_max_m},
    )


__all__ = [
    "CLIP_FORMAT_VERSION",
    "MAX_CLIP_FRAMES",
    "ClipExhausted",
    "ClipInvalid",
    "ClipManifest",
    "RecordedCameraBackend",
    "open_recorded_backend",
    "read_clip",
    "record_clip",
    "write_clip",
]
