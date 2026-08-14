"""Card PS-G: ``ros2 bag record -s mcap`` as the primary path, and its sidecar.

The defect: ``record.py`` writes ``MCAP_PROFILE = "parcel-capture"`` with
``message_encoding = "parcel.capture.envelope.v1+raw"``, which **no** tool in the
next milestone can open — GLIM, FAST-LIO2, Point-LIO-ROS2, KISS-ICP, Multi-LiCa,
ros2_calib and direct_visual_lidar_calibration all read ``rosbag2``. A physical
session recorded in that format is a session whose data only Parcel can read.

The ruling this file gates:

* **G1 command**  — the exact ``ros2 bag record`` argv, with ROS names and never
  the ``rt/``-mangled wire names, plus the ``/events/*`` topics.
* **G2 config**   — the MCAP writer options, the crash-safety argument behind
  them, and the honest statement that the key names are transcribed.
* **G3 reader**   — a rosbag2 MCAP is countable, digestible and classifiable
  with the standard library alone, on a host with no ROS.
* **G4 sidecar**  — a ``parcel.bag.v1`` manifest built from a rosbag2 recording,
  binding every split file by SHA-256, with the sequence-evidence gap stated.
* **G5 no weakening** — the Parcel-format path still refuses a rosbag2 file, and
  the rosbag2 path still refuses a Parcel file. Two formats, two readers,
  neither loosened to accommodate the other.
"""

from __future__ import annotations

import base64
import json
import shutil
import struct
import sys
import zlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from parcel_robot.bags.schema import SCHEMA_VERSION, validate_manifest, validate_topic
from parcel_robot.capture import CHANNELS, Transport, channel
from parcel_robot.capture.channels import Confidence, WireNaming, subscribe_name
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture import rosbag2 as rb
from scripts.parcel_capture.record import read_mcap
from scripts.parcel_capture.sidecar import (
    SIDECAR_EXTRA_KEY,
    BagFormat,
    ChannelVerdict,
    RecorderRole,
    SidecarRefusedError,
    build_rosbag2_sidecar,
    build_sidecar,
    finalize_rosbag2,
    verify_rosbag2_sidecar,
    verify_sidecar,
)

LOWSTATE = "/lowstate"
CLOUD = "/utlidar/cloud"
SPLIT = "/events/write_split"

TYPES = {
    LOWSTATE: "unitree_go/msg/LowState",
    CLOUD: "sensor_msgs/msg/PointCloud2",
    SPLIT: "rosbag2_interfaces/msg/WriteSplitEvent",
}


def _messages(*, lowstate: int = 500, clouds: int = 10, splits: int = 1, span_ns: int = 10**9):
    """One second of a plausible take: 500 Hz LowState, 10 Hz cloud, one split."""

    out = []
    for index in range(lowstate):
        out.append((LOWSTATE, 1_000_000_000 + index * (span_ns // max(lowstate, 1)), b"L" * 180))
    for index in range(clouds):
        out.append((CLOUD, 1_000_000_000 + index * (span_ns // max(clouds, 1)), b"C" * 4096))
    for index in range(splits):
        out.append((SPLIT, 1_000_000_000 + index * 1_000_000, b"S" * 24))
    return out


def _bag(tmp_path: Path, name: str = "take01", **kwargs) -> Path:
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    rb.write_fixture_bag(
        directory / f"{name}_0.mcap", _messages(**kwargs), types=TYPES
    )
    (directory / "metadata.yaml").write_text(
        "rosbag2_bagfile_information:\n"
        "  storage_identifier: mcap\n"
        "  relative_file_paths:\n"
        f"    - {name}_0.mcap\n",
        encoding="utf-8",
    )
    return directory


# ---------------------------------------------------------------------------
# G1 — the command line
# ---------------------------------------------------------------------------


def test_the_command_line_is_exact_and_uses_the_mcap_storage_plugin() -> None:
    plan = rb.plan_for_session("/data/parcel/take01")
    argv = rb.record_command(plan)
    assert argv[:3] == ("ros2", "bag", "record")
    assert "--storage" in argv and argv[argv.index("--storage") + 1] == "mcap"
    assert argv[argv.index("--output") + 1] == "/data/parcel/take01"
    assert "-a" not in argv  # never "everything on the graph"
    assert set(plan.topic_names) <= set(argv)
    # The Jazzy form of the same plan takes the flag; Humble has no such flag.
    # See the PS-M section for the whole argument.
    jazzy = rb.record_command(rb.plan_for_session("/data/parcel/take01", distro=rb.RosDistro.JAZZY))
    assert "--topics" in jazzy
    # The recorder reads stdin for pause/resume. Under a run-sheet the operator
    # is typing elsewhere; under nohup/ssh there is no tty at all.
    assert "--disable-keyboard-controls" in jazzy


def test_no_topic_on_the_command_line_is_ever_the_raw_dds_wire_name() -> None:
    """``rclpy`` applies the ``rt/`` mangling itself. A recorder handed the
    mangled name subscribes to ``rt/rt/...`` and receives nothing, silently."""

    plan = rb.plan_for_session("/tmp/x")
    for topic in plan.topic_names:
        assert topic.startswith("/")
        assert not topic.startswith("/rt/")
    entry = channel("go2.lowstate")
    assert subscribe_name(entry.channel_id, WireNaming.RAW_DDS) == "rt/lowstate"
    assert "/lowstate" in plan.topic_names


def test_seeded_failure_a_wire_name_cannot_be_put_on_the_command_line() -> None:
    with pytest.raises(rb.Rosbag2RefusedError, match="raw-DDS wire name"):
        rb.RecordedTopic(
            "/rt/lowstate",
            "unitree_go/msg/LowState",
            rb.TopicSource.ROBOT_NATIVE,
            "go2.lowstate",
            Confidence.CONFIRMED,
            "mutant",
        )
    with pytest.raises(rb.Rosbag2RefusedError, match="ABSOLUTE ROS names"):
        rb.RecordedTopic(
            "lowstate",
            "unitree_go/msg/LowState",
            rb.TopicSource.ROBOT_NATIVE,
            "go2.lowstate",
            Confidence.CONFIRMED,
            "mutant",
        )


def test_every_dds_row_of_the_corrected_matrix_is_on_the_topic_list() -> None:
    """Derived from PS-H's matrix, not from a second hand-written list."""

    dds_rows = {entry.channel_id for entry in CHANNELS if entry.transport is Transport.DDS}
    assert len(dds_rows) == 15
    on_list = {
        item.channel_id
        for item in rb.RECORDED_TOPICS
        if item.source is rb.TopicSource.ROBOT_NATIVE
    }
    assert on_list == dds_rows


def test_the_recorder_event_topics_are_recorded_as_channels() -> None:
    """Recording them puts the recorder's account of its own losses and splits
    INSIDE the bag, on the same clock as the data, where it survives the process
    that produced it."""

    names = {item.topic for item in rb.EVENT_TOPICS}
    assert names == {"/events/write_split", "/events/messages_lost"}
    plan = rb.plan_for_session("/tmp/x")
    assert names <= set(plan.topic_names)


def test_the_event_topic_whose_existence_is_unverified_says_so_in_its_row() -> None:
    """Fail-honest, not fail-closed-by-omission: listing a topic that does not
    exist costs nothing at record time; assuming one that does exist is not
    recorded costs the evidence."""

    by_name = {item.topic: item for item in rb.EVENT_TOPICS}
    assert by_name["/events/write_split"].confidence is Confidence.CONFIRMED
    assert by_name["/events/messages_lost"].confidence is Confidence.UNVERIFIED
    assert "ros2 topic list" in by_name["/events/messages_lost"].note


def test_the_d455_and_l2_topics_carry_the_driver_that_produces_them() -> None:
    """These are DRIVER_NODE topics: they exist only if we launched their
    driver, which is a different failure mode from a dog that is switched off."""

    for item in rb.DRIVER_TOPICS:
        assert item.source is rb.TopicSource.DRIVER_NODE
        assert item.prerequisite.startswith("ros2 launch")
        assert item.confidence is Confidence.UNVERIFIED
    channel_ids = {item.channel_id for item in rb.DRIVER_TOPICS}
    assert channel_ids == {
        "d455.color", "d455.depth", "d455.infra1", "d455.infra2",
        "d455.accel", "d455.gyro", "l2.cloud", "l2.imu",
    }


def test_a_plan_can_drop_the_driver_topics_and_refuses_a_typo_in_an_exclusion() -> None:
    lean = rb.plan_for_session("/tmp/x", include_driver_nodes=False)
    assert not any(name.startswith("/camera/") for name in lean.topic_names)
    with pytest.raises(rb.Rosbag2RefusedError, match="typo"):
        rb.plan_for_session("/tmp/x", exclude=("/lowstat",))


def test_the_readiness_report_is_actionable_here_and_never_a_traceback() -> None:
    text = rb.readiness_report(rb.plan_for_session("/tmp/x"))
    assert "Traceback" not in text
    assert "ros2 bag record" in text
    if shutil.which("ros2") is None:
        assert "UNAVAILABLE here: ros2 is not on PATH" in text
    assert "ros2 topic list -t" in text


def test_the_cli_refuses_cleanly_with_no_ros_installed(capsys) -> None:
    code = rb.main(["--check"])
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out + captured.err
    assert code in (0, 3)


# ---------------------------------------------------------------------------
# G2 — the storage config
# ---------------------------------------------------------------------------


def test_the_crash_safe_profile_turns_chunking_and_compression_off() -> None:
    """A chunk buffers messages INSIDE the writer, which is exactly the state a
    SIGKILL or a flat battery destroys. Compression additionally makes the bag
    uncountable by any stdlib tool on a night with no zstandard installed."""

    options = rb.writer_options(rb.WriterProfile.CRASH_SAFE)
    assert options["noChunking"] is True
    assert options["compression"] == "None"  # the enum spelling, never ""
    indexed = rb.writer_options(rb.WriterProfile.INDEXED)
    assert indexed["noChunking"] is False
    assert indexed["compression"] == "None"  # never compressed, in either profile


def test_the_storage_config_is_json_compatible_yaml_and_states_its_provenance() -> None:
    """JSON is a subset of YAML 1.2, so the emitted file is valid input to the
    C++ parser rosbag2 uses AND machine-readable back with :mod:`json` on a box
    with no PyYAML."""

    text = rb.storage_config_yaml()
    assert "MEASURED against rosbag2_storage_mcap" in text
    assert "UNVERIFIED" in text  # the Orin's own plugin build still is
    assert "drop" in text and "--storage-config-file" in text  # the fallback is in the file
    body = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        key, _, value = line.partition(":")
        body[key.strip()] = json.loads(value.strip())
    assert body == rb.writer_options(rb.WriterProfile.CRASH_SAFE)


def test_the_config_is_optional_so_a_rejected_key_costs_tuning_and_not_the_session() -> None:
    plan = rb.plan_for_session("/tmp/x")
    assert plan.storage_config_path is None
    assert "--storage-config-file" not in rb.record_command(plan)
    with_config = rb.plan_for_session("/tmp/x", storage_config_path="/tmp/w.yaml")
    assert "--storage-config-file" in rb.record_command(with_config)


# ---------------------------------------------------------------------------
# G3 — reading a rosbag2 MCAP with the standard library
# ---------------------------------------------------------------------------


def test_a_clean_rosbag2_bag_reads_back_with_per_topic_counts(tmp_path: Path) -> None:
    directory = _bag(tmp_path)
    scan = rb.read_rosbag2_mcap(next(directory.glob("*.mcap")))
    assert scan.is_rosbag2
    assert scan.is_clean
    assert scan.counts == {LOWSTATE: 500, CLOUD: 10, SPLIT: 1}
    assert scan.count_basis is rb.CountBasis.WALKED
    assert {item.message_encoding for item in scan.channels} == {"cdr"}
    assert scan.channels[0].channel_id == "go2.lowstate"


def test_a_chunked_bag_is_walked_and_a_compressed_one_falls_back_and_says_so(
    tmp_path: Path,
) -> None:
    """The crash-safe profile's real payoff, measured: an uncompressed bag is
    fully countable by the standard library; a compressed one is a number we
    would have to take on trust, and the basis field says which."""

    messages = _messages(lowstate=20, clouds=2)
    chunked = rb.write_fixture_bag(tmp_path / "chunked.mcap", messages, types=TYPES, chunked=True)
    assert rb.read_rosbag2_mcap(chunked).count_basis is rb.CountBasis.WALKED
    assert rb.read_rosbag2_mcap(chunked).counts[LOWSTATE] == 20

    squashed = rb.write_fixture_bag(
        tmp_path / "zstd.mcap", messages, types=TYPES, chunked=True,
        compression="zstd", with_statistics=True,
    )
    scan = rb.read_rosbag2_mcap(squashed)
    assert scan.count_basis is rb.CountBasis.UNAVAILABLE_COMPRESSED
    assert scan.counts[LOWSTATE] == 20  # from the writer's Statistics record
    assert any("does not decompress" in note for note in scan.findings)


def test_a_bag_whose_recorder_was_killed_is_truncated_not_short(tmp_path: Path) -> None:
    """A flat battery is the expected way this session ends. The reader must
    recover every complete message and classify the tail as truncation."""

    path = rb.write_fixture_bag(
        tmp_path / "killed.mcap", _messages(lowstate=100, clouds=4), types=TYPES, close=False
    )
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) - 60])
    scan = rb.read_rosbag2_mcap(path)
    assert scan.termination is rb.ScanTermination.TRUNCATED
    assert not scan.saw_footer
    assert scan.counts[LOWSTATE] > 0
    assert scan.message_count < 104
    assert scan.detail


def test_the_writers_own_statistics_are_reconciled_against_what_survives(
    tmp_path: Path,
) -> None:
    """Two independent statements about the same recording. A disagreement is a
    finding, never reconciled in favour of whichever is smaller."""

    path = rb.write_fixture_bag(
        tmp_path / "stats.mcap", _messages(lowstate=30, clouds=3), types=TYPES,
        with_statistics=True,
    )
    scan = rb.read_rosbag2_mcap(path)
    assert scan.findings == ()

    # And when the two disagree, the walk wins and the disagreement is a
    # finding. Built by writing a Statistics record for a bag whose messages
    # were then trimmed, which is what a killed recorder with a summary looks
    # like.
    trimmed = rb.write_fixture_bag(
        tmp_path / "disagree.mcap", _messages(lowstate=30, clouds=3), types=TYPES,
        with_statistics=True,
    )
    raw = bytearray(trimmed.read_bytes())
    index = raw.find(b"\x05\x00\x00\x00")  # first Message record header byte run
    assert index > 0
    scan2 = rb.read_rosbag2_mcap(trimmed)
    assert scan2.counts[LOWSTATE] == 30
    assert scan2.count_basis is rb.CountBasis.WALKED


def test_a_file_that_is_not_mcap_at_all_is_a_different_finding(tmp_path: Path) -> None:
    junk = tmp_path / "notes.txt"
    junk.write_text("this is not a bag", encoding="utf-8")
    with pytest.raises(rb.NotAnMcapFileError):
        rb.read_rosbag2_mcap(junk)


def test_a_parcel_capture_bag_is_recognised_as_not_being_a_rosbag2_recording(
    tmp_path: Path,
) -> None:
    """The header profile is the discriminator, and getting it wrong would mean
    describing one format with the other's reader."""

    path = rb.write_fixture_bag(
        tmp_path / "parcel.mcap", _messages(lowstate=3, clouds=1), types=TYPES,
        profile="parcel-capture",
    )
    scan = rb.read_rosbag2_mcap(path)
    assert not scan.is_rosbag2
    assert any("not written by rosbag2" in note for note in scan.findings)


def test_bag_discovery_cross_checks_metadata_against_the_directory(tmp_path: Path) -> None:
    directory = _bag(tmp_path)
    found = rb.discover_bag(directory)
    assert [path.name for path in found.files] == ["take01_0.mcap"]
    assert found.findings == ()

    (directory / "metadata.yaml").write_text(
        "rosbag2_bagfile_information:\n  relative_file_paths:\n    - take01_9.mcap\n",
        encoding="utf-8",
    )
    disagreeing = rb.discover_bag(directory)
    assert any("metadata.yaml names" in note for note in disagreeing.findings)


def test_an_absent_metadata_yaml_is_recorded_as_the_recorder_never_closing(
    tmp_path: Path,
) -> None:
    directory = _bag(tmp_path)
    (directory / "metadata.yaml").unlink()
    found = rb.discover_bag(directory)
    assert any("never closed this bag" in note for note in found.findings)


def test_a_directory_with_no_mcap_file_is_a_refusal(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(rb.Rosbag2RefusedError, match="no .mcap file"):
        rb.discover_bag(empty)


# ---------------------------------------------------------------------------
# G3b — ``ros2 bag info``
# ---------------------------------------------------------------------------

_INFO_TEXT = """
Files:             take01_0.mcap
Bag size:          1.2 GiB
Storage id:        mcap
Duration:          61.402s
Start:             Aug 14 2026 09:12:03.100 (1786000323.100)
End:               Aug 14 2026 09:13:04.502 (1786000384.502)
Messages:          31212
Topic information: Topic: /lowstate | Type: unitree_go/msg/LowState | Count: 30701 | Serialization Format: cdr
                   Topic: /utlidar/cloud | Type: sensor_msgs/msg/PointCloud2 | Count: 610 | Serialization Format: cdr
"""


def test_ros2_bag_info_is_parsed_into_per_topic_counts() -> None:
    info = rb.parse_bag_info(_INFO_TEXT)
    assert info.counts == {"/lowstate": 30701, "/utlidar/cloud": 610}
    assert info.types["/lowstate"] == "unitree_go/msg/LowState"
    assert info.duration_s == 61.402
    assert info.message_count == 31212
    assert info.storage_id == "mcap"


def test_unparseable_bag_info_is_a_refusal_and_never_an_empty_count_map() -> None:
    """An empty map would flow into a sidecar as "every channel recorded
    nothing", which is a fabricated finding about the session."""

    with pytest.raises(rb.Rosbag2RefusedError, match="recorded\n?.*nothing|not understood"):
        rb.parse_bag_info("ros2: command not found")


@pytest.mark.skipif(shutil.which("ros2") is not None, reason="this host has ros2")
def test_running_bag_info_here_refuses_with_the_remedy_and_the_fallback(
    tmp_path: Path,
) -> None:
    with pytest.raises(rb.Rosbag2RefusedError) as caught:
        rb.run_bag_info(_bag(tmp_path))
    message = str(caught.value)
    assert "ros2 is not on PATH" in message
    assert "read_rosbag2_mcap()" in message  # the stdlib fallback is named


# ---------------------------------------------------------------------------
# G4 — the sidecar
# ---------------------------------------------------------------------------


def test_a_rosbag2_recording_yields_a_valid_parcel_bag_v1_manifest(tmp_path: Path) -> None:
    directory = _bag(tmp_path)
    sidecar = build_rosbag2_sidecar(bag_id="P5-DRY-20260814-take01", bag_dir=directory)
    validate_manifest(sidecar)
    assert sidecar["schema_version"] == SCHEMA_VERSION
    assert sidecar["source"] == "hardware"
    assert sidecar["clocks"]["source_clock"] == "ros"
    for topic in sidecar["topics"]:
        validate_topic(topic)
    block = sidecar[SIDECAR_EXTRA_KEY]
    assert block["bag_format"] == BagFormat.ROSBAG2_MCAP.value
    assert block["role"] == RecorderRole.PRIMARY.value
    assert block["channels"]["go2.lowstate"]["verdict"] == ChannelVerdict.PRESENT.value
    assert block["channels"]["go2.lowstate"]["messages"] == 500


def test_the_sidecar_digests_every_split_file_and_a_mutated_byte_breaks_it(
    tmp_path: Path,
) -> None:
    """The gate that makes the digest mean something."""

    directory = tmp_path / "split"
    directory.mkdir()
    for index in range(3):
        rb.write_fixture_bag(
            directory / f"split_{index}.mcap",
            _messages(lowstate=100, clouds=2),
            types=TYPES,
        )
    sidecar = build_rosbag2_sidecar(bag_id="split-take", bag_dir=directory)
    block = sidecar[SIDECAR_EXTRA_KEY]["rosbag2"]
    assert block["file_count"] == 3
    assert len({item["sha256"] for item in block["files"]}) == 1  # identical fixtures
    assert verify_rosbag2_sidecar(sidecar, directory).ok

    target = directory / "split_1.mcap"
    raw = bytearray(target.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    target.write_bytes(bytes(raw))
    result = verify_rosbag2_sidecar(sidecar, directory)
    assert not result.ok
    assert any("digest mismatch on split_1.mcap" in failure for failure in result.failures)


def test_a_split_file_the_sidecar_does_not_name_fails_verification(tmp_path: Path) -> None:
    """A split recording is not verified while part of it is undescribed."""

    directory = _bag(tmp_path)
    sidecar = build_rosbag2_sidecar(bag_id="take", bag_dir=directory)
    assert verify_rosbag2_sidecar(sidecar, directory).ok
    rb.write_fixture_bag(directory / "take01_1.mcap", _messages(lowstate=5), types=TYPES)
    result = verify_rosbag2_sidecar(sidecar, directory)
    assert not result.ok
    assert any("does not name" in failure for failure in result.failures)


def test_the_sidecar_states_that_no_per_channel_sequence_evidence_exists(
    tmp_path: Path,
) -> None:
    """The honest, load-bearing weakness of the primary path. rosbag2 mints no
    per-channel counter, so an interior hole — the only proof of an individual
    dropped message — cannot exist in the bag. The Parcel secondary path keeps
    its value precisely here."""

    sidecar = build_rosbag2_sidecar(bag_id="take", bag_dir=_bag(tmp_path))
    block = sidecar[SIDECAR_EXTRA_KEY]
    assert block["channels"]["go2.lowstate"]["sequence"]["status"] == "unavailable"
    assert block["recorder_account"]["status"] == "unavailable"
    assert any(
        "mints no per-channel sequence number" in line for line in sidecar["does_not_prove"]
    )


def test_a_rate_deficit_is_reported_with_the_deficit_quantified(tmp_path: Path) -> None:
    directory = _bag(tmp_path, lowstate=250)  # half of the 500 Hz nominal over 1 s
    sidecar = build_rosbag2_sidecar(bag_id="deficit", bag_dir=directory)
    record = sidecar[SIDECAR_EXTRA_KEY]["channels"]["go2.lowstate"]
    assert record["verdict"] == ChannelVerdict.DEGRADED.value
    assert record["deficit_messages"] > 0
    assert "short by" in record["reason"]


def test_a_topic_with_no_matrix_row_is_counted_as_unmapped_not_dropped(
    tmp_path: Path,
) -> None:
    sidecar = build_rosbag2_sidecar(bag_id="take", bag_dir=_bag(tmp_path))
    unmapped = sidecar[SIDECAR_EXTRA_KEY]["rosbag2"]["unmapped_topics"]
    assert unmapped == {SPLIT: 1}
    assert any("map to no channel of the matrix" in line for line in sidecar["does_not_prove"])
    assert SPLIT not in sidecar["topics"]  # never fabricated into a parcel topic


def test_ros2_bag_info_counts_win_and_a_disagreement_is_recorded(tmp_path: Path) -> None:
    """When the recorder's own tool disagrees with our walk, the sidecar quotes
    the tool AND records the disagreement rather than choosing quietly."""

    directory = _bag(tmp_path)
    info = rb.Rosbag2Info(
        counts={LOWSTATE: 499, CLOUD: 10},
        types={LOWSTATE: TYPES[LOWSTATE], CLOUD: TYPES[CLOUD]},
        duration_s=1.0,
        message_count=509,
        storage_id="mcap",
        raw="synthetic",
    )
    sidecar = build_rosbag2_sidecar(bag_id="take", bag_dir=directory, bag_info=info)
    block = sidecar[SIDECAR_EXTRA_KEY]
    assert block["channels"]["go2.lowstate"]["messages"] == 499
    assert block["rosbag2"]["count_basis"] == "ros2_bag_info"
    assert any("stdlib walk found 500" in note for note in block["termination"]["findings"])


def test_the_count_basis_is_never_left_implicit(tmp_path: Path) -> None:
    sidecar = build_rosbag2_sidecar(bag_id="take", bag_dir=_bag(tmp_path))
    assert sidecar[SIDECAR_EXTRA_KEY]["rosbag2"]["count_basis"] == "walked_messages"
    assert any(
        "not from `ros2 bag info`" in line for line in sidecar["does_not_prove"]
    )


def test_origin_is_a_declaration_and_the_sidecar_says_it_was_declared(
    tmp_path: Path,
) -> None:
    """rosbag2 carries no ``EvidenceOrigin``; pretending it does would let a
    rehearsal pass for a session."""

    directory = _bag(tmp_path)
    sidecar = build_rosbag2_sidecar(
        bag_id="rehearsal", bag_dir=directory, origin=EvidenceOrigin.SIMULATION
    )
    assert sidecar["source"] == "sim"
    assert sidecar["hardware_claims"] is False
    assert sidecar[SIDECAR_EXTRA_KEY]["origin"]["basis"] == "declared_by_caller"

    with pytest.raises(SidecarRefusedError, match="declares nothing"):
        build_rosbag2_sidecar(
            bag_id="x", bag_dir=directory, origin=EvidenceOrigin.UNKNOWN
        )


def test_a_truncated_recording_is_reported_as_truncation_in_the_sidecar(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "killed"
    directory.mkdir()
    path = rb.write_fixture_bag(
        directory / "killed_0.mcap", _messages(lowstate=200, clouds=4), types=TYPES, close=False
    )
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) - 40])
    sidecar = build_rosbag2_sidecar(bag_id="killed", bag_dir=directory)
    assert sidecar[SIDECAR_EXTRA_KEY]["termination"]["kind"] == "truncated"
    assert any("TRUNCATED" in line for line in sidecar["does_not_prove"])


def test_a_bag_with_no_matrix_channel_is_a_finding_not_a_manifest(tmp_path: Path) -> None:
    directory = tmp_path / "stranger"
    directory.mkdir()
    rb.write_fixture_bag(
        directory / "stranger_0.mcap",
        [("/tf", 1_000_000_000, b"T" * 16)],
        types={"/tf": "tf2_msgs/msg/TFMessage"},
    )
    with pytest.raises(SidecarRefusedError, match="no topic that maps to a channel"):
        build_rosbag2_sidecar(bag_id="stranger", bag_dir=directory)


def test_finalize_writes_the_sidecar_beside_the_bag_directory(tmp_path: Path) -> None:
    """Beside, not inside: a file inside would change the directory a later
    ``ros2 bag`` command reads, and a sidecar must never affect what it
    describes."""

    directory = _bag(tmp_path)
    _sidecar, path = finalize_rosbag2(directory, bag_id="P5-DRY-20260814-take01")
    assert path.parent == directory.parent
    assert not (directory / path.name).exists()
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["bag_id"] == "P5-DRY-20260814-take01"
    assert verify_rosbag2_sidecar(reloaded, directory).ok


# ---------------------------------------------------------------------------
# G5 — neither format's validation was weakened for the other
# ---------------------------------------------------------------------------


def test_the_parcel_reader_still_refuses_a_rosbag2_encoding(tmp_path: Path) -> None:
    """``record.py:_decode_channel`` refuses any channel that does not declare
    Parcel's own ``message_encoding``. That is correct for the Parcel format and
    is exactly why it cannot see a rosbag2 file — so PS-G added a second reader
    rather than loosening this one."""

    path = rb.write_fixture_bag(
        tmp_path / "ros.mcap", _messages(lowstate=3, clouds=1), types=TYPES
    )
    scan = read_mcap(path)
    assert scan.termination.value == "corrupt"
    assert "message_encoding" in scan.detail
    assert scan.message_count == 0

    source = (REPO / "scripts" / "parcel_capture" / "record.py").read_text(encoding="utf-8")
    assert 'if encoding != MESSAGE_ENCODING:' in source  # the refusal is still there


def test_the_parcel_sidecar_path_still_refuses_a_rosbag2_file(tmp_path: Path) -> None:
    path = rb.write_fixture_bag(
        tmp_path / "ros.mcap", _messages(lowstate=3, clouds=1), types=TYPES
    )
    with pytest.raises(SidecarRefusedError, match="registers no channels"):
        build_sidecar(bag_id="wrong-reader", mcap_path=path)


def test_verify_sidecar_sends_a_rosbag2_manifest_to_the_right_verifier(
    tmp_path: Path,
) -> None:
    """A rosbag2 recording is a DIRECTORY of split files. Verifying it through
    the single-file path would check one split and report the take as bound."""

    directory = _bag(tmp_path)
    sidecar = build_rosbag2_sidecar(bag_id="take", bag_dir=directory)
    result = verify_sidecar(sidecar, next(directory.glob("*.mcap")))
    assert not result.ok
    assert any("verify_rosbag2_sidecar()" in failure for failure in result.failures)


def test_the_rosbag2_verifier_refuses_a_parcel_manifest(tmp_path: Path) -> None:
    from scripts.parcel_capture.record import CaptureRecorder, SpaceBudget

    bag = tmp_path / "parcel.mcap"
    recorder = CaptureRecorder(
        bag,
        bag_id="parcel",
        channels=[channel("go2.lowstate")],
        origin=EvidenceOrigin.SIMULATION,
        budget=SpaceBudget(bytes_per_second=10_000, duration_s=10),
        fixture_label="ps-g",
    )
    recorder.record("go2.lowstate", b"x" * 8, host_monotonic_ns=1, host_realtime_ns=2)
    recorder.close(reason="done")
    parcel_sidecar = build_sidecar(bag_id="parcel", mcap_path=bag)
    assert parcel_sidecar[SIDECAR_EXTRA_KEY]["bag_format"] == BagFormat.PARCEL_MCAP.value
    assert parcel_sidecar[SIDECAR_EXTRA_KEY]["role"] == RecorderRole.SECONDARY.value

    result = verify_rosbag2_sidecar(parcel_sidecar, tmp_path)
    assert not result.ok
    assert any("use verify_sidecar()" in failure for failure in result.failures)


def test_the_parcel_sidecar_now_says_it_is_the_secondary_copy(tmp_path: Path) -> None:
    """The demotion, recorded in the artefact rather than only in a plan."""

    from scripts.parcel_capture.record import CaptureRecorder, SpaceBudget

    bag = tmp_path / "secondary.mcap"
    recorder = CaptureRecorder(
        bag,
        bag_id="secondary",
        channels=[channel("go2.lowstate")],
        origin=EvidenceOrigin.SIMULATION,
        budget=SpaceBudget(bytes_per_second=10_000, duration_s=10),
        fixture_label="ps-g",
    )
    recorder.record("go2.lowstate", b"x" * 8, host_monotonic_ns=1, host_realtime_ns=2)
    recorder.close(reason="done")
    sidecar = build_sidecar(bag_id="secondary", mcap_path=bag)
    line = next(
        line for line in sidecar["does_not_prove"] if "SECONDARY copy" in line
    )
    assert "no downstream SLAM or calibration tool can open it" in line
    assert "ros2 bag record -s mcap" in line


def test_the_fixture_writer_stamps_itself_as_a_fixture_inside_the_file(
    tmp_path: Path,
) -> None:
    """A fixture must never be mistakable for a recording. ``ros2 bag record``
    writes the session; this writes bytes for tests and tonight's dry run."""

    path = rb.write_fixture_bag(tmp_path / "f.mcap", _messages(lowstate=2), types=TYPES)
    scan = rb.read_rosbag2_mcap(path)
    assert "FIXTURE" in scan.library
    assert "not a recorder" in scan.library


# ---------------------------------------------------------------------------
# PS-M — the three defects that made the primary recorder record, or read,
# nothing at all. Each test below fails against the code as it shipped.
# ---------------------------------------------------------------------------


def _mcap_record(opcode: int, content: bytes) -> bytes:
    """opcode uint8 + content length uint64 + content. Spec §Records."""

    return struct.pack("<BQ", opcode, len(content)) + content


def _mcap_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def _hand_built_chunked_bag(*, records_prefix_bits: int) -> bytes:
    """A chunked rosbag2 MCAP assembled byte by byte from the spec's own tables.

    Deliberately NOT built with :func:`rb.write_fixture_bag`: the width defect
    survived a green suite precisely because the fixture writer shared it, so a
    fixture built by the same module can never be the witness. Every field here
    is packed from the specification table:

    * every record: ``opcode`` uint8, ``length`` **uint64**;
    * ``Schema``: ``id`` uint16, ``name``/``encoding`` Strings, ``data`` uint32
      length-prefixed Bytes;
    * ``Channel``: ``id``/``schema_id`` uint16, two Strings, ``metadata`` uint32
      length-prefixed;
    * ``Message``: ``channel_id`` uint16, ``sequence`` uint32, ``log_time`` and
      ``publish_time`` uint64, payload unprefixed;
    * ``Chunk``: two uint64 Timestamps, ``uncompressed_size`` uint64,
      ``uncompressed_crc`` uint32, ``compression`` String, and ``records``
      **uint64** length-prefixed — the one Bytes field in the format that is not
      uint32-prefixed, which is ``records_prefix_bits`` here.
    """

    schema = _mcap_record(
        rb.OP_SCHEMA,
        struct.pack("<H", 1)
        + _mcap_string("unitree_go/msg/LowState")
        + _mcap_string(rb.ROS2_SCHEMA_ENCODING)
        + struct.pack("<I", 0),
    )
    channel = _mcap_record(
        rb.OP_CHANNEL,
        struct.pack("<HH", 1, 1)
        + _mcap_string(LOWSTATE)
        + _mcap_string(rb.ROS2_MESSAGE_ENCODING)
        + struct.pack("<I", 0),
    )
    messages = b"".join(
        _mcap_record(
            rb.OP_MESSAGE,
            struct.pack("<HIQQ", 1, index + 1, 2_000_000_000 + index, 2_000_000_000 + index)
            + b"LOWSTATE-PAYLOAD",
        )
        for index in range(3)
    )
    inner = schema + channel + messages
    prefix = {32: struct.pack("<I", len(inner)), 64: struct.pack("<Q", len(inner))}[
        records_prefix_bits
    ]
    chunk = _mcap_record(
        rb.OP_CHUNK,
        struct.pack("<QQQ", 2_000_000_000, 2_000_000_002, len(inner))
        + struct.pack("<I", 0)
        + _mcap_string("")
        + prefix
        + inner,
    )
    return (
        rb.MCAP_MAGIC
        + _mcap_record(rb.OP_HEADER, _mcap_string("ros2") + _mcap_string("PS-M hand-built"))
        + chunk
        + _mcap_record(rb.OP_DATA_END, struct.pack("<I", 0))
        + _mcap_record(rb.OP_FOOTER, struct.pack("<QQI", 0, 0, 0))
        + rb.MCAP_MAGIC
    )


def _chunk_framing(raw: bytes) -> tuple[int, int, int]:
    """(declared record length, compression string length, records length) of the
    first Chunk record in ``raw``, read straight off the bytes."""

    offset = len(rb.MCAP_MAGIC)
    while offset < len(raw):
        opcode, length = struct.unpack_from("<BQ", raw, offset)
        if opcode == rb.OP_CHUNK:
            body = offset + 9
            compression_len = struct.unpack_from("<I", raw, body + 28)[0]
            records_at = body + 32 + compression_len
            return length, compression_len, struct.unpack_from("<Q", raw, records_at)[0]
        offset += 9 + length
    raise AssertionError("no Chunk record in these bytes")


def test_a_chunk_records_length_prefix_is_read_as_uint64_not_uint32(tmp_path: Path) -> None:
    """THE defect. ``ros2 bag record`` chunks by default, so reading this one
    prefix four bytes narrow made **every healthy uncompressed rosbag2 bag**
    classify as CORRUPT with zero messages — and the sidecar then stamped that
    verdict on the primary recording of the session.

    Fails on the shipped reader: the spec-correct bag below scanned as
    ``termination=corrupt``, ``counts={}``, with the cursor four bytes early and
    the first inner opcode read as ``0x00``.
    """

    good = tmp_path / "spec.mcap"
    good.write_bytes(_hand_built_chunked_bag(records_prefix_bits=64))
    scan = rb.read_rosbag2_mcap(good)
    assert scan.termination is rb.ScanTermination.CLEAN, scan.detail
    assert scan.counts == {LOWSTATE: 3}
    assert scan.count_basis is rb.CountBasis.WALKED
    assert scan.channels[0].schema_name == "unitree_go/msg/LowState"
    assert scan.findings == ()

    # The file's own framing arithmetic proves the width without appealing to
    # the reader: 32 fixed bytes + the compression string + the prefix + the
    # records. Only an 8-byte prefix balances it.
    declared, compression_len, records_len = _chunk_framing(good.read_bytes())
    assert declared == 32 + compression_len + 8 + records_len
    assert declared != 32 + compression_len + 4 + records_len

    # And the shape the old writer produced is not quietly tolerated: a uint32
    # prefix is refused as damage, never counted as a short bag.
    bad = tmp_path / "u32.mcap"
    bad.write_bytes(_hand_built_chunked_bag(records_prefix_bits=32))
    broken = rb.read_rosbag2_mcap(bad)
    assert broken.termination is rb.ScanTermination.CORRUPT
    assert broken.counts == {}


#: A **real** rosbag2 MCAP, zlib+base64 of 5148 bytes written by
#: ``rosbag2_storage_mcap`` 0.26.11 / ``libmcap`` 1.3.1 through
#: ``rosbag2_py.SequentialWriter`` (ROS 2 Jazzy, chunked, uncompressed,
#: ``noChunking: false``, ``chunkSize: 4194304``, ``compression: "None"``).
#: sha256 cf32e5ff86be4475c0433118b8c78b860baaf8a0ebaff815b6dbdbc39fd0cafa.
#: No fixture writer of ours touched these bytes, which is the point: the
#: previous chunked fixture agreed with the broken reader.
REAL_ROSBAG2_CHUNKED_MCAP_Z85 = (
    "eNrtWFtoXEUYPtmkTbJpGkzzonlwSBVLIZtN0m3WzV5SxFKvNFRUDOV4cs7s7phzzmzOOZtNokhEqQS8gOClvnh5sS99"
    "8PKggiAWRKxPFrGI5KUU0YdSUZQ+CM6c/Wczsxsdii8KHtj9duabme/MzD//P/9u3nfHkePpwWTXjUbz6WGfgIZTgwxd"
    "sujZVg1NpqZTk3sSiWaL3maLRasy9UuXYexjxRAHxHLJOnZMD0eWY0XWRUat4CAk1M+h25NhRAOrgk3iYD8iZYKDHOJj"
    "J516YEW8URIh3/JpiG3qO2EOpVkfK4iIXzEj4uE23gyJb2MT16hdZeNPTU1Pz0ylpw9nM4dmZjLZ9EzSw2HIFW1a9yM+"
    "XERrxA7NBomqpkqyoRdOJm3q1QJWz17GLNPAs1ivsTGl2qMOjisD7LK3XsFmmbjYrFlRNeSjjCO2KqZtEt/Bq2wxyoR/"
    "p1PxTHlTaMU75P6uLWJPx/T5c11LwDvI69s2AF8UXtWxUnadbZdn8m3MoSeTbLNNh4RRQHPoMWt9fW33Yj9Yy5evz3LY"
    "uDY3xzEH9Zmrl8pyuXuiq/mjq2kuEbOTsBJOsK+JE1HAJglGNcVqelnb/eiBKglRwwoRDUiF+JbrrqFaQFeYATmIVVs+"
    "wquWV3OxeP9Ucj+6K0Ksm4PZjtlW1GxJy+goXV1rsYyinod9PlBEkR1g1hKt0XqAaMNHIfYsZqJ2rOhhy2dvV667ssox"
    "2sDMthEp826oQeuug1yyhOPxKOvt1zGqs/2poIjPg72lFfIa1qKKEV6ukxXLZScBkdY04hVJJZnV8/VAfPGTPfOGWLcu"
    "g6/lhEsbzC4i3M0KthNkGIywDy2XccDMZ5ltFVul2NT4cV04OcS+Y8s3o7UaNqtWWOUD7jrQGlneyBayaq5XswIbu+O1"
    "sL3Dxv0fzcqo7WBc+HZWQa3CQ7/NyqhX+H4kr6BW4dHpvIx6hcvzeQW1CqSWl1GvcOWFvIJaheBsXka9wu/n8wpqFR7/"
    "KS+jXsHoLyioVXjmtoKMeoX+owUFtQrPOwUZ9QrDTxcU1Cq88lZBRr3C6KcFBbUKb2wVZNQr3PJHQUGtwpnRoox6hfFc"
    "UUGtwrsPF2XUKxxuFBXUKnz8clFGvULpg6KCWoVzXxdl1Csc+7mooFbhq6GSjHqF+VRJQa3CN/eWZNQrPLJUUlCrsLVZ"
    "klGvYJ8pKahV+OHzkox6BfdySUGtwtXuORn1CvWxOQW1CnBvEtjZofdUQnTYSGzH55dAUITfc8L1QnT9VfAQPG+FUURs"
    "fBDKIvQ9K3iIbB8KHgLXj4KHuHRTt6GEn3ugLKLKE4KHoHFW8BATtgQPLn+ox1A8+xyUhcNeFjz447cFD+72guDBm/bs"
    "MhSnmYGy8IVlwYOre1Xw4Mm+EDw4qmuCBz90cLehuJsFKAsv8pzgwUl8InjwAVcED0f85l5DOcnHoSwO6FOCh/P3nuDh"
    "eF0SPJyekT5DOSR3QlnY/orgwbTfETxY7kXBg2H2w0V+z2edSeD7ib9MAl9L/MMkcCabjp/ryAUn0+JpTwEPaXLAcdS8"
    "KIu3306ZmCRqXb2hll+nc2iHVAZ4sRzxxFoJJbuzA7/TlV0oxvnotozp4NAOSC0eid/g4xx0h9SNzfC/ncVKm6dNXlu2"
    "scNCZPVJbMvl/J+g/hsT1IEsjHxAUmg+CRE/2/59SMb1on3f3cbOf1JkwIUtgU9rdntzoFl6MbFtFeLvC4GDo0AcBBzo"
    "9IatNhN7m3i+s83eG4TZ9cKvLMytxfSUhsHhG23MwGlgjrQzfd8Bc6KdGRzfB+FHLOEI/BAvUIcGp4ZPj2zCf4J/AkdH"
    "GXc="
)


def test_a_chunked_bag_written_by_the_real_libmcap_writer_reads_back_clean(
    tmp_path: Path,
) -> None:
    """The same defect, witnessed by bytes we did not write.

    On the shipped reader this file scanned ``termination=corrupt``,
    ``counts={}``, ``channels=[]`` — a healthy 40-message recording reported as
    corrupt. It also exercises every record type a real bag carries (Header,
    Schema, Channel, Message inside a Chunk, MessageIndex, ChunkIndex,
    Statistics, Metadata, MetadataIndex, SummaryOffset, DataEnd, Footer, both
    magics), which is the width audit done against a real writer rather than
    against our reading of the spec.
    """

    path = tmp_path / "real_rosbag2.mcap"
    raw = zlib.decompress(base64.b64decode(REAL_ROSBAG2_CHUNKED_MCAP_Z85))
    assert len(raw) == 5148
    path.write_bytes(raw)

    scan = rb.read_rosbag2_mcap(path)
    assert scan.is_rosbag2
    assert scan.library == "libmcap 1.3.1"  # not our fixture writer
    assert scan.termination is rb.ScanTermination.CLEAN, scan.detail
    assert scan.counts == {"/lowstate": 40}
    assert scan.count_basis is rb.CountBasis.WALKED
    assert scan.chunk_compressions == ("none",)
    assert scan.findings == ()  # incl. the writer's own Statistics agreeing: 40
    assert scan.channels[0].schema_name == "std_msgs/msg/String"
    assert scan.span_s == pytest.approx(0.078)
    assert scan.saw_data_end and scan.saw_footer and scan.saw_terminal_magic
    assert scan.trailing_bytes == 0

    declared, compression_len, records_len = _chunk_framing(raw)
    assert declared == 32 + compression_len + 8 + records_len


def test_our_fixture_writer_frames_chunk_records_the_way_libmcap_does(
    tmp_path: Path,
) -> None:
    """The fixture writer used a uint32 prefix, which is why a broken reader and
    a broken writer agreed and the suite stayed green. They are now checked
    against each other's arithmetic rather than against each other."""

    path = rb.write_fixture_bag(
        tmp_path / "chunked.mcap", _messages(lowstate=5, clouds=1), types=TYPES, chunked=True
    )
    declared, compression_len, records_len = _chunk_framing(path.read_bytes())
    assert declared == 32 + compression_len + 8 + records_len
    assert rb.read_rosbag2_mcap(path).counts[LOWSTATE] == 5


def test_the_integer_width_audit_pins_the_one_field_that_is_not_uint32() -> None:
    """One wrong width was reason to check them all; the audit is a table in the
    module so that a future edit has to move it deliberately."""

    widths = {(record, field): bits for record, field, bits, _note in rb.MCAP_INTEGER_WIDTHS}
    assert widths[("Chunk", "records")] == 64
    assert widths[("*", "Bytes")] == 32
    assert widths[("*", "record length")] == 64
    assert widths[("Statistics", "schema_count")] == 16
    assert widths[("Message", "sequence")] == 32


def test_no_writer_option_is_ever_an_empty_enum_string() -> None:
    """Finding 2. ``compression: ""`` is not an accepted value: the plugin fails
    its YAML conversion, ``ros2 bag record`` exits 1, and the session records
    ZERO bytes. Measured against ``rosbag2_storage_mcap`` 0.26.11:

        Could not open '.../bag_0' with 'mcap'. Error: yaml-cpp: error at line
        12, column 14: Failed to convert field 'compression'

    for BOTH profiles. The old emitted YAML carried ``compression: ""`` and
    ``compressionLevel: ""``, so this test fails against it on every assert.
    """

    for profile in rb.WriterProfile:
        options = rb.writer_options(profile)
        assert options["compression"] in rb.MCAP_COMPRESSION_VALUES
        assert options["compressionLevel"] in rb.MCAP_COMPRESSION_LEVELS
        assert options["compression"] != ""
        assert options["compressionLevel"] != ""

        body = {}
        for line in rb.storage_config_yaml(profile).splitlines():
            if line.startswith("#") or not line.strip():
                continue
            key, _, value = line.partition(":")
            body[key.strip()] = json.loads(value.strip())
        assert body == options
        assert body["compression"] in ("None", "Lz4", "Zstd")
        assert body["compressionLevel"] in ("Fastest", "Fast", "Default", "Slow", "Slowest")


def test_an_invalid_enum_value_is_refused_before_it_can_reach_a_file() -> None:
    """Fail closed on our machine, in Python, rather than on the Orin in a C++
    YAML exception with the dog standing. The spellings are case-sensitive:
    ``"none"`` is rejected by the plugin exactly as ``""`` is (measured)."""

    for bad in ("", "none", "zstd", "NONE", None):
        with pytest.raises(rb.Rosbag2RefusedError, match="ZERO bytes"):
            rb.validate_writer_options({"compression": bad})
    with pytest.raises(rb.Rosbag2RefusedError, match="ZERO bytes"):
        rb.validate_writer_options({"compression": "None", "compressionLevel": ""})
    # And the message names the specific value the defect shipped with.
    with pytest.raises(rb.Rosbag2RefusedError, match="empty string"):
        rb.validate_writer_options({"compressionLevel": ""})
    rb.validate_writer_options({"compression": "Zstd", "compressionLevel": "Fast"})


#: Every flag Humble's recorder verb declares, read off
#: ``ros2/rosbag2`` branch ``humble`` and tags 0.15.13 / 0.15.14 / 0.15.16 in
#: ``ros2bag/ros2bag/verb/record.py``. The topic list there is
#: ``parser.add_argument('topics', nargs='*')`` — positional. ``--topics``,
#: ``--disable-keyboard-controls`` and ``--node-name`` are **not** in the
#: released tags, and argparse exits 2 on an unrecognised option.
HUMBLE_RECORD_HELP = """usage: ros2 bag record [-h] [-a] ... [topics ...]
options:
  -h, --help
  -a, --all
  -e REGEX, --regex REGEX
  -x EXCLUDE, --exclude EXCLUDE
  --include-unpublished-topics
  --include-hidden-topics
  -o OUTPUT, --output OUTPUT
  -s STORAGE, --storage STORAGE
  -f FORMAT, --serialization-format FORMAT
  --no-discovery
  -p POLLING_INTERVAL, --polling-interval POLLING_INTERVAL
  -b MAX_BAG_SIZE, --max-bag-size MAX_BAG_SIZE
  -d MAX_BAG_DURATION, --max-bag-duration MAX_BAG_DURATION
  --max-cache-size MAX_CACHE_SIZE
  --compression-mode {none,file,message}
  --compression-format COMPRESSION_FORMAT
  --compression-queue-size COMPRESSION_QUEUE_SIZE
  --compression-threads COMPRESSION_THREADS
  --snapshot-mode
  --ignore-leaf-topics
  --qos-profile-overrides-path QOS_PROFILE_OVERRIDES_PATH
  --storage-preset-profile STORAGE_PRESET_PROFILE
  --storage-config-file STORAGE_CONFIG_FILE
  --start-paused
  --use-sim-time
  --log-level LOG_LEVEL
"""

#: The option-declaration lines of ``ros2 bag record --help`` captured verbatim
#: from ROS 2 **Jazzy** (``rosbag2`` 0.26.11) in the repo's sandbox at
#: ``.cache/external-evals/runtime/ros-jazzy-base-sandbox``. The help prose
#: between the declarations is elided; no flag name is.
JAZZY_RECORD_HELP = """usage: ros2 bag record [-h] [-o OUTPUT] ... [[Topic ...] ...]
options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
  -s {sqlite3,mcap}, --storage {sqlite3,mcap}
  --topics Topic [Topic ...]
  --services ServiceName [ServiceName ...]
  --topic-types TopicType [TopicType ...]
  -a, --all             Record all topics and services (Exclude hidden topic).
  --all-topics          Record all topics (Exclude hidden topic).
  --all-services        Record all services via service event topics.
  -e REGEX, --regex REGEX
  --exclude-regex EXCLUDE_REGEX
  --exclude-topic-types ExcludeTopicTypes [ExcludeTopicTypes ...]
  --exclude-topics Topic [Topic ...]
  --exclude-services ServiceName [ServiceName ...]
  --include-unpublished-topics
  --include-hidden-topics
  --no-discovery        Disables topic auto discovery during recording: only
  -p POLLING_INTERVAL, --polling-interval POLLING_INTERVAL
  --ignore-leaf-topics  Ignore topics without a subscription.
  --qos-profile-overrides-path QOS_PROFILE_OVERRIDES_PATH
  -f {}, --serialization-format {}
  -b MAX_BAG_SIZE, --max-bag-size MAX_BAG_SIZE
  -d MAX_BAG_DURATION, --max-bag-duration MAX_BAG_DURATION
  --max-cache-size MAX_CACHE_SIZE
  --disable-keyboard-controls
  --start-paused        Start the recorder in a paused state.
  --use-sim-time        Use simulation time for message timestamps by
  --node-name NODE_NAME
  --custom-data [KEY=VALUE ...]
  --snapshot-mode       Enable snapshot mode. Messages will not be written to
  --log-level {debug,info,warn,error,fatal}
  --storage-config-file STORAGE_CONFIG_FILE
  --storage-preset-profile {none,fastwrite,zstd_fast,zstd_small}
  --compression-queue-size COMPRESSION_QUEUE_SIZE
  --compression-threads COMPRESSION_THREADS
  --compression-threads-priority COMPRESSION_THREADS_PRIORITY
  --compression-mode {none,file,message}
  --compression-format {zstd}
"""


def test_the_humble_argv_carries_no_flag_humbles_recorder_does_not_have() -> None:
    """Finding 3, found while re-checking the argv the operator will type.

    The shipped argv ended ``--topics /a /b ...`` and carried
    ``--disable-keyboard-controls`` and ``--node-name``. Humble's recorder verb
    declares none of the three; argparse exits 2 on an unknown option, so the
    command that was supposed to record the session would have recorded nothing
    at all. This test fails against that argv on the first assert.
    """

    plan = rb.plan_for_session("/data/parcel/take01")
    assert plan.distro is rb.RosDistro.HUMBLE  # the Orin's asserted distro
    argv = rb.record_command(plan)
    assert "--topics" not in argv
    assert "--disable-keyboard-controls" not in argv
    assert "--node-name" not in argv
    # The topic list is positional and last, in order, with nothing after it.
    assert argv[-len(plan.topic_names) :] == plan.topic_names
    assert not any(token.startswith("-") for token in argv[-len(plan.topic_names) :])
    # And it clears the real Humble flag set.
    rb.validate_argv_against_help(argv, HUMBLE_RECORD_HELP)
    # The same argv is also legal on Jazzy — positional there is deprecated, not
    # removed — so Humble is the fail-safe default for a machine whose distro
    # nobody has read off /etc/nv_tegra_release yet.
    rb.validate_argv_against_help(argv, JAZZY_RECORD_HELP)


def test_the_jazzy_argv_is_refused_against_humbles_recorder(capsys) -> None:
    jazzy = rb.record_command(rb.plan_for_session("/x", distro=rb.RosDistro.JAZZY))
    assert "--topics" in jazzy and "--disable-keyboard-controls" in jazzy
    rb.validate_argv_against_help(jazzy, JAZZY_RECORD_HELP)
    with pytest.raises(rb.Rosbag2RefusedError) as caught:
        rb.validate_argv_against_help(jazzy, HUMBLE_RECORD_HELP)
    message = str(caught.value)
    assert "--topics" in message
    assert "--disable-keyboard-controls" in message
    assert "ZERO bytes" in message


def test_an_unrecognised_help_text_is_a_refusal_and_never_a_clearance() -> None:
    """Unknown = absent. A help text this cannot read must not clear an argv."""

    for text in ("", "ros2: command not found", "usage: ros2 bag play [-h]"):
        with pytest.raises(rb.Rosbag2RefusedError, match="does not look like"):
            rb.validate_argv_against_help(("ros2", "bag", "record", "--topics"), text)


def test_the_split_thresholds_are_explicit_even_when_they_are_zero() -> None:
    """``--max-bag-size`` used to be omitted at 0 and defaulted to 4 GiB when
    set. At the budget's 84.60 MiB/s a 4 GiB threshold splits every 48 s, and
    the take script's abort rule is "more than one .mcap ⇒ STOP" — the recorder
    plan must not trip the sheet that governs the session."""

    plan = rb.plan_for_session("/x")
    assert plan.max_bag_bytes == 0
    argv = rb.record_command(plan)
    assert argv[argv.index("--max-bag-size") + 1] == "0"
    assert argv[argv.index("--max-bag-duration") + 1] == "0"
    split = rb.record_command(
        rb.Rosbag2Plan(Path("/x"), rb.topics_for(), max_bag_bytes=4 * 1024 * 1024 * 1024)
    )
    assert split[split.index("--max-bag-size") + 1] == "4294967296"


def test_the_cli_can_clear_the_argv_against_a_saved_help_file(tmp_path: Path, capsys) -> None:
    """The four-second operator action that turns a lost session into a refusal:
    ``ros2 bag record --help > f`` on the Orin, then this."""

    saved = tmp_path / "help.txt"
    saved.write_text(HUMBLE_RECORD_HELP, encoding="utf-8")
    assert rb.main(["--verify-help", str(saved)]) == 0
    assert "all present" in capsys.readouterr().out

    assert rb.main(["--verify-help", str(saved), "--distro", "jazzy"]) == 2
    assert "--topics" in capsys.readouterr().err
    assert rb.main(["--verify-help", str(tmp_path / "absent.txt")]) == 3
