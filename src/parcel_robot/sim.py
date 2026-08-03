from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np

from .config import ConfigStore
from .gait import ScriptedTrotGait, TrajectoryPlayer
from .models import Pose, VelocityCommand
from .sim_control import PoseController
from .sim_ipc import DEFAULT_SOCKET, PoseSocketServer, message_to_pose, message_to_velocity

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "robot.yaml"
FALLBACK_CONFIG = Path(__file__).with_name("config") / "robot.yaml"
DEFAULT_SCENE = Path(__file__).with_name("scenes") / "city_block.xml"
FLAT_SCENE = (
    REPO_ROOT
    / "third_party"
    / "unitree_mujoco"
    / "unitree_robots"
    / "go2"
    / "scene.xml"
)


def resolve_scene(config_path: Path, override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    store = ConfigStore(config_path)
    simulation = store.section("simulation") if "simulation" in store.data else {}
    configured = simulation.get("scene")
    if configured:
        path = Path(str(configured)).expanduser()
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path.resolve()
    if DEFAULT_SCENE.is_file():
        return DEFAULT_SCENE.resolve()
    return FLAT_SCENE.resolve()


def run_simulator(
    *,
    scene: Path,
    socket_path: Path,
    poses: dict[str, Pose],
    kp: float,
    kd: float,
    walk_vx: float = 0.3,
    walk_yaw: float = 0.4,
    simulate_dt: float = 0.005,
    viewer_dt: float = 0.02,
) -> None:
    if not scene.exists():
        raise FileNotFoundError(
            f"MuJoCo scene not found: {scene}\n"
            "Clone unitree_mujoco into third_party/ or pass --scene."
        )

    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    model.opt.timestep = simulate_dt
    if model.nkey > 0:
        mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)

    controller = PoseController(model, kp=kp, kd=kd)
    controller.sync_from_state(data)
    gait = ScriptedTrotGait()
    trajectory = TrajectoryPlayer()
    walk_command: VelocityCommand | None = None
    last_motion_at = time.monotonic()
    last_walk_log_at = 0.0
    last_logged_walk: VelocityCommand | None = None
    owner_visible = True
    emergency_stopped = False
    pending: list[dict] = []
    pose_hotkeys = {ord("1"): "sit", ord("2"): "bow"}
    base_position = np.array(data.qpos[:3], dtype=np.float64)
    base_yaw = 0.0

    owner_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "owner")
    owner_mocap_id = int(model.body_mocapid[owner_body_id]) if owner_body_id >= 0 else -1
    obstacle_geom_ids: list[int] = []
    for geom_id in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or ""
        if name.startswith(("obstacle_", "bldg_", "bench_", "owner_")):
            obstacle_geom_ids.append(geom_id)

    def robot_yaw() -> float:
        if model.nq < 7:
            return 0.0
        w, x, y, z = (float(value) for value in data.qpos[3:7])
        return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))

    base_yaw = robot_yaw()

    def place_kinematic_base(dt: float) -> None:
        """Advance the game-like base without injecting unstable root forces."""
        nonlocal base_yaw
        if model.nq < 7 or model.nv < 6:
            return
        if walk_command is not None and dt > 0.0:
            cosine = math.cos(base_yaw)
            sine = math.sin(base_yaw)
            allow_translation = True
            obstacle = nearest_obstacle()
            if obstacle is not None and float(obstacle["distance_m"]) <= 0.08:
                travel_angle = math.atan2(walk_command.vy, walk_command.vx)
                angle_error = (
                    float(obstacle["bearing_rad"]) - travel_angle + math.pi
                ) % (2.0 * math.pi) - math.pi
                allow_translation = abs(angle_error) >= 1.15
            if allow_translation:
                base_position[0] += (
                    cosine * walk_command.vx - sine * walk_command.vy
                ) * dt
                base_position[1] += (
                    sine * walk_command.vx + cosine * walk_command.vy
                ) * dt
            base_yaw = (base_yaw + walk_command.vyaw * dt + math.pi) % (
                2.0 * math.pi
            ) - math.pi
        data.qpos[:3] = base_position
        half_yaw = base_yaw * 0.5
        data.qpos[3:7] = (math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw))
        data.qvel[:6] = 0.0

    def nearest_obstacle() -> dict[str, float | str] | None:
        if model.nq < 2 or not obstacle_geom_ids:
            return None
        px, py = float(data.qpos[0]), float(data.qpos[1])
        heading = robot_yaw()
        candidates: list[dict[str, float | str]] = []
        robot_radius = 0.32
        for geom_id in obstacle_geom_ids:
            gx, gy = (float(value) for value in data.geom_xpos[geom_id, :2])
            geom_type = int(model.geom_type[geom_id])
            if geom_type == int(mujoco.mjtGeom.mjGEOM_BOX):
                sx, sy = (float(value) for value in model.geom_size[geom_id, :2])
                dx = max(abs(px - gx) - sx, 0.0)
                dy = max(abs(py - gy) - sy, 0.0)
                distance = math.hypot(dx, dy) - robot_radius
            elif geom_type in {
                int(mujoco.mjtGeom.mjGEOM_CYLINDER),
                int(mujoco.mjtGeom.mjGEOM_CAPSULE),
                int(mujoco.mjtGeom.mjGEOM_SPHERE),
            }:
                radius = float(model.geom_size[geom_id, 0])
                distance = math.hypot(px - gx, py - gy) - radius - robot_radius
            else:
                continue
            bearing = (math.atan2(gy - py, gx - px) - heading + math.pi) % (
                2.0 * math.pi
            ) - math.pi
            candidates.append(
                {
                    "id": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
                    or f"geom-{geom_id}",
                    "distance_m": max(0.0, distance),
                    "bearing_rad": bearing,
                    "x": gx,
                    "y": gy,
                }
            )
        return min(candidates, key=lambda item: float(item["distance_m"])) if candidates else None

    def state_snapshot() -> dict:
        obstacle = nearest_obstacle()
        obstacle_distance = float(obstacle["distance_m"]) if obstacle is not None else None
        if owner_mocap_id >= 0:
            owner_x, owner_y = (
                float(data.mocap_pos[owner_mocap_id, 0]),
                float(data.mocap_pos[owner_mocap_id, 1]),
            )
        else:
            owner_x, owner_y = 0.0, 0.0
        command = walk_command or VelocityCommand()
        return {
            "type": "status",
            "backend": "mujoco",
            "timestamp": time.monotonic(),
            "sim_time": float(data.time),
            "robot": {
                "x": float(data.qpos[0]) if model.nq > 0 else 0.0,
                "y": float(data.qpos[1]) if model.nq > 1 else 0.0,
                "z": float(data.qpos[2]) if model.nq > 2 else 0.0,
                "yaw": robot_yaw(),
            },
            "owner": {
                "id": "owner-1",
                "x": owner_x,
                "y": owner_y,
                "visible": owner_visible,
                "confidence": 1.0 if owner_visible else 0.0,
            },
            "nearest_obstacle_m": obstacle_distance,
            "nearest_obstacle": obstacle,
            "collision": obstacle_distance is not None and obstacle_distance <= 0.01,
            "emergency_stopped": emergency_stopped,
            "command": {"vx": command.vx, "vy": command.vy, "vyaw": command.vyaw},
        }

    def stop_local() -> None:
        nonlocal last_motion_at, walk_command
        walk_command = None
        last_motion_at = time.monotonic()
        trajectory.stop()
        gait.reset()
        controller.hold_joints(gait.standing_joints())
        data.qvel[:] = 0.0

    def apply_local(message: dict) -> None:
        nonlocal emergency_stopped, last_logged_walk, last_motion_at
        nonlocal last_walk_log_at, owner_visible, walk_command
        kind = message.get("type")
        if kind == "emergency_stop":
            emergency_stopped = True
            stop_local()
            print("emergency stop latched", flush=True)
        elif kind == "clear_emergency_stop":
            emergency_stopped = False
            stop_local()
            print("emergency stop cleared", flush=True)
        elif kind == "stop":
            stop_local()
            print("stop requested", flush=True)
        elif kind == "pose":
            if emergency_stopped:
                raise ValueError("simulator motion is disabled by emergency stop")
            walk_command = None
            trajectory.stop()
            gait.reset()
            pose = message_to_pose(message)
            controller.apply_pose(pose, data)
            print(f"applying pose: {pose.name}", flush=True)
        elif kind == "walk":
            if emergency_stopped:
                raise ValueError("simulator motion is disabled by emergency stop")
            trajectory.stop()
            requested = message_to_velocity(message)
            walk_command = VelocityCommand(
                vx=float(np.clip(requested.vx, -walk_vx * 2.0, walk_vx * 2.0)),
                vy=float(np.clip(requested.vy, -walk_vx * 2.0, walk_vx * 2.0)),
                vyaw=float(np.clip(requested.vyaw, -walk_yaw * 2.5, walk_yaw * 2.5)),
            )
            last_motion_at = time.monotonic()
            style = str(message.get("gait_style", "trot"))
            freq = message.get("frequency_hz")
            gait.set_style(style, float(freq) if freq is not None else None)
            gait.reset()
            now = time.monotonic()
            change = (
                float("inf")
                if last_logged_walk is None
                else max(
                    abs(walk_command.vx - last_logged_walk.vx),
                    abs(walk_command.vy - last_logged_walk.vy),
                    abs(walk_command.vyaw - last_logged_walk.vyaw),
                )
            )
            if change >= 0.08 or now - last_walk_log_at >= 1.0:
                print(
                    f"walk command: vx={walk_command.vx:.2f} "
                    f"vy={walk_command.vy:.2f} vyaw={walk_command.vyaw:.2f} style={style}",
                    flush=True,
                )
                last_logged_walk = walk_command
                last_walk_log_at = now
        elif kind == "trajectory":
            if emergency_stopped:
                raise ValueError("simulator motion is disabled by emergency stop")
            walk_command = None
            gait.reset()
            frames = list(message.get("keyframes") or [])
            trajectory.start(frames)
            print(f"trajectory: {message.get('name', 'unnamed')}", flush=True)
        elif kind == "owner_move":
            dx = float(message.get("dx", 0.0))
            dy = float(message.get("dy", 0.0))
            if not math.isfinite(dx) or not math.isfinite(dy) or abs(dx) > 1 or abs(dy) > 1:
                raise ValueError("owner move is outside the allowed range")
            if owner_mocap_id >= 0:
                data.mocap_pos[owner_mocap_id, 0] = np.clip(
                    data.mocap_pos[owner_mocap_id, 0] + dx, -10.0, 10.0
                )
                data.mocap_pos[owner_mocap_id, 1] = np.clip(
                    data.mocap_pos[owner_mocap_id, 1] + dy, -10.0, 10.0
                )
        elif kind == "owner_visibility":
            owner_visible = bool(message.get("visible", True))
        else:
            print(f"ignored message: {kind!r}", flush=True)

    def key_callback(keycode: int) -> None:
        key = chr(keycode).lower() if 0 <= keycode < 256 else ""
        if key == "w":
            pending.append({"type": "walk", "vx": walk_vx, "vy": 0.0, "vyaw": 0.0})
        elif key == "s":
            pending.append({"type": "walk", "vx": -walk_vx, "vy": 0.0, "vyaw": 0.0})
        elif key == "a":
            pending.append({"type": "walk", "vx": 0.0, "vy": walk_vx * 0.7, "vyaw": 0.0})
        elif key == "d":
            pending.append({"type": "walk", "vx": 0.0, "vy": -walk_vx * 0.7, "vyaw": 0.0})
        elif key == "q":
            pending.append({"type": "walk", "vx": 0.0, "vy": 0.0, "vyaw": walk_yaw})
        elif key == "e":
            pending.append({"type": "walk", "vx": 0.0, "vy": 0.0, "vyaw": -walk_yaw})
        elif key == " " or keycode == 32:
            pending.append({"type": "stop"})
        elif keycode in pose_hotkeys:
            name = pose_hotkeys[keycode]
            pose = poses.get(name)
            if pose is not None:
                pending.append(
                    {
                        "type": "pose",
                        "name": pose.name,
                        "duration": pose.duration,
                        "joints": dict(pose.joints),
                    }
                )

    server = PoseSocketServer(socket_path, state_provider=state_snapshot)
    server.start()
    print(f"Parcel sim ready: {scene}", flush=True)
    print(f"Listening for poses/walk/trajectory on {socket_path}", flush=True)
    print("Controls: W/S A/D Q/E Space, 1=sit 2=bow, or run parcel-control", flush=True)

    max_steps_per_frame = max(1, int(viewer_dt / simulate_dt) * 2)
    try:
        with mujoco.viewer.launch_passive(model, data, key_callback=key_callback) as viewer:
            sim_time_wall = time.perf_counter()
            next_view = sim_time_wall
            while viewer.is_running():
                if walk_command is not None and time.monotonic() - last_motion_at > 0.65:
                    apply_local({"type": "stop"})
                    print("motion watchdog stopped a stale command", flush=True)
                for message in pending:
                    apply_local(message)
                pending.clear()
                for message in server.poll():
                    try:
                        apply_local(message)
                    except (KeyError, TypeError, ValueError) as error:
                        print(f"rejected simulator command: {error}", flush=True)

                now = time.perf_counter()
                steps = 0
                while sim_time_wall <= now and steps < max_steps_per_frame:
                    dt = model.opt.timestep
                    traj_joints = trajectory.joints_for(dt)
                    if traj_joints is not None:
                        controller.hold_joints(traj_joints)
                    elif walk_command is not None:
                        controller.hold_joints(gait.joints_for(walk_command, dt))
                    place_kinematic_base(dt)
                    controller.step(data, dt)
                    mujoco.mj_step(model, data)
                    place_kinematic_base(0.0)
                    controller.step(data, 0.0)
                    sim_time_wall += dt
                    steps += 1
                if steps == max_steps_per_frame:
                    sim_time_wall = now

                if now >= next_view:
                    mujoco.mj_forward(model, data)
                    viewer.sync()
                    next_view = now + viewer_dt

                sleep_for = min(simulate_dt, next_view - time.perf_counter())
                if sleep_for > 0.0005:
                    time.sleep(sleep_for)
    finally:
        server.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parcel MuJoCo simulator for skills / city scene"
    )
    default_config = DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else FALLBACK_CONFIG
    parser.add_argument("--config", default=str(default_config))
    parser.add_argument("--scene", help="path to a MuJoCo MJCF scene")
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET))
    parser.add_argument("--kp", type=float, default=60.0, help="position gain")
    parser.add_argument("--kd", type=float, default=2.0, help="damping gain")
    args = parser.parse_args()

    config_path = Path(args.config)
    store = ConfigStore(config_path)
    limits = store.safety_limits()
    scene = resolve_scene(config_path, args.scene)
    run_simulator(
        scene=scene,
        socket_path=Path(args.socket),
        poses=store.poses(),
        kp=args.kp,
        kd=args.kd,
        walk_vx=min(0.3, limits.max_vx),
        walk_yaw=min(0.4, limits.max_vyaw),
    )


if __name__ == "__main__":
    main()
