from __future__ import annotations

import argparse
from pathlib import Path

from .agent import VoiceAgent
from .config import ConfigStore
from .memory import ConversationMemory
from .providers import LlamaCppProvider
from .ros_node import run

DEFAULT_CONFIG = Path(__file__).with_name("config") / "robot.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Parcel robot-dog voice agent")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--ros", action="store_true", help="run as a ROS 2 node")
    parser.add_argument("--text", help="test one transcribed command without ROS")
    parser.add_argument("--llm", action="store_true", help="use the configured llama.cpp server")
    args = parser.parse_args()

    if args.ros:
        run(args.config)
        return

    store = ConfigStore(args.config)
    published = []
    model_config = store.section("language_model")
    language_model = None
    if args.llm:
        language_model = LlamaCppProvider(
            base_url=str(model_config.get("base_url", "http://127.0.0.1:8080")),
            model=str(model_config.get("model", "gemma")),
            timeout=float(model_config.get("timeout", 30)),
        )
    agent = VoiceAgent(
        store.poses(),
        store.load_modules(),
        published.append,
        language_model=language_model,
        memory=ConversationMemory(),
    )
    if args.text:
        print(agent.handle_text(args.text))
        if published:
            print(f"pose request: {published[-1]}")
        return
    parser.error("choose --ros or --text")


if __name__ == "__main__":
    main()
