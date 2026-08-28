"""Deterministic failure mining that can only propose same-split training data."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .contracts import LearningContractError, boolean, canonical_digest, digest, identifier
from .registry import ScenarioRegistryV1, ScenarioV1


@dataclass(frozen=True, slots=True)
class FailureEpisodeV1:
    episode_id: str
    source_scenario_id: str
    failure_kind: str
    artifact_digest: str

    def __post_init__(self) -> None:
        identifier(self.episode_id, "episode_id")
        identifier(self.source_scenario_id, "source_scenario_id")
        identifier(self.failure_kind, "failure_kind")
        digest(self.artifact_digest, "artifact_digest")


@dataclass(frozen=True, slots=True)
class FailureMiningProposalV1:
    base_registry_digest: str
    proposed_registry: ScenarioRegistryV1
    added_scenario_ids: tuple[str, ...]
    authorizes_registry_write: bool = False

    def __post_init__(self) -> None:
        digest(self.base_registry_digest, "base_registry_digest")
        if not isinstance(self.added_scenario_ids, tuple):
            raise LearningContractError("added_scenario_ids must be an immutable tuple")
        if len(self.added_scenario_ids) > 1_000:
            raise LearningContractError("added_scenario_ids exceeds 1000 items")
        for scenario_id in self.added_scenario_ids:
            identifier(scenario_id, "added scenario_id")
        boolean(self.authorizes_registry_write, "authorizes_registry_write")
        if self.authorizes_registry_write:
            raise LearningContractError("failure mining never authorizes registry writes")


def propose_failure_cases(
    registry: ScenarioRegistryV1,
    episodes: tuple[FailureEpisodeV1, ...],
) -> FailureMiningProposalV1:
    """Return an immutable proposal; never mutate or persist the input registry."""

    if not isinstance(episodes, tuple):
        raise LearningContractError("failure episodes must be an immutable tuple")
    if not episodes:
        raise LearningContractError("at least one failure episode is required")
    if len(episodes) > 1_000:
        raise LearningContractError("failure mining exceeds 1000 episodes")
    episode_ids = tuple(item.episode_id for item in episodes)
    if len(set(episode_ids)) != len(episode_ids):
        raise LearningContractError("failure episode IDs must be unique")
    additions: list[ScenarioV1] = []
    existing_ids = {item.scenario_id for item in registry.scenarios}
    for episode in sorted(episodes, key=lambda item: item.episode_id):
        source = registry.scenario(episode.source_scenario_id)
        if source.split == "frozen_test":
            raise LearningContractError("frozen-test episodes cannot be failure-mined")
        suffix = canonical_digest(
            {
                "namespace": "failure-mined-scenario-v1",
                "registry_digest": registry.registry_digest,
                "episode_id": episode.episode_id,
                "source_scenario_id": source.scenario_id,
                "failure_kind": episode.failure_kind,
                "artifact_digest": episode.artifact_digest,
            }
        )[:24]
        scenario_id = f"mined-{suffix}"
        if scenario_id in existing_ids:
            raise LearningContractError("mined scenario collides with an existing scenario")
        existing_ids.add(scenario_id)
        additions.append(
            replace(
                source,
                scenario_id=scenario_id,
                artifact_digest=episode.artifact_digest,
                source_episode_ids=(episode.episode_id,),
            )
        )
    proposed = ScenarioRegistryV1(tuple(sorted((*registry.scenarios, *additions), key=lambda x: x.scenario_id)))
    return FailureMiningProposalV1(
        base_registry_digest=registry.registry_digest,
        proposed_registry=proposed,
        added_scenario_ids=tuple(item.scenario_id for item in additions),
    )
