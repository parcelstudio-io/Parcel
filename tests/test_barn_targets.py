from __future__ import annotations

import pytest

from evals.external.barn_targets import (
    evaluate_barn_top_decile_target,
    load_barn_top_decile_target,
)


def test_frozen_barn_target_matches_published_2026_table() -> None:
    manifest = load_barn_top_decile_target()

    assert manifest["benchmark"]["registered_team_count"] == 17
    assert manifest["benchmark"]["reported_numeric_score_count"] == 12
    assert manifest["target"]["rank_cutoff_in_registered_cohort"] == 2
    assert manifest["target"]["minimum_official_mean_navigation_score"] == pytest.approx(0.4880)
    assert manifest["published_scores_descending"][0] == {
        "rank": 1,
        "team": "IN2 BOT",
        "score": 0.4975,
    }


def test_native_proxy_can_never_pass_official_top_decile_gate() -> None:
    result = evaluate_barn_top_decile_target(0.5, official_protocol=False)

    assert result["numeric_reference_met"] is True
    assert result["official_gate_eligible"] is False
    assert result["official_gate_pass"] is False
    assert result["leaderboard_claim_allowed"] is False
    assert result["status"] == "native_proxy_reference_only"


def test_official_gate_uses_frozen_rank_two_threshold() -> None:
    passed = evaluate_barn_top_decile_target(0.4880, official_protocol=True)
    failed = evaluate_barn_top_decile_target(0.4879, official_protocol=True)

    assert passed["official_gate_pass"] is True
    assert failed["official_gate_pass"] is False
    assert failed["score_gap"] == pytest.approx(-0.0001)
