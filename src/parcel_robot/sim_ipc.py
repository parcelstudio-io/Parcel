from __future__ import annotations

import json
import math
import os
import socket
import stat
from collections.abc import Callable
from pathlib import Path

from .models import Pose, VelocityCommand
from .safety import SafetyLimits

DEFAULT_SOCKET = Path("/tmp/parcel_sim.sock")
PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1_048_576
MAX_CLIENTS_PER_POLL = 4
MAX_TRAJECTORY_FRAMES = 500
MAX_TRAJECTORY_SECONDS = 30.0
ALLOWED_GAIT_STYLES = frozenset({"trot", "run", "crawl"})
_LIMITS = SafetyLimits()


def _finite_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _safe_joints(value: object, field: str = "joints") -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{field} must be a non-empty mapping")
    if len(value) > 64:
        raise ValueError(f"{field} has too many entries")
    joints: dict[str, float] = {}
    for raw_name, raw_value in value.items():
        if not isinstance(raw_name, str) or not raw_name or len(raw_name) > 128:
            raise TypeError(f"{field} names must be non-empty strings")
        position = _finite_float(raw_value, f"{field}.{raw_name}")
        if abs(position) > _LIMITS.max_abs_joint_position:
            raise ValueError(f"{field}.{raw_name} exceeds the safe joint limit")
        joints[raw_name] = position
    return joints


def pose_to_message(pose: Pose) -> dict:
    message = {
        "version": PROTOCOL_VERSION,
        "type": "pose",
        "name": pose.name,
        "duration": pose.duration,
        "joints": dict(pose.joints),
    }
    message_to_pose(message)
    return message


def velocity_to_message(
    command: VelocityCommand,
    *,
    gait_style: str | None = None,
    frequency_hz: float | None = None,
) -> dict:
    message = {
        "version": PROTOCOL_VERSION,
        "type": "walk",
        "vx": command.vx,
        "vy": command.vy,
        "vyaw": command.vyaw,
    }
    if gait_style is not None:
        message["gait_style"] = gait_style
    if frequency_hz is not None:
        message["frequency_hz"] = float(frequency_hz)
    validate_simulator_message(message)
    return message


def trajectory_to_message(skill) -> dict:
    message = {
        "version": PROTOCOL_VERSION,
        "type": "trajectory",
        "name": skill.id,
        "keyframes": [
            {"t": frame.t, "joints": dict(frame.joints)} for frame in skill.keyframes
        ],
    }
    validate_simulator_message(message)
    return message


def message_to_pose(message: dict) -> Pose:
    if message.get("type") != "pose":
        raise ValueError(f"unsupported message type: {message.get('type')!r}")
    name = message.get("name", "unnamed")
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise TypeError("pose name must be a non-empty string")
    duration = _finite_float(message.get("duration", 1.0), "pose duration")
    if not 0.0 < duration <= _LIMITS.max_pose_duration:
        raise ValueError("pose duration is outside the safe range")
    return Pose(
        name=name.strip(),
        joints=_safe_joints(message.get("joints"), "pose joints"),
        duration=duration,
    )


def message_to_velocity(message: dict) -> VelocityCommand:
    if message.get("type") != "walk":
        raise ValueError(f"unsupported message type: {message.get('type')!r}")
    command = VelocityCommand(
        vx=_finite_float(message.get("vx", 0.0), "walk vx"),
        vy=_finite_float(message.get("vy", 0.0), "walk vy"),
        vyaw=_finite_float(message.get("vyaw", 0.0), "walk vyaw"),
    )
    if abs(command.vx) > _LIMITS.max_vx:
        raise ValueError("walk vx exceeds the safe limit")
    if abs(command.vy) > _LIMITS.max_vy:
        raise ValueError("walk vy exceeds the safe limit")
    if abs(command.vyaw) > _LIMITS.max_vyaw:
        raise ValueError("walk vyaw exceeds the safe limit")
    return command


def validate_simulator_message(message: dict) -> None:
    """Validate every untrusted command at the simulator transport boundary."""

    if not isinstance(message, dict):
        raise TypeError("simulator message must be a JSON object")
    version = message.get("version", PROTOCOL_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError("protocol version must be an integer")
    if version != PROTOCOL_VERSION:
        raise ValueError(f"unsupported protocol version: {version}")
    kind = message.get("type")
    if not isinstance(kind, str):
        raise TypeError("message requires a string type")
    if kind == "pose":
        message_to_pose(message)
        return
    if kind == "walk":
        message_to_velocity(message)
        style = message.get("gait_style")
        if style is not None and style not in ALLOWED_GAIT_STYLES:
            raise ValueError(f"unsupported gait style: {style!r}")
        frequency = message.get("frequency_hz")
        if frequency is not None:
            frequency = _finite_float(frequency, "gait frequency_hz")
            if not 0.2 <= frequency <= 5.0:
                raise ValueError("gait frequency_hz is outside the safe range")
        return
    if kind == "trajectory":
        name = message.get("name", "unnamed")
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise TypeError("trajectory name must be a non-empty string")
        frames = message.get("keyframes")
        if not isinstance(frames, list) or not 2 <= len(frames) <= MAX_TRAJECTORY_FRAMES:
            raise ValueError("trajectory requires between 2 and 500 keyframes")
        previous = -1.0
        for index, frame in enumerate(frames):
            if not isinstance(frame, dict):
                raise TypeError("trajectory keyframes must be objects")
            timestamp = _finite_float(frame.get("t"), f"keyframes[{index}].t")
            if timestamp < 0.0 or timestamp > MAX_TRAJECTORY_SECONDS:
                raise ValueError("trajectory timestamp is outside the safe range")
            if timestamp <= previous:
                raise ValueError("trajectory timestamps must be strictly increasing")
            _safe_joints(frame.get("joints"), f"keyframes[{index}].joints")
            previous = timestamp
        return
    if kind == "owner_move":
        dx = _finite_float(message.get("dx", 0.0), "owner dx")
        dy = _finite_float(message.get("dy", 0.0), "owner dy")
        if abs(dx) > 1.0 or abs(dy) > 1.0:
            raise ValueError("owner movement is limited to one meter per request")
        return
    if kind == "owner_visibility":
        if not isinstance(message.get("visible"), bool):
            raise TypeError("owner visibility must be a boolean")
        return
    if kind in {"stop", "emergency_stop", "clear_emergency_stop", "status"}:
        return
    raise ValueError(f"unsupported simulator message type: {kind!r}")


def send_message(message: dict, socket_path: Path | str = DEFAULT_SOCKET) -> None:
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise TypeError("simulator message requires a string type")
    message = dict(message)
    message.setdefault("version", PROTOCOL_VERSION)
    validate_simulator_message(message)
    path = Path(socket_path)
    payload = (json.dumps(message, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("simulator message is too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2.0)
        client.connect(str(path))
        client.sendall(payload)


def publish_pose(pose: Pose, socket_path: Path | str = DEFAULT_SOCKET) -> None:
    send_message(pose_to_message(pose), socket_path)


def publish_velocity(
    command: VelocityCommand,
    socket_path: Path | str = DEFAULT_SOCKET,
    *,
    gait_style: str | None = None,
    frequency_hz: float | None = None,
) -> None:
    send_message(
        velocity_to_message(
            command, gait_style=gait_style, frequency_hz=frequency_hz
        ),
        socket_path,
    )


def publish_trajectory(skill, socket_path: Path | str = DEFAULT_SOCKET) -> None:
    send_message(trajectory_to_message(skill), socket_path)


def publish_stop(socket_path: Path | str = DEFAULT_SOCKET) -> None:
    send_message({"version": PROTOCOL_VERSION, "type": "stop"}, socket_path)


def publish_emergency_stop(socket_path: Path | str = DEFAULT_SOCKET) -> None:
    send_message({"version": PROTOCOL_VERSION, "type": "emergency_stop"}, socket_path)


def publish_clear_emergency_stop(socket_path: Path | str = DEFAULT_SOCKET) -> None:
    send_message({"version": PROTOCOL_VERSION, "type": "clear_emergency_stop"}, socket_path)


def request_status(
    socket_path: Path | str = DEFAULT_SOCKET,
    *,
    timeout: float = 1.0,
) -> dict:
    """Request one timestamped observation from a running simulator."""
    path = Path(socket_path)
    payload = json.dumps({"version": PROTOCOL_VERSION, "type": "status"}).encode() + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_MESSAGE_BYTES:
                raise ValueError("simulator status response is too large")
            chunks.append(chunk)
    if not chunks:
        raise RuntimeError("simulator returned an empty status response")
    response = json.loads(b"".join(chunks).decode("utf-8").splitlines()[0])
    if not isinstance(response, dict):
        raise TypeError("simulator status response must be an object")
    if response.get("type") == "error":
        raise RuntimeError(str(response.get("error", "simulator status failed")))
    validate_simulator_message(
        {"version": response.get("version"), "type": response.get("type")}
    )
    if response.get("type") != "status":
        raise TypeError("simulator status response has the wrong type")
    return response


class PoseSocketServer:
    """Accept newline-delimited JSON pose/stop messages over a Unix socket."""

    def __init__(
        self,
        socket_path: Path | str = DEFAULT_SOCKET,
        state_provider: Callable[[], dict] | None = None,
    ):
        self.socket_path = Path(socket_path)
        self.state_provider = state_provider
        self._server: socket.socket | None = None

    def start(self) -> None:
        self._unlink_existing_socket()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        server.listen(8)
        server.setblocking(False)
        self._server = server

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        self._unlink_existing_socket(missing_ok=True)

    def poll(self) -> list[dict]:
        if self._server is None:
            return []
        messages: list[dict] = []
        for _ in range(MAX_CLIENTS_PER_POLL):
            try:
                conn, _ = self._server.accept()
            except BlockingIOError:
                break
            except OSError:
                break
            with conn:
                conn.settimeout(0.005)
                chunks: list[bytes] = []
                size = 0
                try:
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_MESSAGE_BYTES:
                            raise ValueError("simulator message is too large")
                        chunks.append(chunk)
                        if b"\n" in chunk:
                            break
                except (OSError, TimeoutError, ValueError):
                    pass
                raw = b"".join(chunks).decode("utf-8", errors="replace")
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        message = json.loads(line)
                        if not isinstance(message, dict):
                            raise TypeError("message must be a JSON object")
                        validate_simulator_message(message)
                        if message["type"] == "status":
                            if self.state_provider is None:
                                raise RuntimeError("simulator telemetry is unavailable")
                            response = dict(self.state_provider())
                            response.setdefault("version", PROTOCOL_VERSION)
                            response.setdefault("type", "status")
                            try:
                                conn.sendall(
                                    (json.dumps(response, allow_nan=False) + "\n").encode()
                                )
                            except OSError:
                                pass
                        else:
                            messages.append(message)
                    except (json.JSONDecodeError, TypeError, ValueError, RuntimeError) as error:
                        try:
                            conn.sendall(
                                (
                                    json.dumps(
                                        {
                                            "version": PROTOCOL_VERSION,
                                            "type": "error",
                                            "error": str(error),
                                        }
                                    )
                                    + "\n"
                                ).encode()
                            )
                        except OSError:
                            pass
        return messages

    def _unlink_existing_socket(self, *, missing_ok: bool = False) -> None:
        try:
            mode = os.lstat(self.socket_path).st_mode
        except FileNotFoundError:
            if missing_ok:
                return
            return
        if not stat.S_ISSOCK(mode):
            raise FileExistsError(
                f"refusing to replace non-socket path: {self.socket_path}"
            )
        self.socket_path.unlink()
