from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import evals.external.barn_ros2_submission as submission
from evals.external.barn_ros2_adapter import BARN_ROS2_ADAPTER_ID


def test_hook_replacement_preserves_every_byte_outside_documented_function() -> None:
    prefix = (
        "from launch.actions import ExecuteProcess\n\n"
        "def parse_world_idx(value):\n"
        "    return ('world', 10)\n\n"
    )
    old_hook = (
        "def launch_navigation_stack(context, *args, **kwargs):\n"
        "    evaluator_owned_default = True\n"
        "    return [evaluator_owned_default]\n\n"
    )
    suffix = "def generate_launch_description():\n    return 'unchanged'\n"
    source = (prefix + old_hook + suffix).encode()

    output = submission.replace_navigation_hook(
        source,
        expected_sha256=submission._sha256_bytes(source),
    ).decode()

    assert output.startswith(prefix)
    assert output.endswith(suffix)
    assert old_hook not in output
    assert "evals.external.barn_ros2_node" in output
    assert "/opt/parcel/configs/navigation/experiments/barn_grid_v1.yaml" in output
    assert 'os.environ.get("PYTHONPATH")' in output
    assert "os.environ['PYTHONPATH']" in output
    assert output.count("def launch_navigation_stack") == 1


def test_hook_replacement_rejects_wrong_pin_and_ambiguous_structure() -> None:
    source = (
        b"def launch_navigation_stack(context, *args, **kwargs):\n    return []\n\n"
        b"def generate_launch_description():\n    return None\n"
    )
    with pytest.raises(ValueError, match="SHA-256"):
        submission.replace_navigation_hook(source, expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="structure"):
        submission.replace_navigation_hook(b"def generate_launch_description():\n    pass\n")


def test_parse_evaluator_row_accepts_one_real_world0_terminal_result() -> None:
    row = submission.parse_evaluator_row("0 1 0 0 43.1250 0.1572\n")

    assert row.world_idx == 0
    assert row.success == 1
    assert row.collision == 0
    assert row.timeout == 0
    assert row.elapsed_time_s == pytest.approx(43.125)
    assert row.navigation_metric == pytest.approx(0.1572)


def test_launch_progress_classifies_pretrial_liveness_stall_without_a_score() -> None:
    progress = submission.inspect_launch_progress(
        """
        [BARN_Runner]: >>>>>>>>> Waiting for robot to start moving...
        [parcel_barn_ros2_adapter]: Parcel BARN ROS2 adapter ready: scan=/front/scan
        [cmd_vel_bridge]: Passing message from ROS geometry_msgs/msg/TwistStamped to Gazebo
        """
    )

    assert progress == {
        "parcel_startup_observed": True,
        "first_odometry_observed": False,
        "first_scan_observed": False,
        "first_policy_command_observed": False,
        "command_bridge_observed": True,
        "evaluator_waiting_for_motion": True,
        "evaluator_trial_started": False,
        "evaluator_terminal_observed": False,
        "adapter_error_observed": False,
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("6 1 0 0 40.0 0.2\n", "world 0 only"),
        ("0 0 0 0 40.0 0.0\n", "exactly one terminal"),
        ("0 1 1 0 40.0 0.2\n", "exactly one terminal"),
        ("0 0 1 0 40.0 0.2\n", "unsuccessful"),
        ("0 1 0 0 40.0 0.6\n", "bounds"),
        ("0 1 0 0 40.0 0.2\n0 1 0 0 40.0 0.2\n", "exactly one"),
    ],
)
def test_parse_evaluator_row_rejects_scope_or_metric_escalation(
    text: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        submission.parse_evaluator_row(text)


def test_verify_bundle_binds_every_file_and_rejects_tampering(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    adapter = bundle / "evals/external/barn_ros2_adapter.py"
    overlay = bundle / "overlay/BARN_runner.launch.py"
    adapter.parent.mkdir(parents=True)
    overlay.parent.mkdir(parents=True)
    adapter.write_text("adapter\n", encoding="utf-8")
    overlay.write_text("hook\n", encoding="utf-8")
    material = {
        "schema_version": 1,
        "package_kind": submission.PACKAGE_KIND,
        "files_sha256": {
            "evals/external/barn_ros2_adapter.py": submission._sha256(adapter),
            "overlay/BARN_runner.launch.py": submission._sha256(overlay),
        },
        "claims": {
            "official_protocol": False,
            "top_decile_evidence": False,
        },
    }
    document = dict(material)
    document["package_sha256"] = submission._sha256_bytes(submission._canonical_json(material))
    (bundle / "package-manifest.json").write_bytes(
        submission._canonical_json(document, pretty=True)
    )

    verified = submission.verify_bundle(bundle)
    overlay.write_text("tampered\n", encoding="utf-8")

    assert verified.package_sha256 == document["package_sha256"]
    with pytest.raises(ValueError, match="file mismatch"):
        submission.verify_bundle(bundle)


def test_world0_command_mounts_bundle_and_only_documented_hook(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "bundle"
    overlay = bundle_path / "overlay/BARN_runner.launch.py"
    overlay.parent.mkdir(parents=True)
    overlay.write_text("hook\n", encoding="utf-8")
    bundle = submission.Bundle(
        path=bundle_path,
        manifest_path=bundle_path / "package-manifest.json",
        package_sha256="a" * 64,
        launch_overlay_path=overlay,
        files={"overlay/BARN_runner.launch.py": "b" * 64},
    )
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    monkeypatch.setattr(submission, "verify_bundle", lambda path: bundle)
    monkeypatch.setattr(submission, "_validated_rootfs", lambda path: rootfs)

    command = submission.world0_command(
        bundle,
        rootfs=rootfs,
        out_file="parcel_world0.txt",
    )
    rendered = " ".join(command)

    assert "world_idx:=0" in rendered
    assert "world_idx:=6" not in rendered
    assert str(submission.INSTALLED_LAUNCH) in command
    assert command.count("--ro-bind") == 2
    assert "/opt/parcel" in command
    assert "parcel_world0.txt" in rendered


def test_prepare_mode_never_claims_a_metric() -> None:
    source = Path(submission.__file__).read_text(encoding="utf-8")

    assert '"package_only": True' in source
    assert '"parcel_adapter_metric": False' in source
    assert '"official_score": False' in source
    assert '"top_decile_evidence": False' in source


def test_submission_provenance_uses_the_calibrated_transport_identity() -> None:
    assert submission.ADAPTER_ID == BARN_ROS2_ADAPTER_ID
    assert submission.ADAPTER_ID.endswith("calibrated-sensor-transport-v2")


def test_result_lookup_matches_unchanged_upstream_get_pkg_src_path() -> None:
    assert submission.ROOTFS_RESULT_DIRECTORY == Path("jackal_ws/src/The-Barn-Challenge-Ros2/res")


def test_failed_launch_without_evaluator_row_writes_no_result_or_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle = submission.Bundle(
        path=tmp_path / "bundle",
        manifest_path=tmp_path / "bundle/package-manifest.json",
        package_sha256="a" * 64,
        launch_overlay_path=tmp_path / "bundle/overlay/BARN_runner.launch.py",
        files={},
    )
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    results = tmp_path / "results"
    monkeypatch.setattr(submission, "RUN_CACHE", tmp_path / "run-cache")
    monkeypatch.setattr(submission, "verify_bundle", lambda path: bundle)
    monkeypatch.setattr(submission, "_validated_rootfs", lambda path: rootfs)
    monkeypatch.setattr(
        submission,
        "verify_upstream_checkout",
        lambda: {"commit": "b" * 40, "clean": True, "critical_files_sha256": {}},
    )
    monkeypatch.setattr(
        submission,
        "world0_command",
        lambda bundle, rootfs, out_file: ["/usr/bin/true"],
    )
    monkeypatch.setattr(
        submission,
        "record_evaluation_run",
        lambda **kwargs: pytest.fail("ledger must not be called without an evaluator row"),
    )

    with pytest.raises(RuntimeError, match="without a real evaluator row"):
        submission.run_world0(
            bundle=bundle,
            rootfs=rootfs,
            results_dir=results,
            timeout_s=120.0,
            now=datetime(2026, 8, 3, 13, 59, 2, tzinfo=timezone.utc),
        )

    assert not results.exists()


def test_manifest_json_is_strict_and_finite() -> None:
    payload = submission._canonical_json({"value": 1.25}, pretty=True)
    assert json.loads(payload) == {"value": 1.25}
    with pytest.raises(ValueError):
        submission._canonical_json({"value": float("nan")})
