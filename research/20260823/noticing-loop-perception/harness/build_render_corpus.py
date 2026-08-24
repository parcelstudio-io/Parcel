"""H6 corpus B — the render set, re-rendered from the repo's own city scene.

The 2026-08-21 bench's render frames are gone with their scratchpad, and the
scene has CHANGED since: card W-1 (2026-08-21) textured ``city_block.xml``,
moved the pedestrian capsules to group 4 (not rendered) and put textured human
meshes (``vis_pedestrian_*``) in their place. So this is not a re-run of the
bench's frames — it is the same scene FILE at today's revision, and the
difference is itself a finding.

42 frames, matching the bench's frame count: 7 pedestrians x 3 ranges
(1.6 / 2.6 / 4.2 m) x 2 bearings (-25 deg / +25 deg), camera placed by the
repo's own ``MujocoEglCameraBackend`` free-camera mount maths (D455 nominal
1280x720, dog-height mount, +12 deg pitch). Ground truth is the repo's own
``SegTruthDetector`` over the MuJoCo segmentation buffer, so a GT box is
exactly the VISIBLE pixels of an instance (occlusion is handled by
construction). The Go2 is parked 100 m away so the robot's own body — the one
textured mesh the 08-21 VLM control could name — cannot enter frame.

Writes ``renders.npz`` (color/depth/seg + per-frame poses) and
``renders_gt.json`` next to it.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")

import numpy as np

SCENE = "src/parcel_robot/scenes/city_block.xml"
RANGES_M = (1.6, 2.6, 4.2)
BEARINGS_RAD = (-0.4363, 0.4363)  # -25 deg, +25 deg
PERSON_LABEL = "person"
WORLD_LABELS = (
    "person", "bench", "tree", "building", "lamppost", "planter",
    "door", "traffic light", "crate", "bollard", "bicycle",
)


def _label_for(name: str) -> str | None:
    """Geom name -> world label, using the scene's own prefix table for objects."""

    from parcel_robot.perception.city_semantics import OBJECT_PREFIX_TABLE

    if name.startswith(("vis_pedestrian_", "pedestrian_")):
        return PERSON_LABEL
    if name.startswith(("vis_bicycle", "bicycle")):
        return "bicycle"
    for prefix, label in OBJECT_PREFIX_TABLE:
        if name.startswith(prefix):
            return label
    return None


def main(out_dir: str) -> int:
    import mujoco

    from parcel_robot.camera_channel.backends.mujoco_egl import MujocoEglCameraBackend
    from parcel_robot.camera_channel.channel import CameraChannelSpec
    from parcel_robot.detection_adapter.pixel_detections import SegTruthDetector

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec = CameraChannelSpec.d455_go2_nominal()

    model = mujoco.MjModel.from_xml_path(SCENE)
    data = mujoco.MjData(model)
    # Park the Go2 far away: its trunk free joint is the model's first joint.
    if model.njnt and int(model.jnt_type[0]) == int(mujoco.mjtJoint.mjJNT_FREE):
        adr = int(model.jnt_qposadr[0])
        data.qpos[adr : adr + 3] = (100.0, 100.0, 0.4)
    mujoco.mj_forward(model, data)

    id_to_label: dict[int, str] = {}
    for geom_id in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or ""
        label = _label_for(name)
        if label:
            id_to_label[(geom_id + 1) & 0xFFFF] = label
    truth = SegTruthDetector(id_to_label)

    peds = []
    for body_id in range(model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id) or ""
        if name.startswith("pedestrian_"):
            peds.append((name, np.asarray(data.xpos[body_id], dtype=float).copy()))
    peds.sort()

    backend = MujocoEglCameraBackend(model, data, spec=spec, class_ids=("bg", "obj"))
    colors: list[np.ndarray] = []
    depths: list[np.ndarray] = []
    segs: list[np.ndarray] = []
    frames: list[dict] = []
    seq = 0
    for ped_name, ped_xy in peds:
        for radius in RANGES_M:
            for bearing in BEARINGS_RAD:
                theta = math.atan2(ped_xy[1], ped_xy[0]) + bearing
                rx = float(ped_xy[0] + radius * math.cos(theta))
                ry = float(ped_xy[1] + radius * math.sin(theta))
                yaw = math.atan2(ped_xy[1] - ry, ped_xy[0] - rx)
                backend.capture(
                    source_timestamp_ns=seq + 1, sequence=seq,
                    robot_x=rx, robot_y=ry, robot_yaw_rad=yaw,
                )
                buffers = backend.last_buffers
                assert buffers is not None and buffers.seg_u16 is not None
                seg = np.asarray(buffers.seg_u16, dtype=np.int32)
                colors.append(np.asarray(buffers.color_rgb8, dtype=np.uint8).copy())
                depths.append(np.asarray(buffers.depth_m_f32, dtype=np.float32).copy())
                segs.append(seg.astype(np.uint16).copy())
                gt = truth.detect(rgb=None, depth=None, seg=seg, query=list(WORLD_LABELS))
                frames.append(
                    {
                        "sequence": seq,
                        "focus": ped_name,
                        "robot_x": rx, "robot_y": ry, "robot_yaw_rad": yaw,
                        "range_m": radius, "bearing_rad": bearing,
                        "gt": [
                            {
                                "label": det.label,
                                "box": list(det.box),
                                "seg_id": det.seg_id,
                                "pixels": int((seg == det.seg_id).sum()),
                            }
                            for det in gt
                        ],
                    }
                )
                seq += 1
    backend.close()

    np.savez_compressed(
        out / "renders.npz",
        color=np.stack(colors), depth=np.stack(depths), seg=np.stack(segs),
    )
    persons = [g for f in frames for g in f["gt"] if g["label"] == PERSON_LABEL]
    manifest = {
        "scene": SCENE,
        "scene_note": "post-W-1 textured revision (vis_pedestrian_* human meshes)",
        "width_px": spec.intrinsics.width_px,
        "height_px": spec.intrinsics.height_px,
        "frames": len(frames),
        "person_instances": len(persons),
        "person_pixels_min": min((p["pixels"] for p in persons), default=0),
        "person_pixels_median": int(np.median([p["pixels"] for p in persons])) if persons else 0,
        "gt_instances_total": sum(len(f["gt"]) for f in frames),
        "labels": sorted({g["label"] for f in frames for g in f["gt"]}),
        "records": frames,
    }
    (out / "renders_gt.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps({k: v for k, v in manifest.items() if k != "records"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
