"""Structured model proposal for narrating a physical action outcome."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from parcel_robot.contracts.companion_v1 import (
    SCHEMA_VERSION,
    TERMINAL_ACTION_STATUSES,
    _derived_identifier,
    _digest,
    _enum,
    _exact,
    _identifier,
    _integer,
    _mapping,
    _text,
)


@dataclass(frozen=True, slots=True)
class TerminalClaimProposalV1:
    """A proposed outcome fact, not a license to say it happened."""

    claim_id: str
    mission_id: str
    action_id: str
    action_name: str
    manifest_digest: str
    terminal_receipt_id: str
    claimed_status: str
    proposed_at_monotonic_ns: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        _identifier(self.claim_id, "claim_id")
        _derived_identifier(self.mission_id, "mission_id")
        _derived_identifier(self.action_id, "action_id")
        _identifier(self.action_name, "action_name")
        _digest(self.manifest_digest)
        _derived_identifier(self.terminal_receipt_id, "terminal_receipt_id")
        _enum(self.claimed_status, TERMINAL_ACTION_STATUSES, "claimed_status")
        _integer(self.proposed_at_monotonic_ns, "proposed_at_monotonic_ns")

    @property
    def is_verified(self) -> bool:
        return False

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TerminalClaimProposalV1:
        data = _mapping(value, "TerminalClaimProposalV1")
        fields = {
            "schema_version",
            "claim_id",
            "mission_id",
            "action_id",
            "action_name",
            "manifest_digest",
            "terminal_receipt_id",
            "claimed_status",
            "proposed_at_monotonic_ns",
        }
        _exact(data, fields, "TerminalClaimProposalV1")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            claim_id=_text(data["claim_id"], "claim_id", maximum=128),
            mission_id=_text(data["mission_id"], "mission_id", maximum=128),
            action_id=_text(data["action_id"], "action_id", maximum=128),
            action_name=_text(data["action_name"], "action_name", maximum=128),
            manifest_digest=_text(data["manifest_digest"], "manifest_digest", maximum=64),
            terminal_receipt_id=_text(
                data["terminal_receipt_id"], "terminal_receipt_id", maximum=128
            ),
            claimed_status=_text(data["claimed_status"], "claimed_status", maximum=64),
            proposed_at_monotonic_ns=_integer(
                data["proposed_at_monotonic_ns"], "proposed_at_monotonic_ns"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "claim_id": self.claim_id,
            "mission_id": self.mission_id,
            "action_id": self.action_id,
            "action_name": self.action_name,
            "manifest_digest": self.manifest_digest,
            "terminal_receipt_id": self.terminal_receipt_id,
            "claimed_status": self.claimed_status,
            "proposed_at_monotonic_ns": self.proposed_at_monotonic_ns,
        }


__all__ = ["TerminalClaimProposalV1"]
