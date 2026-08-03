"""Refreeze v6 after a metadata-only baseline-spec preflight abort.

Run01 reached the paired-comparison validation boundary but no BARN suite,
episode, policy, metric, report, or ledger write.  This one-purpose repair keeps
the already frozen and unobserved development corpus, controller artifacts,
hypothesis, protocol, and gates byte-identical.  It changes only the v5 arm's
harness classification from experimental candidate to immutable comparison
reference; deployment remains disabled for both arms.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .barn_policy_specs import PARCEL_POLICY_SOURCE_ROOT, REPO_ROOT, _source_tree_sha256
from .generate_safe_valley_guard_v6_corpus import (
    CHALLENGER_CONFIG,
    CHALLENGER_MODEL,
    CORPUS_ID,
    DEVELOPMENT_WORLD_IDS,
    PROMOTION_GATE,
    REFERENCE_CONFIG,
    REFERENCE_MODEL,
    SEALED_CONFIRMATION_WORLD_IDS,
)
from .generate_safe_valley_guard_v6_corpus import (
    DEFAULT_MANIFEST as PREDECESSOR_MANIFEST,
)
from .generate_safe_valley_v5_corpus import _corpus_sha256, _frozen_file, _write_exclusive_json
from .ledger import sha256_file
from .run_safe_valley_v5 import _require_mapping, _verify_file

PREDECESSOR_MANIFEST_SHA256 = "47dddf6b54a8cc6b962f6bb4b16912a2d72266187126e13c6559af0f0949cd63"
PREDECLARED_CORPUS_SHA256 = "fd587ef042b8fae124c4b0b2779548023d0b374eaf5d4bd9759ea4b0d00ff579"
ABORTED_RUN_ID = "barn-safe-valley-guard-v6-dev-20260803-run01"
REPAIRED_RUN_ID = "barn-safe-valley-guard-v6-dev-20260803-run02"
REPAIRED_MANIFEST = PREDECESSOR_MANIFEST.with_name("split-run02.json")
PREFLIGHT_RECORD = (
    PREDECESSOR_MANIFEST.parent
    / "results"
    / "preflight"
    / f"{ABORTED_RUN_ID}-failed-before-episodes.json"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _assert_absent(path: Path, label: str) -> None:
    if path.exists():
        raise FileExistsError(f"{label} must be absent after the preflight abort: {path}")


def _verify_predecessor() -> tuple[dict[str, Any], Path, dict[str, dict[str, str]]]:
    if sha256_file(PREDECESSOR_MANIFEST) != PREDECESSOR_MANIFEST_SHA256:
        raise ValueError("v6 predecessor manifest changed after the aborted preflight")
    payload = json.loads(PREDECESSOR_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported v6 predecessor manifest")
    if payload.get("corpus_id") != CORPUS_ID:
        raise ValueError("unexpected v6 predecessor corpus identity")
    if payload.get("promotion_gate_frozen_before_development") != PROMOTION_GATE:
        raise ValueError("v6 promotion gate changed after predeclaration")

    status = _require_mapping(payload.get("status_at_freeze"), "status_at_freeze")
    if any(
        status.get(key) is not False
        for key in (
            "development_policy_execution_started",
            "sealed_confirmation_generated",
            "sealed_confirmation_opened",
            "deployment_enabled",
        )
    ):
        raise ValueError("predecessor status is not a pre-execution development freeze")

    identity = _require_mapping(payload.get("identity_partition"), "identity_partition")
    if tuple(identity.get("development_world_ids", ())) != DEVELOPMENT_WORLD_IDS:
        raise ValueError("v6 development identities changed")
    if tuple(identity.get("sealed_confirmation_world_ids", ())) != SEALED_CONFIRMATION_WORLD_IDS:
        raise ValueError("v6 confirmation identities changed")

    corpus = _require_mapping(payload.get("development_corpus"), "development_corpus")
    episodes = corpus.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != len(DEVELOPMENT_WORLD_IDS):
        raise ValueError("v6 predecessor corpus episode count changed")
    if corpus.get("corpus_sha256") != PREDECLARED_CORPUS_SHA256:
        raise ValueError("v6 predecessor corpus digest changed")
    if _corpus_sha256(episodes) != PREDECLARED_CORPUS_SHA256:
        raise ValueError("v6 predecessor episode manifest changed")
    assets_root = Path(str(corpus["assets_root"])).expanduser().resolve()
    for episode in episodes:
        item = _require_mapping(episode, "development episode")
        files = _require_mapping(item.get("files"), f"world {item.get('world_id')} files")
        for kind in ("world", "path", "grid", "cspace", "metrics"):
            _verify_file(
                assets_root, _require_mapping(files.get(kind), kind), str(item["world_id"])
            )
    if sha256_file(assets_root / "generation.log") != corpus.get("generation_log_sha256"):
        raise ValueError("v6 generation log changed")

    for world_id in SEALED_CONFIRMATION_WORLD_IDS:
        for directory, stem, suffix in (
            ("world_files", "world", ".world"),
            ("path_files", "path", ".npy"),
            ("grid_files", "grid", ".npy"),
            ("cspace_files", "cspace", ".npy"),
            ("metrics_files", "metrics", ".npy"),
        ):
            _assert_absent(
                assets_root / directory / f"{stem}_{world_id}{suffix}",
                "sealed confirmation geometry",
            )

    frozen = _require_mapping(
        payload.get("frozen_policy_inputs_before_execution"),
        "frozen_policy_inputs_before_execution",
    )
    expected_policy_files = {
        "reference_config": REFERENCE_CONFIG,
        "reference_model": REFERENCE_MODEL,
        "challenger_config": CHALLENGER_CONFIG,
        "challenger_model": CHALLENGER_MODEL,
    }
    for name, expected_path in expected_policy_files.items():
        record = _require_mapping(frozen.get(name), name)
        if Path(str(record.get("path"))) != expected_path.resolve().relative_to(
            REPO_ROOT.resolve()
        ):
            raise ValueError(f"unexpected predecessor {name} path")
        _verify_file(REPO_ROOT, record, name)
    source_tree = _require_mapping(frozen.get("policy_source_tree"), "policy_source_tree")
    if _source_tree_sha256(PARCEL_POLICY_SOURCE_ROOT) != source_tree.get("sha256"):
        raise ValueError("policy source changed during the aborted preflight")

    harness = _require_mapping(frozen.get("harness_files"), "harness_files")
    allowed_mismatches = {"experiment_runner", "compatibility"}
    observed_mismatches: dict[str, dict[str, str]] = {}
    for name, raw_record in harness.items():
        record = _require_mapping(raw_record, f"harness/{name}")
        path = REPO_ROOT / str(record["path"])
        actual_sha256 = sha256_file(path)
        if actual_sha256 != record.get("sha256"):
            if name not in allowed_mismatches:
                raise ValueError(f"unexpected concurrent harness change: {name}")
            observed_mismatches[str(name)] = {
                "path": str(record["path"]),
                "predecessor_sha256": str(record["sha256"]),
                "repaired_sha256": actual_sha256,
            }
            continue
        if name in allowed_mismatches:
            raise ValueError(f"expected refreeze mismatch was not present: {name}")
        _verify_file(REPO_ROOT, record, f"harness/{name}")
    if set(observed_mismatches) != allowed_mismatches:
        raise ValueError("predecessor harness mismatch set is not the authorized repair set")
    if Path(observed_mismatches["experiment_runner"]["path"]).name != (
        "run_safe_valley_guard_v6.py"
    ):
        raise ValueError("unexpected predecessor experiment runner")
    if Path(observed_mismatches["compatibility"]["path"]).name != "compatibility.py":
        raise ValueError("unexpected concurrent compatibility record")
    return payload, assets_root, observed_mismatches


def refreeze() -> dict[str, Any]:
    """Write an immutable abort record and content-addressed repaired manifest."""

    _assert_absent(REPAIRED_MANIFEST, "repaired manifest")
    _assert_absent(PREFLIGHT_RECORD, "failed-preflight record")
    results_root = PREDECESSOR_MANIFEST.parent / "results"
    expected_outputs = {
        "full_report": results_root / "runs" / f"{ABORTED_RUN_ID}.json",
        "summary": results_root / f"{ABORTED_RUN_ID}-summary.json",
        "ledger_record": results_root / "ledger" / "runs" / f"{ABORTED_RUN_ID}.json",
        "ledger_index": results_root / "ledger" / "runs.jsonl",
    }
    for label, path in expected_outputs.items():
        _assert_absent(path, label)

    predecessor, _assets_root, harness_mismatches = _verify_predecessor()
    preflight = {
        "schema_version": 1,
        "recorded_at": _now(),
        "run_id": ABORTED_RUN_ID,
        "outcome": "failed_preflight_before_episode_execution",
        "exception": {
            "type": "ValueError",
            "message": "baseline_spec must not be experimental",
            "boundary": "run_barn_comparison baseline metadata validation before run_barn_suite",
        },
        "episode_policy_executions": 0,
        "episode_outcomes_inspected": False,
        "metrics_generated": False,
        "report_written": False,
        "ledger_written": False,
        "confirmation_generated_opened_or_evaluated": False,
        "output_absence_verified": {name: str(path) for name, path in expected_outputs.items()},
        "repair_scope": (
            "Classify the byte-identical v5 config/model as a non-experimental immutable paired "
            "reference while keeping deployment_enabled=false; no controller or gate change. "
            "Also content-address the root-authorized concurrent compatibility-table prose "
            "change, which is not imported by the paired BARN runner."
        ),
    }
    _write_exclusive_json(PREFLIGHT_RECORD, preflight)

    repaired = copy.deepcopy(predecessor)
    repaired["created_at"] = _now()
    repaired["purpose"] = (
        "Content-addressed metadata-only refreeze of the v6 one-shot development protocol after "
        "run01 aborted before episode execution"
    )
    repaired["manifest_revision"] = {
        "revision": 2,
        "predecessor": _frozen_file(PREDECESSOR_MANIFEST),
        "failed_preflight": _frozen_file(PREFLIGHT_RECORD),
        "repaired_run_id": REPAIRED_RUN_ID,
        "change": (
            "Use parcel_reference_config_spec for v5 so the paired harness recognizes it as the "
            "immutable reference; its config, model, source, deployment state, and behavior are "
            "unchanged."
        ),
        "corpus_reused_without_episode_execution_or_outcome_inspection": True,
        "hypothesis_protocol_and_promotion_gate_unchanged": True,
        "authorized_harness_hash_changes": {
            "experiment_runner": {
                **harness_mismatches["experiment_runner"],
                "classification": "metadata_only_baseline_reference_spec_repair",
            },
            "compatibility": {
                **harness_mismatches["compatibility"],
                "classification": "concurrent_non_policy_compatibility_table_prose",
                "imported_by_paired_barn_runner": False,
            },
        },
    }
    frozen = _require_mapping(
        repaired["frozen_policy_inputs_before_execution"],
        "frozen_policy_inputs_before_execution",
    )
    frozen["reference_config"] = _frozen_file(REFERENCE_CONFIG)
    frozen["reference_model"] = _frozen_file(REFERENCE_MODEL)
    frozen["challenger_config"] = _frozen_file(CHALLENGER_CONFIG)
    frozen["challenger_model"] = _frozen_file(CHALLENGER_MODEL)
    frozen["policy_source_tree"] = {
        "path": PARCEL_POLICY_SOURCE_ROOT.resolve().relative_to(REPO_ROOT.resolve()).as_posix(),
        "sha256": _source_tree_sha256(PARCEL_POLICY_SOURCE_ROOT),
    }
    old_harness = _require_mapping(frozen.get("harness_files"), "harness_files")
    refreshed_harness: dict[str, Any] = {}
    for name, raw_record in old_harness.items():
        record = _require_mapping(raw_record, f"harness/{name}")
        refreshed_harness[str(name)] = _frozen_file(REPO_ROOT / str(record["path"]))
    refreshed_harness["preflight_refreeze"] = _frozen_file(Path(__file__))
    frozen["harness_files"] = refreshed_harness
    status = _require_mapping(repaired["status_at_freeze"], "status_at_freeze")
    status["development_policy_execution_started"] = False
    status["aborted_preflight_count"] = 1
    status["last_aborted_preflight_run_id"] = ABORTED_RUN_ID
    status["authorized_repaired_development_run_id"] = REPAIRED_RUN_ID
    status["sealed_confirmation_generated"] = False
    status["sealed_confirmation_opened"] = False
    status["deployment_enabled"] = False
    _write_exclusive_json(REPAIRED_MANIFEST, repaired)
    return repaired


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acknowledge-metadata-only-preflight-repair",
        action="store_true",
        help="required acknowledgement; never generates or opens corpus geometry",
    )
    args = parser.parse_args(argv)
    if not args.acknowledge_metadata_only_preflight_repair:
        parser.error("repair requires --acknowledge-metadata-only-preflight-repair")
    repaired = refreeze()
    print(
        json.dumps(
            {
                "repaired_manifest": str(REPAIRED_MANIFEST.resolve()),
                "predecessor_manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
                "corpus_sha256": repaired["development_corpus"]["corpus_sha256"],
                "failed_preflight_run_id": ABORTED_RUN_ID,
                "authorized_repaired_run_id": REPAIRED_RUN_ID,
                "episode_policy_executions_before_refreeze": 0,
                "sealed_confirmation_generated": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ABORTED_RUN_ID",
    "PREFLIGHT_RECORD",
    "REPAIRED_MANIFEST",
    "REPAIRED_RUN_ID",
    "refreeze",
]
