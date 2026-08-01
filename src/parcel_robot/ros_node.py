from __future__ import annotations

import json

from .agent import VoiceAgent
from .config import ConfigStore
from .memory import ConversationMemory
from .models import Pose
from .providers import LlamaCppProvider

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
except ImportError:  # Allows configuration and command tests without ROS installed.
    rclpy = None
    Node = object
    String = None


class ParcelAgentNode(Node):
    """ROS boundary for transcripts, pose requests, and spoken responses."""

    def __init__(self, config_path: str):
        if rclpy is None:
            raise RuntimeError("ROS 2 Python packages are unavailable; source ROS before starting")
        super().__init__("parcel_voice_agent")
        store = ConfigStore(config_path)
        self.pose_pub = self.create_publisher(String, "/parcel/pose_request", 10)
        self.stop_pub = self.create_publisher(String, "/parcel/stop_request", 10)
        self.reply_pub = self.create_publisher(String, "/parcel/voice_reply", 10)
        model_config = store.section("language_model")
        language_model = None
        if model_config.get("enabled", False):
            language_model = LlamaCppProvider(
                base_url=str(model_config.get("base_url", "http://127.0.0.1:8080")),
                model=str(model_config.get("model", "gemma")),
                timeout=float(model_config.get("timeout", 30)),
            )
        memory_config = store.section("memory")
        self.agent = VoiceAgent(
            store.poses(),
            store.load_modules(),
            self.publish_pose,
            language_model=language_model,
            stop_publisher=self.publish_stop,
            memory=ConversationMemory(memory_config.get("path", ":memory:")),
        )
        self.create_subscription(String, "/parcel/transcript", self.on_transcript, 10)

    def publish_pose(self, pose: Pose) -> None:
        message = String()
        message.data = json.dumps(
            {"name": pose.name, "duration": pose.duration, "joints": pose.joints}
        )
        self.pose_pub.publish(message)

    def publish_stop(self) -> None:
        message = String()
        message.data = json.dumps({"command": "stop", "source": "voice_agent"})
        self.stop_pub.publish(message)

    def on_transcript(self, message: String) -> None:
        reply = String()
        reply.data = self.agent.handle_text(message.data)
        self.reply_pub.publish(reply)


def run(config_path: str) -> None:
    if rclpy is None:
        raise RuntimeError("ROS 2 Python packages are unavailable; source ROS before starting")
    rclpy.init()
    node = ParcelAgentNode(config_path)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
