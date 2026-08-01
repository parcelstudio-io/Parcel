from __future__ import annotations

import argparse
import time
from pathlib import Path

import mujoco
import mujoco.viewer

from .config import ConfigStore
from .models import VelocityCommand
from .sim_control import PoseController
from .sim_ipc import DEFAULT_SOCKET, PoseSocketServer, message_to_pose, message_to_velocity

DEFAULT_CONFIG = Path(__file__).with_name("config") / "robot.yaml"
DEFAULT_SCENE = (
    Path(__file__).resolve().parents[2]
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
            repo_root = Path(__file__).resolve().parents[2]
            path = repo_root / path
        return path.resolve()
    return DEFAULT_SCENE

def run_simulator(
    *,
    scene: Path,
    socket_path: Path,
    kp: float,
    kd: float,
    simulate_dt: float = 0.002,
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
    walk_command: VelocityCommand | None = None

    server = PoseSocketServer(socket_path)
    server.start()
    print(f"Parcel sim ready: {scene}", flush=True)
    print(f"Listening for poses/walk on {socket_path}", flush=True)
    print('Try: parcel-agent --sim --text "walk forward"', flush=True)

    try:
        with mujoco.viewer.launch_passive(model, data) as viewer:
            next_view = time.perf_counter()
            while viewer.is_running():
                step_start = time.perf_counter()
                for message in server.poll():
                    kind = message.get("type")
                    if kind == "stop":
                        controller.stop(data)
                        walk_command = None
                        data.qvel[:] = 0.0
                        print("stop requested", flush=True)
                    elif kind == "pose":
                        walk_command = None
                        pose = message_to_pose(message)
                        controller.apply_pose(pose, data)
                        print(f"applying pose: {pose.name}", flush=True)
                    elif kind == "walk":
                        walk_command = message_to_velocity(message)
                        print(
                            f"walk command: vx={walk_command.vx:.2f} "
                            f"vy={walk_command.vy:.2f} vyaw={walk_command.vyaw:.2f}",
                            flush=True,
                        )
                    else:
                        print(f"ignored message: {kind!r}", flush=True)

                if walk_command is not None and model.nq >= 7:
                    # Crude free-base preview until an RL policy drives joints.
                    data.qvel[0] = walk_command.vx
                    data.qvel[1] = walk_command.vy
                    data.qvel[5] = walk_command.vyaw

                controller.step(data, model.opt.timestep)
                mujoco.mj_step(model, data)
                # Re-assert authored joint targets after the physics step.
                controller.step(data, 0.0)
                mujoco.mj_forward(model, data)

                now = time.perf_counter()
                if now >= next_view:
                    viewer.sync()
                    next_view = now + viewer_dt

                remaining = model.opt.timestep - (time.perf_counter() - step_start)
                if remaining > 0:
                    time.sleep(remaining)
    finally:
        server.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parcel MuJoCo simulator that applies robot.yaml poses"
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--scene", help="path to a MuJoCo MJCF scene")
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET))
    parser.add_argument("--kp", type=float, default=60.0, help="position gain")
    parser.add_argument("--kd", type=float, default=2.0, help="damping gain")
    args = parser.parse_args()

    config_path = Path(args.config)
    scene = resolve_scene(config_path, args.scene)
    run_simulator(
        scene=scene,
        socket_path=Path(args.socket),
        kp=args.kp,
        kd=args.kd,
    )


if __name__ == "__main__":
    main()
