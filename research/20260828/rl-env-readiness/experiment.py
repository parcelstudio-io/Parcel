"""Bounded, deterministic fidelity audit for parcel_robot.rl.env.Go2Env.

This script imports the product environment but writes only the requested JSON
artifact.  It never opens a socket, starts a viewer, trains a policy, or touches
physical control.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np

ARTIFACT_DIR = Path(__file__).resolve().parent
REPO = ARTIFACT_DIR.parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parcel_robot.rl.env import Go2Env
from parcel_robot.rl.spaces import ACTION_DIM, OBS_DIM

SCENE = REPO / "third_party/unitree_mujoco/unitree_robots/go2/scene.xml"
MODEL = REPO / "third_party/unitree_mujoco/unitree_robots/go2/go2.xml"
CONFIG = REPO / "configs/robot.yaml"
SEED = 20260828
EXPECTED_DIGESTS = {
    "src/parcel_robot/rl/env.py": (
        "16c461bb93257ad8a70b0d54e61cd9ccbf0354c12881bfc448045591f0282c00"
    ),
    "src/parcel_robot/rl/spaces.py": (
        "f739cc3b94058c2c6e8297a7f82a13ddefa514cace227c23267966ada4c9f400"
    ),
    "third_party/unitree_mujoco/unitree_robots/go2/go2.xml": (
        "2014a3d76e30f17ab9447d8a67bd015291f74fa4d71ae30d005f1a32bd693d4b"
    ),
    "third_party/unitree_mujoco/unitree_robots/go2/scene.xml": (
        "6c1fda780e7883665d1c84113b9275b6d448f586a8b1c110e438a37417cbccd0"
    ),
}
CRITICAL_GATES = tuple(f"G{index}" for index in range(9))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"non-finite experimental value: {result!r}")
        return result
    if value is None or isinstance(value, str):
        return value
    return str(value)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _payload_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _gate(passed: bool, criterion: str, actual: Any) -> dict[str, Any]:
    return {
        "status": "PASS" if passed else "FAIL",
        "criterion": criterion,
        "actual": _jsonable(actual),
    }


def _not_evaluated(criterion: str, reason: str) -> dict[str, Any]:
    return {
        "status": "NOT_EVALUATED",
        "criterion": criterion,
        "actual": {"reason": reason},
    }


def _close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= 1e-6 + 0.01 * max(abs(actual), abs(expected))


def _new_env(*, use_mujoco: bool, max_steps: int = 500) -> Go2Env:
    return Go2Env(
        CONFIG,
        skill_id="stand",
        scene=SCENE if use_mujoco else None,
        use_mujoco=use_mujoco,
        max_episode_steps=max_steps,
    )


def _offline_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    env = _new_env(use_mujoco=False, max_steps=10)
    try:
        reset_obs, reset_info = env.reset(seed=SEED)
        step_obs, reward, terminated, truncated, info = env.step(np.zeros(ACTION_DIM))

        mode_values = {
            key: info.get(key)
            for key in ("physics_mode", "evidence_mode", "mode", "backend")
            if key in info
        }
        labelled_nonphysics = any(
            isinstance(value, str)
            and any(token in value.lower() for token in ("offline", "stub", "non_physics"))
            for value in mode_values.values()
        ) or info.get("physics_valid") is False

        physics_fields = ("actual_vx", "base_height", "upright")
        claims: dict[str, Any] = {}
        claims_are_invalidated = True
        for field in physics_fields:
            if field not in info or info[field] is None:
                claims[field] = {"value": info.get(field), "validity": "absent_or_none"}
                continue
            field_valid = info.get(f"{field}_valid")
            global_valid = info.get("physics_valid")
            explicitly_invalid = field_valid is False or global_valid is False
            claims[field] = {
                "value": info[field],
                "field_valid": field_valid,
                "physics_valid": global_valid,
                "explicitly_invalid": explicitly_invalid,
            }
            claims_are_invalidated = claims_are_invalidated and explicitly_invalid

        fall_detection_invalid = (
            info.get("fall_detection_valid") is False or info.get("physics_valid") is False
        )
        passed = labelled_nonphysics and claims_are_invalidated and fall_detection_invalid
        actual = {
            "labelled_nonphysics": labelled_nonphysics,
            "mode_values": mode_values,
            "physics_claims": claims,
            "fall_detection_explicitly_invalid": fall_detection_invalid,
            "reset_observation_shape": list(reset_obs.shape),
            "reset_info": reset_info,
            "step_observation_shape": list(step_obs.shape),
            "reward": reward,
            "terminated": terminated,
            "truncated": truncated,
        }
        gate = _gate(
            passed,
            "offline mode labels non-physics evidence and invalidates physics-derived claims",
            actual,
        )
        return gate, actual
    finally:
        env.close()


def _joint_names_by_address(model: Any, mujoco: Any, *, qpos: bool) -> list[str]:
    free_type = int(mujoco.mjtJoint.mjJNT_FREE)
    address = model.jnt_qposadr if qpos else model.jnt_dofadr
    pairs = [
        (int(address[joint_id]), model.joint(joint_id).name)
        for joint_id in range(model.njnt)
        if int(model.jnt_type[joint_id]) != free_type
    ]
    return [name for _, name in sorted(pairs)]


def _model_and_mapping_gates(
    env: Go2Env, reset_obs: np.ndarray, mujoco: Any
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    model = env._model
    assert model is not None
    free_type = int(mujoco.mjtJoint.mjJNT_FREE)
    free_joint_ids = [
        index for index in range(model.njnt) if int(model.jnt_type[index]) == free_type
    ]
    leg_joint_ids = [index for index in range(model.njnt) if index not in free_joint_ids]
    actuator_joint_names = [
        model.joint(int(model.actuator_trnid[index, 0])).name for index in range(model.nu)
    ]
    qpos_joint_names = _joint_names_by_address(model, mujoco, qpos=True)
    qvel_joint_names = _joint_names_by_address(model, mujoco, qpos=False)
    expected_action_names = [
        f"{leg}_{joint}_joint"
        for leg in ("FR", "FL", "RR", "RL")
        for joint in ("hip", "thigh", "calf")
    ]
    dimension_checks = {
        "declared_action_shape": tuple(env.action_space["shape"]) == (12,),
        "declared_observation_shape": tuple(env.observation_space["shape"]) == (48,),
        "returned_observation_shape": tuple(reset_obs.shape) == (48,),
        "module_action_dim": ACTION_DIM == 12,
        "module_observation_dim": OBS_DIM == 48,
        "model_nu": model.nu == 12,
        "model_nq": model.nq == 19,
        "model_nv": model.nv == 18,
        "one_free_joint": len(free_joint_ids) == 1,
        "twelve_leg_joints": len(leg_joint_ids) == 12,
        "unique_actuated_leg_joints": (
            len(actuator_joint_names) == 12
            and len(set(actuator_joint_names)) == 12
            and set(actuator_joint_names) == {model.joint(i).name for i in leg_joint_ids}
        ),
        "joint_q_block_width": env.observation_space["layout"]["joint_q"] == (7, 19),
        "joint_dq_block_width": env.observation_space["layout"]["joint_dq"] == (19, 31),
    }
    model_diag = {
        "nq": model.nq,
        "nv": model.nv,
        "nu": model.nu,
        "njnt": model.njnt,
        "nkey": model.nkey,
        "timestep_s": model.opt.timestep,
        "free_joint_ids": free_joint_ids,
        "leg_joint_names_model_order": [model.joint(i).name for i in leg_joint_ids],
        "actuator_joint_names": actuator_joint_names,
        "qpos_joint_names": qpos_joint_names,
        "qvel_joint_names": qvel_joint_names,
        "expected_from_action_meaning": expected_action_names,
        "action_meaning": env.action_space["meaning"],
        "dimension_checks": dimension_checks,
    }
    g1 = _gate(
        all(dimension_checks.values()),
        "12 actions, 48 observations, and exact Go2 nq/nv/nu plus one-to-one joints",
        model_diag,
    )
    mapping_checks = {
        "action_meaning_matches_actuators": expected_action_names == actuator_joint_names,
        "observation_q_matches_actuators": qpos_joint_names == actuator_joint_names,
        "observation_dq_matches_actuators": qvel_joint_names == actuator_joint_names,
    }
    g2 = _gate(
        all(mapping_checks.values()),
        "action, joint_q, and joint_dq orders all equal actuator-to-joint order",
        {
            "checks": mapping_checks,
            "expected_from_action_meaning": expected_action_names,
            "actuator_joint_names": actuator_joint_names,
            "observation_joint_q_names": qpos_joint_names,
            "observation_joint_dq_names": qvel_joint_names,
        },
    )
    return g1, g2, model_diag


def _velocity_gate(env: Go2Env, mujoco: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    env.reset(seed=SEED)
    model, data = env._model, env._data
    assert model is not None and data is not None
    data.qvel[:] = 0.0
    data.qvel[0] = 0.5
    mujoco.mj_forward(model, data)
    trials: list[dict[str, Any]] = []
    for index in range(3):
        x_before = float(data.qpos[0])
        _, _, _, _, info = env.step(np.zeros(ACTION_DIM))
        x_after = float(data.qpos[0])
        fd_vx = (x_after - x_before) / float(model.opt.timestep)
        reported = float(info["actual_vx"])
        trials.append(
            {
                "step": index + 1,
                "x_before_m": x_before,
                "x_after_m": x_after,
                "finite_difference_vx_mps": fd_vx,
                "reported_actual_vx_mps": reported,
                "matches": _close(reported, fd_vx),
            }
        )
    gate = _gate(
        all(row["matches"] for row in trials),
        "reported actual_vx matches finite-difference root velocity for all three steps",
        {"trials": trials},
    )
    return gate, trials


def _body_z_projection(quat_wxyz: np.ndarray) -> float:
    quat = np.asarray(quat_wxyz, dtype=np.float64)
    norm = float(np.linalg.norm(quat))
    if norm == 0.0:
        return float("nan")
    _, x, y, _ = quat / norm
    return float(1.0 - 2.0 * (x * x + y * y))


def _posture_case(env: Go2Env, mujoco: Any, *, forced_fall: bool) -> dict[str, Any]:
    env.reset(seed=SEED)
    model, data = env._model, env._data
    assert model is not None and data is not None
    if forced_fall:
        data.qpos[2] = 0.08
        data.qpos[3:7] = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float64)
        data.qvel[:] = 0.0
        mujoco.mj_forward(model, data)
    home_targets = np.asarray(model.key_ctrl[0], dtype=np.float64) if model.nkey else np.zeros(12)
    _, _, terminated, truncated, info = env.step(home_targets)
    root_height = float(data.qpos[2])
    projection = _body_z_projection(data.qpos[3:7])
    derived_upright = root_height >= 0.18 and projection >= 0.5
    return {
        "case": "forced_fall" if forced_fall else "home",
        "root_height_m": root_height,
        "reported_base_height": float(info["base_height"]),
        "height_matches": _close(float(info["base_height"]), root_height),
        "root_quat_wxyz": np.array(data.qpos[3:7], copy=True),
        "body_z_world_z_projection": projection,
        "derived_upright": derived_upright,
        "reported_upright": bool(info["upright"]),
        "upright_matches": bool(info["upright"]) == derived_upright,
        "terminated": bool(terminated),
        "truncated": bool(truncated),
    }


def _posture_gates(
    env: Go2Env, mujoco: Any
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    cases = [
        _posture_case(env, mujoco, forced_fall=False),
        _posture_case(env, mujoco, forced_fall=True),
    ]
    g4 = _gate(
        all(case["height_matches"] for case in cases),
        "reported base_height matches post-step free-joint root qpos[2] in both cases",
        {"cases": cases},
    )
    g5 = _gate(
        all(case["upright_matches"] for case in cases),
        "reported upright equals height-and-orientation-derived upright in both cases",
        {"cases": cases},
    )
    fallen = next(case for case in cases if case["case"] == "forced_fall")
    g6 = _gate(
        fallen["terminated"],
        "forced fall terminates no later than the immediately following step",
        {"forced_fall": fallen},
    )
    return g4, g5, g6, cases


def _rollout_record(env: Go2Env, actions: list[np.ndarray]) -> dict[str, Any]:
    rows = []
    for action in actions:
        obs, reward, terminated, truncated, info = env.step(action)
        rows.append(
            {
                "observation": obs,
                "reward": reward,
                "terminated": terminated,
                "truncated": truncated,
                "info": info,
            }
        )
    return {"steps": rows}


def _reset_determinism_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    first = _new_env(use_mujoco=True, max_steps=100)
    second = _new_env(use_mujoco=True, max_steps=100)
    try:
        first.reset(seed=1)
        second.reset(seed=2)
        for _ in range(3):
            first.step(np.zeros(ACTION_DIM))
        dirty_action = np.linspace(-0.3, 0.3, ACTION_DIM, dtype=np.float64)
        for _ in range(5):
            second.step(dirty_action)

        reset_first, reset_info_first = first.reset(seed=SEED)
        reset_second, reset_info_second = second.reset(seed=SEED)
        actions = [
            np.zeros(ACTION_DIM, dtype=np.float64),
            np.linspace(-0.2, 0.2, ACTION_DIM, dtype=np.float64),
            np.array([0.0, 0.9, -1.8] * 4, dtype=np.float64),
            np.linspace(0.15, -0.15, ACTION_DIM, dtype=np.float64),
        ]
        first_record = {
            "reset_observation": reset_first,
            "reset_info": reset_info_first,
            **_rollout_record(first, actions),
        }
        second_record = {
            "reset_observation": reset_second,
            "reset_info": reset_info_second,
            **_rollout_record(second, actions),
        }
        first_bytes = _canonical_bytes(first_record)
        second_bytes = _canonical_bytes(second_record)
        reset_diff = np.abs(reset_first - reset_second)
        actual = {
            "records_equal": first_bytes == second_bytes,
            "first_record_sha256": hashlib.sha256(first_bytes).hexdigest(),
            "second_record_sha256": hashlib.sha256(second_bytes).hexdigest(),
            "reset_observation_max_abs_difference": float(np.max(reset_diff)),
            "reset_differing_indices": np.flatnonzero(reset_diff != 0.0),
            "first_reset_last_action": reset_first[31:43],
            "second_reset_last_action": reset_second[31:43],
        }
        gate = _gate(
            first_bytes == second_bytes,
            "same seed and actions match exactly after distinct prior histories",
            actual,
        )
        return gate, _jsonable(actual)
    finally:
        first.close()
        second.close()


def _action_effect_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    home_env = _new_env(use_mujoco=True, max_steps=100)
    offset_env = _new_env(use_mujoco=True, max_steps=100)
    try:
        home_env.reset(seed=SEED)
        offset_env.reset(seed=SEED)
        assert home_env._model is not None and offset_env._model is not None
        home = np.asarray(home_env._model.key_ctrl[0], dtype=np.float64)
        offsets = np.array([0.25 if index % 2 == 0 else -0.25 for index in range(12)])
        perturbed = home + offsets
        for _ in range(25):
            home_env.step(home)
            offset_env.step(perturbed)
        assert home_env._data is not None and offset_env._data is not None
        home_qpos = np.array(home_env._data.qpos, copy=True)
        offset_qpos = np.array(offset_env._data.qpos, copy=True)
        distance = float(np.linalg.norm(offset_qpos - home_qpos))
        actual = {
            "steps": 25,
            "home_action": home,
            "perturbed_action": perturbed,
            "final_home_qpos": home_qpos,
            "final_perturbed_qpos": offset_qpos,
            "final_qpos_l2_distance": distance,
            "finite": math.isfinite(distance),
        }
        gate = _gate(
            math.isfinite(distance) and distance >= 1e-3,
            "25-step action branches produce finite final qpos L2 distance >= 1e-3",
            actual,
        )
        return gate, _jsonable(actual)
    finally:
        home_env.close()
        offset_env.close()


def run() -> dict[str, Any]:
    source_digests = {relative: _sha256(REPO / relative) for relative in EXPECTED_DIGESTS}
    subject_matches = source_digests == EXPECTED_DIGESTS
    gates: dict[str, dict[str, Any]] = {}
    diagnostics: dict[str, Any] = {}

    try:
        gates["G0"], diagnostics["offline"] = _offline_gate()
    except Exception as error:  # noqa: BLE001 - an audit failure is recorded evidence
        gates["G0"] = _gate(
            False,
            "offline mode labels non-physics evidence and invalidates physics-derived claims",
            {"exception": f"{type(error).__name__}: {error}"},
        )
        diagnostics["offline"] = gates["G0"]["actual"]

    mujoco_available = True
    mujoco_error = ""
    try:
        import mujoco
    except Exception as error:  # noqa: BLE001 - optional dependency probe
        mujoco_available = False
        mujoco_error = f"{type(error).__name__}: {error}"
        mujoco = None

    if not mujoco_available or not SCENE.is_file():
        reason = mujoco_error or f"tracked scene missing: {SCENE}"
        criteria = {
            "G1": "12 actions, 48 observations, and exact Go2 nq/nv/nu plus one-to-one joints",
            "G2": "action, joint_q, and joint_dq orders all equal actuator-to-joint order",
            "G3": "reported actual_vx matches finite-difference root velocity for all steps",
            "G4": "reported base_height matches root qpos[2]",
            "G5": "reported upright matches height-and-orientation-derived upright",
            "G6": "forced fall terminates on the following step",
            "G7": "reset is deterministic and history-independent",
            "G8": "different actions materially affect physics",
        }
        for gate_id, criterion in criteria.items():
            gates[gate_id] = _not_evaluated(criterion, reason)
    else:
        env = _new_env(use_mujoco=True, max_steps=100)
        try:
            reset_obs, reset_info = env.reset(seed=SEED)
            diagnostics["mujoco_reset_info"] = reset_info
            gates["G1"], gates["G2"], diagnostics["model"] = _model_and_mapping_gates(
                env, reset_obs, mujoco
            )
            gates["G3"], diagnostics["velocity_trials"] = _velocity_gate(env, mujoco)
            (
                gates["G4"],
                gates["G5"],
                gates["G6"],
                diagnostics["posture_cases"],
            ) = _posture_gates(env, mujoco)
        finally:
            env.close()
        gates["G7"], diagnostics["reset_determinism"] = _reset_determinism_gate()
        gates["G8"], diagnostics["action_effect"] = _action_effect_gate()

    statuses = {gate_id: gates[gate_id]["status"] for gate_id in CRITICAL_GATES}
    if not subject_matches:
        decision = "INVALIDATED_SUBJECT_DRIFT"
    elif any(status == "FAIL" for status in statuses.values()):
        decision = "REFUTED"
    elif any(status == "NOT_EVALUATED" for status in statuses.values()):
        decision = "INCONCLUSIVE"
    else:
        decision = "SUPPORTED_LOCAL_SIM"

    result = {
        "schema_version": 1,
        "experiment_id": "RL-ENV-READINESS-1",
        "seed": SEED,
        "evidence_tier": "local_executable_contract_plus_mujoco_no_policy_no_hardware",
        "subject": {
            "expected_sha256": EXPECTED_DIGESTS,
            "observed_sha256": source_digests,
            "matches_preregistration": subject_matches,
        },
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "mujoco_available": mujoco_available,
            "mujoco": getattr(mujoco, "__version__", None),
            "scene_relative": str(SCENE.relative_to(REPO)),
            "config_relative": str(CONFIG.relative_to(REPO)),
        },
        "gates": gates,
        "gate_statuses": statuses,
        "summary": {
            "pass": sum(status == "PASS" for status in statuses.values()),
            "fail": sum(status == "FAIL" for status in statuses.values()),
            "not_evaluated": sum(status == "NOT_EVALUATED" for status in statuses.values()),
            "total": len(statuses),
        },
        "hypothesis": {
            "id": "H-RL-READY",
            "decision": decision,
            "rule": "all G0-G8 pass; any fail refutes; missing MuJoCo is inconclusive",
        },
        "diagnostics": diagnostics,
        "claim_limits": [
            "No policy was trained or compared.",
            "No generalized locomotion capability was measured.",
            "No sim-to-real transfer or physical safety was measured.",
            "No ROS, Unitree SDK, robot, viewer, network, or live socket was used.",
        ],
    }
    result["payload_sha256"] = _payload_digest(result)
    return _jsonable(result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    output = args.out.resolve()
    try:
        output.relative_to(ARTIFACT_DIR)
    except ValueError as error:
        raise SystemExit(f"refusing to write outside {ARTIFACT_DIR}: {output}") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out": str(output.relative_to(REPO)),
                "decision": result["hypothesis"]["decision"],
                "summary": result["summary"],
                "payload_sha256": result["payload_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
