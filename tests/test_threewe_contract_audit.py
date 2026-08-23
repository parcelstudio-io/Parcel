from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "evals/external/results/threewe/threewe-contract-audit-20260803-baseline01.json"
AUDITOR = ROOT / "evals/external/threewe_contract_audit.py"
PORTFOLIO = ROOT / "evals/external/targets/portfolio.json"
SOURCE_LOCK = ROOT / "evals/external/sources.lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report() -> dict:
    value = json.loads(REPORT.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_threewe_contract_audit_is_immutable_source_evidence_not_a_score() -> None:
    report = _report()

    assert _sha256(REPORT) == "544fd5c6ac53db6a13244d976ac7797826ff9367bf289bb5fe7e0afb079d78f7"
    # ---- CARD GATE-0b (scrum/20260822/task_30) -----------------------------
    # `assert REPORT.stat().st_mode & 0o222 == 0` used to stand here. It was
    # reachable only because this evidence file was NOT in git
    # (`evals/external/.gitignore:1` ignored `results/*`); the same card that
    # tracked it turned that line red, because git records one permission bit
    # and it is not this one — a checkout writes `0666 & ~umask`, i.e. `644`,
    # on this box, on the hosted runner and on the Orin alike.
    #
    # The immutability being claimed is CONTENT immutability, and the line
    # above already asserts it against a pinned sha256 — a far stronger claim
    # than "nobody has chmod +w", and one that survives being cloned. Same
    # decision, same reasoning, as the V9 training manifest
    # (`evals/external/generate_sampled_predictive_tracker_v9_training.py`
    # `_require_immutable_regular_file`); recorded in `task_30/DESIGN.md` §g.
    # ---- END CARD GATE-0b --------------------------------------------------
    assert report["kind"] == "source_contract_compatibility_audit"
    assert report["admission"]["status"] == "not_admitted"
    assert report["admission"]["parcel_adapter_execution_allowed"] is False
    assert report["admission"]["rank_threshold_freeze_allowed"] is False
    assert report["execution"] == {
        "episodes_run": 0,
        "metrics_emitted": False,
        "parcel_policy_executed": False,
        "rank_eligible": False,
        "simulator_started": False,
        "source_code_executed": False,
    }
    assert report["aggregate"] == {
        "critical_contract_blockers": 13,
        "eligible_navigation_scores": 0,
        "targets_remaining_unresolved": 3,
    }


def test_threewe_contract_audit_binds_implementation_and_adopted_manifests() -> None:
    report = _report()

    assert report["audit_implementation"] == {
        "path": "evals/external/threewe_contract_audit.py",
        "sha256": _sha256(AUDITOR),
        "upstream_python_imported": False,
    }
    assert report["source"]["expected_commit"] == ("6073a1bd0a30b6ca1348027ac35b05832b97bfe9")
    assert report["source"]["checkout_commit"] == report["source"]["expected_commit"]
    assert report["source"]["checkout_clean"] is True
    assert report["source"]["portfolio_sha256"] == _sha256(PORTFOLIO)
    assert report["source"]["source_lock_sha256"] == _sha256(SOURCE_LOCK)
    assert report["leaderboard_snapshot"]["rows_rejected_by_implemented_validator"] == 6
    assert report["scene_snapshot"] == {
        "gazebo_enclosed_coordinate_bounds": {"x": [0, 15], "y": [0, 10]},
        "goal_pose_count": 50,
        "goal_poses_outside_or_on_boundary": 34,
        "metadata_area": "20x15m",
        "start_pose_count": 20,
        "start_poses_outside_or_on_boundary": 15,
    }


def test_threewe_contract_audit_covers_each_decisive_admission_failure() -> None:
    report = _report()
    finding_ids = {item["id"] for item in report["findings"]}

    assert finding_ids == {
        "protocol_seed_and_reset_mismatch",
        "task_timeout_mismatch",
        "pointnav_success_boundary_not_enforced",
        "spl_path_length_is_displacement",
        "objectnav_hidden_coordinate_oracle",
        "exploration_backend_is_stub",
        "runner_owns_navigation_stack",
        "isaac_backend_is_stub",
        "simulated_embodiment_is_not_go2",
        "office_scene_coordinate_contract_mismatch",
        "report_submission_schema_divergence",
        "published_baseline_references_diverge",
        "leaderboard_cohort_not_rankable",
    }
    assert all(item["severity"] == "critical" for item in report["findings"])
