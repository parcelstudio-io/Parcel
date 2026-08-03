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
from .sim_ipc import DEFAULT_SOCKET
from .skills.api import Dog

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "robot.yaml"
FALLBACK_CONFIG = Path(__file__).with_name("config") / "robot.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Parcel robot-dog voice agent")
    default_config = DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else FALLBACK_CONFIG
    parser.add_argument("--config", default=str(default_config))
    parser.add_argument("--ros", action="store_true", help="run as a ROS 2 node")
    parser.add_argument("--text", help="test one transcribed command without ROS")
    parser.add_argument("--llm", action="store_true", help="use the configured llama.cpp server")
    parser.add_argument(
        "--sim",
        action="store_true",
        help="send skill requests to a running parcel-sim MuJoCo viewer",
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
        language_model = LlamaCppProvider.from_config(model_config)

    def publish(pose: Pose) -> None:
        published.append(pose)

    def on_walk(command: VelocityCommand) -> None:
        walks.append(command)

    def stop() -> None:
        pass

    motion = build_motion_router(
        store.motion_config(),
        on_command=on_walk,
        on_stop=None,
    )
    dog = Dog.from_config(
        args.config,
        sim_socket=args.socket if args.sim else None,
        motion=motion,
        on_pose=publish,
        on_velocity=on_walk,
    )

    agent = VoiceAgent(
        dog.poses() or store.poses(),
        store.load_modules(),
        publish,
        language_model=language_model,
        stop_publisher=lambda: dog.stop(),
        memory=ConversationMemory(),
        motion=motion,
        safety_limits=store.safety_limits(),
        conversation_history_messages=int(
            store.agent_config().get("conversation_history_messages", 16)
        ),
        dog=dog,
    )
    if args.text:
        print(agent.handle_text(args.text))
        if published:
            print(f"pose request: {published[-1]}")
        if walks:
            print(f"walk request: {walks[-1]}")
        print(f"motion: {motion.status()}")
        if dog.executor.selected:
            print(f"skill: {dog.executor.selected}")
        return
    parser.error("choose --ros or --text")


if __name__ == "__main__":
    main()
