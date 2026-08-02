from __future__ import annotations

import argparse
import time
from pathlib import Path

import mujoco
import mujoco.viewer

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
    pending: list[dict] = []
    pose_hotkeys = {ord("1"): "sit", ord("2"): "bow"}

    def apply_local(message: dict) -> None:
        nonlocal walk_command
        kind = message.get("type")
        if kind == "stop":
            walk_command = None
            trajectory.stop()
            gait.reset()
            controller.hold_joints(gait.standing_joints())
            data.qvel[:] = 0.0
            print("stop requested", flush=True)
        elif kind == "pose":
            walk_command = None
            trajectory.stop()
            gait.reset()
            pose = message_to_pose(message)
            controller.apply_pose(pose, data)
            print(f"applying pose: {pose.name}", flush=True)
        elif kind == "walk":
            trajectory.stop()
            walk_command = message_to_velocity(message)
            style = str(message.get("gait_style", "trot"))
            freq = message.get("frequency_hz")
            gait.set_style(style, float(freq) if freq is not None else None)
            gait.reset()
            print(
                f"walk command: vx={walk_command.vx:.2f} "
                f"vy={walk_command.vy:.2f} vyaw={walk_command.vyaw:.2f} style={style}",
                flush=True,
            )
        elif kind == "trajectory":
            walk_command = None
            gait.reset()
            frames = list(message.get("keyframes") or [])
            trajectory.start(frames)
            print(f"trajectory: {message.get('name', 'unnamed')}", flush=True)
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

    server = PoseSocketServer(socket_path)
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
                for message in pending:
                    apply_local(message)
                pending.clear()
                for message in server.poll():
                    apply_local(message)

                now = time.perf_counter()
                steps = 0
                while sim_time_wall <= now and steps < max_steps_per_frame:
                    dt = model.opt.timestep
                    traj_joints = trajectory.joints_for(dt)
                    if traj_joints is not None:
                        controller.hold_joints(traj_joints)
                    elif walk_command is not None:
                        controller.hold_joints(gait.joints_for(walk_command, dt))
                        if model.nq >= 7:
                            data.qvel[0] = walk_command.vx
                            data.qvel[1] = walk_command.vy
                            data.qvel[5] = walk_command.vyaw
                    controller.step(data, dt)
                    mujoco.mj_step(model, data)
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
