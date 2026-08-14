"""Bandwidth, storage and session-length arithmetic for a physical capture.

Card PS-E of tranche PS-1 (``scrum/20260813/task_1/README.md``). The plan says
the arithmetic was never done (``PHYSICAL_SESSION_PLAN.md:69-72``): an undecided
D455 resolution plus an unmeasured destination gives truncated bags
*indistinguishable from sensor dropouts*. This module does the arithmetic, and
does it in a way that can be checked line by line.

Three rules govern every number here, because a budget that lies costs a
session:

**A budget over-estimates or it refuses.** Fail-closed for a rate limit is not
"assume zero" — assuming zero is the permissive value. A channel with no load
model raises :class:`BudgetRefusedError` rather than contributing nothing, and
every assumption is taken at its worst plausible value with the assumption
named. :data:`LoadBasis` says, per channel, whether a number is derived from
pixel arithmetic, derived from a documented field list, assumed, or measured.

**Framing is measured, not estimated.** ``bytes_per_message`` on the wire is not
the payload: PS-B frames every message as ``uint32 len | envelope JSON | raw
device bytes`` inside an MCAP ``Message`` record. :func:`framing_bytes` obtains
that overhead by writing a real record with PS-B's own writer into an in-memory
handle and reading back the byte count it reports. It is exact for the channel
and sequence magnitude it is asked about, not a rule of thumb.

**A destination is unmeasured until somebody measures it.**
:func:`measure_sustained_write` writes real bytes to a real filesystem and
fsyncs them; :class:`WriteMeasurement` carries the host it ran on, and
:meth:`Budget.sustained_by` returns :attr:`SustainVerdict.UNMEASURED` — never
"ok" — when no measurement is supplied. The dev-host number in
``BANDWIDTH_BUDGET.md`` is labelled *dev-host, to be re-measured on the Orin*
for exactly this reason.

What this module deliberately does not do
-----------------------------------------
It states no power or thermal bound. The plan defers onboard
compute/power/thermal/payload characterisation to Wave 4 (``PLAN:1271``), so
how long an Orin + D455 payload runs off the Go2 battery is **unknown**, and a
guess would be the first false number in the dataset. :data:`UNKNOWNS` names
that and everything else this arithmetic cannot settle, and the budget document
carries the list verbatim.
"""

from __future__ import annotations

import argparse
import io
import math
import os
import platform
import shutil
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

# Absolute imports plus this bootstrap, following attest.py's pattern: the same
# file has to work as `python -m scripts.parcel_capture.<mod>` in this venv and
# as `python3 scripts/parcel_capture/<mod>.py` from a bare checkout on the Orin,
# where `parcel_robot` is not installed and relative imports have no package to
# resolve against.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from parcel_robot.capture import (  # after the deploy-path bootstrap above
    CHANNELS,
    UNCALIBRATED,
    CaptureEnvelope,
    Channel,
    ChannelHealth,
    ChannelPresence,
    channel,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture.record import (
    MinimalMcapWriter,
    frame_payload,
)

#: Bytes in a mebibyte and a gibibyte. Spelled out because MiB/MB confusion is
#: a 5% error on the headline number and 5% of 464 GiB/h is 23 GiB.
MIB = 1024 * 1024
GIB = 1024 * 1024 * 1024

#: Seconds in an hour, named so the GiB/hour arithmetic reads as arithmetic.
SECONDS_PER_HOUR = 3600.0

#: Smallest write a measurement may be taken over. A 5 ms burst measures the
#: page cache; this host has 246 GiB of RAM and would happily absorb one.
MIN_MEASUREMENT_BYTES = 256 * MIB

#: Smallest wall time a measurement may be taken over, for the same reason.
MIN_MEASUREMENT_SECONDS = 1.0

#: Default headroom over the raw estimate, matching PS-B's ``SpaceBudget``.
DEFAULT_MARGIN = 0.15


class BudgetError(RuntimeError):
    """Base for every refusal raised by this module."""


class BudgetRefusedError(BudgetError):
    """A number that cannot be derived honestly is not produced at all."""


class LoadBasis(str, Enum):
    """Where a per-channel byte figure came from. Never decoration.

    The budget document prints this beside every row, so a reader can see at a
    glance which lines are arithmetic and which are engineering assumptions
    waiting to be falsified at preflight.
    """

    #: width x height x bytes-per-pixel x frames-per-second. Exact.
    DERIVED_PIXELS = "derived_pixels"
    #: Summed from a documented message field list. Exact given the field list,
    #: which is itself transcribed and therefore falsifiable.
    DERIVED_FIELDS = "derived_fields"
    #: A stated engineering assumption, taken at its worst plausible value.
    ASSUMED_WORST_CASE = "assumed_worst_case"
    #: Observed from a real message: PS-D's ``SampleReceipt.payload_bytes``.
    MEASURED = "measured"

    @property
    def is_measurement(self) -> bool:
        return self is LoadBasis.MEASURED


class SustainVerdict(str, Enum):
    """Can the destination keep up? ``UNMEASURED`` is never a pass."""

    SUSTAINS = "sustains"
    DOES_NOT_SUSTAIN = "does_not_sustain"
    #: No measurement was supplied. Fail closed: this is not permission.
    UNMEASURED = "unmeasured"

    @property
    def is_pass(self) -> bool:
        return self is SustainVerdict.SUSTAINS


def _positive(value: object, *, field: str, allow_zero: bool = False) -> float:
    """A finite positive number or a refusal. Bools are not numbers."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BudgetRefusedError(f"{field} must be a number, got {type(value).__name__} {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise BudgetRefusedError(f"{field} must be finite, got {value!r}")
    if number < 0.0 or (number == 0.0 and not allow_zero):
        raise BudgetRefusedError(
            f"{field} must be {'non-negative' if allow_zero else 'positive'}, got {value!r}"
        )
    return number


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BudgetRefusedError(f"{field} must be an int, got {type(value).__name__} {value!r}")
    if value <= 0:
        raise BudgetRefusedError(f"{field} must be positive, got {value!r}")
    return value


# ---------------------------------------------------------------------------
# Framing: measured against PS-B's own writer, never estimated
# ---------------------------------------------------------------------------


def framing_bytes(
    entry: Channel,
    *,
    sequence: int = 0,
    origin: EvidenceOrigin = EvidenceOrigin.PHYSICAL,
    fixture_label: str | None = None,
    calibration_ref: str = UNCALIBRATED,
) -> int:
    """Bytes an empty-payload message occupies on disk, for this channel.

    Obtained by writing a real ``Message`` record with PS-B's
    :class:`~scripts.parcel_capture.record.MinimalMcapWriter` into an in-memory
    handle and taking the byte count it returns. Nothing here re-implements the
    wire format, so a change to PS-B's framing moves this number rather than
    silently invalidating the budget.

    It depends on the channel (the id and frame travel in the envelope JSON) and
    on the *magnitude* of the sequence number: message 1,000,000 of a session
    costs six digits more than message 0. Callers that need an upper bound pass
    the session's final sequence.
    """

    envelope = CaptureEnvelope(
        channel_id=entry.channel_id,
        sequence=_sequence_floor(sequence),
        source_timestamp_ns=None,
        host_monotonic_ns=0,
        host_realtime_ns=0,
        frame_id=entry.frame_id,
        origin=origin,
        fixture_label=fixture_label,
        calibration_ref=calibration_ref,
        health=ChannelHealth.UNKNOWN,
    )
    handle = io.BytesIO()
    writer = MinimalMcapWriter(handle)
    writer.register(entry)
    return writer.write_message(
        entry.channel_id,
        sequence=envelope.sequence,
        log_time_ns=0,
        publish_time_ns=0,
        data=frame_payload(envelope, b""),
    )


def _sequence_floor(sequence: object) -> int:
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise BudgetRefusedError(f"sequence must be a non-negative int, got {sequence!r}")
    return sequence


# ---------------------------------------------------------------------------
# Per-channel load models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelLoad:
    """One channel's offered load: how often, and how big.

    ``payload_bytes_per_message`` is the *device* payload. The bytes that reach
    the platter are that plus :func:`framing_bytes`, which the budget adds.
    """

    channel_id: str
    messages_per_second: float
    payload_bytes_per_message: int
    basis: LoadBasis
    derivation: str

    def __post_init__(self) -> None:
        channel(self.channel_id)  # unknown id is a refusal, per PS-A
        _positive(self.messages_per_second, field=f"{self.channel_id}.messages_per_second")
        _positive_int(
            self.payload_bytes_per_message, field=f"{self.channel_id}.payload_bytes_per_message"
        )
        if not isinstance(self.basis, LoadBasis):
            raise BudgetRefusedError(
                f"{self.channel_id}: basis must be a LoadBasis member, got {self.basis!r}"
            )
        if not self.derivation.strip():
            raise BudgetRefusedError(
                f"{self.channel_id}: every load must show its working — an unexplained "
                f"number in a budget is a number nobody can check"
            )

    @property
    def payload_bytes_per_second(self) -> float:
        return self.messages_per_second * self.payload_bytes_per_message


#: Point size of a ``PointCloud2`` carrying x, y, z, intensity as float32.
POINT_STEP_BYTES = 16

#: Points per second assumed for a Unitree built-in / add-on LiDAR. The
#: built-in unit's model is repo-contradicted (Unitree says L2,
#: ``P5_PROCUREMENT_BOM.md:35`` says L1 — ``CHANNEL_MATRIX.md:78-80``), so this
#: takes twice the 21,600 pts/s the L1 is quoted at, i.e. the worse of the two
#: readings. PS-D's preflight measures the real payload and
#: :func:`loads_from_preflight` replaces the assumption with the measurement.
ASSUMED_LIDAR_POINTS_PER_SECOND = 43_200.0

#: Worst-case bitrate assumed for the Go2 front camera's H.264 stream (4 Mb/s).
#: Unverified: PS-H's matrix rewrite established that this stream is RTP over
#: multicast 230.1.1.1:1720 rather than a topic, and nobody in this repo has
#: connected to it.
ASSUMED_FRONT_CAMERA_BITS_PER_SECOND = 4_000_000.0

#: Worst-case bytes per message for the front camera's DDS path, corrected by
#: PS-H (``RISK_ASSESSMENT.md`` row 1). ``Go2FrontVideoData_`` carries
#: ``video720p``/``video360p``/``video180p`` as JPEG octet sequences, so the
#: worst case is all three populated: ~150 KB + ~40 KB + ~12 KB. JPEG per frame
#: is roughly an order of magnitude more than the H.264 assumption the PS-1
#: budget applied to this channel, which is why the correction matters to the
#: session and not only to the document.
ASSUMED_FRONT_CAMERA_JPEG_BYTES = 208_896.0

#: Worst-case publish rate assumed for the event-driven handheld. Silence is
#: normal on this channel; a budget may not assume silence.
ASSUMED_WIRELESS_CONTROLLER_HZ = 100.0


def _cloud_load(channel_id: str, *, rate_hz: float, points_per_second: float, note: str) -> ChannelLoad:
    """A point-cloud channel: bytes/second is set by the device's point rate.

    Scan rate divides the same points into more or fewer messages, so lowering
    the rate saves framing, not pixels.
    """

    points_per_message = points_per_second / rate_hz
    header = 128  # PointCloud2 header + field descriptors, transcribed shape
    payload = round(points_per_message * POINT_STEP_BYTES) + header
    return ChannelLoad(
        channel_id=channel_id,
        messages_per_second=rate_hz,
        payload_bytes_per_message=payload,
        basis=LoadBasis.ASSUMED_WORST_CASE,
        derivation=(
            f"{points_per_second:g} pts/s / {rate_hz:g} Hz = {points_per_message:g} pts/msg "
            f"x {POINT_STEP_BYTES} B (x,y,z,intensity float32) + {header} B header. {note}"
        ),
    )


#: Every channel in the PS-A matrix whose load does not depend on a D455
#: profile. :func:`build_budget` refuses if any matrix channel is missing from
#: this mapping or from the profile's own loads — a channel with no model must
#: not silently contribute zero bytes.
def static_loads() -> dict[str, ChannelLoad]:
    """Load models for the non-D455 channels. One entry per matrix channel."""

    loads = [
        _cloud_load(
            "go2.utlidar.cloud",
            rate_hz=10.0,
            points_per_second=ASSUMED_LIDAR_POINTS_PER_SECOND,
            note=(
                "Worst case of the unresolved L1-vs-L2 contradiction on the built-in "
                "unit (CHANNEL_MATRIX.md:78-80): twice the L1's quoted 21,600 pts/s."
            ),
        ),
        ChannelLoad(
            channel_id="go2.utlidar.imu",
            messages_per_second=200.0,
            payload_bytes_per_message=376,
            basis=LoadBasis.DERIVED_FIELDS,
            derivation=(
                "sensor_msgs/Imu: header ~40 B + quaternion 4xf64 (32) + covariance 9xf64 "
                "(72) + angular_velocity 3xf64 (24) + covariance (72) + linear_acceleration "
                "3xf64 (24) + covariance (72) = 376 B."
            ),
        ),
        ChannelLoad(
            channel_id="go2.utlidar.robot_pose",
            messages_per_second=10.0,
            payload_bytes_per_message=96,
            basis=LoadBasis.DERIVED_FIELDS,
            derivation=(
                "geometry_msgs/PoseStamped: header ~40 B + position 3xf64 (24) + "
                "orientation 4xf64 (32) = 96 B."
            ),
        ),
        ChannelLoad(
            channel_id="go2.utlidar.voxel_map",
            messages_per_second=1.0,
            payload_bytes_per_message=65_536,
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                "A compressed occupancy blob inside a String_. Size unknown to this repo "
                "(PS-A calls this the least certain entry in its table); 64 KiB is taken as "
                "a worst case for a compressed voxel grid. 1 Hz, so it is 64 KiB/s even if "
                "the assumption is 10x wrong."
            ),
        ),
        ChannelLoad(
            channel_id="go2.sportmodestate",
            messages_per_second=50.0,
            payload_bytes_per_message=256,
            basis=LoadBasis.DERIVED_FIELDS,
            derivation=(
                "unitree_go/SportModeState: stamp+error_code (16) + imu_state (53) + "
                "mode/progress/gait/foot_raise_height (4) + position 3xf32 (12) + "
                "body_height (4) + velocity 3xf32 (12) + yaw_speed (4) + range_obstacle "
                "4xf32 (16) + foot_force 4xi16 (8) + foot_position_body 12xf32 (48) + "
                "foot_speed_body 12xf32 (48) = 225 B, rounded up to 256 for CDR padding."
            ),
        ),
        ChannelLoad(
            channel_id="go2.lowstate",
            messages_per_second=500.0,
            payload_bytes_per_message=1_056,
            basis=LoadBasis.DERIVED_FIELDS,
            derivation=(
                "unitree_go/LowState: head/level_flag/sn/version/bandwidth (22) + imu_state "
                "(53) + motor_state 20x(mode+q,dq,ddq,tau_est+q_raw,dq_raw,ddq_raw+temp+"
                "lost+reserve = 42) = 840 + bms_state (44) + foot_force 4xi16 (8) + "
                "foot_force_est 4xi16 (8) + tick (4) + wireless_remote[40] (40) + reserve "
                "(4) + crc (4) = 1,027 B, rounded up to 1,056 for CDR padding. This is the "
                "single largest non-camera channel: 500 Hz x 1,056 B."
            ),
        ),
        ChannelLoad(
            channel_id="go2.lf.lowstate",
            messages_per_second=10.0,
            payload_bytes_per_message=1_056,
            basis=LoadBasis.DERIVED_FIELDS,
            derivation="Same message as go2.lowstate, downsampled to 10 Hz (matrix row 7).",
        ),
        ChannelLoad(
            channel_id="go2.lf.sportmodestate",
            messages_per_second=10.0,
            payload_bytes_per_message=256,
            basis=LoadBasis.DERIVED_FIELDS,
            derivation="Same message as go2.sportmodestate, downsampled to 10 Hz (row 7).",
        ),
        ChannelLoad(
            channel_id="go2.wirelesscontroller",
            messages_per_second=ASSUMED_WIRELESS_CONTROLLER_HZ,
            payload_bytes_per_message=32,
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                "unitree_go/WirelessController: lx,ly,rx,ry f32 (16) + keys u16 (2) + head "
                "(2) = 20 B, rounded to 32. EVENT_DRIVEN, so no nominal rate exists; a "
                "budget may not assume silence, so 100 Hz is taken as a continuously-held "
                "stick. NOTE: at 32 B of payload the framing costs ~11x the message."
            ),
        ),
        ChannelLoad(
            channel_id="go2.front_camera",
            messages_per_second=33.0,
            payload_bytes_per_message=int(ASSUMED_FRONT_CAMERA_JPEG_BYTES),
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                "CORRECTED BY PS-H (RISK_ASSESSMENT.md row 1): the front camera IS on "
                "the DDS topic set, as rt/frontvideostream carrying Go2FrontVideoData_ "
                "= time_frame + video720p/video360p/video180p, JPEG PER FRAME at ~33 Hz. "
                "Worst case is all three resolutions populated: ~150 KB (720p) + ~40 KB "
                "(360p) + ~12 KB (180p) = 204 KiB/frame. The PS-1 budget modelled this "
                "channel as 4 Mb/s H.264 and so UNDER-STATED it by ~10x; the H.264 "
                "assumption now sits on go2.front_camera_h264 where it belongs."
            ),
        ),
        ChannelLoad(
            channel_id="go2.front_camera_h264",
            messages_per_second=30.0,
            payload_bytes_per_message=int(ASSUMED_FRONT_CAMERA_BITS_PER_SECOND / 8 / 30.0),
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                f"H.264 elementary stream as RTP over multicast 230.1.1.1:1720 at an "
                f"assumed {ASSUMED_FRONT_CAMERA_BITS_PER_SECOND / 1e6:g} Mb/s and 30 fps. "
                f"Rate and bitrate are both UNKNOWN to this repo (PS-A marks the channel "
                f"RateKind.UNKNOWN); this is a worst case, not a reading. Same camera as "
                f"go2.front_camera — budgeting both is the fail-closed choice because we "
                f"do not yet know which path we can actually capture."
            ),
        ),
        ChannelLoad(
            channel_id="go2.utlidar.lidar_state",
            messages_per_second=1.0,
            payload_bytes_per_message=256,
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                "unitree_go/LidarState: stamp + firmware/software/SDK version strings + "
                "serial number + rotation speeds + error state + cloud/IMU frequency, "
                "packet-loss rate and size. Variable-length strings dominate; 256 B is a "
                "generous upper bound at 1 Hz."
            ),
        ),
        _cloud_load(
            "go2.utlidar.cloud_deskewed",
            rate_hz=10.0,
            points_per_second=ASSUMED_LIDAR_POINTS_PER_SECOND,
            note=(
                "The motion-compensated twin of utlidar/cloud, added by PS-H. Same point "
                "rate, therefore the same worst case; recording both is what lets us see "
                "what the vendor deskew does to our data."
            ),
        ),
        ChannelLoad(
            channel_id="go2.utlidar.robot_odom",
            messages_per_second=10.0,
            payload_bytes_per_message=736,
            basis=LoadBasis.DERIVED_FIELDS,
            derivation=(
                "nav_msgs/Odometry: header ~40 B + child_frame_id ~16 + pose 7xf64 (56) + "
                "pose covariance 36xf64 (288) + twist 6xf64 (48) + twist covariance "
                "36xf64 (288) = 736 B. The two covariance blocks are most of it, and they "
                "are the reason this is not a duplicate of utlidar/robot_pose."
            ),
        ),
        ChannelLoad(
            channel_id="go2.utlidar.switch",
            messages_per_second=1.0,
            payload_bytes_per_message=32,
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                "std_msgs/String carrying 'ON'/'OFF'. EVENT_DRIVEN, and we expect near "
                "silence — but a budget may not assume silence, so 1 Hz is taken as a "
                "worst case for something toggling the LiDAR repeatedly. Subscribe-only: "
                "this table budgets what we READ, and nothing in the capture stack can "
                "write to a transport."
            ),
        ),
        ChannelLoad(
            channel_id="go2.uwbstate",
            messages_per_second=20.0,
            payload_bytes_per_message=64,
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                "unitree_go/UwbState at an assumed 20 Hz, mirroring the uwb.owner_fob "
                "assumption because they are two candidate paths to one measurement. "
                "CONFIRM_ON_HAND: the module may not be fitted, and assuming a channel "
                "away is the permissive error."
            ),
        ),
        _cloud_load(
            "l2.cloud",
            rate_hz=20.0,
            points_per_second=ASSUMED_LIDAR_POINTS_PER_SECOND,
            note=(
                "Add-on L2 at the top of the matrix's 10-20 Hz range. Scan rate is a device "
                "setting PS-D reads off the unit; a higher rate costs framing, not points."
            ),
        ),
        ChannelLoad(
            channel_id="l2.imu",
            messages_per_second=200.0,
            payload_bytes_per_message=64,
            basis=LoadBasis.DERIVED_FIELDS,
            derivation=(
                "unilidar_sdk2 IMU: stamp (8) + id (4) + quaternion 4xf32 (16) + gyro 3xf32 "
                "(12) + accel 3xf32 (12) = 52 B, rounded to 64."
            ),
        ),
        ChannelLoad(
            channel_id="orin.tegrastats",
            messages_per_second=1.0,
            payload_bytes_per_message=320,
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                "One tegrastats line at the default 1000 ms interval. Line length varies "
                "with the rails reported; 320 B is a generous upper bound."
            ),
        ),
        ChannelLoad(
            channel_id="gnss.zed_f9p",
            messages_per_second=10.0,
            payload_bytes_per_message=512,
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                "A full NMEA sentence set at 10 Hz navigation rate. CONFIRM_ON_HAND: the "
                "receiver may not exist, and a budget includes it because assuming a "
                "channel away is the permissive error."
            ),
        ),
        ChannelLoad(
            channel_id="uwb.owner_fob",
            messages_per_second=20.0,
            payload_bytes_per_message=64,
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                "Range/bearing at an assumed 20 Hz. Protocol and rate are both undocumented "
                "to us (PS-A marks it RateKind.UNKNOWN)."
            ),
        ),
        ChannelLoad(
            channel_id="mic.xvf3800",
            messages_per_second=100.0,
            payload_bytes_per_message=1_920,
            basis=LoadBasis.ASSUMED_WORST_CASE,
            derivation=(
                "6 channels (4 mic + 2 AEC ref) x 16 kHz x 16 bit = 192,000 B/s, delivered "
                "in 10 ms blocks. AWAITING_HARDWARE: excluded from today's total unless "
                "include_awaiting=True, and shown so it drops in without redesign."
            ),
        ),
    ]
    return {load.channel_id: load for load in loads}


# ---------------------------------------------------------------------------
# The D455 decision
# ---------------------------------------------------------------------------

#: Resolution/rate combinations the D455 is documented to offer for colour and
#: depth. VENDOR-DECLARED, unconfirmed: nobody in this repo has enumerated a
#: real device's profiles. PS-D reads them off the unit at preflight. A mode not
#: in this set is refused rather than computed, so a typo cannot become a plan.
D455_DECLARED_MODES: frozenset[tuple[int, int, int]] = frozenset(
    {
        (1280, 720, 30),
        (1280, 720, 15),
        (1280, 720, 5),
        (848, 480, 90),
        (848, 480, 60),
        (848, 480, 30),
        (848, 480, 15),
        (848, 480, 5),
        (640, 480, 90),
        (640, 480, 60),
        (640, 480, 30),
        (640, 480, 15),
        (640, 360, 30),
        (424, 240, 30),
    }
)

#: Bytes per pixel of each D455 stream format, from the format name itself.
BYTES_PER_PIXEL: Mapping[str, int] = {"rgb8": 3, "z16": 2, "y8": 1}

#: Accelerometer and gyroscope rates the D455's BMI055 offers. The worst case
#: of each is the default here, per the fail-closed rule.
D455_ACCEL_RATES_HZ = (63.0, 250.0)
D455_GYRO_RATES_HZ = (200.0, 400.0)


@dataclass(frozen=True)
class D455Profile:
    """One D455 configuration: the only real tuning knob in the budget.

    ``CHANNEL_MATRIX.md:91`` calls this a budget decision rather than a default,
    and this type is what makes it one — every field has to be chosen, and an
    undeclared mode is refused.
    """

    width: int
    height: int
    fps: int
    color: bool = True
    depth: bool = True
    infrared: bool = True
    accel_hz: float = max(D455_ACCEL_RATES_HZ)
    gyro_hz: float = max(D455_GYRO_RATES_HZ)

    def __post_init__(self) -> None:
        _positive_int(self.width, field="width")
        _positive_int(self.height, field="height")
        _positive_int(self.fps, field="fps")
        for name in ("color", "depth", "infrared"):
            if not isinstance(getattr(self, name), bool):
                raise BudgetRefusedError(f"D455Profile.{name} must be a bool")
        _positive(self.accel_hz, field="accel_hz")
        _positive(self.gyro_hz, field="gyro_hz")
        if (self.width, self.height, self.fps) not in D455_DECLARED_MODES:
            raise BudgetRefusedError(
                f"{self.width}x{self.height}@{self.fps} is not a vendor-declared D455 mode; "
                f"declared: {sorted(D455_DECLARED_MODES)}. A mode nobody confirmed is not a "
                f"mode — add it to D455_DECLARED_MODES only once PS-D has read it off the "
                f"device."
            )
        if not (self.color or self.depth or self.infrared):
            raise BudgetRefusedError(
                "a D455 profile with no image stream is not a profile; if the camera is off, "
                "say so by excluding its channels, not by configuring an empty one"
            )

    @property
    def label(self) -> str:
        streams = "".join(
            flag
            for flag, on in (("C", self.color), ("D", self.depth), ("I", self.infrared))
            if on
        )
        return f"{self.width}x{self.height}@{self.fps} {streams or '-'}"

    @property
    def pixels(self) -> int:
        return self.width * self.height

    def stream_bytes_per_frame(self, stream: str) -> int:
        """Exact: pixels x bytes-per-pixel. No compression is applied anywhere."""

        try:
            return self.pixels * BYTES_PER_PIXEL[stream]
        except KeyError as error:
            raise BudgetRefusedError(f"unknown D455 stream format {stream!r}") from error

    def loads(self) -> dict[str, ChannelLoad]:
        """Load models for the six D455 channels of the PS-A matrix.

        A disabled image stream contributes **no entry**, which is how
        :func:`build_budget` tells "this channel is not being recorded" from
        "this channel has no model" — the first is a decision, the second is a
        defect.
        """

        pixels = f"{self.width}x{self.height} = {self.pixels:,} px"
        loads: list[ChannelLoad] = []
        if self.color:
            loads.append(
                ChannelLoad(
                    channel_id="d455.color",
                    messages_per_second=float(self.fps),
                    payload_bytes_per_message=self.stream_bytes_per_frame("rgb8"),
                    basis=LoadBasis.DERIVED_PIXELS,
                    derivation=(
                        f"{pixels} x 3 B/px (RGB8) = "
                        f"{self.stream_bytes_per_frame('rgb8'):,} B/frame x {self.fps} fps."
                    ),
                )
            )
        if self.depth:
            loads.append(
                ChannelLoad(
                    channel_id="d455.depth",
                    messages_per_second=float(self.fps),
                    payload_bytes_per_message=self.stream_bytes_per_frame("z16"),
                    basis=LoadBasis.DERIVED_PIXELS,
                    derivation=(
                        f"{pixels} x 2 B/px (Z16) = "
                        f"{self.stream_bytes_per_frame('z16'):,} B/frame x {self.fps} fps."
                    ),
                )
            )
        if self.infrared:
            for channel_id, eye in (("d455.infra1", "left"), ("d455.infra2", "right")):
                loads.append(
                    ChannelLoad(
                        channel_id=channel_id,
                        messages_per_second=float(self.fps),
                        payload_bytes_per_message=self.stream_bytes_per_frame("y8"),
                        basis=LoadBasis.DERIVED_PIXELS,
                        derivation=(
                            f"{pixels} x 1 B/px (Y8, {eye}) = "
                            f"{self.stream_bytes_per_frame('y8'):,} B/frame x {self.fps} fps."
                        ),
                    )
                )
        loads.append(
            ChannelLoad(
                channel_id="d455.accel",
                messages_per_second=self.accel_hz,
                payload_bytes_per_message=32,
                basis=LoadBasis.DERIVED_FIELDS,
                derivation=(
                    f"BMI055 accelerometer: 3xf32 (12) + timestamp/domain (16) = 28 B, "
                    f"rounded to 32, at {self.accel_hz:g} Hz."
                ),
            )
        )
        loads.append(
            ChannelLoad(
                channel_id="d455.gyro",
                messages_per_second=self.gyro_hz,
                payload_bytes_per_message=32,
                basis=LoadBasis.DERIVED_FIELDS,
                derivation=(
                    f"BMI055 gyroscope: 3xf32 (12) + timestamp/domain (16) = 28 B, rounded "
                    f"to 32, at {self.gyro_hz:g} Hz."
                ),
            )
        )
        return {load.channel_id: load for load in loads}

    def configured_rates(self) -> dict[str, float]:
        """The rates PS-B's sidecar needs for these ``CONFIGURED`` channels.

        Without this, ``observe_channels`` rules every D455 channel
        ``unassessable`` — correctly, because nobody chose a rate. Choosing one
        here is what turns the budget decision into an assertable expectation.
        """

        return {load.channel_id: load.messages_per_second for load in self.loads().values()}


#: The profiles the budget document tables. First is the plan's anchor.
CANDIDATE_PROFILES: tuple[D455Profile, ...] = (
    D455Profile(1280, 720, 30, infrared=False),
    D455Profile(1280, 720, 30),
    D455Profile(1280, 720, 15),
    D455Profile(848, 480, 60),
    D455Profile(848, 480, 30, infrared=False),
    D455Profile(848, 480, 30),
    D455Profile(848, 480, 15),
    D455Profile(848, 480, 30, color=False),
    D455Profile(640, 480, 30),
    D455Profile(424, 240, 30),
)


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetRow:
    """One channel's contribution, payload and framing separated."""

    channel_id: str
    human_name: str
    criticality: str
    presence: str
    messages_per_second: float
    payload_bytes_per_message: int
    framing_bytes_per_message: int
    basis: str
    derivation: str

    @property
    def bytes_per_second(self) -> float:
        return self.messages_per_second * (
            self.payload_bytes_per_message + self.framing_bytes_per_message
        )

    @property
    def framing_bytes_per_second(self) -> float:
        return self.messages_per_second * self.framing_bytes_per_message

    @property
    def mib_per_second(self) -> float:
        return self.bytes_per_second / MIB

    @property
    def gib_per_hour(self) -> float:
        return self.bytes_per_second * SECONDS_PER_HOUR / GIB

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "human_name": self.human_name,
            "criticality": self.criticality,
            "presence": self.presence,
            "messages_per_second": self.messages_per_second,
            "payload_bytes_per_message": self.payload_bytes_per_message,
            "framing_bytes_per_message": self.framing_bytes_per_message,
            "bytes_per_second": round(self.bytes_per_second, 3),
            "mib_per_second": round(self.mib_per_second, 6),
            "gib_per_hour": round(self.gib_per_hour, 6),
            "basis": self.basis,
            "derivation": self.derivation,
        }


@dataclass(frozen=True)
class Budget:
    """The whole rig's offered load, and what it implies for a session."""

    profile: D455Profile
    rows: tuple[BudgetRow, ...]
    excluded: tuple[str, ...]
    session_duration_s: float
    margin: float

    def __post_init__(self) -> None:
        _positive(self.session_duration_s, field="session_duration_s")
        _positive(self.margin, field="margin", allow_zero=True)
        if not self.rows:
            raise BudgetRefusedError("a budget with no channels budgets nothing")

    @property
    def bytes_per_second(self) -> float:
        return math.fsum(row.bytes_per_second for row in self.rows)

    @property
    def payload_bytes_per_second(self) -> float:
        return math.fsum(
            row.messages_per_second * row.payload_bytes_per_message for row in self.rows
        )

    @property
    def framing_bytes_per_second(self) -> float:
        return math.fsum(row.framing_bytes_per_second for row in self.rows)

    @property
    def messages_per_second(self) -> float:
        return math.fsum(row.messages_per_second for row in self.rows)

    @property
    def mib_per_second(self) -> float:
        return self.bytes_per_second / MIB

    @property
    def gib_per_hour(self) -> float:
        return self.bytes_per_second * SECONDS_PER_HOUR / GIB

    @property
    def camera_bytes_per_second(self) -> float:
        return math.fsum(
            row.bytes_per_second for row in self.rows if row.channel_id.startswith("d455.")
        )

    def required_bytes(self, duration_s: float | None = None) -> int:
        """Bytes to reserve for a take, including the margin. Rounded up."""

        seconds = self.session_duration_s if duration_s is None else _positive(
            duration_s, field="duration_s"
        )
        return math.ceil(self.bytes_per_second * seconds * (1.0 + self.margin))

    def required_free_gib(self, duration_s: float | None = None) -> float:
        """What PS-D's ``--required-free-gib`` wants. Rounded UP to 0.1 GiB."""

        return math.ceil(self.required_bytes(duration_s) / GIB * 10.0) / 10.0

    def session_hours(self, free_bytes: int) -> float:
        """How long this configuration can record into ``free_bytes``.

        Fail closed: a negative or non-integer free-space figure is a refusal,
        not an optimistic default. Unknown free space is *not* a long session.
        """

        if isinstance(free_bytes, bool) or not isinstance(free_bytes, int):
            raise BudgetRefusedError(
                f"free_bytes must be an int (from shutil.disk_usage or PS-D's preflight), "
                f"got {type(free_bytes).__name__} {free_bytes!r}"
            )
        if free_bytes < 0:
            raise BudgetRefusedError(f"free_bytes must be non-negative, got {free_bytes}")
        usable = free_bytes / (1.0 + self.margin)
        return usable / self.bytes_per_second / SECONDS_PER_HOUR

    def sustained_by(self, measurement: WriteMeasurement | None) -> SustainVerdict:
        """Does a measured destination keep up? No measurement is not a pass."""

        if measurement is None:
            return SustainVerdict.UNMEASURED
        if not isinstance(measurement, WriteMeasurement):
            raise BudgetRefusedError(
                f"sustained_by needs a WriteMeasurement or None, got "
                f"{type(measurement).__name__} — a bare number is not a measurement"
            )
        return (
            SustainVerdict.SUSTAINS
            if measurement.bytes_per_second >= self.bytes_per_second
            else SustainVerdict.DOES_NOT_SUSTAIN
        )

    def headroom(self, measurement: WriteMeasurement) -> float:
        """Measured write rate divided by required rate. Below 1.0 is a loss."""

        if not isinstance(measurement, WriteMeasurement):
            raise BudgetRefusedError("headroom needs a WriteMeasurement")
        return measurement.bytes_per_second / self.bytes_per_second

    def space_budget_kwargs(self, duration_s: float | None = None) -> dict[str, float]:
        """Arguments for PS-B's ``SpaceBudget``. The recorder refuses without one."""

        return {
            "bytes_per_second": self.bytes_per_second,
            "duration_s": self.session_duration_s if duration_s is None else float(duration_s),
            "margin": self.margin,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.label,
            "session_duration_s": self.session_duration_s,
            "margin": self.margin,
            "bytes_per_second": round(self.bytes_per_second, 3),
            "payload_bytes_per_second": round(self.payload_bytes_per_second, 3),
            "framing_bytes_per_second": round(self.framing_bytes_per_second, 3),
            "messages_per_second": round(self.messages_per_second, 3),
            "mib_per_second": round(self.mib_per_second, 6),
            "gib_per_hour": round(self.gib_per_hour, 6),
            "camera_fraction": round(self.camera_bytes_per_second / self.bytes_per_second, 6),
            "required_bytes": self.required_bytes(),
            "required_free_gib": self.required_free_gib(),
            "excluded_channels": list(self.excluded),
            "rows": [row.to_dict() for row in self.rows],
            "unknowns": list(UNKNOWNS),
        }


def build_budget(
    profile: D455Profile,
    *,
    session_duration_s: float = 3600.0,
    channels: Sequence[Channel] = CHANNELS,
    include_awaiting: bool = False,
    loads: Mapping[str, ChannelLoad] | None = None,
    margin: float = DEFAULT_MARGIN,
) -> Budget:
    """The whole arithmetic, for one D455 profile.

    Refuses if any recorded channel has no load model. That refusal is the
    fail-closed rule doing its job: a channel silently contributing zero bytes
    is how a budget under-states a session and how a bag gets truncated.
    """

    if not isinstance(profile, D455Profile):
        raise BudgetRefusedError(f"profile must be a D455Profile, got {type(profile).__name__}")
    model = dict(static_loads())
    model.update(profile.loads())
    if loads is not None:
        for key, value in loads.items():
            if not isinstance(value, ChannelLoad):
                raise BudgetRefusedError(f"override for {key!r} must be a ChannelLoad")
            if value.channel_id != key:
                raise BudgetRefusedError(
                    f"override key {key!r} does not match load {value.channel_id!r}"
                )
            model[key] = value

    duration = _positive(session_duration_s, field="session_duration_s")
    rows: list[BudgetRow] = []
    excluded: list[str] = []
    for entry in channels:
        if entry.presence is ChannelPresence.AWAITING_HARDWARE and not include_awaiting:
            excluded.append(entry.channel_id)
            continue
        load = model.get(entry.channel_id)
        if load is None:
            if entry.device.value == "d455":
                # A disabled image stream is a decision, and the decision is
                # recorded rather than being mistaken for a missing model.
                excluded.append(entry.channel_id)
                continue
            raise BudgetRefusedError(
                f"{entry.channel_id} is in the PS-A matrix and has no load model. A channel "
                f"with no model must never contribute zero bytes to a budget — add a "
                f"ChannelLoad with its derivation, or exclude it explicitly."
            )
        final_sequence = int(load.messages_per_second * duration)
        rows.append(
            BudgetRow(
                channel_id=entry.channel_id,
                human_name=entry.human_name,
                criticality=entry.criticality.value,
                presence=entry.presence.value,
                messages_per_second=load.messages_per_second,
                payload_bytes_per_message=load.payload_bytes_per_message,
                framing_bytes_per_message=framing_bytes(entry, sequence=final_sequence),
                basis=load.basis.value,
                derivation=load.derivation,
            )
        )
    return Budget(
        profile=profile,
        rows=tuple(rows),
        excluded=tuple(excluded),
        session_duration_s=duration,
        margin=margin,
    )


def loads_from_preflight(
    report: Any,
    payload_bytes: Mapping[str, float],
    *,
    minimum_messages: int = 1,
) -> dict[str, ChannelLoad]:
    """Replace assumptions with what the rig actually delivered.

    PS-D's ``ChannelProbe`` supplies the *rate* half of the measurement
    directly (``observed_rate_hz`` over a bounded window). It does **not**
    supply the size half: ``SampleReceipt.payload_bytes`` is validated per
    receipt and then discarded, and the only surviving trace is the first
    receipt's size inside the prose ``evidence`` string. So ``payload_bytes``
    is a required argument here rather than something this function digs out —
    parsing a sentence for a number a budget depends on would be worse than
    asking for it. (Recorded as a finding in ``PSE_STATUS.md``; the one-line
    fix belongs to PS-D, not here.)

    Only channels that delivered ``minimum_messages`` *and* have a supplied
    size are replaced. A silent channel keeps its assumed model, because a
    channel that published nothing during a 12-second probe has not proved it
    will publish nothing for an hour — dropping it would be the permissive
    error.
    """

    if not isinstance(payload_bytes, Mapping):
        raise BudgetRefusedError(
            f"payload_bytes must be a mapping of channel_id -> observed bytes, got "
            f"{type(payload_bytes).__name__}"
        )
    measured: dict[str, ChannelLoad] = {}
    for probe in getattr(report, "channels", ()):
        rate = probe.observed_rate_hz
        size = payload_bytes.get(probe.channel_id)
        if probe.messages_received < minimum_messages or rate is None or size is None:
            continue
        measured[probe.channel_id] = ChannelLoad(
            channel_id=probe.channel_id,
            messages_per_second=float(rate),
            payload_bytes_per_message=math.ceil(_positive(size, field=probe.channel_id)),
            basis=LoadBasis.MEASURED,
            derivation=(
                f"PS-D preflight: {probe.messages_received} message(s) over a "
                f"{probe.window_s:g} s window at {rate:g} Hz; {probe.evidence}"
            ),
        )
    return measured


# ---------------------------------------------------------------------------
# Measuring the destination
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WriteMeasurement:
    """A sustained sequential write, actually performed and actually fsynced.

    Carries the host it ran on because a number measured on a desktop NVMe is
    not a statement about a Jetson's eMMC or its NVMe under thermal load, and
    the difference is the difference between a dataset and a truncated bag.
    """

    path: str
    host: str
    bytes_written: int
    seconds: float
    fsync_count: int
    block_bytes: int
    fsync_interval_s: float
    filesystem: str
    note: str

    def __post_init__(self) -> None:
        _positive_int(self.bytes_written, field="bytes_written")
        _positive(self.seconds, field="seconds")
        if self.bytes_written < MIN_MEASUREMENT_BYTES:
            raise BudgetRefusedError(
                f"a sustained-write measurement over {self.bytes_written} bytes is a page-cache "
                f"measurement, not a disk measurement; at least {MIN_MEASUREMENT_BYTES} bytes "
                f"are required"
            )
        if self.seconds < MIN_MEASUREMENT_SECONDS:
            raise BudgetRefusedError(
                f"a sustained-write measurement over {self.seconds:g} s is too short to be a "
                f"sustained rate; at least {MIN_MEASUREMENT_SECONDS:g} s are required"
            )
        if self.fsync_count < 1:
            raise BudgetRefusedError(
                "a write measurement with no fsync measures the page cache; refusing to "
                "report it as a disk rate"
            )

    @property
    def bytes_per_second(self) -> float:
        return self.bytes_written / self.seconds

    @property
    def mib_per_second(self) -> float:
        return self.bytes_per_second / MIB

    @property
    def gib_per_hour(self) -> float:
        return self.bytes_per_second * SECONDS_PER_HOUR / GIB

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "host": self.host,
            "filesystem": self.filesystem,
            "bytes_written": self.bytes_written,
            "seconds": round(self.seconds, 6),
            "block_bytes": self.block_bytes,
            "fsync_count": self.fsync_count,
            "fsync_interval_s": self.fsync_interval_s,
            "bytes_per_second": round(self.bytes_per_second, 3),
            "mib_per_second": round(self.mib_per_second, 3),
            "gib_per_hour": round(self.gib_per_hour, 3),
            "note": self.note,
        }


def measure_sustained_write(
    directory: Path | str,
    *,
    total_bytes: int = 2 * 1024 * MIB,
    block_bytes: int = 4 * MIB,
    fsync_interval_s: float = 1.0,
    max_total_bytes: int = 32 * 1024 * MIB,
    note: str = "",
) -> WriteMeasurement:
    """Write real bytes to a real filesystem and time them, fsyncs included.

    The pattern deliberately mirrors ``CaptureRecorder``: a sequential append
    with an fsync roughly every ``fsync_interval_s``, and a final fsync inside
    the timed window. Measuring with ``dd`` and no fsync would measure this
    host's page cache — 246 GiB of it on the development box.

    The write **grows itself** until the timed window clears
    :data:`MIN_MEASUREMENT_SECONDS`, doubling up to ``max_total_bytes``. A fixed
    size cannot be right for both a Jetson's storage and a Gen5 desktop NVMe:
    256 MiB takes a tenth of a second on the latter, and a tenth of a second is
    a cache reading. If even ``max_total_bytes`` finishes too quickly the
    function refuses rather than reporting the fast number.

    The block is filled once from :func:`os.urandom` and reused, so the timing
    is the filesystem's and not the RNG's. ext4 does not compress, so reuse does
    not flatter the number; on a compressing filesystem it would, and the
    measurement names the filesystem it ran on.
    """

    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    total = _positive_int(total_bytes, field="total_bytes")
    block = _positive_int(block_bytes, field="block_bytes")
    cap = _positive_int(max_total_bytes, field="max_total_bytes")
    interval = _positive(fsync_interval_s, field="fsync_interval_s", allow_zero=True)
    if total < MIN_MEASUREMENT_BYTES:
        raise BudgetRefusedError(
            f"refusing to measure over {total} bytes; at least {MIN_MEASUREMENT_BYTES} are "
            f"needed for the number to mean anything"
        )
    if cap < total:
        raise BudgetRefusedError("max_total_bytes must not be below total_bytes")

    written = 0
    elapsed = 0.0
    fsyncs = 0
    while True:
        free = shutil.disk_usage(target_dir).free
        if free < total * 2:
            raise BudgetRefusedError(
                f"refusing to measure: {free} bytes free at {target_dir}, and this "
                f"measurement wants to write {total} with room to spare"
            )
        written, elapsed, fsyncs = _timed_write(target_dir, total, block, interval)
        if elapsed >= MIN_MEASUREMENT_SECONDS or total >= cap:
            break
        total = min(total * 2, cap)

    return WriteMeasurement(
        path=str(target_dir),
        host=platform.node(),
        bytes_written=written,
        seconds=elapsed,
        fsync_count=fsyncs,
        block_bytes=block,
        fsync_interval_s=interval,
        filesystem=_filesystem_of(target_dir),
        note=note,
    )


def _timed_write(
    target_dir: Path, total: int, block: int, interval: float
) -> tuple[int, float, int]:
    """One timed pass. Returns bytes written, seconds elapsed, fsyncs performed."""

    payload = os.urandom(block)
    path = target_dir / f"parcel-capture-writeprobe-{os.getpid()}.bin"
    written = 0
    fsyncs = 0
    try:
        with open(path, "wb", buffering=0) as handle:
            fileno = handle.fileno()
            started = time.monotonic()
            last_sync = started
            while written < total:
                chunk = payload if total - written >= block else payload[: total - written]
                handle.write(chunk)
                written += len(chunk)
                now = time.monotonic()
                if now - last_sync >= interval:
                    os.fsync(fileno)
                    fsyncs += 1
                    last_sync = now
            os.fsync(fileno)
            fsyncs += 1
            elapsed = time.monotonic() - started
    finally:
        try:
            path.unlink()
        except OSError:  # pragma: no cover - best effort cleanup
            pass
    return written, elapsed, fsyncs


def _filesystem_of(path: Path) -> str:
    """Best-effort filesystem type, from /proc/mounts. Unknown says unknown."""

    try:
        target = str(Path(path).resolve())
        best = ("", "")
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            mount, fstype = parts[1], parts[2]
            if (target == mount or target.startswith(mount.rstrip("/") + "/")) and len(
                mount
            ) >= len(best[0]):
                best = (mount, fstype)
        return best[1] or "unknown"
    except OSError:  # pragma: no cover - /proc absent
        return "unknown"


# ---------------------------------------------------------------------------
# What this arithmetic cannot settle
# ---------------------------------------------------------------------------

#: Named, so the budget document can carry them verbatim and so no reader
#: mistakes a computed number for a measured one. Board rule 5: estimates are
#: labelled as estimates.
UNKNOWNS: tuple[str, ...] = (
    (
        "POWER AND THERMAL: how long an Orin NX + D455 payload runs off the Go2 battery, and "
        "whether either throttles under a sustained write, is UNKNOWN. PLAN:1271 defers "
        "onboard compute/power/thermal/payload characterisation to Wave 4. It may well be the "
        "binding constraint on session length rather than disk, and guessing it would be "
        "dishonest. orin.tegrastats (matrix row 16) and go2.lowstate's BMS block are the two "
        "channels that settle it, and both are recorded from minute one."
    ),
    (
        "ORIN FREE SPACE: unknown until PS-D's preflight reports it. Every session-length "
        "bound here is a function of free bytes, not a number."
    ),
    (
        "ORIN SUSTAINED WRITE: unmeasured. The figure in this document was measured on the "
        "development host and is labelled dev-host, to be re-measured on the Orin. A desktop "
        "Gen5 NVMe is not a Jetson storage stack under thermal load."
    ),
    (
        "USB3 CONTENTION: the D455 shares the Orin's USB controller with whatever else is "
        "plugged in (the L2 may be on /dev/ttyACM0). Whether the bus delivers the profile's "
        "frame rate is unmeasured."
    ),
    (
        "LIDAR POINT RATE: assumed, not read. The built-in unit's model is repo-contradicted "
        "(L1 vs L2) and this budget takes the worse reading. PS-D reads the model and the "
        "payload size off the unit; loads_from_preflight() then replaces the assumption."
    ),
    (
        "FRONT CAMERA BITRATE: assumed at 4 Mb/s. Nobody in this repo has connected to "
        "/frontvideostream, and PS-A marks its rate UNKNOWN."
    ),
    (
        "MESSAGE FIELD LISTS: the DDS payload sizes are summed from transcribed field lists, "
        "not from an installed unitree_go IDL — no vendor SDK is present, and none may be "
        "installed into .parcel/. A wrong field list moves a row, never the headline."
    ),
    (
        "COMPRESSION: none is assumed anywhere. Every figure is raw. If a decision is later "
        "taken to compress depth or IR, every row below changes and this document is wrong "
        "until it is re-derived."
    ),
)


# ---------------------------------------------------------------------------
# Document generation — BANDWIDTH_BUDGET.md is a build artefact, not a file
# ---------------------------------------------------------------------------
#
# Card PS-P of tranche PS-3. The document was hand-maintained and went stale by
# 8.6% within one day of the PS-H channel corrections landing — while remaining
# the number of record on every sheet the operator carries. Hand-maintained
# arithmetic goes stale again, so the document is now *rendered from this
# module* and ``tests/test_bandwidth_budget_doc.py`` fails if the committed
# bytes diverge from what :func:`render_document` produces. The pattern is the
# repo's frozen-digest sentinels (``scripts/ci_gate.py:DIGEST_SENTINELS``),
# turned from "these bytes may not change" into "these bytes must equal what
# the code computes".
#
# Everything below is *generation*. No load model, no rate and no payload size
# is defined here; every number in the rendered document comes from
# :func:`build_budget` or from a recorded measurement carried verbatim.

#: Where the rendered document lives, relative to the repository root.
DOCUMENT_RELPATH = "scrum/20260813/task_1/BANDWIDTH_BUDGET.md"

#: The profile the session plans to run. Named once, used by every section, so
#: "the recommended profile" cannot mean two different things in one document.
RECOMMENDED_PROFILE = D455Profile(848, 480, 30)

#: rosbag2's observed recorder throughput, in **decimal MB/s**, as reported by
#: users on hardware stronger than an Orin NX. EXTERNAL and
#: documentation-derived (``RISK_ASSESSMENT.md:64``, ``CHANNEL_MATRIX.md`` §D):
#: it is not a specification, it is a band of field observations, and nobody has
#: measured this recorder on this Jetson. It is used here only to *classify* a
#: profile, never to authorise one.
ROSBAG2_CEILING_MB_S: tuple[float, float] = (110.0, 120.0)

#: Intel's own stated USB3 bandwidth budget for a D400-series camera, in Mb/s.
#: EXTERNAL (``RISK_ASSESSMENT.md:64``). A second ceiling, independent of the
#: first: a profile can clear the recorder and still not clear the cable.
D455_USB_CEILING_MBIT_S = 1200.0

#: Below this multiple of the *low* rosbag2 reading a profile is called THIN
#: rather than FITS. 1.25x is the point at which a 20% miss on somebody else's
#: hardware still leaves the profile recordable here.
CEILING_THIN_FACTOR = 1.25

#: The headline figures this document published while it was hand-maintained,
#: kept so the generated file can explain its own history in the operator's
#: terms. A historical fact, not a live number: MiB/s, GiB/h, one-hour reserve
#: GiB, twenty-minute reserve GiB, and the front camera's old MiB/s.
STALE_HEADLINE: tuple[float, float, float, float, float] = (
    84.604,
    297.43,
    342.1,
    114.1,
    0.486,
)


#: Sustained sequential write on the development host, executed by PS-P on
#: 2026-08-13. **Dev-host, to be re-measured on the Orin.**
DEV_HOST_WRITE = WriteMeasurement(
    path="/home/jaewoo-jang/.cache/parcel-psp",
    host="jaewoo-jang-parcel",
    bytes_written=34_359_738_368,
    seconds=8.693122,
    fsync_count=9,
    block_bytes=4 * MIB,
    fsync_interval_s=1.0,
    filesystem="ext4",
    note="dev-host, to be re-measured on the Orin",
)

#: Whole-stack throughput through PS-B's real recorder, executed by PS-P on
#: 2026-08-13 via ``rehearse.measure_stack_throughput``. Two profiles, both
#: **dev-host**. The achieved figure is a measurement; the *required* column in
#: the document is derived from :func:`build_budget`, so the ratio between them
#: cannot go stale the way the old hand-written one did.
DEV_HOST_STACK: tuple[tuple[str, float, float], ...] = (
    # (profile label, achieved MiB/s, messages per second)
    ("848x480@30 CDI", 1213.383, 26_586.4),
    ("1280x720@30 CDI", 1373.273, 14_196.9),
)


def _usb_megabits_per_second(profile: D455Profile) -> float:
    """USB3 load of the profile's **image** streams, in Mb/s. Exact arithmetic.

    The two motion streams are excluded, and the document says so: at 32 B a
    message they are a few parts in a hundred thousand of this number, and
    including them would imply a precision the rest of the figure lacks.
    """

    per_frame = 0
    if profile.color:
        per_frame += profile.stream_bytes_per_frame("rgb8")
    if profile.depth:
        per_frame += profile.stream_bytes_per_frame("z16")
    if profile.infrared:
        per_frame += 2 * profile.stream_bytes_per_frame("y8")
    return per_frame * profile.fps * 8 / 1e6


def _megabytes_per_second(rate_bytes_per_second: float) -> float:
    """Decimal MB/s — the unit the rosbag2 ceiling is quoted in. Not MiB/s."""

    return rate_bytes_per_second / 1e6


def recorder_verdict(rate_bytes_per_second: float) -> tuple[str, float]:
    """Classify an offered load against the rosbag2 recorder ceiling.

    Returns ``(verdict, margin)`` where ``margin`` is the *low* ceiling reading
    divided by the offered rate. Fail-closed in spirit: a profile is never
    called ``FITS`` on the strength of the optimistic 120 MB/s reading, and no
    verdict here is permission — the ceiling is somebody else's measurement on
    somebody else's machine.
    """

    rate = _positive(rate_bytes_per_second, field="rate_bytes_per_second")
    low, high = ROSBAG2_CEILING_MB_S
    megabytes = _megabytes_per_second(rate)
    margin = low / megabytes
    if megabytes > high:
        return "OVER both readings", margin
    if megabytes > low:
        return "OVER the low reading", margin
    if margin < CEILING_THIN_FACTOR:
        return "THIN", margin
    return "FITS", margin


@dataclass(frozen=True)
class DropStep:
    """One rung of the drop ladder: what to turn off, and what it costs.

    ``dropped_channels`` are non-D455 channels removed by subtracting their own
    rows out of a budget this module already computed — arithmetic over existing
    rows, never a second load model.
    """

    what: str
    profile: D455Profile
    dropped_channels: tuple[str, ...]
    cost: str

    def __post_init__(self) -> None:
        if not self.what.strip() or not self.cost.strip():
            raise BudgetRefusedError(
                "a drop rung with no stated cost is a rung an operator cannot decide on"
            )
        for channel_id in self.dropped_channels:
            channel(channel_id)  # unknown id is a refusal, per PS-A


#: The order to take the fallbacks in, and what each one costs. The order is an
#: engineering judgement and is argued rung by rung in the document; the numbers
#: beside each rung are computed.
DROP_LADDER: tuple[DropStep, ...] = (
    DropStep(
        what="Front camera JPEG off (H.264 path only)",
        profile=RECOMMENDED_PROFILE,
        dropped_channels=("go2.front_camera",),
        cost=(
            "Costs the dog's own forward view at ~33 Hz as JPEG. The H.264 substitute is "
            "RTP over multicast 230.1.1.1:1720, which is NOT a topic and which a "
            "multicast-unfriendly NIC or switch drops silently — so this rung may cost the "
            "channel outright rather than degrading it. It is first because the D455 "
            "already looks forward: this is the only rung that removes no unique sensing "
            "modality, only a redundant view at a different exposure and lens."
        ),
    ),
    DropStep(
        what="...and the IR pair off (848x480@30 C+D)",
        profile=D455Profile(848, 480, 30, infrared=False),
        dropped_channels=("go2.front_camera",),
        cost=(
            "Costs the only streams that work in the dark and the only independent stereo "
            "baseline. CHANNEL_MATRIX.md §D calls the pair explicitly NOT free — it is a "
            "real +40% disk and +50% USB — which is also why it is the first real sensing "
            "loss on the ladder rather than the last."
        ),
    ),
    DropStep(
        what="...or instead keep IR and halve the rate (848x480@15 C+D+IR)",
        profile=D455Profile(848, 480, 15),
        dropped_channels=("go2.front_camera",),
        cost=(
            "Costs frame rate, and frame rate is the one thing that cannot be recovered "
            "from a bag: resolution downsamples, 15 fps does not interpolate into 30. Take "
            "this rung instead of the one above only when the IR pair matters more than "
            "temporal resolution — for a hand-carried calibration take it does, for a "
            "walking take it does not."
        ),
    ),
    DropStep(
        what="...colour off, IR kept (848x480@30 D+IR)",
        profile=D455Profile(848, 480, 30, color=False),
        dropped_channels=("go2.front_camera",),
        cost=(
            "Costs every colour pixel from the D455 — no texture for visual SLAM, no "
            "appearance data, no human-readable review footage. This is the dark-run rung: "
            "it is here because in darkness the colour stream is already worthless and the "
            "IR pair is not."
        ),
    ),
)


def _ladder_budget(step: DropStep, base: Budget) -> Budget:
    """The rig after this drop, as a :class:`Budget` with the rows removed."""

    full = build_budget(step.profile, session_duration_s=base.session_duration_s)
    return Budget(
        profile=step.profile,
        rows=tuple(row for row in full.rows if row.channel_id not in step.dropped_channels),
        excluded=tuple(full.excluded) + step.dropped_channels,
        session_duration_s=base.session_duration_s,
        margin=base.margin,
    )


def _fmt_unknowns_table() -> list[str]:
    """§0, rendered from :data:`UNKNOWNS` so the two cannot drift apart."""

    lines = ["| Unknown | What the module says, verbatim |", "|---|---|"]
    for item in UNKNOWNS:
        key, _, rest = item.partition(": ")
        lines.append(f"| **{key}** | {rest} |")
    return lines


def _fmt_decision_table(budgets: Sequence[Budget]) -> list[str]:
    lines = [
        (
            "| D455 profile | rig MiB/s | rig GiB/hour | rig MB/s | D455 USB Mb/s | "
            "vs rosbag2 ceiling | vs USB ceiling | reserve 1 h (GiB) | h @ 256 GiB | "
            "@ 1 TiB | @ 2 TiB |"
        ),
        "|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|",
    ]
    for budget in budgets:
        verdict, margin = recorder_verdict(budget.bytes_per_second)
        usb = _usb_megabits_per_second(budget.profile)
        usb_verdict = "**OVER**" if usb > D455_USB_CEILING_MBIT_S else "under"
        mark = "**" if budget.profile.label == RECOMMENDED_PROFILE.label else ""
        lines.append(
            f"| {mark}{budget.profile.label}{mark} "
            f"| {mark}{budget.mib_per_second:.2f}{mark} "
            f"| {mark}{budget.gib_per_hour:.1f}{mark} "
            f"| {_megabytes_per_second(budget.bytes_per_second):.1f} "
            f"| {usb:.0f} "
            f"| {mark}{verdict} (x{margin:.2f}){mark} "
            f"| {usb_verdict} "
            f"| {budget.required_free_gib():.1f} "
            f"| {budget.session_hours(256 * GIB):.2f} "
            f"| {budget.session_hours(1024 * GIB):.2f} "
            f"| {budget.session_hours(2048 * GIB):.2f} |"
        )
    return lines


def _fmt_channel_table(budget: Budget) -> list[str]:
    lines = [
        "| channel | msg/s | payload B | frame B | MiB/s | GiB/h | basis |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in sorted(budget.rows, key=lambda item: -item.bytes_per_second):
        lines.append(
            f"| `{row.channel_id}` | {row.messages_per_second:.1f} "
            f"| {row.payload_bytes_per_message:,} | {row.framing_bytes_per_message} "
            f"| {row.mib_per_second:.3f} | {row.gib_per_hour:.2f} | {row.basis} |"
        )
    lines.append(
        f"| **TOTAL** | **{budget.messages_per_second:,.0f}** | | "
        f"| **{budget.mib_per_second:.3f}** | **{budget.gib_per_hour:.2f}** | |"
    )
    return lines


def _fmt_ladder_table(base: Budget) -> list[str]:
    lines = [
        (
            "| # | Drop | rig MiB/s | rig MB/s | saved vs plan of record | "
            "vs rosbag2 ceiling |"
        ),
        "|---|---|---:|---:|---:|---|",
    ]
    for index, step in enumerate(DROP_LADDER, start=1):
        rung = _ladder_budget(step, base)
        verdict, margin = recorder_verdict(rung.bytes_per_second)
        saved = (base.bytes_per_second - rung.bytes_per_second) / MIB
        lines.append(
            f"| {index} | {step.what} | {rung.mib_per_second:.2f} "
            f"| {_megabytes_per_second(rung.bytes_per_second):.1f} | {saved:.2f} "
            f"| {verdict} (x{margin:.2f}) |"
        )
    return lines


def render_document() -> str:
    """The whole of ``BANDWIDTH_BUDGET.md``, derived rather than remembered.

    Byte-stable: no timestamps, no host lookups, and no measurement is taken at
    render time. Two calls in the same tree produce identical bytes, which is
    what lets ``tests/test_bandwidth_budget_doc.py`` compare the committed file
    against this function instead of trusting a human to have re-run the sums.
    """

    budgets = [build_budget(profile) for profile in CANDIDATE_PROFILES]
    plan = build_budget(RECOMMENDED_PROFILE)
    short = build_budget(RECOMMENDED_PROFILE, session_duration_s=1200.0)
    verdict, margin = recorder_verdict(plan.bytes_per_second)
    low, high = ROSBAG2_CEILING_MB_S
    plan_mb = _megabytes_per_second(plan.bytes_per_second)
    plan_usb = _usb_megabits_per_second(RECOMMENDED_PROFILE)
    front = next(row for row in plan.rows if row.channel_id == "go2.front_camera")
    stale_mib, stale_gib, stale_hour, stale_short, stale_front = STALE_HEADLINE
    added = plan.mib_per_second - stale_mib - (front.mib_per_second - stale_front)
    assumed = [row for row in plan.rows if row.basis == LoadBasis.ASSUMED_WORST_CASE.value]
    assumed_mib = math.fsum(row.mib_per_second for row in assumed)
    d455_mib = plan.camera_bytes_per_second / MIB
    imaging_mib = d455_mib + front.mib_per_second
    other_mib = plan.mib_per_second - imaging_mib

    out: list[str] = []
    w = out.append

    w("# Bandwidth budget — the arithmetic nobody had done")
    w("")
    w("> ## ⚠ GENERATED FILE — do not hand-edit")
    w(">")
    w("> Every number below is rendered by")
    w("> `scripts/parcel_capture/budget.py::render_document()`. Hand-editing this file is")
    w("> a defect, not a fix: the next regeneration silently reverts the edit, and")
    w("> `tests/test_bandwidth_budget_doc.py` reddens until it is reverted.")
    w(">")
    w("> ```")
    w("> .parcel/bin/python -m scripts.parcel_capture.budget --emit-doc    # regenerate")
    w("> .parcel/bin/python -m scripts.parcel_capture.budget --check-doc   # is it stale?")
    w("> ```")
    w("")
    w("**Model:** card PS-E · **Generation + this revision:** card PS-P, tranche PS-3")
    w("**Producer:** `scripts/parcel_capture/budget.py` · "
      "**Rehearsal:** `scripts/parcel_capture/rehearse.py`")
    w("**Freshness gate:** `tests/test_bandwidth_budget_doc.py` · "
      "**Status:** [PSE_STATUS.md](PSE_STATUS.md) · [PSP_STATUS.md](PSP_STATUS.md)")
    w("")
    w("### Why this file is generated")
    w("")
    w("Because the hand-maintained version **went stale by 8.6% within one day**, while")
    w("remaining the number of record on every sheet the operator carries.")
    w("")
    w("The PS-H channel corrections re-modelled the Go2 front camera — it is")
    w("**JPEG per frame** on `rt/frontvideostream`, ~204 KiB worst case, not a 4 Mb/s")
    w("H.264 stream at ~16 KB/frame, an under-model of roughly **13x** — and added five")
    w("channels. The code moved; the document did not. It went on publishing")
    w(f"**{stale_mib:.2f} MiB/s · {stale_gib:.1f} GiB/h · {stale_hour:.1f} GiB · "
      f"{stale_short:.1f} GiB** while `budget.py` computed")
    w(f"**{plan.mib_per_second:.3f} · {plan.gib_per_hour:.2f} · "
      f"{plan.required_free_gib():g} · {short.required_free_gib():g}**.")
    w("")
    w("The delta decomposes exactly, which is the tell that this was staleness and not")
    w(f"disagreement: the front camera moved from {stale_front:.3f} to "
      f"{front.mib_per_second:.3f} MiB/s")
    w(f"(**+{front.mib_per_second - stale_front:.3f}**), and PS-H's five added channels")
    w("(`utlidar/cloud_deskewed`, `utlidar/robot_odom`, `uwbstate`,")
    w(f"`utlidar/lidar_state`, `utlidar/switch`) contribute the remaining **+{added:.3f}**.")
    w("")
    w("Arithmetic a human has to remember to re-run is arithmetic that goes stale. This")
    w("file is now a build artefact behind a sentinel, following the repo's frozen-digest")
    w("pattern (`scripts/ci_gate.py:DIGEST_SENTINELS`) — with the difference that the")
    w("sentinel does not pin the bytes, it pins them **to what the code computes**.")
    w("")
    w("---")
    w("")
    w("## 0. What this document does not know")
    w("")
    w("Stated first, because a budget that hides its assumptions is worse than no")
    w("budget. This table is rendered from `budget.UNKNOWNS`, so the module and the")
    w("document cannot disagree about what is unmeasured.")
    w("")
    out.extend(_fmt_unknowns_table())
    w("")
    w("---")
    w("")
    w("## 1. The D455 decision table")
    w("")
    w("The only real tuning knob. Colour is RGB8 (3 B/px), depth is Z16 (2 B/px), each")
    w("infrared is Y8 (1 B/px) — the format names *are* the arithmetic.")
    w("")
    w("**The `rig` columns are the whole rig**: the D455 profile, plus every other")
    w("budgeted channel, plus the per-message framing PS-B writes. `MiB/s` is binary")
    w("(1024²); `MB/s` is decimal (10⁶), because decimal is the unit the rosbag2 ceiling")
    w("is quoted in and confusing the two is a 5% error on a number whose margin is 14%.")
    w("**USB Mb/s counts the image streams only** — the two motion streams are 32 B a")
    w("message and would imply a precision this figure does not have.")
    w("")
    out.extend(_fmt_decision_table(budgets))
    w("")
    w("The free-space columns are **illustrative** — the Orin's actual free space is")
    w("unknown (§0) — and each already has the recorder's 15% margin removed. The")
    w("session-length bound is `free / (1 + margin) / rate`; PS-B's `SpaceBudget` uses")
    w("the same margin, so a take that clears this table is a take the recorder will")
    w("agree to start.")
    w("")
    w("### The plan's anchors, verified rather than copied")
    w("")
    w("`PHYSICAL_SESSION_PLAN.md:69-72` and `CHANNEL_MATRIX.md` §D quote ≈132 MiB/s /")
    w("≈464 GiB/h at 1280×720/30 and ≈58 MiB/s / ≈205 GiB/h at 848×480. Derived here:")
    w("")
    w("```")
    w("1280×720 colour RGB8 : 1280 × 720 × 3 = 2,764,800 B/frame")
    w("1280×720 depth  Z16  : 1280 × 720 × 2 = 1,843,200 B/frame")
    w("                       sum 4,608,000 B/frame × 30 = 138,240,000 B/s")
    w("                       = 131.84 MiB/s = 463.49 GiB/hour        ✓ (quoted ≈132 / ≈464)")
    w("")
    w(" 848×480 colour RGB8 :  848 × 480 × 3 = 1,221,120 B/frame")
    w(" 848×480 depth  Z16  :  848 × 480 × 2 =   814,080 B/frame")
    w("                       sum 2,035,200 B/frame × 30 =  61,056,000 B/s")
    w("                       =  58.23 MiB/s = 204.71 GiB/hour        ✓ (quoted ≈58 / ≈205)")
    w("```")
    w("")
    w("**Both anchors are correct, and both are colour+depth only** — they exclude the")
    w("IR pair, the D455 IMU, every non-camera channel, and the recording framing. The")
    w("gap between an anchor and a `rig` column above is exactly what the plan's quoted")
    w("figures leave out, and most of that gap is now the Go2 front camera.")
    w("")
    w("---")
    w("")
    w("## 2. Does the plan of record actually fit? — the two ceilings")
    w("")
    w("The decision this document exists to drive, answered in the operator's language.")
    w("")
    w(f"> **{RECOMMENDED_PROFILE.label} — the plan of record — offers "
      f"{plan.mib_per_second:.2f} MiB/s,**")
    w(f"> **which is {plan_mb:.1f} MB/s.**")
    w(">")
    w(f"> Against rosbag2's observed recorder ceiling of {low:.0f}–{high:.0f} MB/s that is")
    w(f"> **{verdict}** — a margin of **×{margin:.2f}** on the low reading, i.e. about")
    w(f"> **{(margin - 1.0) * 100:.0f}% of headroom**. That ceiling is a band of field")
    w("> reports from **stronger x86 machines**, not a measurement of this Jetson. An")
    w("> Orin NX is the weaker box, so the local ceiling is more likely to sit *below*")
    w("> that band than above it.")
    w(">")
    w(f"> Against Intel's ~{D455_USB_CEILING_MBIT_S:.0f} Mb/s USB3 budget the same profile")
    w(f"> draws **{plan_usb:.0f} Mb/s** of image data — comfortably under. USB is not the")
    w("> binding ceiling at 848×480. It is the binding ceiling at 720p.")
    w("")
    w("**So: yes on paper, conditionally, and it is not yet proven here.**")
    w(f"{RECOMMENDED_PROFILE.label} is recordable if — and only if — the Orin's own")
    w(f"recorder sustains ~{plan_mb:.0f} MB/s. Nobody has measured that. Two steps measure")
    w("it before the dog is ever involved, and both are tonight:")
    w("")
    w("- `session/TONIGHT_CHECKLIST.md` **N3** — `fio` **tail** throughput on the real")
    w("  record destination. Read the tail, not the peak: a DRAM-less NVMe falls off")
    w("  after its SLC cache is exhausted, and the peak hides exactly that.")
    w("- `session/TONIGHT_CHECKLIST.md` **N4** — the exact `ros2 bag record -s mcap`")
    w("  command line at the real byte rate for ten minutes. This is the one that")
    w("  measures the ceiling in §2, because the ceiling is a property of *the recorder*")
    w("  and not of the disk.")
    w("")
    w("**Until N4 comes back green, treat this profile as a hypothesis.**")
    w("")
    w("Three rows in §1 are **not recordable** and must never be selected on the day:")
    w("`1280x720@30 CD`, `1280x720@30 CDI` and `848x480@60 CDI` are all over the recorder")
    w("ceiling, and two of those three are over the USB ceiling as well — two independent")
    w("ceilings, both below the ask. `1280x720@15 CDI` clears the recorder ceiling by")
    w("×1.02, which is not a margin, it is a coin toss.")
    w("")
    w("### If it does not fit: what to drop, in order, and what each drop costs")
    w("")
    w("Rung 1 is taken first and every other rung sits on top of it. Rungs 2, 3 and 4 are")
    w("**alternatives to each other**, not successive steps — that is why rung 4 saves")
    w("less than rung 3 — so pick the one whose cost the session can afford. The rates")
    w("are computed; the *order* and the alternatives are engineering judgement, argued")
    w("rung by rung so they can be disagreed with at 09:00 rather than re-derived.")
    w("")
    out.extend(_fmt_ladder_table(plan))
    w("")
    for index, step in enumerate(DROP_LADDER, start=1):
        w(f"{index}. **{step.what}** — {step.cost}")
    w("")
    w("**The rung that is deliberately absent is dropping small channels.** Everything")
    w(f"that is neither the D455 nor the front camera totals **{other_mib:.3f} MiB/s**;")
    w("turning all of it off saves less than any single rung above and costs the only")
    w("ground-truth contact signal, the only device clock the dog emits, and the only")
    w("non-LiDAR proximity sensing on the robot. Storage is cheap relative to a second")
    w("physical session, and there is no second session.")
    w("")
    w("---")
    w("")
    w("## 3. Every channel, with its working shown")
    w("")
    w(f"At {RECOMMENDED_PROFILE.label}, over a one-hour take. `frame B` is the per-message")
    w("recording overhead — measured against PS-B's own MCAP writer, not estimated — and")
    w("it grows by one byte per decimal digit of the session's final sequence number, so")
    w("it is evaluated at the *end* of the take.")
    w("")
    out.extend(_fmt_channel_table(plan))
    w("")
    w("Not recorded in this profile: "
      + ", ".join(f"`{item}`" for item in plan.excluded)
      + " — `AWAITING_HARDWARE`, in the post")
    w("(`BLOCKED.md:74-97` B3). Its slot exists and its model is carried (6 ch × 16 kHz ×")
    w("16 bit = 0.21 MiB/s, 0.75 GiB/h) so it drops in without re-deriving anything;")
    w("`--include-awaiting` adds it.")
    w("")
    w("**`basis` is not decoration.** `derived_pixels` is exact arithmetic;")
    w("`derived_fields` is exact given a transcribed field list; `assumed_worst_case` is")
    w("an engineering assumption taken at its worse end.")
    w(f"**{len(assumed)} rows are assumptions and together they are {assumed_mib:.3f} MiB/s")
    w(f"of {plan.mib_per_second:.3f}**, i.e. {assumed_mib / plan.mib_per_second:.1%} of the")
    w("budget. That fraction is the thing this revision changes most: the previous table")
    w("could say its assumptions were 2.3% of the total and therefore harmless. They are")
    w("not any more, because the largest of them is now the front camera. **If the front")
    w("camera's JPEG assumption is wrong by a factor of three in either direction the")
    w("headline moves by more than 10%** — and question 4 of `CHANNEL_MATRIX.md`'s open")
    w("list (does `Go2FrontVideoData_` populate one resolution or all three?) is exactly")
    w("that factor.")
    w("")
    w("### Three findings from doing the arithmetic")
    w("")
    w(f"**(a) Imaging is {imaging_mib / plan.mib_per_second:.1%} of the budget, and the D455")
    w(f"alone is {d455_mib / plan.mib_per_second:.1%}.** `CHANNEL_MATRIX.md` §G's")
    w("*\"<2 MiB/s for the non-camera channels\"* is false as written — the real figure is")
    w(f"**{other_mib:.3f} MiB/s** — but the claim it was making survives intact:")
    w("everything that is not a camera is still a rounding error against the cameras.")
    w("")
    w(f"**(b) The recording framing is {plan.framing_bytes_per_second / MIB:.3f} MiB/s ≈ "
      f"{plan.framing_bytes_per_second * SECONDS_PER_HOUR / GIB:.2f} GiB/hour**, at")
    w(f"{plan.messages_per_second:,.0f} msg/s — "
      f"{plan.framing_bytes_per_second / plan.bytes_per_second:.1%} of the profile. It is")
    w("**not worth optimising**.")
    w("")
    w("**(c) …but framing costs ~10× the payload on the smallest channels.**")
    w("`go2.wirelesscontroller` carries 32 B of sticks and buttons inside a ~318 B")
    w("envelope; `d455.accel` and `d455.gyro` are the same shape. That is the price of")
    w("every message being independently attributable — per-channel sequence, dual")
    w("clocks, frame, origin, calibration ref — and it is the right trade for this")
    w("session. If it ever has to come back, the lever is a compact binary envelope in")
    w("place of JSON, **not** recording fewer channels.")
    w("")
    w("---")
    w("")
    w("## 4. Session length")
    w("")
    w("```")
    w(f"hours = free_bytes / (1 + margin) / bytes_per_second / 3600      "
      f"margin = {plan.margin:g}")
    w("```")
    w("")
    w(f"At {RECOMMENDED_PROFILE.label}, `bytes_per_second = {plan.bytes_per_second:,.0f}` "
      f"({plan.mib_per_second:.2f} MiB/s):")
    w("")
    w("| free space | session length |")
    w("|---|---|")
    for gib, label in ((256, "256 GiB"), (512, "512 GiB"), (1024, "1 TiB"), (2048, "2 TiB")):
        hours = plan.session_hours(gib * GIB)
        w(f"| {label} | {hours:.2f} h ({hours * 60:.0f} min) |")
    w("")
    w("**These are disk bounds only.** The binding constraint may be battery or thermal,")
    w("and that is unknown (§0). Treat the disk bound as a ceiling and expect the real")
    w("bound to be lower.")
    w("")
    w("The number PS-D's go/no-go wants is `--required-free-gib`, which is the *reserve")
    w("for the planned take* rather than a session length:")
    w("")
    w("```")
    w(f"{short.required_free_gib():<8g} # {short.session_duration_s / 60:.0f}-minute take at "
      f"{RECOMMENDED_PROFILE.label}")
    w(f"{plan.required_free_gib():<8g} # one-hour take")
    w("```")
    w("")
    w("PS-B's recorder **refuses to start** below it, and PS-D's `attest()` cannot reach")
    w("`GO_RECORD` without one (`PSD_STATUS.md` design call D-3). Both couplings are")
    w("exercised in the rehearsal.")
    w("")
    w("---")
    w("")
    w("## 5. Can the destination keep up? — measured")
    w("")
    w("```")
    w("$ .parcel/bin/python -c \"measure_sustained_write(")
    w(f"      '{DEV_HOST_WRITE.path}',")
    w("      total_bytes=32*1024**3, block_bytes=4*1024*1024, fsync_interval_s=1.0)\"")
    for key, value in DEV_HOST_WRITE.to_dict().items():
        w(f"  {key}: {value}")
    w("```")
    w("")
    w(f"> ### {DEV_HOST_WRITE.mib_per_second:,.0f} MiB/s — "
      "**dev-host, to be re-measured on the Orin**")
    w(">")
    w(f"> Crucial T700 4 TB (`CT4000T700SSD3`), {DEV_HOST_WRITE.filesystem}, "
      "`/dev/nvme0n1p5`.")
    w(f"> {DEV_HOST_WRITE.bytes_written / GIB:.0f} GiB written sequentially with an fsync")
    w("> every second and a final fsync inside the timed window. **This is not a")
    w("> statement about the Orin.** It is a floor for rehearsal work on this host and")
    w("> nothing more. `session/TONIGHT_CHECKLIST.md` **N3** is where the Orin's own")
    w("> figure comes from.")
    w("")
    w(f"Against the plan of record that is "
      f"**×{DEV_HOST_WRITE.bytes_per_second / plan.bytes_per_second:.1f} headroom on the dev")
    w("host**. The measurement is not `dd`: it fsyncs, so it is not measuring this host's")
    w("246 GiB of page cache, and it grows itself until the timed window clears one")
    w("second, because 256 MiB finishes in a tenth of a second on this drive and a tenth")
    w("of a second is a cache reading.")
    w("")
    w("### And through the whole capture stack, which is the number that matters")
    w("")
    w("Raw disk speed is not what a recorder achieves: every message is JSON-encoded into")
    w("an envelope, length-prefixed, wrapped in an MCAP record, written through a")
    w("buffered handle and fsynced once a second. Measured end to end through PS-B's real")
    w("`CaptureRecorder`, at full payload size:")
    w("")
    w("| profile | achieved | required | vs real time | msg/s |")
    w("|---|---:|---:|---:|---:|")
    for label, achieved, msg_rate in DEV_HOST_STACK:
        matched = next(item for item in budgets if item.profile.label == label)
        w(
            f"| {label} | {achieved:,.0f} MiB/s | {matched.mib_per_second:.1f} MiB/s "
            f"| **×{achieved / matched.mib_per_second:.1f}** | {msg_rate:,.0f} |"
        )
    w("")
    w("**Dev-host, to be re-measured on the Orin**, and single-threaded on a machine with")
    w("far more single-core throughput than an Orin NX. This answers `PSB_STATUS.md`'s")
    w("`does_not_prove` #9 for the dev host and leaves it open for the Jetson; the scaling")
    w("to the Orin is **an estimate and is not made here**. Re-run")
    w("`rehearse.measure_stack_throughput` on the unit.")
    w("")
    w("**And note what this is a measurement OF.** It is the `parcel-capture` recorder,")
    w("not `ros2 bag record`, and PS-G makes rosbag2 the recorder of record. The ceiling")
    w("that actually binds the session is the one in §2, and it has never been measured")
    w("on any of our hardware at all.")
    w("")
    w("---")
    w("")
    w("## 6. How to re-derive any of this")
    w("")
    w("```")
    w("# the decision table")
    w(".parcel/bin/python -m scripts.parcel_capture.budget")
    w("")
    w("# one profile, per-channel, with the unknowns printed")
    w(f".parcel/bin/python -m scripts.parcel_capture.budget --profile "
      f"{RECOMMENDED_PROFILE.width}x{RECOMMENDED_PROFILE.height}@{RECOMMENDED_PROFILE.fps}"
      " --duration 3600")
    w("")
    w("# with a real sustained-write measurement on the destination volume")
    w(".parcel/bin/python -m scripts.parcel_capture.budget --profile 848x480@30 \\")
    w("    --measure-write /path/on/the/orin \\")
    w("    --free-bytes $(df --output=avail -B1 /path | tail -1)")
    w("")
    w("# the rehearsal that drives the whole stack at that profile")
    w(".parcel/bin/python -m scripts.parcel_capture.rehearse --selftest --workdir /tmp/rehearsal")
    w("")
    w("# regenerate THIS DOCUMENT, and check whether it has gone stale")
    w(".parcel/bin/python -m scripts.parcel_capture.budget --emit-doc")
    w(".parcel/bin/python -m scripts.parcel_capture.budget --check-doc")
    w("```")
    w("")
    w("On the Orin, with no editable install and no `PYTHONPATH`, the same files run as")
    w("plain scripts:")
    w("")
    w("```")
    w("python3 scripts/parcel_capture/budget.py --profile 848x480@30 --measure-write /data")
    w("python3 scripts/parcel_capture/rehearse.py --selftest --workdir /data/rehearsal")
    w("```")
    w("")
    w("---")
    w("")
    w("## What this document does not prove")
    w("")
    w("- It does not prove that any of these channels exists on **our** unit, publishes at")
    w("  its declared rate, or carries the payload size assumed for it. §0 names every")
    w("  assumption; the session's first 45 minutes is where they become readings.")
    w("- It does not prove the Orin can record any row in §1. Every sustained-write and")
    w("  stack-throughput number in §5 is **dev-host**, on a desktop Gen5 NVMe and a far")
    w("  faster core, and this document explicitly declines to extrapolate them.")
    w("- **It does not prove the rosbag2 ceiling in §2 applies here.** That band is field")
    w("  reports from other people's x86 machines. It is used to classify a profile, never")
    w("  to authorise one, and `session/TONIGHT_CHECKLIST.md` N4 is the only thing on the")
    w("  board that can settle it.")
    w("- It does not prove the drop ladder's *order* is right for the session's purpose.")
    w("  The rates are computed; the ordering is judgement, argued rung by rung.")
    w("- It states **no power or thermal bound**, which may well be the binding constraint")
    w("  on session length rather than disk (§0).")
    w("- **Being generated does not make it true.** The freshness gate proves the document")
    w("  equals the model. It says nothing whatever about whether the model is right.")
    w("")
    return "\n".join(out) + "\n"


def document_path(root: Path | str | None = None) -> Path:
    """Absolute path of the rendered document."""

    base = _REPO_ROOT if root is None else Path(root)
    return base / DOCUMENT_RELPATH


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_profile(text: str) -> D455Profile:
    """``848x480@30`` or ``848x480@30:CD`` (streams: C colour, D depth, I IR)."""

    body, _, streams = text.partition(":")
    try:
        geometry, _, fps = body.partition("@")
        width, _, height = geometry.partition("x")
        parsed = D455Profile(
            int(width),
            int(height),
            int(fps),
            color="C" in (streams or "CDI").upper(),
            depth="D" in (streams or "CDI").upper(),
            infrared="I" in (streams or "CDI").upper(),
        )
    except (TypeError, ValueError) as error:
        raise BudgetRefusedError(
            f"cannot parse D455 profile {text!r}; expected WIDTHxHEIGHT@FPS[:streams], "
            f"e.g. 848x480@30 or 1280x720@30:CD"
        ) from error
    return parsed


def format_table(budgets: Iterable[Budget], free_bytes: int | None) -> str:
    """The decision table, one row per profile."""

    lines = [
        (
            f"{'D455 profile':<24} {'MiB/s':>9} {'GiB/hour':>10} {'msg/s':>8} "
            f"{'cam %':>6} {'hours @ free':>13}"
        ),
        "-" * 76,
    ]
    for budget in budgets:
        hours = "unknown" if free_bytes is None else f"{budget.session_hours(free_bytes):.2f}"
        lines.append(
            f"{budget.profile.label:<24} {budget.mib_per_second:>9.2f} "
            f"{budget.gib_per_hour:>10.2f} {budget.messages_per_second:>8.0f} "
            f"{budget.camera_bytes_per_second / budget.bytes_per_second:>6.1%} {hours:>13}"
        )
    if free_bytes is None:
        lines.append("")
        lines.append(
            "hours @ free: UNKNOWN — pass --free-bytes, or run PS-D's preflight on the Orin. "
            "Unknown free space is not a long session."
        )
    return "\n".join(lines)


def format_budget(budget: Budget, measurement: WriteMeasurement | None) -> str:
    """The per-channel breakdown for one profile."""

    lines = [
        (
            f"profile: {budget.profile.label}   session: {budget.session_duration_s:g} s   "
            f"margin: {budget.margin:.0%}"
        ),
        "",
        (
            f"{'channel':<26} {'msg/s':>8} {'payload B':>10} {'frame B':>8} {'MiB/s':>9} "
            f"{'GiB/h':>9}  basis"
        ),
        "-" * 92,
    ]
    for row in sorted(budget.rows, key=lambda item: -item.bytes_per_second):
        lines.append(
            f"{row.channel_id:<26} {row.messages_per_second:>8.1f} "
            f"{row.payload_bytes_per_message:>10,} {row.framing_bytes_per_message:>8} "
            f"{row.mib_per_second:>9.3f} {row.gib_per_hour:>9.2f}  {row.basis}"
        )
    lines.append("-" * 92)
    lines.append(
        f"{'TOTAL':<26} {budget.messages_per_second:>8.0f} {'':>10} {'':>8} "
        f"{budget.mib_per_second:>9.3f} {budget.gib_per_hour:>9.2f}"
    )
    lines.append("")
    lines.append(
        f"payload {budget.payload_bytes_per_second / MIB:.3f} MiB/s + framing "
        f"{budget.framing_bytes_per_second / MIB:.3f} MiB/s "
        f"({budget.framing_bytes_per_second / budget.bytes_per_second:.1%} of the total)"
    )
    lines.append(
        f"required for {budget.session_duration_s:g} s: {budget.required_bytes():,} bytes "
        f"({budget.required_free_gib():g} GiB, PS-D --required-free-gib)"
    )
    if budget.excluded:
        lines.append(f"not recorded in this profile: {', '.join(budget.excluded)}")
    lines.append("")
    verdict = budget.sustained_by(measurement)
    if measurement is None:
        lines.append(
            "sustained write: UNMEASURED — run with --measure-write DIR on the destination "
            "volume. Unmeasured is not a pass."
        )
    else:
        lines.append(
            f"sustained write: {measurement.mib_per_second:.1f} MiB/s measured on "
            f"{measurement.host} ({measurement.filesystem}, {measurement.bytes_written / MIB:.0f} "
            f"MiB in {measurement.seconds:.2f} s, {measurement.fsync_count} fsync) -> "
            f"{verdict.value.upper()} (headroom x{budget.headroom(measurement):.1f})"
        )
    lines.append("")
    lines.append("UNKNOWN, to be measured:")
    for item in UNKNOWNS:
        lines.append(f"  * {item}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parcel-capture-budget",
        description=(
            "Bandwidth, storage and session-length arithmetic for the PS-1 capture stack."
        ),
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="D455 profile, e.g. 848x480@30 or 1280x720@30:CD. Omit for the decision table.",
    )
    parser.add_argument(
        "--duration", type=float, default=3600.0, help="planned take length in seconds"
    )
    parser.add_argument(
        "--free-bytes",
        type=int,
        default=None,
        help="free space at the destination; omit and session length reads UNKNOWN",
    )
    parser.add_argument(
        "--measure-write",
        metavar="DIR",
        default=None,
        help="measure sustained write into DIR (writes and deletes a large file)",
    )
    parser.add_argument(
        "--measure-bytes",
        type=int,
        default=2 * 1024 * MIB,
        help="bytes to write for the sustained-write measurement",
    )
    parser.add_argument(
        "--include-awaiting",
        action="store_true",
        help="include AWAITING_HARDWARE channels (the XVF3800 mic array)",
    )
    parser.add_argument(
        "--emit-doc",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help=(
            "render the budget document from this module and write it to PATH "
            "(default: the committed path; '-' for stdout)"
        ),
    )
    parser.add_argument(
        "--check-doc",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="exit 3 if the committed document differs from what this module renders",
    )
    return parser


def _emit_doc(target: str) -> int:
    rendered = render_document()
    if target == "-":
        sys.stdout.write(rendered)
        return 0
    path = document_path() if target == "" else Path(target)
    path.write_text(rendered, encoding="utf-8")
    print(f"wrote {path} ({len(rendered.encode('utf-8')):,} bytes)")
    return 0


def _check_doc(target: str) -> int:
    """Fail closed: an unreadable document is STALE, never assumed current."""

    path = document_path() if target == "" else Path(target)
    rendered = render_document()
    try:
        committed = path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"STALE: cannot read {path}: {error}", file=sys.stderr)
        return 3
    if committed == rendered:
        print(f"FRESH: {path} equals budget.py::render_document()")
        return 0
    left = committed.splitlines()
    right = rendered.splitlines()
    first = next(
        (
            index
            for index in range(max(len(left), len(right)))
            if left[index : index + 1] != right[index : index + 1]
        ),
        0,
    )
    print(
        f"STALE: {path} diverges from budget.py at line {first + 1}\n"
        f"  committed: {(left[first : first + 1] or ['<eof>'])[0]!r}\n"
        f"  computed : {(right[first : first + 1] or ['<eof>'])[0]!r}\n"
        f"  fix with:  .parcel/bin/python -m scripts.parcel_capture.budget --emit-doc",
        file=sys.stderr,
    )
    return 3


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.emit_doc is not None:
            return _emit_doc(args.emit_doc)
        if args.check_doc is not None:
            return _check_doc(args.check_doc)
        measurement = None
        if args.measure_write is not None:
            measurement = measure_sustained_write(
                args.measure_write,
                total_bytes=args.measure_bytes,
                note="dev-host, to be re-measured on the Orin",
            )
        if args.profile is None:
            budgets = [
                build_budget(
                    profile,
                    session_duration_s=args.duration,
                    include_awaiting=args.include_awaiting,
                )
                for profile in CANDIDATE_PROFILES
            ]
            print(format_table(budgets, args.free_bytes))
            if measurement is not None:
                print()
                print(
                    f"sustained write: {measurement.mib_per_second:.1f} MiB/s on "
                    f"{measurement.host} ({measurement.filesystem}) — {measurement.note}"
                )
            return 0
        budget = build_budget(
            parse_profile(args.profile),
            session_duration_s=args.duration,
            include_awaiting=args.include_awaiting,
        )
        print(format_budget(budget, measurement))
        if args.free_bytes is not None:
            print(
                f"session bound at {args.free_bytes:,} free bytes: "
                f"{budget.session_hours(args.free_bytes):.2f} hours"
            )
        return 0
    except BudgetError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = [
    "ASSUMED_LIDAR_POINTS_PER_SECOND",
    "CANDIDATE_PROFILES",
    "CEILING_THIN_FACTOR",
    "D455_DECLARED_MODES",
    "D455_USB_CEILING_MBIT_S",
    "DEFAULT_MARGIN",
    "DEV_HOST_STACK",
    "DEV_HOST_WRITE",
    "DOCUMENT_RELPATH",
    "DROP_LADDER",
    "GIB",
    "MIB",
    "MIN_MEASUREMENT_BYTES",
    "RECOMMENDED_PROFILE",
    "ROSBAG2_CEILING_MB_S",
    "STALE_HEADLINE",
    "UNKNOWNS",
    "Budget",
    "BudgetError",
    "BudgetRefusedError",
    "BudgetRow",
    "ChannelLoad",
    "D455Profile",
    "DropStep",
    "LoadBasis",
    "SustainVerdict",
    "WriteMeasurement",
    "build_budget",
    "document_path",
    "framing_bytes",
    "loads_from_preflight",
    "measure_sustained_write",
    "parse_profile",
    "recorder_verdict",
    "render_document",
    "static_loads",
]
