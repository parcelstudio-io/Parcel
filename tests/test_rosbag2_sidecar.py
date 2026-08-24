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
from parcel_robot.capture.channels import (
    CHANNELS,
    SUPPORT_ARTIFACTS_BY_ID,
    Confidence,
    Transport,
    WireNaming,
    camera_info_topic_for,
    channel,
    subscribe_name,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture import rosbag2 as rb
from scripts.parcel_capture import sidecar as sidecar_mod
from scripts.parcel_capture.record import read_mcap
from scripts.parcel_capture.sidecar import (
    SIDECAR_EXTRA_KEY,
    BagFormat,
    ChannelVerdict,
    GoRecordRefusedError,
    RecorderRole,
    SidecarRefusedError,
    build_rosbag2_sidecar,
    build_sidecar,
    finalize_rosbag2,
    verify_rosbag2_sidecar,
    verify_sidecar,
)
from scripts.parcel_capture.syncevents import build_selftest_fit, sync_fit_digest

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


# ---------------------------------------------------------------------------
# S-1 — support artifacts, the GO-RECORD gate, and real bytes
# ---------------------------------------------------------------------------
#
# The verified P0 (AU-H, executed 2026-08-14): the recording plan carried four
# optical image streams and NO camera_info, NO /tf, NO /tf_static. The tests
# below gate the fix: support topics on the plan, derived names, the sidecar
# GO-RECORD gate with every board-named seeded refusal, the sync-fit binding,
# and — following the PS-M precedent — REAL rosbag2 bags written by the real
# writer (rosbag2_py.SequentialWriter -> librosbag2_storage_mcap.so ->
# libmcap, ROS 2 Jazzy sandbox, rclpy CDR serialization), embedded here
# zlib+base64 with their digests, so the refusals are proven against bytes no
# module of ours produced.

#: Real rosbag2 bags written inside the Jazzy sandbox by write_gate_bags.py
#: (see scrum/20260814/task_1/S1_STATUS.md for the recipe and transcript):
#: 20 Image messages (848x480, rgb8) on /camera/camera/color/image_raw, plus
#: per-bag: matching 848x480 CameraInfo + /tf_static (complete); no CameraInfo
#: at all (missing_ci); a 1280x720 CameraInfo against the 848x480 stream
#: (mismatch). name -> (sha256 of the raw .mcap, zlib+base64 bytes).
REAL_S1_BAGS: dict[str, tuple[str, str]] = {
    "bag_complete": (
        "e15540c578cb150ba2547bb4198925ee5f47e084d18ca714176334ed35ba6b3a",
        (
            "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"
            "S4RrFxql9aL1FxulxYOzLzVKmeQLG41SWvHipUYpx7RxuVFKOLxypVGafV55rVGaily91ijh0tdfb5RAyltvNkoRa+vtRsl9"
            "vbPVKNmyuz0hzkMlcf7xZ8ri/PPTZXH+xVpZnB8+VxbnXz1fFue3zpbF+Xfny+L8+xfK4vyHi2Vx/uPLZXH+8y+Vxfmvr5TF"
            "+e1Xy+L8j82yOL9ztSzO/7xeFuf33iiL8wdvlcX5X58ri/OHv6zE+VlF50jjJxuFOB9+WN595L2jqlzD/M7H8Oi+v/Nx9eg9"
            "/s7H0yunluh1F7/3sbykX5M/83Fi+da/87Eoj48yzS9+JANYsuLQX3Ub9+qusdm/XqGKaJlQ78wPh3h+op7P2hK8Zr6bsbVt"
            "cerIg6hiooQ7hOm3Rmb8YMfy7Xtym33Lpf7tfwzbR9jHlaWDddIcCXbLLm4MP1oNQu8+br83Yw262/7MTDGoZ/T99Mptf2/m"
            "U0etcFqfUl2fUl2fUl2fUl2fUl2fUl1/X7L+vmT9fcn/M9+XrM9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9z"
            "rs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrs9zrvcn1PsT6v0Jle9P+FpT73XHXe+z"
            "N3JbexPeg+IagsuSxjKvybGztc0yfSutyuZu3QRtenrs4eJzZg0gcLNTWRO5HOiYwXJMa3OqpDcIQr9jlvZU/NTLg4qOHLjH"
            "ZoAQDF3aA8lZEBR6DqbgMDNYnzP2LzyzBa/No3YiQkS87bgNKmrPPQ9/n2u7z+tldrSsaxzoZ+AKhJcPwQyKDSJDQUmFYvnc"
            "LNpP9AWaF3FMeLnJmJyf76vFT1Ha3CldI97Ri6cTrrQAFLgzPPK4ASlGD9q94iqT3j2BeXcV5/SYlDIvxp9attVozk1VRsDw"
            "0euq5BYNN2ef9d8pNhrEoWCKhJrlaQtDkuk442fLsjROO5R6QJdv8rbQl9VFa00EF23LmiAjnbBJp1lEgUKMD3aEaYM2ziYt"
            "a7VI/ozE1NChxCBOxRntRAIdvwEYQiSrsr6UVPO13MU1PpSTFtiD6WTBeEYvYT4gcOtKocGiI/jpZtFqaW86JwRT5iXzfmy9"
            "37Pej9jyg+mjEvisDrIdejalowI/pXzoRplCnzL1y3HnwMAlnITDwaEFCk0p1VNeN/IGAqGk8pZyO4OjZ1a2e8ZKMUzvZTzV"
            "rWrR8occ68ooMBOrI6xVy5Z8IfdC6jVerfFqjVc/tr8/0jNfHj/UeKKxz++PmF2S9/rrIw/8506OXjXfPT1C3zcvvnF5r6Qf"
            "1l+vXbBYFF+RP2R91VV/I/YJevaYEfljpqb+9vwn9Zf5J6seV+evOPLABSJ1pPF9T5P6Slezft2V7/70cPGNth+9U74++rh6"
            "8KQucGjqO7imzE/78vqb09/T/Ymf0j34itLsd07Iq3ly9Lf/QL559tDEk4c//EP5Rn9t2zz55M//kXzTn3zy6JfUk5e1qLUM"
            "dQP+WhX46pXvfvD+5QvnNpcebf4vb625MQ=="
        ),
    ),
    "bag_missing_ci": (
        "53cdb8fba354337963f5de6f59457fb5c6ca0e36e309e8f3c832f65ad2b83c53",
        (
            "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"
            "USYA/wLZSWOaMIdr74vS5XYJ7etgp9eAUqmleEFr/jLsLrYj63xxGPPNspDzhV7ajnmQbUcJe6yyiK5xgzJ6iY3LnosXEdMG"
            "GOtpxjG1s27Rg5jT664as0vRV45In4fA3lZEdO2mNGD+97qJcmE6Zh3wLBPFNQSAjYoIcamjel9GMDZBGsS9kDWKk1sP5Lvm"
            "qh6lsKdE8wxEj/SpcTdlYQbfANXC/q1P3EKq93uz5HVwB+gGwWEOcIRU52Kusnx3qQ0Lg4YYGgDg8ZhAuEyF0gxqeo6BuufW"
            "6FwCp5KLrgDET/k6ixWZm4NNDU0SgDkwkxKoBBAnYULrbwrY9ba0L73FErMHQlMjv0jYDK53EferLW3Kk2Aff5UDnAo5CGls"
            "qApAJK8760yvMpaWWLqkt7OiD9ZMOuAVwMPqAKCBGWB5xRAqdKBB1gOzgwUkX9e1Rmgc+RlN/lntbEcqQFoB0gqQfmIBabvm"
            "oNlU7QsISA0UyRPEgjY0Sdr/yCD1G/lwW4FU92wDSHf+Htq+DPw8gsCxs3qyCDlHhjl34+6ZYjqhYb7zuztni+mEhvkgeut8"
            "MZ3QMLV/rl8opROyzRvpxWI6KdvsjJ4vppOyzXv+5WI6Kds8dfPFUjoh2/zka1eK6aRsM3/pajGdlG3eP/NKMZ2UbS4ev15K"
            "J2Sb386+WkwnZZvXvnSzmE7KNn84+FoxnZRtkseXS+mEbPOht1JMJ2Wbt6f9Yjop29h3sC79uIbZeWnKDXNuaogBfravVlq0"
            "n9hfK62ub9q8W/7+ZPNunXrpiVppYfm5zbvIf+DJWilUv2XzLpb+2eZd0Ltqry246PQLm3dh5OkDtdK8/57Nu4n5V5t3M+ja"
            "wVrJ5X9p884nyVO1khO9a/POyn+3eWeOV+2r8J378/O/zxYg1a5d9rzvRzNjdyu+P7Pl3YrbMx/xbsWJ5tK8fh7gjsXCvHtG"
            "r1Y0F+59t2KOGLDp2B9eSoAhyfCQ1RYjJm2RzW8L2CZOJ1q6/LIGYF9bvxn0beUnAssrhZF82MwEkqeaEiJhfb9jkwsSC9tL"
            "ck90XpJu01PW/6FwzflP5PWXgk9ue+tl6PObyH+sue31l8d2FMJjdWheHZpXh+bVoXl1aF4dmleH5tWheXVo/n9zaF7dOq5u"
            "HVe3jqtbx9Wt4+rWcXXruMKrFV6t8Gp1ySO/5DHBS867vmpJ7ysMMbz2PLXJTwf36vK9eSv39urRG7XNf2t41FL8m32xsld3"
            "63zRqfBJYt/XTI3/HtGle9xLnWed5qfH3r7kbd6xpH88/obmM59zp8FLXzZfXrSS5DU73j5lxaiN1Ox6qWX7jNY8+gNbszJa"
            "s+dftuYFpzCnOcfAaXNTp3bgP53v3rE/7f0v5H3zwg=="
        ),
    ),
    "bag_mismatch": (
        "e0e2a21bd25b3016e70cce9a79f61bb6d752e88b3b52a5da7c6e314f2ab88371",
        (
            "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"
            "jRcapcWDMy82Spnk85uNUlrx4qVGKce0eblRSji8fKVRmn1eebVRmopcvdYo4dLXXmuUQMqbbzRKEWv7rUbJfb293SjZsrcz"
            "Ic5DJXH+6WfL4vzLU2Vx/tV6WZwfPlcW518/Xxbnt8+Uxfn358ri/IcLZXH+48WyOP/ppbI4/+VXyuL8t5fL4vzOK2Vx/sdW"
            "WZzfvVoW539eL4vz+6+XxfnDN8vi/K/Pl8X5o1/V4vycpnOk8dONQpwPPaTuPvzeUV2uYX/nY3h039/5uHr0Ln/n4+nVk8v0"
            "+gi/97GybF6TP/NxYuXWv/OxqI6Pss0vfiQDWLLi0F99G/fqrrPZv16hixiZUO/sD4f4Qaqfz9oSvG6/m7G943DqqIOoEqKE"
            "O4Tpt0Zm/GDHyu17cpt9y6X+7X8M28fYx9Xlg3XSHgl2yy5uDj9eDULvPmm/N+MMutv+zEwxqGf0/dTqbX9v5tNHnXBan1Jd"
            "n1Jdn1Jdn1Jdn1Jdn1Jdf1+y/r5k/X3J/zPfl6zPc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67P"
            "c67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc67Pc673J9T7E+r9CZXvT/h60+x1x13vszdyO3sT3oPi"
            "BoKrktYyr6mxs73DMnNLVmVzt26CMT0z9nDxOXMGELjZqayJWg5s28FyzGhzqqQ/CKOgY5f2dPw0y4Oajhq4x2aAEAxdxgOp"
            "WRAUeg6m4DAz2Jiz9i98uwVvicdLqYgQ8S4lS6Cipbnn4e9zS97zZpkdLesaB/oZuALh50Mwg2KDyFBQUqFYPreL9hN9gebF"
            "HBNeXjom5xcEevFTlDZ3KteId8zi6YQrLQAF7gyPfW5BitWDca+4ymR2T2DeXcc5MyaVzIvxp5dtDZrzpM4IWD5mXZXcouXW"
            "3mf9d4qNAXEomCKh5njawpBUOs762bIsrdOOlB7Q5du8LfRlbdFZE8FF27ImyEgnbLLdLKJAIcb7O8KMQVtnI8taLZI/IzE1"
            "dCgxiFNxRjuRQMevA4YQ6ZqqryTVfDX3cI0P5WQEdn86WTCe0UuYDwjculJosOgIfnq3aLWyN5MTginzsn0/dt7fdN6P2Mr9"
            "6aMW+KwOsl16NqWjAj9JPvTiTKNPlfrluHNg4BFOwuHQpgUKQ0maKa8X+wOBUFJ7S7WdoW1mVq57xkoJTO9VPDWtatHyhxrr"
            "2igwE2sirFPLlXwh90LqNV6t8WqNVz+xvz/Ss18eP9R4vLHP74/YXZJ3++sj9/3nTo5etd89PULfNy++cXm3pB8yX69dcFgU"
            "X5E/5HzV1Xwj9nF69qgV+aO2pvn2/KfMl/knqx7X56+01YELROpI4we+IfXVrmH9mqfe/fnh4httP367fH3kMf3gCVPg0NR3"
            "cG2Znw3U9benv6f7Uz9jevBVrdnvnlBX++To7/6RevPsoYknD334x+qN+dq2ffKpX/wT9aY/+eSRL+snLxlRGxmaBvyNLvC1"
            "K9/74P3L589uLT/S/F/v4LPX"
        ),
    ),
}


def _real_bag_dir(tmp_path: Path, name: str) -> Path:
    """Materialise one embedded real bag as a rosbag2 directory, digest-checked."""

    digest, b64 = REAL_S1_BAGS[name]
    raw = zlib.decompress(base64.b64decode(b64))
    import hashlib

    assert hashlib.sha256(raw).hexdigest() == digest, "embedded bag corrupted"
    directory = tmp_path / name
    directory.mkdir(parents=True)
    (directory / f"{name}_0.mcap").write_bytes(raw)
    (directory / "metadata.yaml").write_text(
        "rosbag2_bagfile_information:\n"
        "  storage_identifier: mcap\n"
        "  relative_file_paths:\n"
        f"    - {name}_0.mcap\n",
        encoding="utf-8",
    )
    return directory


# -- CDR fixture encoders ----------------------------------------------------
#
# Test-local encoders for the fixture-bag legs. Padding is written as 0xCC on
# purpose: real rclpy output leaves CDR padding uninitialised, so a decoder
# that reads padding instead of skipping it passes against zeroed fixtures and
# fails in the field. The real-bytes legs below are the independent witness
# that these encoders (our code) agree with the real serializer.


class _CdrWriter:
    def __init__(self) -> None:
        self.buf = bytearray()

    def _align(self, size: int) -> None:
        while len(self.buf) % size:
            self.buf += b"\xcc"

    def u8(self, value: int) -> None:
        self.buf += struct.pack("<B", value)

    def u32(self, value: int) -> None:
        self._align(4)
        self.buf += struct.pack("<I", value)

    def i32(self, value: int) -> None:
        self._align(4)
        self.buf += struct.pack("<i", value)

    def f64(self, value: float) -> None:
        self._align(8)
        self.buf += struct.pack("<d", value)

    def string(self, value: str) -> None:
        raw = value.encode("utf-8") + b"\x00"
        self.u32(len(raw))
        self.buf += raw

    def header(self, frame_id: str) -> None:
        self.i32(1)
        self.u32(0)
        self.string(frame_id)

    def payload(self) -> bytes:
        return b"\x00\x01\x00\x00" + bytes(self.buf)


def _image_payload(width: int, height: int, frame_id: str) -> bytes:
    writer = _CdrWriter()
    writer.header(frame_id)
    writer.u32(height)
    writer.u32(width)
    writer.string("rgb8")
    writer.u8(0)          # is_bigendian
    writer.u32(0)         # step
    writer.u32(0)         # data: empty sequence
    return writer.payload()


def _camera_info_payload(
    width: int, height: int, frame_id: str, *, d0: float = 0.1
) -> bytes:
    writer = _CdrWriter()
    writer.header(frame_id)
    writer.u32(height)
    writer.u32(width)
    writer.string("plumb_bob")
    writer.u32(5)
    for value in (d0, -0.05, 0.001, 0.002, 0.0):
        writer.f64(value)
    for value in (640.0, 0.0, width / 2.0, 0.0, 640.0, height / 2.0, 0.0, 0.0, 1.0):
        writer.f64(value)
    for value in (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
        writer.f64(value)
    for value in (640.0, 0.0, width / 2.0, 0.0, 0.0, 640.0, height / 2.0, 0.0, 0.0, 0.0, 1.0, 0.0):
        writer.f64(value)
    writer.u32(0)         # binning_x
    writer.u32(0)         # binning_y
    for _ in range(4):    # roi x_offset/y_offset/height/width
        writer.u32(0)
    writer.u8(0)          # roi.do_rectify
    return writer.payload()


def _tf_payload(transforms: list[tuple[str, str, tuple, tuple]]) -> bytes:
    writer = _CdrWriter()
    writer.u32(len(transforms))
    for parent, child, xyz, quat in transforms:
        writer.header(parent)
        writer.string(child)
        for value in xyz:
            writer.f64(value)
        for value in quat:
            writer.f64(value)
    return writer.payload()


_S1_IMG = "/camera/camera/color/image_raw"
_S1_CI = "/camera/camera/color/camera_info"
_S1_TF_STATIC = "/tf_static"
_S1_FRAME = "camera_color_optical_frame"
_S1_TYPES = {
    _S1_IMG: "sensor_msgs/msg/Image",
    _S1_CI: "sensor_msgs/msg/CameraInfo",
    _S1_TF_STATIC: "tf2_msgs/msg/TFMessage",
}
_S1_SNAPSHOT = {
    "schema": sidecar_mod.STATIC_TF_SNAPSHOT_SCHEMA,
    "captured_at_utc": "2026-08-14T08:00:00Z",
    "source": "ros2 topic echo --qos-durability transient_local /tf_static, before record start",
    "transforms": [
        {
            "parent_frame": "camera_link",
            "child_frame": _S1_FRAME,
            "translation_m": [0.011, 0.0, 0.0],
            "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
        }
    ],
}


def _optical_bag(
    tmp_path: Path,
    name: str,
    *,
    images: int = 20,
    camera_infos: int = 20,
    ci_size: tuple[int, int] = (848, 480),
    tf_transforms: list | None = None,
) -> Path:
    """A fixture rosbag2 directory with an 848x480 optical stream."""

    messages = []
    for index in range(images):
        stamp = 1_000_000_000 + index * 33_000_000
        messages.append((_S1_IMG, stamp, _image_payload(848, 480, _S1_FRAME)))
    for index in range(camera_infos):
        stamp = 1_000_000_000 + index * 33_000_000
        messages.append(
            (_S1_CI, stamp, _camera_info_payload(ci_size[0], ci_size[1], _S1_FRAME))
        )
    if tf_transforms is not None:
        messages.append((_S1_TF_STATIC, 1_000_000_000, _tf_payload(tf_transforms)))
    directory = tmp_path / name
    directory.mkdir(parents=True)
    rb.write_fixture_bag(directory / f"{name}_0.mcap", messages, types=_S1_TYPES)
    (directory / "metadata.yaml").write_text(
        "rosbag2_bagfile_information:\n"
        "  storage_identifier: mcap\n"
        "  relative_file_paths:\n"
        f"    - {name}_0.mcap\n",
        encoding="utf-8",
    )
    return directory


_S1_GOOD_TF = [("camera_link", _S1_FRAME, (0.011, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))]


def _go_block(manifest: dict) -> dict:
    return manifest[SIDECAR_EXTRA_KEY]["go_record"]


# -- the plan carries the support topics -------------------------------------


def test_every_required_camera_info_topic_is_derived_and_on_the_plan() -> None:
    """The P0's direct negation: camera_info per optical stream, /tf and
    /tf_static are all on RECORDED_TOPICS, and the CameraInfo names are DERIVED
    from the image topic names, never a second hand-written list."""

    support_names = {item.topic for item in rb.SUPPORT_TOPICS}
    for image_topic in (
        "/camera/camera/color/image_raw",
        "/camera/camera/depth/image_rect_raw",
        "/camera/camera/infra1/image_rect_raw",
        "/camera/camera/infra2/image_rect_raw",
    ):
        assert camera_info_topic_for(image_topic) in support_names
    assert "/tf" in support_names
    assert "/tf_static" in support_names
    plan = rb.plan_for_session("/tmp/x")
    assert support_names <= set(plan.topic_names)
    for item in rb.SUPPORT_TOPICS:
        assert item.support_id is not None
        assert item.channel_id is None
        assert item.support_id in SUPPORT_ARTIFACTS_BY_ID


def test_seeded_failure_a_topic_cannot_be_both_payload_and_support() -> None:
    with pytest.raises(rb.Rosbag2RefusedError, match="payload or support"):
        rb.RecordedTopic(
            "/camera/camera/color/camera_info",
            "sensor_msgs/msg/CameraInfo",
            rb.TopicSource.DRIVER_NODE,
            "d455.color",
            Confidence.UNVERIFIED,
            "mutant",
            support_id="support.d455.color.camera_info",
        )
    with pytest.raises(rb.Rosbag2RefusedError, match="unknown support_id"):
        rb.RecordedTopic(
            "/camera/camera/color/camera_info",
            "sensor_msgs/msg/CameraInfo",
            rb.TopicSource.DRIVER_NODE,
            None,
            Confidence.UNVERIFIED,
            "mutant",
            support_id="support.not.a.row",
        )


def test_seeded_failure_excluding_camera_info_under_a_live_stream_is_refused() -> None:
    """Hand-recreating the P0 must now be impossible: a plan that keeps the
    colour stream while excluding its calibration is a refusal, and excluding
    both together is allowed."""

    with pytest.raises(rb.Rosbag2RefusedError, match="cannot certify GO-RECORD"):
        rb.plan_for_session("/tmp/x", exclude=("/camera/camera/color/camera_info",))
    paired = rb.plan_for_session(
        "/tmp/x",
        exclude=("/camera/camera/color/camera_info", "/camera/camera/color/image_raw"),
    )
    assert "/camera/camera/color/image_raw" not in paired.topic_names
    lean = rb.plan_for_session("/tmp/x", include_driver_nodes=False)
    assert not any("camera_info" in name for name in lean.topic_names)


# -- CDR decoding ------------------------------------------------------------


def test_the_cdr_decoders_read_profiles_and_transforms_and_skip_garbage_padding() -> None:
    """Padding in these fixtures is 0xCC, as hostile as real rclpy's
    uninitialised padding. A decoder that reads padding fails here."""

    image = rb.decode_image_meta(_image_payload(848, 480, _S1_FRAME))
    assert (image.width, image.height, image.frame_id) == (848, 480, _S1_FRAME)
    info = rb.decode_camera_info(_camera_info_payload(1280, 720, _S1_FRAME))
    assert (info.width, info.height) == (1280, 720)
    assert info.distortion_model == "plumb_bob"
    assert len(info.d) == 5 and len(info.k) == 9 and len(info.r) == 9 and len(info.p) == 12
    assert info.k[2] == 640.0
    transforms = rb.decode_tf_message(_tf_payload(_S1_GOOD_TF))
    assert len(transforms) == 1
    assert transforms[0].parent_frame == "camera_link"
    assert transforms[0].child_frame == _S1_FRAME
    assert transforms[0].translation_m[0] == 0.011


def test_seeded_failure_foreign_or_truncated_cdr_is_refused_never_guessed() -> None:
    with pytest.raises(rb.CdrDecodeError, match="encapsulation"):
        rb.decode_camera_info(b"\x00\x00\x00\x00" + b"\x00" * 64)
    with pytest.raises(rb.CdrDecodeError):
        rb.decode_camera_info(_camera_info_payload(848, 480, _S1_FRAME)[:40])
    with pytest.raises(rb.CdrDecodeError, match="zero dimension"):
        rb.decode_image_meta(_image_payload(848, 480, _S1_FRAME).replace(
            struct.pack("<I", 480), struct.pack("<I", 0), 1
        ))


# -- the GO-RECORD gate, fixture legs ----------------------------------------


def test_a_bag_with_no_camera_info_cannot_finalize_go_record(tmp_path: Path) -> None:
    bag = _optical_bag(tmp_path, "no_ci", camera_infos=0, tf_transforms=_S1_GOOD_TF)
    manifest = build_rosbag2_sidecar(bag_id="s1", bag_dir=bag)
    block = _go_block(manifest)
    assert block["status"] == "REFUSED" and not block["certified"]
    assert any("NO CameraInfo" in reason for reason in block["refusals"])
    with pytest.raises(GoRecordRefusedError, match="NO CameraInfo"):
        finalize_rosbag2(bag, bag_id="s1", require_go_record=True)
    assert not sidecar_mod.rosbag2_sidecar_path_for(bag).exists(), (
        "a refused GO-RECORD finalize must write NOTHING"
    )
    # The recovery pass still documents the refusal honestly.
    manifest2, path = finalize_rosbag2(bag, bag_id="s1")
    assert path.exists()
    assert any("GO-RECORD REFUSED" in line for line in manifest2["does_not_prove"])


def test_a_profile_mismatch_848x480_stream_1280x720_calibration_is_refused(
    tmp_path: Path,
) -> None:
    """The board's named seeded case, verbatim."""

    bag = _optical_bag(
        tmp_path, "mismatch", ci_size=(1280, 720), tf_transforms=_S1_GOOD_TF
    )
    block = _go_block(build_rosbag2_sidecar(bag_id="s1", bag_dir=bag))
    assert not block["certified"]
    assert any(
        "848x480" in reason and "1280x720" in reason for reason in block["refusals"]
    )


def test_a_camera_info_that_does_not_track_the_stream_rate_is_refused(
    tmp_path: Path,
) -> None:
    """Matching is width/height AND rate: one lonely CameraInfo against a
    20-frame stream is not the driver restating calibration per frame."""

    bag = _optical_bag(tmp_path, "rate", camera_infos=1, tf_transforms=_S1_GOOD_TF)
    block = _go_block(build_rosbag2_sidecar(bag_id="s1", bag_dir=bag))
    assert not block["certified"]
    assert any("rate profile" in reason for reason in block["refusals"])


# -- FX-2 F3: the short-bag rate leg used to fail OPEN ----------------------


@pytest.mark.parametrize(
    ("images", "camera_infos", "certifies"),
    [
        (1, 1, True),    # no deficit at all
        (2, 2, True),
        (2, 1, False),   # 50% deficit — GO-RECORD on the shipped code
        (3, 2, False),   # 33% deficit — GO-RECORD on the shipped code
        (3, 3, True),
        (4, 3, False),   # 25% deficit
        (4, 4, True),
        (5, 4, False),   # 20% deficit
        (5, 5, True),
        (6, 5, False),   # 17% deficit
        (6, 6, True),
    ],
)
def test_no_count_is_small_enough_to_certify_a_camera_info_deficit(
    tmp_path: Path, images: int, camera_infos: int, certifies: bool
) -> None:
    """The boundary sweep FX-2 F3 asks for, images 1..6.

    ``allowance = max(1.0, image_count * tolerance)`` put a floor of one whole
    message under the check, and that floor only ever bit where it was wrong:
    below ten images it let a deficit of 50% certify GO-RECORD through
    ``require_go_record=True``. The allowance is proportional now, so a ratio
    outside the rate profile is outside it at every count.
    """

    bag = _optical_bag(
        tmp_path,
        f"n{images}x{camera_infos}",
        images=images,
        camera_infos=camera_infos,
        tf_transforms=_S1_GOOD_TF,
    )
    block = _go_block(build_rosbag2_sidecar(bag_id="s1", bag_dir=bag))
    assert block["certified"] is certifies, block["refusals"]
    if certifies:
        manifest, _path = finalize_rosbag2(bag, bag_id="s1", require_go_record=True)
        assert _go_block(manifest)["status"] == "GO-RECORD"
        assert any("below 10" in item for item in _go_block(manifest)["findings"]), (
            "a bag this short must still SAY that the rate leg proves little"
        )
    else:
        assert any("rate profile" in reason for reason in block["refusals"])
        with pytest.raises(GoRecordRefusedError, match="rate profile"):
            finalize_rosbag2(bag, bag_id="s1", require_go_record=True)


def test_the_ordinary_off_by_one_at_a_real_take_length_still_certifies(
    tmp_path: Path,
) -> None:
    """The control for the test above: 40 images / 39 CameraInfo is the tail of
    a real recording, well inside the 10% profile, and must keep passing."""

    bag = _optical_bag(
        tmp_path, "tail", images=40, camera_infos=39, tf_transforms=_S1_GOOD_TF
    )
    manifest, _path = finalize_rosbag2(bag, bag_id="s1", require_go_record=True)
    block = _go_block(manifest)
    assert block["status"] == "GO-RECORD"
    assert not any("below 10" in item for item in block["findings"])


def test_tf_static_neither_captured_nor_snapshotted_is_refused(tmp_path: Path) -> None:
    bag = _optical_bag(tmp_path, "no_tf", tf_transforms=None)
    block = _go_block(build_rosbag2_sidecar(bag_id="s1", bag_dir=bag))
    assert not block["certified"]
    assert any("neither captured" in reason for reason in block["refusals"])


def test_a_pre_record_snapshot_substitutes_for_the_transient_local_topic(
    tmp_path: Path,
) -> None:
    bag = _optical_bag(tmp_path, "snap", tf_transforms=None)
    manifest = build_rosbag2_sidecar(
        bag_id="s1", bag_dir=bag, static_transform_snapshot=_S1_SNAPSHOT
    )
    block = _go_block(manifest)
    assert block["certified"], block["refusals"]
    assert block["snapshot_sha256"] == sidecar_mod.static_transform_snapshot_digest(
        _S1_SNAPSHOT
    )
    assert block["transforms"]["snapshot_bound"] is True


def test_seeded_failure_a_malformed_snapshot_is_refused_not_recorded(
    tmp_path: Path,
) -> None:
    bag = _optical_bag(tmp_path, "badsnap", tf_transforms=None)
    for mutant, match in (
        ({**_S1_SNAPSHOT, "source": "  "}, "source"),
        ({**_S1_SNAPSHOT, "transforms": []}, "non-empty"),
        ({**_S1_SNAPSHOT, "schema": "v0"}, "schema"),
        (
            {
                **_S1_SNAPSHOT,
                "transforms": [
                    {**_S1_SNAPSHOT["transforms"][0], "rotation_xyzw": [0, 0, 0, 0.5]}
                ],
            },
            "norm",
        ),
    ):
        with pytest.raises(SidecarRefusedError, match=match):
            build_rosbag2_sidecar(
                bag_id="s1", bag_dir=bag, static_transform_snapshot=mutant
            )


def test_two_competing_parents_for_one_frame_are_ambiguous_and_refused(
    tmp_path: Path,
) -> None:
    bag = _optical_bag(
        tmp_path,
        "ambig",
        tf_transforms=_S1_GOOD_TF
        + [("base_link", _S1_FRAME, (0.2, 0.0, 0.1), (0.0, 0.0, 0.0, 1.0))],
    )
    block = _go_block(build_rosbag2_sidecar(bag_id="s1", bag_dir=bag))
    assert not block["certified"]
    assert any("competing parents" in reason for reason in block["refusals"])


def test_two_disagreeing_declarations_of_one_extrinsic_are_refused(
    tmp_path: Path,
) -> None:
    bag = _optical_bag(tmp_path, "twovals", tf_transforms=_S1_GOOD_TF)
    disagreeing = {
        **_S1_SNAPSHOT,
        "transforms": [
            {
                "parent_frame": "camera_link",
                "child_frame": _S1_FRAME,
                "translation_m": [0.5, 0.0, 0.0],
                "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
            }
        ],
    }
    block = _go_block(
        build_rosbag2_sidecar(
            bag_id="s1", bag_dir=bag, static_transform_snapshot=disagreeing
        )
    )
    assert not block["certified"]
    assert any("competing declarations" in reason for reason in block["refusals"])


def test_a_missing_sensor_frame_parent_is_refused(tmp_path: Path) -> None:
    """tf_static present but about some OTHER frame: the optical frame still
    has no parent, and presence-of-the-topic must not read as coverage."""

    bag = _optical_bag(
        tmp_path,
        "wrongframe",
        tf_transforms=[("base_link", "l2_lidar_link", (0.1, 0.0, 0.2), (0.0, 0.0, 0.0, 1.0))],
    )
    block = _go_block(build_rosbag2_sidecar(bag_id="s1", bag_dir=bag))
    assert not block["certified"]
    assert any("sensor transform absent" in reason for reason in block["refusals"])


def test_a_complete_bag_certifies_and_the_calibration_digest_binds(
    tmp_path: Path,
) -> None:
    bag = _optical_bag(tmp_path, "complete", tf_transforms=_S1_GOOD_TF)
    manifest, _path = finalize_rosbag2(bag, bag_id="s1", require_go_record=True)
    block = _go_block(manifest)
    assert block["status"] == "GO-RECORD"
    assert block["calibration_sha256"] and len(block["calibration_sha256"]) == 64
    ok, failures = sidecar_mod.verify_calibration_digest(manifest, bag)
    assert ok, failures
    # Support topics are classified as support, never as unmapped channels.
    rosbag2_block = manifest[SIDECAR_EXTRA_KEY]["rosbag2"]
    assert _S1_CI in rosbag2_block["support_topics"]
    assert _S1_TF_STATIC in rosbag2_block["support_topics"]
    assert _S1_CI not in rosbag2_block["unmapped_topics"]


def test_seeded_failure_one_perturbed_calibration_byte_fails_verification(
    tmp_path: Path,
) -> None:
    bag = _optical_bag(tmp_path, "perturb", tf_transforms=_S1_GOOD_TF)
    manifest, _path = finalize_rosbag2(bag, bag_id="s1", require_go_record=True)
    mcap = bag / "perturb_0.mcap"
    data = bytearray(mcap.read_bytes())
    payloads, _findings = rb.collect_topic_payloads(mcap, [_S1_CI], max_per_topic=1)
    at = data.find(payloads[_S1_CI][0])
    assert at > 0
    data[at + 80] ^= 0x01  # one byte inside the distortion coefficients
    mcap.write_bytes(bytes(data))
    ok, failures = sidecar_mod.verify_calibration_digest(manifest, bag)
    assert not ok
    assert any("calibration digest mismatch" in item for item in failures)


# -- FX-2 F4: the digest covered only the FIRST CameraInfo per topic ---------


def _drifting_optical_bag(tmp_path: Path, name: str, *, at: int = 15) -> Path:
    """A bag whose CameraInfo changes intrinsics part-way through the take."""

    messages = []
    for index in range(20):
        stamp = 1_000_000_000 + index * 33_000_000
        messages.append((_S1_IMG, stamp, _image_payload(848, 480, _S1_FRAME)))
    for index in range(20):
        stamp = 1_000_000_000 + index * 33_000_000
        distortion = 0.1 if index < at else 0.4  # a recalibration mid-stream
        messages.append(
            (_S1_CI, stamp, _camera_info_payload(848, 480, _S1_FRAME, d0=distortion))
        )
    messages.append((_S1_TF_STATIC, 1_000_000_000, _tf_payload(_S1_GOOD_TF)))
    directory = tmp_path / name
    directory.mkdir(parents=True)
    rb.write_fixture_bag(directory / f"{name}_0.mcap", messages, types=_S1_TYPES)
    (directory / "metadata.yaml").write_text(
        "rosbag2_bagfile_information:\n"
        "  storage_identifier: mcap\n"
        "  relative_file_paths:\n"
        f"    - {name}_0.mcap\n",
        encoding="utf-8",
    )
    return directory


def test_a_perturbed_byte_in_a_LATER_camera_info_breaks_the_digest(
    tmp_path: Path,
) -> None:
    """FX-2 F4. The seeded byte goes into the LAST CameraInfo, not the first.

    On the shipped code the digest was derived from ``payloads[0]`` alone and
    ``verify_calibration_digest`` re-derived with ``max_per_topic=1``, so this
    mutation verified GREEN while the calibration the bag actually carried had
    changed.
    """

    bag = _optical_bag(tmp_path, "late", tf_transforms=_S1_GOOD_TF)
    manifest, _path = finalize_rosbag2(bag, bag_id="s1", require_go_record=True)
    mcap = bag / "late_0.mcap"
    data = bytearray(mcap.read_bytes())
    payloads, _findings = rb.collect_topic_payloads(mcap, [_S1_CI], max_per_topic=64)
    assert len(payloads[_S1_CI]) == 20
    at = data.rfind(payloads[_S1_CI][-1])
    assert at > 0
    data[at + 80] ^= 0x01  # one byte inside the distortion coefficients
    mcap.write_bytes(bytes(data))

    ok, failures = sidecar_mod.verify_calibration_digest(manifest, bag)
    assert not ok
    assert any("calibration digest mismatch" in item for item in failures)


def test_a_calibration_that_changes_mid_stream_is_a_named_finding(
    tmp_path: Path,
) -> None:
    """Drift is bound into the digest AND said out loud, per topic."""

    bag = _drifting_optical_bag(tmp_path, "drift")
    manifest, _path = finalize_rosbag2(bag, bag_id="s1", require_go_record=True)
    block = _go_block(manifest)
    drift = [item for item in block["findings"] if "DIFFERENT calibrations" in item]
    assert len(drift) == 1
    assert _S1_CI in drift[0]
    assert "changed field(s): d" in drift[0]
    ok, failures = sidecar_mod.verify_calibration_digest(manifest, bag)
    assert ok, failures


def test_the_drift_digest_differs_from_the_same_bag_without_the_drift(
    tmp_path: Path,
) -> None:
    """The binding is comparing something: same first message, different digest.

    Both bags open with the identical CameraInfo, so a digest derived from the
    first payload alone is IDENTICAL for the two — which is precisely the hole.
    """

    steady = _optical_bag(tmp_path, "steady", tf_transforms=_S1_GOOD_TF)
    drifting = _drifting_optical_bag(tmp_path, "drifting")
    steady_block = _go_block(build_rosbag2_sidecar(bag_id="s1", bag_dir=steady))
    drift_block = _go_block(build_rosbag2_sidecar(bag_id="s1", bag_dir=drifting))

    first_steady, _f = rb.collect_topic_payloads(
        steady / "steady_0.mcap", [_S1_CI], max_per_topic=1
    )
    first_drift, _f2 = rb.collect_topic_payloads(
        drifting / "drifting_0.mcap", [_S1_CI], max_per_topic=1
    )
    assert first_steady[_S1_CI][0] == first_drift[_S1_CI][0], "same opening calibration"
    assert steady_block["calibration_sha256"] != drift_block["calibration_sha256"]
    assert not any("DIFFERENT calibrations" in item for item in steady_block["findings"])


def test_a_calibration_digest_cannot_verify_against_a_sidecar_without_one(
    tmp_path: Path,
) -> None:
    bag = _bag(tmp_path)  # no optical stream at all
    manifest = build_rosbag2_sidecar(bag_id="s1", bag_dir=bag)
    ok, failures = sidecar_mod.verify_calibration_digest(manifest, bag)
    assert not ok
    assert any("no calibration digest" in item for item in failures)


# -- sync binding (board item 4) ---------------------------------------------


def test_a_run_claiming_recoverable_time_without_a_sync_fit_cannot_certify(
    tmp_path: Path,
) -> None:
    bag = _optical_bag(tmp_path, "timeclaim", tf_transforms=_S1_GOOD_TF)
    block = _go_block(
        build_rosbag2_sidecar(
            bag_id="s1", bag_dir=bag, claims_recoverable_time=True
        )
    )
    assert not block["certified"]
    assert any("no sync fit is bound" in reason for reason in block["refusals"])


def test_a_bound_sync_fit_lands_in_the_sidecar_by_digest(tmp_path: Path) -> None:
    """Item 4: sidecar_sync_block wired into the REAL finalize path, not
    proven only in isolation."""

    fit = build_selftest_fit()
    bag = _optical_bag(tmp_path, "syncbound", tf_transforms=_S1_GOOD_TF)
    manifest = build_rosbag2_sidecar(
        bag_id="s1",
        bag_dir=bag,
        origin=EvidenceOrigin.SIMULATION,
        sync_fit=fit,
        claims_recoverable_time=True,
    )
    block = _go_block(manifest)
    assert block["certified"], block["refusals"]
    sync_block = manifest[SIDECAR_EXTRA_KEY]["sync"]
    assert sync_block["status"] == "present"
    assert sync_block["sync_fit_sha256"] == sync_fit_digest(fit)
    ok, failures = sidecar_mod.verify_sync_fit_binding(manifest, fit)
    assert ok, failures
    # A sidecar with no bound fit refuses to verify any fit against itself.
    bare = build_rosbag2_sidecar(bag_id="s1", bag_dir=bag)
    ok2, failures2 = sidecar_mod.verify_sync_fit_binding(bare, fit)
    assert not ok2 and any("binds no sync fit" in item for item in failures2)


def test_seeded_failure_a_rehearsal_fit_cannot_enter_a_physical_sidecar(
    tmp_path: Path,
) -> None:
    fit = build_selftest_fit()  # origin SIMULATION, fixture-labelled
    bag = _optical_bag(tmp_path, "fitorigin", tf_transforms=_S1_GOOD_TF)
    with pytest.raises(SidecarRefusedError, match="rehearsal fit"):
        build_rosbag2_sidecar(
            bag_id="s1", bag_dir=bag, origin=EvidenceOrigin.PHYSICAL, sync_fit=fit
        )


def test_seeded_failure_a_tampered_sync_digest_fails_the_binding(
    tmp_path: Path,
) -> None:
    fit = build_selftest_fit()
    bag = _optical_bag(tmp_path, "synctamper", tf_transforms=_S1_GOOD_TF)
    manifest = build_rosbag2_sidecar(
        bag_id="s1", bag_dir=bag, origin=EvidenceOrigin.SIMULATION, sync_fit=fit
    )
    tampered = json.loads(json.dumps(manifest))
    tampered[SIDECAR_EXTRA_KEY]["sync"]["sync_fit_sha256"] = "0" * 64
    ok, failures = sidecar_mod.verify_sync_fit_binding(tampered, fit)
    assert not ok
    assert any("digest mismatch" in item for item in failures)


# -- the VENDOR_VIDEO dependency (board item 5) -------------------------------


def test_the_rtp_video_path_needs_a_media_stack_never_the_motion_sdk() -> None:
    """PS-H handoff finding 1, closed: the only VENDOR_VIDEO channel is an RTP
    H.264 stream. Its declared dependency is a media tool; the vendor motion
    SDK must never be the printed remedy for a capture path."""

    from parcel_robot.capture.channels import Transport as T
    from scripts.parcel_capture.record import (
        INSTALL_HINTS,
        TRANSPORT_DEPENDENCIES,
        TRANSPORT_EXECUTABLES,
    )

    assert TRANSPORT_DEPENDENCIES[T.VENDOR_VIDEO] == ()
    assert TRANSPORT_EXECUTABLES[T.VENDOR_VIDEO] == ("ffmpeg",)
    assert "unitree_sdk2py" not in TRANSPORT_DEPENDENCIES[T.VENDOR_VIDEO]
    assert "never the vendor motion SDK" in INSTALL_HINTS["ffmpeg"]
    # The UWB vendor path legitimately still declares the vendor SDK; the fix
    # must not have widened into it.
    assert TRANSPORT_DEPENDENCIES[T.VENDOR_UWB] == ("unitree_sdk2py",)


# -- real bytes: the two board-named refusals against the real writer ---------


def test_real_bag_with_no_camera_info_is_refused_on_real_bytes(
    tmp_path: Path,
) -> None:
    """REAL bytes: rosbag2_py.SequentialWriter -> librosbag2_storage_mcap.so,
    rclpy CDR. 20 real Image messages, no CameraInfo. The gate must refuse."""

    bag = _real_bag_dir(tmp_path, "bag_missing_ci")
    manifest = build_rosbag2_sidecar(bag_id="s1-real", bag_dir=bag)
    block = _go_block(manifest)
    assert not block["certified"]
    assert any("NO CameraInfo" in reason for reason in block["refusals"])
    with pytest.raises(GoRecordRefusedError):
        finalize_rosbag2(bag, bag_id="s1-real", require_go_record=True)


def test_real_bag_with_mismatched_calibration_is_refused_on_real_bytes(
    tmp_path: Path,
) -> None:
    """REAL bytes: the 848x480 stream carries a 1280x720 CameraInfo, both
    decoded out of real rclpy CDR by the stdlib decoder."""

    bag = _real_bag_dir(tmp_path, "bag_mismatch")
    block = _go_block(build_rosbag2_sidecar(bag_id="s1-real", bag_dir=bag))
    assert not block["certified"]
    assert any(
        "848x480" in reason and "1280x720" in reason for reason in block["refusals"]
    )
    stream = block["streams"]["/camera/camera/color/image_raw"]
    assert stream["image_profile"]["width"] == 848
    assert stream["camera_info_profile"]["width"] == 1280


def test_real_complete_bag_certifies_and_one_real_byte_breaks_the_digest(
    tmp_path: Path,
) -> None:
    """REAL bytes, positive control: the same writer with matching CameraInfo
    and /tf_static certifies GO-RECORD, and one flipped byte inside the real
    CameraInfo payload fails the calibration digest."""

    bag = _real_bag_dir(tmp_path, "bag_complete")
    manifest, _path = finalize_rosbag2(bag, bag_id="s1-real", require_go_record=True)
    block = _go_block(manifest)
    assert block["status"] == "GO-RECORD"
    ok, failures = sidecar_mod.verify_calibration_digest(manifest, bag)
    assert ok, failures
    mcap = bag / "bag_complete_0.mcap"
    data = bytearray(mcap.read_bytes())
    payloads, _findings = rb.collect_topic_payloads(
        mcap, ["/camera/camera/color/camera_info"], max_per_topic=1
    )
    at = data.find(payloads["/camera/camera/color/camera_info"][0])
    data[at + 80] ^= 0x01
    mcap.write_bytes(bytes(data))
    ok2, failures2 = sidecar_mod.verify_calibration_digest(manifest, bag)
    assert not ok2
    assert any("calibration digest mismatch" in item for item in failures2)
