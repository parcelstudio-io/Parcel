"""Read-only Unitree L2 ingest — card PS-G.

The add-on L2 is the one sensor on this rig whose vendor API is genuinely
bidirectional: ``unilidar_sdk2`` exposes ``startLidar``, ``stopLidar`` and
``setLidarWorkMode``, and the built-in unit's ``utlidar/switch`` topic is treated
by the vendor stack as an **input** — writing ``ON``/``OFF`` toggles the LiDAR.

So this adapter does not turn the LiDAR on. It attaches to a device that is
already streaming, and if nothing is streaming it **refuses with the command an
operator should run in another process**. That is not timidity; it is the
board's first rule applied to the only sensor where "read-only" and "usable"
could plausibly have been traded off. All three mode-changing names are on
:data:`~scripts.parcel_capture.ingest.base.NEVER_ALLOWED`, so a
:class:`~scripts.parcel_capture.ingest.base.ReadOnlyHandle` cannot be configured
to reach them even by a later editor who wants to.

Network, and the collision nobody notices until the session
-----------------------------------------------------------
The L2 ships on **192.168.1.2**. The Go2 itself is **192.168.1.7**, and
192.168.1.0/24 is also the commonest home subnet. One NIC carrying both is how a
session begins with "no topics visible" and ends without LiDAR. :data:`NETWORK_NOTE`
carries the remedy; PS-D's preflight is where it becomes a measurement.

For the session itself the primary path is the vendor ROS 2 node publishing into
``ros2 bag record -s mcap``. This adapter is the preflight and secondary copy.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from typing import Any, ClassVar

from parcel_robot.capture import Channel, Transport
from parcel_robot.capture.channels import SourceClock

from ..preflight import AbsenceReason, ImuSample, PhysicalSample, PointCloudSample
from .base import (
    IngestAdapter,
    IngestFrame,
    IngestRefusedError,
    IngestUnavailableError,
    PayloadKind,
    ReadOnlyHandle,
    Requirement,
    now_ns,
    present,
    read_field,
    summary_payload,
)

NETWORK_NOTE = (
    "The L2 ships on 192.168.1.2 and the Go2 is on 192.168.1.7; 192.168.1.0/24 is also the "
    "commonest home subnet. Put the L2 on a SECOND NIC with its own subnet before the "
    "session, and pin CycloneDDS to the interface that carries the dog."
)

STREAM_NOTE = (
    "This adapter attaches to an L2 that is already streaming and never starts, stops or "
    "re-modes it. Start it in another process — the vendor ROS 2 node is also what feeds "
    "the rosbag2 primary recording, so starting it there costs nothing extra."
)

#: The only ``unilidar_sdk2`` reader attributes this adapter may reach. Every
#: mode-changing name is absent, and also on NEVER_ALLOWED.
_READER_ALLOWLIST = ("getPointCloud", "getImu", "checkInit", "initialize")

# ---- CARD HW-3 (mid360-band, scrum/20260822/task_36) --------------------
#
# The rig this adapter was written for no longer exists. It assumes a Go2 EDU
# with an ADD-ON Unitree L2 bought separately and read over ``unilidar_sdk2``.
# The owner bought a **Go2 EDU+ with a Livox Mid-360 fitted at the factory**
# (design ``scrum/20260822/WAVE3_HW_DESIGN_FABLE.md`` §2.3): there is no add-on
# L2 on it, the built-in head LiDAR is reachable ONLY over DDS ``rt/utlidar/*``
# from 192.168.123.161 (hardware fact 4) and never over this SDK, and the
# planar scan the runtime consumes now comes from ``parcel_robot.lidar``
# decoding raw Livox UDP off port 56300 (card HW-3).
#
# The file, the class and ``SourceDevice.L2`` all stay: bags recorded on the
# old rig join on ``l2.cloud`` / ``l2.imu`` and renaming an id under a
# six-month-old bag is exactly what ``channels.py`` forbids. The L2 ->
# HEAD_LIDAR rename is HW-2/HW-9's, once the box says which unit is fitted.
#
# What changes here is that this adapter can no longer be pointed at the new
# venue by accident. ``venue=`` is refused for the EDU+, and the retirement
# note rides on every refusal this adapter emits, so an operator who reaches
# it on a session morning is sent to the Mid-360 decoder rather than to a
# three-hour build of a vendor SDK for a device that is not on the robot.
#
# STATE IT PLAINLY: **the venue gate is INERT today.** Nothing passes
# ``venue=``. ``ingest/__init__.py:117-118 adapter_for`` constructs every entry of
# ``LIVE_ADAPTERS`` as ``factory()``, ``orin_rehearsal.py:2072`` does
# ``L2Ingest()``, no ``configs/profiles/`` exists yet and no venue concept
# exists anywhere outside this card. The only effect reachable today is
# ``RETIREMENT_NOTE`` riding on :attr:`L2Ingest.notes`. The mechanism is here
# so the wiring is a one-argument change; the wiring itself belongs to HW-5,
# which owns the physical profile that names the venue, and the injection
# point is ``ingest/__init__.py:117-118``. It is deliberately NOT an unconditional
# raise in ``__init__``: that would break ``adapter_for`` for every adapter,
# and an unconditional refusal in ``open_reader()`` would redden the legacy
# rig's own contract (``tests/test_capture_ingest.py:1615,1637,2459``), which
# is not this card's to change (verifier finding F4).

#: The rig this adapter was written for: Go2 EDU + separately-bought L2.
LEGACY_ADDON_L2_VENUE = "go2_edu_addon_l2"

#: The rig the project is now building for. Same name as HW-5's physical
#: profile and ``capture/channels.py:GO2_EDU_PLUS_VENUE``.
GO2_EDU_PLUS_VENUE = "go2_edu_plus"

RETIREMENT_NOTE = (
    "RETIRED for the Go2 EDU+ venue (design §2.3): that rig has no add-on Unitree L2. "
    "Its built-in head LiDAR is DDS-only (rt/utlidar/*, 192.168.123.161) and its Livox "
    "Mid-360 is decoded by parcel_robot.lidar (raw UDP, port 56300) and banded into "
    "SimObservation.lidar_ranges by parcel_robot.lidar.band — card HW-3, "
    "scrum/20260822/task_36. This adapter remains only for bags and preflights of the "
    "older Go2 EDU + add-on L2 rig."
)

_RETIRED_REMEDY = (
    "read the Mid-360 with parcel_robot.lidar (parse_point_frame / scan_from_frames, no "
    "SDK and no ROS) or record it through livox_ros_driver2 in the rclpy capture venv — "
    "see capture/channels.py:MID360_CHANNELS. Do NOT build unilidar_sdk2 for this rig: "
    "there is no add-on L2 on it, and the built-in head LiDAR does not speak that SDK."
)


def refuse_retired_venue(venue: str) -> None:
    """Refuse the venues this adapter is retired for. Pure; no I/O.

    Named and exported so HW-9's box-day run sheet and any future venue-aware
    caller ask this once rather than restating the rule.
    """

    if venue == GO2_EDU_PLUS_VENUE:
        raise IngestUnavailableError(
            AbsenceReason.NOT_ATTEMPTED,
            f"the add-on Unitree L2 path is retired for venue {venue!r}: {RETIREMENT_NOTE}",
            _RETIRED_REMEDY,
        )


# ---- END CARD HW-3 -------------------------------------------------------

L2_CLOUD = "l2.cloud"
L2_IMU = "l2.imu"


def decode_l2_cloud(message: Any) -> tuple[tuple[PhysicalSample, ...], dict[str, Any]]:
    """A ``unilidar_sdk2`` cloud -> a :class:`PointCloudSample` plus its summary.

    The SDK hands back a point list rather than a ``PointCloud2``, so the field
    names are the SDK's own (``x``, ``y``, ``z``, ``intensity``, ``time``,
    ``ring``) and they are recorded VERBATIM: a cloud whose per-point ``time``
    and ``ring`` were never written down cannot be deskewed later.
    """

    points = read_field(message, "points")
    items = list(points) if present(points) and hasattr(points, "__iter__") else []
    ranges: list[float] = []
    nonfinite = 0
    names: list[str] = []
    for index, point in enumerate(items[:512]):
        if index == 0:
            names = [
                name
                for name in ("x", "y", "z", "intensity", "time", "ring")
                if present(read_field(point, name))
            ]
        coords = [read_field(point, axis) for axis in ("x", "y", "z")]
        if any(
            not present(value) or isinstance(value, bool) or not isinstance(value, (int, float))
            for value in coords
        ):
            nonfinite += 1
            continue
        ranges.append(float(sum(float(value) ** 2 for value in coords)) ** 0.5)
    sample = PointCloudSample(
        point_count=len(items),
        field_names=tuple(names),
        nonfinite_points=nonfinite,
        ranges_m=tuple(ranges),
    )
    return (sample,), {
        "message": "unilidar_sdk2/PointCloud",
        "stamp_ns": _stamp_ns(message),
        "point_count": len(items),
        "fields": names,
        "range_samples": len(ranges),
        "nonfinite_points": nonfinite,
        "ring_count": _int_or_none(read_field(message, "ringNum")),
        "missing_fields": [] if names else ["points"],
        "findings": [],
    }


def decode_l2_imu(message: Any) -> tuple[tuple[PhysicalSample, ...], dict[str, Any]]:
    """A ``unilidar_sdk2`` IMU record -> an :class:`ImuSample` plus its summary."""

    accel = _vector(message, ("linear_acceleration", "acceleration"))
    gyro = _vector(message, ("angular_velocity", "angular_velocity_"))
    samples: list[PhysicalSample] = []
    if accel is not None or gyro is not None:
        samples.append(ImuSample(accel_mps2=accel, gyro_rps=gyro))
    missing = [name for name, value in (("accel", accel), ("gyro", gyro)) if value is None]
    return tuple(samples), {
        "message": "unilidar_sdk2/IMU",
        "stamp_ns": _stamp_ns(message),
        "linear_acceleration_mps2": list(accel) if accel else None,
        "angular_velocity_rps": list(gyro) if gyro else None,
        "missing_fields": missing,
        "findings": [],
    }


def _vector(message: Any, names: tuple[str, ...]) -> tuple[float, float, float] | None:
    for name in names:
        value = read_field(message, name)
        if not present(value):
            continue
        if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
            items = list(value)[:3]
        else:
            items = [read_field(value, axis) for axis in ("x", "y", "z")]
        if len(items) == 3 and all(
            present(item) and not isinstance(item, bool) and isinstance(item, (int, float))
            for item in items
        ):
            return (float(items[0]), float(items[1]), float(items[2]))
    return None


def _stamp_ns(message: Any) -> int | None:
    """The SDK reports seconds as a double. Convert once, here, or not at all."""

    value = read_field(message, "stamp")
    if not present(value):
        value = read_field(message, "timestamp")
    if not present(value) or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value) * 1e9)


def _int_or_none(value: Any) -> int | None:
    if not present(value) or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def decoder_for(entry: Channel) -> Callable[[Any], tuple[tuple[PhysicalSample, ...], dict[str, Any]]]:
    """The decoder this channel's messages go through. The only dispatch here.

    Named and exported so the cross-package structural pin
    (``test_no_channel_whose_decoder_emits_samples_has_an_empty_rule_set``) can
    ask *which* decoder runs for a channel without keeping its own copy of the
    mapping — a second copy is how ``go2.sportmodestate`` came to have a decoder
    that emitted an ``ImuSample`` and a ``FootForceSample`` and a plausibility
    layer that had no rule for either.
    """

    if entry.channel_id == L2_CLOUD:
        return decode_l2_cloud
    if entry.channel_id == L2_IMU:
        return decode_l2_imu
    raise IngestRefusedError(f"{entry.channel_id}: not an L2 channel")


def frame_from_l2(entry: Channel, message: Any) -> IngestFrame:
    samples, summary = decoder_for(entry)(message)
    monotonic_ns, realtime_ns = now_ns()
    stamp = summary.get("stamp_ns") if entry.source_clock is SourceClock.DEVICE_TIMESPEC else None
    return IngestFrame(
        channel_id=entry.channel_id,
        host_monotonic_ns=monotonic_ns,
        host_realtime_ns=realtime_ns,
        payload=summary_payload(summary),
        payload_kind=PayloadKind.DERIVED_SUMMARY,
        source_timestamp_ns=stamp,
        measurements=samples,
        detail=f"{entry.channel_id} via unilidar_sdk2 (attach-only)",
    )


class L2Ingest(IngestAdapter):
    """Attach-only reader for the add-on L2's cloud and IMU."""

    adapter_name: ClassVar[str] = "l2"
    transports: ClassVar[frozenset[Transport]] = frozenset({Transport.UNILIDAR_SDK2})
    payload_kind: ClassVar[PayloadKind] = PayloadKind.DERIVED_SUMMARY
    requirements: ClassVar[tuple[Requirement, ...]] = (
        Requirement(
            "unilidar_sdk2",
            "Orin only: build the vendor unilidar_sdk2 and put its python binding on "
            "PYTHONPATH. Never into .parcel/.",
        ),
    )
    # ---- CARD HW-3: the retirement note rides on every report this adapter
    # emits, so the pointer at parcel_robot.lidar reaches the operator on the
    # path they actually hit (a missing unilidar_sdk2), not only in a docstring.
    notes: ClassVar[tuple[str, ...]] = (STREAM_NOTE, NETWORK_NOTE, RETIREMENT_NOTE)
    # ---- END CARD HW-3 ---------------------------------------------------

    def __init__(
        self,
        *,
        endpoint: str = "udp://192.168.1.2",
        # ---- CARD HW-3: which rig this adapter is being pointed at. The
        # default is the rig it was written for, so nothing that exists today
        # changes; the EDU+ is refused by refuse_retired_venue(). ----------
        venue: str = LEGACY_ADDON_L2_VENUE,
        # ---- END CARD HW-3 -----------------------------------------------
    ) -> None:
        if not endpoint.strip():
            raise IngestRefusedError("endpoint must be non-empty")
        # ---- CARD HW-3 ---------------------------------------------------
        refuse_retired_venue(venue)
        self.venue = venue
        # ---- END CARD HW-3 -----------------------------------------------
        self.endpoint = endpoint

    def open_reader(self) -> ReadOnlyHandle:
        """Attach to an already-streaming L2, or refuse with the start command."""

        self.require_dependencies()
        try:
            sdk = importlib.import_module("unilidar_sdk2")
        except ImportError as error:
            raise IngestUnavailableError(
                AbsenceReason.DEPENDENCY_MISSING,
                f"unilidar_sdk2 became unimportable between the probe and the open: {error}",
                self.requirements[0].remedy,
            ) from error
        reader = sdk.UnitreeLidarReader()
        handle = ReadOnlyHandle(
            reader, allowed=_READER_ALLOWLIST, label=f"unilidar_sdk2 reader {self.endpoint}"
        )
        self.require_attached(handle)
        return handle

    def require_attached(self, handle: ReadOnlyHandle) -> None:
        """A fresh reader is not an attached one, and silence must say which.

        ``UnitreeLidarReader()`` constructs a reader; it does not open the
        socket. Every ``getPointCloud`` on an un-attached reader returns nothing,
        so a probe reported ``l2.cloud`` ABSENT with "no message arrived" — the
        same words it would use for an L2 that was unplugged, at 08:00, on the
        one channel of the two whose absence is CRITICAL.

        This adapter does not attach either. ``initialize()``'s signature varies
        across ``unilidar_sdk2`` builds and is unverified against **our** unit,
        and the board's rule is that a reader does not guess at a vendor API it
        cannot test. So the refusal names the state instead: a preflight result
        that is *not evidence about the L2* now says so, in a sentence with a
        command attached, rather than being indistinguishable from a dead sensor.
        """

        check = read_field(handle, "checkInit")
        if not present(check):
            raise IngestUnavailableError(
                AbsenceReason.NOT_ATTEMPTED,
                "this unilidar_sdk2 build exposes no checkInit(), so whether the reader is "
                "attached cannot be established; an unattached reader returns nothing and "
                "is indistinguishable from an L2 that is not streaming",
                "run the vendor ROS 2 node (which is also what feeds the rosbag2 primary "
                "recording) and read l2.cloud / l2.imu off its topics instead; then record "
                "the SDK version in the run sheet.",
            )
        try:
            attached = bool(check())
        except Exception as error:  # a probe that raises is ABSENT, never a traceback
            raise IngestUnavailableError(
                AbsenceReason.PROBE_RAISED,
                f"unilidar_sdk2 checkInit() raised {type(error).__name__}: {error}",
                "check the L2 is on its own NIC and subnet before anything else. "
                + NETWORK_NOTE,
            ) from error
        if not attached:
            raise IngestUnavailableError(
                AbsenceReason.NOT_ATTEMPTED,
                "the unilidar_sdk2 reader reports it is not initialised, so nothing would "
                "arrive on l2.cloud or l2.imu whatever the LiDAR is doing. This adapter "
                "does not call initialize(): its signature is unverified against our unit "
                "and a reader that guesses at a vendor API is how a session morning is "
                "spent debugging the tool",
                "start the vendor ROS 2 node in another process — it is also what feeds "
                "the rosbag2 primary recording, so it costs nothing extra — and take the "
                "L2's presence from `ros2 topic hz` there. " + NETWORK_NOTE,
            )

    def read_frames(self, entry: Channel, window_s: float) -> Iterator[IngestFrame]:
        """Poll the attached reader for the window, then stop.

        Not UNEXECUTED any more: ``tests/test_capture_ingest.py`` drives this
        loop against a read-only ``unilidar_sdk2`` double. What no double can
        tell us is whether a real reader ever reaches the attached state — see
        :meth:`require_attached`.
        """

        handle = self.open_reader()
        getter = "getPointCloud" if entry.channel_id == L2_CLOUD else "getImu"
        end_ns = now_ns()[0] + int(window_s * 1e9)
        while now_ns()[0] < end_ns:
            message = read_field(handle, getter)()
            if not present(message):
                continue
            yield frame_from_l2(entry, message)

    def channels(self) -> tuple[Channel, ...]:
        from parcel_robot.capture import CHANNELS

        return tuple(entry for entry in CHANNELS if entry.transport is Transport.UNILIDAR_SDK2)
