from __future__ import annotations

import json
import socket
from pathlib import Path

from .models import Pose, VelocityCommand

DEFAULT_SOCKET = Path("/tmp/parcel_sim.sock")


def pose_to_message(pose: Pose) -> dict:
    return {
        "type": "pose",
        "name": pose.name,
        "duration": pose.duration,
        "joints": dict(pose.joints),
    }


def velocity_to_message(command: VelocityCommand) -> dict:
    return {
        "type": "walk",
        "vx": command.vx,
        "vy": command.vy,
        "vyaw": command.vyaw,
    }


def message_to_pose(message: dict) -> Pose:
    if message.get("type") != "pose":
        raise ValueError(f"unsupported message type: {message.get('type')!r}")
    joints = message.get("joints")
    if not isinstance(joints, dict) or not joints:
        raise ValueError("pose message requires a joints mapping")
    return Pose(
        name=str(message.get("name", "unnamed")),
        joints={str(name): float(value) for name, value in joints.items()},
        duration=float(message.get("duration", 1.0)),
    )


def message_to_velocity(message: dict) -> VelocityCommand:
    if message.get("type") != "walk":
        raise ValueError(f"unsupported message type: {message.get('type')!r}")
    return VelocityCommand(
        vx=float(message.get("vx", 0.0)),
        vy=float(message.get("vy", 0.0)),
        vyaw=float(message.get("vyaw", 0.0)),
    )


def send_message(message: dict, socket_path: Path | str = DEFAULT_SOCKET) -> None:
    path = Path(socket_path)
    payload = (json.dumps(message) + "\n").encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2.0)
        client.connect(str(path))
        client.sendall(payload)


def publish_pose(pose: Pose, socket_path: Path | str = DEFAULT_SOCKET) -> None:
    send_message(pose_to_message(pose), socket_path)


def publish_velocity(
    command: VelocityCommand, socket_path: Path | str = DEFAULT_SOCKET
) -> None:
    send_message(velocity_to_message(command), socket_path)


def publish_stop(socket_path: Path | str = DEFAULT_SOCKET) -> None:
    send_message({"type": "stop"}, socket_path)


class PoseSocketServer:
    """Accept newline-delimited JSON pose/stop messages over a Unix socket."""

    def __init__(self, socket_path: Path | str = DEFAULT_SOCKET):
        self.socket_path = Path(socket_path)
        self._server: socket.socket | None = None

    def start(self) -> None:
        if self.socket_path.exists():
            self.socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        server.listen(8)
        server.settimeout(0.05)
        self._server = server

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self.socket_path.exists():
            self.socket_path.unlink()

    def poll(self) -> list[dict]:
        if self._server is None:
            return []
        messages: list[dict] = []
        while True:
            try:
                conn, _ = self._server.accept()
            except TimeoutError:
                break
            except OSError:
                break
            with conn:
                conn.settimeout(0.2)
                chunks: list[bytes] = []
                try:
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
                except TimeoutError:
                    pass
            raw = b"".join(chunks).decode("utf-8")
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                messages.append(json.loads(line))
        return messages
