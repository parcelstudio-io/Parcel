"""``ros2 bag record -s mcap`` as the recorder of record — card PS-G.

The defect this module exists for
---------------------------------
``record.py:152-158`` writes ``MCAP_PROFILE = "parcel-capture"`` and
``message_encoding = "parcel.capture.envelope.v1+raw"`` with a JSON schema
record. **No tool in the next milestone can open that** — GLIM, FAST-LIO2,
Point-LIO-ROS2, KISS-ICP, Multi-LiCa, ros2_calib and
direct_visual_lidar_calibration all read ``rosbag2``. Recording a physical
session into a format only Parcel can read, to feed a pipeline made entirely of
tools that read rosbag2, is a session spent producing data nobody can use.

So the ruling, and it is cheap: **rosbag2 is the primary recorder** and needs no
new ingest code at all, while ``parcel-capture`` is demoted to the attestation +
clock-discipline + sidecar layer, which is where its value actually is. This
module is the primary path made first-class:

* :func:`record_command` emits the **exact** command line, including the
  ``/events/*`` topics, so nobody types it from memory at 08:00;
* :func:`storage_config_yaml` emits the MCAP writer options, with the
  crash-safety argument stated and a documented fallback for the case where the
  installed ``rosbag2_storage_mcap`` rejects a key;
* :data:`RECORDED_TOPICS` is the documented topic list derived from the PS-H
  corrected matrix, using **ROS** names (``rclpy`` applies the ``rt/`` mangling
  itself; handing a subscriber the wire name gets zero messages and no error);
* :class:`Rosbag2Scan` reads a rosbag2 MCAP with the standard library alone, so
  a bag can be counted, digested and classified on a machine with no ROS — which
  is every machine we have tonight;
* :func:`parse_bag_info` turns ``ros2 bag info`` into per-topic counts for the
  sidecar, and refuses rather than guesses on anything it does not recognise.

What is NOT here
----------------
No recorder. This module never writes a session bag: ``ros2 bag record`` does
that, and a second implementation of it would be a second thing to be wrong.
:func:`write_fixture_bag` writes rosbag2-shaped MCAP bytes for **tests and
tonight's dry run only**, and says so in its own docstring and in the library
string it stamps into the file.

Honesty about the storage config
--------------------------------
The key names and the accepted ``compression`` / ``compressionLevel`` spellings
in :func:`storage_config_yaml` were **measured** against
``rosbag2_storage_mcap`` 0.26.11 + ``libmcap`` 1.3.1: a real MCAP writer was
opened with the emitted file and wrote a real bag. They have still not been read
off the Orin, which runs Humble. If the installed version rejects the file,
``ros2 bag record`` fails **before** recording rather than silently ignoring it,
and the remedy is to drop ``--storage-config-file`` and re-run: the plugin's
default measured as chunked-and-uncompressed, which :func:`read_rosbag2_mcap`
counts, so you lose the crash-safety tuning and not the session.

Three defects PS-M found and fixed here, all of which recorded or read nothing
-----------------------------------------------------------------------------
1. ``Chunk.records`` was read as a uint32 length. The MCAP spec makes it the one
   uint64-prefixed byte array, so **every uncompressed chunked bag** — which is
   what ``ros2 bag record`` writes with no storage config — classified as
   CORRUPT with 0 messages, and the sidecar stamped that on healthy data.
2. ``compression: ""`` / ``compressionLevel: ""`` are not valid enum values.
   ``rosbag2_storage_mcap`` fails its YAML conversion and ``ros2 bag record``
   exits 1 having written **zero bytes** — measured, both profiles, both keys.
3. The argv carried ``--topics`` and ``--disable-keyboard-controls``, **neither
   of which exists in Humble's recorder verb**, where the topic list is
   positional. argparse exits 2 on an unknown option. See :class:`RosDistro`
   and :func:`validate_argv_against_help`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from parcel_robot.capture import CHANNELS, Transport
from parcel_robot.capture.channels import Confidence, WireNaming, subscribe_name

# --------------------------------------------------------------------------
# Wire constants
# --------------------------------------------------------------------------

MCAP_MAGIC = b"\x89MCAP0\r\n"

OP_HEADER = 0x01
OP_FOOTER = 0x02
OP_SCHEMA = 0x03
OP_CHANNEL = 0x04
OP_MESSAGE = 0x05
OP_CHUNK = 0x06
OP_MESSAGE_INDEX = 0x07
OP_CHUNK_INDEX = 0x08
OP_ATTACHMENT = 0x09
OP_ATTACHMENT_INDEX = 0x0A
OP_STATISTICS = 0x0B
OP_METADATA = 0x0C
OP_METADATA_INDEX = 0x0D
OP_SUMMARY_OFFSET = 0x0E
OP_DATA_END = 0x0F

#: The MCAP profile rosbag2 stamps. A file that does not carry it was not
#: written by rosbag2, and this module says so rather than assuming.
ROS2_PROFILE = "ros2"

#: ``Channel.message_encoding`` for every ROS 2 message: Common Data
#: Representation, which is what every downstream tool expects to decode.
ROS2_MESSAGE_ENCODING = "cdr"
ROS2_SCHEMA_ENCODING = "ros2msg"

STORAGE_ID = "mcap"

MAX_RECORD_BYTES = 512 * 1024 * 1024

_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_RECORD_HEADER = struct.Struct("<BQ")

#: Every integer width this module reads or writes, audited field by field
#: against the MCAP specification after ``Chunk.records`` was found being read
#: as a uint32. One wrong width was reason to check them all, and the audit is
#: recorded here rather than in a status document nobody re-reads: a future
#: edit that changes a width has to change this table too.
#:
#: ``(record, field, bits, note)``. Every row was additionally cross-checked
#: against bytes written by ``rosbag2_storage_mcap`` 0.26.11 / ``libmcap``
#: 1.3.1 — see ``tests/test_rosbag2_sidecar.py::REAL_ROSBAG2_CHUNKED_MCAP``,
#: which is a bag that real writer produced and which this reader now walks.
MCAP_INTEGER_WIDTHS: tuple[tuple[str, str, int, str], ...] = (
    ("file", "magic", 64, "8 bytes: 0x89 'MCAP' 0x30 CR LF, at both ends"),
    ("*", "opcode", 8, "every record: uint8 opcode"),
    ("*", "record length", 64, "every record: uint64 content length"),
    ("*", "String", 32, "uint32 byte length, then UTF-8"),
    ("*", "Bytes", 32, "uint32 byte length — EXCEPT Chunk.records"),
    ("Header", "profile/library", 32, "two Strings"),
    ("Schema", "id", 16, "uint16"),
    ("Schema", "data", 32, "uint32-prefixed Bytes"),
    ("Channel", "id / schema_id", 16, "two uint16"),
    ("Channel", "metadata", 32, "uint32-prefixed Map<string,string>; not decoded"),
    ("Message", "channel_id", 16, "uint16"),
    ("Message", "sequence", 32, "uint32"),
    ("Message", "log_time / publish_time", 64, "two uint64 Timestamps"),
    ("Message", "data", 0, "unprefixed: the remainder of the record"),
    ("Chunk", "message_start_time / message_end_time", 64, "two uint64 Timestamps"),
    ("Chunk", "uncompressed_size", 64, "uint64"),
    ("Chunk", "uncompressed_crc", 32, "uint32, 0 = do not verify"),
    ("Chunk", "compression", 32, "String; empty means uncompressed"),
    ("Chunk", "records", 64, "uint64 — THE EXCEPTION, and the defect that was here"),
    ("Statistics", "message_count", 64, "uint64"),
    ("Statistics", "schema_count", 16, "uint16 — narrower than the counts around it"),
    ("Statistics", "channel/attachment/metadata/chunk_count", 32, "four uint32"),
    ("Statistics", "message_start_time / message_end_time", 64, "two uint64"),
    ("Statistics", "channel_message_counts", 32, "uint32-prefixed Map<uint16,uint64>"),
    ("Footer", "summary_start / summary_offset_start", 64, "two uint64; not decoded"),
    ("Footer", "summary_crc", 32, "uint32; not decoded"),
    ("DataEnd", "data_section_crc", 32, "uint32; not decoded"),
)


class Rosbag2Error(RuntimeError):
    """Base for every refusal in this module."""


class Rosbag2RefusedError(Rosbag2Error):
    """A plan, a config or a call this module will not make."""


class Rosbag2ReadError(Rosbag2Error):
    """Bytes that could not be decoded. Never a partial guess."""


class NotAnMcapFileError(Rosbag2ReadError):
    """The file does not begin with the MCAP magic at all."""


# --------------------------------------------------------------------------
# The topic list — derived from the PS-H corrected matrix
# --------------------------------------------------------------------------


class TopicSource(str, Enum):
    """Where a ROS topic comes from. This decides what must be running.

    The distinction is operational, not taxonomic: a ``ROBOT_NATIVE`` topic
    appears when the dog is on and the ``unitree_ros2`` overlay is sourced, a
    ``DRIVER_NODE`` topic appears only if **we** launched its driver, and a
    ``RECORDER_EVENT`` topic is published by ``ros2 bag record`` itself. Three
    different failure modes, three different remedies, and mixing them is how a
    session records fifteen topics and misses the camera.
    """

    ROBOT_NATIVE = "robot_native"
    DRIVER_NODE = "driver_node"
    RECORDER_EVENT = "recorder_event"


@dataclass(frozen=True, slots=True)
class RecordedTopic:
    """One topic on the ``ros2 bag record`` command line.

    ``channel_id`` binds it back to the PS-A/PS-H matrix where one exists; a
    topic with no matrix row (the recorder's own event topics) carries ``None``
    and is enumerated in the sidecar as unmapped rather than dropped.
    """

    topic: str
    message_type: str
    source: TopicSource
    channel_id: str | None
    confidence: Confidence
    note: str
    #: What must already be running for this topic to exist. Empty for the
    #: recorder's own events.
    prerequisite: str = ""

    def __post_init__(self) -> None:
        if not self.topic.startswith("/"):
            raise Rosbag2RefusedError(
                f"{self.topic!r}: ros2 bag record takes ABSOLUTE ROS names; a relative "
                f"name resolves against the recorder's namespace, not the robot's"
            )
        if self.topic.startswith("/rt/"):
            raise Rosbag2RefusedError(
                f"{self.topic!r}: that is the raw-DDS wire name. rclpy applies the 'rt/' "
                f"mangling itself, so a recorder given the mangled name subscribes to "
                f"'rt/rt/...' and receives nothing, silently"
            )
        if not self.note.strip():
            raise Rosbag2RefusedError(f"{self.topic}: note must be non-empty")


def _dds_topics() -> tuple[RecordedTopic, ...]:
    """Every DDS row of the matrix, as an absolute ROS name.

    Built from :func:`subscribe_name` with :attr:`WireNaming.ROS2` rather than
    from the address string, so the ``rt/`` correction is applied by the module
    that owns it and cannot drift here.
    """

    topics: list[RecordedTopic] = []
    for entry in CHANNELS:
        if entry.transport is not Transport.DDS:
            continue
        ros_name = subscribe_name(entry.channel_id, WireNaming.ROS2)
        topics.append(
            RecordedTopic(
                topic="/" + ros_name,
                message_type=_ros_interface_name(entry.message_type),
                source=TopicSource.ROBOT_NATIVE,
                channel_id=entry.channel_id,
                confidence=entry.confidence,
                note=f"{entry.human_name} ({entry.criticality.value}, {entry.presence.value})",
                prerequisite=(
                    "dog powered on, on the same subnet, with the unitree_ros2 overlay "
                    "sourced and CycloneDDS bound to the right NIC"
                ),
            )
        )
    return tuple(topics)


def _ros_interface_name(declared: str) -> str:
    """``unitree_go/msg/dds_/LowState_`` -> ``unitree_go/msg/LowState``."""

    parts = declared.split("/")
    if len(parts) == 4 and parts[2] == "dds_" and parts[3].endswith("_"):
        return f"{parts[0]}/{parts[1]}/{parts[3][:-1]}"
    return declared


#: D455 and L2 topics as their standard ROS drivers publish them. These names
#: are **documentation-derived and UNVERIFIED**: they depend on the driver's
#: namespace and launch arguments, which is exactly why every row carries the
#: launch command that produces it and why the run-sheet's first act is
#: ``ros2 topic list``. A wrong name here costs nothing at record time — the
#: recorder simply never subscribes — which is precisely the silent failure the
#: pre-session topic check exists to catch.
DRIVER_TOPICS: tuple[RecordedTopic, ...] = (
    RecordedTopic(
        "/camera/camera/color/image_raw",
        "sensor_msgs/msg/Image",
        TopicSource.DRIVER_NODE,
        "d455.color",
        Confidence.UNVERIFIED,
        "D455 colour. Namespace depends on the launch's camera_name/camera_namespace.",
        "ros2 launch realsense2_camera rs_launch.py enable_color:=true enable_depth:=true",
    ),
    RecordedTopic(
        "/camera/camera/depth/image_rect_raw",
        "sensor_msgs/msg/Image",
        TopicSource.DRIVER_NODE,
        "d455.depth",
        Confidence.UNVERIFIED,
        "D455 depth (Z16). Half the bandwidth budget on its own at 720p30.",
        "ros2 launch realsense2_camera rs_launch.py enable_depth:=true",
    ),
    RecordedTopic(
        "/camera/camera/infra1/image_rect_raw",
        "sensor_msgs/msg/Image",
        TopicSource.DRIVER_NODE,
        "d455.infra1",
        Confidence.UNVERIFIED,
        "D455 left IR. The IR pair costs +40% disk and +50% USB; it is not free.",
        "ros2 launch realsense2_camera rs_launch.py enable_infra1:=true",
    ),
    RecordedTopic(
        "/camera/camera/infra2/image_rect_raw",
        "sensor_msgs/msg/Image",
        TopicSource.DRIVER_NODE,
        "d455.infra2",
        Confidence.UNVERIFIED,
        "D455 right IR. Together with infra1 it equals the Z16 stream exactly.",
        "ros2 launch realsense2_camera rs_launch.py enable_infra2:=true",
    ),
    RecordedTopic(
        "/camera/camera/accel/sample",
        "sensor_msgs/msg/Imu",
        TopicSource.DRIVER_NODE,
        "d455.accel",
        Confidence.UNVERIFIED,
        "D455 accelerometer. unite_imu_method must be set or the IMU topics do not appear.",
        "ros2 launch realsense2_camera rs_launch.py enable_accel:=true enable_gyro:=true",
    ),
    RecordedTopic(
        "/camera/camera/gyro/sample",
        "sensor_msgs/msg/Imu",
        TopicSource.DRIVER_NODE,
        "d455.gyro",
        Confidence.UNVERIFIED,
        "D455 gyroscope. Same unit as the accel stream; one IMU, two topics.",
        "ros2 launch realsense2_camera rs_launch.py enable_accel:=true enable_gyro:=true",
    ),
    RecordedTopic(
        "/unilidar/cloud",
        "sensor_msgs/msg/PointCloud2",
        TopicSource.DRIVER_NODE,
        "l2.cloud",
        Confidence.UNVERIFIED,
        "Add-on L2 cloud. Put the L2 on a second NIC: its factory 192.168.1.2 collides "
        "with the Go2's 192.168.1.7 subnet.",
        "ros2 launch unitree_lidar_ros2 launch.py",
    ),
    RecordedTopic(
        "/unilidar/imu",
        "sensor_msgs/msg/Imu",
        TopicSource.DRIVER_NODE,
        "l2.imu",
        Confidence.UNVERIFIED,
        "Add-on L2 IMU, one of the four independent IMUs on this rig.",
        "ros2 launch unitree_lidar_ros2 launch.py",
    ),
)

#: The recorder's own event topics. Recording them puts the recorder's account
#: of its own losses and splits INSIDE the bag, on the same clock as the data,
#: where it survives the process that produced it.
#:
#: ``/events/write_split`` is CONFIRMED: ``rosbag2_interfaces/msg/WriteSplitEvent``
#: is published on every bag split. ``/events/messages_lost`` is UNVERIFIED — the
#: recorder's message-loss reporting has moved between rosbag2 releases, and this
#: build has no ROS to check against. Listing a topic that does not exist costs
#: nothing at record time (the recorder never subscribes); assuming one that does
#: exist is not recorded costs the evidence. So both are listed, and the
#: pre-session ``ros2 topic list`` settles which arrived.
EVENT_TOPICS: tuple[RecordedTopic, ...] = (
    RecordedTopic(
        "/events/write_split",
        "rosbag2_interfaces/msg/WriteSplitEvent",
        TopicSource.RECORDER_EVENT,
        None,
        Confidence.CONFIRMED,
        "Emitted on every bag split. Without it, a split boundary is indistinguishable "
        "from a gap in the data.",
    ),
    RecordedTopic(
        "/events/messages_lost",
        "rosbag2_interfaces/msg/MessagesLost",
        TopicSource.RECORDER_EVENT,
        None,
        Confidence.UNVERIFIED,
        "The recorder's own account of what it dropped under backpressure. UNVERIFIED: "
        "confirm with `ros2 topic list` before the session; a missing topic here is a "
        "finding, not a failure.",
    ),
)

RECORDED_TOPICS: tuple[RecordedTopic, ...] = _dds_topics() + DRIVER_TOPICS + EVENT_TOPICS

TOPICS_BY_NAME: Mapping[str, RecordedTopic] = {item.topic: item for item in RECORDED_TOPICS}

CHANNEL_BY_TOPIC: Mapping[str, str] = {
    item.topic: item.channel_id for item in RECORDED_TOPICS if item.channel_id
}


def topics_for(
    *,
    include_driver_nodes: bool = True,
    include_events: bool = True,
    exclude: Sequence[str] = (),
) -> tuple[RecordedTopic, ...]:
    """The topic list for one take, with the exclusions stated explicitly."""

    unknown = sorted(set(exclude) - set(TOPICS_BY_NAME))
    if unknown:
        raise Rosbag2RefusedError(
            f"cannot exclude topics that are not on the list: {unknown} — an exclusion "
            f"that matches nothing is a typo that silently records everything"
        )
    chosen: list[RecordedTopic] = []
    for item in RECORDED_TOPICS:
        if item.topic in exclude:
            continue
        if item.source is TopicSource.DRIVER_NODE and not include_driver_nodes:
            continue
        if item.source is TopicSource.RECORDER_EVENT and not include_events:
            continue
        chosen.append(item)
    if not chosen:
        raise Rosbag2RefusedError("a recording with no topics records nothing")
    return tuple(chosen)


# --------------------------------------------------------------------------
# The plan: command line + storage config
# --------------------------------------------------------------------------


class WriterProfile(str, Enum):
    """Which MCAP writer shape to ask for. The trade is crash exposure vs index.

    ``CRASH_SAFE`` turns chunking off: every message reaches the file as its own
    record, so a SIGKILL or a flat battery costs the tail and nothing else, and a
    stdlib reader — :class:`Rosbag2Scan` — can still count every channel in a bag
    that was never closed. ``INDEXED`` uses uncompressed chunks, which gives fast
    seeking and a summary section at the cost of holding up to one chunk of
    messages in the writer's memory, which is exactly the state a crash destroys.

    Compression is off in both. It buys disk we have and costs CPU on an Orin
    that is already carrying the D455, and a compressed chunk is unreadable to
    every stdlib tool we own on a night when ``zstandard`` is not installed.
    """

    CRASH_SAFE = "crash_safe"
    INDEXED = "indexed"


class RosDistro(str, Enum):
    """Which ROS 2 the argv is for. The recorder's CLI is NOT the same on both.

    Verified in ``ros2/rosbag2``'s own ``ros2bag/verb/record.py``:

    * ``humble`` declares ``parser.add_argument('topics', nargs='*')`` — the
      topic list is **positional** — and the file contains no ``keyboard`` at
      all. There is **no** ``--topics`` and **no**
      ``--disable-keyboard-controls``. argparse rejects an unknown option, so an
      argv carrying either exits 2 having recorded nothing.
    * ``jazzy`` adds ``--topics`` (``nargs='+'``),
      ``--disable-keyboard-controls`` and ``--node-name``, and keeps the
      positional list with the warning ``Positional "topics" argument
      deprecated``.

    :attr:`HUMBLE` is therefore the fail-safe default: its argv is the
    intersection and runs on **both**. The Jazzy argv does not run on Humble,
    and JetPack 6.2 on the Orin is Humble.
    """

    HUMBLE = "humble"
    JAZZY = "jazzy"


#: Recorder flags that exist on some distros and not others, with the distros
#: that accept them. A flag absent from this table is on every distro we target
#: (``--storage``, ``--output``, ``--max-cache-size``, ``--max-bag-size``,
#: ``--max-bag-duration``, ``--storage-config-file``,
#: ``--qos-profile-overrides-path`` were each checked in Humble's own
#: ``record.py`` and in Jazzy's ``--help``).
#:
#: ``--node-name`` is here for a weaker reason and deliberately: Humble release
#: tags 0.15.13, 0.15.14 and 0.15.16 do **not** declare it, while the ``humble``
#: branch tip appears to. Which of those the Orin's apt has is unknown tonight,
#: the flag is cosmetic, and an unknown option is an exit-2 with zero bytes
#: recorded — so it is omitted where it is uncertain and kept where it was
#: measured present. Unknown = absent.
_DISTRO_ONLY_FLAGS: Mapping[str, frozenset[RosDistro]] = {
    "--topics": frozenset({RosDistro.JAZZY}),
    "--disable-keyboard-controls": frozenset({RosDistro.JAZZY}),
    "--node-name": frozenset({RosDistro.JAZZY}),
}


@dataclass(frozen=True, slots=True)
class Rosbag2Plan:
    """Everything needed to start the primary recording, and nothing else."""

    output_dir: Path
    topics: tuple[RecordedTopic, ...]
    profile: WriterProfile = WriterProfile.CRASH_SAFE
    #: Bytes the recorder may hold before writing. Directly proportional to what
    #: a crash costs, so it is small and explicit rather than the default
    #: (104857600, double-buffered).
    max_cache_bytes: int = 8 * 1024 * 1024
    #: Split every N bytes; 0 disables splitting, and 0 is the default here.
    #:
    #: This used to be 4 GiB. At the recommended profile's measured 84.60 MiB/s
    #: (``BANDWIDTH_BUDGET.md`` §1) a 4 GiB threshold splits every **48
    #: seconds** — 37 files across the 30-minute core block — and the take
    #: script's own abort rule is "more than one ``.mcap``, or ``write_split``
    #: count > 0 ⇒ **STOP**" (``session/TAKE_SCRIPT.md``,
    #: ``session/TONIGHT_CHECKLIST.md``:876). The recorder's default argv must
    #: not trip the run-sheet that governs the session; both now say 0.
    max_bag_bytes: int = 0
    #: Split every N seconds as well. 0 = never, same argument as above.
    max_bag_duration_s: int = 0
    storage_config_path: Path | None = None
    qos_overrides_path: Path | None = None
    #: Only reaches the argv where ``--node-name`` is known to exist — see
    #: ``_DISTRO_ONLY_FLAGS``. On Humble the recorder keeps its own default name
    #: and nothing downstream depends on ours: ``/events/*`` are namespace
    #: relative, not node-name relative.
    node_name: str = "parcel_rosbag2_recorder"
    #: The ROS 2 on the machine that will type this argv. Default Humble: the
    #: Orin's asserted distro, and the argv that also runs on Jazzy.
    distro: RosDistro = RosDistro.HUMBLE

    def __post_init__(self) -> None:
        if not self.topics:
            raise Rosbag2RefusedError("a recording with no topics records nothing")
        if self.max_cache_bytes < 0:
            raise Rosbag2RefusedError("max_cache_bytes must be >= 0")
        if self.max_bag_bytes < 0 or self.max_bag_duration_s < 0:
            raise Rosbag2RefusedError("split thresholds must be >= 0")
        if not isinstance(self.distro, RosDistro):
            raise Rosbag2RefusedError(
                f"distro must be a RosDistro, got {self.distro!r}; guessing the "
                f"recorder's CLI is how an argv reaches the Orin with a flag that "
                f"distro's argparse rejects"
            )
        seen: set[str] = set()
        for item in self.topics:
            if item.topic in seen:
                raise Rosbag2RefusedError(f"duplicate topic in plan: {item.topic}")
            seen.add(item.topic)

    @property
    def topic_names(self) -> tuple[str, ...]:
        return tuple(item.topic for item in self.topics)

    @property
    def mapped_channels(self) -> tuple[str, ...]:
        return tuple(item.channel_id for item in self.topics if item.channel_id)

    def supports(self, flag: str) -> bool:
        """Does this plan's distro accept ``flag``?"""

        distros = _DISTRO_ONLY_FLAGS.get(flag)
        return distros is None or self.distro in distros


def record_command(plan: Rosbag2Plan) -> tuple[str, ...]:
    """The exact ``ros2 bag record`` argv for this plan.

    Explicit topics, never ``-a``: ``-a`` records whatever happens to be on the
    graph, which on a robot with a running vendor stack is both more than the
    disk budget and less than the list — a topic with no publisher at start time
    is simply absent from ``-a``, and its absence looks like a decision nobody
    made.

    Every flag here exists on the plan's distro, checked against the recorder
    verb's own source. Split thresholds are emitted **explicitly even when they
    are 0**: the operator's sheet types ``--max-bag-size 0``, and a value that
    is only correct because it matches a default is a value nobody verified.
    """

    argv: list[str] = [
        "ros2",
        "bag",
        "record",
        "--storage",
        STORAGE_ID,
        "--output",
        str(plan.output_dir),
        "--max-cache-size",
        str(plan.max_cache_bytes),
    ]
    if plan.supports("--node-name"):
        argv += ["--node-name", plan.node_name]
    if plan.supports("--disable-keyboard-controls"):
        # The recorder reads stdin for its pause/resume keys. On a run-sheet the
        # operator is typing in other terminals, and under nohup/ssh there is no
        # tty at all; either way the keyboard handler is a hazard, not a feature.
        # Humble's recorder has no keyboard handler and no flag to disable it —
        # passing it there is an argparse error and a session that never starts.
        argv.append("--disable-keyboard-controls")
    argv += ["--max-bag-size", str(plan.max_bag_bytes)]
    argv += ["--max-bag-duration", str(plan.max_bag_duration_s)]
    if plan.storage_config_path is not None:
        argv += ["--storage-config-file", str(plan.storage_config_path)]
    if plan.qos_overrides_path is not None:
        argv += ["--qos-profile-overrides-path", str(plan.qos_overrides_path)]
    if plan.supports("--topics"):
        argv += ["--topics", *plan.topic_names]
    else:
        # Humble: the topic list is positional and must come last.
        argv += list(plan.topic_names)
    return tuple(argv)


def record_help_command() -> tuple[str, ...]:
    """The command whose output settles every flag above, on the real machine."""

    return ("ros2", "bag", "record", "--help")


_HELP_FLAG = re.compile(r"(?<![\w-])(--[a-z0-9][a-z0-9-]*)")


def validate_argv_against_help(argv: Sequence[str], help_text: str) -> tuple[str, ...]:
    """Refuse an argv carrying a flag the installed recorder does not have.

    Four seconds of ``ros2 bag record --help > help.txt`` on the Orin, fed back
    in here, is the difference between finding a bad flag now and finding it at
    08:00 with the dog powered on. Returns the flags it checked; raises rather
    than reporting when one is unsupported, and raises when the text does not
    look like the recorder's help at all — an unrecognised help text must never
    read as "nothing wrong".
    """

    supported = set(_HELP_FLAG.findall(help_text))
    if not {"--output", "--storage", "--max-cache-size"} <= supported:
        raise Rosbag2RefusedError(
            "this does not look like `ros2 bag record --help` output (no --output / "
            "--storage / --max-cache-size in it), so it cannot be used to clear an "
            "argv; capture it with: " + " ".join(record_help_command())
        )
    used = tuple(token for token in argv if token.startswith("--"))
    unsupported = [token for token in used if token not in supported]
    if unsupported:
        raise Rosbag2RefusedError(
            f"the installed `ros2 bag record` has no {unsupported}; argparse exits 2 on "
            f"an unrecognised option and the session records ZERO bytes. Remedy: build "
            f"the plan with the distro that machine actually runs "
            f"({[item.value for item in RosDistro]}), or drop the flag"
        )
    return used


#: The ONLY values ``rosbag2_storage_mcap`` accepts for ``compression``.
#:
#: MEASURED, not transcribed: these are the literals in the name→enum table
#: inside ``librosbag2_storage_mcap.so`` (ROS 2 Jazzy, ``rosbag2_storage_mcap``
#: 0.26.11, ``libmcap`` 1.3.1), and each was confirmed by opening a real MCAP
#: writer with it. **The empty string is not among them.** ``compression: ""``
#: makes ``YAML::convert<mcap::Compression>::decode`` fail, the plugin refuses to
#: open, and ``ros2 bag record`` exits 1 having recorded zero bytes. The
#: spellings are case-sensitive: ``"none"`` is rejected, ``"None"`` is accepted.
MCAP_COMPRESSION_VALUES: tuple[str, ...] = ("None", "Lz4", "Zstd")

#: Likewise for ``compressionLevel``. Measured the same way; ``""`` is rejected
#: here too, independently of ``compression`` — a config that fixes only one of
#: the two keys still records nothing.
MCAP_COMPRESSION_LEVELS: tuple[str, ...] = ("Fastest", "Fast", "Default", "Slow", "Slowest")

#: Enum-valued writer-option keys, and their allowed value sets. Anything not in
#: this table is a plain bool/int and is emitted as JSON.
_ENUM_OPTION_VALUES: Mapping[str, tuple[str, ...]] = {
    "compression": MCAP_COMPRESSION_VALUES,
    "compressionLevel": MCAP_COMPRESSION_LEVELS,
}

#: MCAP writer options. The key names are the ones ``rosbag2_storage_mcap``
#: reads (they appear verbatim in the plugin's own string table, and a config
#: built from them was accepted by the real plugin). Values are this card's
#: decision.
#:
#: ``compression`` is the key that matters most, because an UNKNOWN key is
#: silently ignored: if ``noChunking`` were misspelt the writer would fall back
#: to its default. So the no-dog checklist verifies the setting **from the file
#: that was written** (``session/TONIGHT_CHECKLIST.md`` N4e) rather than from the
#: fact that the command did not error. That checklist chooses the opposite
#: values (``Zstd``/``Fast``, chunked); the disagreement is real, is recorded in
#: ``PSG_STATUS.md``, and tonight's measurement settles it. Both spellings are
#: valid input — that was measured — so whichever wins, the recorder starts.
_WRITER_OPTIONS: Mapping[WriterProfile, dict[str, Any]] = {
    WriterProfile.CRASH_SAFE: {
        "noChunking": True,
        "noMessageIndex": True,
        "noSummary": False,
        "noChunkCRC": False,
        "chunkSize": 0,
        # "None", never "". See MCAP_COMPRESSION_VALUES: the empty string is a
        # refusal by the plugin and a session that records nothing.
        "compression": "None",
        "compressionLevel": "Default",
        "forceCompression": False,
    },
    WriterProfile.INDEXED: {
        "noChunking": False,
        "noMessageIndex": False,
        "noSummary": False,
        "noChunkCRC": False,
        "chunkSize": 4 * 1024 * 1024,
        "compression": "None",
        "compressionLevel": "Default",
        "forceCompression": False,
    },
}


def validate_writer_options(options: Mapping[str, Any]) -> None:
    """Refuse any writer option the storage plugin would reject.

    Fail closed at emit time, on our machine, in Python — rather than at
    ``ros2 bag record`` start time, on the Orin, in a C++ YAML exception, with
    the dog standing and the battery running.
    """

    for key, allowed in _ENUM_OPTION_VALUES.items():
        if key not in options:
            continue
        value = options[key]
        if value in allowed:
            continue
        raise Rosbag2RefusedError(
            f"storage config key {key}={value!r} is not one of {list(allowed)}; "
            f"rosbag2_storage_mcap fails its YAML conversion on anything else and "
            f"`ros2 bag record` then exits 1 having recorded ZERO bytes"
            + (
                " — an empty string is the specific value that defect shipped with"
                if value == ""
                else ""
            )
        )


def storage_config_yaml(profile: WriterProfile = WriterProfile.CRASH_SAFE) -> str:
    """The ``--storage-config-file`` contents for a profile.

    Emitted as JSON-compatible YAML on purpose: JSON is a subset of YAML 1.2, so
    this file is valid input to the C++ YAML parser rosbag2 uses **and** is
    machine-readable back with :mod:`json` alone, on a box with no PyYAML in the
    capture environment. A hand-rolled YAML emitter would be a third thing that
    can be subtly wrong the morning of a session.

    Every enum-valued key is validated before it is written. There is no path
    from this function to a file the storage plugin refuses to open.
    """

    if not isinstance(profile, WriterProfile):
        raise Rosbag2RefusedError(f"profile must be a WriterProfile, got {profile!r}")
    options = _WRITER_OPTIONS[profile]
    validate_writer_options(options)
    lines = [
        "# parcel-capture rosbag2 MCAP writer options — card PS-G, corrected by PS-M.",
        f"# profile: {profile.value}",
        "# Key names and the accepted `compression`/`compressionLevel` spellings were",
        "# MEASURED against rosbag2_storage_mcap 0.26.11 + libmcap 1.3.1 (ROS 2 Jazzy):",
        "# a writer opened with this file wrote a real bag. The Orin runs Humble and its",
        "# plugin build is UNVERIFIED. If `ros2 bag record` rejects this file, drop",
        "# --storage-config-file and re-run: the plugin default measured as chunked and",
        "# UNCOMPRESSED, which read_rosbag2_mcap() counts. You lose the crash-safety",
        "# tuning, not the session. Settle it with a synthetic recording BEFORE the session.",
        "# NEVER write compression: \"\" — the plugin refuses and records zero bytes.",
    ]
    lines.extend(f"{key}: {json.dumps(value)}" for key, value in options.items())
    return "\n".join(lines) + "\n"


def writer_options(profile: WriterProfile = WriterProfile.CRASH_SAFE) -> dict[str, Any]:
    return dict(_WRITER_OPTIONS[profile])


def plan_for_session(
    output_dir: Path | str,
    *,
    profile: WriterProfile = WriterProfile.CRASH_SAFE,
    include_driver_nodes: bool = True,
    include_events: bool = True,
    exclude: Sequence[str] = (),
    storage_config_path: Path | str | None = None,
    qos_overrides_path: Path | str | None = None,
    distro: RosDistro = RosDistro.HUMBLE,
) -> Rosbag2Plan:
    """The plan the run-sheet uses. One call, every default already argued."""

    return Rosbag2Plan(
        output_dir=Path(output_dir),
        topics=topics_for(
            include_driver_nodes=include_driver_nodes,
            include_events=include_events,
            exclude=exclude,
        ),
        profile=profile,
        storage_config_path=None if storage_config_path is None else Path(storage_config_path),
        qos_overrides_path=None if qos_overrides_path is None else Path(qos_overrides_path),
        distro=distro,
    )


def preflight_topic_check_command() -> tuple[str, ...]:
    """The one command that settles which of these topics actually exist.

    Every ``DRIVER_NODE`` row and both event rows are documentation. This is what
    replaces them with an observation, and it costs four seconds.
    """

    return ("ros2", "topic", "list", "-t")


def missing_ros_tooling() -> tuple[str, ...]:
    """Which executables this path needs and does not have here."""

    return tuple(name for name in ("ros2",) if shutil.which(name) is None)


def readiness_report(plan: Rosbag2Plan) -> str:
    """Actionable text for ``--check``. Never a traceback, on any host."""

    missing = missing_ros_tooling()
    lines = [
        (
            f"rosbag2 primary recorder plan — {len(plan.topics)} topic(s), "
            f"profile {plan.profile.value}, distro {plan.distro.value}"
        ),
        f"output: {plan.output_dir}",
        "",
        "command:",
        "  " + " ".join(record_command(plan)),
        "",
        (
            f"argv is built for ROS 2 {plan.distro.value}. Humble's recorder has NO "
            f"--topics, NO --disable-keyboard-controls and (in every release tag "
            f"checked) NO --node-name; its topic list is positional. Jazzy has all "
            f"three. An unknown option is exit 2 and zero bytes, so settle it on the "
            f"machine that will type it:"
        ),
        "  " + " ".join(record_help_command()) + " > /tmp/record_help.txt",
        "  python -m scripts.parcel_capture.rosbag2 --verify-help /tmp/record_help.txt",
        "",
    ]
    if plan.storage_config_path is not None and not Path(plan.storage_config_path).exists():
        lines += [
            (
                f"WARNING: --storage-config-file {plan.storage_config_path} does not "
                f"exist on this host."
            ),
            "  On Humble that argument is argparse's FileType('r'): a missing file is an",
            "  exit-2 before any recording starts. Emit it with --emit-storage-config.",
            "",
        ]
    if missing:
        lines += [
            f"UNAVAILABLE here: {', '.join(missing)} is not on PATH.",
            "  remedy: run this on the Orin with /opt/ros/humble/setup.bash sourced, and",
            "          install ros-humble-rosbag2-storage-mcap. Never into .parcel/.",
            "",
        ]
    by_source: dict[str, list[RecordedTopic]] = {}
    for item in plan.topics:
        by_source.setdefault(item.source.value, []).append(item)
    for source, items in by_source.items():
        lines.append(f"{source} ({len(items)}):")
        for item in items:
            mapped = item.channel_id or "-"
            lines.append(
                f"  {item.topic:<44} {item.message_type:<40} {item.confidence.value:<11} {mapped}"
            )
        prerequisites = sorted({item.prerequisite for item in items if item.prerequisite})
        for prerequisite in prerequisites:
            lines.append(f"    requires: {prerequisite}")
        lines.append("")
    lines.append("verify the list against the graph before recording:")
    lines.append("  " + " ".join(preflight_topic_check_command()))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Reading a rosbag2 MCAP with the standard library alone
# --------------------------------------------------------------------------


class ScanTermination(str, Enum):
    """How the byte stream ended. Three disjoint outcomes, none permissive."""

    CLEAN = "clean"
    TRUNCATED = "truncated"
    CORRUPT = "corrupt"


class CountBasis(str, Enum):
    """Where a per-topic message count came from. Never left implicit.

    A count read out of a ``Statistics`` record is the writer's claim about
    itself; a count from walking the messages is what survived. They can differ,
    and which one a sidecar is quoting decides what the sidecar means.
    """

    #: Messages actually walked in the data section.
    WALKED = "walked_messages"
    #: The summary ``Statistics`` record's ``channel_message_counts``.
    STATISTICS = "mcap_statistics"
    #: Chunks are compressed and no decompressor is available here.
    UNAVAILABLE_COMPRESSED = "unavailable_compressed"


@dataclass(frozen=True, slots=True)
class Rosbag2Channel:
    """One channel record out of the bag. ROS names, CDR encoding."""

    mcap_id: int
    topic: str
    message_encoding: str
    schema_name: str
    schema_encoding: str

    @property
    def channel_id(self) -> str | None:
        """The PS-A/PS-H channel this topic maps to, or ``None`` if unmapped."""

        return CHANNEL_BY_TOPIC.get(self.topic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "message_encoding": self.message_encoding,
            "schema_name": self.schema_name,
            "schema_encoding": self.schema_encoding,
            "channel_id": self.channel_id,
        }


@dataclass(frozen=True)
class Rosbag2Scan:
    """What one rosbag2 MCAP file's bytes say, and nothing they do not."""

    path: Path
    file_bytes: int
    profile: str
    library: str
    channels: tuple[Rosbag2Channel, ...]
    counts: Mapping[str, int]
    count_basis: CountBasis
    termination: ScanTermination
    detail: str
    last_complete_offset: int
    trailing_bytes: int
    saw_data_end: bool
    saw_footer: bool
    saw_terminal_magic: bool
    first_log_time_ns: int | None
    last_log_time_ns: int | None
    message_bytes: Mapping[str, int]
    chunk_compressions: tuple[str, ...]
    findings: tuple[str, ...] = ()

    @property
    def is_clean(self) -> bool:
        return self.termination is ScanTermination.CLEAN

    @property
    def message_count(self) -> int:
        return sum(self.counts.values())

    @property
    def is_rosbag2(self) -> bool:
        """True only when the header says ``ros2``. A bag that does not is a
        finding: it may be a Parcel-native capture, which is a different file
        with a different reader and must never be described as this one."""

        return self.profile == ROS2_PROFILE

    @property
    def span_s(self) -> float:
        if self.first_log_time_ns is None or self.last_log_time_ns is None:
            return 0.0
        return max(0.0, (self.last_log_time_ns - self.first_log_time_ns) / 1e9)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.path.name,
            "bytes": self.file_bytes,
            "profile": self.profile,
            "library": self.library,
            "is_rosbag2": self.is_rosbag2,
            "termination": self.termination.value,
            "detail": self.detail,
            "count_basis": self.count_basis.value,
            "counts": dict(sorted(self.counts.items())),
            "message_bytes": dict(sorted(self.message_bytes.items())),
            "channels": [item.to_dict() for item in self.channels],
            "last_complete_offset": self.last_complete_offset,
            "trailing_bytes": self.trailing_bytes,
            "saw_data_end": self.saw_data_end,
            "saw_footer": self.saw_footer,
            "saw_terminal_magic": self.saw_terminal_magic,
            "first_log_time_ns": self.first_log_time_ns,
            "last_log_time_ns": self.last_log_time_ns,
            "span_s": round(self.span_s, 6),
            "chunk_compressions": list(self.chunk_compressions),
            "findings": list(self.findings),
        }


class _Cursor:
    """Bounded reader over one record's content. A short field is an error."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def take(self, count: int, name: str) -> bytes:
        end = self._pos + count
        if end > len(self._data):
            raise Rosbag2ReadError(
                f"field {name} wants {count} bytes, {len(self._data) - self._pos} remain"
            )
        chunk = self._data[self._pos : end]
        self._pos = end
        return chunk

    def u8(self, name: str) -> int:
        return self.take(1, name)[0]

    def u16(self, name: str) -> int:
        return _U16.unpack(self.take(_U16.size, name))[0]

    def u32(self, name: str) -> int:
        return _U32.unpack(self.take(_U32.size, name))[0]

    def u64(self, name: str) -> int:
        return _U64.unpack(self.take(_U64.size, name))[0]

    def string(self, name: str) -> str:
        length = self.u32(f"len({name})")
        try:
            return self.take(length, name).decode("utf-8")
        except UnicodeDecodeError as error:
            raise Rosbag2ReadError(f"field {name} is not UTF-8: {error}") from error

    def blob(self, name: str) -> bytes:
        """The spec's ``Bytes`` type: a **uint32** length followed by that many
        bytes. Used by ``Schema.data``, ``Channel.metadata`` and
        ``Statistics.channel_message_counts``. NOT by ``Chunk.records`` — see
        :meth:`blob64`."""

        return self.take(self.u32(f"len({name})"), name)

    def blob64(self, name: str) -> bytes:
        """``Chunk.records``: a **uint64** length followed by that many bytes.

        This is the one place the MCAP spec departs from its own ``Bytes`` type,
        and reading it as a uint32 is not a benign off-by-four: the cursor then
        starts four bytes early on the chunk's first inner record, so the opcode
        reads as ``0x00`` and its length as garbage, and every uncompressed
        chunked bag — which is what ``ros2 bag record`` writes by default —
        classifies as CORRUPT with zero messages. See ``MCAP_INTEGER_WIDTHS``.
        """

        return self.take(self.u64(f"len({name})"), name)

    def rest(self) -> bytes:
        chunk = self._data[self._pos :]
        self._pos = len(self._data)
        return chunk

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos


@dataclass
class _ScanState:
    schemas: dict[int, tuple[str, str]] = field(default_factory=dict)
    channels: dict[int, Rosbag2Channel] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    message_bytes: dict[str, int] = field(default_factory=dict)
    statistics: dict[int, int] = field(default_factory=dict)
    first_log_time_ns: int | None = None
    last_log_time_ns: int | None = None
    compressions: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)


def read_rosbag2_mcap(path: Path | str) -> Rosbag2Scan:
    """Read a rosbag2 MCAP with the standard library. Never raises on damage.

    Deliberately NOT ``record.py``'s ``read_mcap``: that reader requires every
    channel to declare Parcel's own ``message_encoding`` and refuses anything
    else (``record.py:794``), which is correct for the Parcel-native format and
    is exactly why it cannot see a rosbag2 file. Two formats, two readers, and
    neither one weakened to accommodate the other.

    Compressed chunks are not decompressed — ``zstandard`` and ``lz4`` are not
    installed and the board forbids installing them. Their message counts fall
    back to the ``Statistics`` record, and :attr:`Rosbag2Scan.count_basis` says
    which answer is being quoted.
    """

    path = Path(path)
    try:
        file_bytes = path.stat().st_size
    except OSError as error:
        raise Rosbag2ReadError(f"cannot stat {path}: {error}") from error

    state = _ScanState()
    profile = ""
    library = ""
    saw_data_end = False
    saw_footer = False
    saw_terminal_magic = False
    termination = ScanTermination.CLEAN
    detail = ""
    offset = 0
    walked_any = False

    with path.open("rb") as handle:
        magic = handle.read(len(MCAP_MAGIC))
        if magic != MCAP_MAGIC:
            if len(magic) < len(MCAP_MAGIC) and MCAP_MAGIC.startswith(magic):
                return _empty_scan(
                    path,
                    file_bytes,
                    f"file ends inside the leading MCAP magic after {len(magic)} of "
                    f"{len(MCAP_MAGIC)} bytes",
                )
            raise NotAnMcapFileError(
                f"{path} does not begin with the MCAP magic (got {magic!r})"
            )
        offset = len(MCAP_MAGIC)

        while True:
            head = handle.read(_RECORD_HEADER.size)
            if not head:
                break
            if len(head) < _RECORD_HEADER.size:
                termination = ScanTermination.TRUNCATED
                detail = (
                    f"record header truncated at offset {offset}: {len(head)} of "
                    f"{_RECORD_HEADER.size} bytes"
                )
                break
            opcode, length = _RECORD_HEADER.unpack(head)
            if length > MAX_RECORD_BYTES:
                termination = ScanTermination.CORRUPT
                detail = (
                    f"record opcode 0x{opcode:02x} at offset {offset} declares {length} "
                    f"bytes, above the {MAX_RECORD_BYTES}-byte ceiling"
                )
                break
            content = handle.read(length)
            if len(content) < length:
                termination = ScanTermination.TRUNCATED
                detail = (
                    f"record opcode 0x{opcode:02x} at offset {offset} declares {length} "
                    f"bytes, {len(content)} present"
                )
                break
            try:
                if opcode == OP_HEADER:
                    cursor = _Cursor(content)
                    profile = cursor.string("header.profile")
                    library = cursor.string("header.library")
                elif opcode == OP_SCHEMA:
                    _decode_schema(content, state)
                elif opcode == OP_CHANNEL:
                    _decode_channel(content, state)
                elif opcode == OP_MESSAGE:
                    _decode_message(content, state)
                    walked_any = True
                elif opcode == OP_CHUNK:
                    walked_any = _decode_chunk(content, state) or walked_any
                elif opcode == OP_STATISTICS:
                    _decode_statistics(content, state)
                elif opcode == OP_DATA_END:
                    saw_data_end = True
                elif opcode == OP_FOOTER:
                    saw_footer = True
                    offset += _RECORD_HEADER.size + length
                    trailer = handle.read(len(MCAP_MAGIC))
                    if trailer == MCAP_MAGIC:
                        saw_terminal_magic = True
                        offset += len(MCAP_MAGIC)
                        if handle.read(1):
                            termination = ScanTermination.CORRUPT
                            detail = "bytes present after the terminal MCAP magic"
                    else:
                        termination = ScanTermination.TRUNCATED
                        detail = (
                            f"footer present but terminal magic is {len(trailer)} of "
                            f"{len(MCAP_MAGIC)} bytes"
                        )
                    break
            except Rosbag2ReadError as error:
                termination = ScanTermination.CORRUPT
                detail = f"record opcode 0x{opcode:02x} at offset {offset}: {error}"
                break
            offset += _RECORD_HEADER.size + length

    if termination is ScanTermination.CLEAN and not (saw_data_end and saw_terminal_magic):
        termination = ScanTermination.TRUNCATED
        detail = (
            f"file ends without a complete terminal structure (data_end={saw_data_end}, "
            f"footer={saw_footer}, magic={saw_terminal_magic})"
        )

    counts, basis = _reconcile_counts(state, walked_any)
    channels = tuple(state.channels[key] for key in state.order)
    if profile and profile != ROS2_PROFILE:
        state.findings.append(
            f"header profile is {profile!r}, not {ROS2_PROFILE!r}; this file was not "
            f"written by rosbag2 and nothing here describes a rosbag2 recording"
        )
    return Rosbag2Scan(
        path=path,
        file_bytes=file_bytes,
        profile=profile,
        library=library,
        channels=channels,
        counts=counts,
        count_basis=basis,
        termination=termination,
        detail=detail,
        last_complete_offset=offset,
        trailing_bytes=max(file_bytes - offset, 0),
        saw_data_end=saw_data_end,
        saw_footer=saw_footer,
        saw_terminal_magic=saw_terminal_magic,
        first_log_time_ns=state.first_log_time_ns,
        last_log_time_ns=state.last_log_time_ns,
        message_bytes=dict(state.message_bytes),
        chunk_compressions=tuple(sorted(set(state.compressions))),
        findings=tuple(state.findings),
    )


def _empty_scan(path: Path, file_bytes: int, detail: str) -> Rosbag2Scan:
    return Rosbag2Scan(
        path=path,
        file_bytes=file_bytes,
        profile="",
        library="",
        channels=(),
        counts={},
        count_basis=CountBasis.WALKED,
        termination=ScanTermination.TRUNCATED,
        detail=detail,
        last_complete_offset=0,
        trailing_bytes=file_bytes,
        saw_data_end=False,
        saw_footer=False,
        saw_terminal_magic=False,
        first_log_time_ns=None,
        last_log_time_ns=None,
        message_bytes={},
        chunk_compressions=(),
    )


def _decode_schema(content: bytes, state: _ScanState) -> None:
    cursor = _Cursor(content)
    schema_id = cursor.u16("schema.id")
    name = cursor.string("schema.name")
    encoding = cursor.string("schema.encoding")
    cursor.blob("schema.data")
    state.schemas[schema_id] = (name, encoding)


def _decode_channel(content: bytes, state: _ScanState) -> None:
    cursor = _Cursor(content)
    mcap_id = cursor.u16("channel.id")
    schema_id = cursor.u16("channel.schema_id")
    topic = cursor.string("channel.topic")
    encoding = cursor.string("channel.message_encoding")
    if mcap_id in state.channels:
        return
    schema_name, schema_encoding = state.schemas.get(schema_id, ("", ""))
    if encoding != ROS2_MESSAGE_ENCODING:
        state.findings.append(
            f"channel {topic!r} declares message_encoding {encoding!r}, not "
            f"{ROS2_MESSAGE_ENCODING!r}; a downstream ROS tool will not decode it"
        )
    state.channels[mcap_id] = Rosbag2Channel(
        mcap_id=mcap_id,
        topic=topic,
        message_encoding=encoding,
        schema_name=schema_name,
        schema_encoding=schema_encoding,
    )
    state.order.append(mcap_id)


def _decode_message(content: bytes, state: _ScanState) -> None:
    cursor = _Cursor(content)
    mcap_id = cursor.u16("message.channel_id")
    cursor.u32("message.sequence")
    log_time = cursor.u64("message.log_time")
    cursor.u64("message.publish_time")
    entry = state.channels.get(mcap_id)
    if entry is None:
        raise Rosbag2ReadError(f"message names unregistered MCAP channel id {mcap_id}")
    payload = cursor.rest()
    state.counts[entry.topic] = state.counts.get(entry.topic, 0) + 1
    state.message_bytes[entry.topic] = state.message_bytes.get(entry.topic, 0) + len(payload)
    if state.first_log_time_ns is None or log_time < state.first_log_time_ns:
        state.first_log_time_ns = log_time
    if state.last_log_time_ns is None or log_time > state.last_log_time_ns:
        state.last_log_time_ns = log_time


def _decode_chunk(content: bytes, state: _ScanState) -> bool:
    """Walk an UNCOMPRESSED chunk's records; record a compressed one as opaque.

    Returns True when messages were actually walked. This is why the CRASH_SAFE
    profile turns compression off: on a night with no ``zstandard`` installed, an
    uncompressed chunk is still fully countable by the standard library, and a
    compressed one is a number we would have to take on trust.
    """

    cursor = _Cursor(content)
    cursor.u64("chunk.message_start_time")
    cursor.u64("chunk.message_end_time")
    uncompressed_size = cursor.u64("chunk.uncompressed_size")
    cursor.u32("chunk.uncompressed_crc")
    compression = cursor.string("chunk.compression")
    # uint64, not uint32. The spec's only length prefix that is not a uint32,
    # and the whole reason this reader once called every chunked bag corrupt.
    records = cursor.blob64("chunk.records")
    state.compressions.append(compression or "none")
    if not compression and uncompressed_size != len(records):
        # Free cross-check on the field widths themselves: for an uncompressed
        # chunk the writer's own uncompressed_size must equal the bytes we just
        # framed. A width error makes these two disagree.
        state.findings.append(
            f"chunk declares uncompressed_size {uncompressed_size} but its records "
            f"field frames {len(records)} bytes; the chunk framing was not understood"
        )
    if compression:
        state.findings.append(
            f"chunk uses {compression!r} compression; this reader does not decompress "
            f"(no zstandard/lz4 here), so its messages were not walked"
        )
        return False
    inner = _Cursor(records)
    while inner.remaining:
        if inner.remaining < _RECORD_HEADER.size:
            raise Rosbag2ReadError("chunk ends inside a record header")
        opcode = inner.u8("chunk.record.opcode")
        length = inner.u64("chunk.record.length")
        body = inner.take(length, "chunk.record.body")
        if opcode == OP_SCHEMA:
            _decode_schema(body, state)
        elif opcode == OP_CHANNEL:
            _decode_channel(body, state)
        elif opcode == OP_MESSAGE:
            _decode_message(body, state)
        elif opcode in (OP_MESSAGE_INDEX,):
            continue
        else:
            raise Rosbag2ReadError(f"unexpected opcode 0x{opcode:02x} inside a chunk")
    return True


def _decode_statistics(content: bytes, state: _ScanState) -> None:
    cursor = _Cursor(content)
    cursor.u64("statistics.message_count")
    cursor.u16("statistics.schema_count")
    cursor.u32("statistics.channel_count")
    cursor.u32("statistics.attachment_count")
    cursor.u32("statistics.metadata_count")
    cursor.u32("statistics.chunk_count")
    cursor.u64("statistics.message_start_time")
    cursor.u64("statistics.message_end_time")
    body = _Cursor(cursor.blob("statistics.channel_message_counts"))
    while body.remaining:
        mcap_id = body.u16("statistics.channel_id")
        state.statistics[mcap_id] = body.u64("statistics.count")


def _reconcile_counts(state: _ScanState, walked_any: bool) -> tuple[dict[str, int], CountBasis]:
    """Walked counts win. Statistics fill in only what could not be walked."""

    if walked_any or not state.statistics:
        counts = dict(state.counts)
        for entry in state.channels.values():
            counts.setdefault(entry.topic, 0)
        basis = CountBasis.WALKED
        if state.statistics:
            declared = {
                state.channels[key].topic: value
                for key, value in state.statistics.items()
                if key in state.channels
            }
            disagree = {
                topic: (counts.get(topic, 0), value)
                for topic, value in declared.items()
                if counts.get(topic, 0) != value
            }
            if disagree:
                state.findings.append(
                    f"the writer's Statistics record disagrees with the messages that "
                    f"survive, per topic (walked, declared): {dict(sorted(disagree.items()))}"
                )
        return counts, basis
    counts = {
        state.channels[key].topic: value
        for key, value in state.statistics.items()
        if key in state.channels
    }
    for entry in state.channels.values():
        counts.setdefault(entry.topic, 0)
    return counts, CountBasis.UNAVAILABLE_COMPRESSED


# --------------------------------------------------------------------------
# The bag directory, splits, and ``ros2 bag info``
# --------------------------------------------------------------------------

_RELATIVE_PATH_LINE = re.compile(r"^\s*-\s*(?P<path>[A-Za-z0-9_.\-/]+\.mcap)\s*$")


@dataclass(frozen=True, slots=True)
class Rosbag2Directory:
    """A rosbag2 output directory: ``metadata.yaml`` plus one or more MCAP files.

    ``ros2 bag record`` splits, so "the bag" is a directory and a sidecar that
    digests one file describes part of a session. Every file is listed, in the
    order the recorder wrote them.
    """

    path: Path
    files: tuple[Path, ...]
    metadata_path: Path | None
    findings: tuple[str, ...] = ()


def discover_bag(directory: Path | str) -> Rosbag2Directory:
    """Enumerate a rosbag2 directory, cross-checking the glob against metadata.

    ``metadata.yaml`` is parsed by a strict line scan rather than a YAML library:
    the capture environment has no PyYAML guarantee, and a partial YAML parser
    that guesses is worse than a scan that refuses. When the scan finds file
    names, they must agree with the files on disk — a disagreement is a finding,
    never reconciled in favour of whichever list is longer.
    """

    root = Path(directory)
    if not root.is_dir():
        raise Rosbag2RefusedError(f"{root} is not a directory; rosbag2 output is a directory")
    files = tuple(sorted(root.glob("*.mcap")))
    if not files:
        raise Rosbag2RefusedError(
            f"{root} contains no .mcap file; a rosbag2 directory with no storage file is "
            f"a finding, not an empty recording"
        )
    metadata = root / "metadata.yaml"
    findings: list[str] = []
    if not metadata.exists():
        findings.append(
            "metadata.yaml is absent; the recorder never closed this bag, so its own "
            "account of topics, counts and duration does not exist"
        )
        return Rosbag2Directory(root, files, None, tuple(findings))
    declared = _declared_files(metadata)
    if declared:
        on_disk = {item.name for item in files}
        named = {Path(item).name for item in declared}
        if named != on_disk:
            findings.append(
                f"metadata.yaml names {sorted(named)} but the directory holds "
                f"{sorted(on_disk)}"
            )
    else:
        findings.append(
            "metadata.yaml carries no readable relative_file_paths list; file discovery "
            "fell back to the directory glob and was not cross-checked"
        )
    return Rosbag2Directory(root, files, metadata, tuple(findings))


def _declared_files(metadata_path: Path) -> tuple[str, ...]:
    """Extract ``relative_file_paths`` by strict line scan. Empty when unsure."""

    try:
        text = metadata_path.read_text(encoding="utf-8")
    except OSError:
        return ()
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.strip().startswith("relative_file_paths:"):
            inside = True
            continue
        if inside:
            match = _RELATIVE_PATH_LINE.match(line)
            if match:
                out.append(match.group("path"))
                continue
            if line.strip() and not line.startswith((" ", "-", "\t")):
                break
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Rosbag2Info:
    """``ros2 bag info`` as data. Counts per topic, and where they came from."""

    counts: Mapping[str, int]
    types: Mapping[str, str]
    duration_s: float | None
    message_count: int | None
    storage_id: str | None
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": dict(sorted(self.counts.items())),
            "types": dict(sorted(self.types.items())),
            "duration_s": self.duration_s,
            "message_count": self.message_count,
            "storage_id": self.storage_id,
        }


#: `ros2 bag info` prefixes the FIRST topic line with "Topic information: ",
#: so the topic pattern is searched anywhere in the line rather than anchored.
#: Anchoring it silently drops exactly one channel — and on a 25-topic take the
#: missing one is whichever the recorder happened to see first.
_INFO_TOPIC = re.compile(
    r"Topic:\s*(?P<topic>\S+)\s*\|\s*Type:\s*(?P<type>\S+)\s*\|\s*Count:\s*"
    r"(?P<count>\d+)"
)
_INFO_DURATION = re.compile(r"^\s*Duration:\s*(?P<value>[0-9.]+)s")
_INFO_MESSAGES = re.compile(r"^\s*Messages:\s*(?P<value>\d+)")
_INFO_STORAGE = re.compile(r"^\s*Storage id:\s*(?P<value>\S+)")


def bag_info_command(directory: Path | str) -> tuple[str, ...]:
    return ("ros2", "bag", "info", str(directory))


def parse_bag_info(text: str) -> Rosbag2Info:
    """Parse ``ros2 bag info`` output. Refuses rather than returning a guess.

    A parse that finds no topic lines is a refusal, not an empty result: an empty
    count map would flow into a sidecar as "every channel recorded nothing",
    which is a fabricated finding about the session.
    """

    counts: dict[str, int] = {}
    types: dict[str, str] = {}
    duration: float | None = None
    messages: int | None = None
    storage: str | None = None
    for line in text.splitlines():
        match = _INFO_TOPIC.search(line)
        if match:
            topic = match.group("topic")
            counts[topic] = int(match.group("count"))
            types[topic] = match.group("type")
            continue
        for pattern, setter in (
            (_INFO_DURATION, "duration"),
            (_INFO_MESSAGES, "messages"),
            (_INFO_STORAGE, "storage"),
        ):
            found = pattern.match(line)
            if not found:
                continue
            if setter == "duration":
                duration = float(found.group("value"))
            elif setter == "messages":
                messages = int(found.group("value"))
            else:
                storage = found.group("value")
    if not counts:
        raise Rosbag2RefusedError(
            "ros2 bag info produced no 'Topic: ... | Count: ...' lines; the output was not "
            "understood and an empty count map would read as a session that recorded "
            "nothing"
        )
    return Rosbag2Info(counts, types, duration, messages, storage, text)


def run_bag_info(directory: Path | str, *, timeout_s: float = 60.0) -> Rosbag2Info:
    """Shell out to ``ros2 bag info``, or refuse with the remedy.

    Never a traceback on a host without ROS, which is every host we have tonight.
    """

    if shutil.which("ros2") is None:
        raise Rosbag2RefusedError(
            "ros2 is not on PATH, so per-topic counts cannot be read from the recorder's "
            "own tool here. Remedy: run this on the Orin with /opt/ros/humble/setup.bash "
            "sourced. Fallback: read_rosbag2_mcap() counts the same messages with the "
            "standard library and the sidecar records which basis it used."
        )
    argv = bag_info_command(directory)
    try:
        finished = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Rosbag2RefusedError(f"{' '.join(argv)} could not be run: {error}") from error
    if finished.returncode != 0:
        raise Rosbag2RefusedError(
            f"{' '.join(argv)} exited {finished.returncode}: "
            f"{(finished.stderr or finished.stdout).strip()[:400]}"
        )
    return parse_bag_info(finished.stdout)


def sha256_file(path: Path | str, *, block_bytes: int = 1024 * 1024) -> tuple[str, int]:
    """Streaming digest and size — the file may be hundreds of gibibytes."""

    digest = hashlib.sha256()
    total = 0
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(block_bytes)
            if not block:
                break
            digest.update(block)
            total += len(block)
    return digest.hexdigest(), total


# --------------------------------------------------------------------------
# A rosbag2-shaped fixture writer — TESTS AND DRY RUNS ONLY
# --------------------------------------------------------------------------

FIXTURE_LIBRARY = "parcel-capture rosbag2 FIXTURE writer (not a recorder)"


def write_fixture_bag(
    path: Path | str,
    messages: Sequence[tuple[str, int, bytes]],
    *,
    types: Mapping[str, str] | None = None,
    chunked: bool = False,
    compression: str = "",
    close: bool = True,
    profile: str = ROS2_PROFILE,
    with_statistics: bool = False,
) -> Path:
    """Write rosbag2-shaped MCAP bytes. **Not a recorder** — a fixture.

    ``ros2 bag record`` writes the session. This exists so the sidecar path, the
    scanner and the truncation classifier can be exercised tonight on a machine
    with no ROS, and so a seeded-failure table can mutate a byte and watch the
    digest binding fail. Its ``library`` string says what it is, inside the file,
    so a fixture can never be mistaken for a recording.

    ``messages`` is ``(topic, log_time_ns, payload)``. ``close=False`` stops
    before ``DataEnd``, producing the bag a killed recorder leaves.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    type_map = dict(types or {})
    with target.open("wb") as handle:
        handle.write(MCAP_MAGIC)
        handle.write(_record(OP_HEADER, _string(profile) + _string(FIXTURE_LIBRARY)))
        ids: dict[str, int] = {}
        body = bytearray()
        declarations = bytearray()
        for topic, _stamp, _payload in messages:
            if topic in ids:
                continue
            index = len(ids) + 1
            ids[topic] = index
            schema = _record(
                OP_SCHEMA,
                _U16.pack(index)
                + _string(type_map.get(topic, "std_msgs/msg/String"))
                + _string(ROS2_SCHEMA_ENCODING)
                + _blob(b"# fixture schema"),
            )
            chan = _record(
                OP_CHANNEL,
                _U16.pack(index)
                + _U16.pack(index)
                + _string(topic)
                + _string(ROS2_MESSAGE_ENCODING)
                + _blob(b""),
            )
            body += schema + chan
            declarations += schema + chan
        sequences: dict[str, int] = {}
        for topic, stamp, payload in messages:
            sequences[topic] = sequences.get(topic, 0) + 1
            body += _record(
                OP_MESSAGE,
                _U16.pack(ids[topic])
                + _U32.pack(sequences[topic])
                + _U64.pack(stamp)
                + _U64.pack(stamp)
                + payload,
            )
        if chunked:
            stamps = [stamp for _topic, stamp, _payload in messages] or [0]
            chunk = (
                _U64.pack(min(stamps))
                + _U64.pack(max(stamps))
                + _U64.pack(len(body))
                + _U32.pack(0)
                + _string(compression)
                # uint64, per the spec and per the bytes libmcap actually writes.
                # A uint32 here would make this fixture agree with a broken
                # reader, which is how the width defect survived a green suite.
                + _blob64(bytes(body))
            )
            handle.write(_record(OP_CHUNK, chunk))
        else:
            handle.write(bytes(body))
        if with_statistics:
            # The summary section repeats every schema and channel record, which
            # is what makes a compressed bag's channel table readable without a
            # decompressor. Duplicates are ignored by the reader.
            handle.write(bytes(declarations))
            tally: dict[int, int] = {}
            for topic, _stamp, _payload in messages:
                tally[ids[topic]] = tally.get(ids[topic], 0) + 1
            counts = b"".join(_U16.pack(key) + _U64.pack(value) for key, value in tally.items())
            stamps = [stamp for _topic, stamp, _payload in messages] or [0]
            handle.write(
                _record(
                    OP_STATISTICS,
                    _U64.pack(len(messages))
                    + _U16.pack(len(ids))
                    + _U32.pack(len(ids))
                    + _U32.pack(0)
                    + _U32.pack(0)
                    + _U32.pack(1 if chunked else 0)
                    + _U64.pack(min(stamps))
                    + _U64.pack(max(stamps))
                    + _blob(counts),
                )
            )
        if close:
            handle.write(_record(OP_DATA_END, _U32.pack(0)))
            handle.write(_record(OP_FOOTER, _U64.pack(0) + _U64.pack(0) + _U32.pack(0)))
            handle.write(MCAP_MAGIC)
    return target


def _record(opcode: int, content: bytes) -> bytes:
    return _RECORD_HEADER.pack(opcode, len(content)) + content


def _string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return _U32.pack(len(raw)) + raw


def _blob(value: bytes) -> bytes:
    """The spec's ``Bytes``: uint32 length prefix."""

    return _U32.pack(len(value)) + value


def _blob64(value: bytes) -> bytes:
    """``Chunk.records``: uint64 length prefix. The spec's one exception."""

    return _U64.pack(len(value)) + value


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

_EXIT_OK = 0
_EXIT_REFUSED = 2
_EXIT_DEPENDENCIES = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.parcel_capture.rosbag2",
        description=(
            "rosbag2 primary-recorder plan and reader. Emits the exact `ros2 bag record "
            "-s mcap` command line and storage config, and reads a rosbag2 MCAP with the "
            "standard library. It never records and never publishes."
        ),
    )
    parser.add_argument("--output", default="/data/parcel/session", help="bag output directory")
    parser.add_argument(
        "--profile",
        choices=[item.value for item in WriterProfile],
        default=WriterProfile.CRASH_SAFE.value,
    )
    parser.add_argument(
        "--distro",
        choices=[item.value for item in RosDistro],
        default=RosDistro.HUMBLE.value,
        help="ROS 2 distro of the machine that will run the recorder (default humble)",
    )
    parser.add_argument("--no-driver-nodes", action="store_true")
    parser.add_argument("--no-events", action="store_true")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--print-command", action="store_true", help="the argv, one line")
    parser.add_argument("--emit-storage-config", metavar="PATH", default=None)
    parser.add_argument(
        "--verify-help",
        metavar="PATH",
        default=None,
        help="a saved `ros2 bag record --help`; refuses if the argv uses a flag it lacks",
    )
    parser.add_argument("--check", action="store_true", help="readiness report")
    parser.add_argument("--scan", metavar="MCAP", default=None, help="read one MCAP file")
    parser.add_argument("--info", metavar="BAGDIR", default=None, help="ros2 bag info as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = plan_for_session(
            args.output,
            profile=WriterProfile(args.profile),
            include_driver_nodes=not args.no_driver_nodes,
            include_events=not args.no_events,
            exclude=tuple(args.exclude),
            distro=RosDistro(args.distro),
        )
    except Rosbag2RefusedError as error:
        print(f"refused: {error}", file=sys.stderr)
        return _EXIT_REFUSED

    if args.verify_help:
        try:
            text = Path(args.verify_help).read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            print(f"unavailable: cannot read {args.verify_help}: {error}", file=sys.stderr)
            return _EXIT_DEPENDENCIES
        try:
            checked = validate_argv_against_help(record_command(plan), text)
        except Rosbag2RefusedError as error:
            print(f"refused: {error}", file=sys.stderr)
            return _EXIT_REFUSED
        print(f"argv cleared against {args.verify_help}: {len(checked)} flag(s) all present")
        return _EXIT_OK
    if args.emit_storage_config:
        target = Path(args.emit_storage_config)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(storage_config_yaml(plan.profile), encoding="utf-8")
        print(f"wrote {target}")
        return _EXIT_OK
    if args.print_command:
        print(" ".join(record_command(plan)))
        return _EXIT_OK
    if args.scan:
        try:
            scan = read_rosbag2_mcap(args.scan)
        except Rosbag2Error as error:
            print(f"refused: {error}", file=sys.stderr)
            return _EXIT_REFUSED
        print(json.dumps(scan.to_dict(), indent=2, sort_keys=True))
        return _EXIT_OK if scan.is_clean else _EXIT_REFUSED
    if args.info:
        try:
            info = run_bag_info(args.info)
        except Rosbag2RefusedError as error:
            print(f"unavailable: {error}", file=sys.stderr)
            return _EXIT_DEPENDENCIES
        print(json.dumps(info.to_dict(), indent=2, sort_keys=True))
        return _EXIT_OK

    print(readiness_report(plan))
    return _EXIT_DEPENDENCIES if missing_ros_tooling() else _EXIT_OK


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
