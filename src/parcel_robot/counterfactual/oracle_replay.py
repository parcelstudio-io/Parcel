"""Bit-identical arbitration replay + oracle counterfactual report.

The selector key is frozen to match GoalArbiter.resolve ranking:

    (-priority, -confidence, -issued_s, source)

without importing ``instructnav``.  Replay never consults oracle labels.
Oracle labels only feed the would-a-different-candidate-have-won report that
gates any future learned ranker (COMPARISON §8.3 / T-G4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from parcel_robot.counterfactual.arbitration_log import (
    SELECTOR_ID,
    ArbitrationCandidateV1,
    ArbitrationLogRecordV1,
    record_digest,
)

COUNTERFACTUAL_REPORT_SCHEMA = "parcel.counterfactual_report.v1"


def select_candidate_id(
    candidates: Sequence[ArbitrationCandidateV1],
    *,
    active_plan_step: str = "",
    selector_id: str = SELECTOR_ID,
) -> str | None:
    """Deterministically select among admissible candidates.

    Returns ``None`` when the admissible set is empty (HOLD).  Unknown
    ``selector_id`` values fail closed as HOLD so a future ranker cannot
    silently change offline replay semantics.
    """

    if selector_id != SELECTOR_ID:
        return None
    viable = [c for c in candidates if c.admissible]
    if not viable:
        return None
    if active_plan_step:
        owned = [c for c in viable if c.plan_step_id == active_plan_step]
        if owned:
            viable = owned
    viable.sort(
        key=lambda c: (
            -int(c.priority),
            -float(c.confidence),
            -float(c.issued_s),
            c.source,
            c.candidate_id,
        )
    )
    return viable[0].candidate_id


def replay_committed_choice(record: ArbitrationLogRecordV1) -> str | None:
    """Re-run the frozen selector on a logged record.

    Callers assert equality with ``record.committed_candidate_id`` for
    bit-identical replay integrity.  Digest mismatch raises — the payload
    under selection must be the stamped one.
    """

    expected = record_digest(record)
    if record.record_digest != expected:
        raise ValueError("arbitration log digest mismatch; refuse replay")
    return select_candidate_id(
        record.candidates,
        active_plan_step=record.active_plan_step,
        selector_id=record.selector_id,
    )


@dataclass(frozen=True, slots=True)
class CounterfactualReportV1:
    """Oracle gap report for one arbitration decision."""

    schema_version: str
    record_id: str
    episode_id: str
    replay_candidate_id: str | None
    replay_matches_committed: bool
    committed_candidate_id: str | None
    committed_oracle_success: bool | None
    would_different_candidate_have_won: bool
    alternate_success_ids: tuple[str, ...]
    oracle_preferred_candidate_id: str | None
    selection_regret: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "episode_id": self.episode_id,
            "replay_candidate_id": self.replay_candidate_id,
            "replay_matches_committed": self.replay_matches_committed,
            "committed_candidate_id": self.committed_candidate_id,
            "committed_oracle_success": self.committed_oracle_success,
            "would_different_candidate_have_won": self.would_different_candidate_have_won,
            "alternate_success_ids": list(self.alternate_success_ids),
            "oracle_preferred_candidate_id": self.oracle_preferred_candidate_id,
            "selection_regret": self.selection_regret,
        }


def counterfactual_report(
    record: ArbitrationLogRecordV1,
    *,
    oracle_success: Mapping[str, bool],
) -> CounterfactualReportV1:
    """Report whether a different logged candidate would have won under oracle.

    ``oracle_success`` maps ``candidate_id -> would_have_succeeded``.  Missing
    ids are treated as unlabeled (excluded from alternates).  Labels for
    inadmissible candidates are ignored — the oracle may only choose among
    candidates that were admissible at arbitration.
    """

    replayed = replay_committed_choice(record)
    matches = replayed == record.committed_candidate_id

    admitted_ids = {c.candidate_id for c in record.candidates if c.admissible}
    unknown = set(oracle_success) - {c.candidate_id for c in record.candidates}
    if unknown:
        raise ValueError(f"oracle_success has unknown candidate_id(s): {sorted(unknown)}")

    successful = [
        c
        for c in record.candidates
        if c.admissible and oracle_success.get(c.candidate_id) is True
    ]
    # Prefer the same frozen selector order among oracle-successful candidates.
    successful.sort(
        key=lambda c: (
            -int(c.priority),
            -float(c.confidence),
            -float(c.issued_s),
            c.source,
            c.candidate_id,
        )
    )
    oracle_preferred = successful[0].candidate_id if successful else None

    committed = record.committed_candidate_id
    committed_label: bool | None
    if committed is None or committed not in oracle_success:
        committed_label = None
    else:
        committed_label = bool(oracle_success[committed])

    alternate_ids = tuple(
        c.candidate_id
        for c in successful
        if c.candidate_id != committed and c.candidate_id in admitted_ids
    )

    # Failure means the committed choice is labeled false, or HOLD was taken
    # while at least one admitted candidate is oracle-successful.
    committed_failed = committed_label is False or (
        committed is None and oracle_preferred is not None
    )
    # Unlabeled committed outcomes never claim a counterfactual win.
    would_different = bool(alternate_ids) and committed_failed and committed_label is not True

    selection_regret = bool(
        committed_failed
        and oracle_preferred is not None
        and oracle_preferred != committed
    )

    return CounterfactualReportV1(
        schema_version=COUNTERFACTUAL_REPORT_SCHEMA,
        record_id=record.record_id,
        episode_id=record.episode_id,
        replay_candidate_id=replayed,
        replay_matches_committed=matches,
        committed_candidate_id=committed,
        committed_oracle_success=committed_label,
        would_different_candidate_have_won=would_different,
        alternate_success_ids=alternate_ids,
        oracle_preferred_candidate_id=oracle_preferred,
        selection_regret=selection_regret,
    )
