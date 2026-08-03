"""Independent, fail-closed promotion gate for the V8 paired development run.

This module evaluates only the predeclared development gate.  It never runs a
policy, generates a corpus, opens the operational holdout, or makes an
official/leaderboard claim.  Binary action evidence is parsed and recertified
independently of policy notes before any efficacy or latency result can pass.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from .barn_sensor_faithful import (
    CANDIDATE_THEN_REFERENCE,
    REFERENCE_THEN_CANDIDATE,
)
from .barn_v8_action_certifier import FROZEN_V8_BARN_EVALUATOR_PROFILE
from .barn_v8_action_evidence import (
    V8_ACTION_EVIDENCE_FORMAT_ID,
    V8_ACTION_EVIDENCE_VERSION,
    V8ActionEvidenceReadResult,
    read_v8_action_evidence,
)
from .generate_all_ray_shield_v8_corpus import (
    CORPUS_ID,
    DEVELOPMENT_WORLD_IDS,
    EPISODE_WORKERS,
    PAIRED_ARM_ORDER_SCHEDULE,
    PAIRED_ARM_ORDER_SCHEDULE_SHA256,
    PROMOTION_GATE,
    SUITE_SEED,
    TRIALS_PER_WORLD,
)

V8_GATE_ID = "parcel-barn-v8-predeclared-development-promotion-gate-v1"
V8_EVIDENCE_INDEX_KIND = "parcel-barn-v8-action-evidence-index-v1"
V8_EVIDENCE_INDEX_SCHEMA_VERSION = 1
V8_DEVELOPMENT_PAIR_COUNT = 30
V8_TRIALS_PER_WORLD = TRIALS_PER_WORLD
V8_EPISODE_WORKERS = EPISODE_WORKERS
V8_SUITE_SEED = SUITE_SEED
V8_REQUIRED_RAYS = 720
V8_MINIMUM_SIGNED_BODY_CLEARANCE_M = 0.475

_ARMS = ("reference", "candidate")
_SHA256 = frozenset("0123456789abcdef")
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


class V8PromotionGateError(ValueError):
    """Raised when provenance or evidence is malformed instead of merely weak."""


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize one strict JSON value for identity hashes used by this gate."""

    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value) <= _SHA256
    )


def _require_sha256(value: object, name: str) -> str:
    if not _valid_sha256(value):
        raise V8PromotionGateError(f"{name} must be a lowercase SHA-256 digest")
    return str(value)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V8PromotionGateError(f"{name} must be a JSON object")
    return value


def _list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise V8PromotionGateError(f"{name} must be a JSON array")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise V8PromotionGateError(f"{name} must be an integer")
    return value


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V8PromotionGateError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise V8PromotionGateError(f"{name} must be finite")
    return result


def _same_float(left: object, right: object, *, name: str) -> bool:
    return struct.pack("<d", _finite(left, name)) == struct.pack(
        "<d", _finite(right, name)
    )


def _promotion_number(*keys: str) -> float:
    """Read a required frozen threshold while tolerating descriptive key names."""

    for key in keys:
        if key in PROMOTION_GATE:
            return _finite(PROMOTION_GATE[key], f"PROMOTION_GATE.{key}")
    raise V8PromotionGateError(
        "the generator promotion gate is missing required threshold: " + "/".join(keys)
    )


@dataclass(frozen=True, slots=True)
class V8DevelopmentGateContract:
    """Identities established by manifest and isolated-bundle preflight."""

    run_id: str
    corpus_id: str
    corpus_sha256: str
    manifest_sha256: str
    native_config_sha256: str
    reference_policy_metadata_sha256: str
    candidate_policy_metadata_sha256: str
    one_factor_delta_sha256: str
    isolated_runtime_pair_sha256: str
    world_ids: tuple[int, ...] = tuple(DEVELOPMENT_WORLD_IDS)
    suite_seed: int = V8_SUITE_SEED
    trials_per_world: int = V8_TRIALS_PER_WORLD
    workers: int = V8_EPISODE_WORKERS
    arm_order_schedule: tuple[str, ...] = tuple(PAIRED_ARM_ORDER_SCHEDULE)
    arm_order_schedule_sha256: str = PAIRED_ARM_ORDER_SCHEDULE_SHA256

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise V8PromotionGateError("run_id must be non-empty")
        if self.corpus_id != CORPUS_ID:
            raise V8PromotionGateError("unexpected V8 corpus identity")
        for name in (
            "corpus_sha256",
            "manifest_sha256",
            "native_config_sha256",
            "reference_policy_metadata_sha256",
            "candidate_policy_metadata_sha256",
            "one_factor_delta_sha256",
            "isolated_runtime_pair_sha256",
            "arm_order_schedule_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        if self.world_ids != tuple(DEVELOPMENT_WORLD_IDS):
            raise V8PromotionGateError("development world identities/order changed")
        if len(self.world_ids) != V8_DEVELOPMENT_PAIR_COUNT or len(set(self.world_ids)) != len(
            self.world_ids
        ):
            raise V8PromotionGateError("V8 development requires exactly 30 unique worlds")
        if self.suite_seed != V8_SUITE_SEED:
            raise V8PromotionGateError("V8 suite seed changed")
        if self.trials_per_world != V8_TRIALS_PER_WORLD:
            raise V8PromotionGateError("V8 requires exactly one trial per world")
        if self.workers != V8_EPISODE_WORKERS:
            raise V8PromotionGateError("V8 requires exactly four episode workers")
        if self.arm_order_schedule != tuple(PAIRED_ARM_ORDER_SCHEDULE):
            raise V8PromotionGateError("V8 paired arm-order schedule changed")
        expected_schedule_sha = hashlib.sha256(
            json.dumps(
                list(self.arm_order_schedule),
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if self.arm_order_schedule_sha256 != expected_schedule_sha:
            raise V8PromotionGateError("V8 paired arm-order schedule hash mismatch")
        if self.arm_order_schedule.count(REFERENCE_THEN_CANDIDATE) != 15 or (
            self.arm_order_schedule.count(CANDIDATE_THEN_REFERENCE) != 15
        ):
            raise V8PromotionGateError("V8 schedule must be exactly 15/15 counterbalanced")


def v8_evidence_artifact_name(arm: str, world_id: int, trial_id: int) -> str:
    """Return the transaction-safe opaque-binary artifact name."""

    if arm not in _ARMS:
        raise V8PromotionGateError(f"unsupported evidence arm: {arm!r}")
    if isinstance(world_id, bool) or not isinstance(world_id, int) or world_id < 0:
        raise V8PromotionGateError("world_id must be a non-negative integer")
    if isinstance(trial_id, bool) or not isinstance(trial_id, int) or trial_id < 0:
        raise V8PromotionGateError("trial_id must be a non-negative integer")
    prefix = "ref" if arm == "reference" else "cand"
    return f"{prefix}_w{world_id}_t{trial_id}"


def v8_evidence_relative_path(arm: str, world_id: int, trial_id: int) -> str:
    name = v8_evidence_artifact_name(arm, world_id, trial_id)
    return f"{name}.v8e"


def expected_v8_evidence_paths(
    evidence_root: str | Path,
    *,
    world_ids: Sequence[int] = DEVELOPMENT_WORLD_IDS,
) -> dict[str, Path]:
    root = Path(evidence_root).expanduser().absolute()
    result: dict[str, Path] = {}
    for world_id in world_ids:
        for arm in _ARMS:
            name = v8_evidence_artifact_name(arm, int(world_id), 0)
            result[name] = root / v8_evidence_relative_path(arm, int(world_id), 0)
    return result


def build_v8_evidence_index(
    *,
    contract: V8DevelopmentGateContract,
    evidence_root: str | Path,
    write_results: Mapping[tuple[str, int, int], Any],
) -> dict[str, Any]:
    """Build the canonical index payload from 60 exclusive evidence writes."""

    root = Path(evidence_root).expanduser().resolve()
    expected_keys = {
        (arm, world_id, 0) for world_id in contract.world_ids for arm in _ARMS
    }
    if set(write_results) != expected_keys:
        raise V8PromotionGateError("action-evidence write result membership is not exact")
    entries: list[dict[str, Any]] = []
    for pair_index, world_id in enumerate(contract.world_ids):
        order = contract.arm_order_schedule[pair_index]
        for arm in _ARMS:
            write_result = write_results[(arm, world_id, 0)]
            identity = write_result.identity.as_dict()
            expected_order = int(
                (order == REFERENCE_THEN_CANDIDATE and arm == "candidate")
                or (order == CANDIDATE_THEN_REFERENCE and arm == "reference")
            )
            expected_path = root / v8_evidence_relative_path(arm, world_id, 0)
            if Path(str(identity.get("path", ""))).resolve() != expected_path:
                raise V8PromotionGateError("evidence writer used a non-predeclared path")
            if (
                identity.get("arm") != arm
                or identity.get("world_id") != world_id
                or identity.get("trial_id") != 0
                or identity.get("execution_order") != expected_order
            ):
                raise V8PromotionGateError("evidence writer returned the wrong episode identity")
            verified = read_v8_action_evidence(
                expected_path,
                expected_artifact_sha256=str(identity["artifact_sha256"]),
            )
            if verified.identity.as_dict() != identity:
                raise V8PromotionGateError("evidence writer/read identity mismatch")
            entries.append(
                {
                    "relative_path": expected_path.relative_to(root).as_posix(),
                    "identity": identity,
                    "write_overhead": write_result.overhead.as_dict(),
                    "initial_read_verification_overhead": verified.overhead.as_dict(),
                }
            )
    return {
        "schema_version": V8_EVIDENCE_INDEX_SCHEMA_VERSION,
        "kind": V8_EVIDENCE_INDEX_KIND,
        "run_id": contract.run_id,
        "corpus_id": contract.corpus_id,
        "corpus_sha256": contract.corpus_sha256,
        "manifest_sha256": contract.manifest_sha256,
        "profile_id": FROZEN_V8_BARN_EVALUATOR_PROFILE.profile_id,
        "profile_sha256": FROZEN_V8_BARN_EVALUATOR_PROFILE.identity_sha256,
        "entry_count": len(entries),
        "entries": entries,
        "evidence_overhead_included_in_controller_latency": False,
    }


def build_v8_evidence_index_from_report(
    report: Mapping[str, Any],
    *,
    contract: V8DevelopmentGateContract,
    evidence_root: str | Path,
) -> dict[str, Any]:
    """Extract the harness's already-written evidence metadata without trusting it.

    The gate subsequently opens and independently verifies every indexed binary;
    this helper only forms the canonical transaction index.
    """

    root = Path(evidence_root).expanduser().resolve()
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for report_key, arm in (("baseline", "reference"), ("candidate", "candidate")):
        arm_report = _mapping(report.get(report_key), report_key)
        for raw_episode in _list(arm_report.get("episodes"), f"{report_key}.episodes"):
            episode = _mapping(raw_episode, f"{report_key} episode")
            world_id = _integer(episode.get("world_index"), "world_index")
            trial_id = _integer(episode.get("trial"), "trial")
            metadata = _mapping(episode.get("action_evidence"), "episode action_evidence")
            required_metadata = {
                "identity",
                "write_overhead",
                "read_verification_overhead",
                "action_count_matches_published_trace",
                "all_records_format_read_and_recertified",
                "observed_return_boundary_satisfied_action_count",
                "observed_return_boundary_violating_action_count",
                "perception_incomplete_action_count",
                "evaluator_evidence_overhead_included_in_controller_latency",
            }
            if set(metadata) != required_metadata:
                raise V8PromotionGateError("harness action-evidence metadata schema changed")
            if (
                metadata.get("action_count_matches_published_trace") is not True
                or metadata.get("all_records_format_read_and_recertified") is not True
                or metadata.get("evaluator_evidence_overhead_included_in_controller_latency")
                is not False
            ):
                raise V8PromotionGateError("harness did not fully verify action evidence")
            identity = _mapping(metadata.get("identity"), "action-evidence identity")
            key = (arm, world_id, trial_id)
            if key in seen:
                raise V8PromotionGateError("duplicate action-evidence metadata in report")
            seen.add(key)
            expected_path = root / v8_evidence_relative_path(arm, world_id, trial_id)
            if Path(str(identity.get("path", ""))).resolve() != expected_path:
                raise V8PromotionGateError("harness action-evidence path was not predeclared")
            entries.append(
                {
                    "relative_path": expected_path.relative_to(root).as_posix(),
                    "identity": dict(identity),
                    "write_overhead": dict(
                        _mapping(metadata.get("write_overhead"), "write overhead")
                    ),
                    "initial_read_verification_overhead": dict(
                        _mapping(
                            metadata.get("read_verification_overhead"),
                            "initial read-verification overhead",
                        )
                    ),
                }
            )
    expected = {(arm, world_id, 0) for world_id in contract.world_ids for arm in _ARMS}
    if seen != expected:
        raise V8PromotionGateError("harness action-evidence metadata membership is incomplete")
    entries.sort(
        key=lambda item: (
            int(_mapping(item["identity"], "identity")["world_id"]),
            str(_mapping(item["identity"], "identity")["arm"]),
        )
    )
    return {
        "schema_version": V8_EVIDENCE_INDEX_SCHEMA_VERSION,
        "kind": V8_EVIDENCE_INDEX_KIND,
        "run_id": contract.run_id,
        "corpus_id": contract.corpus_id,
        "corpus_sha256": contract.corpus_sha256,
        "manifest_sha256": contract.manifest_sha256,
        "profile_id": FROZEN_V8_BARN_EVALUATOR_PROFILE.profile_id,
        "profile_sha256": FROZEN_V8_BARN_EVALUATOR_PROFILE.identity_sha256,
        "entry_count": len(entries),
        "entries": entries,
        "evidence_overhead_included_in_controller_latency": False,
    }


def _episode_map(report: Mapping[str, Any], *, arm: str, contract: V8DevelopmentGateContract):
    episodes = _list(report.get("episodes"), f"{arm}.episodes")
    if len(episodes) != V8_DEVELOPMENT_PAIR_COUNT:
        raise V8PromotionGateError(f"{arm} must contain exactly 30 episodes")
    result: dict[tuple[int, int], Mapping[str, Any]] = {}
    for raw in episodes:
        episode = _mapping(raw, f"{arm} episode")
        key = (
            _integer(episode.get("world_index"), f"{arm}.world_index"),
            _integer(episode.get("trial"), f"{arm}.trial"),
        )
        if key in result:
            raise V8PromotionGateError(f"{arm} contains duplicate world/trial evidence")
        result[key] = episode
    expected = {(world_id, 0) for world_id in contract.world_ids}
    if set(result) != expected:
        raise V8PromotionGateError(f"{arm} world/trial membership changed")
    for (world_id, trial_id), episode in result.items():
        expected_seed = contract.suite_seed + world_id * 1_009 + trial_id
        if _integer(episode.get("episode_seed"), "episode_seed") != expected_seed:
            raise V8PromotionGateError(f"{arm} episode seed mismatch for world {world_id}")
    return result


def _validate_report_protocol(
    report: Mapping[str, Any],
    contract: V8DevelopmentGateContract,
) -> tuple[Mapping[str, Any], Mapping[str, Any], dict[tuple[int, int], Mapping[str, Any]], dict[tuple[int, int], Mapping[str, Any]]]:
    if report.get("official_gazebo_score") is not False:
        raise V8PromotionGateError("V8 development output must be explicitly non-official")
    baseline = _mapping(report.get("baseline"), "baseline")
    candidate = _mapping(report.get("candidate"), "candidate")
    for arm, arm_report, expected_policy_sha in (
        ("reference", baseline, contract.reference_policy_metadata_sha256),
        ("candidate", candidate, contract.candidate_policy_metadata_sha256),
    ):
        if arm_report.get("official_gazebo_score") is not False:
            raise V8PromotionGateError(f"{arm} report must be explicitly non-official")
        if arm_report.get("suite_seed") != contract.suite_seed:
            raise V8PromotionGateError(f"{arm} suite seed changed")
        if canonical_json_sha256(arm_report.get("native_config")) != contract.native_config_sha256:
            raise V8PromotionGateError(f"{arm} calibrated native config changed")
        benchmark = _mapping(arm_report.get("benchmark"), f"{arm}.benchmark")
        if benchmark.get("asset_manifest_sha256") != contract.manifest_sha256:
            raise V8PromotionGateError(f"{arm} asset manifest identity changed")
        if benchmark.get("public_world_indices") != list(contract.world_ids):
            raise V8PromotionGateError(f"{arm} world order changed")
        execution = _mapping(arm_report.get("execution"), f"{arm}.execution")
        if (
            execution.get("episode_workers_requested") != contract.workers
            or execution.get("episode_workers_effective") != contract.workers
            or execution.get("process_start_method") != "spawn"
            or execution.get("paired_episode_execution") is not True
            or execution.get("arms_concurrent_within_pair") is not False
        ):
            raise V8PromotionGateError(f"{arm} isolated paired execution protocol changed")
        if canonical_json_sha256(arm_report.get("policy")) != expected_policy_sha:
            raise V8PromotionGateError(f"{arm} policy/runtime identity changed")

    preflight = _mapping(report.get("v8_preflight"), "v8_preflight")
    expected_preflight = {
        "corpus_sha256": contract.corpus_sha256,
        "exact_one_factor_policy_delta": True,
        "isolated_runtime_parity": True,
        "isolated_runtime_pair_sha256": contract.isolated_runtime_pair_sha256,
        "manifest_sha256": contract.manifest_sha256,
        "one_factor_delta_sha256": contract.one_factor_delta_sha256,
    }
    if dict(preflight) != expected_preflight:
        raise V8PromotionGateError("one-factor/runtime preflight identity changed")

    paired = _mapping(report.get("comparison"), "comparison")
    paired_execution = _mapping(paired.get("paired_execution"), "paired_execution")
    if (
        paired_execution.get("pair_count") != V8_DEVELOPMENT_PAIR_COUNT
        or paired_execution.get("arms_never_concurrent_within_pair") is not True
        or paired_execution.get("same_world_config_trial_and_seed_within_pair") is not True
    ):
        raise V8PromotionGateError("paired execution lifecycle changed")
    order_counts = _mapping(paired_execution.get("order_counts"), "order_counts")
    if dict(order_counts) != {
        REFERENCE_THEN_CANDIDATE: 15,
        CANDIDATE_THEN_REFERENCE: 15,
    }:
        raise V8PromotionGateError("paired first-position counts are not exactly 15/15")
    schedule = _list(paired_execution.get("schedule"), "paired schedule")
    expected_schedule = [
        {
            "world_index": world_id,
            "trial": 0,
            "episode_seed": contract.suite_seed + world_id * 1_009,
            "arm_order": contract.arm_order_schedule[index],
        }
        for index, world_id in enumerate(contract.world_ids)
    ]
    if schedule != expected_schedule:
        raise V8PromotionGateError("paired world/trial/seed/order schedule changed")
    if paired.get("same_worlds_trials_config_and_seeds") is not True:
        raise V8PromotionGateError("paired comparison denied input parity")
    if paired.get("paired_episode_count") != V8_DEVELOPMENT_PAIR_COUNT:
        raise V8PromotionGateError("paired comparison episode count changed")

    reference_episodes = _episode_map(baseline, arm="reference", contract=contract)
    candidate_episodes = _episode_map(candidate, arm="candidate", contract=contract)
    return baseline, candidate, reference_episodes, candidate_episodes


def _safe_evidence_path(root: Path, relative_value: object) -> Path:
    if not isinstance(relative_value, str):
        raise V8PromotionGateError("evidence relative_path must be a string")
    relative = PurePosixPath(relative_value)
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise V8PromotionGateError("evidence relative_path is unsafe")
    target = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise V8PromotionGateError(f"symbolic-link evidence paths are forbidden: {current}")
    resolved = target.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise V8PromotionGateError("evidence path escapes its frozen root") from exc
    return resolved


def _action_signature(record: Any) -> bytes:
    return struct.pack(
        "<ddd?",
        record.published_vx_mps,
        record.published_vy_mps,
        record.published_yaw_rate_rps,
        record.published_stop,
    )


def _verify_entry_identity(
    entry: Mapping[str, Any],
    read_result: V8ActionEvidenceReadResult,
) -> None:
    identity = _mapping(entry.get("identity"), "evidence identity")
    if dict(identity) != read_result.identity.as_dict():
        raise V8PromotionGateError("evidence index identity differs from verified artifact")
    write_overhead = _mapping(entry.get("write_overhead"), "evidence write overhead")
    initial_read_overhead = _mapping(
        entry.get("initial_read_verification_overhead"),
        "initial evidence read-verification overhead",
    )
    required = {
        "operation",
        "certificate_recomputation_ns",
        "record_validation_and_encoding_ns",
        "compression_and_immutable_write_ns",
        "artifact_parse_and_verification_ns",
        "included_in_controller_latency",
    }
    for overhead, operation in (
        (write_overhead, "write"),
        (initial_read_overhead, "read_verify"),
    ):
        if set(overhead) != required or overhead.get("operation") != operation:
            raise V8PromotionGateError(f"evidence {operation} overhead schema changed")
        if overhead.get("included_in_controller_latency") is not False:
            raise V8PromotionGateError("evidence overhead leaked into controller latency")
        for name in required - {"operation", "included_in_controller_latency"}:
            value = overhead.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise V8PromotionGateError(f"evidence overhead {name} is invalid")


def _verify_action_evidence(
    *,
    evidence_index: Mapping[str, Any],
    evidence_root: str | Path,
    contract: V8DevelopmentGateContract,
    reference_episodes: Mapping[tuple[int, int], Mapping[str, Any]],
    candidate_episodes: Mapping[tuple[int, int], Mapping[str, Any]],
) -> tuple[dict[tuple[str, int, int], V8ActionEvidenceReadResult], dict[str, Any]]:
    if (
        evidence_index.get("schema_version") != V8_EVIDENCE_INDEX_SCHEMA_VERSION
        or evidence_index.get("kind") != V8_EVIDENCE_INDEX_KIND
        or evidence_index.get("run_id") != contract.run_id
        or evidence_index.get("corpus_id") != contract.corpus_id
        or evidence_index.get("corpus_sha256") != contract.corpus_sha256
        or evidence_index.get("manifest_sha256") != contract.manifest_sha256
        or evidence_index.get("profile_id")
        != FROZEN_V8_BARN_EVALUATOR_PROFILE.profile_id
        or evidence_index.get("profile_sha256")
        != FROZEN_V8_BARN_EVALUATOR_PROFILE.identity_sha256
        or evidence_index.get("entry_count") != 2 * V8_DEVELOPMENT_PAIR_COUNT
        or evidence_index.get("evidence_overhead_included_in_controller_latency") is not False
    ):
        raise V8PromotionGateError("action-evidence index identity changed")
    entries = _list(evidence_index.get("entries"), "evidence entries")
    if len(entries) != 2 * V8_DEVELOPMENT_PAIR_COUNT:
        raise V8PromotionGateError("action-evidence index must contain exactly 60 entries")

    unresolved_root = Path(evidence_root).expanduser().absolute()
    if unresolved_root.is_symlink() or not unresolved_root.is_dir():
        raise V8PromotionGateError("action-evidence root is missing or unsafe")
    root = unresolved_root.resolve()
    for parent in (root, *root.parents):
        if parent.is_symlink():
            raise V8PromotionGateError("action-evidence root contains a symbolic-link component")
    expected_paths = expected_v8_evidence_paths(root, world_ids=contract.world_ids)
    actual_files: set[Path] = set()
    for candidate in root.iterdir():
        if candidate.is_symlink() or not candidate.is_file():
            raise V8PromotionGateError("evidence root contains an unindexed or unsafe entry")
        actual_files.add(candidate.resolve())
    if actual_files != {path.resolve() for path in expected_paths.values()}:
        raise V8PromotionGateError("evidence files are missing, duplicated, or unindexed")

    results: dict[tuple[str, int, int], V8ActionEvidenceReadResult] = {}
    total_write_overhead_ns = 0
    total_initial_read_overhead_ns = 0
    total_read_overhead_ns = 0
    all_rays_classified = True
    all_candidate_boundaries_satisfied = True
    candidate_violation_count = 0
    unavailable_translation_count = 0
    unavailable_nonstop_count = 0
    global_nearest_not_limiting_count = 0
    for raw_entry in entries:
        entry = _mapping(raw_entry, "evidence entry")
        if set(entry) != {
            "relative_path",
            "identity",
            "write_overhead",
            "initial_read_verification_overhead",
        }:
            raise V8PromotionGateError("evidence entry fields changed")
        identity = _mapping(entry.get("identity"), "evidence identity")
        arm = identity.get("arm")
        world_id = _integer(identity.get("world_id"), "evidence world_id")
        trial_id = _integer(identity.get("trial_id"), "evidence trial_id")
        if arm not in _ARMS:
            raise V8PromotionGateError("evidence arm is invalid")
        key = (str(arm), world_id, trial_id)
        if key in results:
            raise V8PromotionGateError("duplicate action-evidence episode identity")
        if world_id not in contract.world_ids or trial_id != 0:
            raise V8PromotionGateError("unexpected action-evidence episode identity")
        pair_index = contract.world_ids.index(world_id)
        order = contract.arm_order_schedule[pair_index]
        expected_order = int(
            (order == REFERENCE_THEN_CANDIDATE and arm == "candidate")
            or (order == CANDIDATE_THEN_REFERENCE and arm == "reference")
        )
        if identity.get("execution_order") != expected_order:
            raise V8PromotionGateError("action-evidence execution order changed")
        expected_seed = contract.suite_seed + world_id * 1_009
        if identity.get("seed") != expected_seed:
            raise V8PromotionGateError("action-evidence episode seed changed")
        expected_relative = v8_evidence_relative_path(str(arm), world_id, trial_id)
        if entry.get("relative_path") != expected_relative:
            raise V8PromotionGateError("action-evidence path naming changed")
        path = _safe_evidence_path(root, entry.get("relative_path"))
        metadata = os.lstat(path)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & _WRITE_BITS:
            raise V8PromotionGateError("action evidence must be an immutable regular file")
        expected_artifact_sha = _require_sha256(
            identity.get("artifact_sha256"), "evidence artifact_sha256"
        )
        try:
            read_result = read_v8_action_evidence(
                path,
                expected_artifact_sha256=expected_artifact_sha,
            )
        except (OSError, ValueError) as exc:
            raise V8PromotionGateError(f"action evidence failed verification: {path}") from exc
        _verify_entry_identity(entry, read_result)
        if (
            read_result.identity.format_id != V8_ACTION_EVIDENCE_FORMAT_ID
            or read_result.identity.format_version != V8_ACTION_EVIDENCE_VERSION
        ):
            raise V8PromotionGateError("action-evidence format identity changed")

        episode = (
            reference_episodes[(world_id, trial_id)]
            if arm == "reference"
            else candidate_episodes[(world_id, trial_id)]
        )
        sensor = _mapping(episode.get("sensor_diagnostics"), "episode sensor diagnostics")
        shield = _mapping(episode.get("shield_stall_diagnostics"), "episode shield diagnostics")
        action_steps = _list(sensor.get("published_action_steps"), "published action steps")
        action_values = _list(sensor.get("published_action_values"), "published actions")
        observation_steps = _list(sensor.get("policy_observation_steps"), "observation steps")
        if (
            read_result.identity.record_count != len(action_steps)
            or len(read_result.records) != len(action_steps)
            or len(action_values) != len(action_steps)
            or _integer(episode.get("steps"), "episode steps") != len(action_steps)
        ):
            raise V8PromotionGateError("evidence action count does not match published steps")
        if _integer(shield.get("issued_policy_command_steps"), "issued policy steps") != len(
            observation_steps
        ):
            raise V8PromotionGateError("policy observation/issued-action count changed")
        if _integer(sensor.get("frame_count"), "normalized frame count") != len(
            observation_steps
        ):
            raise V8PromotionGateError("normalization frame count changed")

        issued_steps: list[int] = []
        for index, record in enumerate(read_result.records):
            step = _integer(action_steps[index], "published action step")
            if record.step_index != step:
                raise V8PromotionGateError("evidence step differs from published action step")
            raw_action = action_values[index]
            if not isinstance(raw_action, (list, tuple)) or len(raw_action) != 4:
                raise V8PromotionGateError("published action value is malformed")
            if (
                _integer(raw_action[0], "published action value step") != step
                or not _same_float(raw_action[1], record.published_vx_mps, name="published vx")
                or not _same_float(
                    raw_action[2], record.published_yaw_rate_rps, name="published yaw"
                )
                or not isinstance(raw_action[3], bool)
                or raw_action[3] is not record.published_stop
            ):
                raise V8PromotionGateError("evidence action differs from published action")
            if record.issued_by_policy:
                issued_steps.append(step)
            certificate = record.certificate
            classified = (
                certificate.ray_count == V8_REQUIRED_RAYS
                and certificate.examined_ray_count == V8_REQUIRED_RAYS
                and certificate.finite_return_count
                + certificate.clear_ray_count
                + certificate.unavailable_ray_count
                == V8_REQUIRED_RAYS
            )
            all_rays_classified = all_rays_classified and classified
            if arm == "candidate":
                candidate_violation_count += certificate.violating_return_count
                all_candidate_boundaries_satisfied = (
                    all_candidate_boundaries_satisfied
                    and certificate.observed_return_boundary_satisfied
                )
                if not certificate.perception_available:
                    unavailable_translation_count += int(record.published_vx_mps != 0.0)
                    unavailable_nonstop_count += int(not record.published_stop)
                finite = [
                    (ray_index, value)
                    for ray_index, value in enumerate(record.normalized_scan_m)
                    if math.isfinite(value)
                ]
                if finite and certificate.limiting_ray_index is not None:
                    minimum_range = min(value for _ray_index, value in finite)
                    nearest_indices = {
                        ray_index for ray_index, value in finite if value == minimum_range
                    }
                    if certificate.limiting_ray_index not in nearest_indices:
                        global_nearest_not_limiting_count += 1
        if issued_steps != [_integer(value, "observation step") for value in observation_steps]:
            raise V8PromotionGateError("evidence issued-action steps differ from observations")

        write_overhead = _mapping(entry["write_overhead"], "write overhead")
        total_write_overhead_ns += sum(
            _integer(write_overhead[name], f"write overhead {name}")
            for name in (
                "certificate_recomputation_ns",
                "record_validation_and_encoding_ns",
                "compression_and_immutable_write_ns",
                "artifact_parse_and_verification_ns",
            )
        )
        initial_read_overhead = _mapping(
            entry["initial_read_verification_overhead"], "initial read overhead"
        )
        total_initial_read_overhead_ns += sum(
            _integer(initial_read_overhead[name], f"initial read overhead {name}")
            for name in (
                "certificate_recomputation_ns",
                "record_validation_and_encoding_ns",
                "compression_and_immutable_write_ns",
                "artifact_parse_and_verification_ns",
            )
        )
        total_read_overhead_ns += sum(
            int(value)
            for name, value in read_result.overhead.as_dict().items()
            if name.endswith("_ns")
        )
        results[key] = read_result

    expected_keys = {
        (arm, world_id, 0) for world_id in contract.world_ids for arm in _ARMS
    }
    if set(results) != expected_keys:
        raise V8PromotionGateError("action-evidence episode membership is incomplete")
    return results, {
        "all_720_rays_classified": all_rays_classified,
        "candidate_observed_return_boundary_satisfied": all_candidate_boundaries_satisfied,
        "candidate_observed_return_violation_count": candidate_violation_count,
        "candidate_perception_unavailable_translation_count": unavailable_translation_count,
        "candidate_perception_unavailable_nonstop_count": unavailable_nonstop_count,
        "global_nearest_not_limiting_action_count": global_nearest_not_limiting_count,
        "verified_artifact_count": len(results),
        "verified_action_count": sum(len(result.records) for result in results.values()),
        "evidence_write_overhead_ns": total_write_overhead_ns,
        "evidence_initial_read_verify_overhead_ns": total_initial_read_overhead_ns,
        "evidence_read_verify_overhead_ns": total_read_overhead_ns,
        "evidence_overhead_included_in_controller_latency": False,
    }


def _independent_mode_affected_count(
    evidence: Mapping[tuple[str, int, int], V8ActionEvidenceReadResult],
    contract: V8DevelopmentGateContract,
) -> tuple[int, list[dict[str, Any]]]:
    affected: list[dict[str, Any]] = []
    for world_id in contract.world_ids:
        reference = {record.step_index: record for record in evidence[("reference", world_id, 0)].records}
        candidate = {record.step_index: record for record in evidence[("candidate", world_id, 0)].records}
        common_steps = sorted(reference.keys() & candidate.keys())
        first_divergence = next(
            (
                step
                for step in common_steps
                if _action_signature(reference[step]) != _action_signature(candidate[step])
            ),
            None,
        )
        if first_divergence is None:
            continue
        left = reference[first_divergence]
        right = candidate[first_divergence]
        exact_observation = (
            left.issued_by_policy
            and right.issued_by_policy
            and left.normalized_scan_float64_le == right.normalized_scan_float64_le
            and struct.pack("<dd", left.angle_min_rad, left.angle_increment_rad)
            == struct.pack("<dd", right.angle_min_rad, right.angle_increment_rad)
        )
        if exact_observation:
            affected.append(
                {
                    "world_index": world_id,
                    "trial": 0,
                    "first_divergence_step": first_divergence,
                    "normalized_scan_float64_sha256": left.normalized_scan_float64_sha256,
                }
            )
    return len(affected), affected


def _crosscheck_aggregates(
    arm_report: Mapping[str, Any],
    episodes: Mapping[tuple[int, int], Mapping[str, Any]],
    *,
    arm: str,
) -> Mapping[str, Any]:
    aggregate = _mapping(arm_report.get("aggregate"), f"{arm}.aggregate")
    count = len(episodes)
    expected = {
        "success_rate": sum(bool(item.get("success")) for item in episodes.values()) / count,
        "collision_rate": sum(bool(item.get("collided")) for item in episodes.values()) / count,
        "timeout_rate": sum(str(item.get("status")) == "timeout" for item in episodes.values())
        / count,
        "navigation_metric": sum(
            _finite(item.get("navigation_metric"), f"{arm}.navigation_metric")
            for item in episodes.values()
        )
        / count,
    }
    for name, value in expected.items():
        if not math.isclose(
            _finite(aggregate.get(name), f"{arm}.aggregate.{name}"),
            value,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise V8PromotionGateError(f"{arm} aggregate {name} is inconsistent with episodes")
    return aggregate


def evaluate_v8_promotion_gate(
    report: Mapping[str, Any],
    *,
    evidence_index: Mapping[str, Any],
    evidence_root: str | Path,
    contract: V8DevelopmentGateContract,
) -> tuple[dict[str, bool], dict[str, Any]]:
    """Recertify all evidence and evaluate the frozen V8 development gate."""

    baseline, candidate, reference_episodes, candidate_episodes = _validate_report_protocol(
        report, contract
    )
    reference_aggregate = _crosscheck_aggregates(
        baseline, reference_episodes, arm="reference"
    )
    candidate_aggregate = _crosscheck_aggregates(
        candidate, candidate_episodes, arm="candidate"
    )
    evidence, evidence_diagnostics = _verify_action_evidence(
        evidence_index=evidence_index,
        evidence_root=evidence_root,
        contract=contract,
        reference_episodes=reference_episodes,
        candidate_episodes=candidate_episodes,
    )
    mode_affected_count, affected_pairs = _independent_mode_affected_count(evidence, contract)

    comparison = _mapping(report.get("comparison"), "comparison")
    paired_episodes = _list(comparison.get("paired_episodes"), "paired episodes")
    if len(paired_episodes) != V8_DEVELOPMENT_PAIR_COUNT:
        raise V8PromotionGateError("paired diagnostics must contain exactly 30 pairs")
    paired_by_key: dict[tuple[int, int], Mapping[str, Any]] = {}
    for raw in paired_episodes:
        item = _mapping(raw, "paired episode")
        key = (
            _integer(item.get("world_index"), "paired world_index"),
            _integer(item.get("trial"), "paired trial"),
        )
        if key in paired_by_key:
            raise V8PromotionGateError("paired diagnostics contain a duplicate")
        paired_by_key[key] = item
    if set(paired_by_key) != set(reference_episodes):
        raise V8PromotionGateError("paired diagnostic membership changed")

    success_gains = 0
    success_regressions = 0
    for key in reference_episodes:
        reference_success = bool(reference_episodes[key].get("success"))
        candidate_success = bool(candidate_episodes[key].get("success"))
        success_gains += int(candidate_success and not reference_success)
        success_regressions += int(reference_success and not candidate_success)
        expected_delta = int(candidate_success) - int(reference_success)
        if _integer(paired_by_key[key].get("success_delta"), "paired success_delta") != expected_delta:
            raise V8PromotionGateError("paired success delta is inconsistent with episodes")

    comparison_affected = _integer(
        comparison.get("mode_affected_episode_count"), "mode affected episode count"
    )
    if comparison_affected != mode_affected_count:
        raise V8PromotionGateError(
            "paired-report mode-affected count differs from independent exact evidence"
        )
    for affected in affected_pairs:
        pair = paired_by_key[(affected["world_index"], affected["trial"])]
        if (
            pair.get("mode_affected") is not True
            or pair.get("first_divergence_on_identical_policy_observation") is not True
            or pair.get("first_published_action_divergence_step")
            != affected["first_divergence_step"]
        ):
            raise V8PromotionGateError("paired causal diagnostics differ from action evidence")

    reference_timeout_rate = _finite(reference_aggregate.get("timeout_rate"), "reference timeout")
    candidate_timeout_rate = _finite(candidate_aggregate.get("timeout_rate"), "candidate timeout")
    success_rate_delta = _finite(candidate_aggregate.get("success_rate"), "candidate success") - _finite(
        reference_aggregate.get("success_rate"), "reference success"
    )
    navigation_metric_delta = _finite(
        candidate_aggregate.get("navigation_metric"), "candidate navigation metric"
    ) - _finite(reference_aggregate.get("navigation_metric"), "reference navigation metric")
    candidate_clearances = []
    for episode in candidate_episodes.values():
        evaluator = _mapping(episode.get("evaluator_diagnostics"), "candidate evaluator diagnostics")
        candidate_clearances.append(
            _finite(
                evaluator.get("minimum_signed_obstacle_clearance_m"),
                "candidate minimum signed body clearance",
            )
        )
    candidate_minimum_clearance = min(candidate_clearances)
    reference_p99 = _finite(
        reference_aggregate.get("controller_step_p99_ms"), "reference controller p99"
    )
    candidate_p99 = _finite(
        candidate_aggregate.get("controller_step_p99_ms"), "candidate controller p99"
    )
    if reference_p99 <= 0.0:
        latency_ratio = 1.0 if candidate_p99 == 0.0 else math.inf
    else:
        latency_ratio = candidate_p99 / reference_p99

    minimum_clearance = _promotion_number(
        "minimum_candidate_signed_body_clearance_m",
        "minimum_signed_body_clearance_m",
        "minimum_signed_clearance_must_be_at_least",
    )
    minimum_success_gains = int(
        _promotion_number("minimum_success_gains", "minimum_paired_success_gains")
    )
    minimum_success_delta = _promotion_number(
        "minimum_success_rate_delta", "minimum_candidate_minus_reference_success_rate"
    )
    minimum_navigation_delta = _promotion_number(
        "minimum_navigation_metric_delta",
        "minimum_candidate_minus_reference_navigation_metric",
    )
    maximum_controller_p99 = _promotion_number(
        "maximum_controller_p99_latency_ms", "maximum_candidate_controller_p99_ms"
    )
    maximum_controller_ratio = _promotion_number(
        "maximum_controller_p99_latency_ratio",
        "maximum_candidate_to_reference_controller_p99_ratio",
    )
    if not math.isclose(
        minimum_clearance,
        V8_MINIMUM_SIGNED_BODY_CLEARANCE_M,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise V8PromotionGateError("frozen V8 signed-clearance threshold changed")

    gates = {
        "exact_one_factor_policy_delta_and_isolated_runtime_parity": True,
        "identical_world_trial_seed_config_and_counterbalanced_schedule": True,
        "fully_verified_immutable_action_evidence": evidence_diagnostics[
            "verified_artifact_count"
        ]
        == 60,
        "all_actions_classify_exactly_720_rays": bool(
            evidence_diagnostics["all_720_rays_classified"]
        ),
        "zero_candidate_observed_return_certificate_violations": bool(
            evidence_diagnostics["candidate_observed_return_boundary_satisfied"]
            and evidence_diagnostics["candidate_observed_return_violation_count"] == 0
        ),
        "zero_candidate_translation_when_perception_unavailable": (
            evidence_diagnostics["candidate_perception_unavailable_translation_count"] == 0
        ),
        "zero_candidate_collisions": all(
            not bool(episode.get("collided")) for episode in candidate_episodes.values()
        ),
        "candidate_minimum_signed_body_clearance": candidate_minimum_clearance
        >= minimum_clearance - 1e-12,
        "candidate_timeout_rate_not_above_reference": candidate_timeout_rate
        <= reference_timeout_rate + 1e-12,
        "zero_paired_success_regressions": success_regressions == 0,
        "minimum_success_gains": success_gains >= minimum_success_gains,
        "minimum_success_rate_delta": success_rate_delta >= minimum_success_delta - 1e-12,
        "minimum_navigation_metric_delta": navigation_metric_delta
        >= minimum_navigation_delta - 1e-12,
        "mode_affected_identical_first_divergence_observation": mode_affected_count >= 1,
        "global_nearest_not_limiting_case_exercised": evidence_diagnostics[
            "global_nearest_not_limiting_action_count"
        ]
        >= 1,
        "candidate_controller_p99_latency": candidate_p99 <= maximum_controller_p99,
        "candidate_to_reference_controller_p99_ratio": latency_ratio
        <= maximum_controller_ratio,
        "evidence_overhead_separate_from_controller_latency": (
            evidence_diagnostics["evidence_overhead_included_in_controller_latency"] is False
            and not any("evidence" in str(key).lower() for key in candidate_aggregate)
            and not any("evidence" in str(key).lower() for key in reference_aggregate)
        ),
    }
    diagnostics = {
        "gate_id": V8_GATE_ID,
        "promotion_gate": dict(PROMOTION_GATE),
        "success_gains": success_gains,
        "success_regressions": success_regressions,
        "reference_success_rate": reference_aggregate["success_rate"],
        "candidate_success_rate": candidate_aggregate["success_rate"],
        "success_rate_delta": success_rate_delta,
        "reference_navigation_metric": reference_aggregate["navigation_metric"],
        "candidate_navigation_metric": candidate_aggregate["navigation_metric"],
        "navigation_metric_delta": navigation_metric_delta,
        "reference_timeout_rate": reference_timeout_rate,
        "candidate_timeout_rate": candidate_timeout_rate,
        "candidate_minimum_signed_body_clearance_m": candidate_minimum_clearance,
        "reference_controller_p99_ms": reference_p99,
        "candidate_controller_p99_ms": candidate_p99,
        "candidate_to_reference_controller_p99_ratio": latency_ratio,
        "mode_affected_identical_observation_pair_count": mode_affected_count,
        "mode_affected_pairs": affected_pairs,
        **evidence_diagnostics,
        "all_conditions_passed": all(gates.values()),
        "official_score": False,
        "leaderboard_claim": False,
        "holdout_evaluated": False,
    }
    return gates, diagnostics


def freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Small helper for callers that want a read-only gate record in memory."""

    return MappingProxyType(dict(value))


__all__ = [
    "V8_DEVELOPMENT_PAIR_COUNT",
    "V8_EPISODE_WORKERS",
    "V8_EVIDENCE_INDEX_KIND",
    "V8_GATE_ID",
    "V8_MINIMUM_SIGNED_BODY_CLEARANCE_M",
    "V8DevelopmentGateContract",
    "V8PromotionGateError",
    "build_v8_evidence_index",
    "build_v8_evidence_index_from_report",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "evaluate_v8_promotion_gate",
    "expected_v8_evidence_paths",
    "v8_evidence_artifact_name",
    "v8_evidence_relative_path",
]
