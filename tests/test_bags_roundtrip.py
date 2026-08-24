"""Roundtrip and oracle-isolation tests for parcel_robot.bags (K2′)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parcel_robot.bags.recorder import BagRecorder
from parcel_robot.bags.replayer import BagReplayer
from parcel_robot.bags.schema import SCHEMA_VERSION, BagSchemaError, reject_privileged_fields


def _record_sample(bag_dir: Path) -> BagRecorder:
    recorder = BagRecorder(
        bag_dir,
        bag_id="sim-bag-test-001",
        source="sim",
        topics=["lidar/scan", "odom/se2", "uwb/state", "camera/color/meta"],
    )
    recorder.record(
        "lidar/scan",
        {
            "angle_min_rad": -2.356,
            "angle_max_rad": 2.356,
            "angle_increment_rad": 0.004,
            "ranges_m": [1.2, 1.5, 0.8],
            "frame_rate_hz": 10.0,
        },
        source="sim.lidar",
        source_timestamp_ns=1_000_000,
        received_monotonic_ns=1_100_000,
        frame_id="lidar_link",
        calibration_id="sim-lidar-v0",
    )
    recorder.record(
        "odom/se2",
        {"x_m": 0.1, "y_m": 0.0, "yaw_rad": 0.05, "vx_mps": 0.2, "vy_mps": 0.0, "wz_rps": 0.0},
        source="sim.odom",
        source_timestamp_ns=1_050_000,
        received_monotonic_ns=1_150_000,
        frame_id="odom",
    )
    recorder.record(
        "uwb/state",
        {
            "bearing_rad": 0.12,
            "range_m": 2.4,
            "quality": 0.7,
            "multipath_suspect": False,
        },
        source="sim.uwb_noise_model",
        source_timestamp_ns=1_080_000,
        received_monotonic_ns=1_180_000,
        frame_id="base_link",
        provenance=["uwb_noise_model_v0"],
    )
    recorder.record(
        "camera/color/meta",
        {
            "width_px": 1280,
            "height_px": 720,
            "fx": 644.0,
            "fy": 644.0,
            "cx": 640.0,
            "cy": 360.0,
            "mount_height_m": 0.35,
            "encoding": "rgb8",
            "blob_ref": None,
        },
        source="sim.camera_d455_shaped",
        source_timestamp_ns=1_090_000,
        received_monotonic_ns=1_190_000,
        frame_id="camera_color_optical_frame",
        calibration_id="d455-intrinsics-nominal",
    )
    recorder.close()
    return recorder


def test_roundtrip_preserves_messages_and_manifest(tmp_path: Path) -> None:
    bag_dir = tmp_path / "bag"
    recorder = _record_sample(bag_dir)
    replayer = BagReplayer(bag_dir)

    assert replayer.manifest["schema_version"] == SCHEMA_VERSION
    assert replayer.manifest["bag_id"] == "sim-bag-test-001"
    assert replayer.manifest["source"] == "sim"
    assert replayer.manifest["hardware_claims"] is False
    assert replayer.manifest["agent_path_excludes_oracle"] is True
    assert replayer.manifest["message_count"] == 4
    assert "clocks" in replayer.manifest
    assert "frames" in replayer.manifest
    assert replayer.does_not_prove
    assert all(isinstance(item, str) and item for item in replayer.does_not_prove)

    messages = replayer.messages()
    assert [m["topic"] for m in messages] == [
        "lidar/scan",
        "odom/se2",
        "uwb/state",
        "camera/color/meta",
    ]
    assert messages[0]["envelope"]["sequence"] == 0
    assert messages[3]["payload"]["mount_height_m"] == 0.35
    assert messages[2]["payload"]["range_m"] == 2.4

    # Second open is deterministic.
    again = BagReplayer(bag_dir)
    assert again.digest() == replayer.digest()
    assert again.messages() == messages
    assert recorder.message_count == 4


def test_rejects_privileged_oracle_fields_on_record(tmp_path: Path) -> None:
    recorder = BagRecorder(
        tmp_path / "oracle-bag",
        bag_id="bad-oracle",
        topics=["lidar/scan"],
    )
    with pytest.raises(BagSchemaError, match="privileged oracle field"):
        recorder.record(
            "lidar/scan",
            {"ranges_m": [1.0], "oracle_pose": {"x": 1.0, "y": 2.0}},
            source="sim.lidar",
            source_timestamp_ns=0,
            received_monotonic_ns=0,
            frame_id="lidar_link",
        )


def test_rejects_nested_ground_truth_on_agent_path() -> None:
    with pytest.raises(BagSchemaError, match="ground_truth"):
        reject_privileged_fields(
            {"detections": [{"label": "person", "ground_truth": True}]},
            path="payload",
        )


def test_replayer_rejects_bag_with_oracle_payload(tmp_path: Path) -> None:
    bag_dir = tmp_path / "poison"
    recorder = BagRecorder(bag_dir, bag_id="poison", topics=["odom/se2"])
    recorder.record(
        "odom/se2",
        {"x_m": 0.0, "y_m": 0.0, "yaw_rad": 0.0},
        source="sim.odom",
        source_timestamp_ns=0,
        received_monotonic_ns=0,
        frame_id="odom",
    )
    recorder.close()

    # Tamper after close: inject privileged field into JSONL.
    messages_path = bag_dir / "messages.jsonl"
    poisoned = (
        '{"topic":"odom/se2","envelope":{"schema_version":1,"evidence_id":"x",'
        '"source":"sim","source_timestamp_ns":0,"received_monotonic_ns":0,'
        '"sequence":0,"frame_id":"odom","scene_revision":0,'
        '"expires_monotonic_ns":1,"calibration_id":"x","provenance":[]},'
        '"payload":{"x_m":0.0,"privileged_pose":[1,2,3]}}\n'
    )
    messages_path.write_text(poisoned, encoding="utf-8")
    manifest = bag_dir / "manifest.json"
    text = manifest.read_text(encoding="utf-8").replace(
        '"message_count": 1', '"message_count": 1'
    )
    # Keep count at 1; just ensure file exists.
    manifest.write_text(text, encoding="utf-8")

    with pytest.raises(BagSchemaError, match="privileged"):
        BagReplayer(bag_dir).messages()


def test_undeclared_topic_rejected(tmp_path: Path) -> None:
    recorder = BagRecorder(
        tmp_path / "topics",
        bag_id="topics-only",
        topics=["imu/data"],
    )
    with pytest.raises(BagSchemaError, match="not declared"):
        recorder.record(
            "lidar/scan",
            {"ranges_m": []},
            source="sim",
            source_timestamp_ns=0,
            received_monotonic_ns=0,
            frame_id="lidar_link",
        )
