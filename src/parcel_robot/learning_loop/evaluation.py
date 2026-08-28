"""Content-bound candidate evaluation records with exact safety accounting."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .contracts import (
    SCHEMA_VERSION,
    LearningContractError,
    as_mapping,
    canonical_digest,
    digest,
    exact,
    finite,
    identifier,
    integer,
    require_version,
    sequence,
    string_tuple,
)


@dataclass(frozen=True, slots=True)
class FamilyMetricsV1:
    family: str
    metrics: Mapping[str, float]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_version(self.schema_version, "FamilyMetricsV1")
        identifier(self.family, "family")
        if not isinstance(self.metrics, Mapping) or not self.metrics:
            raise LearningContractError("metrics must be a non-empty mapping")
        if len(self.metrics) > 128:
            raise LearningContractError("metrics exceeds 128 entries")
        frozen: dict[str, float] = {}
        for name, value in self.metrics.items():
            metric = identifier(name, "metric name")
            frozen[metric] = finite(value, f"metric {metric}")
        if len(frozen) != len(self.metrics):
            raise LearningContractError("metric names must be unique")
        object.__setattr__(self, "metrics", MappingProxyType(dict(sorted(frozen.items()))))

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "family": self.family,
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> FamilyMetricsV1:
        data = as_mapping(value, "FamilyMetricsV1")
        exact(data, {"schema_version", "family", "metrics"}, "FamilyMetricsV1")
        metrics = as_mapping(data["metrics"], "metrics")
        return cls(
            schema_version=require_version(data["schema_version"], "FamilyMetricsV1"),
            family=identifier(data["family"], "family"),
            metrics={identifier(key, "metric name"): finite(val, "metric") for key, val in metrics.items()},
        )


@dataclass(frozen=True, slots=True)
class SafetyCountersV1:
    critical_failure_names: tuple[str, ...]
    false_arrivals: int
    contacts: int
    authority_bypasses: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_version(self.schema_version, "SafetyCountersV1")
        normalized = string_tuple(self.critical_failure_names, "critical_failure_names")
        if normalized != self.critical_failure_names:
            raise LearningContractError("critical_failure_names must be sorted")
        integer(self.false_arrivals, "false_arrivals")
        integer(self.contacts, "contacts")
        integer(self.authority_bypasses, "authority_bypasses")

    @property
    def is_zero(self) -> bool:
        return not self.critical_failure_names and not any(
            (self.false_arrivals, self.contacts, self.authority_bypasses)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "critical_failure_names": list(self.critical_failure_names),
            "false_arrivals": self.false_arrivals,
            "contacts": self.contacts,
            "authority_bypasses": self.authority_bypasses,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SafetyCountersV1:
        data = as_mapping(value, "SafetyCountersV1")
        fields = {
            "schema_version", "critical_failure_names", "false_arrivals", "contacts",
            "authority_bypasses",
        }
        exact(data, fields, "SafetyCountersV1")
        return cls(
            schema_version=require_version(data["schema_version"], "SafetyCountersV1"),
            critical_failure_names=string_tuple(
                data["critical_failure_names"], "critical_failure_names"
            ),
            false_arrivals=integer(data["false_arrivals"], "false_arrivals"),
            contacts=integer(data["contacts"], "contacts"),
            authority_bypasses=integer(data["authority_bypasses"], "authority_bypasses"),
        )


@dataclass(frozen=True, slots=True)
class CandidateEvaluationV1:
    candidate_id: str
    candidate_digest: str
    model_digest: str
    config_digest: str
    registry_digest: str
    evaluator_digest: str
    reproducibility_digest: str
    family_metrics: tuple[FamilyMetricsV1, ...]
    safety: SafetyCountersV1
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_version(self.schema_version, "CandidateEvaluationV1")
        identifier(self.candidate_id, "candidate_id")
        for field_name in (
            "candidate_digest", "model_digest", "config_digest", "registry_digest",
            "evaluator_digest", "reproducibility_digest",
        ):
            digest(getattr(self, field_name), field_name)
        if not isinstance(self.family_metrics, tuple):
            raise LearningContractError("family_metrics must be an immutable tuple")
        if not self.family_metrics:
            raise LearningContractError("family_metrics cannot be empty")
        if len(self.family_metrics) > 256:
            raise LearningContractError("family_metrics exceeds 256 families")
        if any(not isinstance(item, FamilyMetricsV1) for item in self.family_metrics):
            raise LearningContractError("family_metrics must contain FamilyMetricsV1 records")
        if not isinstance(self.safety, SafetyCountersV1):
            raise LearningContractError("safety must be a SafetyCountersV1 record")
        families = tuple(item.family for item in self.family_metrics)
        if len(set(families)) != len(families):
            raise LearningContractError("family_metrics families must be unique")
        if families != tuple(sorted(families)):
            raise LearningContractError("family_metrics must be sorted by family")

    def metric(self, family: str, metric: str) -> float | None:
        for result in self.family_metrics:
            if result.family == family:
                return result.metrics.get(metric)
        return None

    def as_dict(self) -> dict[str, object]:
        return {**self._body(), "evaluation_digest": self.evaluation_digest}

    @property
    def evaluation_digest(self) -> str:
        return canonical_digest(self._body())

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "model_digest": self.model_digest,
            "config_digest": self.config_digest,
            "registry_digest": self.registry_digest,
            "evaluator_digest": self.evaluator_digest,
            "reproducibility_digest": self.reproducibility_digest,
            "family_metrics": [item.as_dict() for item in self.family_metrics],
            "safety": self.safety.as_dict(),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CandidateEvaluationV1:
        data = as_mapping(value, "CandidateEvaluationV1")
        fields = {
            "schema_version", "candidate_id", "candidate_digest", "model_digest",
            "config_digest", "registry_digest", "evaluator_digest",
            "reproducibility_digest", "family_metrics", "safety",
            "evaluation_digest",
        }
        exact(data, fields, "CandidateEvaluationV1")
        metrics = sequence(data["family_metrics"], "family_metrics", maximum=256)
        evaluation = cls(
            schema_version=require_version(data["schema_version"], "CandidateEvaluationV1"),
            candidate_id=identifier(data["candidate_id"], "candidate_id"),
            candidate_digest=digest(data["candidate_digest"], "candidate_digest"),
            model_digest=digest(data["model_digest"], "model_digest"),
            config_digest=digest(data["config_digest"], "config_digest"),
            registry_digest=digest(data["registry_digest"], "registry_digest"),
            evaluator_digest=digest(data["evaluator_digest"], "evaluator_digest"),
            reproducibility_digest=digest(
                data["reproducibility_digest"], "reproducibility_digest"
            ),
            family_metrics=tuple(
                FamilyMetricsV1.from_mapping(as_mapping(item, "family metric"))
                for item in metrics
            ),
            safety=SafetyCountersV1.from_mapping(as_mapping(data["safety"], "safety")),
        )
        supplied = digest(data["evaluation_digest"], "evaluation_digest")
        if supplied != evaluation.evaluation_digest:
            raise LearningContractError("evaluation_digest does not match canonical evaluation")
        return evaluation
