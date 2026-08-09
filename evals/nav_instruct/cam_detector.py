"""T-cam real-detector cell: the OWLv2 open-vocab DETECTOR on rendered pixels (B3 gate).

Where ``cam_foundation.py`` proves the GEOMETRY + localization pipeline against a
synthetic seg/depth pack with a *perfect* :class:`SegTruthDetector`, this cell adds
the **real recognition step**: it renders real MuJoCo RGB (+depth+seg) and runs the
**OWLv2 open-vocabulary detector** (``detection_adapter.owlv2_onnx.OwlV2Detector``,
Apache-2.0) through the SAME ``localize_frame`` seam, ALONGSIDE ``SegTruthDetector``
on the identical frames. SegTruthDetector is the geometry-only ruler (recognition
perfect by construction); OWLv2 adds recognition, so the gap between them is the
honest **recognition error** the P0 stance predicts.

Metrics (per detector, over a deterministic MuJoCo scene set)
-----------------------------------------------------------
* **right-object rate** — fraction of localized detections whose predicted label
  matches the ground-truth label of the instance they actually localize to
  (dominant seg-id in the box). 1.0 for seg-truth by construction; < 1.0 for OWLv2
  when it mis-names or hallucinates a box.
* **recall** — fraction of ground-truth query instances OWLv2 correctly detects.
* **localization error vs the seg-truth ruler** — ``|OWLv2 world point − SegTruth
  world point|`` for the SAME instance. Comparing OWLv2 to SegTruth (not to the
  volumetric geom centre) isolates the RECOGNITION-induced box error from the
  common monocular surface-vs-centre offset both share, so this number is the pure
  recognition delta.
* **ms/query (CPU)** — wall time of one ``detect`` over a frame.

Guarded / additive / opt-in
---------------------------
This is a NEW, standalone file. It touches no frozen pack, no ``runner.py``, no
``from_tier`` seam — so the T0/T1 GT-source baselines stay byte-identical. The gate
runs only when BOTH an offscreen GL context (``MUJOCO_GL=egl``) AND the OWLv2
weights (``scripts/fetch_owlv2.sh`` + ``PARCEL_OWLV2_ONNX=1``) are present; it skips
cleanly (returning a ``skipped`` report with the blocker) otherwise, so CI without
GL/weights is unchanged. Renders are not byte-frozen (GL output is driver-dependent),
which is exactly why this is an on-demand gate and not a frozen digest.

HONESTY (P0)
------------
Rendered MuJoCo textures are NOT photoreal, so OWLv2 recall here tests the
pixels->localize->ground->lock-on pipeline + a FLOOR of recognition, NOT real-world
D455 recognition (a hardware re-earn). No field recall/precision is claimed.

Usage::

    MUJOCO_GL=egl PARCEL_OWLV2_ONNX=1 .parcel/bin/python -m evals.nav_instruct.cam_detector --report
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any

TIER_ID = "T-cam-detector"

# The recognition-error budget the OWLv2 localization delta is reported against.
# OWLv2's box differs from the exact seg mask, so its back-projected centroid drifts
# a few cm off the seg-truth ruler; pinned well below the 1.0 m arrival band.
RECOGNITION_LOCALIZATION_BUDGET_M = 0.30

DOES_NOT_PROVE = (
    (
        "Rendered MuJoCo textures are NOT photoreal: OWLv2 recall here tests the "
        "pixels->localize->ground->lock-on pipeline + a FLOOR of recognition, NOT "
        "real-world D455 recognition (that is a hardware re-earn)."
    ),
    (
        "The right-object / localization DELTA vs SegTruthDetector is the honest sim "
        "RECOGNITION error on top of already-proven geometry, not a field claim."
    ),
)


# ---------------------------------------------------------------------------
# deterministic scene set (colored primitives → open-vocab color+shape queries)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SceneObject:
    name: str
    geom_type: str  # "sphere" | "box" | "cylinder"
    size_m: float
    position: tuple[float, float, float]
    rgba: str
    query: str  # the open-vocab phrase OWLv2 is asked for


@dataclass(frozen=True, slots=True)
class DetScene:
    scene_id: str
    robot_x: float
    robot_y: float
    robot_yaw_rad: float
    objects: tuple[SceneObject, ...]


def build_scenes() -> list[DetScene]:
    """A small, deterministic set of MuJoCo scenes with recognizable colored shapes.

    Colors are kept distinct within a scene so the open-vocab query is unambiguous;
    shapes/colors vary across scenes so the detector is exercised on several nouns.
    """

    def obj(name, typ, size, pos, rgba, query) -> SceneObject:
        return SceneObject(name, typ, size, pos, rgba, query)

    scenes = [
        DetScene(
            "det-000", 0.0, 0.0, 0.0,
            (
                obj("o0", "sphere", 0.30, (3.0, 0.6, 0.5), "1 0 0 1", "red ball"),
                obj("o1", "box", 0.28, (3.4, -0.6, 0.5), "0 1 0 1", "green box"),
            ),
        ),
        DetScene(
            "det-001", 0.0, 0.0, 0.0,
            (
                obj("o0", "cylinder", 0.22, (2.8, -0.2, 0.6), "0 0 1 1", "blue cylinder"),
                obj("o1", "sphere", 0.26, (3.6, 0.8, 0.5), "1 1 0 1", "yellow ball"),
            ),
        ),
        DetScene(
            "det-002", -1.0, 0.5, 0.3,
            (
                obj("o0", "box", 0.30, (2.2, 0.9, 0.5), "1 0 0 1", "red box"),
                obj("o1", "sphere", 0.24, (3.2, 0.1, 0.5), "0 1 0 1", "green ball"),
                obj("o2", "cylinder", 0.20, (2.6, 1.6, 0.6), "1 1 1 1", "white cylinder"),
            ),
        ),
        DetScene(
            "det-003", 1.5, -0.5, -0.4,
            (
                obj("o0", "sphere", 0.30, (4.0, -1.4, 0.5), "1 0 0 1", "red ball"),
                obj("o1", "box", 0.26, (3.4, -2.0, 0.5), "0 0 1 1", "blue box"),
            ),
        ),
        DetScene(
            "det-004", 0.0, 0.0, 0.6,
            (
                obj("o0", "cylinder", 0.24, (2.6, 1.9, 0.6), "1 0.5 0 1", "orange cylinder"),
                obj("o1", "sphere", 0.28, (3.2, 2.4, 0.5), "0 1 0 1", "green ball"),
            ),
        ),
        DetScene(
            "det-005", -2.0, -1.0, 0.2,
            (
                obj("o0", "box", 0.30, (1.4, -0.6, 0.5), "1 1 0 1", "yellow box"),
                obj("o1", "sphere", 0.26, (2.4, -0.2, 0.5), "1 0 0 1", "red ball"),
                obj("o2", "cylinder", 0.22, (1.8, 0.4, 0.6), "0 0 1 1", "blue cylinder"),
            ),
        ),
        DetScene(
            "det-006", 0.5, 0.5, -0.2,
            (
                obj("o0", "sphere", 0.30, (3.6, -0.2, 0.5), "1 1 1 1", "white ball"),
                obj("o1", "box", 0.28, (3.0, 1.1, 0.5), "1 0 0 1", "red box"),
            ),
        ),
        DetScene(
            "det-007", 0.0, 0.0, 0.0,
            (
                obj("o0", "sphere", 0.32, (2.6, 0.0, 0.5), "0 1 0 1", "green ball"),
                obj("o1", "cylinder", 0.22, (3.4, -1.0, 0.6), "1 0.5 0 1", "orange cylinder"),
            ),
        ),
    ]
    return scenes


def _scene_xml(scene: DetScene) -> str:
    parts = [
        '<mujoco><worldbody><light pos="0 0 5"/>',
        '<geom name="ground" type="plane" size="40 40 0.1" rgba="0.75 0.75 0.78 1"/>',
    ]
    for o in scene.objects:
        if o.geom_type == "box":
            size = f"{o.size_m} {o.size_m} {o.size_m}"
        elif o.geom_type == "cylinder":
            size = f"{o.size_m} {o.size_m}"
        else:
            size = f"{o.size_m}"
        px, py, pz = o.position
        parts.append(
            f'<body name="b_{o.name}" pos="{px} {py} {pz}">'
            f'<geom name="{o.name}" type="{o.geom_type}" size="{size}" rgba="{o.rgba}"/></body>'
        )
    parts.append("</worldbody></mujoco>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# render + evaluate (guarded — needs EGL + weights)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RenderedScene:
    scene_id: str
    rgb: Any
    depth: Any
    seg: Any
    id_to_label: dict[int, str]
    extrinsics: Any
    query: list[str]


def render_scene(scene: DetScene, spec: Any) -> RenderedScene | None:
    """Render a scene to RGB+depth+seg via the MuJoCo-EGL backend, or ``None`` if GL is down.

    ``seg_id = geom_id + 1`` (``mujoco_egl`` packing); geom 0 is the ground plane
    (seg 1), so scene objects occupy seg ids ``2 .. 1 + len(objects)`` in declaration
    order. Returns ``None`` when no offscreen GL context is available.
    """

    import mujoco

    from parcel_robot.camera_channel.backends.mujoco_egl import (
        MujocoEglCameraBackend,
        MujocoEglUnavailable,
    )
    from parcel_robot.detection_adapter.pixel_detections import CameraExtrinsics

    model = mujoco.MjModel.from_xml_string(_scene_xml(scene))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    try:
        backend = MujocoEglCameraBackend(model, data, spec=spec, class_ids=("bg", "obj"))
    except MujocoEglUnavailable:
        return None
    try:
        backend.capture(
            source_timestamp_ns=1, sequence=0,
            robot_x=scene.robot_x, robot_y=scene.robot_y, robot_yaw_rad=scene.robot_yaw_rad,
        )
    except Exception:  # noqa: BLE001 — offscreen capture failure => skip, not crash
        backend.close()
        return None
    buf = backend.last_buffers
    backend.close()
    if buf is None or buf.seg_u16 is None:
        return None

    import numpy as np

    # geom id for each object: ground is geom 0, objects follow in declaration order.
    id_to_label: dict[int, str] = {}
    for idx, o in enumerate(scene.objects):
        gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, o.name)
        id_to_label[(gid + 1) & 0xFFFF] = o.query
    ext = CameraExtrinsics.from_mount_pose(
        robot_x=scene.robot_x, robot_y=scene.robot_y, robot_yaw_rad=scene.robot_yaw_rad,
        mount=spec.mount,
    )
    query = sorted({o.query for o in scene.objects})
    return RenderedScene(
        scene_id=scene.scene_id,
        rgb=np.asarray(buf.color_rgb8),
        depth=np.asarray(buf.depth_m_f32, dtype=np.float64),
        seg=np.asarray(buf.seg_u16, dtype=np.int32),
        id_to_label=id_to_label,
        extrinsics=ext,
        query=query,
    )


def _dominant_seg(seg: Any, box: tuple[int, int, int, int], valid_ids: set[int]) -> int | None:
    import numpy as np

    u0, v0, u1, v1 = box
    patch = np.asarray(seg)[v0:v1, u0:u1]
    if patch.size == 0:
        return None
    ids, counts = np.unique(patch, return_counts=True)
    best, best_count = None, 0
    for sid, cnt in zip(ids.tolist(), counts.tolist(), strict=False):
        if sid in valid_ids and cnt > best_count:
            best, best_count = int(sid), int(cnt)
    return best


@dataclass
class DetectorScore:
    detector: str
    n_scenes: int
    n_detections: int
    n_gt_instances: int
    right_object_rate: float
    recall: float
    loc_error_mean_m: float
    loc_error_p95_m: float
    loc_error_max_m: float
    ms_per_query_mean: float


def evaluate(spec: Any | None = None, *, threshold: float | None = None) -> dict[str, Any]:
    """Render the scene set and score SegTruthDetector vs OWLv2 through localize_frame.

    Returns a report dict. When GL or the OWLv2 weights are unavailable, returns a
    ``{"status": "skipped", "blocker": ...}`` report instead of raising.
    """

    from parcel_robot.camera_channel.channel import CameraChannelSpec
    from parcel_robot.detection_adapter.owlv2_onnx import (
        load_owlv2_detector,
        onnx_enabled,
        owlv2_weights_present,
    )

    if not owlv2_weights_present():
        return {"status": "skipped", "tier_id": TIER_ID,
                "blocker": "OWLv2 weights absent — run scripts/fetch_owlv2.sh"}
    if not onnx_enabled():
        return {"status": "skipped", "tier_id": TIER_ID,
                "blocker": "PARCEL_OWLV2_ONNX not set — opt-in gate is off"}
    owl = load_owlv2_detector(threshold=threshold)
    if owl is None:
        return {"status": "skipped", "tier_id": TIER_ID,
                "blocker": "OWLv2 detector failed to load (see log)"}

    spec = spec if spec is not None else CameraChannelSpec.d455_go2_nominal()
    intr = spec.intrinsics
    scenes = build_scenes()

    import numpy as np

    from parcel_robot.detection_adapter.pixel_detections import (
        SegTruthDetector,
        localize_frame,
    )

    per_scene: list[dict[str, Any]] = []
    seg_right: list[bool] = []
    owl_right: list[bool] = []
    owl_errs: list[float] = []
    owl_ms: list[float] = []
    seg_ms: list[float] = []
    total_gt = 0
    owl_recall_hits = 0
    n_rendered = 0

    for scene in scenes:
        rendered = render_scene(scene, spec)
        if rendered is None:
            return {"status": "skipped", "tier_id": TIER_ID,
                    "blocker": "MuJoCo offscreen GL unavailable — set MUJOCO_GL=egl"}
        n_rendered += 1
        valid_ids = set(rendered.id_to_label)
        total_gt += len(valid_ids)

        # --- SegTruth ruler world points (geometry-only, perfect recognition) ---
        t0 = time.perf_counter()
        seg_detector = SegTruthDetector(rendered.id_to_label)
        seg_locs = localize_frame(
            seg_detector, rgb=rendered.rgb, depth=rendered.depth, seg=rendered.seg,
            query=rendered.query, intrinsics=intr, extrinsics=rendered.extrinsics,
            source_timestamp_ns=1, received_monotonic_ns=1, depth_max_m=1000.0,
        )
        seg_ms.append((time.perf_counter() - t0) * 1000.0)
        ruler = {loc.seg_id: (loc.world_x, loc.world_y, loc.world_z) for loc in seg_locs}
        for loc in seg_locs:
            seg_right.append(rendered.id_to_label.get(loc.seg_id) == loc.label)

        # --- OWLv2 detections (recognition + geometry) ---
        t0 = time.perf_counter()
        owl_dets = owl.detect(rgb=rendered.rgb, depth=None, seg=None, query=rendered.query)
        owl_ms.append((time.perf_counter() - t0) * 1000.0)
        owl_locs = localize_frame(
            owl, rgb=rendered.rgb, depth=rendered.depth, seg=rendered.seg,
            query=rendered.query, intrinsics=intr, extrinsics=rendered.extrinsics,
            source_timestamp_ns=1, received_monotonic_ns=1, depth_max_m=1000.0,
        )
        found_ids: set[int] = set()
        scene_rows: list[dict[str, Any]] = []
        for det, loc in zip(owl_dets, owl_locs, strict=False):
            mseg = _dominant_seg(rendered.seg, det.box, valid_ids)
            gt_label = rendered.id_to_label.get(mseg) if mseg is not None else None
            is_right = gt_label is not None and gt_label == det.label
            owl_right.append(is_right)
            err = math.nan
            if mseg is not None and mseg in ruler:
                err = math.dist((loc.world_x, loc.world_y, loc.world_z), ruler[mseg])
                if is_right:
                    owl_errs.append(err)
                    found_ids.add(mseg)
            scene_rows.append({
                "label": det.label, "score": round(det.score, 4),
                "matched_seg": mseg, "gt_label": gt_label,
                "right_object": is_right,
                "loc_error_vs_ruler_m": (None if math.isnan(err) else round(err, 4)),
            })
        owl_recall_hits += len(found_ids)
        per_scene.append({
            "scene_id": scene.scene_id, "query": rendered.query,
            "n_gt_instances": len(valid_ids),
            "n_seg_detections": len(seg_locs), "n_owl_detections": len(owl_dets),
            "owl_detections": scene_rows,
        })

    errs = np.asarray(owl_errs, dtype=np.float64) if owl_errs else np.zeros(0)
    seg_score = DetectorScore(
        detector="seg_truth", n_scenes=n_rendered, n_detections=len(seg_right),
        n_gt_instances=total_gt,
        right_object_rate=(sum(seg_right) / len(seg_right)) if seg_right else 1.0,
        recall=1.0, loc_error_mean_m=0.0, loc_error_p95_m=0.0, loc_error_max_m=0.0,
        ms_per_query_mean=(sum(seg_ms) / len(seg_ms)) if seg_ms else 0.0,
    )
    owl_score = DetectorScore(
        detector="owlv2", n_scenes=n_rendered, n_detections=len(owl_right),
        n_gt_instances=total_gt,
        right_object_rate=(sum(owl_right) / len(owl_right)) if owl_right else 0.0,
        recall=(owl_recall_hits / total_gt) if total_gt else 0.0,
        loc_error_mean_m=float(errs.mean()) if errs.size else 0.0,
        loc_error_p95_m=float(np.percentile(errs, 95)) if errs.size else 0.0,
        loc_error_max_m=float(errs.max()) if errs.size else 0.0,
        ms_per_query_mean=(sum(owl_ms) / len(owl_ms)) if owl_ms else 0.0,
    )
    return {
        "status": "ran",
        "tier_id": TIER_ID,
        "detector_model": "owlv2-base-patch16-ensemble (int8 ONNX, Apache-2.0)",
        "threshold": owl.threshold,
        "n_scenes": n_rendered,
        "n_gt_instances": total_gt,
        "seg_truth": vars(seg_score),
        "owlv2": vars(owl_score),
        "recognition_error_delta": {
            "right_object_rate_drop": round(
                seg_score.right_object_rate - owl_score.right_object_rate, 4
            ),
            "recall_drop": round(seg_score.recall - owl_score.recall, 4),
            "localization_error_added_m_mean": round(owl_score.loc_error_mean_m, 4),
            "localization_error_added_m_max": round(owl_score.loc_error_max_m, 4),
            "budget_m": RECOGNITION_LOCALIZATION_BUDGET_M,
        },
        "off_10hz_path": owl_score.ms_per_query_mean > 100.0,
        "frozen_baseline": False,
        "does_not_prove": list(DOES_NOT_PROVE),
        "scenes": per_scene,
    }


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("MUJOCO_GL", "egl")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="run the gate and print the report")
    parser.add_argument("--threshold", type=float, default=None, help="OWLv2 score gate override")
    parser.add_argument("--full", action="store_true", help="include per-scene detail in the report")
    args = parser.parse_args(argv)

    report = evaluate(threshold=args.threshold)
    if not args.full:
        report = {k: v for k, v in report.items() if k != "scenes"}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"ran", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
