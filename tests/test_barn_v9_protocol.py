from __future__ import annotations

import copy
import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest

from evals.external import barn_v9_protocol as protocol


def _write_protocol(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_all_identity_recipe_and_schedule_commitments_are_exact() -> None:
    assert protocol.TRAINING_WORLD_IDS == tuple(range(5000, 5100))
    assert protocol.DEVELOPMENT_WORLD_IDS == tuple(range(5100, 5130))
    assert protocol.HOLDOUT_WORLD_IDS == tuple(range(5130, 5150))
    assert protocol.TRAINING_WORLD_IDS_SHA256 == (
        "61b8b2769406e8f4e030fdd0a6c221f0023f2d5a1d9fe871c5bb39dcaaf2ea3e"
    )
    assert protocol.DEVELOPMENT_WORLD_IDS_SHA256 == (
        "ae25a4e10bb1527416b045a73e5e2740f5dbd8370fd57be4f11ff748e59a0b7a"
    )
    assert protocol.HOLDOUT_WORLD_IDS_SHA256 == (
        "7834ee138d61e040abd91fe560642be49dfcea86f7b7a69cd13dede3250f85ae"
    )
    assert protocol.TRAINING_CORPUS_SHA256 == (
        "40c260e32985123d648e4634f0c087ec3de8309494581b2a64ca1fd289d9907f"
    )
    assert protocol.TRAINING_MANIFEST_SHA256 == (
        "018b2863bd699a2856e264b6f7712c91ed7561de48ba2999a4a6b020f6ef16fd"
    )

    assert protocol.ORDER_SCHEDULE[::2] == ("candidate_then_reference",) * 15
    assert protocol.ORDER_SCHEDULE[1::2] == ("reference_then_candidate",) * 15
    assert protocol.ORDER_SCHEDULE_SHA256 == (
        "b50bc5c5d094b79d11a3873bba72f1e21841bc03ab001de8708915631bfeedd1"
    )
    assert protocol.canonical_json_sha256(list(protocol.ORDER_SCHEDULE)) == (
        protocol.ORDER_SCHEDULE_SHA256
    )
    assert protocol.EXECUTION_SCHEDULE[0] == {
        "arm_order": "candidate_then_reference",
        "episode_seed": 25406703,
        "trial": 0,
        "world_id": 5100,
    }
    assert protocol.EXECUTION_SCHEDULE[-1] == {
        "arm_order": "reference_then_candidate",
        "episode_seed": 25435964,
        "trial": 0,
        "world_id": 5129,
    }
    assert protocol.EXECUTION_SCHEDULE_SHA256 == (
        "862abf0ac155f993e4e772d272a89a73596ed349d5013a8de06c45f838fe0916"
    )
    assert protocol.canonical_json_sha256(list(protocol.EXECUTION_SCHEDULE)) == (
        protocol.EXECUTION_SCHEDULE_SHA256
    )

    recipe = protocol.holdout_recipe()
    assert recipe == {
        "acceptance": (
            "first connected upstream BARN map; no policy execution; geometry and difficulty "
            "analyses are descriptive and never admission filters"
        ),
        "generator_commit": "295ca5cc7b9b0ecea93013f0c49c5a1ca4352151",
        "parameter_algorithm": (
            "offset=world_id-5100; fill=(0.15,0.20,0.25,0.30)[(offset//3)%4]; "
            "smooth=(2,3,4)[offset%3]; rows=30; columns=30"
        ),
        "seed_algorithm": (
            "uint64_be(sha256(namespace + ':' + world_id + ':' + attempt)[0:8]) "
            "bitwise-and 0x7fffffff"
        ),
        "seed_namespace": ("parcel-barn-sampled-predictive-tracker-v9-evidence-corpus-20260803"),
        "world_ids": list(range(5130, 5150)),
    }
    assert protocol.HOLDOUT_RECIPE_COMMITMENT_SHA256 == (
        "fbb3ce7be6895722dce96de36288a4f572086b45afb51ea39c2b9cca33796e40"
    )
    assert protocol.canonical_json_sha256(recipe) == protocol.HOLDOUT_RECIPE_COMMITMENT_SHA256


def test_development_and_scaled_holdout_gates_are_frozen() -> None:
    document = protocol.protocol_document()
    development = document["development_gate"]
    assert development["minimum_paired_success_gains"] == 3
    assert development["minimum_label_independent_liveness_failure_count_reduction"] == 3
    assert development["minimum_mode_affected_paired_episodes"] == 15
    assert development["minimum_safe_escape_witness_count"] == 1
    assert development["required_liveness_thresholds"]["safe_escape_progress_m"] == 0.5
    assert development["minimum_candidate_signed_body_clearance_m"] == 0.475
    assert development["maximum_candidate_collisions"] == 0
    assert development["maximum_controller_p99_latency_ms"] == 100.0
    assert development["maximum_controller_p99_latency_ratio"] == 1.2

    holdout = document["holdout_gate"]["scaled_paired_gate"]
    assert holdout["minimum_paired_success_gains"] == 2
    assert holdout["minimum_label_independent_liveness_failure_count_reduction"] == 2
    assert holdout["minimum_mode_affected_paired_episodes"] == 10
    for unchanged in (
        "maximum_candidate_collisions",
        "maximum_candidate_observed_return_certificate_violations",
        "maximum_controller_p99_latency_ms",
        "maximum_controller_p99_latency_ratio",
        "maximum_paired_liveness_regressions",
        "maximum_paired_success_regressions",
        "minimum_candidate_signed_body_clearance_m",
        "minimum_navigation_metric_delta",
        "minimum_safe_escape_witness_count",
        "minimum_success_rate_delta",
        "required_classified_rays_per_policy_issued_action",
    ):
        assert holdout[unchanged] == development[unchanged]

    evidence = document["evidence_contract"]
    assert evidence["free_form_notes_may_not_establish_causal_metrics"] is True
    assert evidence["requested_action_or_shield_scale_may_not_be_inferred"] is True
    assert evidence["missing_structured_fields_remain_null_and_cannot_count_as_vetoes"] is True
    scope = document["benchmark_scope"]
    assert scope["native_development_can_establish_official_or_top_decile_status"] is False
    assert scope["official_score_or_rank_requires_external_organizer_attestation"] is True


def test_checked_in_protocol_and_complete_training_corpus_verify_fail_closed() -> None:
    verified = protocol.verify_v9_protocol()
    checked_in = json.loads(protocol.PROTOCOL_PATH.read_bytes())

    assert checked_in == protocol.protocol_document()
    assert verified.training_manifest_sha256 == protocol.TRAINING_MANIFEST_SHA256
    assert verified.training_corpus_sha256 == protocol.TRAINING_CORPUS_SHA256
    assert verified.candidate_freeze_sha256 == protocol.CANDIDATE_FREEZE_SHA256
    assert verified.final_development_candidate_selected is False
    assert verified.development_execution_authorized is False
    assert verified.holdout_execution_authorized is False
    assert verified.deployment_enabled is False
    fields = {item.name: item for item in dataclasses.fields(protocol.VerifiedV9Protocol)}
    for authority in (
        "final_development_candidate_selected",
        "development_execution_authorized",
        "holdout_execution_authorized",
        "deployment_enabled",
    ):
        assert fields[authority].init is False
    status = checked_in["declaration_status"]
    assert status["scratch_screening_authorized"] is True
    assert status["development_assets_materialized"] is False
    assert status["development_execution_started"] is False
    final_candidate = checked_in["policy_identity"]["final_development_candidate"]
    assert final_candidate["selected"] is False
    assert final_candidate["package_sha256"] is None
    assert final_candidate["manifest_sha256"] is None
    assert final_candidate["separate_content_addressed_selection_required"] is True

    with pytest.raises(protocol.V9ExecutionNotAuthorizedError, match="final-candidate"):
        protocol.require_v9_development_execution_authorization()
    with pytest.raises(protocol.V9ExecutionNotAuthorizedError, match="root supplies"):
        protocol.require_v9_holdout_execution_authorization()


def test_any_authority_threshold_or_provenance_mutation_is_rejected(
    tmp_path: Path,
) -> None:
    expected = protocol.protocol_document()
    mutations: list[dict[str, object]] = []

    for path, value in (
        (("declaration_status", "development_execution_authorized"), True),
        (("policy_identity", "final_development_candidate", "selected"), True),
        (("policy_identity", "final_development_candidate", "package_sha256"), "0" * 64),
        (("holdout_gate", "holdout_execution_authorized"), True),
        (("development_gate", "minimum_paired_success_gains"), 2),
        (("single_use_transaction_contract", "retry_allowed"), True),
        (("source_closure_contract", "closure_complete"), True),
        (("benchmark_scope", "top_decile_claim"), True),
    ):
        changed = copy.deepcopy(expected)
        target: Any = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        mutations.append(changed)

    candidate = tmp_path / "PROTOCOL.json"
    for mutation in mutations:
        _write_protocol(candidate, mutation)
        with pytest.raises(protocol.V9ProtocolError, match="differs from exact"):
            protocol.verify_v9_protocol(protocol_path=candidate)


def test_protocol_parser_rejects_duplicates_links_and_unauthorized_assets(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}\n', encoding="utf-8")
    with pytest.raises(protocol.V9ProtocolError, match="duplicate field"):
        protocol.verify_v9_protocol(protocol_path=duplicate)

    real = tmp_path / "real.json"
    _write_protocol(real, protocol.protocol_document())
    alias = tmp_path / "alias.json"
    alias.symlink_to(real)
    with pytest.raises(protocol.V9ProtocolError, match="symbolic link"):
        protocol.verify_v9_protocol(protocol_path=alias)

    development = tmp_path / "unauthorized-development"
    development.mkdir()
    with pytest.raises(protocol.V9ProtocolError, match="unauthorized V9 development assets"):
        protocol.verify_v9_protocol(development_assets_root=development)

    hardlink_source = tmp_path / "hardlink-source.json"
    _write_protocol(hardlink_source, protocol.protocol_document())
    hardlink = tmp_path / "hardlink.json"
    os.link(hardlink_source, hardlink)
    with pytest.raises(protocol.V9ProtocolError, match="uniquely linked"):
        protocol.verify_v9_protocol(protocol_path=hardlink)


def test_training_reverification_and_raw_identity_drift_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_training_verifier = protocol.verify_training_corpus
    monkeypatch.setattr(
        protocol,
        "verify_training_corpus",
        lambda _path: {
            "corpus_id": protocol.TRAINING_CORPUS_ID,
            "corpus_sha256": "0" * 64,
            "manifest_sha256": protocol.TRAINING_MANIFEST_SHA256,
            "promotion_evidence_eligible": False,
            "world_count": 100,
        },
    )
    with pytest.raises(protocol.V9ProtocolError, match="verification result is not exact"):
        protocol.verify_v9_protocol()
    monkeypatch.setattr(protocol, "verify_training_corpus", real_training_verifier)

    training = tmp_path / "training.json"
    training.write_bytes(protocol.TRAINING_MANIFEST_PATH.read_bytes() + b" ")
    with pytest.raises(protocol.V9ProtocolError, match="training manifest identity changed"):
        protocol.verify_v9_protocol(training_manifest_path=training)

    freeze = tmp_path / "freeze.json"
    freeze.write_bytes(protocol.CANDIDATE_FREEZE_PATH.read_bytes() + b" ")
    with pytest.raises(
        protocol.V9ProtocolError, match="initial-challenger freeze identity changed"
    ):
        protocol.verify_v9_protocol(candidate_freeze_path=freeze)
