"""Frozen arbitration-time candidate log contracts (offline measurement).

Decoupled from Design C's full multi-candidate runtime ABI
(WorldStateSliceV1 / CandidatePoolV1 / HardMaskVerdictV1 / RankDecisionV1 /
CommitLeaseV1).  This module only records what was present at arbitration and
what was committed, so later oracle replay can measure a selection residual.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ARBITRATION_LOG_SCHEMA = "parcel.arbitration_log.v1"
SELECTOR_ID = "parcel.arbitration_selector.v1"

_DIGEST_EXCLUDE = frozenset({"record_digest"})


@dataclass(frozen=True, slots=True)
class ArbitrationCandidateV1:
    """One candidate observed at an arbitration decision.

    Field names mirror the GoalArbiter sort/veto inputs without importing
    ``instructnav``.  ``admissible`` is the caller's post-filter verdict at
    log time (TTL / lethal / revision already applied).
    """

    candidate_id: str
    source: str
    priority: int = 0
    confidence: float = 1.0
    issued_s: float = 0.0
    pose_xyyaw: tuple[float, float, float] | None = None
    waypoints_xy: tuple[tuple[float, float], ...] = ()
    plan_step_id: str = ""
    task_id: str = ""
    plan_revision: int = 0
    admissible: bool = True
    veto_reason: str = ""

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.candidate_id.strip():
            raise ValueError("candidate_id must be non-empty")
        if not self.source or not self.source.strip():
            raise ValueError("source must be non-empty")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise TypeError("priority must be an int")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be finite in [0, 1]")
        if not math.isfinite(self.issued_s):
            raise ValueError("issued_s must be finite")
        if self.plan_revision < 0:
            raise ValueError("plan_revision must be non-negative")
        if self.pose_xyyaw is not None and (
            len(self.pose_xyyaw) != 3
            or not all(math.isfinite(v) for v in self.pose_xyyaw)
        ):
            raise ValueError("pose_xyyaw must be three finite floats")
        for point in self.waypoints_xy:
            if len(point) != 2 or not all(math.isfinite(v) for v in point):
                raise ValueError("waypoints_xy entries must be finite (x, y)")
        if not self.admissible and not self.veto_reason:
            raise ValueError("inadmissible candidates require veto_reason")
        if self.admissible and self.veto_reason:
            raise ValueError("admissible candidates must not set veto_reason")

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source": self.source,
            "priority": self.priority,
            "confidence": self.confidence,
            "issued_s": self.issued_s,
            "pose_xyyaw": (
                list(self.pose_xyyaw) if self.pose_xyyaw is not None else None
            ),
            "waypoints_xy": [list(p) for p in self.waypoints_xy],
            "plan_step_id": self.plan_step_id,
            "task_id": self.task_id,
            "plan_revision": self.plan_revision,
            "admissible": self.admissible,
            "veto_reason": self.veto_reason,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ArbitrationCandidateV1:
        pose_raw = data.get("pose_xyyaw")
        pose: tuple[float, float, float] | None
        if pose_raw is None:
            pose = None
        else:
            pose = (float(pose_raw[0]), float(pose_raw[1]), float(pose_raw[2]))
        waypoints_raw = data.get("waypoints_xy") or ()
        waypoints = tuple((float(p[0]), float(p[1])) for p in waypoints_raw)
        return cls(
            candidate_id=str(data["candidate_id"]),
            source=str(data["source"]),
            priority=int(data.get("priority", 0)),
            confidence=float(data.get("confidence", 1.0)),
            issued_s=float(data.get("issued_s", 0.0)),
            pose_xyyaw=pose,
            waypoints_xy=waypoints,
            plan_step_id=str(data.get("plan_step_id", "")),
            task_id=str(data.get("task_id", "")),
            plan_revision=int(data.get("plan_revision", 0)),
            admissible=bool(data.get("admissible", True)),
            veto_reason=str(data.get("veto_reason", "")),
        )


@dataclass(frozen=True, slots=True)
class ArbitrationLogRecordV1:
    """One arbitration decision with the full candidate set and commit."""

    schema_version: str
    record_id: str
    episode_id: str
    decision_monotonic_ns: int
    selector_id: str
    active_plan_step: str
    candidates: tuple[ArbitrationCandidateV1, ...]
    committed_candidate_id: str | None
    record_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "episode_id": self.episode_id,
            "decision_monotonic_ns": self.decision_monotonic_ns,
            "selector_id": self.selector_id,
            "active_plan_step": self.active_plan_step,
            "candidates": [c.as_dict() for c in self.candidates],
            "committed_candidate_id": self.committed_candidate_id,
            "record_digest": self.record_digest,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ArbitrationLogRecordV1:
        candidates = tuple(
            ArbitrationCandidateV1.from_mapping(item)
            for item in data.get("candidates", ())
        )
        committed = data.get("committed_candidate_id")
        return cls(
            schema_version=str(data["schema_version"]),
            record_id=str(data["record_id"]),
            episode_id=str(data["episode_id"]),
            decision_monotonic_ns=int(data["decision_monotonic_ns"]),
            selector_id=str(data["selector_id"]),
            active_plan_step=str(data.get("active_plan_step", "")),
            candidates=candidates,
            committed_candidate_id=None if committed is None else str(committed),
            record_digest=str(data["record_digest"]),
        )


def _canonical_candidate_order(
    candidates: Sequence[ArbitrationCandidateV1],
) -> tuple[ArbitrationCandidateV1, ...]:
    """Stable log order: admissible by selector key, then inadmissible by id."""

    admissible = [c for c in candidates if c.admissible]
    inadmissible = [c for c in candidates if not c.admissible]
    admissible.sort(
        key=lambda c: (
            -int(c.priority),
            -float(c.confidence),
            -float(c.issued_s),
            c.source,
            c.candidate_id,
        )
    )
    inadmissible.sort(key=lambda c: (c.source, c.candidate_id))
    return tuple(admissible + inadmissible)


def canonical_record_payload(record: Mapping[str, Any] | ArbitrationLogRecordV1) -> bytes:
    """Canonical JSON bytes used for digest (excludes ``record_digest``)."""

    if isinstance(record, ArbitrationLogRecordV1):
        payload = record.as_dict()
    else:
        payload = dict(record)
    body = {key: value for key, value in payload.items() if key not in _DIGEST_EXCLUDE}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def record_digest(record: Mapping[str, Any] | ArbitrationLogRecordV1) -> str:
    """SHA-256 hex digest of the canonical arbitration payload."""

    return hashlib.sha256(canonical_record_payload(record)).hexdigest()


def build_arbitration_log(
    *,
    record_id: str,
    episode_id: str,
    decision_monotonic_ns: int,
    candidates: Iterable[ArbitrationCandidateV1],
    committed_candidate_id: str | None,
    active_plan_step: str = "",
    selector_id: str = SELECTOR_ID,
) -> ArbitrationLogRecordV1:
    """Stamp an arbitration log record with a frozen digest.

    The committed id is recorded as supplied (what the product path actually
    chose).  :func:`parcel_robot.counterfactual.replay_committed_choice` later
    proves the deterministic selector reproduces that choice bit-identically.
    """

    if not record_id or not record_id.strip():
        raise ValueError("record_id must be non-empty")
    if not episode_id or not episode_id.strip():
        raise ValueError("episode_id must be non-empty")
    if (
        isinstance(decision_monotonic_ns, bool)
        or not isinstance(decision_monotonic_ns, int)
        or decision_monotonic_ns < 0
    ):
        raise ValueError("decision_monotonic_ns must be a non-negative int")
    if not selector_id or not selector_id.strip():
        raise ValueError("selector_id must be non-empty")

    ordered = _canonical_candidate_order(tuple(candidates))
    seen: set[str] = set()
    for candidate in ordered:
        if candidate.candidate_id in seen:
            raise ValueError(f"duplicate candidate_id: {candidate.candidate_id}")
        seen.add(candidate.candidate_id)

    if committed_candidate_id is not None:
        if committed_candidate_id not in seen:
            raise ValueError("committed_candidate_id must name a logged candidate")
        committed = next(c for c in ordered if c.candidate_id == committed_candidate_id)
        if not committed.admissible:
            raise ValueError("committed_candidate_id must be admissible")

    draft = {
        "schema_version": ARBITRATION_LOG_SCHEMA,
        "record_id": record_id,
        "episode_id": episode_id,
        "decision_monotonic_ns": decision_monotonic_ns,
        "selector_id": selector_id,
        "active_plan_step": active_plan_step,
        "candidates": [c.as_dict() for c in ordered],
        "committed_candidate_id": committed_candidate_id,
    }
    digest = record_digest(draft)
    return ArbitrationLogRecordV1(
        schema_version=ARBITRATION_LOG_SCHEMA,
        record_id=record_id,
        episode_id=episode_id,
        decision_monotonic_ns=decision_monotonic_ns,
        selector_id=selector_id,
        active_plan_step=active_plan_step,
        candidates=ordered,
        committed_candidate_id=committed_candidate_id,
        record_digest=digest,
    )
