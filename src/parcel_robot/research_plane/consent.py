"""Authenticated, bounded consent contracts for the research plane."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .contracts import canonical_json_bytes, sha256_hex

CONSENT_AUTHORITIES = frozenset({"owner_ui", "operator_protocol"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PROOF = re.compile(r"^[A-Za-z0-9_+=./:-]{16,2048}$")
_VERIFIED_CONSENT_TOKEN = object()
ConsentVerifier = Callable[[bytes, str, str, str], bool]


@dataclass(frozen=True, slots=True)
class TrustedConsentVerifierV1:
    """Process-local verifier provider with an immutable persisted identity."""

    verifier_id: str
    verifier: ConsentVerifier = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.verifier_id):
            raise ValueError("consent verifier_id must be a bounded identifier")
        if not callable(self.verifier):
            raise TypeError("consent verifier must be callable")

    def verify(
        self,
        canonical_record: bytes,
        proof: str,
        authenticator_id: str,
        channel: str,
    ) -> bool:
        """Verify the exact canonical record and its complete authority context."""

        if (
            not isinstance(canonical_record, bytes)
            or not canonical_record
            or not isinstance(proof, str)
            or not _PROOF.fullmatch(proof)
            or not _IDENTIFIER.fullmatch(authenticator_id)
            or channel not in CONSENT_AUTHORITIES
        ):
            return False
        try:
            return self.verifier(
                canonical_record,
                proof,
                authenticator_id,
                channel,
            ) is True
        except Exception:  # noqa: BLE001 - a provider failure must fail closed
            return False


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: str) -> str:
    return _parse(value).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ConsentRecordV1:
    consent_id: str
    subject_pseudonym: str
    streams: tuple[str, ...]
    destination: str
    granted_at: str
    expires_at: str
    authority: str
    purpose: str = "research_evaluation"

    def __post_init__(self) -> None:
        if not isinstance(self.streams, tuple):
            raise TypeError("consent streams must be an immutable tuple")
        if any(not isinstance(stream, str) for stream in self.streams):
            raise TypeError("consent streams must contain only strings")
        if not _IDENTIFIER.fullmatch(self.consent_id):
            raise ValueError("consent_id must be a bounded identifier")
        if not _IDENTIFIER.fullmatch(self.subject_pseudonym):
            raise ValueError("subject_pseudonym must be a bounded pseudonym")
        allowed_streams = {"navigation", "conversation", "audio", "perception", "feedback"}
        if not self.streams or len(set(self.streams)) != len(self.streams):
            raise ValueError("streams must be non-empty and unique")
        if set(self.streams) - allowed_streams:
            raise ValueError("consent names an unsupported stream")
        if not _IDENTIFIER.fullmatch(self.destination):
            raise ValueError("destination must be a bounded identifier")
        if self.authority not in CONSENT_AUTHORITIES:
            raise ValueError("models and untyped callers cannot grant research consent")
        if self.purpose != "research_evaluation":
            raise ValueError("unsupported consent purpose")
        granted, expires = _parse(self.granted_at), _parse(self.expires_at)
        if expires <= granted:
            raise ValueError("consent expiry must be after grant")
        if expires - granted > timedelta(days=365):
            raise ValueError("consent lifetime must not exceed 365 days")
        object.__setattr__(self, "granted_at", _utc_text(self.granted_at))
        object.__setattr__(self, "expires_at", _utc_text(self.expires_at))

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            {
                "authority": self.authority,
                "consent_id": self.consent_id,
                "destination": self.destination,
                "expires_at": self.expires_at,
                "granted_at": self.granted_at,
                "purpose": self.purpose,
                "streams": list(self.streams),
                "subject_pseudonym": self.subject_pseudonym,
            }
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedConsentV1:
    """Process-local proof that a trusted channel authenticated a full record."""

    record: ConsentRecordV1
    channel: str
    authenticator_id: str
    proof: str = field(repr=False)
    _token: object | None = field(init=False, repr=False, compare=False, default=None)
    _canonical_record: bytes = field(init=False, repr=False, compare=False, default=b"")
    _record_sha256: str = field(init=False, repr=False, compare=False, default="")
    _verifier_id: str = field(init=False, repr=False, compare=False, default="")

    @classmethod
    def authenticate(
        cls,
        record: ConsentRecordV1,
        *,
        channel: str,
        authenticator_id: str,
        proof: str,
        verifier_provider: TrustedConsentVerifierV1 | None = None,
    ) -> AuthenticatedConsentV1:
        result = cls(record, channel, authenticator_id, proof)
        if not isinstance(verifier_provider, TrustedConsentVerifierV1):
            raise TypeError("trusted consent authenticator is required")
        canonical = record.canonical_bytes()
        if not verifier_provider.verify(canonical, proof, authenticator_id, channel):
            raise ValueError("consent authentication failed")
        object.__setattr__(result, "_canonical_record", canonical)
        object.__setattr__(result, "_record_sha256", sha256_hex(canonical))
        object.__setattr__(result, "_verifier_id", verifier_provider.verifier_id)
        object.__setattr__(result, "_token", _VERIFIED_CONSENT_TOKEN)
        return result

    def __post_init__(self) -> None:
        if type(self.record) is not ConsentRecordV1:
            raise TypeError("authenticated consent requires a typed ConsentRecordV1")
        if self.channel not in CONSENT_AUTHORITIES:
            raise ValueError("consent channel is unsupported")
        if self.channel != self.record.authority:
            raise ValueError("consent channel does not match record authority")
        if not _IDENTIFIER.fullmatch(self.authenticator_id):
            raise ValueError("authenticator_id must be a bounded identifier")
        if not isinstance(self.proof, str) or not _PROOF.fullmatch(self.proof):
            raise ValueError("consent proof is invalid")

    @property
    def authenticated(self) -> bool:
        return (
            self._token is _VERIFIED_CONSENT_TOKEN
            and self._canonical_record == self.record.canonical_bytes()
            and self._record_sha256 == sha256_hex(self._canonical_record)
            and bool(_IDENTIFIER.fullmatch(self._verifier_id))
        )

    @property
    def canonical_record(self) -> bytes:
        if not self.authenticated:
            raise ValueError("authenticated consent binding is no longer valid")
        return self._canonical_record

    @property
    def record_sha256(self) -> str:
        if not self.authenticated:
            raise ValueError("authenticated consent binding is no longer valid")
        return self._record_sha256

    @property
    def verifier_id(self) -> str:
        if not self.authenticated:
            raise ValueError("authenticated consent binding is no longer valid")
        return self._verifier_id

    def verified_record(self) -> ConsentRecordV1:
        """Reconstruct from authenticated bytes, never from mutable live attributes."""

        decoded = json.loads(self.canonical_record)
        decoded["streams"] = tuple(decoded["streams"])
        record = ConsentRecordV1(**decoded)
        if record.canonical_bytes() != self._canonical_record:
            raise ValueError("authenticated consent canonical reconstruction changed")
        return record
