"""B4 live product-path gate: grounds + ARRIVES via PIXEL detections.

Runs the PROVEN closed-loop navigation rig ``HeadlessCityQualityHarness`` — the
same production ``DirectiveNavigator`` + reactive-safety + arrival-verification loop
the frozen nav_instruct arrivals use — but with its ONE semantic-candidate ingress
(``headless_city.semantic_candidates_from_observation``) redirected to the async
:class:`CameraIngress` (render -> OWLv2 -> localize -> candidate dicts). The scene
has NO city-semantic annotations, so the oracle would be empty regardless: every
candidate the navigator grounds + arrives on is a PIXEL detection.

Mission A ("go to the red ball"): a landmark OWLv2 scores above the UNMODIFIED
grounder ``minimum_confidence`` (0.55) — full search->detect->localize->ground->A*->
arrive->verify via pixels. Mission B ("go to the lamppost"): reports OWLv2's real
score on a non-photoreal lamppost prop (the honest recognition FLOOR) — no faked
arrival.

Run:
  MUJOCO_GL=egl PARCEL_OWLV2_ONNX=1 .parcel/bin/python scratchpad/b4_gate.py
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "egl")  # MUST precede first mujoco import
os.environ.setdefault("PARCEL_OWLV2_ONNX", "1")

import mujoco

import parcel_robot.headless_city as hc
from parcel_robot.camera_channel.channel import CameraChannelSpec
from parcel_robot.camera_channel.ingress import CameraIngress
from parcel_robot.headless_city import (
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
)

MAX_STEPS = 1400

TARGET_GEOMS = {
    "red ball": ('<geom name="ball" type="sphere" size="0.4" rgba="1 0 0 1"/>', 0.5),
    "lamppost": (
        '<geom name="pole" type="cylinder" size="0.16 1.3" pos="0 0 1.3" rgba="0.12 0.12 0.14 1"/>'
        + '<geom name="head" type="box" size="0.28 0.16 0.14" pos="0 0 2.72" rgba="0.98 0.94 0.55 1"/>',
        0.0,
    ),
}


def _scene_file(query: str, tx: float, ty: float) -> Path:
    geom, tz = TARGET_GEOMS[query]
    xml = (
        '<mujoco><option gravity="0 0 0"/><worldbody>'
        '<light pos="0 0 6"/>'
        '<geom name="ground" type="plane" size="40 40 0.1" rgba="0.72 0.72 0.75 1"/>'
        '<body name="robot" pos="0 0 0.2"><freejoint/>'
        '<geom name="robot_geom" type="box" size="0.14 0.10 0.07" rgba="0.2 0.2 0.25 1"/></body>'
        '<body name="owner" mocap="true" pos="-25 -25 0"/>'  # park owner off-corridor
        f'<body name="target" pos="{tx} {ty} {tz}">{geom}</body>'
        "</worldbody></mujoco>"
    )
    path = Path(tempfile.mkstemp(suffix="_b4gate.xml")[1])
    path.write_text(xml, encoding="utf-8")
    return path


def run_mission(name: str, directive: str, query: str, tx: float, ty: float) -> dict:
    threshold = float(os.environ.get("PARCEL_OWLV2_THRESHOLD", "0.1"))
    spec = CameraChannelSpec.d455_go2_nominal()
    scene = _scene_file(query, tx, ty)
    world = HeadlessCityWorld(scene)

    render_data = mujoco.MjData(world.model)
    mujoco.mj_forward(world.model, render_data)
    ingress = CameraIngress.from_model_data(
        world.model, render_data, spec=spec, threshold=threshold,
        robot_body_name="robot", class_ids=("bg", "target"),
    )

    report: dict = {"mission": name, "directive": directive, "query": query,
                    "owlv2_threshold": threshold, "target_xy": [tx, ty],
                    "grounder_minimum_confidence": 0.55}

    ingress.set_query(query)
    ingress.set_pose(0.0, 0.0, 0.0)
    ingress.start()
    deadline = time.perf_counter() + 8.0
    while ingress.stats.polls < 1 and time.perf_counter() < deadline:
        time.sleep(0.05)
    warm = ingress.latest_candidates() or []
    report["detection"] = {
        "found": bool(warm),
        "best_confidence": round(max((c["confidence"] for c in warm), default=0.0), 3),
        "detect_ms": round(ingress.stats.last_detect_ms, 1),
        "localization_error_m": (
            round(min(math.dist(c["position"][:2], (tx, ty)) for c in warm), 3) if warm else None
        ),
        "candidates": [
            {"label": c["label"], "confidence": round(c["confidence"], 3),
             "position": [round(v, 3) for v in c["position"]], "source": c["source"]}
            for c in warm
        ],
    }
    report["clears_grounding_gate"] = report["detection"]["best_confidence"] >= 0.55

    # Redirect the harness's ONE semantic ingress to the pixel detector. It sets
    # the render pose from the live observation and returns the async buffer — an
    # O(1) read; OWLv2 runs on the worker thread, never in this call.
    ingress_calls = {"n": 0, "max_ms": 0.0, "oracle_seen": 0}

    def _pixels_from_pixels(observation, **_kw):
        t = time.perf_counter()
        ingress_calls["oracle_seen"] += len(observation.semantic_objects)
        ingress.set_pose(observation.robot.x, observation.robot.y, observation.robot.yaw)
        cands = ingress.latest_candidates() or []
        ingress_calls["n"] += 1
        ingress_calls["max_ms"] = max(ingress_calls["max_ms"], (time.perf_counter() - t) * 1000.0)
        return cands

    original = hc.semantic_candidates_from_observation
    hc.semantic_candidates_from_observation = _pixels_from_pixels
    t0 = time.perf_counter()
    try:
        harness = HeadlessCityQualityHarness(world=world)
        result = harness.run(directive, max_steps=MAX_STEPS)
    finally:
        hc.semantic_candidates_from_observation = original
        wall_s = time.perf_counter() - t0
        ingress.stop()
        scene.unlink(missing_ok=True)

    final = world.observe().robot
    report.update({
        "grounding": {
            "mission_status": result.status,
            "reason": result.reason,
            "target_id": result.target_id,
        },
        "arrived": bool(result.succeeded),
        "final_distance_m": round(math.dist((final.x, final.y), (tx, ty)), 3),
        "steps": len(result.trace),
        "semantic_scan_steps": result.semantic_scan_steps,
        "wall_time_s": round(wall_s, 2),
        "ingress_polls": ingress.stats.polls,
        "ingress_detect_ms": round(ingress.stats.last_detect_ms, 1),
        "ingress_errors": ingress.stats.errors,
        "oracle_objects_seen_by_navigator": ingress_calls["oracle_seen"],
        "ingress_read_max_ms": round(ingress_calls["max_ms"], 3),
        "reactive_gate_never_blocked_on_detection": (
            ingress.stats.last_detect_ms > 10.0 * ingress_calls["max_ms"]
            if ingress_calls["max_ms"] > 0 else None
        ),
    })
    return report


def main() -> int:
    results = [
        run_mission("A_red_ball", "go to the red ball", "red ball", 3.0, 0.0),
        run_mission("B_lamppost", "go to the lamppost", "lamppost", 3.2, 1.0),
    ]
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
