"""Bounded, simulator-only contracts for learned whole-body motion proposals.

This module deliberately stops above every motor boundary.  A conversation or
planning model may select reviewed *names* for a gait, a style, and a body
target.  It cannot supply velocity, joint, torque, trajectory, or latent-vector
values.  A trusted caller then checks those names against a content-bound
catalog and an explicit transition graph before receiving a
:class:`MotionIntentV1` proposal.

The proposal is not a command.  It has no dispatch method and it never grants
motion authority.  A downstream simulator executive still has to resolve the
named targets to reviewed skills and pass through its ordinary safety/admission
chain.  Version 1 cannot be commissioned for a physical robot.

Policy artifacts are represented only by SHA-256 digests.  Their observation
schema, reviewed categorical action schema, catalog, and transition graph are
bound into a deterministic candidate digest.  This makes simulator experiments
reproducible without turning a learned artifact into executable authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

SCHEMA_VERSION = 1
SIM_CANDIDATE = "sim_candidate"
SIMULATOR_ONLY = "simulator_only"
REVIEWED_CATEGORICAL_ACTIONS = "reviewed_categorical_targets_v1"

TargetKind = Literal["gait", "style", "body"]
TARGET_KINDS: tuple[TargetKind, ...] = ("body", "gait", "style")

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class GeneralizedMotionContractError(ValueError):
    """A simulator motion-learning boundary value is malformed or unsafe."""


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise GeneralizedMotionContractError(f"{name} must be a bounded identifier")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise GeneralizedMotionContractError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _exact_mapping(
    value: object,
    fields: frozenset[str],
    name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GeneralizedMotionContractError(f"{name} must be a mapping")
    keys = set(value)
    missing = fields - keys
    extra = keys - fields
    if missing:
        raise GeneralizedMotionContractError(f"{name} missing fields: {sorted(missing)}")
    if extra:
        raise GeneralizedMotionContractError(f"{name} has unknown fields: {sorted(extra)}")
    return value


def _version(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GeneralizedMotionContractError(f"{name} must be an integer")
    if value != SCHEMA_VERSION:
        raise GeneralizedMotionContractError(f"{name} must equal {SCHEMA_VERSION}")
    return value


def _exact_false(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise GeneralizedMotionContractError(f"{name} must be a boolean")
    if value:
        raise GeneralizedMotionContractError(f"{name} must remain false in schema v1")
    return value


def _controller_frequency(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeneralizedMotionContractError("controller_frequency_hz must be a finite number")
    result = float(value)
    if not math.isfinite(result) or not 1.0 <= result <= 1_000.0:
        raise GeneralizedMotionContractError(
            "controller_frequency_hz must be between 1 and 1000 Hz"
        )
    return result


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise GeneralizedMotionContractError(f"value is not canonical JSON: {error}") from error


def canonical_digest(value: object) -> str:
    """Return the canonical JSON SHA-256 used by every contract in this module."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ReviewedMotionTargetV1:
    """One named target with externally reviewed, content-bound evidence.

    ``review_evidence_digest`` binds the record to evidence; it is not itself a
    signature or a claim that the reviewer is trusted.  The catalog supplied to
    :func:`admit_language_selection` must come from trusted configuration.
    """

    kind: TargetKind
    target_id: str
    review_authority_id: str
    review_evidence_digest: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version, "ReviewedMotionTargetV1 schema_version")
        if self.kind not in TARGET_KINDS:
            raise GeneralizedMotionContractError(f"target kind must be one of {list(TARGET_KINDS)}")
        _identifier(self.target_id, "target_id")
        _identifier(self.review_authority_id, "review_authority_id")
        _digest(self.review_evidence_digest, "review_evidence_digest")

    @property
    def target_digest(self) -> str:
        return canonical_digest(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "target_id": self.target_id,
            "review_authority_id": self.review_authority_id,
            "review_evidence_digest": self.review_evidence_digest,
        }


@dataclass(frozen=True, slots=True)
class ReviewedMotionCatalogV1:
    """Immutable allowlist of the only targets a language model may select."""

    targets: tuple[ReviewedMotionTargetV1, ...]
    catalog_id: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version, "ReviewedMotionCatalogV1 schema_version")
        _identifier(self.catalog_id, "catalog_id")
        if not isinstance(self.targets, tuple):
            raise GeneralizedMotionContractError("catalog targets must be an immutable tuple")
        if not 3 <= len(self.targets) <= 256:
            raise GeneralizedMotionContractError(
                "catalog must contain between 3 and 256 reviewed targets"
            )
        if any(not isinstance(target, ReviewedMotionTargetV1) for target in self.targets):
            raise GeneralizedMotionContractError(
                "catalog targets must contain ReviewedMotionTargetV1 records"
            )
        keys = tuple((target.kind, target.target_id) for target in self.targets)
        if keys != tuple(sorted(keys)):
            raise GeneralizedMotionContractError(
                "catalog targets must be sorted by (kind, target_id)"
            )
        if len(keys) != len(set(keys)):
            raise GeneralizedMotionContractError("catalog targets must be unique")
        kinds = {target.kind for target in self.targets}
        if kinds != set(TARGET_KINDS):
            raise GeneralizedMotionContractError(
                "catalog must contain at least one body, gait, and style target"
            )

    @property
    def catalog_digest(self) -> str:
        return canonical_digest(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "catalog_id": self.catalog_id,
            "targets": [target.as_dict() for target in self.targets],
        }

    def target(self, kind: TargetKind, target_id: str) -> ReviewedMotionTargetV1:
        if kind not in TARGET_KINDS:
            raise GeneralizedMotionContractError("unknown target kind")
        wanted = _identifier(target_id, f"{kind} target")
        for target in self.targets:
            if target.kind == kind and target.target_id == wanted:
                return target
        raise GeneralizedMotionContractError(
            f"{kind} target {wanted!r} is not in the reviewed catalog"
        )

    def ids_for(self, kind: TargetKind) -> tuple[str, ...]:
        if kind not in TARGET_KINDS:
            raise GeneralizedMotionContractError("unknown target kind")
        return tuple(target.target_id for target in self.targets if target.kind == kind)


@dataclass(frozen=True, slots=True)
class MotionStateV1:
    """The executive-owned categorical motion state; never motor state."""

    gait_target: str
    style_target: str
    body_target: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version, "MotionStateV1 schema_version")
        _identifier(self.gait_target, "gait_target")
        _identifier(self.style_target, "style_target")
        _identifier(self.body_target, "body_target")

    @property
    def state_digest(self) -> str:
        return canonical_digest(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "gait_target": self.gait_target,
            "style_target": self.style_target,
            "body_target": self.body_target,
        }

    def validate_against(self, catalog: ReviewedMotionCatalogV1) -> None:
        if not isinstance(catalog, ReviewedMotionCatalogV1):
            raise GeneralizedMotionContractError("catalog must be a ReviewedMotionCatalogV1 record")
        catalog.target("gait", self.gait_target)
        catalog.target("style", self.style_target)
        catalog.target("body", self.body_target)


@dataclass(frozen=True, slots=True)
class LanguageMotionSelectionV1:
    """The complete language-facing surface: exactly three reviewed names."""

    gait_target: str
    style_target: str
    body_target: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version, "LanguageMotionSelectionV1 schema_version")
        _identifier(self.gait_target, "gait_target")
        _identifier(self.style_target, "style_target")
        _identifier(self.body_target, "body_target")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LanguageMotionSelectionV1:
        """Parse an exact language response, rejecting motor/latent extensions."""

        data = _exact_mapping(
            value,
            frozenset({"schema_version", "gait_target", "style_target", "body_target"}),
            "LanguageMotionSelectionV1",
        )
        return cls(
            schema_version=_version(
                data["schema_version"], "LanguageMotionSelectionV1 schema_version"
            ),
            gait_target=_identifier(data["gait_target"], "gait_target"),
            style_target=_identifier(data["style_target"], "style_target"),
            body_target=_identifier(data["body_target"], "body_target"),
        )

    def as_state(self) -> MotionStateV1:
        return MotionStateV1(
            gait_target=self.gait_target,
            style_target=self.style_target,
            body_target=self.body_target,
        )


@dataclass(frozen=True, slots=True)
class MotionTransitionV1:
    """A single reviewed, directional categorical transition."""

    kind: TargetKind
    from_target: str
    to_target: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version, "MotionTransitionV1 schema_version")
        if self.kind not in TARGET_KINDS:
            raise GeneralizedMotionContractError(
                f"transition kind must be one of {list(TARGET_KINDS)}"
            )
        _identifier(self.from_target, "transition from_target")
        _identifier(self.to_target, "transition to_target")
        if self.from_target == self.to_target:
            raise GeneralizedMotionContractError(
                "self transitions are implicit and must not be listed"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "from_target": self.from_target,
            "to_target": self.to_target,
        }


@dataclass(frozen=True, slots=True)
class MotionTransitionGraphV1:
    """Explicit legal edges for gait, style, and body-target changes."""

    graph_id: str
    reviewed_catalog_digest: str
    review_evidence_digest: str
    transitions: tuple[MotionTransitionV1, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version, "MotionTransitionGraphV1 schema_version")
        _identifier(self.graph_id, "graph_id")
        _digest(self.reviewed_catalog_digest, "reviewed_catalog_digest")
        _digest(self.review_evidence_digest, "transition review_evidence_digest")
        if not isinstance(self.transitions, tuple):
            raise GeneralizedMotionContractError("transitions must be an immutable tuple")
        if len(self.transitions) > 4_096:
            raise GeneralizedMotionContractError("transition graph exceeds 4096 edges")
        if any(not isinstance(edge, MotionTransitionV1) for edge in self.transitions):
            raise GeneralizedMotionContractError(
                "transitions must contain MotionTransitionV1 records"
            )
        keys = tuple((edge.kind, edge.from_target, edge.to_target) for edge in self.transitions)
        if keys != tuple(sorted(keys)):
            raise GeneralizedMotionContractError(
                "transitions must be sorted by (kind, from_target, to_target)"
            )
        if len(keys) != len(set(keys)):
            raise GeneralizedMotionContractError("transition edges must be unique")

    @property
    def graph_digest(self) -> str:
        return canonical_digest(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "reviewed_catalog_digest": self.reviewed_catalog_digest,
            "review_evidence_digest": self.review_evidence_digest,
            "transitions": [edge.as_dict() for edge in self.transitions],
        }

    def validate_against(self, catalog: ReviewedMotionCatalogV1) -> None:
        if not isinstance(catalog, ReviewedMotionCatalogV1):
            raise GeneralizedMotionContractError("catalog must be a ReviewedMotionCatalogV1 record")
        if self.reviewed_catalog_digest != catalog.catalog_digest:
            raise GeneralizedMotionContractError(
                "transition graph is bound to a different reviewed catalog"
            )
        for edge in self.transitions:
            catalog.target(edge.kind, edge.from_target)
            catalog.target(edge.kind, edge.to_target)

    def allows(self, kind: TargetKind, from_target: str, to_target: str) -> bool:
        if kind not in TARGET_KINDS:
            raise GeneralizedMotionContractError("unknown target kind")
        source = _identifier(from_target, "transition source")
        target = _identifier(to_target, "transition target")
        if source == target:
            return True
        return any(
            edge.kind == kind and edge.from_target == source and edge.to_target == target
            for edge in self.transitions
        )

    def require_legal(self, current: MotionStateV1, target: MotionStateV1) -> None:
        pairs = (
            ("gait", current.gait_target, target.gait_target),
            ("style", current.style_target, target.style_target),
            ("body", current.body_target, target.body_target),
        )
        denied = [
            f"{kind}:{source}->{destination}"
            for kind, source, destination in pairs
            if not self.allows(kind, source, destination)  # type: ignore[arg-type]
        ]
        if denied:
            raise GeneralizedMotionContractError(
                f"motion transition is not reviewed: {', '.join(denied)}"
            )


@dataclass(frozen=True, slots=True)
class MotionIntentV1:
    """A content-bound simulator proposal; explicitly not a motor command."""

    source_turn_digest: str
    from_state: MotionStateV1
    target_state: MotionStateV1
    reviewed_catalog_digest: str
    transition_graph_digest: str
    gait_target_digest: str
    style_target_digest: str
    body_target_digest: str
    lifecycle: str = SIM_CANDIDATE
    execution_scope: str = SIMULATOR_ONLY
    physical_commissioned: bool = False
    authorizes_motion: bool = False
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version, "MotionIntentV1 schema_version")
        _digest(self.source_turn_digest, "source_turn_digest")
        if not isinstance(self.from_state, MotionStateV1):
            raise GeneralizedMotionContractError("from_state must be a MotionStateV1")
        if not isinstance(self.target_state, MotionStateV1):
            raise GeneralizedMotionContractError("target_state must be a MotionStateV1")
        for name in (
            "reviewed_catalog_digest",
            "transition_graph_digest",
            "gait_target_digest",
            "style_target_digest",
            "body_target_digest",
        ):
            _digest(getattr(self, name), name)
        if self.lifecycle != SIM_CANDIDATE:
            raise GeneralizedMotionContractError(
                f"MotionIntentV1 lifecycle must be {SIM_CANDIDATE!r}"
            )
        if self.execution_scope != SIMULATOR_ONLY:
            raise GeneralizedMotionContractError(
                f"MotionIntentV1 execution_scope must be {SIMULATOR_ONLY!r}"
            )
        _exact_false(self.physical_commissioned, "physical_commissioned")
        _exact_false(self.authorizes_motion, "authorizes_motion")

    @property
    def intent_digest(self) -> str:
        return canonical_digest(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_turn_digest": self.source_turn_digest,
            "from_state": self.from_state.as_dict(),
            "target_state": self.target_state.as_dict(),
            "reviewed_catalog_digest": self.reviewed_catalog_digest,
            "transition_graph_digest": self.transition_graph_digest,
            "gait_target_digest": self.gait_target_digest,
            "style_target_digest": self.style_target_digest,
            "body_target_digest": self.body_target_digest,
            "lifecycle": self.lifecycle,
            "execution_scope": self.execution_scope,
            "physical_commissioned": self.physical_commissioned,
            "authorizes_motion": self.authorizes_motion,
        }


def admit_language_selection(
    selection: LanguageMotionSelectionV1,
    *,
    current: MotionStateV1,
    catalog: ReviewedMotionCatalogV1,
    transition_graph: MotionTransitionGraphV1,
    source_turn_digest: str,
) -> MotionIntentV1:
    """Validate a language selection and return a non-authorizing sim intent."""

    if not isinstance(selection, LanguageMotionSelectionV1):
        raise GeneralizedMotionContractError("selection must be a LanguageMotionSelectionV1 record")
    if not isinstance(current, MotionStateV1):
        raise GeneralizedMotionContractError("current must be a MotionStateV1 record")
    if not isinstance(catalog, ReviewedMotionCatalogV1):
        raise GeneralizedMotionContractError("catalog must be a ReviewedMotionCatalogV1 record")
    if not isinstance(transition_graph, MotionTransitionGraphV1):
        raise GeneralizedMotionContractError(
            "transition_graph must be a MotionTransitionGraphV1 record"
        )
    source_digest = _digest(source_turn_digest, "source_turn_digest")
    transition_graph.validate_against(catalog)
    current.validate_against(catalog)
    target = selection.as_state()
    target.validate_against(catalog)
    transition_graph.require_legal(current, target)

    gait = catalog.target("gait", target.gait_target)
    style = catalog.target("style", target.style_target)
    body = catalog.target("body", target.body_target)
    return MotionIntentV1(
        source_turn_digest=source_digest,
        from_state=current,
        target_state=target,
        reviewed_catalog_digest=catalog.catalog_digest,
        transition_graph_digest=transition_graph.graph_digest,
        gait_target_digest=gait.target_digest,
        style_target_digest=style.target_digest,
        body_target_digest=body.target_digest,
    )


@dataclass(frozen=True, slots=True)
class ReviewedMotionActionSchemaV1:
    """Categorical policy output schema derived from a reviewed catalog.

    A policy may rank these categories.  There is deliberately no latent
    dimension, continuous action vector, joint target, or torque field.
    """

    reviewed_catalog_digest: str
    gait_targets: tuple[str, ...]
    style_targets: tuple[str, ...]
    body_targets: tuple[str, ...]
    encoding: str = REVIEWED_CATEGORICAL_ACTIONS
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version, "ReviewedMotionActionSchemaV1 schema_version")
        _digest(self.reviewed_catalog_digest, "reviewed_catalog_digest")
        for name in ("gait_targets", "style_targets", "body_targets"):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise GeneralizedMotionContractError(f"{name} must be an immutable tuple")
            if not values or len(values) > 256:
                raise GeneralizedMotionContractError(
                    f"{name} must contain between 1 and 256 targets"
                )
            for value in values:
                _identifier(value, f"{name} item")
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise GeneralizedMotionContractError(
                    f"{name} must be unique and canonically sorted"
                )
        if self.encoding != REVIEWED_CATEGORICAL_ACTIONS:
            raise GeneralizedMotionContractError(
                "action encoding must use reviewed categorical targets; latent vectors are refused"
            )

    @classmethod
    def from_catalog(cls, catalog: ReviewedMotionCatalogV1) -> ReviewedMotionActionSchemaV1:
        if not isinstance(catalog, ReviewedMotionCatalogV1):
            raise GeneralizedMotionContractError("catalog must be a ReviewedMotionCatalogV1 record")
        return cls(
            reviewed_catalog_digest=catalog.catalog_digest,
            gait_targets=catalog.ids_for("gait"),
            style_targets=catalog.ids_for("style"),
            body_targets=catalog.ids_for("body"),
        )

    @property
    def action_schema_digest(self) -> str:
        return canonical_digest(self.as_dict())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "reviewed_catalog_digest": self.reviewed_catalog_digest,
            "gait_targets": list(self.gait_targets),
            "style_targets": list(self.style_targets),
            "body_targets": list(self.body_targets),
            "encoding": self.encoding,
        }

    def validate_against(self, catalog: ReviewedMotionCatalogV1) -> None:
        expected = type(self).from_catalog(catalog)
        if self != expected:
            raise GeneralizedMotionContractError(
                "action schema does not exactly match the reviewed catalog"
            )


@dataclass(frozen=True, slots=True)
class MotionPolicyCandidateV1:
    """Digest-only policy identity for offline simulator evaluation.

    This record cannot load, execute, promote, commission, or dispatch the
    artifact.  Physical use requires a different, separately reviewed contract.
    """

    candidate_id: str
    policy_artifact_digest: str
    body_model_digest: str
    observation_schema_digest: str
    action_schema: ReviewedMotionActionSchemaV1
    transition_graph_digest: str
    controller_frequency_hz: float
    command_envelope_digest: str
    training_config_digest: str
    evaluation_manifest_digest: str
    evaluation_evidence_digest: str
    stop_contract_digest: str
    fallback_contract_digest: str
    termination_contract_digest: str
    lifecycle: str = SIM_CANDIDATE
    execution_scope: str = SIMULATOR_ONLY
    physical_commissioned: bool = False
    authorizes_motion: bool = False
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _version(self.schema_version, "MotionPolicyCandidateV1 schema_version")
        _identifier(self.candidate_id, "candidate_id")
        for name in (
            "policy_artifact_digest",
            "body_model_digest",
            "observation_schema_digest",
            "transition_graph_digest",
            "command_envelope_digest",
            "training_config_digest",
            "evaluation_manifest_digest",
            "evaluation_evidence_digest",
            "stop_contract_digest",
            "fallback_contract_digest",
            "termination_contract_digest",
        ):
            _digest(getattr(self, name), name)
        object.__setattr__(
            self,
            "controller_frequency_hz",
            _controller_frequency(self.controller_frequency_hz),
        )
        if not isinstance(self.action_schema, ReviewedMotionActionSchemaV1):
            raise GeneralizedMotionContractError(
                "action_schema must be a ReviewedMotionActionSchemaV1 record"
            )
        if self.lifecycle != SIM_CANDIDATE:
            raise GeneralizedMotionContractError(f"policy lifecycle must be {SIM_CANDIDATE!r}")
        if self.execution_scope != SIMULATOR_ONLY:
            raise GeneralizedMotionContractError(
                f"policy execution_scope must be {SIMULATOR_ONLY!r}"
            )
        _exact_false(self.physical_commissioned, "physical_commissioned")
        _exact_false(self.authorizes_motion, "authorizes_motion")

    @property
    def action_schema_digest(self) -> str:
        return self.action_schema.action_schema_digest

    @property
    def candidate_digest(self) -> str:
        return canonical_digest(self.as_dict())

    def binds_policy_artifact(self, artifact: bytes) -> bool:
        if not isinstance(artifact, bytes):
            raise GeneralizedMotionContractError("policy artifact must be bytes")
        return hashlib.sha256(artifact).hexdigest() == self.policy_artifact_digest

    def validate_against(
        self,
        *,
        catalog: ReviewedMotionCatalogV1,
        transition_graph: MotionTransitionGraphV1,
    ) -> None:
        """Check the candidate's categorical and transition bindings only.

        Passing this validation does not load, activate, or authorize the policy.
        """

        self.action_schema.validate_against(catalog)
        transition_graph.validate_against(catalog)
        if self.transition_graph_digest != transition_graph.graph_digest:
            raise GeneralizedMotionContractError(
                "policy candidate is bound to a different transition graph"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "policy_artifact_digest": self.policy_artifact_digest,
            "body_model_digest": self.body_model_digest,
            "observation_schema_digest": self.observation_schema_digest,
            "action_schema_digest": self.action_schema_digest,
            "reviewed_catalog_digest": self.action_schema.reviewed_catalog_digest,
            "transition_graph_digest": self.transition_graph_digest,
            "controller_frequency_hz": self.controller_frequency_hz,
            "command_envelope_digest": self.command_envelope_digest,
            "training_config_digest": self.training_config_digest,
            "evaluation_manifest_digest": self.evaluation_manifest_digest,
            "evaluation_evidence_digest": self.evaluation_evidence_digest,
            "stop_contract_digest": self.stop_contract_digest,
            "fallback_contract_digest": self.fallback_contract_digest,
            "termination_contract_digest": self.termination_contract_digest,
            "lifecycle": self.lifecycle,
            "execution_scope": self.execution_scope,
            "physical_commissioned": self.physical_commissioned,
            "authorizes_motion": self.authorizes_motion,
        }


def digest_bytes(value: bytes) -> str:
    """Hash an in-memory artifact without loading or executing it."""

    if not isinstance(value, bytes):
        raise GeneralizedMotionContractError("artifact must be bytes")
    return hashlib.sha256(value).hexdigest()


def digest_schema(value: Mapping[str, object] | Sequence[object]) -> str:
    """Content-bind a JSON-compatible observation or configuration schema."""

    if isinstance(value, (str, bytes)) or not isinstance(value, (Mapping, Sequence)):
        raise GeneralizedMotionContractError("schema must be a mapping or sequence")
    return canonical_digest(value)


__all__ = [
    "REVIEWED_CATEGORICAL_ACTIONS",
    "SCHEMA_VERSION",
    "SIMULATOR_ONLY",
    "SIM_CANDIDATE",
    "GeneralizedMotionContractError",
    "LanguageMotionSelectionV1",
    "MotionIntentV1",
    "MotionPolicyCandidateV1",
    "MotionStateV1",
    "MotionTransitionGraphV1",
    "MotionTransitionV1",
    "ReviewedMotionActionSchemaV1",
    "ReviewedMotionCatalogV1",
    "ReviewedMotionTargetV1",
    "admit_language_selection",
    "canonical_digest",
    "digest_bytes",
    "digest_schema",
]
