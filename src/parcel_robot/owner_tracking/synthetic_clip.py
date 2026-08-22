"""A two-person clip with no camera in the building.

Card P1-C, work item 4 asks for *"a recorded clip with two people (synthetic or
the owner's own recorded session, owner-gated)"*. This host has no camera
attached (no ``/dev/video*``, no RealSense on USB — board, Wave P1/P2 host
facts), so the clip is **synthesized**: two people with deliberately different
appearances walk scripted paths past a fixed camera, cross each other, and one
of them disappears behind an occluder and comes back.

WHAT A SYNTHETIC CLIP CAN AND CANNOT PROVE
------------------------------------------
It can prove the *mechanism*: that association is appearance-driven rather than
nearest-neighbour, that a track id survives an occlusion, that an empty gallery
yields no owner claim, that the confidence is a number that came out of an
encoder. Those are structural properties and a rendered clip exercises them
exactly as a real one would.

It cannot prove *recall on a real person*. Two flat-shaded bodies with a stripe
pattern are much easier for SigLIP-2 to tell apart than two housemates in the
same grey hoodie, and the separation margin measured here is therefore an upper
bound, not an estimate. The live rows in
``scrum/20260822/task_8/P1C_STATUS.md`` are the ones that answer that, and they
are OWNER-GATED on a camera.

WHY THE SCRIPT IS DATA AND THE PIXELS ARE NOT
---------------------------------------------
``tests/data/p1c_two_person_clip.json`` holds the *script* — per-frame world
positions, appearances, visibility — and the frames are rendered from it
deterministically here. Shipping a few hundred KB of rendered PNGs would have
made the fixture opaque: an auditor could not tell whether the crossing
actually crosses without opening an image viewer. Shipping the script makes the
scenario readable and the rendering reproducible.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parcel_robot.camera_channel.ingress import CameraDetectionFrame, CameraDetectionRecord

CLIP_SCHEMA = "parcel.p1c_two_person_clip.v1"

#: Standing height of the rendered bodies, metres. Sets the box height in pixels.
PERSON_HEIGHT_M = 1.70
#: Shoulder width, metres. Sets the box width.
PERSON_WIDTH_M = 0.52


@dataclass(frozen=True, slots=True)
class Appearance:
    """One person's flat-shaded look. Distinct on purpose; see module docstring."""

    person_id: str
    shirt: tuple[int, int, int]
    trouser: tuple[int, int, int]
    skin: tuple[int, int, int]
    pattern: str = "plain"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Appearance:
        return cls(
            person_id=str(value["id"]),
            shirt=tuple(int(v) for v in value["shirt"]),  # type: ignore[arg-type]
            trouser=tuple(int(v) for v in value["trouser"]),  # type: ignore[arg-type]
            skin=tuple(int(v) for v in value["skin"]),  # type: ignore[arg-type]
            pattern=str(value.get("pattern", "plain")),
        )


@dataclass(frozen=True, slots=True)
class ClipScript:
    """The scenario, as ``tests/data/p1c_two_person_clip.json`` carries it."""

    width: int
    height: int
    fps: float
    fx: float
    fy: float
    cx: float
    cy: float
    camera_height_m: float
    people: tuple[Appearance, ...]
    frames: tuple[Mapping[str, Any], ...]
    owner_id: str = "owner"

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ClipScript:
        if value.get("schema") != CLIP_SCHEMA:
            raise ValueError(f"clip script schema is {value.get('schema')!r}, expected {CLIP_SCHEMA!r}")
        camera = value["camera"]
        return cls(
            width=int(value["width"]),
            height=int(value["height"]),
            fps=float(value["fps"]),
            fx=float(camera["fx"]),
            fy=float(camera["fy"]),
            cx=float(camera["cx"]),
            cy=float(camera["cy"]),
            camera_height_m=float(camera["height_m"]),
            people=tuple(Appearance.from_mapping(p) for p in value["people"]),
            frames=tuple(dict(f) for f in value["frames"]),
            owner_id=str(value.get("owner_id", "owner")),
        )

    @classmethod
    def load(cls, path: str | Path) -> ClipScript:
        return cls.from_mapping(json.loads(Path(path).read_text(encoding="utf-8")))


def build_default_script() -> dict[str, Any]:
    """The scenario the card asks for, as plain data.

    Twenty frames at 4 Hz, 640×480, ~93° HFOV. The camera sits at the origin
    looking down +x; the two people walk past each other at ~1.05 m/s.

    * frames 0-5   — both people walk in, well separated. **Enrollment frames.**
    * frames 8-11  — they CROSS. The true crossing falls between frames 9 and
      10, so the closest sampled world separation is ~0.33 m (lateral 0.26 m,
      depth 0.20 m) — comfortably inside the association gate, which is exactly
      why a position-only tracker swaps here. In the image the boxes overlap by
      about half a body width: a shoulder-brush pass, not a total eclipse, so
      each crop is still mostly its own person.
    * frames 13-16 — the owner is fully OCCLUDED (four frames, one second).
    * frames 17-19 — the owner returns and walks out on the far side.

    Held-out by construction: the enrollment frames (0-5) are not the frames the
    identity rows are measured on (6-19), so no measured cosine is a crop
    against itself.
    """

    frames: list[dict[str, Any]] = []
    for index in range(20):
        t = index / 4.0
        # Owner: left to right across the field of view, walking slightly away.
        owner_y = 2.47 - 0.26 * index
        owner_x = 3.50 - 0.0263 * index
        # Other: right to left and slightly toward the camera, so the two swap
        # both sides AND depth order through the middle.
        other_y = -2.47 + 0.26 * index
        other_x = 2.80 + 0.0263 * index
        occluded = 13 <= index <= 16
        frames.append(
            {
                "t": round(t, 3),
                "poses": {
                    "owner": {
                        "x": round(owner_x, 4),
                        "y": round(owner_y, 4),
                        "visible": not occluded,
                    },
                    "other": {"x": round(other_x, 4), "y": round(other_y, 4), "visible": True},
                },
            }
        )
    return {
        "schema": CLIP_SCHEMA,
        "note": (
            "Card P1-C fixture. Synthesized because this host has no camera. "
            "Frames 0-5 are the enrollment set; identity rows are measured on "
            "6-19 so no cosine is a crop against itself. Crossing between "
            "frames 9 and 10, owner occluded on frames 13-16."
        ),
        "width": 640,
        "height": 480,
        "fps": 4.0,
        "owner_id": "owner",
        "camera": {"fx": 300.0, "fy": 300.0, "cx": 320.0, "cy": 240.0, "height_m": 0.42},
        "enrollment_frames": [0, 1, 2, 3, 4, 5],
        "crossing_frames": [8, 9, 10, 11],
        "occlusion_frames": [13, 14, 15, 16],
        "people": [
            {
                "id": "owner",
                "shirt": [38, 72, 196],
                "trouser": [26, 28, 58],
                "skin": [228, 192, 162],
                "pattern": "vstripe",
            },
            {
                "id": "other",
                "shirt": [206, 92, 36],
                "trouser": [72, 62, 40],
                "skin": [146, 108, 82],
                "pattern": "hband",
            },
        ],
        "frames": frames,
    }


# --------------------------------------------------------------- projection
def project(
    script: ClipScript, world_x: float, world_y: float
) -> tuple[tuple[float, float, float, float], float, float]:
    """World (x forward, y left) → (box, range_m, bearing_rad). Pinhole, no distortion."""

    if world_x <= 0.05:
        raise ValueError("a person behind the image plane cannot be projected")
    range_m = math.hypot(world_x, world_y)
    bearing = math.atan2(world_y, world_x)
    # Optical convention: +y (left) maps to a SMALLER column.
    u_centre = script.cx - script.fx * (world_y / world_x)
    half_w = 0.5 * script.fx * (PERSON_WIDTH_M / world_x)
    top_m = PERSON_HEIGHT_M - script.camera_height_m
    bottom_m = -script.camera_height_m
    v_top = script.cy - script.fy * (top_m / world_x)
    v_bottom = script.cy - script.fy * (bottom_m / world_x)
    return (u_centre - half_w, v_top, u_centre + half_w, v_bottom), range_m, bearing


def render_frame(script: ClipScript, index: int) -> Any:
    """Render one RGB frame as a ``(H, W, 3)`` uint8 array."""

    import numpy as np

    entry = script.frames[index]
    canvas = np.zeros((script.height, script.width, 3), dtype=np.uint8)
    # Background: a wall gradient over a darker floor. Not decoration — a
    # constant background would let the encoder key on "how much grey is in the
    # crop", which is not re-identification.
    rows = np.arange(script.height, dtype=np.float32)[:, None]
    canvas[..., 0] = np.clip(150.0 - 0.22 * rows, 0, 255).astype(np.uint8)
    canvas[..., 1] = np.clip(155.0 - 0.20 * rows, 0, 255).astype(np.uint8)
    canvas[..., 2] = np.clip(160.0 - 0.16 * rows, 0, 255).astype(np.uint8)
    horizon = int(script.cy + script.fy * (script.camera_height_m / 6.0))
    canvas[horizon:, :, :] = (np.asarray([96, 92, 86], dtype=np.uint8))
    # Wall stripes, so a crop's background is not identical everywhere. A
    # constant background would let the encoder key on "how much grey", which
    # would make the separation number a measurement of the wall.
    stripe = max(4, script.width // 26)
    for left in (script.width // 8, (script.width * 3) // 4):
        canvas[:, left : left + stripe, :] = np.asarray([118, 124, 132], dtype=np.uint8)
    # Painter's algorithm: farthest first, so the nearer body occludes the
    # farther one at the crossing. Without this the draw order is the list
    # order, and the person "in front" would flip depending on the JSON.
    drawable: list[tuple[float, Appearance, tuple[float, float, float, float]]] = []
    for person in script.people:
        pose = entry["poses"][person.person_id]
        if not bool(pose.get("visible", True)):
            continue
        box, range_m, _bearing = project(script, float(pose["x"]), float(pose["y"]))
        drawable.append((range_m, person, box))
    for _range_m, person, box in sorted(drawable, key=lambda item: -item[0]):
        _paint_person(canvas, box, person)
    return canvas


def _paint_person(canvas: Any, box: Sequence[float], person: Appearance) -> None:
    import numpy as np

    height, width = canvas.shape[0], canvas.shape[1]
    x0 = max(0, min(width, round(box[0])))
    x1 = max(0, min(width, round(box[2])))
    y0 = max(0, min(height, round(box[1])))
    y1 = max(0, min(height, round(box[3])))
    if x1 - x0 < 2 or y1 - y0 < 6:
        return
    box_h = y1 - y0
    head_end = y0 + max(1, box_h // 6)
    torso_end = y0 + max(2, (box_h * 3) // 5)
    canvas[y0:head_end, x0:x1] = np.asarray(person.skin, dtype=np.uint8)
    canvas[head_end:torso_end, x0:x1] = np.asarray(person.shirt, dtype=np.uint8)
    canvas[torso_end:y1, x0:x1] = np.asarray(person.trouser, dtype=np.uint8)
    if person.pattern == "vstripe":
        for column in range(x0, x1, 4):
            canvas[head_end:torso_end, column : column + 2] = np.asarray(
                [min(255, c + 70) for c in person.shirt], dtype=np.uint8
            )
    elif person.pattern == "hband":
        for row in range(head_end, torso_end, 5):
            canvas[row : row + 2, x0:x1] = np.asarray(
                [max(0, c - 70) for c in person.shirt], dtype=np.uint8
            )


def detection_frame(
    script: ClipScript,
    index: int,
    *,
    detector_score: float = 0.83,
    base_monotonic_ns: int = 1_000_000_000,
    detection_ttl_ns: int = 300_000_000,
) -> CameraDetectionFrame:
    """The C-1 frame the ingress stream would have published for this render.

    Only the fields the tracker reads carry scenario meaning; the timing fields
    are consistent (capture ≤ complete ≤ publish) so the frame passes
    ``CameraDetectionFrame``'s own validation rather than being a mock.
    """

    entry = script.frames[index]
    period_ns = int(1e9 / script.fps)
    capture = base_monotonic_ns + index * period_ns
    records: list[CameraDetectionRecord] = []
    for person in script.people:
        pose = entry["poses"][person.person_id]
        if not bool(pose.get("visible", True)):
            continue
        world_x = float(pose["x"])
        world_y = float(pose["y"])
        box, range_m, bearing = project(script, world_x, world_y)
        records.append(
            CameraDetectionRecord(
                label="person",
                score=detector_score,
                box=box,
                world_x=world_x,
                world_y=world_y,
                world_z=0.9,
                range_m=range_m,
                bearing_rad=bearing,
                depth_m=world_x,
                sigma_range_m=0.05,
                inlier_pixels=400,
            )
        )
    return CameraDetectionFrame(
        frame_id=f"p1c-clip-{index:03d}",
        sequence=index,
        source_timestamp_ns=capture,
        capture_started_monotonic_ns=capture,
        capture_completed_monotonic_ns=capture + 8_000_000,
        published_monotonic_ns=capture + 12_000_000,
        published_wall_s=1_800_000_000.0 + index / script.fps,
        detection_ttl_ns=detection_ttl_ns,
        width_px=script.width,
        height_px=script.height,
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        queries=("person",),
        detections=tuple(records),
        raw_detections=len(records),
        localized_detections=len(records),
        rejected_detections=0,
        truncated_detections=0,
        render_ms=1.0,
        detect_ms=7.0,
        total_ms=12.0,
        detector_name="p1c_synthetic",
        provider_profile="synthetic",
        active_providers=("synthetic",),
    )


def iter_clip(script: ClipScript) -> Iterator[tuple[int, Any, CameraDetectionFrame]]:
    """``(index, rgb, frame)`` for every frame in the script."""

    for index in range(script.frame_count):
        yield index, render_frame(script, index), detection_frame(script, index)


#: Bands and bins for :func:`histogram_embed_image`. Three vertical bands
#: (head / torso / legs), eight bins per channel: 72 dimensions.
_HIST_BANDS = 3
_HIST_BINS = 8


def histogram_embed_image(image: Any) -> tuple[float, ...]:
    """A banded colour histogram with the ``embed_fn`` call shape. **Fixture only.**

    Why this exists, stated plainly so nobody mistakes it for a model:
    ``route_memory.place_graph.stub_embed_image`` hashes the crop's *bytes*, so
    two crops of the same person one frame apart are orthogonal — which makes it
    useless for exercising a re-ID tracker, because appearance association would
    have nothing to associate on. This stand-in is the cheapest function that is
    genuinely appearance-discriminative and pose-tolerant: three vertical bands
    (head, torso, legs), an 8-bin histogram per RGB channel, L2-normalized.

    It runs on any host in about a millisecond, so the structural rows of card
    P1-C — no owner claim without a gallery, no swap on crossing, id survives an
    occlusion, confidence is a measured number — are provable in CI with no GPU
    and no weights. It is **not** a re-ID model and it proves nothing about
    recall on real people: the real-encoder rows are measured separately, on
    ``instructnav.siglip2_onnx`` at ``cuda_fp16``, and are gated on the weights
    being present.
    """

    import numpy as np

    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[2] < 3:
        raise ValueError("histogram_embed_image needs an (H, W, >=3) array")
    arr = arr[:, :, :3].astype(np.float32)
    height = arr.shape[0]
    features: list[float] = []
    edges = np.linspace(0.0, 256.0, _HIST_BINS + 1, dtype=np.float32)
    for band in range(_HIST_BANDS):
        y0 = (height * band) // _HIST_BANDS
        y1 = max(y0 + 1, (height * (band + 1)) // _HIST_BANDS)
        chunk = arr[y0:y1]
        for channel in range(3):
            counts, _ = np.histogram(chunk[:, :, channel], bins=edges)
            total = float(counts.sum()) or 1.0
            features.extend(float(c) / total for c in counts)
    norm = math.sqrt(sum(v * v for v in features))
    if norm <= 0.0:
        return tuple(features)
    return tuple(v / norm for v in features)


def crop_for(script: ClipScript, index: int, person_id: str) -> Any | None:
    """The rendered crop of one person on one frame, or ``None`` when occluded."""

    entry = script.frames[index]
    pose = entry["poses"].get(person_id)
    if pose is None or not bool(pose.get("visible", True)):
        return None
    box, _range_m, _bearing = project(script, float(pose["x"]), float(pose["y"]))
    rgb = render_frame(script, index)
    x0 = max(0, math.floor(box[0]))
    x1 = min(script.width, math.ceil(box[2]))
    y0 = max(0, math.floor(box[1]))
    y1 = min(script.height, math.ceil(box[3]))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return rgb[y0:y1, x0:x1]


__all__ = [
    "CLIP_SCHEMA",
    "PERSON_HEIGHT_M",
    "PERSON_WIDTH_M",
    "Appearance",
    "ClipScript",
    "build_default_script",
    "crop_for",
    "detection_frame",
    "histogram_embed_image",
    "iter_clip",
    "project",
    "render_frame",
]
