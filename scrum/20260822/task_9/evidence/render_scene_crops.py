"""P1-D fixture F-CROP: TEXTURED city_block crops, ground truth from the scene.

The 2026-08-21 bench crops were rendered from the UNTEXTURED scene (verified by
eye: flat-shaded primitives with no material detail). W-1 has since textured
`city_block.xml`, and the card requires the operating points derived on
TEXTURED dev-scene renders — C-3's F2 tail. So the fixture is rebuilt here.

Ground truth is the SCENE ITSELF: a segmentation pass gives the geom id of every
pixel, geom names group into objects by the scene's own naming convention, and
the class is what the world file calls the thing. No detector is involved, so a
detector's opinion cannot leak into the labels the VLM is scored against.

Poses: the 42 the 2026-08-21 detector bench used, reused verbatim so the two
fixtures are comparable, plus nothing invented.
"""
from __future__ import annotations

import collections
import hashlib
import json
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")

REPO = Path("/home/jaewoo-jang/Desktop/Projects/Parcel")
BENCH = Path(
    "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/"
    "799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/perception/bench-owl"
)
OUT = Path("/home/jaewoo-jang/.cache/parcel-p1d/evidence/scene_crops")
sys.path.insert(0, str(REPO / "src"))

import mujoco
import numpy as np

SCENE = REPO / "src/parcel_robot/scenes/city_block.xml"
MOUNT_HEIGHT_M = 0.35
MOUNT_FORWARD_M = 0.18
PITCH_UP_DEG = 12.0
W, H = 1280, 720
FX = 644.0
MIN_PX = 3000

#: geom-name prefix -> (object key, class label). The scene's own vocabulary.
#: Structural parts of one object share an object key so a bench is one crop and
#: not four crops of its legs.
GROUPS: list[tuple[str, str, str]] = [
    ("bench_", "bench_1", "bench"),
    ("tree_top_1", "tree_1", "tree"),
    ("tree_1", "tree_1", "tree"),
    ("tree_top_2", "tree_2", "tree"),
    ("tree_2", "tree_2", "tree"),
    ("planter_1", "planter_1", "planter"),
    ("planter_2", "planter_2", "planter"),
    ("lamp_post_1", "lamppost_1", "lamppost"),
    ("lamp_head_1", "lamppost_1", "lamppost"),
    ("lamp_post_2", "lamppost_2", "lamppost"),
    ("lamp_head_2", "lamppost_2", "lamppost"),
    ("door_1", "door_1", "door"),
    ("signal_", "traffic_light_1", "traffic light"),
    ("obstacle_bollard", "bollard_1", "bollard"),
    ("obstacle_crate", "crate_1", "crate"),
    ("bldg_1", "building_1", "building"),
    ("bldg_2", "building_2", "building"),
    ("bldg_3", "building_3", "building"),
    ("bldg_4", "building_4", "building"),
    ("bldg_5", "building_5", "building"),
    ("bldg_6", "building_6", "building"),
    ("pedestrian", "person", "person"),
    ("cyclist", "bicycle", "bicycle"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((BENCH / "frames/manifest.json").read_text())
    model = mujoco.MjModel.from_xml_path(str(SCENE))
    model.vis.global_.offwidth = max(int(model.vis.global_.offwidth), W)
    model.vis.global_.offheight = max(int(model.vis.global_.offheight), H)
    model.vis.global_.fovy = math.degrees(2.0 * math.atan(H / (2.0 * FX)))
    # HIDE THE ROBOT'S OWN BODY. The camera sits at the Go2's mount point, so
    # every frame otherwise contains the dog's white legs in the near field —
    # which is true of what a real D455 sees, but a "tree" crop whose largest
    # object is a robot calf is a fixture bug, not a hard example. The 2026-08-21
    # bench excluded them the same way. Nothing else is touched.
    robot_bodies = {
        b
        for b in range(model.nbody)
        if (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b) or "").startswith(
            ("base_link", "FL_", "FR_", "RL_", "RR_")
        )
    }
    hidden = 0
    for gid in range(model.ngeom):
        if int(model.geom_bodyid[gid]) in robot_bodies:
            model.geom_rgba[gid][3] = 0.0
            hidden += 1
    print(f"hidden robot geoms: {hidden}")

    mj = mujoco.MjData(model)
    mujoco.mj_forward(model, mj)
    rgb_r = mujoco.Renderer(model, height=H, width=W)
    seg_r = mujoco.Renderer(model, height=H, width=W)
    seg_r.enable_segmentation_rendering()
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE

    # geom id -> (object key, class label)
    owner: dict[int, tuple[str, str]] = {}
    for gid in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, gid) or ""
        for prefix, key, label in GROUPS:
            if name.startswith(prefix):
                owner[gid] = (key, label)
                break

    # POSES. The 2026-08-21 bench's 42, plus a deterministic STANDOFF ORBIT.
    #
    # The bench poses were designed for near-field detection and put the camera
    # 1-2 m from its subject; at the Go2's 0.35 m eye height that is a texture
    # swatch, not a view. The orbit adds, for every object in GROUPS, the camera
    # at 3.0 / 4.5 / 6.0 m on four bearings, aimed at the object's own centre.
    # Nothing is sampled randomly and nothing is chosen after seeing a result:
    # every pose in the product below is rendered, and the visibility guards
    # decide which produce crops.
    poses: list[tuple[str, float, float, float]] = [
        (f["stem"], float(f["pose"]["x"]), float(f["pose"]["y"]), float(f["pose"]["yaw"]))
        for f in manifest["frames"]
    ]
    centres: dict[str, list] = {}
    for gid, (key, _label) in owner.items():
        centres.setdefault(key, []).append(
            np.asarray(model.geom_pos[gid], dtype=float)
        )
    centre_xy = {
        key: np.mean(np.vstack(vals), axis=0)[:2] for key, vals in centres.items()
    }
    for key, (ox, oy) in sorted(centre_xy.items()):
        for radius in (3.0, 4.5, 6.0):
            for bearing_deg in (0.0, 90.0, 180.0, 270.0):
                bearing = math.radians(bearing_deg)
                px = float(ox) + radius * math.cos(bearing)
                py = float(oy) + radius * math.sin(bearing)
                yaw = math.atan2(float(oy) - py, float(ox) - px)
                poses.append((f"orbit_{key}_{radius:g}m_{bearing_deg:g}", px, py, yaw))

    meta = []
    for stem, rx, ry, yaw in poses:
        frame = {"stem": stem}
        cam.lookat[:] = [
            rx + MOUNT_FORWARD_M * math.cos(yaw),
            ry + MOUNT_FORWARD_M * math.sin(yaw),
            MOUNT_HEIGHT_M,
        ]
        cam.distance = 1e-6
        cam.azimuth = math.degrees(yaw) + 180.0
        cam.elevation = -PITCH_UP_DEG
        rgb_r.update_scene(mj, cam)
        rgb = np.asarray(rgb_r.render(), dtype=np.uint8)
        seg_r.update_scene(mj, cam)
        seg = np.asarray(seg_r.render())[:, :, 0]

        groups: dict[str, tuple[str, list[int]]] = {}
        for gid in np.unique(seg):
            if gid < 0 or int(gid) not in owner:
                continue
            key, label = owner[int(gid)]
            groups.setdefault(key, (label, []))[1].append(int(gid))

        for key, (label, ids) in groups.items():
            mask = np.isin(seg, ids)
            visible = int(mask.sum())
            if visible < MIN_PX:
                continue
            ys, xs = np.nonzero(mask)
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            if (x1 - x0) < 32 or (y1 - y0) < 32:
                continue
            # DOMINANCE GUARD. The VLM is asked "what is the MAIN object in
            # this image", so a crop where the target is not the main object is
            # a question with a wrong answer key, and scoring the model against
            # it would measure the fixture. Two conditions, both necessary:
            # the target must fill at least 35 % of its own crop, and no other
            # single scene object may occupy more of that crop than it does.
            area = float((x1 - x0) * (y1 - y0))
            if visible / area < 0.35:
                continue
            window = seg[y0:y1, x0:x1]
            rival = 0
            for other_key, (_lab, other_ids) in groups.items():
                if other_key == key:
                    continue
                rival = max(rival, int(np.isin(window, other_ids).sum()))
            if rival >= visible:
                continue
            # DISTANCE BAND. At the Go2's 0.35 m mount height a wall two
            # metres away fills the frame, and a crop of that is a texture
            # swatch, not a view of a building. Requiring the object's box to
            # occupy between 1 % and 35 % of the frame keeps the views a
            # PERSON could name — which is the standard the naming accuracy
            # number is quoted against.
            if not 0.01 <= area / float(W * H) <= 0.35:
                continue
            # CONTEXT PADDING. A best-view crop with no surroundings strips the
            # cue a VLM (and a human) uses most: what the thing is standing on
            # and next to. 25 % on every side, clipped to the frame.
            pad_x = int(0.25 * (x1 - x0))
            pad_y = int(0.25 * (y1 - y0))
            cx0, cy0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
            cx1, cy1 = min(W, x1 + pad_x), min(H, y1 + pad_y)
            crop = rgb[cy0:cy1, cx0:cx1]
            name = f"{frame['stem']}__{key}.npy"
            path = OUT / name
            np.save(path, crop)
            meta.append(
                {
                    "id": name[:-4],
                    "path": str(path),
                    "label": label,
                    "object_key": key,
                    "frame": frame["stem"],
                    "box": [x0, y0, x1, y1],
                    "crop_box": [cx0, cy0, cx1, cy1],
                    "visible_px": visible,
                    "fill": round(visible / float((x1 - x0) * (y1 - y0)), 4),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )

    (OUT / "meta.json").write_text(json.dumps(meta, indent=1))
    digest = hashlib.sha256(
        json.dumps(sorted(m["sha256"] for m in meta)).encode()
    ).hexdigest()
    print(f"crops={len(meta)}")
    print("by label:", dict(collections.Counter(m["label"] for m in meta)))
    print("distinct objects:", len({m["object_key"] for m in meta}))
    print(f"FIXTURE_SHA256={digest}")


if __name__ == "__main__":
    main()
