"""C-B sol half: frozen arbitration log + bit-identical oracle replay."""

from __future__ import annotations

import pytest

from parcel_robot.counterfactual import (
    ARBITRATION_LOG_SCHEMA,
    COUNTERFACTUAL_REPORT_SCHEMA,
    SELECTOR_ID,
    ArbitrationCandidateV1,
    ArbitrationLogRecordV1,
    build_arbitration_log,
    counterfactual_report,
    record_digest,
    replay_committed_choice,
    select_candidate_id,
)


def _cand(
    candidate_id: str,
    *,
    source: str | None = None,
    priority: int = 0,
    confidence: float = 1.0,
    issued_s: float = 1.0,
    admissible: bool = True,
    veto_reason: str = "",
    plan_step_id: str = "",
) -> ArbitrationCandidateV1:
    return ArbitrationCandidateV1(
        candidate_id=candidate_id,
        source=source or candidate_id,
        priority=priority,
        confidence=confidence,
        issued_s=issued_s,
        pose_xyyaw=(0.0, 0.0, 0.0),
        admissible=admissible,
        veto_reason=veto_reason,
        plan_step_id=plan_step_id,
    )


def test_frozen_schema_and_selector_ids() -> None:
    assert ARBITRATION_LOG_SCHEMA == "parcel.arbitration_log.v1"
    assert COUNTERFACTUAL_REPORT_SCHEMA == "parcel.counterfactual_report.v1"
    assert SELECTOR_ID == "parcel.arbitration_selector.v1"


def test_selector_matches_priority_confidence_issued_source_key() -> None:
    candidates = (
        _cand("a", priority=1, confidence=0.9, issued_s=2.0),
        _cand("b", priority=2, confidence=0.5, issued_s=1.0),
        _cand("c", priority=2, confidence=0.8, issued_s=1.0),
        _cand("d", priority=2, confidence=0.8, issued_s=3.0),
    )
    # Highest priority wins; then confidence; then freshest issued_s; then source.
    assert select_candidate_id(candidates) == "d"
    assert (
        select_candidate_id(
            (
                _cand("z", priority=2, confidence=0.8, issued_s=3.0),
                _cand("a", priority=2, confidence=0.8, issued_s=3.0),
            )
        )
        == "a"
    )


def test_selector_plan_step_filter_and_hold_on_empty() -> None:
    candidates = (
        _cand("other", priority=9, plan_step_id="step-b"),
        _cand("owned", priority=1, plan_step_id="step-a"),
    )
    assert select_candidate_id(candidates, active_plan_step="step-a") == "owned"
    assert select_candidate_id((), active_plan_step="") is None
    assert select_candidate_id((_cand("x", admissible=False, veto_reason="ttl"),)) is None


def test_unknown_selector_id_fails_closed_to_hold() -> None:
    assert select_candidate_id((_cand("x"),), selector_id="future.ranker.v0") is None


def test_build_log_stamps_digest_and_canonical_order() -> None:
    record = build_arbitration_log(
        record_id="r1",
        episode_id="ep1",
        decision_monotonic_ns=100,
        candidates=(
            _cand("low", priority=0, confidence=0.5, issued_s=1.0),
            _cand("high", priority=3, confidence=0.2, issued_s=1.0),
            _cand("vetoed", priority=9, admissible=False, veto_reason="lethal"),
        ),
        committed_candidate_id="high",
    )
    assert record.schema_version == ARBITRATION_LOG_SCHEMA
    assert record.selector_id == SELECTOR_ID
    assert [c.candidate_id for c in record.candidates] == ["high", "low", "vetoed"]
    assert record.record_digest == record_digest(record)
    assert len(record.record_digest) == 64


def test_log_roundtrip_is_bit_identical() -> None:
    record = build_arbitration_log(
        record_id="r2",
        episode_id="ep2",
        decision_monotonic_ns=42,
        candidates=(_cand("win", priority=1), _cand("lose", priority=0)),
        committed_candidate_id="win",
        active_plan_step="",
    )
    restored = ArbitrationLogRecordV1.from_mapping(record.as_dict())
    assert restored == record
    assert restored.as_dict() == record.as_dict()
    assert record_digest(restored) == record.record_digest


def test_replay_reproduces_committed_choice_bit_identically() -> None:
    record = build_arbitration_log(
        record_id="r3",
        episode_id="ep3",
        decision_monotonic_ns=7,
        candidates=(
            _cand("grid", priority=1, confidence=0.7, issued_s=1.0),
            _cand("route", priority=1, confidence=0.9, issued_s=1.0),
            _cand("shadow", priority=0, confidence=1.0, issued_s=9.0),
            _cand("dead", priority=9, admissible=False, veto_reason="expired"),
        ),
        committed_candidate_id="route",
    )
    assert replay_committed_choice(record) == "route"
    assert replay_committed_choice(record) == record.committed_candidate_id


def test_replay_hold_when_nothing_admissible() -> None:
    record = build_arbitration_log(
        record_id="r4",
        episode_id="ep4",
        decision_monotonic_ns=8,
        candidates=(_cand("dead", admissible=False, veto_reason="lethal"),),
        committed_candidate_id=None,
    )
    assert replay_committed_choice(record) is None
    assert replay_committed_choice(record) == record.committed_candidate_id


def test_replay_rejects_tampered_digest() -> None:
    record = build_arbitration_log(
        record_id="r5",
        episode_id="ep5",
        decision_monotonic_ns=9,
        candidates=(_cand("only"),),
        committed_candidate_id="only",
    )
    tampered = ArbitrationLogRecordV1(
        schema_version=record.schema_version,
        record_id=record.record_id,
        episode_id=record.episode_id,
        decision_monotonic_ns=record.decision_monotonic_ns,
        selector_id=record.selector_id,
        active_plan_step=record.active_plan_step,
        candidates=record.candidates,
        committed_candidate_id=record.committed_candidate_id,
        record_digest="0" * 64,
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        replay_committed_choice(tampered)


def test_counterfactual_would_different_candidate_have_won() -> None:
    record = build_arbitration_log(
        record_id="r6",
        episode_id="ep6",
        decision_monotonic_ns=10,
        candidates=(
            _cand("chosen", priority=2, confidence=0.9, issued_s=1.0),
            _cand("alt_good", priority=1, confidence=1.0, issued_s=1.0),
            _cand("alt_bad", priority=0, confidence=1.0, issued_s=1.0),
            _cand("masked", priority=9, admissible=False, veto_reason="lethal"),
        ),
        committed_candidate_id="chosen",
    )
    report = counterfactual_report(
        record,
        oracle_success={
            "chosen": False,
            "alt_good": True,
            "alt_bad": False,
            "masked": True,  # ignored: inadmissible
        },
    )
    assert report.schema_version == COUNTERFACTUAL_REPORT_SCHEMA
    assert report.replay_matches_committed is True
    assert report.committed_oracle_success is False
    assert report.would_different_candidate_have_won is True
    assert report.alternate_success_ids == ("alt_good",)
    assert report.oracle_preferred_candidate_id == "alt_good"
    assert report.selection_regret is True


def test_counterfactual_no_regret_when_committed_succeeds() -> None:
    record = build_arbitration_log(
        record_id="r7",
        episode_id="ep7",
        decision_monotonic_ns=11,
        candidates=(_cand("chosen", priority=2), _cand("alt", priority=1)),
        committed_candidate_id="chosen",
    )
    report = counterfactual_report(
        record,
        oracle_success={"chosen": True, "alt": True},
    )
    assert report.would_different_candidate_have_won is False
    assert report.selection_regret is False
    assert report.alternate_success_ids == ("alt",)
    assert report.oracle_preferred_candidate_id == "chosen"


def test_counterfactual_hold_when_good_candidate_existed() -> None:
    # Product may commit HOLD even when admissible candidates were logged.
    record = build_arbitration_log(
        record_id="r8",
        episode_id="ep8",
        decision_monotonic_ns=12,
        candidates=(_cand("good", priority=1),),
        committed_candidate_id=None,
    )
    report = counterfactual_report(record, oracle_success={"good": True})
    assert report.replay_candidate_id == "good"
    assert report.replay_matches_committed is False
    assert report.would_different_candidate_have_won is True
    assert report.alternate_success_ids == ("good",)
    assert report.oracle_preferred_candidate_id == "good"
    assert report.selection_regret is True


def test_counterfactual_hold_with_empty_admissible_set() -> None:
    empty = build_arbitration_log(
        record_id="r8b",
        episode_id="ep8",
        decision_monotonic_ns=12,
        candidates=(_cand("dead", admissible=False, veto_reason="ttl"),),
        committed_candidate_id=None,
    )
    report = counterfactual_report(empty, oracle_success={"dead": True})
    assert report.replay_matches_committed is True
    assert report.would_different_candidate_have_won is False
    assert report.oracle_preferred_candidate_id is None


def test_build_rejects_committed_unknown_or_inadmissible() -> None:
    with pytest.raises(ValueError, match="committed_candidate_id"):
        build_arbitration_log(
            record_id="x",
            episode_id="e",
            decision_monotonic_ns=1,
            candidates=(_cand("a"),),
            committed_candidate_id="missing",
        )
    with pytest.raises(ValueError, match="admissible"):
        build_arbitration_log(
            record_id="x",
            episode_id="e",
            decision_monotonic_ns=1,
            candidates=(_cand("a", admissible=False, veto_reason="ttl"),),
            committed_candidate_id="a",
        )


def test_oracle_report_rejects_unknown_label_ids() -> None:
    record = build_arbitration_log(
        record_id="r9",
        episode_id="ep9",
        decision_monotonic_ns=14,
        candidates=(_cand("a"),),
        committed_candidate_id="a",
    )
    with pytest.raises(ValueError, match="unknown candidate_id"):
        counterfactual_report(record, oracle_success={"a": False, "ghost": True})
