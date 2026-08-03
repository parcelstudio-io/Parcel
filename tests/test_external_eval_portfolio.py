from __future__ import annotations

import copy

import pytest

from evals.external.portfolio_targets import (
    load_portfolio_target,
    portfolio_claim_preconditions,
    validate_portfolio_target,
)


def test_portfolio_freezes_each_official_ranked_target_independently() -> None:
    document = load_portfolio_target()
    targets = {item["id"]: item for item in document["official_ranked_targets"]}

    assert document["objective"]["aggregation"] == "conjunctive"
    assert document["objective"]["averaging_across_evaluators_allowed"] is False
    assert targets["habitat2020_pointnav_test_challenge"]["metric"]["threshold"] == 0.21
    assert targets["habitat2020_objectnav_test_challenge"]["metric"]["threshold"] == 0.1
    assert targets["barn2026_simulation_qualifier"]["metric"]["threshold"] == 0.488
    assert [target["cohort"]["top_decile_rank_cutoff"] for target in targets.values()] == [
        1,
        1,
        2,
    ]


def test_portfolio_never_treats_proxies_or_internal_tests_as_rank_evidence() -> None:
    document = load_portfolio_target()

    assert all(gate["claim_eligible"] is False for gate in document["proxy_development_gates"])
    assert all(
        gate["claim_class"] == "internal_pass_fail" for gate in document["internal_pass_fail_gates"]
    )
    assert all(
        target["eligibility"]["parcel_offline_proxy_eligible"] is False
        for target in document["official_ranked_targets"]
    )


def test_threewe_targets_remain_explicit_unresolved_claim_blockers() -> None:
    document = load_portfolio_target()
    unresolved = document["unresolved_targets"]

    assert {item["id"] for item in unresolved} == {
        "threewe_pointnav",
        "threewe_objectnav",
        "threewe_exploration",
    }
    assert all(item["numeric_threshold"] is None for item in unresolved)
    assert all(item["blocks_portfolio_claim"] is True for item in unresolved)
    assert all(
        item["source_commit"] == "6073a1bd0a30b6ca1348027ac35b05832b97bfe9" for item in unresolved
    )
    assert all(
        item["leaderboard_snapshot"]["sha256"]
        == "5740907e0aafcf38eaf08ebd0cbb1c366465aa7e790401e9f723ab96fefa4323"
        for item in unresolved
    )
    assert all("organizer-confirmed" in item["resolution_required"] for item in unresolved)


def test_portfolio_target_records_no_achievement() -> None:
    preconditions = portfolio_claim_preconditions()

    assert preconditions["recorded_achievement"] is None
    assert preconditions["claim_possible_from_targets_alone"] is False
    assert len(preconditions["unresolved_target_ids"]) == 3


def test_validator_rejects_rank_averaging_or_proxy_claims() -> None:
    document = load_portfolio_target()
    averaged = copy.deepcopy(document)
    averaged["objective"]["aggregation"] = "mean"
    with pytest.raises(ValueError, match="conjunctive"):
        validate_portfolio_target(averaged)

    proxy_claim = copy.deepcopy(document)
    proxy_claim["proxy_development_gates"][0]["claim_eligible"] = True
    with pytest.raises(ValueError, match="ineligible"):
        validate_portfolio_target(proxy_claim)


def test_validator_rejects_invented_unresolved_threshold() -> None:
    document = load_portfolio_target()
    invented = copy.deepcopy(document)
    invented["unresolved_targets"][0]["numeric_threshold"] = 0.9

    with pytest.raises(ValueError, match="cannot invent"):
        validate_portfolio_target(invented)


def test_validator_rejects_threewe_snapshot_drift() -> None:
    document = load_portfolio_target()
    drifted_commit = copy.deepcopy(document)
    drifted_commit["unresolved_targets"][0]["source_commit"] = "0" * 40
    with pytest.raises(ValueError, match="source lock"):
        validate_portfolio_target(drifted_commit)

    mutable_path = copy.deepcopy(document)
    mutable_path["unresolved_targets"][0]["leaderboard_snapshot"]["path"] = "../mutable.json"
    with pytest.raises(ValueError, match="repository-relative"):
        validate_portfolio_target(mutable_path)
