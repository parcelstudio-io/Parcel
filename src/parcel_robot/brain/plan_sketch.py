"""Compact model-owned semantics that compile into trusted :class:`PlanIR`."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from .contracts import FrozenDict, GoalSpec, GoalTarget

PLAN_SKETCH_SCHEMA_VERSION = 1
PLAN_SKETCH_OUTPUT_CONTRACT = "plan_sketch_v1"
_SKILL_NAME = re.compile(r"^[A-Z][A-Za-z0-9]{0,63}$")


@dataclass(frozen=True, slots=True)
class PlanSketchGoal:
    """The terminal semantic outcome selected by the planner model."""

    relation: str
    kind: str
    query: str

    def __post_init__(self) -> None:
        # Reuse PlanIR's bounded semantic vocabulary without exposing its
        # system-owned tolerance field at the model boundary.
        GoalSpec(self.relation, GoalTarget(self.kind, self.query), tolerance_m=0.0)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PlanSketchGoal:
        data = _mapping(value, "PlanSketch goal")
        _exact_fields(data, {"relation", "kind", "query"}, "PlanSketch goal")
        return cls(
            relation=_string(data["relation"], "goal relation", maximum=32),
            kind=_string(data["kind"], "goal kind", maximum=40),
            query=_string(data["query"], "goal query", maximum=160, allow_empty=True),
        )

    def as_goal_spec(self) -> GoalSpec:
        return GoalSpec(
            relation=self.relation,
            target=GoalTarget(kind=self.kind, query=self.query),
            tolerance_m=0.0,
        )

    def as_dict(self) -> dict[str, object]:
        return {"relation": self.relation, "kind": self.kind, "query": self.query}


@dataclass(frozen=True, slots=True)
class NavigationGrounding:
    """Explicit model-authored grounding for exactly one NavigateTo step."""

    relation: str
    target: str

    def __post_init__(self) -> None:
        if self.relation not in {"inside", "near"}:
            raise ValueError("navigation relation must be 'inside' or 'near'")
        if (
            not isinstance(self.target, str)
            or not self.target
            or len(self.target) > 160
            or self.target != self.target.strip()
            or ":" in self.target
        ):
            raise ValueError("navigation target must be a bounded, trimmed human label without ':'")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> NavigationGrounding:
        data = _mapping(value, "navigation grounding")
        _exact_fields(data, {"relation", "target"}, "navigation grounding")
        return cls(
            relation=_string(data["relation"], "navigation relation", maximum=16),
            target=_string(data["target"], "navigation target", maximum=160),
        )

    def as_dict(self) -> dict[str, object]:
        return {"relation": self.relation, "target": self.target}


@dataclass(frozen=True, slots=True)
class PlanSketchStep:
    """One ordered semantic skill plus only its model-owned arguments."""

    skill: str
    arguments: FrozenDict
    navigation: NavigationGrounding | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.skill, str) or not _SKILL_NAME.fullmatch(self.skill):
            raise ValueError("PlanSketch skill must be a bounded PascalCase identifier")
        if not isinstance(self.arguments, FrozenDict):
            object.__setattr__(self, "arguments", FrozenDict(self.arguments))
        if self.skill == "NavigateTo":
            if not isinstance(self.navigation, NavigationGrounding):
                raise ValueError("NavigateTo requires explicit navigation grounding")
        elif self.navigation is not None:
            raise ValueError("only NavigateTo may include navigation grounding")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PlanSketchStep:
        data = _mapping(value, "PlanSketch step")
        _exact_fields(
            data,
            {"skill", "arguments", "navigation"},
            "PlanSketch step",
        )
        raw_navigation = data["navigation"]
        navigation = (
            None
            if raw_navigation is None
            else NavigationGrounding.from_mapping(_mapping(raw_navigation, "navigation grounding"))
        )
        return cls(
            skill=_string(data["skill"], "PlanSketch skill", maximum=64),
            arguments=FrozenDict(_mapping(data["arguments"], "PlanSketch arguments")),
            navigation=navigation,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "skill": self.skill,
            "arguments": self.arguments.to_dict(),
            "navigation": self.navigation.as_dict() if self.navigation is not None else None,
        }


@dataclass(frozen=True, slots=True)
class PlanSketch:
    """Versioned compact planner output with no model-authored provenance."""

    schema_version: int
    goal: PlanSketchGoal
    steps: tuple[PlanSketchStep, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or self.schema_version != PLAN_SKETCH_SCHEMA_VERSION
        ):
            raise ValueError("PlanSketch schema_version must equal 1")
        if not isinstance(self.goal, PlanSketchGoal):
            raise TypeError("PlanSketch goal must be PlanSketchGoal")
        if not isinstance(self.steps, tuple):
            raise TypeError("PlanSketch steps must be a tuple")
        if not 1 <= len(self.steps) <= 12:
            raise ValueError("PlanSketch must contain between one and twelve steps")
        if any(not isinstance(step, PlanSketchStep) for step in self.steps):
            raise TypeError("PlanSketch steps must contain PlanSketchStep values")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PlanSketch:
        data = _mapping(value, "PlanSketch")
        _exact_fields(data, {"schema_version", "goal", "steps"}, "PlanSketch")
        raw_steps = data["steps"]
        if not isinstance(raw_steps, (list, tuple)):
            raise TypeError("PlanSketch steps must be an array")
        if len(raw_steps) > 12:
            raise ValueError("PlanSketch steps exceed 12 items")
        return cls(
            schema_version=_integer(data["schema_version"], "PlanSketch schema_version"),
            goal=PlanSketchGoal.from_mapping(_mapping(data["goal"], "PlanSketch goal")),
            steps=tuple(
                PlanSketchStep.from_mapping(_mapping(item, "PlanSketch step")) for item in raw_steps
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "goal": self.goal.as_dict(),
            "steps": [step.as_dict() for step in self.steps],
        }


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _exact_fields(data: Mapping[str, object], fields: set[str], name: str) -> None:
    actual = set(data)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        raise ValueError(f"{name} fields are invalid (missing={missing}, unknown={unknown})")


def _string(
    value: object,
    name: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (not allow_empty and not value) or len(value) > maximum:
        raise ValueError(f"{name} is outside its bounded length")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


__all__ = [
    "PLAN_SKETCH_OUTPUT_CONTRACT",
    "PLAN_SKETCH_SCHEMA_VERSION",
    "NavigationGrounding",
    "PlanSketch",
    "PlanSketchGoal",
    "PlanSketchStep",
]
