"""Authenticate and publish the frozen V10 planner-profile candidate.

The freeze authorizes repeatable training-screen worlds 5000--5009 only.  It
does not authorize development, holdout, deployment, or a simulator run by
itself.  This module is the sole candidate-specific materialization entry
point; it re-authenticates the raw freeze, its S4-derived gate, the exact V8
parent, and the recomputed one-file plan before delegating publication.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .barn_profile_candidate_bundle import (
    PlannerProfileCandidateBundle,
    PlannerProfileCandidatePlan,
    prepare_planner_profile_candidate,
)
from .barn_v10_planner_profile_candidate import (
    PROFILE_DESTINATION,
    PROFILE_SOURCE,
    V10_PLANNER_PROFILE_SPEC,
    plan_v10_planner_profile_candidate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ROOT = REPO_ROOT / "evals/external/experiments/barn_planner_profile_v10"
CANDIDATE_FREEZE_PATH = EXPERIMENT_ROOT / "CANDIDATE_FREEZE.json"
S4_FREEZE_PATH = (
    REPO_ROOT
    / "evals/external/experiments/barn_sampled_predictive_tracker_v9/scratch_challengers"
    / "supervisory_gap_s4/SCRATCH_FREEZE.json"
)

CANDIDATE_FREEZE_SHA256 = "7d0b97a30a7e4196c35b4f28c12229b0a3f9ff4c884868dff8131e72aac911e8"
PROFILE_SHA256 = "c9f14b5bb50a3139ccb30a853fd1f5b321ac78d9632ec8b78a49831d9ab4926a"
REFERENCE_PROFILE_SHA256 = "0d0700f8568d62f17d8b8c707ba2ec46e9c8539c626fb95d3eda201fa08f297b"
CANDIDATE_PACKAGE_SHA256 = "f0b3c15763887d2023e42a4515073227d51d8c11e3c527b5f7bf1f90bac7a655"
CANDIDATE_MANIFEST_SHA256 = "c7b08d55637602940c444314e9b702dd8b4da5ea966950bcdd82efdaaf116f61"
NAVIGATION_CONFIG_SHA256 = "22fa34207e85eb8ece4e019900738dff13cc2fce17244ddb8c8074b3fba3f794"
REFERENCE_PACKAGE_SHA256 = "189ac31f0f6a461da9e10fad2ac21b2bc3a485a4d5245c517b1492b2a16eb7d9"
REFERENCE_MANIFEST_SHA256 = "d3bca126041d69afb5553ac29656a0152242c00f29a7b987803e9dc536914115"
S4_FREEZE_SHA256 = "a26c32c92f85bd4e3d63f042578d8a5c9b3d66ef8c6690dde91a00797a140b9c"

S2_PACKAGE_SHA256 = "68e3e66638aea3549bb26618c6b29e02a8e2a309726dddc55c4ef53ad5a0159c"
S2_MANIFEST_SHA256 = "04867ea70a7c4f7f0d9f6383815e2d592df635eafb2d8833e193f70d4de4dad7"
S2_REPORT_SHA256 = "3ccce81f675a7556fa9618cb8c14dfea1ff5f0d35cd17732699dcaa49157962d"
S2_ANALYSIS_SHA256 = "1cc259ed55ee96ccfae9d784d9734924a7537f0e9da9b80418c05cc645a6ff9f"
S2_TRAINING_GATE_SHA256 = "254d53ac946c19a5c73dcfc6651f7e2f9c6b25911c2d8d4c43d8ea34f0e3"

TRAINING_WORLD_IDS = tuple(range(5000, 5010))
V10_GATE_ID = "parcel-v10-planner-profile-training-screen10-gate-v1"
S4_GATE_ID = "parcel-v9-supervisory-gap-s4-training-screen10-gate-v1"
V8_CONTROLLER_ID = "parcel-directive-navigator-grid-v1-v8-all-ray"

_TOP_LEVEL_KEYS = {
    "candidate",
    "deployment_enabled",
    "development_execution_authorized",
    "experimental",
    "freeze_id",
    "frozen_before_materialization",
    "holdout_execution_authorized",
    "one_factor_delta",
    "profile_semantics",
    "reference",
    "schema_version",
    "scratch_gate_lineage",
    "scratch_screen",
    "training_execution_authorization",
}


class V10PlannerProfileError(RuntimeError):
    """Raised when the V10 candidate differs from its pre-materialization freeze."""


@dataclass(frozen=True, slots=True)
class VerifiedV10PlannerProfile:
    plan: PlannerProfileCandidatePlan
    freeze_path: Path
    freeze_sha256: str
    freeze: dict[str, Any]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise V10PlannerProfileError("freeze must contain finite JSON data") from error


def _lexical_absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _strict_json(raw: bytes, *, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise V10PlannerProfileError(f"{label} contains duplicate field: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> NoReturn:
        raise V10PlannerProfileError(f"{label} contains non-finite value: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise V10PlannerProfileError(f"{label} is not strict JSON") from error
    if not isinstance(value, dict):
        raise V10PlannerProfileError(f"{label} must contain an object")
    return value


def _read_unique_regular(path: str | Path, *, label: str) -> tuple[Path, bytes]:
    requested = _lexical_absolute(path)
    for component in (requested, *requested.parents):
        if os.path.lexists(component) and stat.S_ISLNK(os.lstat(component).st_mode):
            raise V10PlannerProfileError(f"{label} path contains a symbolic link: {component}")
    try:
        metadata = os.lstat(requested)
    except FileNotFoundError:
        raise V10PlannerProfileError(f"{label} is missing: {requested}") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise V10PlannerProfileError(f"{label} must be a uniquely linked regular file")
    return requested, requested.read_bytes()


def _expected_candidate() -> dict[str, Any]:
    return {
        "active_model": "grid_v1",
        "controller_id": V8_CONTROLLER_ID,
        "manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "package_sha256": CANDIDATE_PACKAGE_SHA256,
        "profile_sha256": PROFILE_SHA256,
    }


def _expected_reference() -> dict[str, Any]:
    return {
        "development_gate_passed": False,
        "deployment_enabled": False,
        "manifest_sha256": REFERENCE_MANIFEST_SHA256,
        "package_sha256": REFERENCE_PACKAGE_SHA256,
        "role": "rejected_v8_experimental_control_only",
    }


def _expected_gate_lineage() -> dict[str, Any]:
    return {
        "numeric_thresholds_copied_exactly_from_s4": True,
        "s2_incumbent": {
            "analysis_sha256": S2_ANALYSIS_SHA256,
            "manifest_sha256": S2_MANIFEST_SHA256,
            "package_sha256": S2_PACKAGE_SHA256,
            "report_sha256": S2_REPORT_SHA256,
            "training_gate_sha256": S2_TRAINING_GATE_SHA256,
        },
        "s4_freeze_sha256": S4_FREEZE_SHA256,
        "s4_gate_id": S4_GATE_ID,
        "screen_substitutions": ["candidate_package_sha256", "gate_id"],
    }


def _screen_from_s4() -> dict[str, Any]:
    _path, raw = _read_unique_regular(S4_FREEZE_PATH, label="S4 gate freeze")
    if _sha256_bytes(raw) != S4_FREEZE_SHA256:
        raise V10PlannerProfileError("S4 gate freeze raw identity changed")
    s4 = _strict_json(raw, label="S4 gate freeze")
    screen = s4.get("scratch_screen")
    if not isinstance(screen, dict) or screen.get("gate_id") != S4_GATE_ID:
        raise V10PlannerProfileError("S4 gate freeze no longer contains its exact screen")
    expected = copy.deepcopy(screen)
    expected["candidate_package_sha256"] = CANDIDATE_PACKAGE_SHA256
    expected["gate_id"] = V10_GATE_ID
    return expected


def _verify_freeze_semantics(freeze: dict[str, Any]) -> None:
    if set(freeze) != _TOP_LEVEL_KEYS:
        raise V10PlannerProfileError("candidate freeze top-level membership is not exact")
    fixed = {
        "schema_version": 1,
        "freeze_id": "parcel-v10-planner-profile-training-candidate-freeze-v1",
        "frozen_before_materialization": True,
        "experimental": True,
        "deployment_enabled": False,
        "development_execution_authorized": False,
        "holdout_execution_authorized": False,
        "candidate": _expected_candidate(),
        "reference": _expected_reference(),
        "one_factor_delta": {
            "additions": [],
            "all_other_reference_payload_bytes_identical": True,
            "replacement": PROFILE_DESTINATION,
            "unchanged_reference_file_count": 116,
        },
        "profile_semantics": V10_PLANNER_PROFILE_SPEC.semantics_record(),
        "scratch_gate_lineage": _expected_gate_lineage(),
        "training_execution_authorization": {
            "all_other_worlds_authorized": False,
            "rerunnable": True,
            "world_ids": list(TRAINING_WORLD_IDS),
        },
    }
    for key, expected in fixed.items():
        if _canonical_json(freeze.get(key)) != _canonical_json(expected):
            raise V10PlannerProfileError(f"candidate freeze field is invalid: {key}")
    if _canonical_json(freeze.get("scratch_screen")) != _canonical_json(_screen_from_s4()):
        raise V10PlannerProfileError("candidate scratch screen changed from the exact S4 gate")


def verify_v10_planner_profile(
    *,
    freeze_path: str | Path = CANDIDATE_FREEZE_PATH,
    profile_source_path: str | Path = PROFILE_SOURCE,
) -> VerifiedV10PlannerProfile:
    """Authenticate raw freeze and recompute the exact one-file candidate plan."""

    checked_path, raw = _read_unique_regular(freeze_path, label="V10 candidate freeze")
    observed_sha = _sha256_bytes(raw)
    if observed_sha != CANDIDATE_FREEZE_SHA256:
        raise V10PlannerProfileError("candidate freeze raw identity changed")
    freeze = _strict_json(raw, label="V10 candidate freeze")
    _verify_freeze_semantics(freeze)
    try:
        plan = plan_v10_planner_profile_candidate(
            profile_source_path=profile_source_path,
            expected_reference_package_sha256=REFERENCE_PACKAGE_SHA256,
            expected_reference_manifest_sha256=REFERENCE_MANIFEST_SHA256,
        )
    except (FileNotFoundError, TypeError, ValueError) as error:
        raise V10PlannerProfileError("candidate plan could not be rederived") from error
    if (
        plan.profile_sha256 != PROFILE_SHA256
        or plan.package_sha256 != CANDIDATE_PACKAGE_SHA256
        or plan.manifest_sha256 != CANDIDATE_MANIFEST_SHA256
        or plan.reference.package_sha256 != REFERENCE_PACKAGE_SHA256
        or plan.reference.manifest_sha256 != REFERENCE_MANIFEST_SHA256
        or plan.reference.files_sha256.get(PROFILE_DESTINATION)
        != REFERENCE_PROFILE_SHA256
        or plan.reference.files_sha256.get(
            "configs/navigation/experiments/barn_grid_v1.yaml"
        )
        != NAVIGATION_CONFIG_SHA256
        or plan.delta.get("replacements") != [PROFILE_DESTINATION]
        or plan.delta.get("additions") != []
        or plan.delta.get("unchanged_reference_file_count") != 116
        or plan.delta.get("all_other_file_bytes_identical_to_reference") is not True
        or plan.delta.get("one_factor_planner_profile_delta") is not True
        or plan.delta.get("experiment_config_changed") is not False
        or plan.delta.get("active_model_id_changed") is not False
        or plan.delta.get("navigator_source_changed") is not False
        or plan.delta.get("grid_planner_source_changed") is not False
        or plan.delta.get("all_ray_safety_shield_changed") is not False
        or plan.delta.get("adapter_or_evaluator_source_changed") is not False
        or plan.delta.get("external_identity_freeze_required_before_real_materialization")
        is not True
        or plan.delta.get("training_only") is not True
        or plan.delta.get("development_execution_authorized") is not False
        or plan.delta.get("holdout_execution_authorized") is not False
        or plan.delta.get("deployment_enabled") is not False
    ):
        raise V10PlannerProfileError("candidate derivation differs from its freeze")
    return VerifiedV10PlannerProfile(
        plan=plan,
        freeze_path=checked_path,
        freeze_sha256=observed_sha,
        freeze=freeze,
    )


def prepare_v10_planner_profile_bundle(
    *,
    destination_root: str | Path,
) -> PlannerProfileCandidateBundle:
    """Publish only after the canonical pre-materialization freeze re-verifies."""

    verified = verify_v10_planner_profile()
    bundle = prepare_planner_profile_candidate(
        spec=V10_PLANNER_PROFILE_SPEC,
        profile_source_path=PROFILE_SOURCE,
        expected_candidate_package_sha256=CANDIDATE_PACKAGE_SHA256,
        expected_candidate_manifest_sha256=CANDIDATE_MANIFEST_SHA256,
        reference_root=verified.plan.reference.root,
        expected_reference_package_sha256=REFERENCE_PACKAGE_SHA256,
        expected_reference_manifest_sha256=REFERENCE_MANIFEST_SHA256,
        destination_root=destination_root,
    )
    if bundle.delta != verified.plan.delta:
        raise V10PlannerProfileError("materialized candidate differs from the frozen plan")
    return bundle


__all__ = [
    "CANDIDATE_FREEZE_PATH",
    "CANDIDATE_FREEZE_SHA256",
    "CANDIDATE_MANIFEST_SHA256",
    "CANDIDATE_PACKAGE_SHA256",
    "EXPERIMENT_ROOT",
    "NAVIGATION_CONFIG_SHA256",
    "PROFILE_SHA256",
    "REFERENCE_MANIFEST_SHA256",
    "REFERENCE_PACKAGE_SHA256",
    "REFERENCE_PROFILE_SHA256",
    "S2_ANALYSIS_SHA256",
    "S2_MANIFEST_SHA256",
    "S2_PACKAGE_SHA256",
    "S2_REPORT_SHA256",
    "S2_TRAINING_GATE_SHA256",
    "S4_FREEZE_SHA256",
    "TRAINING_WORLD_IDS",
    "V10PlannerProfileError",
    "VerifiedV10PlannerProfile",
    "prepare_v10_planner_profile_bundle",
    "verify_v10_planner_profile",
]
