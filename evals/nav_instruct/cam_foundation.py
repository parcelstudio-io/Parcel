"""T-cam-foundation: the visual-search FOUNDATION eval tier (B2 gate).

What this measures
------------------
The generalized-visual-search arc replaces the mission's oracle camera with a
detector-on-pixels path. Before any real detector lands (B3, awaiting the
owner's pick), this tier proves the GEOMETRY + localization + DetectionMsg
pipeline that sits *under* the detector, using MuJoCo-style segmentation-truth
as a perfect detector (:class:`SegTruthDetector`) — the sim-legitimate ruler.

Two DERIVED metrics over a frozen render pack:

1. **localization error** — ``|detected world point − true world centroid|`` for
   every localized detection. For SegTruthDetector this is near zero *by
   construction*: the residual is pure pixel quantization, not geometry error,
   because the seg buffer IS the ruler. That is the point — it proves the
   box→world-point→DetectionMsg pipeline is geometrically exact, so a real
   open-vocab detector (B3) later only adds RECOGNITION error on top.
2. **right-object rate** — fraction of localized detections whose ground-truth
   identity matches the queried noun. Perfect (1.0) for seg-truth; a real
   detector or a mutant (phantom box / wrong class) drives it below 1.0.

Additive / opt-in
-----------------
This is a NEW, standalone artifact. It does NOT touch ``runner.py``, the
perception-chain ``from_tier`` seam, the frozen episode sets, or any frozen
result JSON, so the T0/T1 GT-source baselines stay byte-identical (the tier is
purely additive — see ``tests/test_cam_foundation.py``). The render pack is a
deterministic *pinhole-projected synthetic* seg/depth pack (no GL), so CI runs
it without EGL; the guarded real-MuJoCo self-check in
``tests/test_k5_camera_detection_gates.py`` validates the actual renderer's
intrinsics.

HONESTY (P0)
------------
Proves geometry + localization + the DetectionMsg pipeline + FP-handling
machinery against seg-truth. Does NOT prove real-texture recognition (B3 +
hardware). No detector recognition accuracy is claimed.

Usage::

    .parcel/bin/python -m evals.nav_instruct.cam_foundation --check
    .parcel/bin/python -m evals.nav_instruct.cam_foundation --regenerate
    .parcel/bin/python -m evals.nav_instruct.cam_foundation --report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from parcel_robot.camera_channel.d455 import (
    D455_DEPTH_MAX_M,
    D455_DEPTH_MIN_M,
    CameraIntrinsics,
    d455_color_intrinsics,
    go2_d455_mount,
)
from parcel_robot.detection_adapter.pixel_detections import (
    DOES_NOT_PROVE as PIXEL_DOES_NOT_PROVE,
)
from parcel_robot.detection_adapter.pixel_detections import (
    CameraExtrinsics,
    SegTruthDetector,
    localize_frame,
    project,
)

#: NOT renamed to ``T-cam-proxy-foundation`` with its sibling cells, and the
#: exception is deliberate. This string is BAKED INTO the frozen pack
#: ``cam_foundation_pack.json`` (``"tier_id": "T-cam-foundation"``), which
#: ``tests/test_cam_foundation.py`` byte-pins by sha256. Renaming it would move a
#: frozen digest to make a label prettier — a rule-2 STOP, not a cleanup. Like
#: every other ``T-cam*`` label in this directory it is a REPORT id, not a
#: registered perception tier: see
#: :data:`~parcel_robot.detection_adapter.perception_chain.REGISTERED_TIERS`.
#: Retiring it belongs to whoever next re-freezes this pack.
TIER_ID = "T-cam-foundation"
PACK_VERSION = 1

ARTIFACT_PATH = Path(__file__).resolve().parent / "cam_foundation_pack.json"

#: Rounding for the frozen pack (1e-6 m — four orders below the arrival band).
ROUND_DP = 6

#: The seed the frozen pack is generated from. Freezing the seed + the generator
#: freezes the pack; ``--check`` reddens if the artifact was not regenerated.
PACK_SEED = 20260809
PACK_SCENES = 24

#: Object vocabulary the synthetic scenes draw from (street-scene nouns).
_VOCAB: tuple[str, ...] = (
    "bench",
    "lamppost",
    "hydrant",
    "trash_can",
    "sign",
    "planter",
    "bicycle",
    "traffic_cone",
)

#: Localization-error bound the SegTruthDetector must clear. The residual is
#: pixel-quantization only (a flat facing patch at the centroid depth, so
#: back-projecting the integer centroid pixel lands within ~0.5 px · D / fx of
#: truth ≈ sub-cm at these ranges). Pinned well above that and far below any
#: geometry bug: the un-fixed fovy would be decimeters off.
LOCALIZATION_ERROR_BOUND_M = 0.02


# ---------------------------------------------------------------------------
# frozen render pack
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Target:
    seg_id: int
    label: str
    position: tuple[float, float, float]
    radius_m: float
    is_query: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "seg_id": self.seg_id,
            "label": self.label,
            "position": [_r(self.position[0]), _r(self.position[1]), _r(self.position[2])],
            "radius_m": _r(self.radius_m),
            "is_query": self.is_query,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Target:
        pos = data["position"]
        return cls(
            seg_id=int(data["seg_id"]),
            label=str(data["label"]),
            position=(float(pos[0]), float(pos[1]), float(pos[2])),
            radius_m=float(data["radius_m"]),
            is_query=bool(data["is_query"]),
        )


@dataclass(frozen=True, slots=True)
class Scene:
    scene_id: str
    robot_x: float
    robot_y: float
    robot_yaw_rad: float
    query: str
    targets: tuple[Target, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "robot": {
                "x": _r(self.robot_x),
                "y": _r(self.robot_y),
                "yaw_rad": _r(self.robot_yaw_rad),
            },
            "query": self.query,
            "targets": [t.as_dict() for t in self.targets],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Scene:
        robot = data["robot"]
        return cls(
            scene_id=str(data["scene_id"]),
            robot_x=float(robot["x"]),
            robot_y=float(robot["y"]),
            robot_yaw_rad=float(robot["yaw_rad"]),
            query=str(data["query"]),
            targets=tuple(Target.from_dict(t) for t in data["targets"]),
        )

    def extrinsics(self) -> CameraExtrinsics:
        return CameraExtrinsics.from_mount_pose(
            robot_x=self.robot_x,
            robot_y=self.robot_y,
            robot_yaw_rad=self.robot_yaw_rad,
            mount=go2_d455_mount(),
        )

    def id_to_label(self) -> dict[int, str]:
        return {t.seg_id: t.label for t in self.targets}


def _r(value: float) -> float:
    return round(float(value), ROUND_DP)


def generate_scenes(*, seed: int = PACK_SEED, n_scenes: int = PACK_SCENES) -> list[Scene]:
    """Deterministic synthetic scenes. Seed + generator == the frozen pack."""

    rng = random.Random(seed)
    intr = d455_color_intrinsics()
    hfov = intr.horizontal_fov_rad()
    scenes: list[Scene] = []
    for i in range(n_scenes):
        robot_x = round(rng.uniform(-6.0, 6.0), 3)
        robot_y = round(rng.uniform(-3.0, 3.0), 3)
        robot_yaw = round(rng.uniform(-math.pi, math.pi), 4)
        ext = CameraExtrinsics.from_mount_pose(
            robot_x=robot_x, robot_y=robot_y, robot_yaw_rad=robot_yaw, mount=go2_d455_mount()
        )
        n_targets = rng.randint(2, 4)
        labels = rng.sample(_VOCAB, len(_VOCAB))
        targets: list[Target] = []
        boxes: list[tuple[float, float, float, float]] = []
        # Try candidate bearing slots; accept a target only if its projected box
        # lands cleanly inside the image AND does not overlap an accepted box
        # (with a gap). Non-overlapping masks make the FOUNDATION localization
        # error pure pixel-quantization — occlusion/depth-bleed is D2's tier.
        candidate_slots = list(range(-4, 5))
        rng.shuffle(candidate_slots)
        li = 0
        for slot in candidate_slots:
            if len(targets) >= n_targets:
                break
            label = labels[li % len(labels)]
            li += 1
            rng_range = rng.uniform(1.8, 4.8)
            bearing = slot * (0.22 * hfov / 4.0)
            height = rng.uniform(0.35, 1.5)
            world_bearing = robot_yaw + bearing
            px = robot_x + rng_range * math.cos(world_bearing)
            py = robot_y + rng_range * math.sin(world_bearing)
            radius = round(rng.uniform(0.12, 0.40), 3)
            pos = (round(px, 4), round(py, 4), round(height, 4))
            pr = project(pos, intr, ext)
            if pr is None:
                continue
            u, v, d = pr
            r_px = intr.fx * radius / max(d, 1e-3)
            u0, v0, u1, v1 = u - r_px, v - r_px, u + r_px, v + r_px
            if not (8 < u0 and u1 < intr.width_px - 8 and 8 < v0 and v1 < intr.height_px - 8):
                continue
            gap = 6.0
            if any(
                u0 < bx1 + gap and bx0 - gap < u1 and v0 < by1 + gap and by0 - gap < v1
                for (bx0, by0, bx1, by1) in boxes
            ):
                continue
            targets.append(
                Target(
                    seg_id=2 + len(targets),
                    label=label,
                    position=pos,
                    radius_m=radius,
                    is_query=False,
                )
            )
            boxes.append((u0, v0, u1, v1))
        if len(targets) < 2:
            continue
        # Query one present label; mark its instances.
        query_target = rng.choice(targets)
        query = query_target.label
        targets = [
            Target(t.seg_id, t.label, t.position, t.radius_m, is_query=(t.label == query))
            for t in targets
        ]
        scenes.append(
            Scene(
                scene_id=f"cam-foundation-{i:03d}",
                robot_x=robot_x,
                robot_y=robot_y,
                robot_yaw_rad=robot_yaw,
                query=query,
                targets=tuple(targets),
            )
        )
    return scenes


def build_pack(*, seed: int = PACK_SEED, n_scenes: int = PACK_SCENES) -> dict[str, Any]:
    scenes = generate_scenes(seed=seed, n_scenes=n_scenes)
    payload = {
        "pack_version": PACK_VERSION,
        "tier_id": TIER_ID,
        "generated_by": "evals/nav_instruct/cam_foundation.py",
        "do_not_hand_edit": (
            "regenerate with: .parcel/bin/python -m evals.nav_instruct.cam_foundation "
            "--regenerate"
        ),
        "seed": seed,
        "n_scenes_requested": n_scenes,
        "intrinsics": d455_color_intrinsics().as_dict(),
        "scenes": [s.as_dict() for s in scenes],
    }
    payload["digest"] = pack_digest(payload)
    return payload


def pack_digest(payload: Mapping[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "digest"}
    blob = json.dumps(body, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def write_pack(path: str | Path = ARTIFACT_PATH) -> Path:
    target = Path(path)
    target.write_text(json.dumps(build_pack(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return target


def load_pack(path: str | Path = ARTIFACT_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_scenes(path: str | Path = ARTIFACT_PATH) -> list[Scene]:
    return [Scene.from_dict(s) for s in load_pack(path)["scenes"]]


# ---------------------------------------------------------------------------
# synthetic pinhole render (no GL) — seg + depth for a scene
# ---------------------------------------------------------------------------


def render_scene(
    scene: Scene,
    intrinsics: CameraIntrinsics,
    *,
    inject_depth_outliers: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Project a scene's targets to a (seg, depth) buffer via the pinhole model.

    Each target is a flat quad facing the camera at its centroid's optical-axis
    depth, so back-projecting the mask centroid recovers the true centroid up to
    pixel quantization. Nearer targets win the depth test. Optionally seeds a few
    gross depth outliers inside each mask so the localizer's Z-score reject stage
    is genuinely exercised (a broken reject stage moves the world point).
    """

    h, w = intrinsics.height_px, intrinsics.width_px
    seg = np.zeros((h, w), dtype=np.int32)
    depth = np.zeros((h, w), dtype=np.float32)
    zbuf = np.full((h, w), np.inf, dtype=np.float64)
    ext = scene.extrinsics()
    seed_bytes = hashlib.sha256(scene.scene_id.encode("utf-8")).digest()[:4]
    rng = np.random.default_rng(int.from_bytes(seed_bytes, "big"))
    for target in scene.targets:
        pr = project(target.position, intrinsics, ext)
        if pr is None:
            continue
        u, v, d = pr
        r_px = round(intrinsics.fx * target.radius_m / max(d, 1e-3))
        r_px = max(4, r_px)
        uc_i, vc_i = round(u), round(v)
        u0, u1 = uc_i - r_px, uc_i + r_px
        v0, v1 = vc_i - r_px, vc_i + r_px
        u0, u1 = max(0, u0), min(w, u1)
        v0, v1 = max(0, v0), min(h, v1)
        if u1 <= u0 or v1 <= v0:
            continue
        patch = zbuf[v0:v1, u0:u1]
        nearer = d < patch
        ys, xs = np.where(nearer)
        seg[v0:v1, u0:u1][nearer] = target.seg_id
        depth[v0:v1, u0:u1][nearer] = np.float32(d)
        zbuf[v0:v1, u0:u1][nearer] = d
        if inject_depth_outliers and ys.size > 12:
            # A handful of gross outliers the Z-score(tau=2) stage must reject.
            k = max(1, ys.size // 40)
            pick = rng.choice(ys.size, size=k, replace=False)
            for p in pick:
                depth[v0 + ys[p], u0 + xs[p]] = np.float32(d + 3.0)
    return seg, depth


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SceneResult:
    scene_id: str
    query: str
    n_query_instances: int
    n_detections: int
    localization_errors_m: tuple[float, ...]
    right_object: tuple[bool, ...]
    recall: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "query": self.query,
            "n_query_instances": self.n_query_instances,
            "n_detections": self.n_detections,
            "localization_errors_m": [round(e, 6) for e in self.localization_errors_m],
            "right_object": list(self.right_object),
            "recall": round(self.recall, 6),
        }


def evaluate_scene(scene: Scene, intrinsics: CameraIntrinsics) -> SceneResult:
    seg, depth = render_scene(scene, intrinsics)
    detector = SegTruthDetector(scene.id_to_label())
    ext = scene.extrinsics()
    localized = localize_frame(
        detector,
        rgb=None,
        depth=depth,
        seg=seg,
        query=scene.query,
        intrinsics=intrinsics,
        extrinsics=ext,
        source_timestamp_ns=1,
        received_monotonic_ns=1,
        depth_min_m=D455_DEPTH_MIN_M * 0.0,  # synthetic depth is exact; keep >0 only
        depth_max_m=D455_DEPTH_MAX_M + 10.0,
    )
    truth = {t.seg_id: t for t in scene.targets}
    query_ids = {t.seg_id for t in scene.targets if t.is_query}
    errors: list[float] = []
    right: list[bool] = []
    found_ids: set[int] = set()
    for loc in localized:
        tgt = truth.get(loc.seg_id)
        if tgt is None:
            right.append(False)
            continue
        err = math.dist((loc.world_x, loc.world_y, loc.world_z), tgt.position)
        errors.append(err)
        is_right = tgt.label == scene.query
        right.append(is_right)
        if is_right:
            found_ids.add(loc.seg_id)
    recall = len(found_ids & query_ids) / max(1, len(query_ids))
    return SceneResult(
        scene_id=scene.scene_id,
        query=scene.query,
        n_query_instances=len(query_ids),
        n_detections=len(localized),
        localization_errors_m=tuple(errors),
        right_object=tuple(right),
        recall=recall,
    )


def evaluate_pack(path: str | Path = ARTIFACT_PATH) -> dict[str, Any]:
    """Run the foundation tier over the frozen pack; return a DERIVED report."""

    pack = load_pack(path)
    intr = CameraIntrinsics(
        width_px=int(pack["intrinsics"]["width_px"]),
        height_px=int(pack["intrinsics"]["height_px"]),
        fx=float(pack["intrinsics"]["fx"]),
        fy=float(pack["intrinsics"]["fy"]),
        cx=float(pack["intrinsics"]["cx"]),
        cy=float(pack["intrinsics"]["cy"]),
        calibration_id=str(pack["intrinsics"]["calibration_id"]),
    )
    scenes = [Scene.from_dict(s) for s in pack["scenes"]]
    results = [evaluate_scene(s, intr) for s in scenes]

    all_errors: list[float] = []
    all_right: list[bool] = []
    recalls: list[float] = []
    for res in results:
        all_errors.extend(res.localization_errors_m)
        all_right.extend(res.right_object)
        recalls.append(res.recall)

    errors_arr = np.asarray(all_errors, dtype=np.float64) if all_errors else np.zeros(0)
    dist = {
        "n": int(errors_arr.size),
        "mean_m": float(errors_arr.mean()) if errors_arr.size else 0.0,
        "p50_m": float(np.percentile(errors_arr, 50)) if errors_arr.size else 0.0,
        "p95_m": float(np.percentile(errors_arr, 95)) if errors_arr.size else 0.0,
        "max_m": float(errors_arr.max()) if errors_arr.size else 0.0,
    }
    right_rate = (sum(1 for r in all_right if r) / len(all_right)) if all_right else 1.0
    return {
        "kind": "cam_foundation_derived",
        "tier_id": TIER_ID,
        "pack_version": PACK_VERSION,
        "pack_digest": str(pack.get("digest")),
        "n_scenes": len(scenes),
        "n_detections": len(all_right),
        "localization_error_m": dist,
        "localization_error_bound_m": LOCALIZATION_ERROR_BOUND_M,
        "right_object_rate": right_rate,
        "recall_mean": (sum(recalls) / len(recalls)) if recalls else 1.0,
        # A derived diagnostic — never a frozen baseline, never re-freezes T0/T1.
        "frozen_baseline": False,
        "detector": "seg_truth",
        "does_not_prove": list(PIXEL_DOES_NOT_PROVE),
        "scenes": [r.as_dict() for r in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regenerate", action="store_true", help="rewrite the frozen pack")
    parser.add_argument("--check", action="store_true", help="exit non-zero if the pack drifted")
    parser.add_argument("--report", action="store_true", help="run the tier and print the report")
    args = parser.parse_args(argv)

    if args.regenerate:
        write_pack()
        print(json.dumps({"regenerated": str(ARTIFACT_PATH)}, indent=2))
        return 0

    if args.check:
        fresh = build_pack()
        stored = load_pack() if ARTIFACT_PATH.exists() else None
        drifted = stored is None or stored.get("digest") != fresh["digest"]
        print(json.dumps({"artifact": str(ARTIFACT_PATH), "drifted": drifted}, indent=2))
        return 1 if drifted else 0

    report = evaluate_pack()
    summary = {k: v for k, v in report.items() if k != "scenes"}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
