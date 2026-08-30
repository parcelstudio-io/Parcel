#!/usr/bin/env python3
"""Inspect the official stack's bounded applicability to Parcel's lower layer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    import mjlab.tasks  # noqa: F401
    import src.tasks  # noqa: F401
    from mjlab.tasks.registry import load_env_cfg

    flat = load_env_cfg("Unitree-Go2-Flat")
    rough = load_env_cfg("Unitree-Go2-Rough")
    xml_path = source / "src/assets/robots/unitree_go2/xmls/go2.xml"
    xml_root = ET.parse(xml_path).getroot()
    joint_names = [
        node.attrib["name"]
        for node in xml_root.findall(".//joint")
        if node.attrib.get("name")
    ]
    env_cfg = source / "src/tasks/velocity/config/go2/env_cfgs.py"
    runner = source / "src/tasks/velocity/rl/runner.py"
    root_readme = source / "README.md"
    deploy_cmake = source / "deploy/robots/go2/CMakeLists.txt"
    deploy_main = source / "deploy/robots/go2/main.cpp"
    deploy_controller = source / "deploy/robots/go2/src/State_RLBase.cpp"
    inspected = [
        xml_path,
        env_cfg,
        runner,
        root_readme,
        deploy_cmake,
        deploy_main,
        deploy_controller,
    ]
    runner_text = runner.read_text(encoding="utf-8")
    readme_text = root_readme.read_text(encoding="utf-8")
    cmake_text = deploy_cmake.read_text(encoding="utf-8")
    controller_text = deploy_controller.read_text(encoding="utf-8")

    observed = {
        "go2_named_leg_joints": joint_names,
        "go2_named_leg_joint_count": len(joint_names),
        "flat_sensors": [
            {"name": sensor.name, "type": type(sensor).__name__}
            for sensor in (flat.scene.sensors or ())
        ],
        "rough_sensors": [
            {"name": sensor.name, "type": type(sensor).__name__}
            for sensor in (rough.scene.sensors or ())
        ],
        "velocity_command_terms": sorted(flat.commands),
        "flat_terrain_type": flat.scene.terrain.terrain_type if flat.scene.terrain else None,
        "rough_terrain_type": rough.scene.terrain.terrain_type if rough.scene.terrain else None,
        "rough_terrain_generator_present": bool(
            rough.scene.terrain and rough.scene.terrain.terrain_generator
        ),
        "randomization_events": sorted(rough.events),
        "onnx_export_hook_present": (
            "export_policy_to_onnx" in runner_text and "attach_metadata_to_onnx" in runner_text
        ),
        "upstream_train_play_sim2real_workflow_documented": all(
            word in readme_text for word in ("Train", "Play", "Sim2Real")
        ),
        "separate_simulation_deployment_recommended": (
            "Simulation Deployment" in readme_text and "unitree_mujoco" in readme_text
        ),
        "go2_deployment_controller_present": all(
            path.is_file() for path in (deploy_cmake, deploy_main, deploy_controller)
        ),
        "aarch64_onnxruntime_branch_present": "aarch64" in cmake_text,
        "go2_controller_loads_onnx": "policy.onnx" in controller_text,
    }
    lower_layer_hooks_pass = all(
        (
            observed["go2_named_leg_joint_count"] == 12,
            {item["name"] for item in observed["rough_sensors"]}
            >= {"terrain_scan", "feet_ground_contact", "nonfoot_ground_touch"},
            observed["velocity_command_terms"] == ["twist"],
            observed["rough_terrain_generator_present"],
            {"push_robot", "foot_friction", "encoder_bias", "base_com"}
            <= set(observed["randomization_events"]),
            observed["onnx_export_hook_present"],
            observed["go2_deployment_controller_present"],
        )
    )
    record = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "MJLAB-1",
        "hypothesis": "MJF-H4",
        "source": {
            "path": str(source),
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=source, text=True
            ).strip(),
            "tracked_diff_empty": subprocess.run(
                ["git", "diff", "--quiet"], cwd=source, check=False
            ).returncode
            == 0,
            "inspected_sha256": {
                str(path.relative_to(source)): sha256(path) for path in inspected
            },
            "probe_sha256": sha256(Path(__file__).resolve()),
        },
        "observed": observed,
        "lower_layer_hooks_pass": lower_layer_hooks_pass,
        "useful_for_lower_layer_locomotion_research_in_pinned_environment": lower_layer_hooks_pass,
        "not_present_in_tested_task": [
            "Parcel camera or Mid-360 LiDAR observations",
            "audio, speech, or full-duplex conversational input/output",
            "dynamic pedestrian, sidewalk, crosswalk, elevator, stair, or social-comfort scenarios",
            "Model A proposal/lease contract or Model B execution-receipt narration",
            "interruptible task ledger, global planning, semantic object grounding, or memory",
            "Starlink latency/loss and acoustic/network fault injection",
            "Go2 EDU+ AGX Orin payload mass/inertia/thermal/power model",
            "independent safety supervisor or Parcel's sole-writer motion authority",
        ],
        "important_distinctions": [
            "terrain_scan is a simulator ray-cast height grid, not a modeled Mid-360 data path",
            "the retained PPO policy is a three-iteration smoke artifact, not a locomotion policy",
            "the upstream deploy controller was inspected, not compiled or run",
            "direct deployment must not bypass Parcel's commissioned gateway and STOP authority",
        ],
        "h4_assessment": (
            "Useful as a pinned lower-layer locomotion research substrate; insufficient for "
            "Model A/Model B promotion, companion navigation, conversation, or physical safety."
        ),
        "strict_h4_gate_supported": False,
        "strict_h4_reason": (
            "DESIGN.md conditions usefulness on H1-H3. Clean-install H1 failed, so the strict "
            "all-gates chain remains false even though remediated H2/H3 and the hooks pass."
        ),
    }
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    return 0 if lower_layer_hooks_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
