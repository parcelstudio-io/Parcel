"""Canonical, machine-readable enumeration of every capturable sensor channel.

Card PS-A of tranche PS-1, **rewritten by card PS-H of the corrective tranche
PS-2** against ``scrum/20260813/task_1/RISK_ASSESSMENT.md`` "Channel-matrix
corrections". It grounds ``scrum/20260813/task_1/CHANNEL_MATRIX.md`` — the
authoritative matrix behind the owner's *use all the sensors possible*
directive for the physical session (Go2 EDU + add-on Unitree L2 + RealSense
D455 + Jetson Orin NX, recording onboard).

This is a LEAF module in exactly the sense :mod:`parcel_robot.evidence_origin`
is one: it imports the standard library and nothing else. The capture process
runs on the Orin under JetPack 6.2.x / Python 3.10 and must be able to
enumerate what to record without dragging the autonomy stack — or a vendor SDK
— behind it. ``tests/test_capture_envelope.py`` pins that with an AST import
walk and a subprocess ``sys.modules`` probe, and separately pins that no symbol
here names a command surface: this package subscribes and never speaks.

Rows, channels, and payload fields
----------------------------------
Three different things get counted here and they are NOT the same number. Every
document in the tranche now quotes all three:

* **25 channel rows** — the numbered rows of table A of CHANNEL_MATRIX.md.
  :data:`MATRIX_ROW_TITLES`.
* **28 channels** — the recording unit. A channel is an independently-arriving,
  independently-dropping STREAM, and it gets its own sequence space. Rows 7, 14
  and 15 each bundle two such streams (``lf/lowstate`` + ``lf/sportmodestate``;
  "Infrared x2"; "accel + gyro", which the RealSense SDK delivers as two motion
  streams at two rates), so 25 rows expand to 28 channels. Bundling any of them
  would reintroduce, at small scale, the exact defect this package exists to
  fix — a drop on IR-left hidden behind IR-right's traffic.
* **11 payload-field rows** — table B of CHANNEL_MATRIX.md, :data:`PAYLOAD_FIELDS`.
  These are fields INSIDE a channel's message (``range_obstacle[4]`` inside
  ``SportModeState``, ``power_v`` inside ``LowState``). They cost no extra
  bandwidth, they arrive when their parent arrives, and they must NEVER be
  minted as channels: a field has no independent arrival, so giving it its own
  sequence space would fabricate drops and double-count bytes. They are
  enumerated because "not a channel" was, in the PS-1 matrix, indistinguishable
  from "not recorded" — and four of them were quietly missing.

Coverage is machine-checkable in both directions
(``test_every_matrix_row_is_covered_and_no_channel_invents_a_row``,
``test_every_payload_field_row_is_covered_and_names_a_real_parent``).

Nothing here is a measurement
-----------------------------
``message_type``, ``nominal_rate_hz``, ``frame_id``, ``presence``,
``wire_address`` and ``source_clock`` are DECLARED EXPECTATIONS transcribed
from CHANNEL_MATRIX.md, from vendor documentation, and from the external
research recorded in RISK_ASSESSMENT.md. :data:`DECLARATION_BASIS` says so in
one machine-readable word, and every row carries a :class:`Confidence` marker
that is a marker of *documentation quality*, never of evidence. Each is to be
replaced by a reading from OUR unit inside :data:`MEASUREMENT_WINDOW`. A
mismatch between this table and the unit is a FINDING, never a silent
correction, and :class:`ChannelPresence` never authorises anything: a channel
is present when — and only when — a message was received from it (board rule 3,
"unknown = absent").

Four fail-closed consequences are load-bearing:

* ``utlidar/imu`` is transcribed by the matrix as "LIVE if published". An
  unverified publication is not LIVE, so it is
  :attr:`ChannelPresence.CONFIRM_ON_HAND` — and two independent field reports
  have it emitting accelerations of order 1e24 m/s^2, which a receipt-count
  probe would attest as healthy. That is the input to the PS-J physical
  plausibility gate.
* ``sportmodestate``, ``utlidar/robot_pose``, ``utlidar/voxel_map_compressed``
  and ``utlidar/robot_odom`` are produced by on-robot SERVICES, not by sensor
  firmware. The topic can exist, carry a publisher, and emit nothing — which is
  indistinguishable at the DDS layer from a bad network config. They are
  :attr:`ChannelPresence.VERIFY_IN_SESSION`, which is a distinct state from
  "is the box in the room".
* On the raw DDS wire (the vendor C++/Python SDK over CycloneDDS, no rclpy)
  every ROS topic name carries ROS 2's ``rt/`` mangling. A raw-DDS subscriber
  on the unmangled name receives ZERO MESSAGES AND NO ERROR. So every DDS
  channel carries both names and :func:`subscribe_name` refuses to guess which
  stack the caller is on — there is no default argument to get wrong.
* Any channel whose rate is a configuration decision rather than a device
  constant carries :attr:`RateKind.CONFIGURED` and ``nominal_rate_hz=None``, so
  a consumer cannot compute an "expected count" from a number nobody chose.
  ``None`` never means "no expectation is enforced"; it means the consumer must
  obtain the rate from the capture configuration or report the channel as
  unassessable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

#: The document this table transcribes, repo-relative. PS-D cites it when a
#: probe contradicts a declared expectation.
CHANNEL_MATRIX_DOC = "scrum/20260813/task_1/CHANNEL_MATRIX.md"

#: The external-research record that corrected this table. Cited beside the
#: matrix doc so a reader of a six-month-old bag can find out why a row says
#: what it says.
CHANNEL_MATRIX_CORRECTIONS_DOC = "scrum/20260813/task_1/RISK_ASSESSMENT.md"

#: Numbered rows in table A (channels) of that document. Pinned so a matrix
#: edit that adds a row without adding a channel reddens the gate instead of
#: silently shrinking the session's coverage.
CHANNEL_MATRIX_ROWS = 25

#: Numbered rows in table B (payload fields of record) of that document.
PAYLOAD_FIELD_ROWS = 11

#: Where every declaration in this module comes from. Not one of them is a
#: reading from our unit; PS-D replaces them one probe at a time.
DECLARATION_BASIS = "documentation_derived"

#: When each declaration is to be replaced by a measurement from OUR hardware.
#: The session run-sheet allocates this block before anything else happens.
MEASUREMENT_WINDOW = "session_first_45_minutes"

#: ROS 2 mangles every topic name it publishes over DDS. Reading a ROS topic
#: with a raw DDS subscriber therefore means subscribing to ``rt/<name>``; on
#: the unmangled name the reader is simply silent, with no error and no
#: diagnostic. This constant exists so that fact is in the code, not in a
#: person's memory at 06:00 on a session morning.
DDS_ROS_TOPIC_PREFIX = "rt/"

#: ``frame_id`` for channels that carry no spatial datum at all (an operator
#: button press, a platform telemetry line, a device health record).
#: Deliberately not the empty string — ``bags/schema.py:make_envelope`` refuses
#: an empty ``frame_id``, and an empty frame that silently means "base_link" is
#: how frames get lost.
NON_SPATIAL_FRAME = "non_spatial"


class CaptureError(ValueError):
    """Base for every refusal raised by :mod:`parcel_robot.capture`."""


class UnknownChannelError(CaptureError):
    """A channel id that is not in :data:`CHANNELS`. Unknown is absent."""


class UnknownPayloadFieldError(CaptureError):
    """A field id that is not in :data:`PAYLOAD_FIELDS`. Unknown is absent."""


class SourceDevice(str, Enum):
    """The physical unit a channel comes off. One box, one entry."""

    GO2 = "go2"
    L2 = "l2"
    D455 = "d455"
    ORIN = "orin"
    GNSS = "gnss"
    UWB = "uwb"
    MIC = "mic"
    # ---- CARD HW-3 (mid360-band, scrum/20260822/task_36) ----------------
    #: The Livox Mid-360 that ships fitted on the Go2 EDU+ (design §2.3).
    #: A distinct box from the built-in head LiDAR (:attr:`L2`): different
    #: vendor, different transport, different mount. Its rows are
    #: :data:`MID360_CHANNELS`, beside the payload matrix — see the CARD HW-3
    #: block further down for why they are not in :data:`CHANNELS`.
    MID360 = "mid360"
    # ---- END CARD HW-3 ---------------------------------------------------


class Transport(str, Enum):
    """How the bytes reach the capture process. Every member is read-only.

    There is deliberately no member for a command or request path. The capture
    process subscribes, reads a device handle, or scrapes a platform tool; it
    has no transport that can write to the robot.

    The membership of this enum is pinned by ``record.py``'s dependency tables
    (an unmapped transport raises at import), so a new transport is a
    cross-card change. The front camera's H.264 path did not need one: it is a
    vendor media stream, which is what :attr:`VENDOR_VIDEO` already meant —
    only the address was wrong.
    """

    #: CycloneDDS via ``unitree_ros2`` (rclpy, ROS names) or the vendor SDK
    #: (raw DDS, ``rt/``-mangled names). EDU-only exposure. Both namings are
    #: carried per channel; see :func:`subscribe_name`.
    DDS = "dds"
    #: The add-on L2's own transport: Ethernet/UDP or ``/dev/ttyACM0``.
    UNILIDAR_SDK2 = "unilidar_sdk2"
    #: A vendor media stream that is NOT a DDS topic. On the Go2 this is the
    #: front camera's H.264 elementary stream carried as RTP over multicast.
    VENDOR_VIDEO = "vendor_video"
    #: The RealSense SDK over USB3.
    REALSENSE = "realsense"
    #: A platform tool scraped line-by-line on the Orin (``tegrastats``).
    PLATFORM_TOOL = "platform_tool"
    #: A serial character device carrying NMEA/UBX.
    SERIAL = "serial"
    #: Vendor UWB fob path; the ranging protocol is undocumented to us.
    VENDOR_UWB = "vendor_uwb"
    #: USB audio class capture from the XVF3800 mic array.
    USB_AUDIO = "usb_audio"


class WireNaming(str, Enum):
    """Which naming a subscriber will use on the wire. There is no default.

    The two stacks disagree about the name of the same topic, and the
    disagreement is SILENT: a raw-DDS reader subscribed to ``lowstate`` instead
    of ``rt/lowstate`` returns no messages, raises nothing, and looks exactly
    like a robot that is not publishing. :func:`subscribe_name` therefore
    demands this argument rather than defaulting to either one.
    """

    #: ``rclpy`` / ``unitree_ros2``: the caller passes the ROS name and the ROS
    #: middleware applies the ``rt/`` mangling itself.
    ROS2 = "ros2"
    #: The vendor SDK or a bare CycloneDDS reader: the caller must pass the
    #: already-mangled name.
    RAW_DDS = "raw_dds"


class RateKind(str, Enum):
    """What kind of rate expectation a channel carries.

    This exists so ``nominal_rate_hz=None`` is never ambiguous. A consumer that
    computes an expected message count must branch on this, not on ``None``.
    """

    #: The device publishes at a device-fixed rate; ``nominal_rate_hz`` is set.
    PERIODIC = "periodic"
    #: Messages appear only when something happens; a count expectation is
    #: meaningless and silence is not evidence of a fault.
    EVENT_DRIVEN = "event_driven"
    #: The rate is chosen at capture-configuration time (PS-E's budget
    #: decision, or a device setting read at preflight). No nominal exists here.
    CONFIGURED = "configured"
    #: We do not know the rate and have not measured it. Fail closed: a
    #: consumer must report this channel as unassessable, never as nominal.
    UNKNOWN = "unknown"


class SourceClock(str, Enum):
    """What time, if any, the PAYLOAD itself carries. Drives card PS-I.

    ``CaptureEnvelope.source_timestamp_ns`` is nullable for a reason, and this
    field says per channel whether it can ever be non-null and what the number
    would be worth. The finding that forced it: ``LowState`` — the 500 Hz IMU
    channel, the most valuable stream on the dog — has NO timestamp field at
    all, only ``tick``, a ``uint32`` millisecond counter that wraps. The PS-1
    clock card assumed every device could be asked for a time; the dog cannot
    be, and ``SportModeState.stamp`` is the only real source-clock anchor it
    emits.
    """

    #: The payload carries an absolute device time (a ``TimeSpec``, or a ROS
    #: ``header.stamp`` populated on the device).
    DEVICE_TIMESPEC = "device_timespec"
    #: The payload carries a free-running counter that WRAPS. It is not a
    #: timestamp: it orders messages within one unwrapped span and nothing
    #: more. ``source_timestamp_ns`` must stay null for such a channel.
    WRAPPING_COUNTER = "wrapping_counter"
    #: The payload carries no time field at all. The host receipt clock is the
    #: only clock, and cross-device alignment must come from the PS-I sync
    #: ritual rather than from arithmetic.
    ABSENT = "absent"
    #: We have not read the message definition or the field's semantics. Fail
    #: closed: treat as :attr:`ABSENT` until a message is on the bench.
    UNVERIFIED = "unverified"

    @property
    def is_usable_anchor(self) -> bool:
        """True only for a real device time. A counter is never an anchor."""

        return self is SourceClock.DEVICE_TIMESPEC


class Confidence(str, Enum):
    """How good the DOCUMENTATION behind a row is. Never evidence.

    Carried per row because RISK_ASSESSMENT.md carries it per correction, and
    dropping it at transcription time is how "true of Go2 EDUs described
    online" becomes "true of our unit" without anyone deciding it. Every member
    means the same thing operationally: PS-D still has to receive a message.
    """

    #: Multiple independent sources, or a message definition read directly.
    CONFIRMED = "confirmed"
    #: One credible source, or a first-hand field report we cannot reproduce.
    LIKELY = "likely"
    #: Inference, a single ambiguous mention, or a guess we are recording as a
    #: guess so that it can be falsified.
    UNVERIFIED = "unverified"


class Criticality(str, Enum):
    """What the absence of this channel costs the session.

    Feeds PS-D's go/no-go and PS-F's degrade-to-*mount, measure, photograph*
    failure branch. It never gates arming — nothing in this package can arm
    anything — and it is not a recording priority: bandwidth is a PS-E
    decision, and every non-camera channel together is a rounding error against
    the D455.
    """

    #: Absence means the session did not achieve the thing it exists for.
    CRITICAL = "critical"
    #: Absence materially degrades the dataset; the session still yields value.
    IMPORTANT = "important"
    #: Record if present. Absence is an expected outcome and costs nothing.
    OPPORTUNISTIC = "opportunistic"


class ChannelPresence(str, Enum):
    """Our PRIOR about whether a channel exists — never evidence that it does.

    PS-D replaces this with a probe result per channel. There is no path from
    :attr:`LIVE` to "present": only a received message is that.
    """

    #: Expected present on the confirmed hardware.
    LIVE = "live"
    #: The topic is expected to EXIST, but what fills it is an on-robot service
    #: rather than sensor firmware, so it can carry a publisher and emit
    #: nothing. Distinguishing that from a bad DDS config costs session time,
    #: which is why it is a declared state and not a surprise.
    VERIFY_IN_SESSION = "verify_in_session"
    #: In the BOM or the vendor kit, presence unverified. Confirm on hand.
    CONFIRM_ON_HAND = "confirm_on_hand"
    #: Known absent today; the slot exists so it drops in without redesign.
    AWAITING_HARDWARE = "awaiting_hardware"


#: The 25 numbered rows of CHANNEL_MATRIX.md table A, titles verbatim. Kept
#: beside the channel table so a reader can audit coverage without the document
#: open.
MATRIX_ROW_TITLES: Mapping[int, str] = MappingProxyType(
    {
        1: "Built-in LiDAR cloud",
        2: "Built-in LiDAR IMU",
        3: "Vendor LiDAR odometry (PoseStamped)",
        4: "Vendor voxel map",
        5: "Sport mode state",
        6: "Low state",
        7: "Low-freq mirrors",
        8: "Wireless controller",
        9: "Front camera (DDS, JPEG per frame)",
        10: "L2 point cloud",
        11: "L2 IMU",
        12: "Color",
        13: "Depth",
        14: "Infrared ×2",
        15: "D455 internal IMU",
        16: "CPU/GPU load, thermal zones, power rails, NVMe throughput",
        17: "GNSS ZED-F9P (NMEA/UBX, NTRIP)",
        18: "UWB owner fob (range/bearing)",
        19: "XVF3800 mic array (4-mic + AEC ref)",
        20: "Built-in LiDAR state / health",
        21: "Built-in LiDAR deskewed cloud",
        22: "Vendor LiDAR odometry (Odometry, with covariance)",
        23: "Built-in LiDAR switch (subscribe-only)",
        24: "Front camera H.264 (RTP over multicast)",
        25: "UWB state (DDS)",
    }
)

#: The 11 numbered rows of CHANNEL_MATRIX.md table B: fields of record that
#: live INSIDE a channel's message. Not channels; see the module docstring.
FIELD_ROW_TITLES: Mapping[int, str] = MappingProxyType(
    {
        1: "range_obstacle[4] — the only non-LiDAR proximity sensing",
        2: "stamp (TimeSpec) — the only source-clock anchor on the dog",
        3: "tick (uint32 ms, wraps) — LowState has no timestamp",
        4: "power_v / power_a — the Wave-4 runtime number",
        5: "wireless_remote[40] — gap-free 500 Hz controller copy",
        6: "motor_state[20] — 12 actuated joints, 12..19 are padding",
        7: "foot_force[4] AND foot_force_est[4] — both exist",
        8: "bms_state — no voltage field",
        9: "imu_state — body IMU inside LowState",
        10: "fan_frequency[4] — thermal evidence",
        11: "temperature_ntc1 / temperature_ntc2 — thermal evidence",
    }
)

_ID_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.")


@dataclass(frozen=True, slots=True)
class Channel:
    """One independently-sequenced sensor stream.

    Every field except :attr:`channel_id`, :attr:`matrix_row` and
    :attr:`criticality` is a transcription of vendor documentation, of
    CHANNEL_MATRIX.md, or of RISK_ASSESSMENT.md's corrections, and is therefore
    falsifiable at preflight rather than authoritative. See the module
    docstring.
    """

    #: Stable dotted id, ``<device>.<path>``. This is the key everything else
    #: in the capture stack joins on, so it must never be renamed once a bag
    #: exists that uses it.
    channel_id: str
    human_name: str
    device: SourceDevice
    transport: Transport
    #: Topic, device path, multicast endpoint, or tool invocation — whatever
    #: the transport addresses the stream by. For DDS this is the ROS name.
    address: str
    #: For DDS channels ONLY: the same topic as it appears on the raw DDS wire,
    #: i.e. ``rt/`` + :attr:`address`. ``None`` for every other transport.
    #: Never derive this at the call site: see :func:`subscribe_name`.
    wire_address: str | None
    #: DECLARED type. ROS/IDL names for DDS channels, media-type-ish strings
    #: for the vendor and platform paths so the two are never confused.
    message_type: str
    rate_kind: RateKind
    nominal_rate_hz: float | None
    #: What time the payload itself carries, if any. Drives PS-I.
    source_clock: SourceClock
    #: DECLARED frame. The transform BETWEEN these frames is unmeasured — there
    #: is no TF implementation in this repo (``pose.py`` ``Frame`` is a
    #: two-member enum with no transform function) and the mount extrinsics are
    #: PS-F's tape measure. Naming a frame here does not locate it.
    frame_id: str
    criticality: Criticality
    presence: ChannelPresence
    #: Quality of the documentation behind this row. Never evidence.
    confidence: Confidence
    #: Which numbered row of CHANNEL_MATRIX.md table A this stream came from.
    matrix_row: int
    #: Why this channel is worth its bandwidth, or what is unverified about it.
    note: str

    def __post_init__(self) -> None:
        if not self.channel_id or set(self.channel_id) - _ID_ALPHABET:
            raise CaptureError(
                f"channel_id must be lowercase [a-z0-9_.]: {self.channel_id!r}"
            )
        if "." not in self.channel_id.strip("."):
            raise CaptureError(
                f"channel_id must be dotted <device>.<path>: {self.channel_id!r}"
            )
        if not self.human_name.strip():
            raise CaptureError(f"{self.channel_id}: human_name must be non-empty")
        if not self.address.strip():
            raise CaptureError(f"{self.channel_id}: address must be non-empty")
        if not self.message_type.strip():
            raise CaptureError(f"{self.channel_id}: message_type must be non-empty")
        if not self.frame_id.strip():
            raise CaptureError(f"{self.channel_id}: frame_id must be non-empty")
        if not self.note.strip():
            raise CaptureError(f"{self.channel_id}: note must be non-empty")
        if not isinstance(self.source_clock, SourceClock):
            raise CaptureError(
                f"{self.channel_id}: source_clock must be a SourceClock member, got "
                f"{self.source_clock!r} — an undeclared payload clock is how a null "
                f"timestamp becomes an assumed one"
            )
        if not isinstance(self.confidence, Confidence):
            raise CaptureError(
                f"{self.channel_id}: confidence must be a Confidence member, got "
                f"{self.confidence!r} — an unmarked external claim reads as a fact"
            )
        if self.matrix_row not in MATRIX_ROW_TITLES:
            raise CaptureError(
                f"{self.channel_id}: matrix_row {self.matrix_row!r} is not a row of "
                f"{CHANNEL_MATRIX_DOC}"
            )
        self._check_wire_address()
        if self.rate_kind is RateKind.PERIODIC:
            rate = self.nominal_rate_hz
            if not isinstance(rate, float) or not rate > 0.0 or rate == float("inf"):
                raise CaptureError(
                    f"{self.channel_id}: PERIODIC requires a finite positive "
                    f"nominal_rate_hz, got {rate!r}"
                )
        elif self.nominal_rate_hz is not None:
            raise CaptureError(
                f"{self.channel_id}: {self.rate_kind.value} must not carry a "
                f"nominal_rate_hz ({self.nominal_rate_hz!r}) — a rate nobody chose "
                f"is not an expectation"
            )

    def _check_wire_address(self) -> None:
        """A DDS row states BOTH names, and they must agree by construction.

        The failure this forbids is silent by nature: a raw-DDS reader on an
        unmangled name gets zero messages and no error. So a DDS row without a
        wire name, a wire name that is not the mangled form of the ROS name,
        and a non-DDS row that carries one at all are all refusals.
        """

        if self.transport is Transport.DDS:
            if self.address.startswith(DDS_ROS_TOPIC_PREFIX):
                raise CaptureError(
                    f"{self.channel_id}: address {self.address!r} is the raw-DDS name; "
                    f"address holds the ROS name and wire_address holds the "
                    f"{DDS_ROS_TOPIC_PREFIX!r}-mangled one"
                )
            expected = DDS_ROS_TOPIC_PREFIX + self.address
            if self.wire_address != expected:
                raise CaptureError(
                    f"{self.channel_id}: DDS wire_address must be {expected!r}, got "
                    f"{self.wire_address!r} — a raw-DDS reader on the wrong name is "
                    f"silent, not noisy"
                )
        elif self.wire_address is not None:
            raise CaptureError(
                f"{self.channel_id}: wire_address is DDS-only, but transport is "
                f"{self.transport.value} and wire_address is {self.wire_address!r}"
            )

    @property
    def bag_topic(self) -> str:
        """The channel id as a ``parcel.bag.v1`` topic (``a/b`` hierarchical).

        PS-B needs one string that satisfies ``bags/schema.py:validate_topic``.
        Deriving it here rather than storing a second name keeps the two from
        drifting; the test pins it against the real validator.
        """

        return self.channel_id.replace(".", "/")

    @property
    def is_spatial(self) -> bool:
        return self.frame_id != NON_SPATIAL_FRAME

    @property
    def carries_a_time_anchor(self) -> bool:
        """True only where the payload can anchor a cross-device fit (PS-I)."""

        return self.source_clock.is_usable_anchor


@dataclass(frozen=True, slots=True)
class PayloadField:
    """A field of record INSIDE a channel's message. Never a channel.

    It has no independent arrival, so it gets no sequence space of its own: it
    is present exactly when its parent message is, and a "drop" of it is a drop
    of the parent. It is enumerated because the PS-1 matrix's silence about
    these fields was read as their absence — ``range_obstacle[4]`` is the only
    non-LiDAR proximity sensing on the dog and appeared in no document, and
    ``power_v`` is the Wave-4 runtime number the plan says nobody has, sitting
    inside a message we were already recording.
    """

    #: Dotted id: the parent channel id, then the field path.
    field_id: str
    human_name: str
    parent_channel_id: str
    #: The declared IDL shape, e.g. ``float32[4]``. Transcribed, falsifiable.
    spec: str
    confidence: Confidence
    #: Which numbered row of CHANNEL_MATRIX.md table B this field came from.
    matrix_field_row: int
    note: str

    def __post_init__(self) -> None:
        if not self.field_id or set(self.field_id) - _ID_ALPHABET:
            raise CaptureError(
                f"field_id must be lowercase [a-z0-9_.]: {self.field_id!r}"
            )
        if not self.field_id.startswith(self.parent_channel_id + "."):
            raise CaptureError(
                f"{self.field_id!r} must be dotted under its parent "
                f"{self.parent_channel_id!r} — a field id that does not name its "
                f"parent cannot be joined back to the message it arrived in"
            )
        if not self.human_name.strip():
            raise CaptureError(f"{self.field_id}: human_name must be non-empty")
        if not self.spec.strip():
            raise CaptureError(f"{self.field_id}: spec must be non-empty")
        if not self.note.strip():
            raise CaptureError(f"{self.field_id}: note must be non-empty")
        if not isinstance(self.confidence, Confidence):
            raise CaptureError(
                f"{self.field_id}: confidence must be a Confidence member, got "
                f"{self.confidence!r}"
            )
        if self.matrix_field_row not in FIELD_ROW_TITLES:
            raise CaptureError(
                f"{self.field_id}: matrix_field_row {self.matrix_field_row!r} is not a "
                f"table-B row of {CHANNEL_MATRIX_DOC}"
            )


CHANNELS: tuple[Channel, ...] = (
    # -- A. Unitree Go2 EDU, via DDS -------------------------------------
    Channel(
        channel_id="go2.utlidar.cloud",
        human_name="Built-in LiDAR point cloud",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="utlidar/cloud",
        wire_address="rt/utlidar/cloud",
        message_type="sensor_msgs/msg/dds_/PointCloud2_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=10.0,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id="go2_utlidar_link",
        criticality=Criticality.CRITICAL,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.CONFIRMED,
        matrix_row=1,
        note=(
            "Built-in unit. Model is REPO-CONTRADICTED (Unitree says L2, "
            "P5_PROCUREMENT_BOM.md:35 says L1); row 20 settles it "
            "ELECTRONICALLY from utlidar/lidar_state rather than by reading "
            "either document. header.stamp is a device stamp we have not "
            "verified against the dog's own clock."
        ),
    ),
    Channel(
        channel_id="go2.utlidar.imu",
        human_name="Built-in LiDAR IMU",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="utlidar/imu",
        wire_address="rt/utlidar/imu",
        message_type="sensor_msgs/msg/dds_/Imu_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=200.0,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id="go2_utlidar_imu_link",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.CONFIRM_ON_HAND,
        confidence=Confidence.LIKELY,
        matrix_row=2,
        note=(
            "Matrix says 'LIVE if published'. An unverified publication is not "
            "LIVE. TWO INDEPENDENT FIELD REPORTS have this topic emitting "
            "|accel| of order 1e24 m/s^2, which a receipt-count probe attests "
            "as healthy — this row is the reason the PS-J plausibility gate "
            "exists. Assert |accel| = 9.81 +/- 1 at rest before believing it."
        ),
    ),
    Channel(
        channel_id="go2.utlidar.robot_pose",
        human_name="Vendor LiDAR odometry (PoseStamped)",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="utlidar/robot_pose",
        wire_address="rt/utlidar/robot_pose",
        message_type="geometry_msgs/msg/dds_/PoseStamped_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=10.0,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id="odom",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.VERIFY_IN_SESSION,
        confidence=Confidence.LIKELY,
        matrix_row=3,
        note=(
            "SERVICE-GATED, not sensor firmware: the topic can exist with a "
            "publisher and emit nothing, indistinguishable from a bad DDS "
            "config. Free localisation baseline IF it runs — but running our "
            "own SLAM plausibly requires the built-in obstacle avoidance OFF, "
            "and that is what drives this output. OPEN QUESTION, one take in "
            "each state settles it; do not plan on having both at once."
        ),
    ),
    Channel(
        channel_id="go2.utlidar.voxel_map",
        human_name="Vendor compressed voxel map",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="utlidar/voxel_map_compressed",
        wire_address="rt/utlidar/voxel_map_compressed",
        message_type="std_msgs/msg/dds_/String_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=1.0,
        source_clock=SourceClock.ABSENT,
        frame_id="go2_vendor_map",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.VERIFY_IN_SESSION,
        confidence=Confidence.LIKELY,
        matrix_row=4,
        note=(
            "SERVICE-GATED like row 3, and subject to the same "
            "obstacle-avoidance-OFF question. message_type is the least "
            "certain entry in this table (a compressed blob in a String_, "
            "which carries no header and therefore no stamp); PS-D reads the "
            "advertised type off DDS discovery."
        ),
    ),
    Channel(
        channel_id="go2.sportmodestate",
        human_name="Sport mode state",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="sportmodestate",
        wire_address="rt/sportmodestate",
        message_type="unitree_go/msg/dds_/SportModeState_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=50.0,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id="odom",
        criticality=Criticality.CRITICAL,
        presence=ChannelPresence.VERIFY_IN_SESSION,
        confidence=Confidence.LIKELY,
        matrix_row=5,
        note=(
            "SERVICE-GATED: produced by the sport service, not by sensor "
            "firmware, so it can carry a publisher and emit nothing. It is "
            "nonetheless CRITICAL, because field rows 1 and 2 live in it: "
            "range_obstacle[4] is the ONLY non-LiDAR proximity sensing on the "
            "dog, and stamp is the ONLY real source-clock anchor the robot "
            "emits. If this topic is silent, PS-I loses its anchor and the "
            "sync ritual becomes the only cross-device timing evidence."
        ),
    ),
    Channel(
        channel_id="go2.lowstate",
        human_name="Low state",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="lowstate",
        wire_address="rt/lowstate",
        message_type="unitree_go/msg/dds_/LowState_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=500.0,
        source_clock=SourceClock.WRAPPING_COUNTER,
        frame_id="base_link",
        criticality=Criticality.CRITICAL,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.CONFIRMED,
        matrix_row=6,
        note=(
            "The densest channel on the dog and the one with NO TIMESTAMP: "
            "only tick, a uint32 ms counter that wraps (field row 3). Carries "
            "field rows 3-11 — power_v/power_a, wireless_remote[40], "
            "motor_state[20] of which only 12 are actuated, BOTH foot_force[4] "
            "and foot_force_est[4], a BMS with no voltage field, fan and NTC "
            "temperatures. Foot force is the only ground-truth contact signal "
            "we will ever get: the sim is kinematic (UNVERIFIED.md:24-35)."
        ),
    ),
    Channel(
        channel_id="go2.lf.lowstate",
        human_name="Low-frequency low-state mirror",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="lf/lowstate",
        wire_address="rt/lf/lowstate",
        message_type="unitree_go/msg/dds_/LowState_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=10.0,
        source_clock=SourceClock.WRAPPING_COUNTER,
        frame_id="base_link",
        criticality=Criticality.OPPORTUNISTIC,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.LIKELY,
        matrix_row=7,
        note=(
            "Cheap redundancy: a downsampled mirror survives if the 500 Hz "
            "stream is the one the writer starves. Same payload, so the same "
            "field rows and the same missing timestamp apply."
        ),
    ),
    Channel(
        channel_id="go2.lf.sportmodestate",
        human_name="Low-frequency sport-state mirror",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="lf/sportmodestate",
        wire_address="rt/lf/sportmodestate",
        message_type="unitree_go/msg/dds_/SportModeState_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=10.0,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id="odom",
        criticality=Criticality.OPPORTUNISTIC,
        presence=ChannelPresence.VERIFY_IN_SESSION,
        confidence=Confidence.LIKELY,
        matrix_row=7,
        note=(
            "Second topic of matrix row 7. Separate stream, separate sequence "
            "— sharing one counter with lf/lowstate would hide a drop on "
            "either behind the other's traffic. Service-gated with its 50 Hz "
            "parent, so it is not a fallback if the sport service is down."
        ),
    ),
    Channel(
        channel_id="go2.wirelesscontroller",
        human_name="Wireless handheld state",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="wirelesscontroller",
        wire_address="rt/wirelesscontroller",
        message_type="unitree_go/msg/dds_/WirelessController_",
        rate_kind=RateKind.EVENT_DRIVEN,
        nominal_rate_hz=None,
        source_clock=SourceClock.ABSENT,
        frame_id=NON_SPATIAL_FRAME,
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.CONFIRMED,
        matrix_row=8,
        note=(
            "Timestamped only by our receipt — the message carries no stamp. "
            "Record of every operator action, which is what makes an incident "
            "reconstructable, and a free take-annotation channel. Field row 5 "
            "is the same information sampled gap-free at 500 Hz inside "
            "LowState; record both and cross-check them. Event-driven: "
            "silence is not a fault."
        ),
    ),
    # -- B. Go2 front camera: ON the DDS topic set, plus an RTP path -------
    Channel(
        channel_id="go2.front_camera",
        human_name="Go2 front camera (DDS, JPEG per frame)",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="frontvideostream",
        wire_address="rt/frontvideostream",
        message_type="unitree_go/msg/dds_/Go2FrontVideoData_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=33.0,
        source_clock=SourceClock.UNVERIFIED,
        frame_id="go2_front_camera_optical_frame",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.CONFIRMED,
        matrix_row=9,
        note=(
            "CORRECTION (RISK_ASSESSMENT.md row 1): the PS-1 matrix said the "
            "front camera is 'not on the DDS topic set'. It is. "
            "Go2FrontVideoData_ = time_frame + video720p/video360p/video180p, "
            "JPEG PER FRAME, ~33 Hz, so a ROS-side recorder reaches it after "
            "all. time_frame's epoch and units are unread, hence an UNVERIFIED "
            "payload clock. JPEG per frame is far more bandwidth than the "
            "H.264 the PS-1 budget assumed — see row 24."
        ),
    ),
    # -- C. Add-on Unitree L2, via its own SDK ----------------------------
    Channel(
        channel_id="l2.cloud",
        human_name="Add-on L2 point cloud",
        device=SourceDevice.L2,
        transport=Transport.UNILIDAR_SDK2,
        address="udp://l2 or /dev/ttyACM0",
        wire_address=None,
        message_type="unilidar_sdk2/PointCloud",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id="l2_lidar_link",
        criticality=Criticality.CRITICAL,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.CONFIRMED,
        matrix_row=10,
        note=(
            "Matrix says ~10-20 Hz; scan rate is a device setting, so PS-D "
            "reads it off the unit rather than this table guessing. Two "
            "LiDARs at a measured relative extrinsic is the cross-validation "
            "asset for every SLAM candidate — and PS-F must verify the two "
            "FOVs OVERLAP before final torque, because no post-hoc "
            "LiDAR-to-LiDAR calibration tool can recover an extrinsic between "
            "units that never share a view."
        ),
    ),
    Channel(
        channel_id="l2.imu",
        human_name="Add-on L2 IMU",
        device=SourceDevice.L2,
        transport=Transport.UNILIDAR_SDK2,
        address="udp://l2 or /dev/ttyACM0",
        wire_address=None,
        message_type="unilidar_sdk2/IMU",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=200.0,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id="l2_imu_link",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.LIKELY,
        matrix_row=11,
        note=(
            "Separate SDK from the built-in unit; the two are not the same "
            "device. Its factory IP 192.168.1.2 collides conceptually with the "
            "Go2's 192.168.1.7 and with the commonest home subnet — put it on "
            "a second NIC (RISK_ASSESSMENT.md platform risk 6)."
        ),
    ),
    # -- D. RealSense D455 -------------------------------------------------
    Channel(
        channel_id="d455.color",
        human_name="D455 color stream",
        device=SourceDevice.D455,
        transport=Transport.REALSENSE,
        address="rs.stream.color",
        wire_address=None,
        message_type="image/rgb8",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.UNVERIFIED,
        frame_id="camera_color_optical_frame",
        criticality=Criticality.CRITICAL,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.CONFIRMED,
        matrix_row=12,
        note=(
            "The raw-pixel source. Resolution/rate/format is PS-E's budget "
            "decision, not a default: 1280x720/30 colour+depth is 131.8 MiB/s "
            "(~464 GiB/h); 848x480 is 58.2 MiB/s (~205 GiB/h) — arithmetic "
            "independently re-verified. PAYLOAD CLOCK UNVERIFIED: the pip "
            "wheel is reported to cost UVC per-frame metadata, which is "
            "exactly the device timestamp PS-I depends on."
        ),
    ),
    Channel(
        channel_id="d455.depth",
        human_name="D455 depth stream",
        device=SourceDevice.D455,
        transport=Transport.REALSENSE,
        address="rs.stream.depth",
        wire_address=None,
        message_type="image/z16",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.UNVERIFIED,
        frame_id="camera_depth_optical_frame",
        criticality=Criticality.CRITICAL,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.CONFIRMED,
        matrix_row=13,
        note="Half the D455 budget; see d455.color for the arithmetic and the clock risk.",
    ),
    Channel(
        channel_id="d455.infra1",
        human_name="D455 infrared left",
        device=SourceDevice.D455,
        transport=Transport.REALSENSE,
        address="rs.stream.infrared:1",
        wire_address=None,
        message_type="image/y8",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.UNVERIFIED,
        frame_id="camera_infra1_optical_frame",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.CONFIRMED,
        matrix_row=14,
        note=(
            "CORRECTION (RISK_ASSESSMENT.md row 9): the PS-1 matrix called the "
            "IR pair 'nearly free'. It is not. Two Y8 streams equal the Z16 "
            "stream EXACTLY: +40% disk and +50% USB bandwidth. 720p with all "
            "streams on is ~1327 Mb/s, above Intel's own ~1200 Mb/s ceiling "
            "AND above the ~110-120 MB/s rosbag2 recorder ceiling. Still worth "
            "recording — it is the only channel that works in the dark and the "
            "only independent stereo baseline — but it is a BUDGET DECISION."
        ),
    ),
    Channel(
        channel_id="d455.infra2",
        human_name="D455 infrared right",
        device=SourceDevice.D455,
        transport=Transport.REALSENSE,
        address="rs.stream.infrared:2",
        wire_address=None,
        message_type="image/y8",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.UNVERIFIED,
        frame_id="camera_infra2_optical_frame",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.CONFIRMED,
        matrix_row=14,
        note=(
            "Second stream of matrix row 14 ('Infrared x2'). Its own sequence: "
            "a stereo pair that shares a counter cannot report which eye "
            "dropped, which is the whole defect this package fixes. Costs the "
            "same as its twin; see d455.infra1."
        ),
    ),
    Channel(
        channel_id="d455.accel",
        human_name="D455 internal accelerometer",
        device=SourceDevice.D455,
        transport=Transport.REALSENSE,
        address="rs.stream.accel",
        wire_address=None,
        message_type="imu/accel_xyz",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.UNVERIFIED,
        frame_id="camera_imu_optical_frame",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.LIKELY,
        matrix_row=15,
        note=(
            "BMI055. The RealSense SDK delivers accel and gyro as two motion "
            "streams at two selectable rates, so they are two channels. "
            "D455-on-Orin-NX has open unfixed reports of a DEAD IMU as well as "
            "~80% RGB drop; confirm with the vendor motion demo tonight, not "
            "on the dog."
        ),
    ),
    Channel(
        channel_id="d455.gyro",
        human_name="D455 internal gyroscope",
        device=SourceDevice.D455,
        transport=Transport.REALSENSE,
        address="rs.stream.gyro",
        wire_address=None,
        message_type="imu/gyro_xyz",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.UNVERIFIED,
        frame_id="camera_imu_optical_frame",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.LIKELY,
        matrix_row=15,
        note="Second stream of matrix row 15; see d455.accel.",
    ),
    # -- E. Orin NX platform telemetry -------------------------------------
    Channel(
        channel_id="orin.tegrastats",
        human_name="Orin platform telemetry",
        device=SourceDevice.ORIN,
        transport=Transport.PLATFORM_TOOL,
        address="tegrastats --interval <ms>",
        wire_address=None,
        message_type="text/tegrastats-line",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.ABSENT,
        frame_id=NON_SPATIAL_FRAME,
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.CONFIRMED,
        matrix_row=16,
        note=(
            "Not a sensor; the only way the session can answer 'how long can "
            "we run' and 'did we thermally throttle mid-take' (PLAN:1271 "
            "defers exactly this to Wave 4). Interval is a CLI flag. A text "
            "line carries no device clock at all."
        ),
    ),
    # -- F. Conditional; confirm on hand at preflight ----------------------
    Channel(
        channel_id="gnss.zed_f9p",
        human_name="GNSS ZED-F9P",
        device=SourceDevice.GNSS,
        transport=Transport.SERIAL,
        address="/dev/ttyACM* (NMEA/UBX)",
        wire_address=None,
        message_type="text/nmea0183+ubx",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id="gnss_antenna_link",
        criticality=Criticality.OPPORTUNISTIC,
        presence=ChannelPresence.CONFIRM_ON_HAND,
        confidence=Confidence.LIKELY,
        matrix_row=17,
        note=(
            "P5_PROCUREMENT_BOM.md:31 item 4. Neither the inventory nor the "
            "repo confirms it is on hand; navigation rate is a receiver "
            "setting. If it IS on hand it is the best clock in the rig — GNSS "
            "time is absolute — so PS-I should record it even with no fix, "
            "and note whether a PPS line is wired."
        ),
    ),
    Channel(
        channel_id="uwb.owner_fob",
        human_name="UWB owner fob range/bearing (vendor path)",
        device=SourceDevice.UWB,
        transport=Transport.VENDOR_UWB,
        address="vendor uwb path",
        wire_address=None,
        message_type="vendor/uwb_range_bearing",
        rate_kind=RateKind.UNKNOWN,
        nominal_rate_hz=None,
        source_clock=SourceClock.UNVERIFIED,
        frame_id="uwb_anchor_link",
        criticality=Criticality.OPPORTUNISTIC,
        presence=ChannelPresence.CONFIRM_ON_HAND,
        confidence=Confidence.UNVERIFIED,
        matrix_row=18,
        note=(
            "BOM optional B, usually ships with the Go2. The owner-tracking "
            "evidence in backlog/UNVERIFIED.md U39 says is uncharacterised. "
            "This row is the VENDOR path and row 25 is the DDS topic; they are "
            "two candidate paths to ONE measurement, so if both deliver they "
            "are not two independent observations. Protocol and rate both "
            "undocumented to us, which is why this row is UNVERIFIED."
        ),
    ),
    Channel(
        channel_id="mic.xvf3800",
        human_name="XVF3800 mic array",
        device=SourceDevice.MIC,
        transport=Transport.USB_AUDIO,
        address="hw:XVF3800 (4 mic + AEC ref)",
        wire_address=None,
        message_type="audio/pcm_s16le",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.ABSENT,
        frame_id="xvf3800_link",
        criticality=Criticality.OPPORTUNISTIC,
        presence=ChannelPresence.AWAITING_HARDWARE,
        confidence=Confidence.CONFIRMED,
        matrix_row=19,
        note=(
            "BOM item 5, in the post (BLOCKED.md:74-97 B3). The slot exists so "
            "audio drops in without redesign; it records nothing today."
        ),
    ),
    # -- G. Added by PS-H: channels the PS-1 matrix missed entirely --------
    Channel(
        channel_id="go2.utlidar.lidar_state",
        human_name="Built-in LiDAR state / health",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="utlidar/lidar_state",
        wire_address="rt/utlidar/lidar_state",
        message_type="unitree_go/msg/dds_/LidarState_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=1.0,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id=NON_SPATIAL_FRAME,
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.LIKELY,
        matrix_row=20,
        note=(
            "The cheapest high-value row on this table. It settles the "
            "L1-vs-L2 contradiction ELECTRONICALLY (firmware/software/SDK "
            "version and serial strings) instead of by squinting at a sticker, "
            "and it carries cloud and IMU packet-LOSS RATE plus rotation "
            "speed — a per-take health record that turns 'the cloud looked "
            "thin' into a number. One message per second, ~256 B."
        ),
    ),
    Channel(
        channel_id="go2.utlidar.cloud_deskewed",
        human_name="Built-in LiDAR deskewed cloud",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="utlidar/cloud_deskewed",
        wire_address="rt/utlidar/cloud_deskewed",
        message_type="sensor_msgs/msg/dds_/PointCloud2_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=10.0,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id="go2_utlidar_link",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.LIVE,
        confidence=Confidence.LIKELY,
        matrix_row=21,
        note=(
            "The motion-compensated twin of row 1. Recording BOTH is the only "
            "way to learn what the vendor's deskew actually does to our data, "
            "and every SLAM candidate we evaluate will want one or the other. "
            "Costs a second cloud (~0.7 MiB/s), which is a rounding error "
            "against the D455."
        ),
    ),
    Channel(
        channel_id="go2.utlidar.robot_odom",
        human_name="Vendor LiDAR odometry (Odometry, with covariance)",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="utlidar/robot_odom",
        wire_address="rt/utlidar/robot_odom",
        message_type="nav_msgs/msg/dds_/Odometry_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=10.0,
        source_clock=SourceClock.DEVICE_TIMESPEC,
        frame_id="odom",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.VERIFY_IN_SESSION,
        confidence=Confidence.LIKELY,
        matrix_row=22,
        note=(
            "Not a duplicate of row 3: an Odometry_ carries twist and BOTH "
            "covariance blocks, and covariance is the thing this repo's pose "
            "layer fabricates when it has none (pose.py:945-954 returns "
            "ZERO_COVARIANCE with health=HEALTHY). Same service gating and "
            "same obstacle-avoidance-OFF question as rows 3 and 4."
        ),
    ),
    Channel(
        channel_id="go2.utlidar.switch",
        human_name="Built-in LiDAR switch (subscribe-only)",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="utlidar/switch",
        wire_address="rt/utlidar/switch",
        message_type="std_msgs/msg/dds_/String_",
        rate_kind=RateKind.EVENT_DRIVEN,
        nominal_rate_hz=None,
        source_clock=SourceClock.ABSENT,
        frame_id=NON_SPATIAL_FRAME,
        criticality=Criticality.OPPORTUNISTIC,
        presence=ChannelPresence.VERIFY_IN_SESSION,
        confidence=Confidence.LIKELY,
        matrix_row=23,
        note=(
            "READ THIS ROW BEFORE USING IT. Unlike every other row in this "
            "table, the vendor stack treats this topic as an INPUT: writing "
            "'ON'/'OFF' to it toggles the built-in LiDAR. We subscribe and "
            "never write — board rule 1, and nothing in this package can write "
            "to a transport at all. Recorded because it is the only evidence "
            "of who toggled the LiDAR mid-session and when, which otherwise "
            "reads in the bag as an unexplained sensor dropout. Expect "
            "silence: it only carries traffic when something toggles it."
        ),
    ),
    Channel(
        channel_id="go2.front_camera_h264",
        human_name="Go2 front camera H.264 (RTP over multicast)",
        device=SourceDevice.GO2,
        transport=Transport.VENDOR_VIDEO,
        address="rtp://230.1.1.1:1720 (H.264 elementary stream)",
        wire_address=None,
        message_type="video/h264+rtp",
        rate_kind=RateKind.UNKNOWN,
        nominal_rate_hz=None,
        source_clock=SourceClock.WRAPPING_COUNTER,
        frame_id="go2_front_camera_optical_frame",
        criticality=Criticality.OPPORTUNISTIC,
        presence=ChannelPresence.VERIFY_IN_SESSION,
        confidence=Confidence.LIKELY,
        matrix_row=24,
        note=(
            "CORRECTION (RISK_ASSESSMENT.md row 1): the H.264 path exists but "
            "is NOT a topic — it is RTP over multicast 230.1.1.1:1720, so no "
            "topic-based recorder reaches it and a multicast-unfriendly switch "
            "or NIC config drops it silently. Same camera as row 9, roughly an "
            "order of magnitude cheaper than per-frame JPEG, so it is the "
            "fallback if row 9's bandwidth is unaffordable. Its RTP timestamp "
            "is a 90 kHz counter with a random initial offset: without RTCP "
            "sender reports it anchors to nothing."
        ),
    ),
    Channel(
        channel_id="go2.uwbstate",
        human_name="UWB state (DDS)",
        device=SourceDevice.GO2,
        transport=Transport.DDS,
        address="uwbstate",
        wire_address="rt/uwbstate",
        message_type="unitree_go/msg/dds_/UwbState_",
        rate_kind=RateKind.PERIODIC,
        nominal_rate_hz=20.0,
        source_clock=SourceClock.ABSENT,
        frame_id="uwb_anchor_link",
        criticality=Criticality.OPPORTUNISTIC,
        presence=ChannelPresence.CONFIRM_ON_HAND,
        confidence=Confidence.LIKELY,
        matrix_row=25,
        note=(
            "The on-robot side of row 18: if the UWB module is fitted, this is "
            "the topic its range/bearing arrives on, and it costs nothing to "
            "subscribe. Rate is a documentation figure, not a reading. Rows 18 "
            "and 25 are two paths to ONE measurement — recording both is "
            "fail-closed (we do not know which works), but a consumer must not "
            "treat them as independent observations of the owner's position."
        ),
    ),
)


CHANNELS_BY_ID: Mapping[str, Channel] = MappingProxyType(
    {entry.channel_id: entry for entry in CHANNELS}
)

if len(CHANNELS_BY_ID) != len(CHANNELS):  # pragma: no cover - import-time invariant
    raise CaptureError("duplicate channel_id in CHANNELS")

_WIRE_NAMES = [
    entry.wire_address for entry in CHANNELS if entry.wire_address is not None
]
if len(set(_WIRE_NAMES)) != len(_WIRE_NAMES):  # pragma: no cover - import-time
    raise CaptureError(
        "two channels claim the same raw-DDS wire name; one of them would record "
        "the other's traffic under its own sequence space"
    )


PAYLOAD_FIELDS: tuple[PayloadField, ...] = (
    PayloadField(
        field_id="go2.sportmodestate.range_obstacle",
        human_name="Obstacle range ring",
        parent_channel_id="go2.sportmodestate",
        spec="float32[4]",
        confidence=Confidence.CONFIRMED,
        matrix_field_row=1,
        note=(
            "MISSED ENTIRELY by the PS-1 matrix. This is the ONLY non-LiDAR "
            "proximity sensing on the dog, it is free, it is inside a message "
            "we were already recording, and it is unrecoverable after "
            "power-down. Units and sensing modality are undocumented to us — "
            "record it and characterise it later against LiDAR range."
        ),
    ),
    PayloadField(
        field_id="go2.sportmodestate.stamp",
        human_name="Device TimeSpec",
        parent_channel_id="go2.sportmodestate",
        spec="TimeSpec (sec:int32, nanosec:uint32)",
        confidence=Confidence.CONFIRMED,
        matrix_field_row=2,
        note=(
            "THE ONLY REAL SOURCE-CLOCK ANCHOR the dog emits. Everything PS-I "
            "does about dog-to-host offset rests on this one field, and it "
            "arrives on a SERVICE-GATED channel at 50 Hz. If sportmodestate is "
            "silent there is no device clock at all, and the bracketed "
            "physical sync ritual becomes the only cross-device timing "
            "evidence the session produces."
        ),
    ),
    PayloadField(
        field_id="go2.lowstate.tick",
        human_name="Millisecond tick (wraps)",
        parent_channel_id="go2.lowstate",
        spec="uint32 (milliseconds, wraps at ~49.7 days)",
        confidence=Confidence.CONFIRMED,
        matrix_field_row=3,
        note=(
            "CORRECTION: the PS-1 matrix implied lowstate carries a usable "
            "timestamp. It carries NO timestamp field at all — only this "
            "counter, in milliseconds, which wraps. It orders messages within "
            "one unwrapped span and is not an absolute time; a consumer that "
            "differences it across a wrap gets a ~49.7-day jump. The channel's "
            "source_clock is WRAPPING_COUNTER for exactly this reason and "
            "source_timestamp_ns must stay null on it."
        ),
    ),
    PayloadField(
        field_id="go2.lowstate.power_v_power_a",
        human_name="Pack voltage and current",
        parent_channel_id="go2.lowstate",
        spec="float32 power_v, float32 power_a",
        confidence=Confidence.CONFIRMED,
        matrix_field_row=4,
        note=(
            "MISSED ENTIRELY by the PS-1 matrix, and it is THE WAVE-4 RUNTIME "
            "NUMBER the plan says nobody has (PLAN:1271) — sitting in a "
            "message we were already recording. v x a integrated over a take "
            "answers 'how long can we run with this payload'. Also the "
            "documented substitute for the pack voltage BmsState does not "
            "carry (field row 8)."
        ),
    ),
    PayloadField(
        field_id="go2.lowstate.wireless_remote",
        human_name="Controller byte block, sampled at 500 Hz",
        parent_channel_id="go2.lowstate",
        spec="uint8[40]",
        confidence=Confidence.CONFIRMED,
        matrix_field_row=5,
        note=(
            "MISSED ENTIRELY by the PS-1 matrix. A gap-free, time-aligned copy "
            "of the handheld state at 500 Hz — strictly better than the "
            "event-driven wirelesscontroller topic for reconstructing WHEN an "
            "operator acted, and a free session-annotation track (press a "
            "button to mark a take). Costs 40 B inside a message we already "
            "record."
        ),
    ),
    PayloadField(
        field_id="go2.lowstate.motor_state",
        human_name="Motor state array",
        parent_channel_id="go2.lowstate",
        spec="MotorState[20] — indices 0..11 actuated, 12..19 padding",
        confidence=Confidence.CONFIRMED,
        matrix_field_row=6,
        note=(
            "CORRECTION: the PS-1 matrix said '20x motor'. MotorState[20] is a "
            "FIXED UNION ARRAY sized for the largest Unitree platform; a Go2 "
            "has 12 ACTUATED JOINTS and indices 12-19 are padding. As written, "
            "an analyst would have reported 8 dropped channels. Each entry "
            "also carries mode and the q_raw/dq_raw/ddq_raw triplet alongside "
            "q/dq/ddq, plus tau_est, temperature and lost — the payload-load "
            "and thermal evidence Wave 4 wants."
        ),
    ),
    PayloadField(
        field_id="go2.lowstate.foot_force",
        human_name="Foot force, sensed and estimated",
        parent_channel_id="go2.lowstate",
        spec="int16 foot_force[4] AND int16 foot_force_est[4]",
        confidence=Confidence.CONFIRMED,
        matrix_field_row=7,
        note=(
            "CORRECTION: there are TWO arrays, not one. Record both — their "
            "difference is free evidence about which of them is sensed and "
            "which is derived. Both are int16 RAW COUNTS from an air-pressure "
            "contact proxy with no published units, gain or offset, so a "
            "zero-offset take (all four feet off the ground) at session start "
            "is the only thing that makes them interpretable later. This is "
            "the only ground-truth contact signal we will ever get: the sim is "
            "kinematic (UNVERIFIED.md:24-35)."
        ),
    ),
    PayloadField(
        field_id="go2.lowstate.bms_state",
        human_name="Battery management state",
        parent_channel_id="go2.lowstate",
        spec="BmsState: soc, current, cycle, cell_vol[15], bq_ntc[2], mcu_ntc[2]",
        confidence=Confidence.CONFIRMED,
        matrix_field_row=8,
        note=(
            "CORRECTION: the PS-1 matrix listed BMS 'voltage'. BmsState HAS NO "
            "VOLTAGE FIELD. Pack voltage is sum(cell_vol[15]) or, more "
            "directly, LowState.power_v (field row 4). A consumer that reads a "
            "voltage field here finds nothing and may substitute a default — "
            "which is precisely the fail-open this tranche exists to stop."
        ),
    ),
    PayloadField(
        field_id="go2.lowstate.imu_state",
        human_name="Body IMU inside LowState",
        parent_channel_id="go2.lowstate",
        spec="quaternion[4], gyroscope[3], accelerometer[3], rpy[3], temperature",
        confidence=Confidence.CONFIRMED,
        matrix_field_row=9,
        note=(
            "The 500 Hz body IMU, and the densest inertial channel in the rig. "
            "It is the reference against which utlidar/imu's reported 1e24 "
            "m/s^2 pathology is judged, and the signal the PS-I sync ritual's "
            "taps and still-twist-still segment will appear in."
        ),
    ),
    PayloadField(
        field_id="go2.lowstate.fan_frequency",
        human_name="Fan frequencies",
        parent_channel_id="go2.lowstate",
        spec="uint16[4]",
        confidence=Confidence.LIKELY,
        matrix_field_row=10,
        note=(
            "MISSED ENTIRELY by the PS-1 matrix. Fan speed is the robot's own "
            "statement about its thermal state and it costs 8 B inside a "
            "message we already record — Wave-4 thermal evidence for free. "
            "Field presence transcribed from the LowState definition, not read "
            "off our unit."
        ),
    ),
    PayloadField(
        field_id="go2.lowstate.temperature_ntc",
        human_name="NTC temperatures",
        parent_channel_id="go2.lowstate",
        spec="temperature_ntc1, temperature_ntc2",
        confidence=Confidence.LIKELY,
        matrix_field_row=11,
        note=(
            "MISSED ENTIRELY by the PS-1 matrix. Two body thermistors, "
            "distinct from the per-motor temperatures in field row 6 and from "
            "the BMS thermistors in field row 8. Units and placement are "
            "undocumented to us; record them and characterise later."
        ),
    ),
)


PAYLOAD_FIELDS_BY_ID: Mapping[str, PayloadField] = MappingProxyType(
    {entry.field_id: entry for entry in PAYLOAD_FIELDS}
)

if len(PAYLOAD_FIELDS_BY_ID) != len(PAYLOAD_FIELDS):  # pragma: no cover
    raise CaptureError("duplicate field_id in PAYLOAD_FIELDS")

for _field in PAYLOAD_FIELDS:  # pragma: no cover - import-time invariant
    if _field.parent_channel_id not in CHANNELS_BY_ID:
        raise CaptureError(
            f"{_field.field_id}: parent {_field.parent_channel_id!r} is not a channel — "
            f"a field of record must arrive inside something we actually record"
        )


# ---------------------------------------------------------------------------
# Support artifacts — card S-1 (scrum/20260814/task_1/REVISED_BOARD.md)
# ---------------------------------------------------------------------------
#
# The verified P0 this class exists for, executed on 2026-08-14: the recording
# plan carried FOUR optical image streams and NOT ONE ``camera_info``, no
# ``/tf`` and no ``/tf_static``. A bag with ``color/image_raw`` and no
# intrinsics or distortion model cannot feed any camera-involving SLAM or
# fusion; without transforms there are no extrinsics between the sensors
# either. The matrix enumerated *sensor* channels and never modelled
# *calibration and transform support artifacts* as a class — the gap was in the
# specification, so the fix is a specification object, not a prose note.
#
# A support artifact is NOT a channel. A channel is an independently-arriving,
# independently-dropping sensor stream and mints its own payload sequence
# space; a support artifact has no independent sensor arrival semantics — a
# ``camera_info`` message is the driver restating a calibration table, and a
# ``/tf_static`` message is a latched declaration. Minting a sequence space for
# one would fabricate drop evidence, which is the exact defect the channel
# table exists to prevent. So this class lives BESIDE :data:`CHANNELS`:
# ``CHANNEL_MATRIX.md`` (immutable, 20260813) stays payload-only, and this
# table is the machine-readable cross-reference that says what else a bag must
# carry before its payload is usable.


#: How many support artifacts this table declares. Pinned like
#: :data:`CHANNEL_MATRIX_ROWS` so an edit that drops one reddens a gate
#: instead of silently shrinking the completeness contract.
SUPPORT_ARTIFACT_ROWS = 8


class UnknownSupportArtifactError(CaptureError):
    """A support id that is not in :data:`SUPPORT_ARTIFACTS`. Unknown is absent."""


class SupportArtifactKind(str, Enum):
    """What kind of support evidence an artifact is."""

    #: ``sensor_msgs/msg/CameraInfo`` for one optical stream: intrinsics,
    #: distortion model and coefficients, at the stream's own resolution.
    CAMERA_INFO = "camera_info"
    #: Dynamic transforms (``/tf``).
    TF = "tf"
    #: Static transforms (``/tf_static``) — the sensor mounting extrinsics.
    TF_STATIC = "tf_static"
    #: A SHA-256 over the canonical decoded calibration set, bound into the
    #: sidecar so a one-byte change to any calibration payload is detectable.
    CALIBRATION_DIGEST = "calibration_digest"


class SupportNeed(str, Enum):
    """What the absence of this artifact does to a run. Never permissive.

    The members are ordered from hardest to softest, and the soft members
    exist so that "cannot exist" and "may be absent" are different words from
    "required": collapsing them is how the four camera_info topics went
    unrecorded in the first place.
    """

    #: Absent or mismatched at reconciliation/finalize time = refusal.
    REQUIRED = "required"
    #: Required, but a machine-readable static-transform snapshot captured
    #: before record start may stand in for the live topic — ``/tf_static`` is
    #: transient-local, so a recorder started after the publisher may never
    #: receive it. Neither captured nor snapshotted = refusal.
    SNAPSHOT_SUBSTITUTABLE = "snapshot_substitutable"
    #: Joins the recording plan; absence is a recorded finding, not a refusal.
    #: For ``/tf``: a stationary rig with no odometry publisher legitimately
    #: has no dynamic transforms, and refusing on that would gate the session
    #: on evidence that cannot exist for it.
    RECORDED_OPPORTUNISTIC = "recorded_opportunistic"
    #: No publisher for this artifact exists at all (the Go2 front camera has
    #: no CameraInfo source). The absence is recorded in the sidecar as a
    #: does-not-prove line — never silently passed, never a refusal that would
    #: push the operator to drop the stream from the recording.
    UNAVAILABLE_DOCUMENTED = "unavailable_documented"


class SupportScope(str, Enum):
    """Which payload channels an artifact vouches for."""

    #: Exactly the channels named in ``supports_channel_ids``.
    PER_CHANNEL = "per_channel"
    #: Every spatial channel of the rig (``supports_channel_ids`` empty by
    #: construction; the set is derived from the channel table, not restated).
    RIG_SPATIAL = "rig_spatial"


@dataclass(frozen=True, slots=True)
class SupportArtifact:
    """One calibration/transform artifact a complete bag must account for.

    Deliberately NOT a :class:`Channel`: it carries no ``rate_kind``, no
    ``nominal_rate_hz``, no ``presence`` prior and no sequence space. Its
    fields are transcriptions (``message_type``, topic derivation) plus this
    card's decisions (``need``), all falsifiable at preflight reconciliation.
    """

    #: Stable dotted id under the ``support.`` prefix, so it can never collide
    #: with a payload ``channel_id`` (those are ``<device>.<path>``).
    support_id: str
    kind: SupportArtifactKind
    human_name: str
    #: Payload channels this artifact vouches for (PER_CHANNEL scope only).
    supports_channel_ids: tuple[str, ...]
    need: SupportNeed
    scope: SupportScope
    #: Declared ROS interface type on the wire; ``None`` for artifacts that are
    #: not topics (the calibration digest is derived, not subscribed).
    message_type: str | None
    confidence: Confidence
    note: str

    def __post_init__(self) -> None:
        if not self.support_id or set(self.support_id) - _ID_ALPHABET:
            raise CaptureError(
                f"support_id must be lowercase [a-z0-9_.]: {self.support_id!r}"
            )
        if not self.support_id.startswith("support."):
            raise CaptureError(
                f"support_id must start with 'support.': {self.support_id!r} — the "
                f"prefix is what keeps a support artifact out of the payload id space"
            )
        if not self.human_name.strip():
            raise CaptureError(f"{self.support_id}: human_name must be non-empty")
        if not self.note.strip():
            raise CaptureError(f"{self.support_id}: note must be non-empty")
        if not isinstance(self.kind, SupportArtifactKind):
            raise CaptureError(
                f"{self.support_id}: kind must be a SupportArtifactKind member, got "
                f"{self.kind!r}"
            )
        if not isinstance(self.need, SupportNeed):
            raise CaptureError(
                f"{self.support_id}: need must be a SupportNeed member, got "
                f"{self.need!r} — an undeclared need reads as optional, which is the "
                f"fail-open this class exists to close"
            )
        if not isinstance(self.scope, SupportScope):
            raise CaptureError(
                f"{self.support_id}: scope must be a SupportScope member, got {self.scope!r}"
            )
        if not isinstance(self.confidence, Confidence):
            raise CaptureError(
                f"{self.support_id}: confidence must be a Confidence member, got "
                f"{self.confidence!r}"
            )
        if self.scope is SupportScope.PER_CHANNEL and not self.supports_channel_ids:
            raise CaptureError(
                f"{self.support_id}: PER_CHANNEL scope requires supports_channel_ids — "
                f"an artifact that vouches for nothing is prose, not a contract"
            )
        if self.scope is SupportScope.RIG_SPATIAL and self.supports_channel_ids:
            raise CaptureError(
                f"{self.support_id}: RIG_SPATIAL scope derives its channel set from the "
                f"table; restating it here is a second list that can drift"
            )
        if self.message_type is not None and not self.message_type.strip():
            raise CaptureError(
                f"{self.support_id}: message_type must be None or non-empty — an empty "
                f"string would read as 'any type matches' at reconciliation"
            )

    @property
    def is_topic_backed(self) -> bool:
        """True when this artifact arrives on a ROS topic at all."""

        return self.message_type is not None


#: Leaf basenames a camera image topic may end in, per the realsense2_camera /
#: image_transport convention. Documentation-derived like every other name.
_IMAGE_TOPIC_LEAVES = ("image_raw", "image_rect_raw", "image")


def camera_info_topic_for(image_topic: str) -> str:
    """The ``camera_info`` topic beside one image topic. Refuses to guess.

    The D455 driver publishes ``CameraInfo`` per stream under the SAME
    namespace as the stream's image topic (``.../color/image_raw`` →
    ``.../color/camera_info``). Deriving the name here — from the image topic
    the plan already carries — means a namespace change updates both names or
    neither, and there is no second hand-written list to go stale.

    Fail closed: a topic whose last segment is not a known image leaf is
    refused rather than mangled, because a wrong ``camera_info`` name costs
    nothing at record time (the recorder never subscribes) and everything at
    calibration time.
    """

    if not image_topic.startswith("/") or image_topic.endswith("/"):
        raise CaptureError(
            f"camera_info derivation needs an absolute image topic, got {image_topic!r}"
        )
    namespace, _, leaf = image_topic.rpartition("/")
    if leaf not in _IMAGE_TOPIC_LEAVES:
        raise CaptureError(
            f"{image_topic!r} does not end in an image leaf {_IMAGE_TOPIC_LEAVES}; "
            f"deriving a camera_info name from it would be a guess, and a wrong "
            f"support-topic name is silent at record time"
        )
    if not namespace:
        raise CaptureError(
            f"{image_topic!r} has no namespace to hang a camera_info topic under"
        )
    return f"{namespace}/camera_info"


SUPPORT_ARTIFACTS: tuple[SupportArtifact, ...] = (
    SupportArtifact(
        support_id="support.d455.color.camera_info",
        kind=SupportArtifactKind.CAMERA_INFO,
        human_name="D455 colour intrinsics (CameraInfo)",
        supports_channel_ids=("d455.color",),
        need=SupportNeed.REQUIRED,
        scope=SupportScope.PER_CHANNEL,
        message_type="sensor_msgs/msg/CameraInfo",
        confidence=Confidence.UNVERIFIED,
        note=(
            "Published by the realsense2_camera driver beside the image topic, at "
            "the stream's own resolution. UNVERIFIED like every driver topic name: "
            "H-2 measures it on the Orin. Without it the colour stream cannot feed "
            "any camera-involving SLAM or camera-LiDAR fusion — the P0 this class "
            "exists for."
        ),
    ),
    SupportArtifact(
        support_id="support.d455.depth.camera_info",
        kind=SupportArtifactKind.CAMERA_INFO,
        human_name="D455 depth intrinsics (CameraInfo)",
        supports_channel_ids=("d455.depth",),
        need=SupportNeed.REQUIRED,
        scope=SupportScope.PER_CHANNEL,
        message_type="sensor_msgs/msg/CameraInfo",
        confidence=Confidence.UNVERIFIED,
        note=(
            "Depth reprojection is arithmetic on these intrinsics; a depth image "
            "without them is a bitmap, not a point source."
        ),
    ),
    SupportArtifact(
        support_id="support.d455.infra1.camera_info",
        kind=SupportArtifactKind.CAMERA_INFO,
        human_name="D455 left-IR intrinsics (CameraInfo)",
        supports_channel_ids=("d455.infra1",),
        need=SupportNeed.REQUIRED,
        scope=SupportScope.PER_CHANNEL,
        message_type="sensor_msgs/msg/CameraInfo",
        confidence=Confidence.UNVERIFIED,
        note=(
            "The IR pair is the only independent stereo baseline on the rig; the "
            "baseline lives in the calibration, not in the pixels."
        ),
    ),
    SupportArtifact(
        support_id="support.d455.infra2.camera_info",
        kind=SupportArtifactKind.CAMERA_INFO,
        human_name="D455 right-IR intrinsics (CameraInfo)",
        supports_channel_ids=("d455.infra2",),
        need=SupportNeed.REQUIRED,
        scope=SupportScope.PER_CHANNEL,
        message_type="sensor_msgs/msg/CameraInfo",
        confidence=Confidence.UNVERIFIED,
        note="Second eye of the stereo pair; see support.d455.infra1.camera_info.",
    ),
    SupportArtifact(
        support_id="support.go2.front_camera.camera_info",
        kind=SupportArtifactKind.CAMERA_INFO,
        human_name="Go2 front camera intrinsics — NO PUBLISHER EXISTS",
        supports_channel_ids=("go2.front_camera", "go2.front_camera_h264"),
        need=SupportNeed.UNAVAILABLE_DOCUMENTED,
        scope=SupportScope.PER_CHANNEL,
        message_type=None,
        confidence=Confidence.CONFIRMED,
        note=(
            "The vendor stream (rows 9/24) carries JPEG/H.264 frames and nothing "
            "publishes a CameraInfo for them anywhere in the vendor stack. Recorded "
            "here so the absence is a stated property of the dataset — the front "
            "camera is usable as imagery, not as a calibrated sensor — rather than "
            "a silent gap a consumer discovers six months in."
        ),
    ),
    SupportArtifact(
        support_id="support.tf",
        kind=SupportArtifactKind.TF,
        human_name="Dynamic transforms (/tf)",
        supports_channel_ids=(),
        need=SupportNeed.RECORDED_OPPORTUNISTIC,
        scope=SupportScope.RIG_SPATIAL,
        message_type="tf2_msgs/msg/TFMessage",
        confidence=Confidence.UNVERIFIED,
        note=(
            "Whatever publishes odom->base_link (if anything does) is unverified. "
            "Recorded when present; a stationary rig with no odometry publisher "
            "legitimately has none, so absence is a finding, never a refusal."
        ),
    ),
    SupportArtifact(
        support_id="support.tf_static",
        kind=SupportArtifactKind.TF_STATIC,
        human_name="Static transforms (/tf_static) — sensor mounting extrinsics",
        supports_channel_ids=(),
        need=SupportNeed.SNAPSHOT_SUBSTITUTABLE,
        scope=SupportScope.RIG_SPATIAL,
        message_type="tf2_msgs/msg/TFMessage",
        confidence=Confidence.UNVERIFIED,
        note=(
            "TRANSIENT-LOCAL: published once, latched. A recorder started after "
            "the publisher may receive it (transient-local re-delivery) or may "
            "not, depending on QoS overrides — so the run must either capture it "
            "in the bag or bind a machine-readable static-transform snapshot "
            "taken before record start. Neither = the bag's frames are labels "
            "with no geometry = refusal."
        ),
    ),
    SupportArtifact(
        support_id="support.calibration.digest",
        kind=SupportArtifactKind.CALIBRATION_DIGEST,
        human_name="Calibration digest over the decoded CameraInfo set",
        supports_channel_ids=("d455.color", "d455.depth", "d455.infra1", "d455.infra2"),
        need=SupportNeed.REQUIRED,
        scope=SupportScope.PER_CHANNEL,
        message_type=None,
        confidence=Confidence.CONFIRMED,
        note=(
            "SHA-256 over the canonical decoded calibration set, computed from the "
            "bag's own bytes and bound into the sidecar. Not a topic: it exists so "
            "a one-byte change to any calibration payload after the session is a "
            "verification failure, not a silent recalibration."
        ),
    ),
)

SUPPORT_ARTIFACTS_BY_ID: Mapping[str, SupportArtifact] = MappingProxyType(
    {entry.support_id: entry for entry in SUPPORT_ARTIFACTS}
)

if len(SUPPORT_ARTIFACTS_BY_ID) != len(SUPPORT_ARTIFACTS):  # pragma: no cover
    raise CaptureError("duplicate support_id in SUPPORT_ARTIFACTS")

if len(SUPPORT_ARTIFACTS) != SUPPORT_ARTIFACT_ROWS:  # pragma: no cover
    raise CaptureError(
        f"SUPPORT_ARTIFACTS declares {len(SUPPORT_ARTIFACTS)} rows, the pinned count "
        f"is {SUPPORT_ARTIFACT_ROWS}; change both together or not at all"
    )

for _support in SUPPORT_ARTIFACTS:  # pragma: no cover - import-time invariant
    if _support.support_id in CHANNELS_BY_ID:
        raise CaptureError(
            f"{_support.support_id}: collides with a payload channel id — a support "
            f"artifact must never be able to mint a payload sequence space"
        )
    for _cid in _support.supports_channel_ids:
        if _cid not in CHANNELS_BY_ID:
            raise CaptureError(
                f"{_support.support_id}: supports unknown channel {_cid!r} — an "
                f"artifact for a stream we do not record vouches for nothing"
            )


# ---- CARD HW-3 (mid360-band, scrum/20260822/task_36) --------------------
#
# The venue changed. ``CHANNEL_MATRIX.md`` (immutable, 20260813) describes one
# rig: a Go2 EDU with an ADD-ON Unitree L2, a D455 and an Orin on a dock. The
# owner bought a different one — a Go2 EDU+ with a **Livox Mid-360 fitted at
# the factory** (design §2.3, hardware facts 5-7) — and the Mid-360's streams
# are on no numbered row of that document.
#
# They are declared BESIDE the matrix, exactly as card S-1 declared
# :data:`SUPPORT_ARTIFACTS` beside it, and for the same reason in reverse: the
# 25 rows / 28 channels / 11 field rows the whole tranche quotes are a
# TRANSCRIPTION, and inventing rows 26-27 in code would make this table claim
# a document that does not say that. Growing table A is a document change
# first, a table change second and a pin change third — a handoff to the
# capture-matrix owner on box-day (HW-9), recorded in ``HW3_STATUS.md``.
#
# What is NOT compromised: these rows carry every field a :class:`Channel`
# carries, their ids cannot collide with a payload channel's, and a DDS row
# still states both namings. What they do NOT get is a payload sequence space
# in the 28 — until the matrix says so.
#
# Transport: ``Transport.DDS`` describes the CAPTURE path only — the vendor
# ``livox_ros_driver2`` node in the rclpy capture venv, which is the reader
# that needs no new dependency (hardware fact 6). The RUNTIME path is
# ``parcel_robot.lidar`` decoding raw UDP off port 56300 with no ROS at all,
# and that is not a capture transport: a ``LIVOX_UDP`` member would have to
# land in ``scripts/parcel_capture/record.py``'s two dependency tables in the
# same commit (an unmapped transport raises at its import) and is therefore a
# cross-card change, per :class:`Transport`'s own docstring. Also a handoff.

#: How many venue rows this table declares. Pinned like
#: :data:`SUPPORT_ARTIFACT_ROWS` so a dropped row reddens a gate.
VENUE_CHANNEL_ROWS = 2

#: The venue these rows belong to — the same name HW-5's physical profile
#: takes (``configs/profiles/go2_edu_plus.yaml``, design §5.8).
GO2_EDU_PLUS_VENUE = "go2_edu_plus"


@dataclass(frozen=True, slots=True)
class VenueChannel:
    """A payload stream of a venue ``CHANNEL_MATRIX.md`` does not describe.

    Deliberately NOT a :class:`Channel`: a ``Channel`` asserts, in its
    ``__post_init__``, that it came off a numbered row of that document. This
    class asserts the opposite and names the venue instead. Everything else —
    the declared expectations, the DDS double-naming rule, the "a rate nobody
    chose is not an expectation" rule — is the same, because the reason for
    each of them is the same.
    """

    channel_id: str
    human_name: str
    device: SourceDevice
    transport: Transport
    address: str
    wire_address: str | None
    message_type: str
    rate_kind: RateKind
    nominal_rate_hz: float | None
    source_clock: SourceClock
    frame_id: str
    criticality: Criticality
    presence: ChannelPresence
    confidence: Confidence
    #: Which rig this stream exists on. Not a row number: there is no row.
    venue: str
    note: str

    def __post_init__(self) -> None:
        if not self.channel_id or set(self.channel_id) - _ID_ALPHABET:
            raise CaptureError(
                f"channel_id must be lowercase [a-z0-9_.]: {self.channel_id!r}"
            )
        if "." not in self.channel_id.strip("."):
            raise CaptureError(
                f"channel_id must be dotted <device>.<path>: {self.channel_id!r}"
            )
        # Spelled out rather than looped over field names with ``getattr``:
        # ``tests/test_no_arm_pin.py`` censuses every reach builtin in this
        # package by (file, function, builtin) and an exact census is worth
        # more here than six saved lines.
        for name, value in (
            ("human_name", self.human_name),
            ("address", self.address),
            ("message_type", self.message_type),
            ("frame_id", self.frame_id),
            ("venue", self.venue),
            ("note", self.note),
        ):
            if not str(value).strip():
                raise CaptureError(f"{self.channel_id}: {name} must be non-empty")
        if not isinstance(self.source_clock, SourceClock):
            raise CaptureError(
                f"{self.channel_id}: source_clock must be a SourceClock member, got "
                f"{self.source_clock!r} — an undeclared payload clock is how a null "
                f"timestamp becomes an assumed one"
            )
        if not isinstance(self.confidence, Confidence):
            raise CaptureError(
                f"{self.channel_id}: confidence must be a Confidence member, got "
                f"{self.confidence!r} — an unmarked external claim reads as a fact"
            )
        if self.rate_kind is RateKind.PERIODIC:
            rate = self.nominal_rate_hz
            if not isinstance(rate, float) or not rate > 0.0 or rate == float("inf"):
                raise CaptureError(
                    f"{self.channel_id}: PERIODIC requires a finite positive "
                    f"nominal_rate_hz, got {rate!r}"
                )
        elif self.nominal_rate_hz is not None:
            raise CaptureError(
                f"{self.channel_id}: {self.rate_kind.value} must not carry a "
                f"nominal_rate_hz ({self.nominal_rate_hz!r}) — a rate nobody chose "
                f"is not an expectation"
            )
        if self.transport is Transport.DDS:
            if self.address.startswith(DDS_ROS_TOPIC_PREFIX):
                raise CaptureError(
                    f"{self.channel_id}: address {self.address!r} is the raw-DDS name; "
                    f"address holds the ROS name and wire_address holds the "
                    f"{DDS_ROS_TOPIC_PREFIX!r}-mangled one"
                )
            expected = DDS_ROS_TOPIC_PREFIX + self.address
            if self.wire_address != expected:
                raise CaptureError(
                    f"{self.channel_id}: DDS wire_address must be {expected!r}, got "
                    f"{self.wire_address!r} — a raw-DDS reader on the wrong name is "
                    f"silent, not noisy"
                )
        elif self.wire_address is not None:
            raise CaptureError(
                f"{self.channel_id}: wire_address is DDS-only, but transport is "
                f"{self.transport.value} and wire_address is {self.wire_address!r}"
            )

    @property
    def bag_topic(self) -> str:
        return self.channel_id.replace(".", "/")

    @property
    def is_spatial(self) -> bool:
        return self.frame_id != NON_SPATIAL_FRAME

    @property
    def carries_a_time_anchor(self) -> bool:
        return self.source_clock.is_usable_anchor


_MID360_SOURCES = (
    "Read 2026-08-23: livox-SDK2 include/livox_lidar_def.h (frame layout), "
    "livox_ros_driver2 README (frame_id 'livox_frame', publish_freq 5/10/20/50, "
    "max 100, default 10; xfer_format 0 = 'Livox pointcloud2(PointXYZRTLT)'; "
    "HAP/Mid360/Mid360s/Avia2 supported) and samples/livox_lidar_quick_start/"
    "mid360_config.json (lidar ports cmd 56100 / push 56200 / point 56300 / imu "
    "56400 / log 56500, host ports +1, sample host 192.168.1.5). The TOPIC NAMES "
    "below are the driver's conventional defaults and are UNVERIFIED against a "
    "read of lddc.cpp — the one field of this row a session must check first."
)

MID360_CHANNELS: tuple[VenueChannel, ...] = (
    VenueChannel(
        channel_id="mid360.cloud",
        human_name="Livox Mid-360 point cloud",
        device=SourceDevice.MID360,
        transport=Transport.DDS,
        address="livox/lidar",
        wire_address="rt/livox/lidar",
        message_type="sensor_msgs/msg/PointCloud2 (Livox PointXYZRTLT)",
        rate_kind=RateKind.CONFIGURED,
        nominal_rate_hz=None,
        source_clock=SourceClock.UNVERIFIED,
        frame_id="livox_frame",
        criticality=Criticality.CRITICAL,
        presence=ChannelPresence.AWAITING_HARDWARE,
        confidence=Confidence.UNVERIFIED,
        venue=GO2_EDU_PLUS_VENUE,
        note=(
            "The runtime's planar scan comes from this sensor, but NOT through this "
            "row: parcel_robot.lidar decodes the raw UDP point frames off port 56300 "
            "and parcel_robot.lidar.band bins them into SimObservation.lidar_ranges "
            "(card HW-3, design §5.3). This row is the CAPTURE path — the vendor node "
            "in the rclpy venv, which is also what feeds a rosbag2 primary recording. "
            "SOURCE CLOCK UNVERIFIED on purpose: the frame carries a uint64 ns "
            "timestamp whose zero depends on the header's time_type (0 = since LiDAR "
            "power-on, which is NOT an absolute anchor; 1 = gPTP master), and which "
            "one a fitted Mid-360 emits is read off the unit, not from a table. "
            "Vertical FOV -7°..+52°: it sees up, not down — floor drops are the "
            "D455's job. " + _MID360_SOURCES
        ),
    ),
    VenueChannel(
        channel_id="mid360.imu",
        human_name="Livox Mid-360 IMU (ICM40609)",
        device=SourceDevice.MID360,
        transport=Transport.DDS,
        address="livox/imu",
        wire_address="rt/livox/imu",
        message_type="sensor_msgs/msg/Imu",
        rate_kind=RateKind.UNKNOWN,
        nominal_rate_hz=None,
        source_clock=SourceClock.UNVERIFIED,
        frame_id="livox_frame",
        criticality=Criticality.IMPORTANT,
        presence=ChannelPresence.AWAITING_HARDWARE,
        confidence=Confidence.UNVERIFIED,
        venue=GO2_EDU_PLUS_VENUE,
        note=(
            "RateKind.UNKNOWN and not a number: the Mid-360's IMU output rate is in "
            "none of the sources read, and a rate nobody measured must read as "
            "unassessable rather than as nominal. The raw path is data_type 0 on port "
            "56400, six float32s per sample; parcel_robot.lidar REFUSES that data_type "
            "in its point parser rather than claim units it has not read. Second-best "
            "IMU on the rig after the Go2's own LowState, and the input B17's LIO "
            "bake-off needs. " + _MID360_SOURCES
        ),
    ),
)

MID360_CHANNELS_BY_ID: Mapping[str, VenueChannel] = MappingProxyType(
    {entry.channel_id: entry for entry in MID360_CHANNELS}
)

if len(MID360_CHANNELS_BY_ID) != len(MID360_CHANNELS):  # pragma: no cover
    raise CaptureError("duplicate channel_id in MID360_CHANNELS")

if len(MID360_CHANNELS) != VENUE_CHANNEL_ROWS:  # pragma: no cover
    raise CaptureError(
        f"MID360_CHANNELS declares {len(MID360_CHANNELS)} rows, the pinned count is "
        f"{VENUE_CHANNEL_ROWS}; change both together or not at all"
    )

for _venue_channel in MID360_CHANNELS:  # pragma: no cover - import-time invariant
    if _venue_channel.channel_id in CHANNELS_BY_ID:
        raise CaptureError(
            f"{_venue_channel.channel_id}: collides with a payload channel id — a "
            f"venue row must never shadow a row of the matrix"
        )
    if _venue_channel.channel_id in SUPPORT_ARTIFACTS_BY_ID:
        raise CaptureError(
            f"{_venue_channel.channel_id}: collides with a support artifact id"
        )


def venue_channel(channel_id: str) -> VenueChannel:
    """Look up a venue channel, refusing anything not in the table.

    Refuses rather than falling through to :data:`CHANNELS`: "this stream is
    on the EDU+ but not in the matrix" and "this stream is in the matrix" are
    different answers and must not share a lookup.
    """

    try:
        return MID360_CHANNELS_BY_ID[channel_id]
    except (KeyError, TypeError) as exc:
        raise UnknownChannelError(
            f"unknown venue channel_id {channel_id!r}; known ids: "
            f"{', '.join(sorted(MID360_CHANNELS_BY_ID))}"
        ) from exc


def venue_channels_for(venue: str) -> tuple[VenueChannel, ...]:
    """Every declared venue row for one rig, in table order."""

    return tuple(entry for entry in MID360_CHANNELS if entry.venue == venue)


# ---- END CARD HW-3 -------------------------------------------------------


def support_artifact(support_id: str) -> SupportArtifact:
    """Look up a support artifact, refusing anything not in the table."""

    try:
        return SUPPORT_ARTIFACTS_BY_ID[support_id]
    except (KeyError, TypeError) as exc:
        raise UnknownSupportArtifactError(
            f"unknown support_id {support_id!r}; known ids: "
            f"{', '.join(sorted(SUPPORT_ARTIFACTS_BY_ID))}"
        ) from exc


def support_artifacts_for(channel_id: str) -> tuple[SupportArtifact, ...]:
    """Every support artifact that vouches for one payload channel.

    RIG_SPATIAL artifacts apply to every spatial channel; PER_CHANNEL ones to
    the channels they name. Refuses an unknown channel rather than returning an
    empty tuple, for the same reason :func:`payload_fields_of` does.
    """

    entry = channel(channel_id)
    out: list[SupportArtifact] = []
    for item in SUPPORT_ARTIFACTS:
        if item.scope is SupportScope.RIG_SPATIAL:
            if entry.is_spatial:
                out.append(item)
        elif channel_id in item.supports_channel_ids:
            out.append(item)
    return tuple(out)


def certified_optical_channel_ids() -> tuple[str, ...]:
    """The optical streams whose CameraInfo is REQUIRED — the GO-RECORD set.

    Derived from the support table, never restated: a stream is in this set
    exactly when a REQUIRED CAMERA_INFO artifact vouches for it. The Go2 front
    camera is deliberately not here (no publisher exists; its absence is
    documented, not gated).
    """

    out: list[str] = []
    for item in SUPPORT_ARTIFACTS:
        if item.kind is SupportArtifactKind.CAMERA_INFO and item.need is SupportNeed.REQUIRED:
            for cid in item.supports_channel_ids:
                if cid not in out:
                    out.append(cid)
    return tuple(out)


def channel(channel_id: str) -> Channel:
    """Look up a channel, refusing anything not in the matrix.

    Fail closed: an id we do not know is not a channel we may record under. A
    typo must not mint a new stream with its own sequence space at 03:00 on a
    session morning.
    """

    try:
        return CHANNELS_BY_ID[channel_id]
    except (KeyError, TypeError) as exc:
        raise UnknownChannelError(
            f"unknown channel_id {channel_id!r}; known ids: "
            f"{', '.join(sorted(CHANNELS_BY_ID))}"
        ) from exc


def channel_ids() -> tuple[str, ...]:
    """Every channel id, in table order."""

    return tuple(entry.channel_id for entry in CHANNELS)


def payload_field(field_id: str) -> PayloadField:
    """Look up a field of record, refusing anything not in table B."""

    try:
        return PAYLOAD_FIELDS_BY_ID[field_id]
    except (KeyError, TypeError) as exc:
        raise UnknownPayloadFieldError(
            f"unknown field_id {field_id!r}; known ids: "
            f"{', '.join(sorted(PAYLOAD_FIELDS_BY_ID))}"
        ) from exc


def payload_fields_of(channel_id: str) -> tuple[PayloadField, ...]:
    """Every field of record carried inside one channel, in table order.

    Refuses an unknown channel rather than returning an empty tuple: "this
    channel has no enumerated fields" and "this channel does not exist" are
    different answers and must not share a representation.
    """

    channel(channel_id)
    return tuple(
        entry for entry in PAYLOAD_FIELDS if entry.parent_channel_id == channel_id
    )


def subscribe_name(channel_id: str, naming: WireNaming) -> str:
    """The topic name a reader must use, for the stack it is actually on.

    There is deliberately NO DEFAULT for ``naming``. The failure being designed
    out is silent: a raw-DDS reader subscribed to ``lowstate`` rather than
    ``rt/lowstate`` receives zero messages and raises nothing, which looks
    exactly like a robot that is not publishing — and on a one-session day that
    is hours of debugging aimed at the wrong layer. Making the caller state
    which stack it is on turns that into a decision somebody made.

    Refuses for non-DDS channels: the L2, the camera and the platform tool are
    not addressed by topic, and returning their ``address`` here would let a
    caller believe the naming question had been answered for them.
    """

    entry = channel(channel_id)
    if not isinstance(naming, WireNaming):
        raise CaptureError(
            f"naming must be a WireNaming member, got {naming!r} — a bare string "
            f"never selects the wire, because the two namings differ silently"
        )
    if entry.transport is not Transport.DDS:
        raise CaptureError(
            f"{channel_id} is carried over {entry.transport.value}, which is not "
            f"addressed by topic name; its address is {entry.address!r}"
        )
    if naming is WireNaming.RAW_DDS:
        wire = entry.wire_address
        if wire is None:  # pragma: no cover - forbidden at construction
            raise CaptureError(f"{channel_id}: DDS channel with no wire_address")
        return wire
    return entry.address


def select_channels(
    *,
    presence: ChannelPresence | Iterable[ChannelPresence] | None = None,
    criticality: Criticality | Iterable[Criticality] | None = None,
    device: SourceDevice | Iterable[SourceDevice] | None = None,
    transport: Transport | Iterable[Transport] | None = None,
) -> tuple[Channel, ...]:
    """Filter the table. Omitted facets do not filter; they never widen."""

    presences = _as_set(presence, ChannelPresence)
    criticalities = _as_set(criticality, Criticality)
    devices = _as_set(device, SourceDevice)
    transports = _as_set(transport, Transport)
    return tuple(
        entry
        for entry in CHANNELS
        if (presences is None or entry.presence in presences)
        and (criticalities is None or entry.criticality in criticalities)
        and (devices is None or entry.device in devices)
        and (transports is None or entry.transport in transports)
    )


def _as_set(value: object, member_type: type) -> frozenset | None:
    if value is None:
        return None
    if isinstance(value, member_type):
        return frozenset({value})
    if isinstance(value, (str, bytes)):
        raise CaptureError(
            f"expected {member_type.__name__} members, got a raw string {value!r} — "
            f"a string never selects an enum here"
        )
    members = frozenset(value)  # type: ignore[call-overload]
    bad = {item for item in members if not isinstance(item, member_type)}
    if bad or not members:
        raise CaptureError(
            f"expected non-empty {member_type.__name__} members, got {value!r}"
        )
    return members


__all__ = [
    "CHANNELS",
    "CHANNELS_BY_ID",
    "CHANNEL_MATRIX_CORRECTIONS_DOC",
    "CHANNEL_MATRIX_DOC",
    "CHANNEL_MATRIX_ROWS",
    "DDS_ROS_TOPIC_PREFIX",
    "DECLARATION_BASIS",
    "FIELD_ROW_TITLES",
    "MATRIX_ROW_TITLES",
    "MEASUREMENT_WINDOW",
    "NON_SPATIAL_FRAME",
    "PAYLOAD_FIELDS",
    "PAYLOAD_FIELDS_BY_ID",
    "PAYLOAD_FIELD_ROWS",
    "SUPPORT_ARTIFACTS",
    "SUPPORT_ARTIFACTS_BY_ID",
    "SUPPORT_ARTIFACT_ROWS",
    "CaptureError",
    "Channel",
    "ChannelPresence",
    "Confidence",
    "Criticality",
    "PayloadField",
    "RateKind",
    "SourceClock",
    "SourceDevice",
    "SupportArtifact",
    "SupportArtifactKind",
    "SupportNeed",
    "SupportScope",
    "Transport",
    "UnknownChannelError",
    "UnknownPayloadFieldError",
    "UnknownSupportArtifactError",
    "WireNaming",
    "camera_info_topic_for",
    "certified_optical_channel_ids",
    "channel",
    "channel_ids",
    "payload_field",
    "payload_fields_of",
    "select_channels",
    "subscribe_name",
    "support_artifact",
    "support_artifacts_for",
]
