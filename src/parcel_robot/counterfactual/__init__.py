"""Offline counterfactual candidate logging + oracle replay (C-B sol half).

Pure measurement substrate only.  No runtime, GoalArbiter, or navigation
product wiring.  Opus Wave-2b consumes these contracts at the arbitration
log site.

Frozen public surface
---------------------
- :func:`build_arbitration_log` — stamp candidates + committed choice
- :func:`replay_committed_choice` — bit-identical deterministic re-select
- :func:`counterfactual_report` — would-a-different-candidate-have-won
"""

from parcel_robot.counterfactual.arbitration_log import (
    ARBITRATION_LOG_SCHEMA,
    SELECTOR_ID,
    ArbitrationCandidateV1,
    ArbitrationLogRecordV1,
    build_arbitration_log,
    canonical_record_payload,
    record_digest,
)
from parcel_robot.counterfactual.oracle_replay import (
    COUNTERFACTUAL_REPORT_SCHEMA,
    CounterfactualReportV1,
    counterfactual_report,
    replay_committed_choice,
    select_candidate_id,
)

__all__ = [
    "ARBITRATION_LOG_SCHEMA",
    "COUNTERFACTUAL_REPORT_SCHEMA",
    "SELECTOR_ID",
    "ArbitrationCandidateV1",
    "ArbitrationLogRecordV1",
    "CounterfactualReportV1",
    "build_arbitration_log",
    "canonical_record_payload",
    "counterfactual_report",
    "record_digest",
    "replay_committed_choice",
    "select_candidate_id",
]
