"""Pure decoder for the Livox SDK2 point-cloud UDP frame — card HW-3.

No socket is opened here, no vendor SDK is imported, no ROS is involved, and
numpy is never imported: the parser is ``bytes -> LivoxPointFrame`` and nothing
else, so it is testable offline against synthesised frames and importable in
the ``base`` extra on the Orin's CPython 3.10 / aarch64 (design §5.1). The one
function that touches a socket, :func:`receive_frames`, is deliberately
separate and takes an ALREADY-BOUND socket object.

Where this layout comes from
----------------------------
Read on 2026-08-23 and transcribed field by field:

* ``https://raw.githubusercontent.com/Livox-SDK/Livox-SDK2/master/include/livox_lidar_def.h``
  — ``LivoxLidarEthernetPacket`` and the three raw point structs, all inside
  ``#pragma pack(1)`` / ``#pragma pack()``, which is why the offsets below are
  the naive sums with no padding.
* ``https://github.com/Livox-SDK/Livox-SDK2/wiki/Livox-SDK-Communication-Protocol-HAP(English)``
  — the wire table with offsets and the ``time_type`` meanings. This is the
  **HAP** page; the Mid-360 page did not load, so every field whose meaning
  appears only there is marked UNCONFIRMED below and is carried verbatim
  rather than decoded.
* ``https://raw.githubusercontent.com/Livox-SDK/livox_ros_driver2/master/src/comm/pub_handler.cpp``
  — how the vendor's own driver decodes: the per-point timestamp arithmetic
  and the mm/cm scaling reproduced here are its lines, not an interpretation.
  It also documents the two forms this card refuses (``:429-431`` spherical,
  ``:469-482`` double echo) — see :class:`LivoxDataType`: they are refused as
  OUT OF SCOPE, not as unknown.
* ``https://raw.githubusercontent.com/Livox-SDK/livox_ros_driver2/master/src/comm/comm.h``
  — ``:96-98``, the three timestamp types (:class:`LivoxTimeType`).
* ``https://raw.githubusercontent.com/Livox-SDK/Livox-SDK2/master/samples/livox_lidar_quick_start/mid360_config.json``
  — the Mid-360 port map.

The citing rule this module obeys (dispatch, ``research.json``): a field whose
meaning is *documented* is decoded; a field whose meaning is *inferred* is
carried verbatim or refused, never guessed. Guessing here does not produce a
wrong number in a log — it produces an obstacle that is not there, in the only
channel ``navigation/reactive_safety.py`` reads.

The 36-byte header, little-endian, byte-packed
----------------------------------------------
====== ==== ================ =========================================
offset size field            what this module does
====== ==== ================ =========================================
0      1    ``version``      refused unless in :data:`SUPPORTED_PROTOCOL_VERSIONS`
1      2    ``length``       carried as ``declared_length``; never decoded with (UNCONFIRMED for Mid-360)
3      2    ``time_interval`` ``* 100`` = the packet's sampling window in ns
5      2    ``dot_num``      point count; ``0`` and over-cap are refusals
7      2    ``udp_cnt``      carried; :func:`sequence_report` reads it
9      1    ``frame_cnt``    carried; nothing branches on it (UNCONFIRMED)
10     1    ``data_type``    dispatch, see :class:`LivoxDataType`
11     1    ``time_type``    carried; see :class:`LivoxTimeType`
12     12   ``rsvd[12]``     carried verbatim (the HAP page names byte 12 ``pack_info``; UNCONFIRMED here)
24     4    ``crc32``        carried, NOT verified — the polynomial/seed/reflection are unstated (UNCONFIRMED)
28     8    ``timestamp``    8 bytes host-order (LE on x86_64/aarch64; the driver
                            memcpy's them into a uint64, pub_handler.cpp:265-268) = the frame's base ns
36     ...  ``data``         ``dot_num`` points of :data:`POINT_SIZE_BYTES` bytes
====== ==== ================ =========================================
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

__all__ = [
    "CMD_DATA_PORT",
    "HEADER_SIZE_BYTES",
    "HOST_POINT_DATA_PORT",
    "IMU_DATA_PORT",
    "LIDAR_SAMPLE_HOST_IP",
    "LOG_DATA_PORT",
    "MAX_POINTS_PER_FRAME",
    "POINT_DATA_PORT",
    "POINT_SIZE_BYTES",
    "PUSH_MSG_PORT",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "FrameSequenceReport",
    "LivoxDataType",
    "LivoxDecodeError",
    "LivoxPointFrame",
    "LivoxTimeType",
    "build_point_frame",
    "parse_point_frame",
    "receive_frames",
    "sequence_report",
]


class LivoxDecodeError(ValueError):
    """A datagram this module refuses to decode, with the field that refused.

    Every message names the field and the byte counts involved. A decoder that
    says only "bad packet" sends the reader to the wrong layer on the one
    morning the hardware is on the bench.
    """


class LivoxDataType(IntEnum):
    """``data_type`` values, verbatim from ``livox_lidar_def.h``.

    Only the two Cartesian forms are DECODED here. The other three are refused
    as **out of scope for card HW-3, not as unknown** — the distinction matters
    because "we could not read the format" and "we chose not to implement it"
    are different facts and only the first would justify a stall on box-day:

    * :attr:`IMU` — documented (``LivoxLidarImuRawPoint``, six float32s), but
      it is not point data and arrives on its own port
      (:data:`IMU_DATA_PORT`). Its axis units are not claimed here.
    * :attr:`SPHERICAL` — fully documented: ``pub_handler.cpp:429-431``
      converts ``theta``/``phi`` at 0.01 deg and ``depth`` in mm. Not decoded
      because the Mid-360 is configured for Cartesian output and a half-tested
      second geometry path is a liability, not a feature.
    * :attr:`DOUBLE_ECHO` — fully documented: ``livox_lidar_def.h:174-185``
      defines ``LivoxLidarDoubleEchoRawPoint`` (two returns of
      ``{i32 x,y,z mm, u8 reflectivity, u8 tag}`` = 28 B), decoded at
      ``pub_handler.cpp:469-482``. Not decoded because dual-return changes what
      a band bin MEANS (which echo is the surface?) and that is a design
      question B11 answers with a real sensor, not a decoder detail.

    Adding either is a small, well-cited change; refusing until then keeps the
    scan honest.
    """

    IMU = 0x00
    CARTESIAN_HIGH = 0x01
    CARTESIAN_LOW = 0x02
    SPHERICAL = 0x03
    DOUBLE_ECHO = 0x11


class LivoxTimeType(IntEnum):
    """``time_type`` values — ``livox_ros_driver2/src/comm/comm.h:96-98``
    (``kTimestampTypeNoSync = 0``, ``kTimestampTypeGptpOrPtp = 1``,
    ``kTimestampTypeGps = 2``), meanings from the HAP protocol page.

    All three carry a ``uint64`` nanosecond count; they differ in what the zero
    is. :attr:`NO_SYNC` counts from LiDAR power-on and is therefore NOT an
    absolute anchor — which is why ``capture/channels.py``'s Mid-360 rows
    declare ``SourceClock.UNVERIFIED`` until the value is read off a real unit.
    :attr:`GPTP` and :attr:`GPS` are both externally disciplined, which is what
    :attr:`LivoxPointFrame.synchronised` answers.
    """

    NO_SYNC = 0
    GPTP = 1
    GPS = 2


#: Protocol versions whose field layout this module has read. The layout is
#: version-defined, so an unknown version is a refusal rather than a decode:
#: see :func:`parse_point_frame`. Box-day (HW-9) reads the real value off the
#: unit in one command; adding it here is a one-line change.
SUPPORTED_PROTOCOL_VERSIONS: frozenset[int] = frozenset({0})

HEADER_SIZE_BYTES = 36

#: Wire size of one point, by ``data_type``. These are the packed ``sizeof``
#: of the SDK2 structs (``3 x int32 + 2 x uint8`` and ``3 x int16 + 2 x
#: uint8``); ``pub_handler.cpp`` casts the data segment to those structs and
#: indexes it, which is the same claim. NB ``livox_ros_driver2``'s own
#: ``comm.h`` carries ``KCartesianPointSize = 13`` / ``KSphericalPointSzie =
#: 9`` — those are the SDK **1** raw points, which have no ``tag`` byte
#: (13 = 3x4+1, 9 = 4+2+2+1), and they are not these sizes.
POINT_SIZE_BYTES: dict[LivoxDataType, int] = {
    LivoxDataType.CARTESIAN_HIGH: 14,
    LivoxDataType.CARTESIAN_LOW: 8,
}

#: Metres per raw coordinate unit, by ``data_type`` — ``pub_handler.cpp``
#: divides by 1000.0 (mm) and by 100.0 (cm) respectively.
_XYZ_SCALE_M: dict[LivoxDataType, float] = {
    LivoxDataType.CARTESIAN_HIGH: 1e-3,
    LivoxDataType.CARTESIAN_LOW: 1e-2,
}

_POINT_STRUCT: dict[LivoxDataType, struct.Struct] = {
    LivoxDataType.CARTESIAN_HIGH: struct.Struct("<iiiBB"),
    LivoxDataType.CARTESIAN_LOW: struct.Struct("<hhhBB"),
}

#: Largest UDP payload an IPv4 datagram can carry.
_MAX_UDP_PAYLOAD_BYTES = 65507

#: A ``dot_num`` larger than the smallest point size could fit in one datagram
#: is not a big frame, it is a corrupt header — refused before any allocation.
MAX_POINTS_PER_FRAME = (_MAX_UDP_PAYLOAD_BYTES - HEADER_SIZE_BYTES) // min(
    POINT_SIZE_BYTES.values()
)

# Ports and the sample host address, verbatim from ``mid360_config.json``.
# Host-side ports are the LiDAR-side port + 1; the host IP/NIC on the Orin is
# UNKNOWN until the box is opened (Q-wire, design §8), which is why nothing
# here is a default argument to a socket call.
CMD_DATA_PORT = 56100
PUSH_MSG_PORT = 56200
POINT_DATA_PORT = 56300
IMU_DATA_PORT = 56400
LOG_DATA_PORT = 56500
HOST_POINT_DATA_PORT = POINT_DATA_PORT + 1
LIDAR_SAMPLE_HOST_IP = "192.168.1.5"

_HEADER_STRUCT = struct.Struct("<BHHHHBBB12sIQ")


@dataclass(frozen=True, slots=True)
class LivoxPointFrame:
    """One decoded point-cloud datagram.

    Coordinates are kept in the wire's own integer units with
    :attr:`xyz_scale_m` beside them rather than being converted eagerly: the
    band filter folds the scale into its extrinsic and touches each point
    once. :meth:`points_m` is the general-purpose view for every other reader.
    """

    version: int
    declared_length: int
    time_interval_ns: int
    dot_num: int
    udp_cnt: int
    frame_cnt: int
    data_type: LivoxDataType
    time_type: int
    reserved: bytes
    crc32: int
    base_timestamp_ns: int
    point_interval_ns: int
    xyz_scale_m: float
    #: ``(x, y, z, reflectivity, tag)`` per point, in wire units. ``tag`` is
    #: carried verbatim and never interpreted: its bit meanings are in none of
    #: the sources read (UNCONFIRMED).
    raw_points: tuple[tuple[int, int, int, int, int], ...]

    @property
    def synchronised(self) -> bool:
        """True only for a declared external clock discipline (gPTP/PTP or
        GPS, ``comm.h:96-98``). An unknown ``time_type`` is not synced: unknown
        is absent, never assumed."""

        return self.time_type in (LivoxTimeType.GPTP, LivoxTimeType.GPS)

    def timestamp_ns(self, index: int) -> int:
        """Per-point timestamp — ``pub_handler.cpp``'s arithmetic, exactly.

        ``point.offset_time = pkt.time_stamp + i * pkt.point_interval`` with
        ``point_interval = time_interval * 100 / dot_num`` (ns).
        """

        if not 0 <= index < len(self.raw_points):
            raise IndexError(f"point index {index} out of range for {self.dot_num} points")
        return self.base_timestamp_ns + index * self.point_interval_ns

    def points_m(self) -> Iterator[tuple[float, float, float, int, int, int]]:
        """``(x_m, y_m, z_m, reflectivity, tag, timestamp_ns)`` per point."""

        scale = self.xyz_scale_m
        base = self.base_timestamp_ns
        step = self.point_interval_ns
        for index, (x, y, z, reflectivity, tag) in enumerate(self.raw_points):
            yield (x * scale, y * scale, z * scale, reflectivity, tag, base + index * step)

    def xyz_m(self) -> Iterator[tuple[float, float, float]]:
        """Just the metric coordinates, for the band filter."""

        scale = self.xyz_scale_m
        for x, y, z, _reflectivity, _tag in self.raw_points:
            yield (x * scale, y * scale, z * scale)


def parse_point_frame(payload: bytes) -> LivoxPointFrame:
    """Decode one point-cloud datagram, or refuse and say which field refused.

    Pure: no socket, no clock, no global state. Every refusal is a
    :class:`LivoxDecodeError`.
    """

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise LivoxDecodeError(
            f"a Livox frame is bytes, got {type(payload).__name__} — a decoder that "
            f"accepts anything iterable will happily decode a list of ints as geometry"
        )
    payload = bytes(payload)
    if len(payload) < HEADER_SIZE_BYTES:
        raise LivoxDecodeError(
            f"truncated header: {len(payload)} bytes, the Livox header is "
            f"{HEADER_SIZE_BYTES}"
        )
    (
        version,
        declared_length,
        time_interval,
        dot_num,
        udp_cnt,
        frame_cnt,
        raw_data_type,
        time_type,
        reserved,
        crc32,
        base_timestamp_ns,
    ) = _HEADER_STRUCT.unpack_from(payload, 0)

    if version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise LivoxDecodeError(
            f"version {version} is not a protocol version this decoder has read "
            f"(known: {sorted(SUPPORTED_PROTOCOL_VERSIONS)}). The field layout is "
            f"version-defined, so decoding it would fabricate geometry; read the "
            f"real value off the unit and add it to SUPPORTED_PROTOCOL_VERSIONS"
        )
    try:
        data_type = LivoxDataType(raw_data_type)
    except ValueError as error:
        known = ", ".join(f"{member.value:#04x}={member.name}" for member in LivoxDataType)
        raise LivoxDecodeError(
            f"data_type {raw_data_type} (0x{raw_data_type:02x}) is not a value in "
            f"livox_lidar_def.h; known: {known}"
        ) from error
    if data_type not in POINT_SIZE_BYTES:
        raise LivoxDecodeError(_undecodable_reason(data_type))
    if dot_num == 0:
        raise LivoxDecodeError("dot_num is 0: a point frame with no points is not a frame")
    if dot_num > MAX_POINTS_PER_FRAME:
        raise LivoxDecodeError(
            f"dot_num {dot_num} exceeds {MAX_POINTS_PER_FRAME}, the most points that "
            f"fit in one {_MAX_UDP_PAYLOAD_BYTES}-byte datagram — a corrupt header, "
            f"refused before allocating for it"
        )

    point_size = POINT_SIZE_BYTES[data_type]
    expected = HEADER_SIZE_BYTES + dot_num * point_size
    if len(payload) != expected:
        raise LivoxDecodeError(
            f"frame is {len(payload)} bytes but the header declares {dot_num} points "
            f"of {point_size} bytes ({data_type.name}), i.e. {expected} bytes — "
            f"truncated or over-long frames are refused, never partially decoded"
        )

    point_struct = _POINT_STRUCT[data_type]
    raw_points = tuple(point_struct.iter_unpack(payload[HEADER_SIZE_BYTES:]))
    return LivoxPointFrame(
        version=version,
        declared_length=declared_length,
        time_interval_ns=time_interval * 100,
        dot_num=dot_num,
        udp_cnt=udp_cnt,
        frame_cnt=frame_cnt,
        data_type=data_type,
        time_type=time_type,
        reserved=reserved,
        crc32=crc32,
        base_timestamp_ns=base_timestamp_ns,
        point_interval_ns=(time_interval * 100) // dot_num,
        xyz_scale_m=_XYZ_SCALE_M[data_type],
        raw_points=raw_points,
    )


def _undecodable_reason(data_type: LivoxDataType) -> str:
    if data_type is LivoxDataType.IMU:
        return (
            f"{data_type.name} (0x{data_type.value:02x}) is IMU data, not point data: it "
            f"arrives on port {IMU_DATA_PORT} as six float32s and this decoder does not "
            f"claim its units"
        )
    if data_type is LivoxDataType.SPHERICAL:
        return (
            f"{data_type.name} (0x{data_type.value:02x}) is DOCUMENTED but NOT DECODED in "
            f"card HW-3 (out of scope, not unknown): pub_handler.cpp:429-431 gives "
            f"theta/phi in 0.01 deg and depth in mm. Configure the LiDAR for Cartesian "
            f"output, or implement the spherical path and pin it against those lines"
        )
    return (
        f"{data_type.name} (0x{data_type.value:02x}) is DOCUMENTED but NOT DECODED in card "
        f"HW-3 (out of scope, not unknown): livox_lidar_def.h:174-185 defines "
        f"LivoxLidarDoubleEchoRawPoint (2 x 14 B) and pub_handler.cpp:469-482 decodes it. "
        f"Which echo a band bin should take is a B11 question, not a decoder detail"
    )


@dataclass(frozen=True, slots=True)
class FrameSequenceReport:
    """What a run of frames says about its own ordering. Reported, never fixed.

    Silently reordering or dropping is how a sweep with a hole in it becomes a
    scan that looks complete. Every count here is evidence for the box-day
    coverage measurement (HW-9), which is also why nothing in this module acts
    on it.
    """

    frames: int
    points: int
    udp_cnt_gaps: tuple[tuple[int, int], ...]
    duplicate_udp_cnt: tuple[int, ...]
    timestamp_regressions: tuple[tuple[int, int], ...]

    @property
    def contiguous(self) -> bool:
        return not (self.udp_cnt_gaps or self.duplicate_udp_cnt or self.timestamp_regressions)


def sequence_report(frames: Iterable[LivoxPointFrame]) -> FrameSequenceReport:
    """Ordering evidence for one run of frames. ``udp_cnt`` is a uint16 counter.

    A wrap from 65535 to 0 is the counter doing its job and is not a gap; a
    regression that is not a wrap is. Timestamps must not go backwards between
    frames: they carry the same clock, whichever ``time_type`` names it.
    """

    ordered = list(frames)
    gaps: list[tuple[int, int]] = []
    duplicates: list[int] = []
    regressions: list[tuple[int, int]] = []
    points = 0
    previous: LivoxPointFrame | None = None
    for frame in ordered:
        points += len(frame.raw_points)
        if previous is not None:
            expected = (previous.udp_cnt + 1) % 65536
            if frame.udp_cnt == previous.udp_cnt:
                duplicates.append(frame.udp_cnt)
            elif frame.udp_cnt != expected:
                gaps.append((previous.udp_cnt, frame.udp_cnt))
            if frame.base_timestamp_ns < previous.base_timestamp_ns:
                regressions.append((previous.base_timestamp_ns, frame.base_timestamp_ns))
        previous = frame
    return FrameSequenceReport(
        frames=len(ordered),
        points=points,
        udp_cnt_gaps=tuple(gaps),
        duplicate_udp_cnt=tuple(duplicates),
        timestamp_regressions=tuple(regressions),
    )


def receive_frames(
    sock: Any,
    *,
    max_frames: int,
    on_refusal: Callable[[LivoxDecodeError], None] | None = None,
    max_datagram_bytes: int = _MAX_UDP_PAYLOAD_BYTES,
) -> Iterator[LivoxPointFrame]:
    """Read up to ``max_frames`` datagrams off an ALREADY-BOUND socket.

    The only function in this package that touches a socket, and it neither
    creates, binds, configures nor closes one: the caller owns the socket and
    therefore owns the NIC/IP/port question that cannot be answered until the
    box is opened (Q-wire). That is what keeps :func:`parse_point_frame`
    testable with no network anywhere in the test suite.

    ``on_refusal`` is how a reader thread survives one corrupt datagram: given
    a callback, refusals are reported and the datagram skipped; left ``None``,
    the refusal propagates to the caller.
    """

    if max_frames <= 0:
        raise ValueError("max_frames must be positive")
    delivered = 0
    while delivered < max_frames:
        payload = sock.recv(max_datagram_bytes)
        try:
            frame = parse_point_frame(payload)
        except LivoxDecodeError as error:
            if on_refusal is None:
                raise
            on_refusal(error)
            continue
        delivered += 1
        yield frame


def build_point_frame(
    points: Sequence[tuple[int, int, int, int, int]],
    *,
    data_type: LivoxDataType = LivoxDataType.CARTESIAN_HIGH,
    version: int = 0,
    time_interval_raw: int = 1000,
    udp_cnt: int = 0,
    frame_cnt: int = 0,
    time_type: int = LivoxTimeType.NO_SYNC,
    reserved: bytes = b"\x00" * 12,
    crc32: int = 0,
    base_timestamp_ns: int = 0,
) -> bytes:
    """Serialise a frame in the layout of the table above.

    Product code, not test code, because it is the machine-readable statement
    of what this module believes the wire looks like: the round-trip test
    proves the parser against THIS, and box-day (HW-9) falsifies THIS against
    one real datagram. ``time_interval_raw`` is in the wire's own 0.1 us units.
    """

    if data_type not in POINT_SIZE_BYTES:
        raise LivoxDecodeError(_undecodable_reason(data_type))
    if len(reserved) != 12:
        raise LivoxDecodeError(f"reserved is 12 bytes, got {len(reserved)}")
    point_struct = _POINT_STRUCT[data_type]
    body = b"".join(point_struct.pack(*point) for point in points)
    length = HEADER_SIZE_BYTES + len(body)
    header = _HEADER_STRUCT.pack(
        version,
        length,
        time_interval_raw,
        len(points),
        udp_cnt,
        frame_cnt,
        int(data_type),
        int(time_type),
        reserved,
        crc32,
        base_timestamp_ns,
    )
    return header + body
