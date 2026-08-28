"""Leaf evidence and process-local authentication contracts for H2b.

This module intentionally imports no navigation policy, pipeline, executive or
actuator surface.  It authenticates exact software-interface payloads and
provider identities; it does not establish independent production sensors,
processes, administrators or failure domains.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import dataclass

SCHEMA_VERSION = 2
MAX_IDENTIFIER_CHARS = 128
MAX_PUBLIC_INTEGER = (1 << 64) - 1
EVIDENCE_AUTH_SCHEMA = "parcel.independent-completion.evidence-auth.v1"


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_IDENTIFIER_CHARS:
        raise ValueError(
            f"{name} must be a non-empty string up to {MAX_IDENTIFIER_CHARS} characters"
        )
    return value


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum or value > MAX_PUBLIC_INTEGER:
        raise ValueError(f"{name} must be in [{minimum}, {MAX_PUBLIC_INTEGER}]")
    return value


def _finite(value: object, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


def _probability(value: object, name: str) -> float:
    result = _finite(value, name)
    if result < 0.0 or result > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _schema(value: object) -> None:
    if isinstance(value, bool) or value != SCHEMA_VERSION:
        raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")


def _valid_auth_tag(value: object, name: str = "auth_tag") -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 HMAC")


def _canonical_auth_payload(
    *,
    channel: str,
    provider_id: str,
    verifier_id: str,
    evidence: dict[str, object],
) -> bytes:
    return json.dumps(
        {
            "auth_schema": EVIDENCE_AUTH_SCHEMA,
            "channel": channel,
            "evidence": evidence,
            "provider_id": provider_id,
            "verifier_id": verifier_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


@dataclass(frozen=True, slots=True)
class PlaceIdentityEvidenceV1:
    """A discriminative place observation in one explicit pose epoch."""

    observation_id: str
    goal_id: str
    goal_nonce: str
    place_id: str
    pose_epoch: int
    captured_at_monotonic_ns: int
    received_at_monotonic_ns: int
    target_score: float
    runner_up_score: float
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        _identifier(self.observation_id, "observation_id")
        _identifier(self.goal_id, "goal_id")
        _identifier(self.goal_nonce, "goal_nonce")
        _identifier(self.place_id, "place_id")
        _integer(self.pose_epoch, "pose_epoch")
        captured = _integer(self.captured_at_monotonic_ns, "captured_at_monotonic_ns")
        received = _integer(self.received_at_monotonic_ns, "received_at_monotonic_ns")
        if received < captured:
            raise ValueError("received_at_monotonic_ns must not precede capture")
        _probability(self.target_score, "target_score")
        _probability(self.runner_up_score, "runner_up_score")

    @property
    def score_margin(self) -> float:
        return self.target_score - self.runner_up_score

    def as_dict(self) -> dict[str, object]:
        return {
            "captured_at_monotonic_ns": self.captured_at_monotonic_ns,
            "goal_id": self.goal_id,
            "goal_nonce": self.goal_nonce,
            "observation_id": self.observation_id,
            "place_id": self.place_id,
            "pose_epoch": self.pose_epoch,
            "received_at_monotonic_ns": self.received_at_monotonic_ns,
            "runner_up_score": self.runner_up_score,
            "schema_version": self.schema_version,
            "target_score": self.target_score,
        }


@dataclass(frozen=True, slots=True)
class PoseEpochVerificationV1:
    """Proof that an identity-rooted reset created and verified a new epoch."""

    verification_id: str
    goal_id: str
    goal_nonce: str
    reset_id: str
    anchor_observation_id: str
    parent_pose_epoch: int
    pose_epoch: int
    reset_at_monotonic_ns: int
    verified_at_monotonic_ns: int
    received_at_monotonic_ns: int
    scan_residual_m: float
    landmark_residual_m: float
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        _identifier(self.verification_id, "verification_id")
        _identifier(self.goal_id, "goal_id")
        _identifier(self.goal_nonce, "goal_nonce")
        _identifier(self.reset_id, "reset_id")
        _identifier(self.anchor_observation_id, "anchor_observation_id")
        parent = _integer(self.parent_pose_epoch, "parent_pose_epoch")
        epoch = _integer(self.pose_epoch, "pose_epoch")
        if epoch <= parent:
            raise ValueError("pose_epoch must be strictly newer than parent_pose_epoch")
        reset = _integer(self.reset_at_monotonic_ns, "reset_at_monotonic_ns")
        verified = _integer(self.verified_at_monotonic_ns, "verified_at_monotonic_ns")
        received = _integer(self.received_at_monotonic_ns, "received_at_monotonic_ns")
        if not reset <= verified <= received:
            raise ValueError("reset, verification and receipt timestamps must be ordered")
        _finite(self.scan_residual_m, "scan_residual_m", minimum=0.0)
        _finite(self.landmark_residual_m, "landmark_residual_m", minimum=0.0)

    def as_dict(self) -> dict[str, object]:
        return {
            "anchor_observation_id": self.anchor_observation_id,
            "goal_id": self.goal_id,
            "goal_nonce": self.goal_nonce,
            "landmark_residual_m": self.landmark_residual_m,
            "parent_pose_epoch": self.parent_pose_epoch,
            "pose_epoch": self.pose_epoch,
            "received_at_monotonic_ns": self.received_at_monotonic_ns,
            "reset_at_monotonic_ns": self.reset_at_monotonic_ns,
            "reset_id": self.reset_id,
            "scan_residual_m": self.scan_residual_m,
            "schema_version": self.schema_version,
            "verification_id": self.verification_id,
            "verified_at_monotonic_ns": self.verified_at_monotonic_ns,
        }


@dataclass(frozen=True, slots=True)
class TerminalGeometryEvidenceV1:
    """Target-relative mean and 2-D covariance in a verified pose epoch."""

    evidence_id: str
    goal_id: str
    goal_nonce: str
    target_place_id: str
    identity_observation_id: str
    pose_epoch: int
    captured_at_monotonic_ns: int
    received_at_monotonic_ns: int
    relative_x_m: float
    relative_y_m: float
    covariance_xx_m2: float
    covariance_xy_m2: float
    covariance_yy_m2: float
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        _identifier(self.evidence_id, "evidence_id")
        _identifier(self.goal_id, "goal_id")
        _identifier(self.goal_nonce, "goal_nonce")
        _identifier(self.target_place_id, "target_place_id")
        _identifier(self.identity_observation_id, "identity_observation_id")
        _integer(self.pose_epoch, "pose_epoch")
        captured = _integer(self.captured_at_monotonic_ns, "captured_at_monotonic_ns")
        received = _integer(self.received_at_monotonic_ns, "received_at_monotonic_ns")
        if received < captured:
            raise ValueError("received_at_monotonic_ns must not precede capture")
        _finite(self.relative_x_m, "relative_x_m")
        _finite(self.relative_y_m, "relative_y_m")
        xx = _finite(self.covariance_xx_m2, "covariance_xx_m2", minimum=0.0)
        xy = _finite(self.covariance_xy_m2, "covariance_xy_m2")
        yy = _finite(self.covariance_yy_m2, "covariance_yy_m2", minimum=0.0)
        if xx * yy - xy * xy < -1e-12:
            raise ValueError("terminal covariance must be positive semidefinite")

    @property
    def mean_range_m(self) -> float:
        return math.hypot(self.relative_x_m, self.relative_y_m)

    @property
    def largest_covariance_eigenvalue_m2(self) -> float:
        trace = self.covariance_xx_m2 + self.covariance_yy_m2
        delta = self.covariance_xx_m2 - self.covariance_yy_m2
        discriminant = math.sqrt(max(0.0, delta * delta + 4.0 * self.covariance_xy_m2**2))
        return max(0.0, 0.5 * (trace + discriminant))

    def as_dict(self) -> dict[str, object]:
        return {
            "captured_at_monotonic_ns": self.captured_at_monotonic_ns,
            "covariance_xx_m2": self.covariance_xx_m2,
            "covariance_xy_m2": self.covariance_xy_m2,
            "covariance_yy_m2": self.covariance_yy_m2,
            "evidence_id": self.evidence_id,
            "goal_id": self.goal_id,
            "goal_nonce": self.goal_nonce,
            "identity_observation_id": self.identity_observation_id,
            "pose_epoch": self.pose_epoch,
            "received_at_monotonic_ns": self.received_at_monotonic_ns,
            "relative_x_m": self.relative_x_m,
            "relative_y_m": self.relative_y_m,
            "schema_version": self.schema_version,
            "target_place_id": self.target_place_id,
        }


@dataclass(frozen=True, slots=True)
class AuthenticatedPlaceIdentityEvidenceV1:
    """Identity evidence authenticated by one exact local provider channel."""

    evidence: PlaceIdentityEvidenceV1
    provider_id: str
    verifier_id: str
    auth_tag: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, PlaceIdentityEvidenceV1):
            raise TypeError("evidence must be PlaceIdentityEvidenceV1")
        _identifier(self.provider_id, "identity provider_id")
        _identifier(self.verifier_id, "identity verifier_id")
        _valid_auth_tag(self.auth_tag, "identity auth_tag")

    @property
    def authorizes_motion(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class AuthenticatedPoseEpochVerificationV1:
    """Pose-reset evidence authenticated by one exact local provider channel."""

    evidence: PoseEpochVerificationV1
    provider_id: str
    verifier_id: str
    auth_tag: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, PoseEpochVerificationV1):
            raise TypeError("evidence must be PoseEpochVerificationV1")
        _identifier(self.provider_id, "pose epoch provider_id")
        _identifier(self.verifier_id, "pose epoch verifier_id")
        _valid_auth_tag(self.auth_tag, "pose epoch auth_tag")

    @property
    def authorizes_motion(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class AuthenticatedTerminalGeometryEvidenceV1:
    """Terminal geometry authenticated by one exact local provider channel."""

    evidence: TerminalGeometryEvidenceV1
    provider_id: str
    verifier_id: str
    auth_tag: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, TerminalGeometryEvidenceV1):
            raise TypeError("evidence must be TerminalGeometryEvidenceV1")
        _identifier(self.provider_id, "geometry provider_id")
        _identifier(self.verifier_id, "geometry verifier_id")
        _valid_auth_tag(self.auth_tag, "geometry auth_tag")

    @property
    def authorizes_motion(self) -> bool:
        return False


class _TrustedEvidenceVerifierV1:
    """Shared process-local HMAC mechanics; subclasses fix the evidence role."""

    __slots__ = ("_key", "provider_id", "verifier_id")
    _channel = ""

    def __init__(self, *, provider_id: str, verifier_id: str, key: bytes) -> None:
        self.provider_id = _identifier(provider_id, "provider_id")
        self.verifier_id = _identifier(verifier_id, "verifier_id")
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("evidence authentication key must contain at least 32 bytes")
        self._key = bytes(key)

    def _tag(self, evidence: dict[str, object]) -> str:
        return hmac.new(
            self._key,
            _canonical_auth_payload(
                channel=self._channel,
                provider_id=self.provider_id,
                verifier_id=self.verifier_id,
                evidence=evidence,
            ),
            hashlib.sha256,
        ).hexdigest()


class TrustedPlaceIdentityVerifierV1(_TrustedEvidenceVerifierV1):
    """Commissionable local verifier for the place-identity evidence role."""

    __slots__ = ()
    _channel = "place_identity"

    def authenticate(
        self, evidence: PlaceIdentityEvidenceV1
    ) -> AuthenticatedPlaceIdentityEvidenceV1:
        if not isinstance(evidence, PlaceIdentityEvidenceV1):
            raise TypeError("evidence must be PlaceIdentityEvidenceV1")
        return AuthenticatedPlaceIdentityEvidenceV1(
            evidence=evidence,
            provider_id=self.provider_id,
            verifier_id=self.verifier_id,
            auth_tag=self._tag(evidence.as_dict()),
        )

    def verify(self, authenticated: AuthenticatedPlaceIdentityEvidenceV1) -> bool:
        return (
            isinstance(authenticated, AuthenticatedPlaceIdentityEvidenceV1)
            and authenticated.provider_id == self.provider_id
            and authenticated.verifier_id == self.verifier_id
            and hmac.compare_digest(
                authenticated.auth_tag,
                self._tag(authenticated.evidence.as_dict()),
            )
        )


class TrustedPoseEpochVerifierV1(_TrustedEvidenceVerifierV1):
    """Commissionable local verifier for identity-rooted pose-reset evidence."""

    __slots__ = ()
    _channel = "pose_epoch_verification"

    def authenticate(
        self, evidence: PoseEpochVerificationV1
    ) -> AuthenticatedPoseEpochVerificationV1:
        if not isinstance(evidence, PoseEpochVerificationV1):
            raise TypeError("evidence must be PoseEpochVerificationV1")
        return AuthenticatedPoseEpochVerificationV1(
            evidence=evidence,
            provider_id=self.provider_id,
            verifier_id=self.verifier_id,
            auth_tag=self._tag(evidence.as_dict()),
        )

    def verify(self, authenticated: AuthenticatedPoseEpochVerificationV1) -> bool:
        return (
            isinstance(authenticated, AuthenticatedPoseEpochVerificationV1)
            and authenticated.provider_id == self.provider_id
            and authenticated.verifier_id == self.verifier_id
            and hmac.compare_digest(
                authenticated.auth_tag,
                self._tag(authenticated.evidence.as_dict()),
            )
        )


class TrustedTerminalGeometryVerifierV1(_TrustedEvidenceVerifierV1):
    """Commissionable local verifier for target-relative geometry evidence."""

    __slots__ = ()
    _channel = "terminal_geometry"

    def authenticate(
        self, evidence: TerminalGeometryEvidenceV1
    ) -> AuthenticatedTerminalGeometryEvidenceV1:
        if not isinstance(evidence, TerminalGeometryEvidenceV1):
            raise TypeError("evidence must be TerminalGeometryEvidenceV1")
        return AuthenticatedTerminalGeometryEvidenceV1(
            evidence=evidence,
            provider_id=self.provider_id,
            verifier_id=self.verifier_id,
            auth_tag=self._tag(evidence.as_dict()),
        )

    def verify(self, authenticated: AuthenticatedTerminalGeometryEvidenceV1) -> bool:
        return (
            isinstance(authenticated, AuthenticatedTerminalGeometryEvidenceV1)
            and authenticated.provider_id == self.provider_id
            and authenticated.verifier_id == self.verifier_id
            and hmac.compare_digest(
                authenticated.auth_tag,
                self._tag(authenticated.evidence.as_dict()),
            )
        )


__all__ = [
    "SCHEMA_VERSION",
    "AuthenticatedPlaceIdentityEvidenceV1",
    "AuthenticatedPoseEpochVerificationV1",
    "AuthenticatedTerminalGeometryEvidenceV1",
    "PlaceIdentityEvidenceV1",
    "PoseEpochVerificationV1",
    "TerminalGeometryEvidenceV1",
    "TrustedPlaceIdentityVerifierV1",
    "TrustedPoseEpochVerifierV1",
    "TrustedTerminalGeometryVerifierV1",
]
