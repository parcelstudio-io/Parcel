from __future__ import annotations

import argparse
from pathlib import Path

from .agent import VoiceAgent
from .config import ConfigStore
from .memory import ConversationMemory
from .models import Pose, VelocityCommand
from .motion import build_motion_router
from .providers import LlamaCppProvider
from .ros_node import run
from .sim_ipc import DEFAULT_SOCKET, publish_pose, publish_stop, publish_velocity

DEFAULT_CONFIG = Path(__file__).with_name("config") / "robot.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Parcel robot-dog voice agent")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--ros", action="store_true", help="run as a ROS 2 node")
    parser.add_argument("--text", help="test one transcribed command without ROS")
    parser.add_argument("--llm", action="store_true", help="use the configured llama.cpp server")
    parser.add_argument(
        "--sim",
        action="store_true",
        help="send pose/walk requests to a running parcel-sim MuJoCo viewer",
    )
    parser.add_argument(
        "--socket",
        default=str(DEFAULT_SOCKET),
        help="Unix socket used by parcel-sim (default: /tmp/parcel_sim.sock)",
    )
    args = parser.parse_args()

    if args.ros:
        run(args.config)
        return

    store = ConfigStore(args.config)
    published: list[Pose] = []
    walks: list[VelocityCommand] = []
    model_config = store.section("language_model")
    language_model = None
    if args.llm:
        language_model = LlamaCppProvider(
            base_url=str(model_config.get("base_url", "http://127.0.0.1:8080")),
            model=str(model_config.get("model", "gemma")),
            timeout=float(model_config.get("timeout", 30)),
        )

    def publish(pose: Pose) -> None:
        published.append(pose)
        if args.sim:
            publish_pose(pose, args.socket)

    def on_walk(command: VelocityCommand) -> None:
        walks.append(command)
        if args.sim:
            publish_velocity(command, args.socket)

    def stop() -> None:
        if args.sim:
            publish_stop(args.socket)

    motion = build_motion_router(
        store.motion_config(),
        on_command=on_walk,
        on_stop=stop if args.sim else None,
    )

    agent = VoiceAgent(
        store.poses(),
        store.load_modules(),
        publish,
        language_model=language_model,
        stop_publisher=stop,
        memory=ConversationMemory(),
        motion=motion,
        safety_limits=store.safety_limits(),
    )
    if args.text:
        print(agent.handle_text(args.text))
        if published:
            print(f"pose request: {published[-1]}")
        if walks:
            print(f"walk request: {walks[-1]}")
        print(f"motion: {motion.status()}")
        return
    parser.error("choose --ros or --text")


if __name__ == "__main__":
    main()
