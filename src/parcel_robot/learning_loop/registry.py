"""Immutable, content-bound scenario and split registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .contracts import (
    SCHEMA_VERSION,
    SPLITS,
    LearningContractError,
    as_mapping,
    canonical_digest,
    digest,
    exact,
    identifier,
    require_version,
    sequence,
    string_tuple,
)


@dataclass(frozen=True, slots=True)
class ScenarioV1:
    scenario_id: str
    split: str
    leakage_group_id: str
    family: str
    artifact_digest: str
    config_digest: str
    code_digest: str
    calibration_digest: str
    evaluator_digest: str
    source_episode_ids: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_version(self.schema_version, "ScenarioV1")
        identifier(self.scenario_id, "scenario_id")
        if self.split not in SPLITS:
            raise LearningContractError(f"split must be one of {sorted(SPLITS)}")
        identifier(self.leakage_group_id, "leakage_group_id")
        identifier(self.family, "family")
        for field_name in (
            "artifact_digest",
            "config_digest",
            "code_digest",
            "calibration_digest",
            "evaluator_digest",
        ):
            digest(getattr(self, field_name), field_name)
        normalized = string_tuple(self.source_episode_ids, "source_episode_ids")
        if normalized != self.source_episode_ids:
            raise LearningContractError("source_episode_ids must be sorted canonically")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scenario_id": self.scenario_id,
            "split": self.split,
            "leakage_group_id": self.leakage_group_id,
            "family": self.family,
            "artifact_digest": self.artifact_digest,
            "config_digest": self.config_digest,
            "code_digest": self.code_digest,
            "calibration_digest": self.calibration_digest,
            "evaluator_digest": self.evaluator_digest,
            "source_episode_ids": list(self.source_episode_ids),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ScenarioV1:
        data = as_mapping(value, "ScenarioV1")
        fields = {
            "schema_version", "scenario_id", "split", "leakage_group_id", "family",
            "artifact_digest", "config_digest", "code_digest", "calibration_digest",
            "evaluator_digest", "source_episode_ids",
        }
        exact(data, fields, "ScenarioV1")
        return cls(
            schema_version=require_version(data["schema_version"], "ScenarioV1"),
            scenario_id=identifier(data["scenario_id"], "scenario_id"),
            split=identifier(data["split"], "split"),
            leakage_group_id=identifier(data["leakage_group_id"], "leakage_group_id"),
            family=identifier(data["family"], "family"),
            artifact_digest=digest(data["artifact_digest"], "artifact_digest"),
            config_digest=digest(data["config_digest"], "config_digest"),
            code_digest=digest(data["code_digest"], "code_digest"),
            calibration_digest=digest(data["calibration_digest"], "calibration_digest"),
            evaluator_digest=digest(data["evaluator_digest"], "evaluator_digest"),
            source_episode_ids=string_tuple(data["source_episode_ids"], "source_episode_ids"),
        )


@dataclass(frozen=True, slots=True)
class ScenarioRegistryV1:
    scenarios: tuple[ScenarioV1, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_version(self.schema_version, "ScenarioRegistryV1")
        if not isinstance(self.scenarios, tuple):
            raise LearningContractError("scenarios must be an immutable tuple")
        if not self.scenarios:
            raise LearningContractError("scenario registry cannot be empty")
        if len(self.scenarios) > 10_000:
            raise LearningContractError("scenario registry exceeds 10000 scenarios")
        if any(not isinstance(item, ScenarioV1) for item in self.scenarios):
            raise LearningContractError("scenarios must contain only ScenarioV1 records")
        ids = tuple(item.scenario_id for item in self.scenarios)
        if len(set(ids)) != len(ids):
            raise LearningContractError("scenario_id values must be unique")
        if ids != tuple(sorted(ids)):
            raise LearningContractError("scenarios must be sorted by scenario_id")
        split_by_group: dict[str, str] = {}
        split_by_artifact: dict[str, str] = {}
        assignment_by_episode: dict[str, tuple[str, str]] = {}
        for item in self.scenarios:
            prior = split_by_group.setdefault(item.leakage_group_id, item.split)
            if prior != item.split:
                raise LearningContractError(
                    f"leakage group {item.leakage_group_id!r} crosses splits"
                )
            artifact_split = split_by_artifact.setdefault(item.artifact_digest, item.split)
            if artifact_split != item.split:
                raise LearningContractError(
                    f"artifact {item.artifact_digest!r} crosses splits"
                )
            assignment = (item.split, item.leakage_group_id)
            for episode_id in item.source_episode_ids:
                prior_assignment = assignment_by_episode.setdefault(episode_id, assignment)
                if prior_assignment != assignment:
                    raise LearningContractError(
                        f"source episode {episode_id!r} crosses split or leakage group"
                    )
        represented = {item.split for item in self.scenarios}
        if represented != SPLITS:
            raise LearningContractError("registry must contain train, dev, and frozen_test splits")

    @property
    def registry_digest(self) -> str:
        return canonical_digest(self._body())

    @property
    def frozen_test_digest(self) -> str:
        frozen = [item.as_dict() for item in self.scenarios if item.split == "frozen_test"]
        return canonical_digest({"schema_version": self.schema_version, "frozen_test": frozen})

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scenarios": [item.as_dict() for item in self.scenarios],
        }

    def as_dict(self) -> dict[str, object]:
        return {**self._body(), "registry_digest": self.registry_digest}

    def scenario(self, scenario_id: str) -> ScenarioV1:
        wanted = identifier(scenario_id, "scenario_id")
        for item in self.scenarios:
            if item.scenario_id == wanted:
                return item
        raise LearningContractError(f"unknown scenario_id: {wanted}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ScenarioRegistryV1:
        data = as_mapping(value, "ScenarioRegistryV1")
        exact(data, {"schema_version", "scenarios", "registry_digest"}, "ScenarioRegistryV1")
        raw = sequence(data["scenarios"], "scenarios")
        registry = cls(
            scenarios=tuple(ScenarioV1.from_mapping(as_mapping(item, "scenario")) for item in raw),
            schema_version=require_version(data["schema_version"], "ScenarioRegistryV1"),
        )
        supplied = digest(data["registry_digest"], "registry_digest")
        if supplied != registry.registry_digest:
            raise LearningContractError("registry_digest does not match canonical registry")
        return registry
