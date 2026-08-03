# ruff: noqa: I001
"""Python-3.6-compatible, evaluator-only Habitat 2020 PointNav bridge.

This file intentionally avoids modern syntax and imports no Parcel modules.
The archived challenge process can load it under Python 3.6 and exchange a
small JSON-lines protocol with Parcel running in a modern Python sidecar.
Only the official RGB-D/PointGoal observations and bridge-owned action history
cross that boundary.
"""

import json
import math
import subprocess

import numpy as np


PROTOCOL_VERSION = 1
OFFICIAL_ACTIONS = ("STOP", "MOVE_FORWARD", "TURN_LEFT", "TURN_RIGHT")


class BridgeProtocolError(ValueError):
    """Raised when a sensor frame or sidecar message violates the contract."""


def _finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise BridgeProtocolError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise BridgeProtocolError(f"{name} must be finite")
    return result


def pointgoal_polar_to_local(pointgoal):
    """Convert Habitat's static ``[rho, left-positive phi]`` to Parcel XY."""

    values = np.asarray(pointgoal, dtype=np.float64).reshape(-1)
    if values.size != 2:
        raise BridgeProtocolError("pointgoal must contain exactly rho and phi")
    rho = _finite_number(values[0], "pointgoal rho")
    phi = _finite_number(values[1], "pointgoal phi")
    if rho < 0.0:
        raise BridgeProtocolError("pointgoal rho must be non-negative")
    return (rho * math.cos(phi), rho * math.sin(phi))


def depth_to_planar_scan(
    depth,
    hfov_deg=70.0,
    min_depth_m=0.1,
    max_depth_m=10.0,
    normalized=True,
    bins=181,
    row_fraction=0.5,
):
    """Project the camera horizon onto a uniform, left-positive planar scan.

    Habitat depth is optical-axis depth.  Each selected sample is therefore
    divided by ``cos(bearing)`` to obtain planar radial range.  Saturated depth
    is encoded as JSON ``null`` (a no-return ray), never as a phantom wall.
    """

    array = np.asarray(depth)
    if array.ndim == 3 and array.shape[2] == 1:
        array = array[:, :, 0]
    if array.ndim != 2 or array.shape[0] < 2 or array.shape[1] < 2:
        raise BridgeProtocolError("depth must have shape HxW or HxWx1")
    if not np.issubdtype(array.dtype, np.number):
        raise BridgeProtocolError("depth must be numeric")
    hfov = _finite_number(hfov_deg, "hfov_deg")
    minimum = _finite_number(min_depth_m, "min_depth_m")
    maximum = _finite_number(max_depth_m, "max_depth_m")
    fraction = _finite_number(row_fraction, "row_fraction")
    if not 0.0 < hfov < 180.0:
        raise BridgeProtocolError("hfov_deg must be inside (0, 180)")
    if minimum < 0.0 or maximum <= minimum:
        raise BridgeProtocolError("depth range must satisfy 0 <= min < max")
    if isinstance(bins, bool) or not isinstance(bins, (int, np.integer)) or not 3 <= bins <= 4096:
        raise BridgeProtocolError("bins must be an integer in [3, 4096]")
    if not 0.0 <= fraction <= 1.0:
        raise BridgeProtocolError("row_fraction must be in [0, 1]")

    height, width = array.shape
    row = round((height - 1) * fraction)
    half_fov = math.radians(hfov) / 2.0
    angles = np.linspace(-half_fov, half_fov, int(bins), dtype=np.float64)
    center_x = (width - 1) / 2.0
    focal_x = center_x / math.tan(half_fov)
    # Image x increases right while Parcel bearing increases left.
    pixels = np.rint(center_x - focal_x * np.tan(angles)).astype(np.int64)
    pixels = np.clip(pixels, 0, width - 1)
    optical_depth = array[row, pixels].astype(np.float64)

    if normalized:
        finite_values = optical_depth[np.isfinite(optical_depth)]
        if finite_values.size and (
            float(np.min(finite_values)) < -1e-6
            or float(np.max(finite_values)) > 1.0 + 1e-6
        ):
            raise BridgeProtocolError("normalized depth values must be in [0, 1]")
        optical_depth = minimum + optical_depth * (maximum - minimum)

    radial = optical_depth / np.cos(angles)
    no_return = ~np.isfinite(optical_depth) | (optical_depth >= maximum - 1e-6)
    invalid = optical_depth < minimum - 1e-6
    no_return |= invalid
    ranges = [None if no_return[index] else float(radial[index]) for index in range(int(bins))]
    radial_max = maximum / math.cos(half_fov)
    return {
        "ranges_m": ranges,
        "angle_min_rad": float(angles[0]),
        "angle_increment_rad": float(angles[1] - angles[0]),
        "range_min_m": minimum,
        "range_max_m": radial_max,
        "source": "habitat_depth_center_horizon",
    }


def encode_message(message):
    if not isinstance(message, dict):
        raise BridgeProtocolError("protocol message must be an object")
    try:
        return json.dumps(message, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    except (TypeError, ValueError) as exc:
        raise BridgeProtocolError(f"protocol message is not strict JSON: {exc}")


def decode_message(line):
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    if not isinstance(line, str) or not line.strip():
        raise BridgeProtocolError("protocol line must be non-empty UTF-8 JSON")
    try:
        message = json.loads(line)
    except (TypeError, ValueError) as exc:
        raise BridgeProtocolError(f"invalid JSON response: {exc}")
    if not isinstance(message, dict):
        raise BridgeProtocolError("protocol message must decode to an object")
    if message.get("schema_version") != PROTOCOL_VERSION:
        raise BridgeProtocolError("unsupported protocol schema_version")
    return message


class NominalActionOdometry:
    """Dead reckoning from issued actions; never reads simulator state."""

    def __init__(self, forward_step_m=0.25, turn_angle_deg=30.0):
        self.forward_step_m = _finite_number(forward_step_m, "forward_step_m")
        self.turn_angle_rad = math.radians(_finite_number(turn_angle_deg, "turn_angle_deg"))
        if self.forward_step_m <= 0.0 or self.turn_angle_rad <= 0.0:
            raise BridgeProtocolError("odometry step sizes must be positive")
        self.reset()

    def reset(self):
        self.x_m = 0.0
        self.y_m = 0.0
        self.heading_rad = 0.0

    def integrate(self, action):
        if action not in OFFICIAL_ACTIONS:
            raise BridgeProtocolError(f"unsupported Habitat action: {action}")
        if action == "MOVE_FORWARD":
            self.x_m += math.cos(self.heading_rad) * self.forward_step_m
            self.y_m += math.sin(self.heading_rad) * self.forward_step_m
        elif action == "TURN_LEFT":
            self.heading_rad += self.turn_angle_rad
        elif action == "TURN_RIGHT":
            self.heading_rad -= self.turn_angle_rad
        self.heading_rad = (self.heading_rad + math.pi) % (2.0 * math.pi) - math.pi

    def as_message(self):
        return {"x_m": self.x_m, "y_m": self.y_m, "heading_rad": self.heading_rad}


class SubprocessJsonTransport:
    """Synchronous local transport suitable for one self-contained container."""

    def __init__(self, command):
        if not isinstance(command, (list, tuple)) or not command:
            raise BridgeProtocolError("sidecar command must be a non-empty argument list")
        self._process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            universal_newlines=True,
            bufsize=1,
        )

    def request(self, message):
        if self._process.poll() is not None:
            raise BridgeProtocolError("Parcel sidecar exited before request")
        self._process.stdin.write(encode_message(message))
        self._process.stdin.flush()
        response = self._process.stdout.readline()
        if not response:
            raise BridgeProtocolError("Parcel sidecar closed stdout")
        return decode_message(response)

    def close(self):
        if self._process.poll() is None:
            try:
                self.request({"schema_version": PROTOCOL_VERSION, "op": "close"})
            except BridgeProtocolError:
                pass
            self._process.terminate()
            self._process.wait()


class PointNav2020Bridge:
    """Stateful adapter from official observations to the Parcel sidecar."""

    def __init__(
        self,
        transport,
        arrival_radius_m=0.30,
        scan_bins=181,
        turn_priority_rate=0.20,
        forward_deadband=1e-4,
    ):
        if transport is None or not hasattr(transport, "request"):
            raise BridgeProtocolError("transport must provide request(message)")
        self.transport = transport
        self.arrival_radius_m = _finite_number(arrival_radius_m, "arrival_radius_m")
        if not 0.0 < self.arrival_radius_m < 0.36:
            raise BridgeProtocolError("arrival radius must be inside Habitat's 0.36 m region")
        self.scan_bins = int(scan_bins)
        if not 3 <= self.scan_bins <= 4096:
            raise BridgeProtocolError("scan_bins must be in [3, 4096]")
        self.turn_priority_rate = _finite_number(turn_priority_rate, "turn_priority_rate")
        self.forward_deadband = _finite_number(forward_deadband, "forward_deadband")
        self.odometry = NominalActionOdometry()
        self._episode_id = 0
        self._step_id = 0
        self._started = False
        self._last_action = None
        self._idle_turn_left = True

    def reset(self):
        self._episode_id += 1
        self._step_id = 0
        self._started = False
        self._last_action = None
        self._idle_turn_left = True
        self.odometry.reset()

    def act(self, observations):
        if not isinstance(observations, dict):
            raise BridgeProtocolError("observations must be a dictionary")
        if self._last_action is not None:
            self.odometry.integrate(self._last_action)
        if not self._started:
            if "pointgoal" not in observations:
                raise BridgeProtocolError("first observation is missing pointgoal")
            goal_x, goal_y = pointgoal_polar_to_local(observations["pointgoal"])
            response = self.transport.request(
                {
                    "schema_version": PROTOCOL_VERSION,
                    "op": "start",
                    "episode_id": self._episode_id,
                    "goal": {"x_m": goal_x, "y_m": goal_y},
                    "arrival_radius_m": self.arrival_radius_m,
                }
            )
            self._validate_response(response, "started")
            self._started = True
        if "depth" not in observations:
            raise BridgeProtocolError("observation is missing depth")
        scan = depth_to_planar_scan(observations["depth"], bins=self.scan_bins)
        response = self.transport.request(
            {
                "schema_version": PROTOCOL_VERSION,
                "op": "act",
                "episode_id": self._episode_id,
                "step_id": self._step_id,
                "pose": self.odometry.as_message(),
                "scan": scan,
                "sensor_contract": {
                    "depth_present": True,
                    "rgb_present": "rgb" in observations,
                    "gps_compass_present": False,
                },
            }
        )
        self._validate_response(response, "command")
        if response.get("step_id") != self._step_id:
            raise BridgeProtocolError("sidecar response step_id mismatch")
        action = self._command_to_action(response)
        self._last_action = action
        self._step_id += 1
        return {"action": action}

    def _validate_response(self, response, expected_op):
        if not isinstance(response, dict):
            raise BridgeProtocolError("sidecar response must be an object")
        if response.get("schema_version") != PROTOCOL_VERSION:
            raise BridgeProtocolError("sidecar response schema mismatch")
        if response.get("op") == "error":
            raise BridgeProtocolError(f"sidecar rejected request: {response.get('error')}")
        if response.get("op") != expected_op:
            raise BridgeProtocolError(f"expected sidecar op {expected_op}")
        if response.get("episode_id") != self._episode_id:
            raise BridgeProtocolError("sidecar response episode_id mismatch")

    def _command_to_action(self, response):
        stop = response.get("stop")
        if not isinstance(stop, bool):
            raise BridgeProtocolError("command stop must be boolean")
        vx = _finite_number(response.get("vx"), "command vx")
        vy = _finite_number(response.get("vy"), "command vy")
        vyaw = _finite_number(response.get("vyaw"), "command vyaw")
        if abs(vy) > 1e-6:
            raise BridgeProtocolError("Habitat 2020 has no lateral action; refusing to hide vy")
        if vx < -self.forward_deadband:
            raise BridgeProtocolError("Habitat 2020 has no reverse action; refusing to hide vx")
        if stop:
            return "STOP"
        if abs(vyaw) >= self.turn_priority_rate:
            return "TURN_LEFT" if vyaw > 0.0 else "TURN_RIGHT"
        if vx > self.forward_deadband:
            return "MOVE_FORWARD"
        if abs(vyaw) > 1e-9:
            return "TURN_LEFT" if vyaw > 0.0 else "TURN_RIGHT"
        # The challenge has no no-op. Alternate rotations for a non-terminal
        # zero command instead of issuing STOP and falsely ending the episode.
        action = "TURN_LEFT" if self._idle_turn_left else "TURN_RIGHT"
        self._idle_turn_left = not self._idle_turn_left
        return action

    def close(self):
        close = getattr(self.transport, "close", None)
        if close is not None:
            close()


try:
    import habitat

    _HabitatAgentBase = habitat.Agent
except ImportError:
    _HabitatAgentBase = object


class ParcelHabitat2020Agent(_HabitatAgentBase):
    """Minimal archived-challenge Agent wrapper around :class:`PointNav2020Bridge`."""

    def __init__(self, transport):
        self.bridge = PointNav2020Bridge(transport)

    def reset(self):
        self.bridge.reset()

    def act(self, observations):
        return self.bridge.act(observations)

    def close(self):
        self.bridge.close()
