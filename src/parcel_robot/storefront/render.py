"""Synthetic CameraChannel RGB containing readable storefront signage (P3).

Composites fixture placards into a D455-nominal frame so OCR smoke can run on
synthetic pixels without EGL. Texture PNGs under the fixture pack are also
suitable for MuJoCo geom materials when an EGL backend is available.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from parcel_robot.camera_channel.backends.synthetic import CaptureBuffers
from parcel_robot.camera_channel.channel import CameraChannel, CameraChannelSpec
from parcel_robot.camera_channel.d455 import D455_HEIGHT_PX, D455_WIDTH_PX
from parcel_robot.camera_channel.frames import CameraFrameEnvelope
from parcel_robot.storefront.fixtures import (
    DOES_NOT_PROVE,
    StorefrontFixture,
    StorefrontManifest,
    load_manifest,
)
from parcel_robot.storefront.placards import render_placard_rgb

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _read_png_rgb(path: Path) -> np.ndarray:
    """Decode RGB PNGs written by ``placards.write_png_rgb`` (stdlib only)."""

    import struct
    import zlib

    data = path.read_bytes()
    if not data.startswith(_PNG_SIG):
        raise ValueError(f"not a PNG: {path}")
    offset = 8
    width = height = None
    idat = bytearray()
    while offset + 8 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        tag = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type, *_ = struct.unpack(">IIBBBBB", chunk)
            if bit_depth != 8 or color_type != 2:
                raise ValueError("only 8-bit RGB PNGs are supported")
        elif tag == b"IDAT":
            idat.extend(chunk)
        elif tag == b"IEND":
            break
    if width is None or height is None:
        raise ValueError("PNG missing IHDR")
    raw = zlib.decompress(bytes(idat))
    stride = 1 + width * 3
    if len(raw) != stride * height:
        raise ValueError("PNG IDAT size mismatch")
    rows = []
    for y in range(height):
        start = y * stride
        if raw[start] != 0:
            raise ValueError("only filter-none PNG rows are supported")
        rows.append(np.frombuffer(raw, dtype=np.uint8, count=width * 3, offset=start + 1))
    return np.vstack(rows).reshape(height, width, 3).copy()


def _roi_pixels(
    roi_norm: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = roi_norm
    px0 = max(0, min(width - 1, round(x0 * width)))
    py0 = max(0, min(height - 1, round(y0 * height)))
    px1 = max(px0 + 1, min(width, round(x1 * width)))
    py1 = max(py0 + 1, min(height, round(y1 * height)))
    return px0, py0, px1, py1


def composite_storefront_frame(
    manifest: StorefrontManifest,
    *,
    width: int = D455_WIDTH_PX,
    height: int = D455_HEIGHT_PX,
    storefront_ids: tuple[str, ...] | None = None,
    street_rgb: tuple[int, int, int] = (48, 52, 58),
    sidewalk_rgb: tuple[int, int, int] = (90, 90, 95),
) -> tuple[np.ndarray, tuple[StorefrontFixture, ...]]:
    """Build a D455-sized RGB frame with placard textures in authored ROIs."""

    if width < 64 or height < 64:
        raise ValueError("frame must be at least 64×64")
    selected = (
        tuple(manifest.by_id(sid) for sid in storefront_ids)
        if storefront_ids is not None
        else manifest.storefronts
    )
    frame = np.empty((height, width, 3), dtype=np.uint8)
    horizon = int(height * 0.45)
    frame[:horizon] = np.asarray((70, 110, 160), dtype=np.uint8)
    frame[horizon:] = np.asarray(street_rgb, dtype=np.uint8)
    curb = int(height * 0.78)
    frame[curb : curb + 8] = np.asarray(sidewalk_rgb, dtype=np.uint8)

    for fixture in selected:
        x0, y0, x1, y1 = _roi_pixels(fixture.roi_norm, width=width, height=height)
        pw, ph = x1 - x0, y1 - y0
        try:
            placard = _read_png_rgb(fixture.placard_path)
        except (OSError, ValueError):
            placard = render_placard_rgb(
                fixture.expected_text,
                width=max(64, pw),
                height=max(32, ph),
                bg_rgb=fixture.bg_rgb,
                fg_rgb=fixture.fg_rgb,
            )
        ys = (np.linspace(0, placard.shape[0] - 1, ph)).astype(np.int32)
        xs = (np.linspace(0, placard.shape[1] - 1, pw)).astype(np.int32)
        resized = placard[ys][:, xs]
        frame[y0:y1, x0:x1] = resized
    return frame, selected


@dataclass(frozen=True, slots=True)
class StorefrontCapture:
    """One synthetic capture with fixtures that were painted into the frame."""

    envelope: CameraFrameEnvelope
    color_rgb8: np.ndarray
    depth_m_f32: np.ndarray
    fixtures: tuple[StorefrontFixture, ...]
    buffers: CaptureBuffers
    does_not_prove: tuple[str, ...] = DOES_NOT_PROVE


class StorefrontSyntheticAdapter:
    """Expose synthetic RGB (CameraChannel-shaped) with readable signage.

    CI path: no EGL. Placard PNGs from the fixture pack are composited into a
    D455-nominal frame. MuJoCo can later bind the same PNGs as geom textures;
    that does not change this adapter's honesty (HR-4).
    """

    kind = "storefront_synthetic"

    def __init__(
        self,
        *,
        manifest: StorefrontManifest | None = None,
        spec: CameraChannelSpec | None = None,
        storefront_ids: tuple[str, ...] | None = None,
    ) -> None:
        self._manifest = manifest if manifest is not None else load_manifest()
        self._channel = CameraChannel(spec)
        self._storefront_ids = storefront_ids
        self._buffers: dict[str, np.ndarray] = {}
        self._last: StorefrontCapture | None = None

    @property
    def spec(self) -> CameraChannelSpec:
        return self._channel.spec

    @property
    def manifest(self) -> StorefrontManifest:
        return self._manifest

    @property
    def last_capture(self) -> StorefrontCapture | None:
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
        intr = self.spec.intrinsics
        color, fixtures = composite_storefront_frame(
            self._manifest,
            width=intr.width_px,
            height=intr.height_px,
            storefront_ids=self._storefront_ids,
        )
        depth = np.full((intr.height_px, intr.width_px), 4.5, dtype=np.float32)
        # Paint per-sign depth from fixture range.
        for fixture in fixtures:
            x0, y0, x1, y1 = _roi_pixels(
                fixture.roi_norm, width=intr.width_px, height=intr.height_px
            )
            depth[y0:y1, x0:x1] = float(fixture.range_m)

        color_ref = f"mem://storefront/color/{sequence}"
        depth_ref = f"mem://storefront/depth/{sequence}"
        self._buffers[color_ref] = color
        self._buffers[depth_ref] = depth
        buffers = CaptureBuffers(color_rgb8=color, depth_m_f32=depth, seg_u16=None)
        envelope = self._channel.wrap_stub_envelope(
            source_timestamp_ns=source_timestamp_ns,
            sequence=sequence,
            scene_revision=scene_revision,
            class_ids=("background", "sign", "sidewalk", "curb"),
            color_blob_ref=color_ref,
            depth_blob_ref=depth_ref,
            seg_blob_ref=None,
        )
        self._channel.validate_envelope(envelope)
        self._last = StorefrontCapture(
            envelope=envelope,
            color_rgb8=color,
            depth_m_f32=depth,
            fixtures=fixtures,
            buffers=buffers,
            does_not_prove=self._manifest.does_not_prove,
        )
        return envelope

    def get_color(self) -> np.ndarray:
        if self._last is None:
            raise RuntimeError("capture() before get_color()")
        return self._last.color_rgb8
