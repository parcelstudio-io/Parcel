"""Exact-runtime scene/render/action probe for archived Python 3.6.

This fixed script uses only the public Habitat test fixture mounted at
``/opt/parcel-smoke/data``.  It does not import Habitat-Lab, read a goal, run a
policy/evaluator, or calculate a navigation metric.
"""

import ctypes
import gzip
import hashlib
import json
import math
import os
import sys
import traceback

SENTINEL = "PARCEL_HABITAT_SCENE_SMOKE="
DATA_ROOT = "/opt/parcel-smoke/data"
SCENE_PATH = os.path.join(
    DATA_ROOT,
    "scene_datasets/habitat-test-scenes/skokloster-castle.glb",
)
NAVMESH_PATH = os.path.join(
    DATA_ROOT,
    "scene_datasets/habitat-test-scenes/skokloster-castle.navmesh",
)
DATASET_PATH = os.path.join(
    DATA_ROOT,
    "datasets/pointnav/habitat-test-scenes/v1/val/val.json.gz",
)
EXPECTED_SCENE_ID = "data/scene_datasets/habitat-test-scenes/skokloster-castle.glb"
EXPECTED_EPISODE_COUNT = 100
EXPECTED_EPISODE_ID = "0"
ACTIONS = ["move_forward", "turn_left", "turn_right"]


def _cuda_probe():
    cuda = ctypes.CDLL("libcuda.so.1")
    cuda.cuInit.argtypes = [ctypes.c_uint]
    cuda.cuInit.restype = ctypes.c_int
    cuda.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
    cuda.cuDeviceGetCount.restype = ctypes.c_int
    init_result = int(cuda.cuInit(0))
    count = ctypes.c_int(0)
    count_result = int(cuda.cuDeviceGetCount(ctypes.byref(count)))
    return {
        "library_loaded": True,
        "cu_init_result": init_result,
        "cu_device_get_count_result": count_result,
        "device_count": int(count.value),
        "passed": init_result == 0 and count_result == 0 and count.value > 0,
    }


def _egl_probe():
    egl = ctypes.CDLL("libEGL.so.1")
    egl.eglGetProcAddress.argtypes = [ctypes.c_char_p]
    egl.eglGetProcAddress.restype = ctypes.c_void_p
    query_pointer = egl.eglGetProcAddress(b"eglQueryDevicesEXT")
    display_pointer = egl.eglGetProcAddress(b"eglGetPlatformDisplayEXT")
    if not query_pointer or not display_pointer:
        return {
            "library_loaded": True,
            "extension_functions_resolved": False,
            "device_count": 0,
            "egl_initialize_result": False,
            "passed": False,
        }
    query_devices = ctypes.CFUNCTYPE(
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_int),
    )(query_pointer)
    get_platform_display = ctypes.CFUNCTYPE(
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
    )(display_pointer)
    devices = (ctypes.c_void_p * 16)()
    count = ctypes.c_int(0)
    query_result = bool(query_devices(16, devices, ctypes.byref(count)))
    initialized = False
    major = ctypes.c_int(0)
    minor = ctypes.c_int(0)
    if query_result and count.value > 0:
        display = get_platform_display(0x313F, devices[0], None)
        if display:
            egl.eglInitialize.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
            ]
            egl.eglInitialize.restype = ctypes.c_uint
            initialized = bool(egl.eglInitialize(display, ctypes.byref(major), ctypes.byref(minor)))
            if initialized:
                egl.eglTerminate.argtypes = [ctypes.c_void_p]
                egl.eglTerminate.restype = ctypes.c_uint
                egl.eglTerminate(display)
    return {
        "library_loaded": True,
        "extension_functions_resolved": True,
        "query_devices_result": query_result,
        "device_count": int(count.value),
        "egl_initialize_result": initialized,
        "egl_version": f"{major.value}.{minor.value}",
        "passed": query_result and count.value > 0 and initialized,
    }


def _load_start_fixture():
    for path in (SCENE_PATH, NAVMESH_PATH, DATASET_PATH):
        if not os.path.isfile(path):
            raise RuntimeError(f"required read-only fixture is missing: {path}")
        if not os.path.realpath(path).startswith(os.path.realpath(DATA_ROOT) + os.sep):
            raise RuntimeError("fixture resolves outside the mounted data root")
    with gzip.open(DATASET_PATH, "rb") as stream:
        payload = stream.read(16 * 1024 * 1024 + 1)
    if len(payload) > 16 * 1024 * 1024:
        raise RuntimeError("PointNav fixture exceeds its decompression bound")
    document = json.loads(payload.decode("utf-8"))
    episodes = document.get("episodes") if isinstance(document, dict) else None
    if not isinstance(episodes, list) or len(episodes) != EXPECTED_EPISODE_COUNT:
        raise RuntimeError("PointNav fixture has an unexpected episode count")
    matches = [
        item
        for item in episodes
        if isinstance(item, dict)
        and str(item.get("episode_id")) == EXPECTED_EPISODE_ID
        and item.get("scene_id") == EXPECTED_SCENE_ID
    ]
    if len(matches) != 1:
        raise RuntimeError("PointNav start fixture does not select the frozen test scene")
    position = matches[0].get("start_position")
    rotation = matches[0].get("start_rotation")
    if not (
        isinstance(position, list)
        and len(position) == 3
        and isinstance(rotation, list)
        and len(rotation) == 4
        and all(isinstance(value, (int, float)) and math.isfinite(value) for value in position)
        and all(isinstance(value, (int, float)) and math.isfinite(value) for value in rotation)
    ):
        raise RuntimeError("PointNav start fixture has an invalid transform")
    return position, rotation


def _observation_summary(observations, numpy):
    color = numpy.asarray(observations["color_sensor"])
    depth = numpy.asarray(observations["depth_sensor"])
    if color.shape[:2] != (128, 128) or color.ndim != 3 or color.shape[2] not in (3, 4):
        raise RuntimeError("unexpected RGB observation shape")
    if depth.shape != (128, 128) or not numpy.isfinite(depth).all():
        raise RuntimeError("unexpected depth observation shape or values")
    color_range = int(color.max()) - int(color.min())
    positive_depth = int(numpy.count_nonzero(depth > 0))
    if color_range <= 0 or positive_depth <= 0:
        raise RuntimeError("rendered RGB-D observation has no scene variation")
    return {
        "color_shape": list(color.shape),
        "color_dtype": str(color.dtype),
        "color_sha256": hashlib.sha256(color.tobytes()).hexdigest(),
        "color_value_range": color_range,
        "depth_shape": list(depth.shape),
        "depth_dtype": str(depth.dtype),
        "depth_sha256": hashlib.sha256(depth.tobytes()).hexdigest(),
        "positive_depth_pixels": positive_depth,
    }


def _state_summary(agent, habitat_sim, numpy):
    state = agent.get_state()
    return {
        "position": [float(value) for value in state.position],
        "rotation_xyzw": [
            float(value) for value in habitat_sim.utils.common.quat_to_coeffs(state.rotation)
        ],
        "position_norm": float(numpy.linalg.norm(state.position)),
    }


def _simulator_probe(position, rotation):
    import habitat_sim
    import numpy as np

    simulator_configuration = habitat_sim.SimulatorConfiguration()
    simulator_configuration.scene.id = SCENE_PATH
    simulator_configuration.gpu_device_id = 0
    simulator_configuration.allow_sliding = False

    color = habitat_sim.SensorSpec()
    color.uuid = "color_sensor"
    color.sensor_type = habitat_sim.SensorType.COLOR
    color.resolution = [128, 128]
    color.position = [0.0, 1.5, 0.0]

    depth = habitat_sim.SensorSpec()
    depth.uuid = "depth_sensor"
    depth.sensor_type = habitat_sim.SensorType.DEPTH
    depth.resolution = [128, 128]
    depth.position = [0.0, 1.5, 0.0]

    agent_configuration = habitat_sim.AgentConfiguration()
    agent_configuration.sensor_specifications = [color, depth]
    agent_configuration.action_space = {
        "move_forward": habitat_sim.agent.ActionSpec(
            "move_forward", habitat_sim.agent.ActuationSpec(amount=0.25)
        ),
        "turn_left": habitat_sim.agent.ActionSpec(
            "turn_left", habitat_sim.agent.ActuationSpec(amount=30.0)
        ),
        "turn_right": habitat_sim.agent.ActionSpec(
            "turn_right", habitat_sim.agent.ActuationSpec(amount=30.0)
        ),
    }
    configuration = habitat_sim.Configuration(simulator_configuration, [agent_configuration])
    simulator = None
    try:
        simulator = habitat_sim.Simulator(configuration)
        agent = simulator.get_agent(0)
        initial_state = habitat_sim.AgentState()
        initial_state.position = np.asarray(position, dtype=np.float64)
        initial_state.rotation = habitat_sim.utils.common.quat_from_coeffs(
            np.asarray(rotation, dtype=np.float64)
        )
        agent.set_state(initial_state, reset_sensors=True, is_initial=True)
        before = _state_summary(agent, habitat_sim, np)
        frames = [_observation_summary(simulator.get_sensor_observations(), np)]
        collisions = []
        action_states = []
        for action in ACTIONS:
            observations = simulator.step(action)
            collisions.append(bool(observations.pop("collided")))
            frames.append(_observation_summary(observations, np))
            action_states.append(_state_summary(agent, habitat_sim, np))
        after = action_states[-1]
        displacement = float(
            np.linalg.norm(np.asarray(after["position"]) - np.asarray(before["position"]))
        )
        turn_changed_orientation = (
            action_states[0]["rotation_xyzw"] != action_states[1]["rotation_xyzw"]
        )
        rendering_passed = len(frames) == 4 and len({item["color_sha256"] for item in frames}) >= 2
        actions_passed = displacement > 0.05 and turn_changed_orientation
        return {
            "habitat_sim_version": getattr(habitat_sim, "__version__", None),
            "python_version": sys.version,
            "simulator_constructed": True,
            "scene_loaded": True,
            "navmesh_loaded": bool(simulator.pathfinder.is_loaded),
            "rendering": {
                "frame_count": len(frames),
                "frames": frames,
                "passed": rendering_passed,
            },
            "actions": {
                "executed": list(ACTIONS),
                "collisions": collisions,
                "position_displacement_m": displacement,
                "turn_changed_orientation": turn_changed_orientation,
                "states": action_states,
                "passed": actions_passed,
            },
            "start_state": before,
            "passed": bool(simulator.pathfinder.is_loaded and rendering_passed and actions_passed),
        }
    finally:
        if simulator is not None:
            simulator.close()


def main():
    report = {
        "schema_version": 1,
        "python_version": sys.version,
        "cuda": None,
        "egl": None,
        "rendering": None,
        "actions": None,
        "claims": {
            "pointnav_fixture_start_state_used": False,
            "pointnav_goal_read_or_used": False,
            "scene_loaded": False,
            "simulator_constructed": False,
            "gpu_render_executed": False,
            "discrete_actions_executed": False,
            "stop_task_action_executed": False,
            "parcel_policy_executed": False,
            "official_evaluator_executed": False,
            "navigation_episode_executed": False,
            "navigation_metrics_emitted": False,
            "cuda_compute_kernel_executed": False,
        },
        "passed": False,
    }
    try:
        report["cuda"] = _cuda_probe()
        report["egl"] = _egl_probe()
        position, rotation = _load_start_fixture()
        report["claims"]["pointnav_fixture_start_state_used"] = True
        simulator = _simulator_probe(position, rotation)
        report["habitat_sim_version"] = simulator["habitat_sim_version"]
        report["simulator_constructed"] = simulator["simulator_constructed"]
        report["scene_loaded"] = simulator["scene_loaded"]
        report["navmesh_loaded"] = simulator["navmesh_loaded"]
        report["rendering"] = simulator["rendering"]
        report["actions"] = simulator["actions"]
        report["start_state"] = simulator["start_state"]
        report["claims"]["simulator_constructed"] = simulator["simulator_constructed"]
        report["claims"]["scene_loaded"] = simulator["scene_loaded"]
        report["claims"]["gpu_render_executed"] = simulator["rendering"]["passed"]
        report["claims"]["discrete_actions_executed"] = simulator["actions"]["passed"]
        report["passed"] = bool(
            report["cuda"]["passed"]
            and report["egl"]["passed"]
            and simulator["passed"]
            and simulator["habitat_sim_version"] == "0.1.4"
        )
    except Exception as error:  # noqa: BLE001 - emit one fail-closed in-image result
        report["error"] = f"{type(error).__name__}: {error}"
        report["traceback"] = traceback.format_exc()
    print(SENTINEL + json.dumps(report, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
