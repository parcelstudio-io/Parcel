"""Fail-closed independent completion contract for H2b.

This leaf deliberately does **not** integrate with :mod:`navigation.pipeline`
and cannot emit a velocity command.  It answers one question only: may an
upstream executive propose a terminal navigation claim after three independent
pieces of evidence agree?

The three authorities are kept separate and must enter through distinct,
process-local authenticated provider channels:

* a discriminative place-identity observation;
* a verified, strictly newer pose epoch rooted in an identity observation and
  supported by scan and landmark residuals; and
* target-relative terminal geometry whose covariance-expanded upper bound is
  inside the configured success radius.

A localization discontinuity invalidates every cached proof and raises the
minimum acceptable pose epoch.  Missing, stale, cross-epoch, replayed or
inconsistent evidence holds and eventually becomes typed uncertainty.  The
feature is default-disabled and every decision reports ``authorizes_motion``
as false.  This is an isolated contract for simulation/replay evaluation, not
physical authority.  Channel authentication proves only local interface
provenance; it does not prove that three production sensors are physically or
administratively independent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from parcel_robot.navigation.independent_completion_evidence import (
    SCHEMA_VERSION,
    AuthenticatedPlaceIdentityEvidenceV1,
    AuthenticatedPoseEpochVerificationV1,
    AuthenticatedTerminalGeometryEvidenceV1,
    PlaceIdentityEvidenceV1,
    PoseEpochVerificationV1,
    TerminalGeometryEvidenceV1,
    TrustedPlaceIdentityVerifierV1,
    TrustedPoseEpochVerifierV1,
    TrustedTerminalGeometryVerifierV1,
    _finite,
    _identifier,
    _integer,
    _probability,
    _schema,
)


class CompletionDispositionV1(str, Enum):
    """Possible outputs; only one is a positive terminal-claim proposal."""

    CONTINUE = "continue"
    HOLD = "hold"
    AUTHORIZE_TERMINAL_CLAIM = "authorize_terminal_claim"
    LOCALIZATION_UNCERTAIN = "localization_uncertain"


class CompletionReasonV1(str, Enum):
    """Stable diagnostics for the first fail-closed condition."""

    FEATURE_DISABLED = "feature_disabled"
    NO_MAP_CANDIDATE = "no_map_candidate"
    MAP_UNHEALTHY = "map_unhealthy"
    DISCONTINUITY_LATCHED = "discontinuity_latched"
    IDENTITY_UNAVAILABLE = "identity_unavailable"
    IDENTITY_AMBIGUOUS = "identity_ambiguous"
    VERIFIED_EPOCH_UNAVAILABLE = "verified_epoch_unavailable"
    EPOCH_NOT_NEW = "epoch_not_new"
    RESIDUAL_INCONSISTENT = "residual_inconsistent"
    TERMINAL_GEOMETRY_UNAVAILABLE = "terminal_geometry_unavailable"
    TERMINAL_GEOMETRY_OUTSIDE = "terminal_geometry_outside"
    EVIDENCE_STALE = "evidence_stale"
    EVIDENCE_LINEAGE_MISMATCH = "evidence_lineage_mismatch"
    EVIDENCE_AUTHENTICATION_FAILED = "evidence_authentication_failed"
    WAIT_TIMEOUT = "wait_timeout"
    TIME_REGRESSION = "time_regression"
    TERMINAL_CLAIM_AUTHORIZED = "terminal_claim_authorized"
    ALREADY_CLOSED = "already_closed"


@dataclass(frozen=True, slots=True)
class IndependentCompletionConfigV1:
    """Frozen H2b thresholds; disabled unless explicitly enabled by a caller."""

    enabled: bool = False
    discontinuity_score_min: float = 0.70
    identity_score_min: float = 0.70
    identity_margin_min: float = 0.15
    identity_max_age_s: float = 0.50
    reset_anchor_max_age_s: float = 2.00
    epoch_verification_max_age_s: float = 8.00
    scan_residual_max_m: float = 0.12
    landmark_residual_max_m: float = 0.15
    geometry_max_age_s: float = 0.40
    geometry_sigma_multiplier: float = 3.0
    geometry_guard_m: float = 0.01
    uncertainty_timeout_s: float = 4.0
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        for name in (
            "discontinuity_score_min",
            "identity_score_min",
            "identity_margin_min",
        ):
            _probability(getattr(self, name), name)
        for name in (
            "identity_max_age_s",
            "reset_anchor_max_age_s",
            "epoch_verification_max_age_s",
            "scan_residual_max_m",
            "landmark_residual_max_m",
            "geometry_max_age_s",
            "geometry_sigma_multiplier",
            "geometry_guard_m",
            "uncertainty_timeout_s",
        ):
            _finite(getattr(self, name), name, minimum=0.0)
        if self.identity_margin_min > self.identity_score_min:
            raise ValueError("identity_margin_min cannot exceed identity_score_min")
        if self.identity_max_age_s > self.reset_anchor_max_age_s:
            raise ValueError("reset anchors cannot expire before terminal identity evidence")
        if self.uncertainty_timeout_s <= 0.0:
            raise ValueError("uncertainty_timeout_s must be positive")


@dataclass(frozen=True, slots=True)
class IndependentCompletionGoalV1:
    """One goal and the pose epoch that existed when it was accepted."""

    goal_id: str
    goal_nonce: str
    target_place_id: str
    baseline_pose_epoch: int
    success_radius_m: float
    started_at_monotonic_ns: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        _identifier(self.goal_id, "goal_id")
        _identifier(self.goal_nonce, "goal_nonce")
        _identifier(self.target_place_id, "target_place_id")
        _integer(self.baseline_pose_epoch, "baseline_pose_epoch")
        _integer(self.started_at_monotonic_ns, "started_at_monotonic_ns")
        radius = _finite(self.success_radius_m, "success_radius_m", minimum=0.0)
        if radius <= 0.0:
            raise ValueError("success_radius_m must be positive")


@dataclass(frozen=True, slots=True)
class IndependentCompletionObservationV1:
    """One tick at the H2b boundary; scorer truth is intentionally absent."""

    now_monotonic_ns: int
    current_pose_epoch: int
    map_completion_candidate: bool
    map_healthy: bool
    discontinuity_score: float | None = None
    place_identity: AuthenticatedPlaceIdentityEvidenceV1 | None = None
    pose_epoch_verification: AuthenticatedPoseEpochVerificationV1 | None = None
    terminal_geometry: AuthenticatedTerminalGeometryEvidenceV1 | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        _integer(self.now_monotonic_ns, "now_monotonic_ns")
        _integer(self.current_pose_epoch, "current_pose_epoch")
        if not isinstance(self.map_completion_candidate, bool):
            raise TypeError("map_completion_candidate must be a boolean")
        if not isinstance(self.map_healthy, bool):
            raise TypeError("map_healthy must be a boolean")
        if self.discontinuity_score is not None:
            _probability(self.discontinuity_score, "discontinuity_score")
        if self.place_identity is not None and not isinstance(
            self.place_identity, AuthenticatedPlaceIdentityEvidenceV1
        ):
            raise TypeError("place_identity must be AuthenticatedPlaceIdentityEvidenceV1 or None")
        if self.pose_epoch_verification is not None and not isinstance(
            self.pose_epoch_verification, AuthenticatedPoseEpochVerificationV1
        ):
            raise TypeError(
                "pose_epoch_verification must be AuthenticatedPoseEpochVerificationV1 or None"
            )
        if self.terminal_geometry is not None and not isinstance(
            self.terminal_geometry, AuthenticatedTerminalGeometryEvidenceV1
        ):
            raise TypeError(
                "terminal_geometry must be AuthenticatedTerminalGeometryEvidenceV1 or None"
            )


@dataclass(frozen=True, slots=True)
class IndependentCompletionDecisionV1:
    """A bounded diagnostic/proposal, never a locomotion command."""

    disposition: CompletionDispositionV1
    reason: CompletionReasonV1
    unmet_requirements: tuple[str, ...]
    current_pose_epoch: int
    required_newer_than_epoch: int
    terminal_claim_authorized: bool = False
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        if not isinstance(self.disposition, CompletionDispositionV1):
            raise TypeError("disposition must be CompletionDispositionV1")
        if not isinstance(self.reason, CompletionReasonV1):
            raise TypeError("reason must be CompletionReasonV1")
        if not isinstance(self.unmet_requirements, tuple) or any(
            not isinstance(item, str) or not item for item in self.unmet_requirements
        ):
            raise TypeError("unmet_requirements must be a tuple of non-empty strings")
        _integer(self.current_pose_epoch, "current_pose_epoch")
        _integer(self.required_newer_than_epoch, "required_newer_than_epoch")
        if not isinstance(self.terminal_claim_authorized, bool):
            raise TypeError("terminal_claim_authorized must be a boolean")
        expected = self.disposition is CompletionDispositionV1.AUTHORIZE_TERMINAL_CLAIM
        if self.terminal_claim_authorized is not expected:
            raise ValueError("terminal_claim_authorized must match disposition")

    @property
    def authorizes_motion(self) -> bool:
        """H2b never grants locomotion authority, including on success."""

        return False


class IndependentCompletionLatchV1:
    """Stateful, one-shot evaluator for a single navigation goal."""

    def __init__(
        self,
        goal: IndependentCompletionGoalV1,
        config: IndependentCompletionConfigV1 | None = None,
        *,
        identity_verifier: TrustedPlaceIdentityVerifierV1 | None = None,
        pose_epoch_verifier: TrustedPoseEpochVerifierV1 | None = None,
        geometry_verifier: TrustedTerminalGeometryVerifierV1 | None = None,
    ) -> None:
        if not isinstance(goal, IndependentCompletionGoalV1):
            raise TypeError("goal must be IndependentCompletionGoalV1")
        if config is not None and not isinstance(config, IndependentCompletionConfigV1):
            raise TypeError("config must be IndependentCompletionConfigV1 or None")
        self.goal = goal
        self.config = config or IndependentCompletionConfigV1()
        channels = (identity_verifier, pose_epoch_verifier, geometry_verifier)
        if any(channel is not None for channel in channels):
            if not all(channel is not None for channel in channels):
                raise ValueError("all three evidence verifier channels are required")
            if not isinstance(identity_verifier, TrustedPlaceIdentityVerifierV1):
                raise TypeError("identity_verifier must be TrustedPlaceIdentityVerifierV1")
            if not isinstance(pose_epoch_verifier, TrustedPoseEpochVerifierV1):
                raise TypeError("pose_epoch_verifier must be TrustedPoseEpochVerifierV1")
            if not isinstance(geometry_verifier, TrustedTerminalGeometryVerifierV1):
                raise TypeError("geometry_verifier must be TrustedTerminalGeometryVerifierV1")
            provider_ids = {
                identity_verifier.provider_id,
                pose_epoch_verifier.provider_id,
                geometry_verifier.provider_id,
            }
            if len(provider_ids) != 3:
                raise ValueError("evidence verifier provider IDs must be distinct")
            verifier_ids = {
                identity_verifier.verifier_id,
                pose_epoch_verifier.verifier_id,
                geometry_verifier.verifier_id,
            }
            if len(verifier_ids) != 3:
                raise ValueError("evidence verifier IDs must be distinct")
            if (
                len(
                    {
                        identity_verifier._key,
                        pose_epoch_verifier._key,
                        geometry_verifier._key,
                    }
                )
                != 3
            ):
                raise ValueError("evidence verifier authentication keys must be distinct")
        elif self.config.enabled:
            raise ValueError(
                "enabled independent completion requires three evidence verifier channels"
            )
        self._identity_verifier = identity_verifier
        self._pose_epoch_verifier = pose_epoch_verifier
        self._geometry_verifier = geometry_verifier
        self._required_newer_than_epoch = goal.baseline_pose_epoch
        self._last_now_ns = goal.started_at_monotonic_ns
        self._waiting_since_ns: int | None = None
        self._discontinuity_latched = False
        self._qualified_identities: dict[str, PlaceIdentityEvidenceV1] = {}
        self._verified_epoch: PoseEpochVerificationV1 | None = None
        self._terminal_geometry: TerminalGeometryEvidenceV1 | None = None
        self._closed = False

    @property
    def required_newer_than_epoch(self) -> int:
        return self._required_newer_than_epoch

    @property
    def discontinuity_latched(self) -> bool:
        return self._discontinuity_latched

    def _decision(
        self,
        disposition: CompletionDispositionV1,
        reason: CompletionReasonV1,
        observation: IndependentCompletionObservationV1,
        unmet: tuple[str, ...] = (),
    ) -> IndependentCompletionDecisionV1:
        return IndependentCompletionDecisionV1(
            disposition=disposition,
            reason=reason,
            unmet_requirements=unmet,
            current_pose_epoch=observation.current_pose_epoch,
            required_newer_than_epoch=self._required_newer_than_epoch,
            terminal_claim_authorized=(
                disposition is CompletionDispositionV1.AUTHORIZE_TERMINAL_CLAIM
            ),
        )

    @staticmethod
    def _age_s(now_ns: int, then_ns: int) -> float:
        return (now_ns - then_ns) / 1_000_000_000.0

    def _identity_qualifies(
        self,
        evidence: PlaceIdentityEvidenceV1,
        now_ns: int,
        *,
        max_age_s: float,
    ) -> bool:
        age_s = self._age_s(now_ns, evidence.captured_at_monotonic_ns)
        return (
            0.0 <= age_s <= max_age_s
            and evidence.received_at_monotonic_ns <= now_ns
            and evidence.target_score >= self.config.identity_score_min
            and evidence.score_margin >= self.config.identity_margin_min
        )

    def _bound_to_goal(self, goal_id: str, goal_nonce: str) -> bool:
        return goal_id == self.goal.goal_id and goal_nonce == self.goal.goal_nonce

    def _after_goal_start(self, *timestamps_ns: int) -> bool:
        return all(
            timestamp_ns >= self.goal.started_at_monotonic_ns for timestamp_ns in timestamps_ns
        )

    def _prune_identities(self, now_ns: int) -> None:
        self._qualified_identities = {
            evidence_id: evidence
            for evidence_id, evidence in self._qualified_identities.items()
            if self._identity_qualifies(
                evidence,
                now_ns,
                max_age_s=self.config.reset_anchor_max_age_s,
            )
        }

    def _observe_identity(
        self,
        authenticated: AuthenticatedPlaceIdentityEvidenceV1 | None,
        now_ns: int,
        current_pose_epoch: int,
    ) -> CompletionReasonV1 | None:
        if authenticated is None:
            return None
        verifier = self._identity_verifier
        if verifier is None or not verifier.verify(authenticated):
            return CompletionReasonV1.EVIDENCE_AUTHENTICATION_FAILED
        evidence = authenticated.evidence
        if not self._bound_to_goal(evidence.goal_id, evidence.goal_nonce):
            return CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        if not self._after_goal_start(
            evidence.captured_at_monotonic_ns,
            evidence.received_at_monotonic_ns,
        ):
            return CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        if evidence.pose_epoch != current_pose_epoch:
            return CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        if evidence.received_at_monotonic_ns > now_ns or evidence.captured_at_monotonic_ns > now_ns:
            return CompletionReasonV1.EVIDENCE_STALE
        if (
            evidence.target_score < self.config.identity_score_min
            or evidence.score_margin < self.config.identity_margin_min
        ):
            return CompletionReasonV1.IDENTITY_AMBIGUOUS
        if not self._identity_qualifies(
            evidence,
            now_ns,
            max_age_s=self.config.reset_anchor_max_age_s,
        ):
            return CompletionReasonV1.EVIDENCE_STALE
        self._qualified_identities[evidence.observation_id] = evidence
        return None

    def _observe_epoch_verification(
        self,
        authenticated: AuthenticatedPoseEpochVerificationV1 | None,
        now_ns: int,
        current_pose_epoch: int,
    ) -> CompletionReasonV1 | None:
        if authenticated is None:
            return None
        verifier = self._pose_epoch_verifier
        if verifier is None or not verifier.verify(authenticated):
            return CompletionReasonV1.EVIDENCE_AUTHENTICATION_FAILED
        evidence = authenticated.evidence
        if not self._bound_to_goal(evidence.goal_id, evidence.goal_nonce):
            return CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        if not self._after_goal_start(
            evidence.reset_at_monotonic_ns,
            evidence.verified_at_monotonic_ns,
            evidence.received_at_monotonic_ns,
        ):
            return CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        if evidence.pose_epoch != current_pose_epoch:
            return CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        anchor = self._qualified_identities.get(evidence.anchor_observation_id)
        if anchor is None:
            return CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        if (
            evidence.received_at_monotonic_ns > now_ns
            or evidence.verified_at_monotonic_ns > now_ns
            or self._age_s(now_ns, evidence.verified_at_monotonic_ns)
            > self.config.epoch_verification_max_age_s
        ):
            return CompletionReasonV1.EVIDENCE_STALE
        if (
            evidence.parent_pose_epoch != self._required_newer_than_epoch
            or evidence.pose_epoch <= self._required_newer_than_epoch
            or anchor.pose_epoch != evidence.parent_pose_epoch
            or evidence.reset_at_monotonic_ns < anchor.captured_at_monotonic_ns
        ):
            return CompletionReasonV1.EPOCH_NOT_NEW
        if (
            evidence.scan_residual_m > self.config.scan_residual_max_m
            or evidence.landmark_residual_m > self.config.landmark_residual_max_m
        ):
            return CompletionReasonV1.RESIDUAL_INCONSISTENT
        self._verified_epoch = evidence
        self._terminal_geometry = None
        return None

    def _observe_geometry(
        self,
        authenticated: AuthenticatedTerminalGeometryEvidenceV1 | None,
        now_ns: int,
        current_pose_epoch: int,
    ) -> CompletionReasonV1 | None:
        if authenticated is None:
            return None
        verifier = self._geometry_verifier
        if verifier is None or not verifier.verify(authenticated):
            return CompletionReasonV1.EVIDENCE_AUTHENTICATION_FAILED
        evidence = authenticated.evidence
        if not self._bound_to_goal(evidence.goal_id, evidence.goal_nonce):
            return CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        if not self._after_goal_start(
            evidence.captured_at_monotonic_ns,
            evidence.received_at_monotonic_ns,
        ):
            return CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        if evidence.pose_epoch != current_pose_epoch:
            return CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        if (
            evidence.received_at_monotonic_ns > now_ns
            or evidence.captured_at_monotonic_ns > now_ns
            or self._age_s(now_ns, evidence.captured_at_monotonic_ns)
            > self.config.geometry_max_age_s
        ):
            return CompletionReasonV1.EVIDENCE_STALE
        self._terminal_geometry = evidence
        return None

    def _terminal_identity(
        self,
        observation: IndependentCompletionObservationV1,
    ) -> PlaceIdentityEvidenceV1 | None:
        verified = self._verified_epoch
        if verified is None:
            return None
        eligible = (
            evidence
            for evidence in self._qualified_identities.values()
            if evidence.place_id == self.goal.target_place_id
            and evidence.pose_epoch == observation.current_pose_epoch
            and evidence.captured_at_monotonic_ns >= verified.verified_at_monotonic_ns
            and self._identity_qualifies(
                evidence,
                observation.now_monotonic_ns,
                max_age_s=self.config.identity_max_age_s,
            )
        )
        return max(eligible, key=lambda item: item.captured_at_monotonic_ns, default=None)

    def _geometry_upper_bound_m(self, evidence: TerminalGeometryEvidenceV1) -> float:
        sigma_m = math.sqrt(evidence.largest_covariance_eigenvalue_m2)
        return evidence.mean_range_m + self.config.geometry_sigma_multiplier * sigma_m

    def _requirements(
        self,
        observation: IndependentCompletionObservationV1,
    ) -> tuple[tuple[str, ...], CompletionReasonV1]:
        unmet: list[str] = []
        reason = CompletionReasonV1.DISCONTINUITY_LATCHED
        if not observation.map_completion_candidate:
            unmet.append("map_completion_candidate")
            reason = CompletionReasonV1.NO_MAP_CANDIDATE
        if not observation.map_healthy:
            unmet.append("map_healthy")
            if reason is CompletionReasonV1.DISCONTINUITY_LATCHED:
                reason = CompletionReasonV1.MAP_UNHEALTHY

        verified = self._verified_epoch
        if verified is None:
            unmet.append("verified_new_pose_epoch")
            if reason is CompletionReasonV1.DISCONTINUITY_LATCHED:
                reason = CompletionReasonV1.VERIFIED_EPOCH_UNAVAILABLE
        elif (
            verified.pose_epoch != observation.current_pose_epoch
            or verified.pose_epoch <= self._required_newer_than_epoch
        ):
            unmet.append("verified_current_pose_epoch")
            if reason is CompletionReasonV1.DISCONTINUITY_LATCHED:
                reason = CompletionReasonV1.EPOCH_NOT_NEW

        identity = self._terminal_identity(observation)
        if identity is None:
            unmet.append("fresh_target_identity")
            if reason is CompletionReasonV1.DISCONTINUITY_LATCHED:
                reason = CompletionReasonV1.IDENTITY_UNAVAILABLE

        geometry = self._terminal_geometry
        if geometry is None:
            unmet.append("fresh_terminal_geometry")
            if reason is CompletionReasonV1.DISCONTINUITY_LATCHED:
                reason = CompletionReasonV1.TERMINAL_GEOMETRY_UNAVAILABLE
        elif (
            identity is None
            or verified is None
            or (
                geometry.target_place_id != self.goal.target_place_id
                or geometry.identity_observation_id != identity.observation_id
                or geometry.pose_epoch != observation.current_pose_epoch
                or geometry.pose_epoch != verified.pose_epoch
                or geometry.captured_at_monotonic_ns < identity.captured_at_monotonic_ns
            )
        ):
            unmet.append("terminal_geometry_lineage")
            if reason is CompletionReasonV1.DISCONTINUITY_LATCHED:
                reason = CompletionReasonV1.EVIDENCE_LINEAGE_MISMATCH
        elif (
            self._age_s(observation.now_monotonic_ns, geometry.captured_at_monotonic_ns)
            > self.config.geometry_max_age_s
        ):
            unmet.append("fresh_terminal_geometry")
            if reason is CompletionReasonV1.DISCONTINUITY_LATCHED:
                reason = CompletionReasonV1.EVIDENCE_STALE
        else:
            conservative_limit_m = self.goal.success_radius_m - self.config.geometry_guard_m
            if conservative_limit_m <= 0.0 or (
                self._geometry_upper_bound_m(geometry) > conservative_limit_m
            ):
                unmet.append("conservative_terminal_geometry")
                if reason is CompletionReasonV1.DISCONTINUITY_LATCHED:
                    reason = CompletionReasonV1.TERMINAL_GEOMETRY_OUTSIDE

        return tuple(dict.fromkeys(unmet)), reason

    def _apply_discontinuity(self, observation: IndependentCompletionObservationV1) -> None:
        score = observation.discontinuity_score
        if score is None or score < self.config.discontinuity_score_min:
            return
        self._required_newer_than_epoch = max(
            self._required_newer_than_epoch,
            observation.current_pose_epoch,
        )
        self._discontinuity_latched = True
        self._qualified_identities.clear()
        self._verified_epoch = None
        self._terminal_geometry = None
        if self._waiting_since_ns is None:
            self._waiting_since_ns = observation.now_monotonic_ns

    def _expire_cached_verification(self, now_ns: int) -> bool:
        verified = self._verified_epoch
        if verified is None:
            return False
        age_s = self._age_s(now_ns, verified.verified_at_monotonic_ns)
        if (
            age_s < 0.0
            or age_s > self.config.epoch_verification_max_age_s
            or verified.received_at_monotonic_ns > now_ns
        ):
            self._verified_epoch = None
            self._terminal_geometry = None
            return True
        return False

    def _ingest_observation(
        self, observation: IndependentCompletionObservationV1
    ) -> CompletionReasonV1 | None:
        verification_expired = self._expire_cached_verification(observation.now_monotonic_ns)
        self._prune_identities(observation.now_monotonic_ns)
        self._apply_discontinuity(observation)
        identity_issue = self._observe_identity(
            observation.place_identity,
            observation.now_monotonic_ns,
            observation.current_pose_epoch,
        )
        epoch_issue = self._observe_epoch_verification(
            observation.pose_epoch_verification,
            observation.now_monotonic_ns,
            observation.current_pose_epoch,
        )
        if observation.pose_epoch_verification is not None and epoch_issue is None:
            verification_expired = False
        geometry_issue = self._observe_geometry(
            observation.terminal_geometry,
            observation.now_monotonic_ns,
            observation.current_pose_epoch,
        )
        if observation.map_completion_candidate and self._waiting_since_ns is None:
            self._waiting_since_ns = observation.now_monotonic_ns
        return (
            identity_issue
            or epoch_issue
            or geometry_issue
            or (CompletionReasonV1.EVIDENCE_STALE if verification_expired else None)
        )

    def _terminal_or_waiting_decision(
        self,
        observation: IndependentCompletionObservationV1,
        unmet: tuple[str, ...],
        reason: CompletionReasonV1,
    ) -> IndependentCompletionDecisionV1:
        if not unmet:
            self._closed = True
            self._discontinuity_latched = False
            return self._decision(
                CompletionDispositionV1.AUTHORIZE_TERMINAL_CLAIM,
                CompletionReasonV1.TERMINAL_CLAIM_AUTHORIZED,
                observation,
            )
        if self._waiting_since_ns is None:
            return self._decision(
                CompletionDispositionV1.CONTINUE,
                CompletionReasonV1.NO_MAP_CANDIDATE,
                observation,
                unmet,
            )
        waited_s = self._age_s(observation.now_monotonic_ns, self._waiting_since_ns)
        if waited_s >= self.config.uncertainty_timeout_s:
            self._closed = True
            return self._decision(
                CompletionDispositionV1.LOCALIZATION_UNCERTAIN,
                CompletionReasonV1.WAIT_TIMEOUT,
                observation,
                unmet,
            )
        return self._decision(
            CompletionDispositionV1.HOLD,
            reason,
            observation,
            unmet,
        )

    def step(
        self, observation: IndependentCompletionObservationV1
    ) -> IndependentCompletionDecisionV1:
        """Consume one tick and return a proposal/hold; never a motion command."""

        if not isinstance(observation, IndependentCompletionObservationV1):
            raise TypeError("observation must be IndependentCompletionObservationV1")
        if self._closed:
            return self._decision(
                CompletionDispositionV1.HOLD,
                CompletionReasonV1.ALREADY_CLOSED,
                observation,
                ("new_goal_required",),
            )
        if observation.now_monotonic_ns < self._last_now_ns:
            self._closed = True
            self._qualified_identities.clear()
            self._verified_epoch = None
            self._terminal_geometry = None
            return self._decision(
                CompletionDispositionV1.LOCALIZATION_UNCERTAIN,
                CompletionReasonV1.TIME_REGRESSION,
                observation,
                ("monotonic_time",),
            )
        self._last_now_ns = observation.now_monotonic_ns

        if not self.config.enabled:
            return self._decision(
                CompletionDispositionV1.HOLD,
                CompletionReasonV1.FEATURE_DISABLED,
                observation,
                ("feature_enabled",),
            )

        issue = self._ingest_observation(observation)
        unmet, reason = self._requirements(observation)
        if issue is CompletionReasonV1.EVIDENCE_AUTHENTICATION_FAILED:
            unmet = tuple(dict.fromkeys((*unmet, "authenticated_evidence")))
            reason = issue
        if issue is not None and reason in {
            CompletionReasonV1.DISCONTINUITY_LATCHED,
            CompletionReasonV1.IDENTITY_UNAVAILABLE,
            CompletionReasonV1.VERIFIED_EPOCH_UNAVAILABLE,
            CompletionReasonV1.TERMINAL_GEOMETRY_UNAVAILABLE,
        }:
            reason = issue
        return self._terminal_or_waiting_decision(observation, unmet, reason)


__all__ = [
    "AuthenticatedPlaceIdentityEvidenceV1",
    "AuthenticatedPoseEpochVerificationV1",
    "AuthenticatedTerminalGeometryEvidenceV1",
    "CompletionDispositionV1",
    "CompletionReasonV1",
    "IndependentCompletionConfigV1",
    "IndependentCompletionDecisionV1",
    "IndependentCompletionGoalV1",
    "IndependentCompletionLatchV1",
    "IndependentCompletionObservationV1",
    "PlaceIdentityEvidenceV1",
    "PoseEpochVerificationV1",
    "TerminalGeometryEvidenceV1",
    "TrustedPlaceIdentityVerifierV1",
    "TrustedPoseEpochVerifierV1",
    "TrustedTerminalGeometryVerifierV1",
]
