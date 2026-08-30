"""Deterministic, proposal-only learning of contextual skill reliability.

The learning plane may summarize immutable simulator outcomes, but it does not
write a scenario registry, mutate a running planner, or activate a candidate.
Context is an ordered hierarchy from broad to specific.  For example,
``("indoor", "stairs", "wet")`` can back off to ``("indoor", "stairs")``,
then ``("indoor",)``, then the global ``()`` node when a more specific node
does not meet the configured support floor.

Only train/dev scenarios may contribute to a proposal.  Frozen-test outcomes
are deliberately rejected instead of silently ignored.  A supported table
entry can be converted to the affordance planner's ``SkillReliabilityV1``;
an unsupported lookup returns ``None`` and therefore remains unknown.  Safety
failures are never hidden by the support floor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .contracts import (
    SCHEMA_VERSION,
    SPLITS,
    LearningContractError,
    as_mapping,
    boolean,
    canonical_digest,
    digest,
    exact,
    identifier,
    integer,
    require_version,
    sequence,
)
from .registry import ScenarioRegistryV1

if TYPE_CHECKING:
    from parcel_robot.brain.affordance_planner import SkillReliabilityV1


SKILL_OUTCOMES = frozenset({"succeeded", "failed", "safety_failure"})
LEARNING_SPLITS = frozenset({"train", "dev"})
MAX_CONTEXT_DEPTH = 16
MAX_TRANSITIONS = 100_000


def _context_path(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise LearningContractError(f"{name} must be an immutable tuple")
    if len(value) > MAX_CONTEXT_DEPTH:
        raise LearningContractError(f"{name} exceeds {MAX_CONTEXT_DEPTH} levels")
    result = tuple(identifier(item, f"{name} item") for item in value)
    if len(set(result)) != len(result):
        raise LearningContractError(f"{name} cannot repeat a hierarchy level")
    return result


@dataclass(frozen=True, slots=True)
class SkillTransitionV1:
    """One content-bound terminal outcome from an offline scenario."""

    transition_id: str
    scenario_id: str
    source_split: str
    reliability_key: str
    context_path: tuple[str, ...]
    outcome: str
    evidence_digest: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_version(self.schema_version, "SkillTransitionV1")
        identifier(self.transition_id, "transition_id")
        identifier(self.scenario_id, "scenario_id")
        split = identifier(self.source_split, "source_split")
        if split not in SPLITS:
            raise LearningContractError(f"source_split must be one of {sorted(SPLITS)}")
        identifier(self.reliability_key, "reliability_key")
        _context_path(self.context_path, "context_path")
        if self.outcome not in SKILL_OUTCOMES:
            raise LearningContractError(f"outcome must be one of {sorted(SKILL_OUTCOMES)}")
        digest(self.evidence_digest, "evidence_digest")

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "transition_id": self.transition_id,
            "scenario_id": self.scenario_id,
            "source_split": self.source_split,
            "reliability_key": self.reliability_key,
            "context_path": list(self.context_path),
            "outcome": self.outcome,
            "evidence_digest": self.evidence_digest,
        }

    @property
    def transition_digest(self) -> str:
        return canonical_digest({"namespace": "skill-transition-v1", "transition": self._body()})

    def as_dict(self) -> dict[str, object]:
        return {**self._body(), "transition_digest": self.transition_digest}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SkillTransitionV1:
        data = as_mapping(value, "SkillTransitionV1")
        exact(
            data,
            {
                "schema_version",
                "transition_id",
                "scenario_id",
                "source_split",
                "reliability_key",
                "context_path",
                "outcome",
                "evidence_digest",
                "transition_digest",
            },
            "SkillTransitionV1",
        )
        raw_context = sequence(data["context_path"], "context_path", maximum=MAX_CONTEXT_DEPTH)
        transition = cls(
            schema_version=require_version(data["schema_version"], "SkillTransitionV1"),
            transition_id=identifier(data["transition_id"], "transition_id"),
            scenario_id=identifier(data["scenario_id"], "scenario_id"),
            source_split=identifier(data["source_split"], "source_split"),
            reliability_key=identifier(data["reliability_key"], "reliability_key"),
            context_path=tuple(identifier(item, "context_path item") for item in raw_context),
            outcome=identifier(data["outcome"], "outcome"),
            evidence_digest=digest(data["evidence_digest"], "evidence_digest"),
        )
        supplied = digest(data["transition_digest"], "transition_digest")
        if supplied != transition.transition_digest:
            raise LearningContractError("transition_digest does not match canonical transition")
        return transition


@dataclass(frozen=True, slots=True)
class SkillContextReliabilityV1:
    """One known node in a proposed contextual reliability hierarchy."""

    reliability_key: str
    context_path: tuple[str, ...]
    successes: int
    failures: int
    safety_failures: int = 0
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_version(self.schema_version, "SkillContextReliabilityV1")
        identifier(self.reliability_key, "reliability_key")
        _context_path(self.context_path, "context_path")
        successes = integer(self.successes, "successes", maximum=MAX_TRANSITIONS)
        failures = integer(self.failures, "failures", maximum=MAX_TRANSITIONS)
        safety = integer(
            self.safety_failures,
            "safety_failures",
            maximum=MAX_TRANSITIONS,
        )
        if successes + failures == 0:
            raise LearningContractError("a reliability entry must have positive support")
        if safety > failures:
            raise LearningContractError("safety_failures cannot exceed failures")

    @property
    def support(self) -> int:
        return self.successes + self.failures

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "reliability_key": self.reliability_key,
            "context_path": list(self.context_path),
            "successes": self.successes,
            "failures": self.failures,
            "safety_failures": self.safety_failures,
        }

    @property
    def entry_digest(self) -> str:
        return canonical_digest(
            {"namespace": "skill-context-reliability-v1", "entry": self._body()}
        )

    def as_dict(self) -> dict[str, object]:
        return {**self._body(), "entry_digest": self.entry_digest}

    def as_planner_reliability(self) -> SkillReliabilityV1:
        """Return the exact immutable estimate consumed by AffordancePlannerV1."""

        from parcel_robot.brain.affordance_planner import SkillReliabilityV1

        return SkillReliabilityV1(
            reliability_key=self.reliability_key,
            successes=self.successes,
            failures=self.failures,
            safety_failures=self.safety_failures,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SkillContextReliabilityV1:
        data = as_mapping(value, "SkillContextReliabilityV1")
        exact(
            data,
            {
                "schema_version",
                "reliability_key",
                "context_path",
                "successes",
                "failures",
                "safety_failures",
                "entry_digest",
            },
            "SkillContextReliabilityV1",
        )
        raw_context = sequence(data["context_path"], "context_path", maximum=MAX_CONTEXT_DEPTH)
        entry = cls(
            schema_version=require_version(data["schema_version"], "SkillContextReliabilityV1"),
            reliability_key=identifier(data["reliability_key"], "reliability_key"),
            context_path=tuple(identifier(item, "context_path item") for item in raw_context),
            successes=integer(data["successes"], "successes", maximum=MAX_TRANSITIONS),
            failures=integer(data["failures"], "failures", maximum=MAX_TRANSITIONS),
            safety_failures=integer(
                data["safety_failures"],
                "safety_failures",
                maximum=MAX_TRANSITIONS,
            ),
        )
        supplied = digest(data["entry_digest"], "entry_digest")
        if supplied != entry.entry_digest:
            raise LearningContractError("entry_digest does not match canonical entry")
        return entry


@dataclass(frozen=True, slots=True)
class SkillReliabilityTableProposalV1:
    """Auditable reliability proposal with no write, motion, or activation power."""

    source_registry_digest: str
    minimum_support: int
    train_transition_count: int
    dev_transition_count: int
    source_transition_digests: tuple[str, ...]
    entries: tuple[SkillContextReliabilityV1, ...]
    authorizes_registry_write: bool = False
    authorizes_runtime_write: bool = False
    authorizes_activation: bool = False
    authorizes_motion: bool = False
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_version(self.schema_version, "SkillReliabilityTableProposalV1")
        digest(self.source_registry_digest, "source_registry_digest")
        minimum = integer(
            self.minimum_support,
            "minimum_support",
            maximum=MAX_TRANSITIONS,
        )
        if minimum < 1:
            raise LearningContractError("minimum_support must be at least 1")
        train_count = integer(
            self.train_transition_count,
            "train_transition_count",
            maximum=MAX_TRANSITIONS,
        )
        dev_count = integer(
            self.dev_transition_count,
            "dev_transition_count",
            maximum=MAX_TRANSITIONS,
        )
        if not isinstance(self.source_transition_digests, tuple):
            raise LearningContractError("source_transition_digests must be an immutable tuple")
        if not self.source_transition_digests:
            raise LearningContractError("a reliability proposal requires source transitions")
        if len(self.source_transition_digests) > MAX_TRANSITIONS:
            raise LearningContractError(
                f"source_transition_digests exceeds {MAX_TRANSITIONS} items"
            )
        for item in self.source_transition_digests:
            digest(item, "source transition digest")
        if self.source_transition_digests != tuple(sorted(set(self.source_transition_digests))):
            raise LearningContractError("source_transition_digests must be unique and sorted")
        if train_count + dev_count != len(self.source_transition_digests):
            raise LearningContractError(
                "train/dev transition counts must cover every source transition"
            )
        if not isinstance(self.entries, tuple):
            raise LearningContractError("entries must be an immutable tuple")
        if len(self.entries) > MAX_TRANSITIONS * (MAX_CONTEXT_DEPTH + 1):
            raise LearningContractError("entries exceeds the bounded hierarchy size")
        if any(not isinstance(item, SkillContextReliabilityV1) for item in self.entries):
            raise LearningContractError("entries must contain SkillContextReliabilityV1 records")
        entry_keys = tuple((item.reliability_key, item.context_path) for item in self.entries)
        if entry_keys != tuple(sorted(set(entry_keys))):
            raise LearningContractError("entries must be unique and sorted canonically")
        for item in self.entries:
            if item.support < minimum and item.safety_failures == 0:
                raise LearningContractError(
                    "an entry below minimum_support must contain safety evidence"
                )
        for field_name in (
            "authorizes_registry_write",
            "authorizes_runtime_write",
            "authorizes_activation",
            "authorizes_motion",
        ):
            allowed = boolean(getattr(self, field_name), field_name)
            if allowed:
                raise LearningContractError(
                    "a skill reliability proposal cannot grant write, activation, or motion authority"
                )

    @property
    def transition_set_digest(self) -> str:
        return canonical_digest(
            {
                "namespace": "skill-transition-set-v1",
                "transition_digests": list(self.source_transition_digests),
            }
        )

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_registry_digest": self.source_registry_digest,
            "minimum_support": self.minimum_support,
            "train_transition_count": self.train_transition_count,
            "dev_transition_count": self.dev_transition_count,
            "source_transition_digests": list(self.source_transition_digests),
            "transition_set_digest": self.transition_set_digest,
            "entries": [item.as_dict() for item in self.entries],
            "authorizes_registry_write": self.authorizes_registry_write,
            "authorizes_runtime_write": self.authorizes_runtime_write,
            "authorizes_activation": self.authorizes_activation,
            "authorizes_motion": self.authorizes_motion,
        }

    @property
    def proposal_digest(self) -> str:
        return canonical_digest(
            {"namespace": "skill-reliability-table-proposal-v1", "proposal": self._body()}
        )

    def as_dict(self) -> dict[str, object]:
        return {**self._body(), "proposal_digest": self.proposal_digest}

    def resolve_entry(
        self,
        reliability_key: str,
        context_path: tuple[str, ...],
    ) -> SkillContextReliabilityV1 | None:
        """Resolve most-specific supported evidence, otherwise return unknown."""

        wanted = identifier(reliability_key, "reliability_key")
        context = _context_path(context_path, "context_path")
        by_key = {
            item.context_path: item for item in self.entries if item.reliability_key == wanted
        }
        for depth in range(len(context), -1, -1):
            selected = by_key.get(context[:depth])
            if selected is not None:
                return selected
        return None

    def resolve(
        self,
        reliability_key: str,
        context_path: tuple[str, ...],
    ) -> SkillReliabilityV1 | None:
        """Resolve directly to the affordance planner contract, or ``None``."""

        entry = self.resolve_entry(reliability_key, context_path)
        return None if entry is None else entry.as_planner_reliability()

    def planner_reliability(
        self,
        reliability_keys: tuple[str, ...],
        context_path: tuple[str, ...],
    ) -> tuple[SkillReliabilityV1, ...]:
        """Return sorted, known estimates suitable for ``PlanningProblemV1``."""

        if not isinstance(reliability_keys, tuple):
            raise LearningContractError("reliability_keys must be an immutable tuple")
        normalized = tuple(identifier(item, "reliability key") for item in reliability_keys)
        if len(set(normalized)) != len(normalized):
            raise LearningContractError("reliability_keys must be unique")
        estimates = [
            estimate
            for key in sorted(normalized)
            if (estimate := self.resolve(key, context_path)) is not None
        ]
        return tuple(estimates)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SkillReliabilityTableProposalV1:
        data = as_mapping(value, "SkillReliabilityTableProposalV1")
        exact(
            data,
            {
                "schema_version",
                "source_registry_digest",
                "minimum_support",
                "train_transition_count",
                "dev_transition_count",
                "source_transition_digests",
                "transition_set_digest",
                "entries",
                "authorizes_registry_write",
                "authorizes_runtime_write",
                "authorizes_activation",
                "authorizes_motion",
                "proposal_digest",
            },
            "SkillReliabilityTableProposalV1",
        )
        raw_digests = sequence(
            data["source_transition_digests"],
            "source_transition_digests",
            maximum=MAX_TRANSITIONS,
        )
        raw_entries = sequence(
            data["entries"],
            "entries",
            maximum=MAX_TRANSITIONS * (MAX_CONTEXT_DEPTH + 1),
        )
        proposal = cls(
            schema_version=require_version(
                data["schema_version"], "SkillReliabilityTableProposalV1"
            ),
            source_registry_digest=digest(data["source_registry_digest"], "source_registry_digest"),
            minimum_support=integer(
                data["minimum_support"],
                "minimum_support",
                maximum=MAX_TRANSITIONS,
            ),
            train_transition_count=integer(
                data["train_transition_count"],
                "train_transition_count",
                maximum=MAX_TRANSITIONS,
            ),
            dev_transition_count=integer(
                data["dev_transition_count"],
                "dev_transition_count",
                maximum=MAX_TRANSITIONS,
            ),
            source_transition_digests=tuple(
                digest(item, "source transition digest") for item in raw_digests
            ),
            entries=tuple(
                SkillContextReliabilityV1.from_mapping(as_mapping(item, "entry"))
                for item in raw_entries
            ),
            authorizes_registry_write=boolean(
                data["authorizes_registry_write"], "authorizes_registry_write"
            ),
            authorizes_runtime_write=boolean(
                data["authorizes_runtime_write"], "authorizes_runtime_write"
            ),
            authorizes_activation=boolean(data["authorizes_activation"], "authorizes_activation"),
            authorizes_motion=boolean(data["authorizes_motion"], "authorizes_motion"),
        )
        supplied_set = digest(data["transition_set_digest"], "transition_set_digest")
        if supplied_set != proposal.transition_set_digest:
            raise LearningContractError("transition_set_digest does not match source transitions")
        supplied_proposal = digest(data["proposal_digest"], "proposal_digest")
        if supplied_proposal != proposal.proposal_digest:
            raise LearningContractError("proposal_digest does not match canonical proposal")
        return proposal


def propose_skill_reliability_table(
    registry: ScenarioRegistryV1,
    transitions: tuple[SkillTransitionV1, ...],
    *,
    minimum_support: int,
) -> SkillReliabilityTableProposalV1:
    """Aggregate train/dev outcomes into a deterministic hierarchy proposal."""

    if not isinstance(registry, ScenarioRegistryV1):
        raise LearningContractError("registry must be a ScenarioRegistryV1 record")
    if not isinstance(transitions, tuple):
        raise LearningContractError("transitions must be an immutable tuple")
    if not transitions:
        raise LearningContractError("at least one skill transition is required")
    if len(transitions) > MAX_TRANSITIONS:
        raise LearningContractError(f"transitions exceeds {MAX_TRANSITIONS} items")
    if any(not isinstance(item, SkillTransitionV1) for item in transitions):
        raise LearningContractError("transitions must contain SkillTransitionV1 records")
    support_floor = integer(
        minimum_support,
        "minimum_support",
        maximum=MAX_TRANSITIONS,
    )
    if support_floor < 1:
        raise LearningContractError("minimum_support must be at least 1")

    transition_ids = tuple(item.transition_id for item in transitions)
    if len(set(transition_ids)) != len(transition_ids):
        raise LearningContractError("transition_id values must be unique")
    evidence_digests = tuple(item.evidence_digest for item in transitions)
    if len(set(evidence_digests)) != len(evidence_digests):
        raise LearningContractError("evidence_digest values must be unique")

    # Values are [successes, failures, safety_failures].  Integer addition is
    # order-independent; sorted input and output still make the procedure and
    # serialized proposal deterministic across callers.
    counts: dict[tuple[str, tuple[str, ...]], list[int]] = {}
    split_counts = {"train": 0, "dev": 0}
    ordered = tuple(sorted(transitions, key=lambda item: item.transition_digest))
    for transition in ordered:
        scenario = registry.scenario(transition.scenario_id)
        if scenario.split != transition.source_split:
            raise LearningContractError(
                "transition source_split does not match the scenario registry"
            )
        if scenario.split not in LEARNING_SPLITS:
            raise LearningContractError(
                "frozen-test transitions cannot contribute to skill reliability"
            )
        split_counts[scenario.split] += 1
        for depth in range(len(transition.context_path) + 1):
            key = (transition.reliability_key, transition.context_path[:depth])
            bucket = counts.setdefault(key, [0, 0, 0])
            if transition.outcome == "succeeded":
                bucket[0] += 1
            else:
                bucket[1] += 1
                if transition.outcome == "safety_failure":
                    bucket[2] += 1

    entries: list[SkillContextReliabilityV1] = []
    for (reliability_key, context_path), values in sorted(counts.items()):
        successes, failures, safety_failures = values
        if successes + failures < support_floor and safety_failures == 0:
            continue
        entries.append(
            SkillContextReliabilityV1(
                reliability_key=reliability_key,
                context_path=context_path,
                successes=successes,
                failures=failures,
                safety_failures=safety_failures,
            )
        )

    return SkillReliabilityTableProposalV1(
        source_registry_digest=registry.registry_digest,
        minimum_support=support_floor,
        train_transition_count=split_counts["train"],
        dev_transition_count=split_counts["dev"],
        source_transition_digests=tuple(sorted(item.transition_digest for item in transitions)),
        entries=tuple(entries),
    )


__all__ = [
    "LEARNING_SPLITS",
    "MAX_CONTEXT_DEPTH",
    "SKILL_OUTCOMES",
    "SkillContextReliabilityV1",
    "SkillReliabilityTableProposalV1",
    "SkillTransitionV1",
    "propose_skill_reliability_table",
]
