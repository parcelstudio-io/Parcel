"""Process-local authenticity channels for companion evidence.

The wrappers carry integrity and provenance only.  They expose no robot,
executive, publisher, or actuator handle and therefore grant no actuation
authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from parcel_robot.contracts.companion_v1 import (
    ActionReceiptV1,
    EmbodimentEnvelopeV1,
    OperatorEvidenceV1,
    _identifier,
)


def _valid_tag(value: object, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 HMAC")


def _canonical_payload(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


@dataclass(frozen=True, slots=True)
class AuthenticatedActionReceiptV1:
    """Receipt plus integrity proof from one local trusted channel."""

    receipt: ActionReceiptV1
    authenticator_id: str
    auth_tag: str

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, ActionReceiptV1):
            raise TypeError("receipt must be ActionReceiptV1")
        _identifier(self.authenticator_id, "authenticator_id")
        _valid_tag(self.auth_tag, "auth_tag")

    def as_dict(self) -> dict[str, object]:
        """Expose receipt data, not a serializable authority wrapper."""

        return self.receipt.as_dict()

    @property
    def authorizes_actuation(self) -> bool:
        return False

    def __getattr__(self, name: str) -> object:
        return getattr(self.receipt, name)


class TrustedReceiptAuthenticatorV1:
    """Process-local HMAC channel; it holds no actuator authority."""

    __slots__ = ("_key", "authenticator_id")

    def __init__(self, *, authenticator_id: str, key: bytes) -> None:
        self.authenticator_id = _identifier(authenticator_id, "authenticator_id")
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("receipt authentication key must contain at least 32 bytes")
        self._key = bytes(key)

    def authenticate(self, receipt: ActionReceiptV1) -> AuthenticatedActionReceiptV1:
        if not isinstance(receipt, ActionReceiptV1):
            raise TypeError("receipt must be ActionReceiptV1")
        tag = hmac.new(
            self._key, _canonical_payload(receipt.as_dict()), hashlib.sha256
        ).hexdigest()
        return AuthenticatedActionReceiptV1(receipt, self.authenticator_id, tag)

    def verify(self, authenticated: AuthenticatedActionReceiptV1) -> bool:
        if not isinstance(authenticated, AuthenticatedActionReceiptV1):
            return False
        if authenticated.authenticator_id != self.authenticator_id:
            return False
        expected = hmac.new(
            self._key,
            _canonical_payload(authenticated.receipt.as_dict()),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(authenticated.auth_tag, expected)


@dataclass(frozen=True, slots=True)
class AuthenticatedEmbodimentEnvelopeV1:
    """Whole local body snapshot plus integrity and channel provenance."""

    envelope: EmbodimentEnvelopeV1
    authenticator_id: str
    auth_tag: str

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EmbodimentEnvelopeV1):
            raise TypeError("envelope must be EmbodimentEnvelopeV1")
        _identifier(self.authenticator_id, "embodiment authenticator_id")
        _valid_tag(self.auth_tag, "embodiment auth_tag")

    @property
    def authorizes_actuation(self) -> bool:
        return False


class TrustedEmbodimentAuthenticatorV1:
    """Authenticates one complete local snapshot without granting motion."""

    __slots__ = ("_key", "authenticator_id")

    def __init__(self, *, authenticator_id: str, key: bytes) -> None:
        self.authenticator_id = _identifier(authenticator_id, "authenticator_id")
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("embodiment authentication key must contain at least 32 bytes")
        self._key = bytes(key)

    def authenticate(
        self, envelope: EmbodimentEnvelopeV1
    ) -> AuthenticatedEmbodimentEnvelopeV1:
        if not isinstance(envelope, EmbodimentEnvelopeV1):
            raise TypeError("envelope must be EmbodimentEnvelopeV1")
        tag = hmac.new(
            self._key, _canonical_payload(envelope.as_dict()), hashlib.sha256
        ).hexdigest()
        return AuthenticatedEmbodimentEnvelopeV1(envelope, self.authenticator_id, tag)

    def verify(self, authenticated: AuthenticatedEmbodimentEnvelopeV1) -> bool:
        if not isinstance(authenticated, AuthenticatedEmbodimentEnvelopeV1):
            return False
        if authenticated.authenticator_id != self.authenticator_id:
            return False
        expected = hmac.new(
            self._key,
            _canonical_payload(authenticated.envelope.as_dict()),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(authenticated.auth_tag, expected)


@dataclass(frozen=True, slots=True)
class AuthenticatedOperatorEvidenceV1:
    evidence: OperatorEvidenceV1
    authenticator_id: str
    auth_tag: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, OperatorEvidenceV1):
            raise TypeError("evidence must be OperatorEvidenceV1")
        _identifier(self.authenticator_id, "operator authenticator_id")
        _valid_tag(self.auth_tag, "operator auth_tag")

    @property
    def authorizes_actuation(self) -> bool:
        return False


class TrustedOperatorAuthenticatorV1:
    """Local operator-identity verifier; this grants no action authority."""

    __slots__ = ("_key", "authenticator_id")

    def __init__(self, *, authenticator_id: str, key: bytes) -> None:
        self.authenticator_id = _identifier(authenticator_id, "authenticator_id")
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("operator authentication key must contain at least 32 bytes")
        self._key = bytes(key)

    def authenticate(
        self, evidence: OperatorEvidenceV1
    ) -> AuthenticatedOperatorEvidenceV1:
        if not evidence.verified:
            raise ValueError("only verified operator evidence can be authenticated")
        tag = hmac.new(
            self._key, _canonical_payload(evidence.as_dict()), hashlib.sha256
        ).hexdigest()
        return AuthenticatedOperatorEvidenceV1(evidence, self.authenticator_id, tag)

    def verify(self, authenticated: AuthenticatedOperatorEvidenceV1) -> bool:
        if not isinstance(authenticated, AuthenticatedOperatorEvidenceV1):
            return False
        if authenticated.authenticator_id != self.authenticator_id:
            return False
        expected = hmac.new(
            self._key,
            _canonical_payload(authenticated.evidence.as_dict()),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(authenticated.auth_tag, expected)


__all__ = [
    "AuthenticatedActionReceiptV1",
    "AuthenticatedEmbodimentEnvelopeV1",
    "AuthenticatedOperatorEvidenceV1",
    "TrustedEmbodimentAuthenticatorV1",
    "TrustedOperatorAuthenticatorV1",
    "TrustedReceiptAuthenticatorV1",
]
