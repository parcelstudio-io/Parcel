"""Live sensor ingest for ``parcel-capture`` — card PS-G, the hole in PS-1.

``record.py`` shipped a recorder that could not read a byte:
``resolve_live_source()`` refused for every transport and ``preflight.py``
defaulted to ``unavailable_reader_factory``, because no PS-1 card owned the DDS
subscriber, the RealSense loop or the L2 reader. This package is that owner.

Four adapters, one interface
----------------------------

======================  ==================================  ==================
adapter                 transport                           dependency
======================  ==================================  ==================
:class:`DdsIngest`      the 15 DDS rows of the matrix       ``rclpy``
:class:`RealSenseIngest` the 6 D455 streams                 ``pyrealsense2``
:class:`L2Ingest`       the add-on L2's cloud and IMU       ``unilidar_sdk2``
:class:`FakeIngest`     any row, synthetically              none
======================  ==================================  ==================

Every one of the first three refuses on this dev box — but card ENV-1 split
*why* into two facts that must never be conflated. ``rclpy`` and
``unilidar_sdk2`` are not installed, so those two refuse ``dependency_missing``.
``pyrealsense2`` **is** installed (P1-A put it in ``.parcel`` on 2026-08-22 for
the desk-camera venue) and no camera is plugged in, so :class:`RealSenseIngest`
refuses ``device_node_missing`` — and it does so from a ``/dev`` census, without
importing the SDK. :func:`dependency_report_text` prints each module's state as
one of *absent*, *installed but no device*, or *ready*, because "the wheel
imports" and "the camera is there" are different claims and a report that
collapses them tells the go/no-go a lie. :class:`FakeIngest` is what makes the
*path* testable anyway.

Ordering, because it decides what the session records
-----------------------------------------------------
``ros2 bag record -s mcap`` (:mod:`scripts.parcel_capture.rosbag2`) is the
**primary** recorder: it needs no code from this package and its output is
readable by every tool in the next milestone. These adapters serve preflight,
the physical-plausibility gate, and the Parcel-native attestation/clock stream,
which is the **secondary** copy and never the sole copy of anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from parcel_robot.capture import CHANNELS, Channel, Transport

from .base import (
    ABSENT,
    NEVER_ALLOWED,
    AdapterCapability,
    DependencyReport,
    DevicePresence,
    DeviceReport,
    IngestAdapter,
    IngestContractError,
    IngestError,
    IngestFrame,
    IngestRefusedError,
    IngestUnavailableError,
    PayloadKind,
    ReadOnlyHandle,
    RecorderFeed,
    Requirement,
    channel_reader_factory,
    deadline_ns,
    now_ns,
    present,
    read_field,
    summary_payload,
)
from .dds import DdsIngest, ros_message_type, ros_subscribe_name
from .dds import decoder_for as dds_decoder_for
from .fake import FakeIngest
from .l2 import L2Ingest
from .l2 import decoder_for as l2_decoder_for
from .realsense import RealSenseIngest
from .realsense import decoder_for as realsense_decoder_for

#: Live adapters in resolution order. :class:`FakeIngest` is deliberately NOT
#: here: a synthetic backend must never be selected by accident on the day.
LIVE_ADAPTERS: tuple[type[IngestAdapter], ...] = (DdsIngest, RealSenseIngest, L2Ingest)

#: Transports the matrix declares but no adapter serves. Enumerated rather than
#: discovered, so a channel with no reader is a stated gap, not a surprise: the
#: GNSS puck, the UWB fob and the mic array are all CONFIRM_ON_HAND or
#: AWAITING_HARDWARE, and the front camera's H.264 path needs a media stack
#: (ffmpeg/GStreamer), not a robot SDK.
UNSERVED_TRANSPORTS: dict[Transport, str] = {
    Transport.PLATFORM_TOOL: (
        "tegrastats is scraped by PS-D's preflight, which already owns the platform-tool "
        "path; duplicating it here would give one channel two readers"
    ),
    Transport.SERIAL: (
        "the ZED-F9P is CONFIRM_ON_HAND and its NMEA/UBX reader is not on this card"
    ),
    Transport.VENDOR_UWB: (
        "the UWB ranging protocol is undocumented to us; no reader can be written from "
        "what we have"
    ),
    Transport.USB_AUDIO: (
        "the XVF3800 mic array is AWAITING_HARDWARE (BLOCKED.md B3)"
    ),
    Transport.VENDOR_VIDEO: (
        "the front camera's H.264 path is RTP over multicast 230.1.1.1:1720 and needs a "
        "media stack (ffmpeg/GStreamer), not the robot SDK. Its JPEG twin is a DDS topic "
        "and IS served, by DdsIngest"
    ),
}


def adapter_for(entry: Channel) -> IngestAdapter:
    """The live adapter that serves this channel, or a refusal naming the gap."""

    if not isinstance(entry, Channel):
        raise IngestRefusedError(f"expected a Channel, got {entry!r}")
    for factory in LIVE_ADAPTERS:
        adapter = factory()
        if adapter.serves(entry):
            return adapter
    reason = UNSERVED_TRANSPORTS.get(
        entry.transport, "no adapter is registered for this transport"
    )
    raise IngestRefusedError(
        f"{entry.channel_id}: transport {entry.transport.value} has no ingest adapter — "
        f"{reason}"
    )


def decoder_for_channel(entry: Channel) -> Any:
    """The decode function this channel's messages actually go through.

    Each adapter owns exactly one dispatch — :func:`dds.decoder_for`,
    :func:`l2.decoder_for`, :func:`realsense.decoder_for` — and this routes to
    it. There is no fourth table anywhere, which is the point: the plausibility
    layer's rule set for a channel and the decoder that feeds it must agree, and
    the way they came to disagree was that nothing could ask both questions in
    one place. ``go2.sportmodestate`` was CRITICAL, its decoder emitted an
    ``ImuSample`` and a ``FootForceSample`` per message, and
    ``preflight.classify_channel`` returned ``()`` for it — so every measurement
    that channel produced was discarded before any rule saw it, and nothing
    could notice. ``test_no_channel_whose_decoder_emits_samples_has_an_empty_rule_set``
    asks both questions here, for every row of the matrix.

    Refuses for a channel no live adapter serves, rather than returning a
    do-nothing decoder: "this channel decodes to nothing" and "no reader exists
    for this channel" are different facts and must not share a return value.
    """

    if not isinstance(entry, Channel):
        raise IngestRefusedError(f"expected a Channel, got {entry!r}")
    if entry.transport is Transport.DDS:
        return dds_decoder_for(entry)
    if entry.transport is Transport.UNILIDAR_SDK2:
        return l2_decoder_for(entry)
    if entry.transport is Transport.REALSENSE:
        return realsense_decoder_for(entry)
    reason = UNSERVED_TRANSPORTS.get(
        entry.transport, "no adapter is registered for this transport"
    )
    raise IngestRefusedError(
        f"{entry.channel_id}: transport {entry.transport.value} has no decoder — {reason}"
    )


def capabilities() -> tuple[AdapterCapability, ...]:
    """What every live adapter claims, and whether it could run here."""

    return tuple(factory().capability() for factory in LIVE_ADAPTERS)


def coverage() -> dict[str, list[str]]:
    """Which matrix channels have a reader and which do not. Fail-closed census."""

    served: list[str] = []
    unserved: list[str] = []
    for entry in CHANNELS:
        try:
            adapter_for(entry)
        except IngestRefusedError:
            unserved.append(entry.channel_id)
        else:
            served.append(entry.channel_id)
    return {"served": served, "unserved": unserved}


def dependency_report_text(adapters: Sequence[type[IngestAdapter]] | None = None) -> str:
    """Actionable, human-readable, never a traceback. What ``--check`` prints."""

    factories = tuple(adapters) if adapters is not None else LIVE_ADAPTERS
    lines: list[str] = []
    census = coverage()
    lines.append(
        f"channels in the matrix: {len(CHANNELS)}  served: {len(census['served'])}  "
        f"unserved: {len(census['unserved'])}"
    )
    for factory in factories:
        adapter = factory()
        report = adapter.dependency_report()
        device = adapter.device_report()
        # Three states, not two (card ENV-1). READY is reserved for "the module
        # is here AND nothing says the hardware is not"; an installed wheel with
        # no device on the bus reads NO DEVICE and names the modules it does
        # have, so the line is actionable either way.
        if not report.satisfied:
            state = f"UNAVAILABLE (missing: {', '.join(report.missing)})"
        elif device.presence is DevicePresence.ABSENT:
            state = f"NO DEVICE (installed: {', '.join(report.present) or 'nothing required'})"
        else:
            state = "READY"
        lines.append("")
        lines.append(f"{report.adapter:<12} {len(adapter.channels()):>2} channel(s)  {state}")
        if report.remedy:
            lines.append(f"    remedy: {report.remedy}")
        lines.append(f"    device: {device.presence.value} — {device.detail}")
        if device.presence is DevicePresence.ABSENT and device.remedy:
            lines.append(f"    plug:   {device.remedy}")
        for note in adapter.notes:
            lines.append(f"    note:   {note}")
    if census["unserved"]:
        lines.append("")
        lines.append("channels with NO ingest adapter (each is a stated gap, not a surprise):")
        for channel_id in census["unserved"]:
            entry = next(item for item in CHANNELS if item.channel_id == channel_id)
            reason = UNSERVED_TRANSPORTS.get(entry.transport, "no adapter registered")
            lines.append(f"  {channel_id:<26} {entry.transport.value:<14} {reason}")
    return "\n".join(lines)


__all__ = [
    "ABSENT",
    "CHANNELS",
    "LIVE_ADAPTERS",
    "NEVER_ALLOWED",
    "UNSERVED_TRANSPORTS",
    "AdapterCapability",
    "DdsIngest",
    "DependencyReport",
    "DevicePresence",
    "DeviceReport",
    "FakeIngest",
    "IngestAdapter",
    "IngestContractError",
    "IngestError",
    "IngestFrame",
    "IngestRefusedError",
    "IngestUnavailableError",
    "L2Ingest",
    "PayloadKind",
    "ReadOnlyHandle",
    "RealSenseIngest",
    "RecorderFeed",
    "Requirement",
    "adapter_for",
    "capabilities",
    "channel_reader_factory",
    "coverage",
    "deadline_ns",
    "decoder_for_channel",
    "dependency_report_text",
    "now_ns",
    "present",
    "read_field",
    "ros_message_type",
    "ros_subscribe_name",
    "summary_payload",
]
