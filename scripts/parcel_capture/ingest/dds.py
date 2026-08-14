"""Read-only DDS ingest for the fifteen Go2 topics — card PS-G.

``rclpy`` and nothing else
--------------------------
There are three ways to reach these topics: ``rclpy`` over the ``unitree_ros2``
overlay, a bare CycloneDDS reader, or the vendor ``unitree_sdk2py``. This
adapter uses the first and **refuses the third by never naming it in an import**.
The vendor SDK ships the motion clients in the same package as its subscriber;
importing it to read a sensor puts a command surface one attribute away, and the
absence of that package from ``.parcel/`` is the strongest motion guarantee the
project has. What we lose is nothing: ``unitree_ros2`` carries every topic here.

Naming, and the failure that is silent by construction
------------------------------------------------------
``rclpy`` applies ROS 2's ``rt/`` mangling itself, so a subscriber built here
must be given the **ROS** name; a raw-DDS reader must be given the mangled one.
Get it backwards and you receive zero messages and no error — indistinguishable
from a robot that is not publishing. :func:`subscribe_name` has no default
argument for exactly this reason, and :func:`ros_subscribe_name` below is the
only way this module produces a topic string.

What the decoders are for
-------------------------
The wire bytes go to the rosbag2 primary recording. These decoders exist to
produce the typed physical summaries PS-J's plausibility gate rules on, and they
carry every message-shape correction from ``RISK_ASSESSMENT.md``:

* ``MotorState[20]`` is a fixed union array and **a Go2 has 12 actuated
  joints**. Indices 12-19 are padding; decoding all twenty would report eight
  dead channels as sensors.
* ``BmsState`` has **no voltage field**. Pack voltage is ``LowState.power_v``
  or ``sum(cell_vol[15])``, and ``cell_vol`` is **millivolts** — PS-J's
  ``PowerSample`` is documented in volts and refuses to guess units, so the
  conversion happens here and both estimates are recorded so they can disagree.
* There are **two** foot-force arrays, ``foot_force[4]`` and
  ``foot_force_est[4]``, both ``int16`` raw counts from an air-pressure contact
  proxy with no published units, gain or offset. Their difference is free
  evidence about which one is sensed, so both are recorded.
* ``LowState`` has **no timestamp**, only ``tick``, a ``uint32`` millisecond
  counter that wraps. :class:`~scripts.parcel_capture.ingest.base.IngestFrame`
  refuses a source timestamp on it; ``tick`` is recorded as a counter, in the
  summary, where nobody can mistake it for a clock.
* ``range_obstacle[4]``, ``power_v``/``power_a``, ``wireless_remote[40]``,
  ``fan_frequency[4]`` and ``temperature_ntc1/2`` are recorded because they are
  free, they are the only proximity/power/annotation evidence of their kind, and
  a second session is what it costs to go back for them.

Every field is read through
:func:`~scripts.parcel_capture.ingest.base.read_field`, so a documentation error
about *our* unit yields a summary with a named missing field rather than a
crashed probe forty minutes into a battery.
"""

from __future__ import annotations

import importlib
import math
import struct
from collections.abc import Iterator, Sequence
from typing import Any, ClassVar

from parcel_robot.capture import Channel, Transport
from parcel_robot.capture.channels import SourceClock, WireNaming, subscribe_name

from ..preflight import (
    AbsenceReason,
    FootForceSample,
    ImuSample,
    PhysicalSample,
    PointCloudSample,
    PowerSample,
)
from .base import (
    ABSENT,
    IngestAdapter,
    IngestContractError,
    IngestFrame,
    IngestRefusedError,
    IngestUnavailableError,
    PayloadKind,
    ReadOnlyHandle,
    Requirement,
    now_ns,
    present,
    read_field,
    sealed_call,
    summary_payload,
)

#: ``MotorState[20]`` is a fixed union array shared across Unitree platforms.
MOTOR_STATE_ARRAY_LEN = 20

#: A Go2 has twelve actuated joints. Indices 12-19 are padding, and reading
#: them as sensors is how a report grows eight channels that never existed.
GO2_ACTUATED_JOINTS = 12

#: ``BmsState.cell_vol`` is a 15-element millivolt array.
BMS_CELL_COUNT = 15

#: ``LowState.wireless_remote`` is a 40-byte gap-free copy of the controller at
#: the LowState rate. A free, time-aligned annotation track.
WIRELESS_REMOTE_BYTES = 40

#: ``tick`` is ``uint32`` milliseconds and wraps every ~49.7 days. It orders
#: messages within one unwrapped span and is not a clock.
TICK_MODULUS = 1 << 32

#: PointCloud2 datatype codes we can read a range from. Anything else is
#: recorded as an unreadable layout rather than decoded on a guess.
_PF_FLOAT32 = 7
_PF_FLOAT64 = 8

#: At most this many points are sampled for the range statistic. Preflight does
#: not hold a cloud, and a 10 Hz L2 cloud is ~100k points.
MAX_RANGE_SAMPLES = 512


def ros_subscribe_name(entry: Channel) -> str:
    """The absolute ROS name an ``rclpy`` subscriber must be given.

    Refuses any non-DDS channel and never emits the ``rt/``-mangled form: this
    module is the ROS side of the naming split, and handing it the wire name is
    the mistake that produces silence.
    """

    if entry.transport is not Transport.DDS:
        raise IngestRefusedError(
            f"{entry.channel_id}: transport is {entry.transport.value}, which is not "
            f"addressed by a ROS topic name"
        )
    name = subscribe_name(entry.channel_id, WireNaming.ROS2)
    return name if name.startswith("/") else "/" + name


def ros_message_type(entry: Channel) -> str:
    """``unitree_go/msg/dds_/LowState_`` -> ``unitree_go/msg/LowState``.

    The matrix records the IDL name that appears on the DDS wire, which is the
    name a raw reader needs. ``rclpy`` wants the ROS interface name, and the two
    differ by a ``dds_`` segment and a trailing underscore. Deriving it is safe;
    guessing at it is not, so a type that does not match the pattern refuses.
    """

    declared = entry.message_type
    parts = declared.split("/")
    if len(parts) == 4 and parts[2] == "dds_" and parts[3].endswith("_"):
        return f"{parts[0]}/{parts[1]}/{parts[3][:-1]}"
    if len(parts) == 3:
        return declared
    raise IngestRefusedError(
        f"{entry.channel_id}: message_type {declared!r} is not a ROS interface name; "
        f"this adapter will not guess at a type it has to import"
    )


def _message_class(entry: Channel) -> Any:
    """Import the generated message class for a channel. Never a vendor client."""

    package, kind, name = ros_message_type(entry).split("/")
    try:
        module = importlib.import_module(f"{package}.{kind}")
    except ImportError as error:
        raise IngestUnavailableError(
            AbsenceReason.DEPENDENCY_MISSING,
            f"{entry.channel_id}: message package {package}.{kind} is not importable "
            f"({error})",
            f"source the Orin's Humble overlay that provides {package} "
            f"(unitree_ros2 for the unitree_go interfaces); never install it into .parcel/",
        ) from error
    found = read_field(module, name)
    if found is ABSENT:
        raise IngestUnavailableError(
            AbsenceReason.UNPARSEABLE,
            f"{entry.channel_id}: {package}.{kind} has no interface named {name}",
            f"check the interface version: `ros2 interface show {package}/{kind}/{name}`",
        )
    return found


# ---------------------------------------------------------------------------
# Decoders. Pure functions over a duck-typed message; testable with no ROS.
# ---------------------------------------------------------------------------


def _iterable(value: Any) -> bool:
    """Sequence-like and not a string. A string iterates into characters, which
    is how a text field becomes a plausible-looking array of numbers."""

    return not isinstance(value, (str, bytes, bytearray)) and hasattr(value, "__iter__")


def _floats(value: Any, *, limit: int | None = None) -> list[float]:
    if not _iterable(value):
        return []
    items = list(value)
    if limit is not None:
        items = items[:limit]
    out: list[float] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return []
        out.append(float(item))
    return out


def _ints(value: Any, *, limit: int | None = None) -> list[int]:
    if not _iterable(value):
        return []
    items = list(value)
    if limit is not None:
        items = items[:limit]
    out: list[int] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return []
        out.append(int(item))
    return out


def _vec3(value: Any) -> tuple[float, float, float] | None:
    numbers = _floats(value, limit=4)
    if len(numbers) < 3:
        return None
    return (numbers[0], numbers[1], numbers[2])


def _xyz(message: Any) -> tuple[float, float, float] | None:
    parts = [read_field(message, axis) for axis in ("x", "y", "z")]
    if any(not present(part) for part in parts):
        return None
    return _vec3(parts)


def timespec_ns(stamp: Any) -> int | None:
    """``TimeSpec``/``builtin_interfaces/Time`` -> ns, or ``None``.

    Fail closed on anything that is not two integral fields: a partially decoded
    clock is worse than an absent one, because the absent one is visible.
    """

    if not present(stamp):
        return None
    sec = read_field(stamp, "sec")
    nanosec = read_field(stamp, "nanosec")
    if not present(nanosec):
        nanosec = read_field(stamp, "nsec")
    if not present(sec) or not present(nanosec):
        return None
    if isinstance(sec, bool) or isinstance(nanosec, bool):
        return None
    if not isinstance(sec, (int, float)) or not isinstance(nanosec, (int, float)):
        return None
    if not math.isfinite(float(sec)) or not math.isfinite(float(nanosec)):
        return None
    return int(sec) * 1_000_000_000 + int(nanosec)


def header_stamp_ns(message: Any) -> int | None:
    header = read_field(message, "header")
    if not present(header):
        return None
    return timespec_ns(read_field(header, "stamp"))


def _imu_from_state(imu_state: Any) -> tuple[ImuSample | None, dict[str, Any]]:
    """``unitree_go/msg/IMUState`` -> an :class:`ImuSample` plus its summary."""

    if not present(imu_state):
        return None, {"present": False}
    accel = _vec3(read_field(imu_state, "accelerometer"))
    gyro = _vec3(read_field(imu_state, "gyroscope"))
    summary: dict[str, Any] = {
        "present": True,
        "accelerometer_mps2": list(accel) if accel else None,
        "gyroscope_rps": list(gyro) if gyro else None,
        "rpy_rad": _floats(read_field(imu_state, "rpy"), limit=3) or None,
        "quaternion": _floats(read_field(imu_state, "quaternion"), limit=4) or None,
        "temperature_c": _optional_number(read_field(imu_state, "temperature")),
    }
    if accel is None and gyro is None:
        return None, summary
    return ImuSample(accel_mps2=accel, gyro_rps=gyro), summary


def _optional_number(value: Any) -> float | None:
    if not present(value) or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def decode_low_state(message: Any) -> tuple[tuple[PhysicalSample, ...], dict[str, Any]]:
    """``unitree_go/msg/LowState`` — the 500 Hz stream, with every correction.

    Returns the physical samples PS-J rules on and the JSON summary that becomes
    the frame payload. ``tick`` appears in the summary as ``tick_ms`` with its
    modulus stated; it never becomes a timestamp.
    """

    samples: list[PhysicalSample] = []
    findings: list[str] = []
    missing: list[str] = []

    imu_sample, imu_summary = _imu_from_state(read_field(message, "imu_state"))
    if imu_sample is not None:
        samples.append(imu_sample)
    else:
        missing.append("imu_state")

    motors_raw = read_field(message, "motor_state")
    motors: list[dict[str, Any]] = []
    padding_nonzero: list[int] = []
    if present(motors_raw) and isinstance(motors_raw, (list, tuple)):
        declared = len(motors_raw)
        if declared != MOTOR_STATE_ARRAY_LEN:
            findings.append(
                f"motor_state has {declared} entries, not the documented "
                f"{MOTOR_STATE_ARRAY_LEN}"
            )
        for index, motor in enumerate(motors_raw[:GO2_ACTUATED_JOINTS]):
            motors.append(
                {
                    "index": index,
                    "q": _optional_number(read_field(motor, "q")),
                    "dq": _optional_number(read_field(motor, "dq")),
                    "ddq": _optional_number(read_field(motor, "ddq")),
                    "tau_est": _optional_number(read_field(motor, "tau_est")),
                    "q_raw": _optional_number(read_field(motor, "q_raw")),
                    "dq_raw": _optional_number(read_field(motor, "dq_raw")),
                    "ddq_raw": _optional_number(read_field(motor, "ddq_raw")),
                    "temperature_c": _optional_number(read_field(motor, "temperature")),
                    "lost": _optional_number(read_field(motor, "lost")),
                }
            )
        for index, motor in enumerate(motors_raw[GO2_ACTUATED_JOINTS:], GO2_ACTUATED_JOINTS):
            value = _optional_number(read_field(motor, "q"))
            if value not in (None, 0.0):
                padding_nonzero.append(index)
        if padding_nonzero:
            findings.append(
                f"motor_state padding indices {padding_nonzero} carry non-zero q; a Go2 has "
                f"{GO2_ACTUATED_JOINTS} actuated joints, so this is a finding about the "
                f"message definition, not eight extra sensors"
            )
    else:
        missing.append("motor_state")

    foot_force = _ints(read_field(message, "foot_force"), limit=4)
    foot_force_est = _ints(read_field(message, "foot_force_est"), limit=4)
    if len(foot_force) == 4:
        samples.append(
            FootForceSample(
                counts=tuple(foot_force),
                counts_est=tuple(foot_force_est) if len(foot_force_est) == 4 else None,
            )
        )
    else:
        missing.append("foot_force")
    if len(foot_force_est) != 4:
        missing.append("foot_force_est")

    power_v = _optional_number(read_field(message, "power_v"))
    power_a = _optional_number(read_field(message, "power_a"))
    bms = read_field(message, "bms_state")
    cell_mv = _ints(read_field(bms, "cell_vol"), limit=BMS_CELL_COUNT) if present(bms) else []
    cell_volts = tuple(value / 1000.0 for value in cell_mv)
    cell_sum_v = math.fsum(cell_volts) if cell_volts else None
    if power_v is not None:
        samples.append(PowerSample(power_v=power_v, cell_volts=cell_volts, power_a=power_a))
    elif cell_sum_v is not None:
        # BmsState carries no voltage field. The cell sum is the only other
        # estimate, and using it is recorded as a substitution, never silent.
        samples.append(PowerSample(power_v=cell_sum_v, cell_volts=cell_volts, power_a=power_a))
        findings.append(
            "power_v is absent; pack voltage was taken as sum(cell_vol)/1000 — BmsState "
            "itself has no voltage field"
        )
    else:
        missing.append("power_v")

    remote = _ints(read_field(message, "wireless_remote"), limit=WIRELESS_REMOTE_BYTES)
    if len(remote) != WIRELESS_REMOTE_BYTES:
        missing.append("wireless_remote")

    tick = read_field(message, "tick")
    summary: dict[str, Any] = {
        "message": "unitree_go/msg/LowState",
        # Named tick_ms, never stamp: uint32 milliseconds, wraps at the stated
        # modulus. IngestFrame refuses a source timestamp on this channel.
        "tick_ms": int(tick) if present(tick) and not isinstance(tick, bool) else None,
        "tick_modulus": TICK_MODULUS,
        "imu_state": imu_summary,
        "actuated_joints": GO2_ACTUATED_JOINTS,
        "motor_state": motors,
        "motor_state_declared_len": len(motors_raw)
        if present(motors_raw) and isinstance(motors_raw, (list, tuple))
        else None,
        "motor_state_padding_nonzero": padding_nonzero,
        "foot_force": foot_force,
        "foot_force_est": foot_force_est,
        "power_v": power_v,
        "power_a": power_a,
        "bms_cell_volts": list(cell_volts),
        "bms_cell_sum_v": cell_sum_v,
        "bms_soc": _optional_number(read_field(bms, "soc")) if present(bms) else None,
        "bms_current": _optional_number(read_field(bms, "current")) if present(bms) else None,
        "fan_frequency": _ints(read_field(message, "fan_frequency"), limit=4),
        "temperature_ntc1": _optional_number(read_field(message, "temperature_ntc1")),
        "temperature_ntc2": _optional_number(read_field(message, "temperature_ntc2")),
        "wireless_remote": remote,
        "missing_fields": missing,
        "findings": findings,
    }
    return tuple(samples), summary


def decode_sport_mode_state(message: Any) -> tuple[tuple[PhysicalSample, ...], dict[str, Any]]:
    """``unitree_go/msg/SportModeState`` — the dog's only real clock anchor.

    ``stamp`` is a device ``TimeSpec`` and the only source-clock anchor the dog
    emits; ``range_obstacle[4]`` is the only non-LiDAR proximity sensing on it.
    Both are here because both are free and both cost a second session.
    """

    samples: list[PhysicalSample] = []
    missing: list[str] = []
    imu_sample, imu_summary = _imu_from_state(read_field(message, "imu_state"))
    if imu_sample is not None:
        samples.append(imu_sample)
    else:
        missing.append("imu_state")

    foot_force = _ints(read_field(message, "foot_force"), limit=4)
    if len(foot_force) == 4:
        samples.append(FootForceSample(counts=tuple(foot_force)))
    else:
        missing.append("foot_force")

    ranges = _floats(read_field(message, "range_obstacle"), limit=4)
    if len(ranges) != 4:
        missing.append("range_obstacle")

    summary = {
        "message": "unitree_go/msg/SportModeState",
        "stamp_ns": timespec_ns(read_field(message, "stamp")),
        "mode": _optional_number(read_field(message, "mode")),
        "gait_type": _optional_number(read_field(message, "gait_type")),
        "error_code": _optional_number(read_field(message, "error_code")),
        "body_height": _optional_number(read_field(message, "body_height")),
        "foot_raise_height": _optional_number(read_field(message, "foot_raise_height")),
        "position": _floats(read_field(message, "position"), limit=3),
        "velocity": _floats(read_field(message, "velocity"), limit=3),
        "yaw_speed": _optional_number(read_field(message, "yaw_speed")),
        "range_obstacle": ranges,
        "foot_force": foot_force,
        "foot_position_body": _floats(read_field(message, "foot_position_body"), limit=12),
        "foot_speed_body": _floats(read_field(message, "foot_speed_body"), limit=12),
        "imu_state": imu_summary,
        "missing_fields": missing,
        "findings": [],
    }
    return tuple(samples), summary


def decode_imu(message: Any) -> tuple[tuple[PhysicalSample, ...], dict[str, Any]]:
    """``sensor_msgs/msg/Imu``. Two independent field reports say ``utlidar/imu``
    can emit ~1e24 m/s^2, so the vector is passed through unclamped: PS-J's
    sensor-range rule exists to FAIL on it, and a decoder that sanitised it here
    would attest a broken IMU as healthy."""

    accel = _xyz(read_field(message, "linear_acceleration"))
    gyro = _xyz(read_field(message, "angular_velocity"))
    samples: list[PhysicalSample] = []
    missing: list[str] = []
    if accel is None:
        missing.append("linear_acceleration")
    if gyro is None:
        missing.append("angular_velocity")
    if accel is not None or gyro is not None:
        samples.append(ImuSample(accel_mps2=accel, gyro_rps=gyro))
    orientation = read_field(message, "orientation")
    quaternion = (
        [
            _optional_number(read_field(orientation, axis))
            for axis in ("x", "y", "z", "w")
        ]
        if present(orientation)
        else None
    )
    return tuple(samples), {
        "message": "sensor_msgs/msg/Imu",
        "stamp_ns": header_stamp_ns(message),
        "linear_acceleration_mps2": list(accel) if accel else None,
        "angular_velocity_rps": list(gyro) if gyro else None,
        "orientation_xyzw": quaternion,
        "missing_fields": missing,
        "findings": [],
    }


def _point_ranges(message: Any, fields: Sequence[Any]) -> tuple[tuple[float, ...], list[str]]:
    """Sample per-point ranges, or say why not. Never a guessed layout."""

    findings: list[str] = []
    by_name = {str(read_field(item, "name")): item for item in fields}
    if not {"x", "y", "z"} <= set(by_name):
        return (), ["cloud carries no x/y/z fields; no range statistic was computed"]
    datatypes = {str(read_field(by_name[axis], "datatype")) for axis in ("x", "y", "z")}
    if datatypes not in ({str(_PF_FLOAT32)}, {str(_PF_FLOAT64)}):
        return (), [
            (
                f"x/y/z datatypes {sorted(datatypes)} are not a single float layout; "
                f"ranges were not decoded rather than decoded on a guess"
            )
        ]
    width = 4 if datatypes == {str(_PF_FLOAT32)} else 8
    code = "<f" if width == 4 else "<d"
    point_step = read_field(message, "point_step")
    data = read_field(message, "data")
    if not present(point_step) or not present(data):
        return (), ["cloud carries no point_step/data; no range statistic was computed"]
    try:
        blob = bytes(data)
        step = int(point_step)
    except (TypeError, ValueError):
        return (), ["cloud data is not byte-addressable; no range statistic was computed"]
    if step <= 0:
        return (), [f"point_step is {step}; no range statistic was computed"]
    offsets = [int(read_field(by_name[axis], "offset") or 0) for axis in ("x", "y", "z")]
    total = len(blob) // step
    if total == 0:
        return (), ["cloud data holds no whole points"]
    stride = max(1, total // MAX_RANGE_SAMPLES)
    ranges: list[float] = []
    for index in range(0, total, stride):
        base = index * step
        try:
            xyz = [struct.unpack_from(code, blob, base + offset)[0] for offset in offsets]
        except struct.error:
            findings.append("cloud data ended inside a point; sampling stopped there")
            break
        ranges.append(math.sqrt(sum(value * value for value in xyz)))
        if len(ranges) >= MAX_RANGE_SAMPLES:
            break
    return tuple(ranges), findings


def decode_point_cloud2(message: Any) -> tuple[tuple[PhysicalSample, ...], dict[str, Any]]:
    """``sensor_msgs/msg/PointCloud2``.

    ``fields[]`` is recorded VERBATIM and in wire order. That list is the single
    most session-critical thing here that is unrecoverable after power-down: a
    cloud whose intensity/ring/time fields were never written down cannot be fed
    to a deskewing SLAM six months later.
    """

    raw_fields = read_field(message, "fields")
    fields = list(raw_fields) if present(raw_fields) and isinstance(raw_fields, (list, tuple)) else []
    names = tuple(str(read_field(item, "name")) for item in fields if present(read_field(item, "name")))
    height = read_field(message, "height")
    width = read_field(message, "width")
    count = 0
    if present(height) and present(width):
        count = int(height) * int(width)
    ranges, findings = _point_ranges(message, fields)
    nonfinite = sum(1 for value in ranges if not math.isfinite(value))
    sample = PointCloudSample(
        point_count=count,
        field_names=names,
        nonfinite_points=nonfinite,
        ranges_m=tuple(value for value in ranges if math.isfinite(value)),
    )
    return (sample,), {
        "message": "sensor_msgs/msg/PointCloud2",
        "stamp_ns": header_stamp_ns(message),
        "height": int(height) if present(height) else None,
        "width": int(width) if present(width) else None,
        "point_count": count,
        "fields": [
            {
                "name": str(read_field(item, "name")),
                "offset": _optional_number(read_field(item, "offset")),
                "datatype": _optional_number(read_field(item, "datatype")),
                "count": _optional_number(read_field(item, "count")),
            }
            for item in fields
        ],
        "point_step": _optional_number(read_field(message, "point_step")),
        "is_dense": bool(read_field(message, "is_dense")) if present(read_field(message, "is_dense")) else None,
        "range_samples": len(ranges),
        "nonfinite_range_samples": nonfinite,
        "missing_fields": [] if names else ["fields"],
        "findings": findings,
    }


def decode_generic(message: Any) -> tuple[tuple[PhysicalSample, ...], dict[str, Any]]:
    """No physical rule exists for this message; record arrival and say so.

    Returning no measurement is the honest outcome — PS-J turns an empty
    measurement set into UNKNOWN, never into PASS.
    """

    return (), {
        "message": "undecoded",
        "stamp_ns": header_stamp_ns(message),
        "note": (
            "no typed decoder is registered for this message; the rosbag2 primary "
            "recording holds the wire bytes and this frame records arrival only"
        ),
        "missing_fields": [],
        "findings": [],
    }


#: ROS interface name -> decoder. Keyed by the derived ROS name so one entry
#: serves both the ``lf/`` mirror and the full-rate topic.
DECODERS = {
    "unitree_go/msg/LowState": decode_low_state,
    "unitree_go/msg/SportModeState": decode_sport_mode_state,
    "sensor_msgs/msg/Imu": decode_imu,
    "sensor_msgs/msg/PointCloud2": decode_point_cloud2,
}


def decoder_for(entry: Channel) -> Any:
    return DECODERS.get(ros_message_type(entry), decode_generic)


def frame_from_message(entry: Channel, message: Any) -> IngestFrame:
    """Decode one received message into a frame. The fail-closed clock lives here.

    ``source_timestamp_ns`` is taken from the payload **only** where the matrix
    declares a real device time. Everywhere else it stays null, and
    :class:`IngestFrame` refuses it even if a future decoder tries.
    """

    samples, summary = decoder_for(entry)(message)
    monotonic_ns, realtime_ns = now_ns()
    stamp: int | None = None
    if entry.source_clock is SourceClock.DEVICE_TIMESPEC:
        stamp = summary.get("stamp_ns")
        if stamp is None:
            stamp = header_stamp_ns(message)
        if stamp is None:
            summary = dict(summary)
            summary["findings"] = [
                *summary.get("findings", ()),
                (
                    "the matrix declares a device timespec on this channel and the "
                    "message carried none; source_timestamp_ns is null, never substituted"
                ),
            ]
    return IngestFrame(
        channel_id=entry.channel_id,
        host_monotonic_ns=monotonic_ns,
        host_realtime_ns=realtime_ns,
        payload=summary_payload(summary),
        payload_kind=PayloadKind.DERIVED_SUMMARY,
        source_timestamp_ns=stamp,
        measurements=samples,
        detail=f"{entry.channel_id} via rclpy on {ros_subscribe_name(entry)}",
    )


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------

#: The only ``rclpy`` node attributes this adapter may reach. ``create_publisher``
#: is on the same object and is not here, which is the whole point.
_NODE_ALLOWLIST = ("create_subscription", "destroy_node", "get_name")


class _SubscribeOnlySession:
    """The one place in this package that is handed a raw ``rclpy`` node.

    It stores neither the node nor the ``rclpy`` module. The earlier version
    kept both on attributes (``__node`` — which name mangling turns into the
    perfectly readable ``_SubscribeOnlySession__node`` — and ``_rclpy``, which
    was never private in the first place), and an auditor read them from another
    module in one line and created a publisher on ``/cmd_vel``. Now:

    * the node goes into a :class:`~.base.ReadOnlyHandle` with a three-name
      allowlist, and
    * the two module-level entry points that need the raw node or the context as
      an *argument* are bound at construction by
      :func:`~.base.sealed_call`, which returns a function and keeps its
      bindings in a closure.

    Nothing on this object yields the node or the module by attribute access.
    ``session._spin.__closure__`` still does — that residual is documented on
    :func:`~.base.sealed_call` and pinned by ``tests/test_no_arm_pin.py``.
    """

    __slots__ = ("_shutdown", "_spin", "_subscriptions", "handle")

    def __init__(self, rclpy_module: Any, node: Any, context: Any, *, label: str) -> None:
        self._subscriptions: list[Any] = []
        self.handle = ReadOnlyHandle(node, allowed=_NODE_ALLOWLIST, label=label)
        self._spin = sealed_call(rclpy_module, "spin_once", label=label, bind_args=(node,))
        self._shutdown = sealed_call(
            rclpy_module, "shutdown", label=label, bind_kwargs={"context": context}
        )

    def subscribe(self, message_class: Any, topic: str, sink: Any, depth: int) -> Any:
        subscription = self.handle.create_subscription(message_class, topic, sink, depth)
        self._subscriptions.append(subscription)
        return subscription

    def spin_once(self, timeout_s: float) -> None:
        self._spin(timeout_sec=timeout_s)

    def close(self) -> None:
        try:
            self.handle.destroy_node()
        finally:
            self._shutdown()


class DdsIngest(IngestAdapter):
    """Subscribe-only reader for the fifteen DDS rows of the channel matrix."""

    adapter_name: ClassVar[str] = "dds"
    transports: ClassVar[frozenset[Transport]] = frozenset({Transport.DDS})
    payload_kind: ClassVar[PayloadKind] = PayloadKind.DERIVED_SUMMARY
    requirements: ClassVar[tuple[Requirement, ...]] = (
        Requirement(
            "rclpy",
            "Orin only: source /opt/ros/humble/setup.bash and the unitree_ros2 overlay "
            "(JetPack 6.2.x ships Humble). Never install a ROS stack into .parcel/.",
        ),
    )
    notes: ClassVar[tuple[str, ...]] = (
        (
            "rclpy only. The vendor SDK is never imported: it ships the motion clients "
            "beside its subscriber, and its absence from .parcel/ is the motion guarantee."
        ),
        (
            "Payloads are derived JSON summaries. The wire bytes live in the rosbag2 "
            "primary recording; this path is the secondary, attestation-side copy."
        ),
        (
            "Three rows are service-gated (sportmodestate, utlidar/robot_pose, "
            "utlidar/voxel_map_compressed): a publisher can exist and emit nothing."
        ),
    )

    def __init__(self, *, node_name: str = "parcel_capture_ingest", queue_depth: int = 50) -> None:
        if queue_depth < 1:
            raise IngestRefusedError(f"queue_depth must be >= 1, got {queue_depth}")
        self.node_name = node_name
        self.queue_depth = queue_depth

    def open_session(self) -> _SubscribeOnlySession:
        """A subscribe-only session over an ``rclpy`` node, or a refusal.

        Refuses here, on this dev box, because ``rclpy`` is absent and the board
        forbids installing it — module named, remedy attached, no traceback.
        """

        self.require_dependencies()
        try:
            rclpy = importlib.import_module("rclpy")
            node_module = importlib.import_module("rclpy.node")
        except ImportError as error:
            raise IngestUnavailableError(
                AbsenceReason.DEPENDENCY_MISSING,
                f"rclpy became unimportable between the probe and the open: {error}",
                self.requirements[0].remedy,
            ) from error
        context = rclpy.Context()
        rclpy.init(context=context)
        node = node_module.Node(self.node_name, context=context)
        return _SubscribeOnlySession(
            rclpy, node, context, label=f"rclpy node {self.node_name}"
        )

    def read_frames(self, entry: Channel, window_s: float) -> Iterator[IngestFrame]:
        """Subscribe, collect for the window, close. Never publishes.

        The loop below cannot reach a robot on this host — ``rclpy`` is absent
        and the board forbids installing it — but it is no longer UNEXECUTED,
        which is what the PS-G status doc claimed and PS-N measured as false.
        ``tests/test_capture_ingest.py`` drives every line of it against a
        read-only ``rclpy`` double: subscribe, spin, decode, close. What the
        double cannot tell us is whether ``rclpy.spin_once`` DELIVERS against
        this robot — QoS matching in particular — and PSN_STATUS.md
        does_not_prove names that as the first thing to check on the Orin.
        """

        session = self.open_session()
        try:
            message_class = _message_class(entry)
            pending: list[Any] = []
            session.subscribe(
                message_class, ros_subscribe_name(entry), pending.append, self.queue_depth
            )
            end_ns = now_ns()[0] + int(window_s * 1e9)
            while now_ns()[0] < end_ns:
                session.spin_once(0.01)
                while pending:
                    yield frame_from_message(entry, pending.pop(0))
        finally:
            session.close()

    def channels(self) -> tuple[Channel, ...]:
        from parcel_robot.capture import CHANNELS

        entries = tuple(entry for entry in CHANNELS if entry.transport is Transport.DDS)
        if not entries:
            raise IngestContractError("the channel matrix declares no DDS rows")
        return entries
