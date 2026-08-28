"""Pre-persistence admission boundary for research summaries.

Unknown fields are rejected rather than silently widening the research
contract.  The only content transformation is bounded regex redaction on the
explicitly named ``redacted_note`` field; this is a seeded-leak backstop, not a
claim of de-identification.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .contracts import ALLOWED_DATA_KEYS, ResearchEventV1

FORBIDDEN_KEYS = frozenset(
    {
        "raw_audio",
        "audio_bytes",
        "raw_image",
        "image_bytes",
        "raw_video",
        "transcript",
        "full_text",
        "face_embedding",
        "voice_embedding",
        "gps_lat",
        "gps_lon",
        "latitude",
        "longitude",
        "exact_address",
        "name",
        "email",
        "phone",
        "credential",
        "api_key",
        "access_token",
    }
)
RAW_PAYLOAD_KINDS = frozenset({"raw_audio", "raw_image", "raw_video", "mcap_raw"})

_REDACTIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "email",
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    ),
    (
        "phone",
        re.compile(
            r"(?<![A-Za-z0-9])(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)"
            r"\d{3}[-.\s]?\d{4}(?![A-Za-z0-9])"
        ),
    ),
    (
        "credential",
        re.compile(r"\b(?:sk|pk|api)[-_][A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
    ),
)


class AdmissionStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    status: AdmissionStatus
    reason: str
    event: ResearchEventV1 | None = None
    redactions: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.status is AdmissionStatus.ACCEPTED


def _walk_keys(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key).lower()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _redact_note(value: object) -> tuple[object, tuple[str, ...]]:
    if not isinstance(value, str):
        return value, ()
    result = value
    changes: list[str] = []
    for name, pattern in _REDACTIONS:
        result, count = pattern.subn(f"[REDACTED_{name.upper()}]", result)
        changes.extend([name] * count)
    return result, tuple(changes)


def admit_candidate(candidate: Mapping[str, object]) -> AdmissionDecision:
    """Validate and sanitize one candidate without performing I/O.

    Consent validity and revocation are deliberately checked later by the
    dedicated spool, transactionally with insertion.  This function never
    opens owner memory and never grants consent.
    """

    if not isinstance(candidate, Mapping):
        return AdmissionDecision(AdmissionStatus.REJECTED, "candidate_not_object")
    privacy_class = candidate.get("privacy_class")
    if privacy_class == "companion_only":
        return AdmissionDecision(AdmissionStatus.REJECTED, "companion_only")
    if privacy_class == "consent_required" and not candidate.get("consent_id"):
        return AdmissionDecision(AdmissionStatus.REJECTED, "missing_consent_id")

    data = candidate.get("data")
    if not isinstance(data, Mapping):
        return AdmissionDecision(AdmissionStatus.REJECTED, "data_not_object")
    if data.get("payload_kind") in RAW_PAYLOAD_KINDS:
        return AdmissionDecision(AdmissionStatus.REJECTED, "raw_payload")

    forbidden = sorted(set(_walk_keys(candidate)) & FORBIDDEN_KEYS)
    if forbidden:
        return AdmissionDecision(
            AdmissionStatus.REJECTED,
            f"forbidden_fields:{','.join(forbidden)}",
        )

    stream = candidate.get("stream")
    if candidate.get("priority") == 0:
        return AdmissionDecision(AdmissionStatus.REJECTED, "reserved_control_priority")
    allowed = ALLOWED_DATA_KEYS.get(str(stream))
    if allowed is None:
        return AdmissionDecision(AdmissionStatus.REJECTED, "unknown_stream")
    unknown = sorted({str(key) for key in data} - allowed)
    if unknown:
        return AdmissionDecision(
            AdmissionStatus.REJECTED,
            f"unknown_data_fields:{','.join(unknown)}",
        )

    clean: dict[str, Any] = copy.deepcopy(dict(candidate))
    clean_data = dict(data)
    redactions: tuple[str, ...] = ()
    if "redacted_note" in clean_data:
        clean_data["redacted_note"], redactions = _redact_note(clean_data["redacted_note"])
    clean["data"] = clean_data

    try:
        event = ResearchEventV1.from_mapping(clean)
    except (TypeError, ValueError) as exc:
        return AdmissionDecision(AdmissionStatus.REJECTED, f"invalid_contract:{exc}")
    return AdmissionDecision(
        AdmissionStatus.ACCEPTED,
        "accepted",
        event=event,
        redactions=redactions,
    )
