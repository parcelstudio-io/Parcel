from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import evals.external.barn_official_doctor as doctor
from evals.external.fetch_sources import load_lock


def test_runtime_manifest_is_pinned_and_public_is_never_official() -> None:
    manifest = doctor.load_runtime_manifest()

    assert manifest["official_sources"]["repository_commit"] == (
        "d6c575b51e477bd524d634e12cffeb34036fcd1e"
    )
    assert manifest["container"]["tested_version"] == "4.3.0"
    assert manifest["container"]["installer_sha256"] == (
        "0d165a619a4d7ff094e041c59e1f17490b08c6bd8705378db474c823b0efc0e8"
    )
    assert manifest["container"]["installer_size_bytes"] == 52_091_122
    assert manifest["container"]["installer_package_version"] == "4.3.0-noble"
    assert manifest["container"]["installer_architecture"] == "amd64"
    assert len(manifest["container"]["extracted_critical_files_sha256"]) == 3
    assert manifest["container"]["local_base_image_linux_amd64_manifest_digest"] == (
        "sha256:567b81bc54f44479e16ef1b75e4984d132f154b6511ea4fc851ee6bde76c30f8"
    )
    assert (
        manifest["official_sources"]["critical_files_sha256"][
            "jackal_helper/scripts/barn_runner.py"
        ]
        == "a4794ea1c271ca89b2d5496e954a5709d78f4a024a211a707c4a07b84b10f3a3"
    )
    assert manifest["rootless_diagnostic"]["official_compatibility_gate"] is False
    assert manifest["rootless_diagnostic"]["proot_sha256"] == (
        "b7f2adf5a225000a164f4905aabefeebe11c4c1d5bedff5e1fe8866c48dd70d2"
    )
    assert manifest["protocol"]["public_world_indices"] == list(range(0, 300, 6))
    assert manifest["protocol"]["hidden_world_count"] == 50
    assert manifest["protocol"]["hidden_trials_per_world"] == 10
    assert manifest["eligibility"]["public_container_run_is_official_score"] is False
    assert (
        manifest["eligibility"]["leaderboard_claim_allowed_without_organizer_attestation"] is False
    )
    assert (
        load_lock()[doctor.SOURCE_ID]["commit"]
        == (manifest["official_sources"]["repository_commit"])
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("singularity-ce version 4.3.0", "4.3.0"),
        ("singularity-ce 4.3.0", "4.3.0"),
        ("apptainer version 1.4.5", "1.4.5"),
        ("unexpected", None),
    ],
)
def test_parse_singularity_version(raw: str, expected: str | None) -> None:
    assert doctor.parse_singularity_version(raw) == expected


def test_readiness_separates_build_prerequisites_from_public_and_hidden_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_commit = "d6c575b51e477bd524d634e12cffeb34036fcd1e"

    def fake_command(executable: str, arguments: tuple[str, ...]) -> dict[str, object]:
        del arguments
        if executable == "singularity":
            return {
                "detected": True,
                "path": "/usr/local/bin/singularity",
                "output": "singularity-ce version 4.3.0",
                "error": None,
            }
        if executable == "nvidia-smi":
            return {
                "detected": True,
                "path": "/usr/bin/nvidia-smi",
                "output": "test gpu",
                "error": None,
            }
        return {"detected": False, "path": None, "output": None, "error": "not found"}

    monkeypatch.setattr(doctor, "_command_version", fake_command)
    monkeypatch.setattr(
        doctor,
        "_git_checkout_status",
        lambda path, commit, origin: {
            "path": str(path),
            "detected": True,
            "actual_commit": expected_commit,
            "expected_commit": commit,
            "commit_matches": True,
            "origin_url": origin,
            "expected_origin": origin,
            "origin_matches": True,
            "worktree_clean": True,
            "provenance_verified": True,
            "error": None,
        },
    )
    monkeypatch.setattr(
        doctor,
        "_user_namespace_probe",
        lambda executable, arguments: {"attempted": True, "ready": True, "error": None},
    )
    monkeypatch.setattr(
        doctor,
        "_read_text",
        lambda path: (
            'ID="ubuntu"\nVERSION_ID="24.04"\n'
            if Path(path) == Path("/tmp/test-os-release")
            else "1\n"
        ),
    )
    monkeypatch.setattr(doctor, "_mapping_present", lambda path, username: True)
    monkeypatch.setattr(doctor.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(doctor.shutil, "which", lambda executable: f"/usr/bin/{executable}")

    report = doctor.audit_barn_ros2_readiness(
        repo_root=Path(__file__).resolve().parents[1],
        checkout_root=Path("/tmp/test-barn-checkouts"),
        os_release_path=Path("/tmp/test-os-release"),
        environment={"USER": "tester"},
    )

    assert report["classification"]["build_prerequisites_ready"] is True
    assert report["classification"]["public_container_compatibility_ready"] is False
    assert report["classification"]["official_hidden_protocol_ready"] is False
    assert report["classification"]["official_score_available"] is False
    assert report["classification"]["leaderboard_claim_allowed"] is False
    assert report["host"]["native_ros2_jazzy_supported"] is True
    assert report["host"]["gpu"]["required"] is False
    assert report["host"]["gpu"]["local_passthrough_supported_by_upstream_wrapper"] is True
    assert report["host"]["gpu"]["official_simulation_gpu_promised"] is False
    assert report["host"]["gpu"]["official_physical_final_gpu_available"] is False
    assert report["host"]["gpu"]["cpu_compatibility_required"] is True
    assert report["source"]["provenance_ready"] is True
    blocker_ids = {blocker["id"] for blocker in report["blockers"]}
    assert "compatibility_sif_missing" in blocker_ids
    assert "public_500_episode_report_missing_or_invalid" in blocker_ids
    assert "organizer_hidden_evaluation_required" in blocker_ids
    assert "post_event_submission_not_confirmed" in blocker_ids


def test_current_host_audit_is_read_only_and_never_grants_official_claim() -> None:
    report = doctor.audit_barn_ros2_readiness()

    assert report["schema_version"] == 1
    assert report["classification"]["official_score_available"] is False
    assert report["classification"]["leaderboard_claim_allowed"] is False
    assert report["adapter"]["production_package_modified"] is False
    assert report["adapter"]["official_evaluator_modified"] is False
    assert report["runtime_artifacts"]["extraction_is_runtime_exec_proof"] is False
    assert report["classification"]["rootless_upstream_smoke_evidence_valid"] is True
    assert report["rootless_diagnostic"]["official_compatibility_gate"] is False
    assert report["rootless_diagnostic"]["parcel_navigation_score"] is False
    assert report["rootless_diagnostic"]["top_decile_evidence"] is False


def test_git_checkout_provenance_requires_exact_origin_commit_and_clean_tree(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    def git(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(checkout), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    git("init", "--quiet")
    (checkout / "README.md").write_text("pinned\n", encoding="utf-8")
    git("add", "README.md")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "pin")
    commit = git("rev-parse", "HEAD")
    origin = "https://github.com/example/official.git"
    git("remote", "add", "origin", origin)

    clean = doctor._git_checkout_status(checkout, commit, origin)
    (checkout / "README.md").write_text("modified\n", encoding="utf-8")
    dirty = doctor._git_checkout_status(checkout, commit, origin)

    assert clean["provenance_verified"] is True
    assert clean["origin_matches"] is True
    assert clean["worktree_clean"] is True
    assert dirty["commit_matches"] is True
    assert dirty["worktree_clean"] is False
    assert dirty["provenance_verified"] is False


def test_verified_extraction_never_substitutes_for_executable_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_commit = "d6c575b51e477bd524d634e12cffeb34036fcd1e"

    def fake_command(executable: str, arguments: tuple[str, ...]) -> dict[str, object]:
        del arguments
        return {"detected": False, "path": None, "output": None, "error": f"{executable} missing"}

    monkeypatch.setattr(doctor, "_command_version", fake_command)
    monkeypatch.setattr(
        doctor,
        "_git_checkout_status",
        lambda path, commit, origin: {
            "path": str(path),
            "detected": True,
            "actual_commit": expected_commit,
            "expected_commit": commit,
            "commit_matches": True,
            "origin_url": origin,
            "expected_origin": origin,
            "origin_matches": True,
            "worktree_clean": True,
            "provenance_verified": True,
            "error": None,
        },
    )
    monkeypatch.setattr(
        doctor,
        "inspect_runtime_package",
        lambda path, manifest: {"path": str(path), "verified": True},
    )
    monkeypatch.setattr(
        doctor,
        "inspect_runtime_rootfs",
        lambda path, manifest: {
            "path": str(path),
            "verified": True,
            "runtime_exec_ready": False,
        },
    )
    monkeypatch.setattr(
        doctor,
        "_user_namespace_probe",
        lambda executable, arguments: {
            "attempted": True,
            "ready": arguments == ("--user", "true"),
            "error": None if arguments == ("--user", "true") else "uid_map denied",
        },
    )

    report = doctor.audit_barn_ros2_readiness(
        repo_root=Path(__file__).resolve().parents[1],
        checkout_root=tmp_path / "checkout",
        runtime_package_path=tmp_path / "runtime.deb",
        runtime_rootfs_path=tmp_path / "rootfs",
    )

    assert report["classification"]["build_prerequisites_ready"] is False
    assert report["classification"]["public_container_compatibility_ready"] is False
    blocker_ids = {blocker["id"] for blocker in report["blockers"]}
    assert "tested_singularity_runtime_not_installed" in blocker_ids
    assert "rootless_namespace_mapping_blocked" in blocker_ids


def test_rootless_smoke_evidence_is_bound_to_raw_row_and_non_official_claims(
    tmp_path: Path,
) -> None:
    source = doctor.DEFAULT_ROOTLESS_SMOKE_EVIDENCE
    raw_source = source.with_name("upstream-mppi-world0-20260803.raw.txt")
    evidence = tmp_path / source.name
    raw = tmp_path / raw_source.name
    evidence.write_bytes(source.read_bytes())
    raw.write_bytes(raw_source.read_bytes())

    manifest = doctor.load_runtime_manifest()
    valid = doctor._rootless_smoke_evidence_status(evidence, manifest=manifest)

    assert valid["valid"] is True
    assert valid["episode"] == {
        "world_idx": 0,
        "success": 1,
        "collision": 0,
        "timeout": 0,
        "elapsed_time_s": 37.715,
        "navigation_metric": 0.1802,
    }
    assert valid["official_protocol"] is False
    assert valid["parcel_adapter_exercised"] is False
    assert valid["top_decile_evidence"] is False

    raw.write_text("0 0 1 0 120.0000 0.0000\n", encoding="utf-8")
    tampered = doctor._rootless_smoke_evidence_status(evidence, manifest=manifest)

    assert tampered["valid"] is False
    assert "raw result sha256 mismatch" in tampered["errors"]
    assert "raw result size mismatch" in tampered["errors"]
    assert "episode metrics do not match the raw evaluator row" in tampered["errors"]


def test_rootless_smoke_rejects_claim_escalation(tmp_path: Path) -> None:
    source = doctor.DEFAULT_ROOTLESS_SMOKE_EVIDENCE
    raw_source = source.with_name("upstream-mppi-world0-20260803.raw.txt")
    evidence = tmp_path / source.name
    raw = tmp_path / raw_source.name
    raw.write_bytes(raw_source.read_bytes())
    document = json.loads(source.read_text(encoding="utf-8"))
    document["claims"]["parcel_navigation_score"] = True
    document["claims"]["top_decile_evidence"] = True
    evidence.write_text(json.dumps(document), encoding="utf-8")

    status = doctor._rootless_smoke_evidence_status(
        evidence,
        manifest=doctor.load_runtime_manifest(),
    )

    assert status["valid"] is False
    assert "non-official claim boundary mismatch" in status["errors"]


def test_rootless_build_rootfs_checks_build_outputs_packages_and_source_hashes(
    tmp_path: Path,
) -> None:
    source_payloads = {
        "jackal_helper/config/nav2.yaml": b"nav2\n",
        "jackal_helper/launch/BARN_runner.launch.py": b"runner launch\n",
        "jackal_helper/launch/nav2_bringup.launch.py": b"nav2 launch\n",
        "jackal_helper/scripts/barn_runner.py": b"runner\n",
    }
    critical = {
        relative: hashlib.sha256(payload).hexdigest()
        for relative, payload in source_payloads.items()
    }
    rootfs = tmp_path / "rootfs"
    for relative, payload in source_payloads.items():
        destination = rootfs / "jackal_ws/src/The-Barn-Challenge-Ros2" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    for relative in (
        "opt/ros/jazzy/setup.bash",
        "jackal_ws/install/local_setup.bash",
        "jackal_ws/install/jackal_helper/share/jackal_helper/package.xml",
    ):
        destination = rootfs / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("built\n", encoding="utf-8")
    status_path = rootfs / "var/lib/dpkg/status"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        "Package: ros-jazzy-ros-gz\nStatus: install ok installed\n\n"
        "Package: ros-jazzy-clearpath-simulator\nStatus: install ok installed\n",
        encoding="utf-8",
    )

    ready = doctor._rootless_build_rootfs_status(
        rootfs,
        critical_source_hashes=critical,
    )
    (rootfs / "jackal_ws/src/The-Barn-Challenge-Ros2/jackal_helper/config/nav2.yaml").write_text(
        "tampered\n",
        encoding="utf-8",
    )
    tampered = doctor._rootless_build_rootfs_status(
        rootfs,
        critical_source_hashes=critical,
    )

    assert ready["ready_for_diagnostic_replay"] is True
    assert ready["satisfies_singularity_or_sif_gate"] is False
    assert tampered["ready_for_diagnostic_replay"] is False
    assert tampered["evaluator_critical_files_verified"] is False
