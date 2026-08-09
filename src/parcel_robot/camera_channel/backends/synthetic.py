"""Deterministic synthetic CameraBackend for CI / headless without EGL."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from parcel_robot.camera_channel.channel import CameraChannel, CameraChannelSpec
from parcel_robot.camera_channel.frames import CameraFrameEnvelope


@dataclass(frozen=True, slots=True)
class CaptureBuffers:
    """In-memory pixel payloads keyed by envelope blob_ref."""

    color_rgb8: np.ndarray
    depth_m_f32: np.ndarray
    seg_u16: np.ndarray | None = None


class SyntheticCameraBackend:
    """Fill CameraChannel envelopes with seed-stable synthetic pixels.

    Used when MuJoCo EGL/OSMesa is unavailable (typical CI). Patterned RGB /
    depth / seg are **not** sensor-realistic — HR-4 still applies.
    """

    kind = "synthetic"

    def __init__(
        self,
        spec: CameraChannelSpec | None = None,
        *,
        class_ids: tuple[str, ...] = ("background", "person", "sign", "curb"),
        seed: int = 0,
    ) -> None:
        self._channel = CameraChannel(spec)
        self._class_ids = tuple(class_ids)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an integer")
        self._seed = seed
        self._buffers: dict[str, np.ndarray] = {}
        self._last: CaptureBuffers | None = None

    @property
    def spec(self) -> CameraChannelSpec:
        return self._channel.spec

    @property
    def last_buffers(self) -> CaptureBuffers | None:
        return self._last

    def get_buffer(self, blob_ref: str) -> np.ndarray:
        try:
            return self._buffers[blob_ref]
        except KeyError as exc:
            raise KeyError(f"unknown blob_ref: {blob_ref!r}") from exc

    def capture(
        self,
        *,
        source_timestamp_ns: int,
        sequence: int,
        scene_revision: int = 0,
    ) -> CameraFrameEnvelope:
        intr = self._channel.spec.intrinsics
        h, w = intr.height_px, intr.width_px
        rng = np.random.default_rng(self._seed + int(sequence))

        yy, xx = np.mgrid[0:h, 0:w]
        color = np.empty((h, w, 3), dtype=np.uint8)
        color[..., 0] = ((xx + sequence * 17) % 256).astype(np.uint8)
        color[..., 1] = ((yy + sequence * 31) % 256).astype(np.uint8)
        color[..., 2] = np.uint8(40 + (sequence % 50))
        # Deterministic soft noise so two sequences differ but same seq matches.
        color[..., 0] = np.clip(
            color[..., 0].astype(np.int16) + rng.integers(-2, 3, size=(h, w)),
            0,
            255,
        ).astype(np.uint8)

        depth_min = self._channel.spec.depth_min_m
        depth_max = self._channel.spec.depth_max_m
        depth = (
            depth_min
            + 0.35
            + 0.001 * (xx.astype(np.float32) + yy.astype(np.float32))
            + 0.01 * float(sequence % 7)
        ).astype(np.float32)
        depth = np.clip(depth, depth_min, depth_max)

        seg: np.ndarray | None = None
        if self._channel.spec.include_segmentation:
            seg = np.zeros((h, w), dtype=np.uint16)
            # Central person-ish blob + upper sign strip (low-viewpoint stress cue).
            cy, cx = h // 2, w // 2
            seg[cy - 40 : cy + 120, cx - 35 : cx + 35] = 1  # person
            seg[20:80, cx - 80 : cx + 80] = 2  # sign
            seg[h - 60 : h, :] = 3  # curb / ground band

        color_ref = f"mem://synthetic/color/{sequence}"
        depth_ref = f"mem://synthetic/depth/{sequence}"
        seg_ref = f"mem://synthetic/seg/{sequence}" if seg is not None else None
        self._buffers[color_ref] = color
        self._buffers[depth_ref] = depth
        if seg is not None and seg_ref is not None:
            self._buffers[seg_ref] = seg
        self._last = CaptureBuffers(color_rgb8=color, depth_m_f32=depth, seg_u16=seg)

        return self._channel.wrap_stub_envelope(
            source_timestamp_ns=source_timestamp_ns,
            sequence=sequence,
            scene_revision=scene_revision,
            class_ids=self._class_ids if seg is not None else (),
            color_blob_ref=color_ref,
            depth_blob_ref=depth_ref,
            seg_blob_ref=seg_ref,
        )
