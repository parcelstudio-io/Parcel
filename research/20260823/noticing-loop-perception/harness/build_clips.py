"""H6 — pack the two corpora into replayable clips for the repo's ``recorded`` backend.

No camera exists on this host (``ls /dev/video*`` -> nothing, 2026-08-23), so the
DESIGN's fallback venue applies: the real-photo set and the render set are
streamed through ``camera_channel.backends.recorded.RecordedCameraBackend``,
which is the repo's own CI venue and stamps every frame ``REPLAY``.

Four clips:
  * ``photos_640.npz``   156 photos, 640x360, letterboxed (aspect preserved,
    grey pad), RGB ONLY — a webcam venue publishes no depth, and P8 needs that
    to be true of the clip too, not just of the prose.
  * ``renders_640.npz``  42 city renders, 640x360 (exact 2x decimation of the
    1280x720 render, so a GT box divides by two with no resampling error),
    RGB+depth.
  * ``renders_1280.npz`` the same 42 frames at full 1280x720 RGB+depth — the
    "before" venue for the ingress freshness baseline.
  * ``photos_native/``   is not a clip: the threshold sweep reads the JPEGs at
    native size directly through ``OwlV2Detector``.

Box transforms are written next to the clips so no measurement has to redo
them: ``clips_gt.json`` holds, per clip, per frame, the GT boxes in THAT clip's
pixel frame.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

from parcel_robot.camera_channel.backends.recorded import write_clip
from parcel_robot.evidence_origin import EvidenceOrigin

LOOP_W, LOOP_H = 640, 360
PAD_VALUE = 128  # OWLv2's own grey pad value (0.5 in normalised units)


def _letterbox(image: np.ndarray, width: int, height: int) -> tuple[np.ndarray, float, int, int]:
    src_h, src_w = image.shape[:2]
    scale = min(width / src_w, height / src_h)
    new_w, new_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.full((height, width, 3), PAD_VALUE, dtype=np.uint8)
    off_x, off_y = (width - new_w) // 2, (height - new_h) // 2
    canvas[off_y : off_y + new_h, off_x : off_x + new_w] = resized
    return canvas, scale, off_x, off_y


def build_photo_clip(corpus: Path, out: Path) -> dict:
    manifest = json.loads((corpus / "photos_gt.json").read_text())
    colors: list[np.ndarray] = []
    frames: list[dict] = []
    for record in manifest["records"]:
        bgr = cv2.imread(str(corpus / "photos" / record["file"]), cv2.IMREAD_COLOR)
        if bgr is None:
            raise RuntimeError(f"unreadable photo {record['file']}")
        rgb = bgr[:, :, ::-1]
        boxed, scale, off_x, off_y = _letterbox(np.ascontiguousarray(rgb), LOOP_W, LOOP_H)
        colors.append(boxed)
        frames.append(
            {
                "file": record["file"],
                "objects": [
                    {
                        "label": obj["label"],
                        "iscrowd": obj["iscrowd"],
                        "box": [
                            obj["box"][0] * scale + off_x, obj["box"][1] * scale + off_y,
                            obj["box"][2] * scale + off_x, obj["box"][3] * scale + off_y,
                        ],
                    }
                    for obj in record["objects"]
                ],
            }
        )
    write_clip(
        out / "photos_640.npz", colors, clip_id="h6-photos-640",
        captured_origin=EvidenceOrigin.UNKNOWN,
        captured_label="COCO val2017 photographs (public corpus, not this host's camera)",
        depths=None, fps=30,
        notes="H6 real-photo venue, letterboxed to 640x360, RGB only (no depth).",
    )
    return {"clip": "photos_640.npz", "frames": len(colors), "records": frames}


def build_render_clips(corpus: Path, out: Path) -> list[dict]:
    gt = json.loads((corpus / "renders_gt.json").read_text())
    with np.load(corpus / "renders.npz") as data:
        color = np.ascontiguousarray(data["color"])
        depth = np.ascontiguousarray(data["depth"])
    write_clip(
        out / "renders_1280.npz", color, clip_id="h6-renders-1280",
        captured_origin=EvidenceOrigin.SIMULATION,
        captured_label="city_block.xml render (post-W-1 textured revision)",
        depths=depth, fps=30, notes="H6 render venue at D455 nominal resolution.",
    )
    small_color = color[:, ::2, ::2, :]
    small_depth = depth[:, ::2, ::2]
    write_clip(
        out / "renders_640.npz", small_color, clip_id="h6-renders-640",
        captured_origin=EvidenceOrigin.SIMULATION,
        captured_label="city_block.xml render (post-W-1 textured revision)",
        depths=small_depth, fps=30,
        notes="H6 render venue decimated 2x to the loop's 640x360.",
    )
    full = [
        {"sequence": rec["sequence"], "focus": rec["focus"],
         "objects": [{"label": g["label"], "box": [float(v) for v in g["box"]],
                      "seg_id": g["seg_id"], "pixels": g["pixels"]} for g in rec["gt"]]}
        for rec in gt["records"]
    ]
    half = [
        {"sequence": rec["sequence"], "focus": rec["focus"],
         "objects": [{"label": g["label"], "box": [v / 2.0 for v in g["box"]],
                      "seg_id": g["seg_id"], "pixels": g["pixels"]} for g in rec["gt"]]}
        for rec in gt["records"]
    ]
    return [
        {"clip": "renders_1280.npz", "frames": int(color.shape[0]), "records": full},
        {"clip": "renders_640.npz", "frames": int(small_color.shape[0]), "records": half},
    ]


def main(corpus_dir: str) -> int:
    corpus = Path(corpus_dir)
    out = corpus / "clips"
    out.mkdir(parents=True, exist_ok=True)
    clips = [build_photo_clip(corpus, out), *build_render_clips(corpus, out)]
    (out / "clips_gt.json").write_text(json.dumps({"clips": clips}, indent=1))
    for clip in clips:
        print(clip["clip"], clip["frames"], "frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
