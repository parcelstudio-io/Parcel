"""Versioned, bounded data contracts for Parcel's split-brain architecture."""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

SCHEMA_VERSION = 1

INTENT_ROUTES = frozenset(
    {"conversation_only", "direct_skill", "deliberative_plan", "clarify_or_abstain"}
)
SPEECH_ACTS = frozenset({"request", "question", "statement", "correction", "cancel", "unknown"})
AFFECT_LABELS = frozenset({"happy", "sad", "neutral", "unknown"})
AFFECT_SOURCES = frozenset({"explicit_transcript", "prosody", "multimodal", "unknown"})
TARGET_KINDS = frozenset(
    {"semantic_region", "semantic_object", "owner", "current_pose", "safe_region"}
)
GOAL_RELATIONS = frozenset({"inside", "near", "behind", "orbit", "hold", "safe_pose", "relative"})
RESOURCES = ("base", "posture", "voice", "attention")
INTERRUPTIBILITIES = frozenset({"immediate", "checkpoint", "when_idle", "never"})
SENSOR_NAMES = frozenset({"camera", "lidar"})
BATTERY_STATES = frozenset({"unavailable", "normal", "low", "critical"})
TASK_STATES = frozenset(
    {
        "idle",
        "queued",
        "waiting_precondition",
        "waiting_resource",
        "running",
        "recovering",
        "waiting_checkpoint",
        "succeeded",
        "failed",
        "cancelled",
    }
)
ENTITY_KINDS = frozenset({"owner", "semantic_region", "semantic_object", "person"})
EXECUTION_STATUSES = frozenset(
    {"in_progress", "succeeded", "blocked", "failed", "cancelled", "timed_out"}
)
FEEDBACK_CODES = frozenset(
    {
        "in_progress",
        "succeeded",
        "blocked",
        "target_lost",
        "perception_stale",
        "owner_moved",
        "scene_changed",
        "battery_changed",
        "cancelled",
        "timed_out",
        "failed",
    }
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SKILL_NAME = re.compile(r"^[A-Z][A-Za-z0-9]{0,63}$")


class FrozenDict(Mapping[str, object]):
    """A recursively frozen, JSON-compatible mapping.

    Plan arguments cross a probabilistic/trusted boundary.  Copying and
    freezing them prevents a caller from changing a validated plan afterward.
    """

    __slots__ = ("_data",)

    def __init__(
        self,
        value: Mapping[str, object] | None = None,
        *,
        _depth: int = 0,
    ):
        source = {} if value is None else value
        if not isinstance(source, Mapping):
            raise TypeError("frozen JSON value must be a mapping")
        if len(source) > 64:
            raise ValueError("JSON mapping exceeds 64 keys")
        data: dict[str, object] = {}
        for key, item in source.items():
            if not isinstance(key, str) or not key or len(key) > 80:
                raise ValueError("JSON mapping keys must be short non-empty strings")
            data[key] = _freeze_json(item, depth=_depth + 1)
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenDict({self._data!r})"

    def to_dict(self) -> dict[str, object]:
        return {key: _thaw_json(value) for key, value in self._data.items()}


@dataclass(frozen=True, slots=True)
class AffectEvidence:
    label: str
    confidence: float
    source: str = "explicit_transcript"

    def __post_init__(self) -> None:
        _enum(self.label, AFFECT_LABELS, "affect label")
        _probability(self.confidence, "affect confidence")
        _enum(self.source, AFFECT_SOURCES, "affect source")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> AffectEvidence:
        data = _mapping(value, "affect_evidence")
        _exact_fields(data, {"label", "confidence", "source"}, "affect_evidence")
        return cls(
            label=_string(data["label"], "affect label", maximum=32),
            confidence=_number(data["confidence"], "affect confidence"),
            source=_string(data["source"], "affect source", maximum=40),
        )

    def as_dict(self) -> dict[str, object]:
        return {"label": self.label, "confidence": self.confidence, "source": self.source}


@dataclass(frozen=True, slots=True)
class IntentFrame:
    schema_version: int
    turn_id: str
    route: str
    confidence: float
    speech_act: str
    affect_evidence: AffectEvidence | None
    spatial_references: tuple[str, ...]
    urgency_cues: tuple[str, ...]
    requires_fresh_scene: bool
    original_transcript_ref: str
    transcript_sha256: str
    router_version: str
    matched_rule: str | None = None

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _identifier(self.turn_id, "turn_id")
        _enum(self.route, INTENT_ROUTES, "intent route")
        _probability(self.confidence, "intent confidence")
        _enum(self.speech_act, SPEECH_ACTS, "speech act")
        if self.affect_evidence is not None and not isinstance(
            self.affect_evidence, AffectEvidence
        ):
            raise TypeError("affect_evidence must be AffectEvidence or null")
        _string_tuple(self.spatial_references, "spatial references", maximum_items=8)
        _string_tuple(self.urgency_cues, "urgency cues", maximum_items=8)
        if not isinstance(self.requires_fresh_scene, bool):
            raise TypeError("requires_fresh_scene must be a boolean")
        _short_string(self.original_transcript_ref, "original_transcript_ref", 200)
        if not re.fullmatch(r"[0-9a-f]{64}", self.transcript_sha256):
            raise ValueError("transcript_sha256 must be a lowercase SHA-256 digest")
        _short_string(self.router_version, "router_version", 80)
        if self.matched_rule is not None:
            _short_string(self.matched_rule, "matched_rule", 80)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> IntentFrame:
        data = _mapping(value, "intent frame")
        required = {
            "schema_version",
            "turn_id",
            "route",
            "confidence",
            "speech_act",
            "affect_evidence",
            "spatial_references",
            "urgency_cues",
            "requires_fresh_scene",
            "original_transcript_ref",
            "transcript_sha256",
            "router_version",
            "matched_rule",
        }
        _exact_fields(data, required, "intent frame")
        affect_raw = data["affect_evidence"]
        affect = (
            None
            if affect_raw is None
            else AffectEvidence.from_mapping(_mapping(affect_raw, "affect_evidence"))
        )
        matched = data["matched_rule"]
        if matched is not None and not isinstance(matched, str):
            raise TypeError("matched_rule must be a string or null")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            turn_id=_string(data["turn_id"], "turn_id", maximum=128),
            route=_string(data["route"], "route", maximum=40),
            confidence=_number(data["confidence"], "confidence"),
            speech_act=_string(data["speech_act"], "speech_act", maximum=32),
            affect_evidence=affect,
            spatial_references=_strings(data["spatial_references"], "spatial_references", 8),
            urgency_cues=_strings(data["urgency_cues"], "urgency_cues", 8),
            requires_fresh_scene=_boolean(data["requires_fresh_scene"], "requires_fresh_scene"),
            original_transcript_ref=_string(
                data["original_transcript_ref"], "original_transcript_ref", maximum=200
            ),
            transcript_sha256=_string(data["transcript_sha256"], "transcript_sha256", maximum=64),
            router_version=_string(data["router_version"], "router_version", maximum=80),
            matched_rule=matched,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "turn_id": self.turn_id,
            "route": self.route,
            "confidence": self.confidence,
            "speech_act": self.speech_act,
            "affect_evidence": (
                self.affect_evidence.as_dict() if self.affect_evidence is not None else None
            ),
            "spatial_references": list(self.spatial_references),
            "urgency_cues": list(self.urgency_cues),
            "requires_fresh_scene": self.requires_fresh_scene,
            "original_transcript_ref": self.original_transcript_ref,
            "transcript_sha256": self.transcript_sha256,
            "router_version": self.router_version,
            "matched_rule": self.matched_rule,
        }


@dataclass(frozen=True, slots=True)
class GoalTarget:
    kind: str
    query: str = ""

    def __post_init__(self) -> None:
        _enum(self.kind, TARGET_KINDS, "goal target kind")
        if self.kind in {"semantic_region", "semantic_object"}:
            _short_string(self.query, "semantic target query", 160)
        elif self.query:
            _short_string(self.query, "goal target query", 160)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> GoalTarget:
        data = _mapping(value, "goal target")
        _exact_fields(data, {"kind", "query"}, "goal target")
        return cls(
            kind=_string(data["kind"], "goal target kind", maximum=40),
            query=_string(data["query"], "goal target query", maximum=160, allow_empty=True),
        )

    def as_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "query": self.query}


@dataclass(frozen=True, slots=True)
class GoalSpec:
    relation: str
    target: GoalTarget
    tolerance_m: float = 0.0

    def __post_init__(self) -> None:
        _enum(self.relation, GOAL_RELATIONS, "goal relation")
        if not isinstance(self.target, GoalTarget):
            raise TypeError("goal target must be GoalTarget")
        _bounded_number(self.tolerance_m, "goal tolerance", minimum=0.0, maximum=5.0)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> GoalSpec:
        data = _mapping(value, "goal")
        _exact_fields(data, {"relation", "target", "tolerance_m"}, "goal")
        return cls(
            relation=_string(data["relation"], "goal relation", maximum=32),
            target=GoalTarget.from_mapping(_mapping(data["target"], "goal target")),
            tolerance_m=_number(data["tolerance_m"], "goal tolerance"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "relation": self.relation,
            "target": self.target.as_dict(),
            "tolerance_m": self.tolerance_m,
        }


@dataclass(frozen=True, slots=True)
class SuccessCondition:
    fact: str
    target: str | None = None
    tolerance_m: float | None = None
    confidence_min: float | None = None

    def __post_init__(self) -> None:
        _short_string(self.fact, "success fact", 80)
        if self.target is not None:
            _short_string(self.target, "success target", 160)
        if self.tolerance_m is not None:
            _bounded_number(self.tolerance_m, "success tolerance", minimum=0.0, maximum=5.0)
        if self.confidence_min is not None:
            _probability(self.confidence_min, "success confidence")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SuccessCondition:
        data = _mapping(value, "success condition")
        _exact_fields(
            data,
            {"fact", "target", "tolerance_m", "confidence_min"},
            "success condition",
        )
        target = data["target"]
        tolerance = data["tolerance_m"]
        confidence = data["confidence_min"]
        if target is not None and not isinstance(target, str):
            raise TypeError("success target must be a string or null")
        return cls(
            fact=_string(data["fact"], "success fact", maximum=80),
            target=target,
            tolerance_m=(None if tolerance is None else _number(tolerance, "success tolerance")),
            confidence_min=(
                None if confidence is None else _number(confidence, "success confidence")
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "fact": self.fact,
            "target": self.target,
            "tolerance_m": self.tolerance_m,
            "confidence_min": self.confidence_min,
        }


@dataclass(frozen=True, slots=True)
class PlanStep:
    step_id: str
    skill: str
    arguments: FrozenDict = field(default_factory=FrozenDict)
    preconditions: tuple[str, ...] = ()
    success: SuccessCondition = field(default_factory=lambda: SuccessCondition("succeeded"))
    timeout_s: float = 30.0
    max_attempts: int = 1
    recovery: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    interruptibility: str = "checkpoint"

    def __post_init__(self) -> None:
        _identifier(self.step_id, "step_id")
        if not _SKILL_NAME.fullmatch(self.skill):
            raise ValueError("skill must be a bounded PascalCase identifier")
        if not isinstance(self.arguments, FrozenDict):
            object.__setattr__(self, "arguments", FrozenDict(self.arguments))
        _string_tuple(self.preconditions, "preconditions", maximum_items=16)
        if not isinstance(self.success, SuccessCondition):
            raise TypeError("step success must be SuccessCondition")
        _bounded_number(self.timeout_s, "step timeout", minimum=0.1, maximum=300.0)
        if isinstance(self.max_attempts, bool) or not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be an integer between one and three")
        _string_tuple(self.recovery, "recovery", maximum_items=6)
        _string_tuple(self.resources, "resources", maximum_items=len(RESOURCES))
        if len(set(self.resources)) != len(self.resources):
            raise ValueError("step resources cannot contain duplicates")
        for resource in self.resources:
            _enum(resource, frozenset(RESOURCES), "step resource")
        _enum(self.interruptibility, INTERRUPTIBILITIES, "step interruptibility")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PlanStep:
        data = _mapping(value, "plan step")
        fields = {
            "id",
            "skill",
            "arguments",
            "preconditions",
            "success",
            "timeout_s",
            "max_attempts",
            "recovery",
            "resources",
            "interruptibility",
        }
        _exact_fields(data, fields, "plan step")
        return cls(
            step_id=_string(data["id"], "step id", maximum=128),
            skill=_string(data["skill"], "skill", maximum=64),
            arguments=FrozenDict(_mapping(data["arguments"], "step arguments")),
            preconditions=_strings(data["preconditions"], "preconditions", 16),
            success=SuccessCondition.from_mapping(_mapping(data["success"], "success condition")),
            timeout_s=_number(data["timeout_s"], "step timeout"),
            max_attempts=_integer(data["max_attempts"], "max_attempts"),
            recovery=_strings(data["recovery"], "recovery", 6),
            resources=_strings(data["resources"], "resources", len(RESOURCES)),
            interruptibility=_string(data["interruptibility"], "interruptibility", maximum=32),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.step_id,
            "skill": self.skill,
            "arguments": self.arguments.to_dict(),
            "preconditions": list(self.preconditions),
            "success": self.success.as_dict(),
            "timeout_s": self.timeout_s,
            "max_attempts": self.max_attempts,
            "recovery": list(self.recovery),
            "resources": list(self.resources),
            "interruptibility": self.interruptibility,
        }


@dataclass(frozen=True, slots=True)
class PlanIR:
    schema_version: int
    task_id: str
    plan_revision: int
    source_turn_id: str
    goal: GoalSpec
    invariants: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    requested_interrupt: str = "at_checkpoint"

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _identifier(self.task_id, "task_id")
        if isinstance(self.plan_revision, bool) or not 1 <= self.plan_revision <= 1_000_000:
            raise ValueError("plan_revision must be a positive integer")
        _identifier(self.source_turn_id, "source_turn_id")
        if not isinstance(self.goal, GoalSpec):
            raise TypeError("plan goal must be GoalSpec")
        _string_tuple(self.invariants, "invariants", maximum_items=16)
        if not isinstance(self.steps, tuple):
            raise TypeError("plan steps must be a tuple")
        if not self.steps or len(self.steps) > 12:
            raise ValueError("PlanIR must contain between one and twelve steps")
        if any(not isinstance(step, PlanStep) for step in self.steps):
            raise TypeError("plan steps must contain PlanStep values")
        if self.requested_interrupt not in {
            "interrupt_now",
            "at_checkpoint",
            "when_idle",
        }:
            raise ValueError("requested_interrupt is not allowed")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PlanIR:
        data = _mapping(value, "PlanIR")
        _exact_fields(
            data,
            {
                "schema_version",
                "task_id",
                "plan_revision",
                "source_turn_id",
                "goal",
                "invariants",
                "steps",
                "requested_interrupt",
            },
            "PlanIR",
        )
        raw_steps = _sequence(data["steps"], "steps", maximum=12)
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            task_id=_string(data["task_id"], "task_id", maximum=128),
            plan_revision=_integer(data["plan_revision"], "plan_revision"),
            source_turn_id=_string(data["source_turn_id"], "source_turn_id", maximum=128),
            goal=GoalSpec.from_mapping(_mapping(data["goal"], "goal")),
            invariants=_strings(data["invariants"], "invariants", 16),
            steps=tuple(PlanStep.from_mapping(_mapping(item, "plan step")) for item in raw_steps),
            requested_interrupt=_string(
                data["requested_interrupt"], "requested_interrupt", maximum=32
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "plan_revision": self.plan_revision,
            "source_turn_id": self.source_turn_id,
            "goal": self.goal.as_dict(),
            "invariants": list(self.invariants),
            "steps": [step.as_dict() for step in self.steps],
            "requested_interrupt": self.requested_interrupt,
        }


@dataclass(frozen=True, slots=True)
class SensorSnapshot:
    name: str
    available: bool
    fresh: bool
    source: str
    observed_at_monotonic_s: float | None
    age_ms: float | None

    def __post_init__(self) -> None:
        _enum(self.name, SENSOR_NAMES, "sensor name")
        if not isinstance(self.available, bool) or not isinstance(self.fresh, bool):
            raise TypeError("sensor available/fresh fields must be booleans")
        _short_string(self.source, "sensor source", 80)
        if self.observed_at_monotonic_s is not None:
            _bounded_number(
                self.observed_at_monotonic_s,
                "sensor observed time",
                minimum=0.0,
                maximum=None,
            )
        if self.age_ms is not None:
            _bounded_number(self.age_ms, "sensor age", minimum=0.0, maximum=3_600_000.0)
        if self.fresh and not self.available:
            raise ValueError("an unavailable sensor cannot be fresh")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SensorSnapshot:
        data = _mapping(value, "sensor snapshot")
        _exact_fields(
            data,
            {"name", "available", "fresh", "source", "observed_at_monotonic_s", "age_ms"},
            "sensor snapshot",
        )
        observed = data["observed_at_monotonic_s"]
        age = data["age_ms"]
        return cls(
            name=_string(data["name"], "sensor name", maximum=16),
            available=_boolean(data["available"], "sensor available"),
            fresh=_boolean(data["fresh"], "sensor fresh"),
            source=_string(data["source"], "sensor source", maximum=80),
            observed_at_monotonic_s=(
                None if observed is None else _number(observed, "sensor observed time")
            ),
            age_ms=None if age is None else _number(age, "sensor age"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "available": self.available,
            "fresh": self.fresh,
            "source": self.source,
            "observed_at_monotonic_s": self.observed_at_monotonic_s,
            "age_ms": self.age_ms,
        }


@dataclass(frozen=True, slots=True)
class RobotStateSnapshot:
    moving: bool
    controller_state: str
    x: float | None = None
    y: float | None = None
    z: float | None = None
    yaw_rad: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.moving, bool):
            raise TypeError("robot moving must be a boolean")
        _short_string(self.controller_state, "controller_state", 80)
        for name, value in (("x", self.x), ("y", self.y), ("z", self.z), ("yaw", self.yaw_rad)):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"robot {name} must be finite")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RobotStateSnapshot:
        data = _mapping(value, "robot snapshot")
        _exact_fields(
            data, {"moving", "controller_state", "x", "y", "z", "yaw_rad"}, "robot snapshot"
        )
        return cls(
            moving=_boolean(data["moving"], "robot moving"),
            controller_state=_string(data["controller_state"], "controller_state", maximum=80),
            x=_optional_number(data["x"], "robot x"),
            y=_optional_number(data["y"], "robot y"),
            z=_optional_number(data["z"], "robot z"),
            yaw_rad=_optional_number(data["yaw_rad"], "robot yaw"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "moving": self.moving,
            "controller_state": self.controller_state,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "yaw_rad": self.yaw_rad,
        }


@dataclass(frozen=True, slots=True)
class SafetyStateSnapshot:
    emergency_stopped: bool
    collision_imminent: bool
    telemetry_fresh: bool
    nearest_obstacle_m: float | None = None
    nearest_person_m: float | None = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(item, bool)
            for item in (self.emergency_stopped, self.collision_imminent, self.telemetry_fresh)
        ):
            raise TypeError("safety flags must be booleans")
        for name, value in (
            ("nearest_obstacle_m", self.nearest_obstacle_m),
            ("nearest_person_m", self.nearest_person_m),
        ):
            if value is not None:
                _bounded_number(value, name, minimum=0.0, maximum=10_000.0)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SafetyStateSnapshot:
        data = _mapping(value, "safety snapshot")
        _exact_fields(
            data,
            {
                "emergency_stopped",
                "collision_imminent",
                "telemetry_fresh",
                "nearest_obstacle_m",
                "nearest_person_m",
            },
            "safety snapshot",
        )
        return cls(
            emergency_stopped=_boolean(data["emergency_stopped"], "emergency_stopped"),
            collision_imminent=_boolean(data["collision_imminent"], "collision_imminent"),
            telemetry_fresh=_boolean(data["telemetry_fresh"], "telemetry_fresh"),
            nearest_obstacle_m=_optional_number(data["nearest_obstacle_m"], "nearest_obstacle_m"),
            nearest_person_m=_optional_number(data["nearest_person_m"], "nearest_person_m"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "emergency_stopped": self.emergency_stopped,
            "collision_imminent": self.collision_imminent,
            "telemetry_fresh": self.telemetry_fresh,
            "nearest_obstacle_m": self.nearest_obstacle_m,
            "nearest_person_m": self.nearest_person_m,
        }


@dataclass(frozen=True, slots=True)
class BatteryStateSnapshot:
    state: str = "unavailable"
    percent: float | None = None
    source: str = "unavailable"

    def __post_init__(self) -> None:
        _enum(self.state, BATTERY_STATES, "battery state")
        if self.percent is not None:
            _bounded_number(self.percent, "battery percent", minimum=0.0, maximum=100.0)
        _short_string(self.source, "battery source", 80)
        if self.state == "unavailable" and self.percent is not None:
            raise ValueError("unavailable battery state cannot carry a percentage")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> BatteryStateSnapshot:
        data = _mapping(value, "battery snapshot")
        _exact_fields(data, {"state", "percent", "source"}, "battery snapshot")
        return cls(
            state=_string(data["state"], "battery state", maximum=24),
            percent=_optional_number(data["percent"], "battery percent"),
            source=_string(data["source"], "battery source", maximum=80),
        )

    def as_dict(self) -> dict[str, object]:
        return {"state": self.state, "percent": self.percent, "source": self.source}


@dataclass(frozen=True, slots=True)
class TaskStateSnapshot:
    state: str = "idle"
    task_id: str | None = None
    plan_revision: int | None = None
    step_id: str | None = None
    at_checkpoint: bool = True

    def __post_init__(self) -> None:
        _enum(self.state, TASK_STATES, "task state")
        if self.task_id is not None:
            _identifier(self.task_id, "task_id")
        if self.plan_revision is not None and (
            isinstance(self.plan_revision, bool) or self.plan_revision < 1
        ):
            raise ValueError("task plan_revision must be a positive integer or null")
        if self.step_id is not None:
            _identifier(self.step_id, "step_id")
        if not isinstance(self.at_checkpoint, bool):
            raise TypeError("at_checkpoint must be a boolean")
        if self.state == "idle" and any(
            item is not None for item in (self.task_id, self.plan_revision, self.step_id)
        ):
            raise ValueError("idle task state cannot identify a task or step")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TaskStateSnapshot:
        data = _mapping(value, "task snapshot")
        _exact_fields(
            data,
            {"state", "task_id", "plan_revision", "step_id", "at_checkpoint"},
            "task snapshot",
        )
        task_id = data["task_id"]
        step_id = data["step_id"]
        revision = data["plan_revision"]
        if task_id is not None and not isinstance(task_id, str):
            raise TypeError("task_id must be a string or null")
        if step_id is not None and not isinstance(step_id, str):
            raise TypeError("step_id must be a string or null")
        return cls(
            state=_string(data["state"], "task state", maximum=40),
            task_id=task_id,
            plan_revision=(None if revision is None else _integer(revision, "plan_revision")),
            step_id=step_id,
            at_checkpoint=_boolean(data["at_checkpoint"], "at_checkpoint"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "task_id": self.task_id,
            "plan_revision": self.plan_revision,
            "step_id": self.step_id,
            "at_checkpoint": self.at_checkpoint,
        }


@dataclass(frozen=True, slots=True)
class ResourceLease:
    resource: str
    owner_task_id: str
    owner_step_id: str

    def __post_init__(self) -> None:
        _enum(self.resource, frozenset(RESOURCES), "resource lease")
        _identifier(self.owner_task_id, "owner_task_id")
        _identifier(self.owner_step_id, "owner_step_id")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ResourceLease:
        data = _mapping(value, "resource lease")
        _exact_fields(data, {"resource", "owner_task_id", "owner_step_id"}, "resource lease")
        return cls(
            resource=_string(data["resource"], "resource", maximum=16),
            owner_task_id=_string(data["owner_task_id"], "owner_task_id", maximum=128),
            owner_step_id=_string(data["owner_step_id"], "owner_step_id", maximum=128),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "resource": self.resource,
            "owner_task_id": self.owner_task_id,
            "owner_step_id": self.owner_step_id,
        }


@dataclass(frozen=True, slots=True)
class ObservedEntity:
    entity_id: str
    kind: str
    label: str
    confidence: float
    source: str
    observed_at_monotonic_s: float
    attributes: FrozenDict = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        _identifier(self.entity_id, "entity_id")
        _enum(self.kind, ENTITY_KINDS, "entity kind")
        _short_string(self.label, "entity label", 160)
        _probability(self.confidence, "entity confidence")
        _short_string(self.source, "entity source", 80)
        _bounded_number(
            self.observed_at_monotonic_s,
            "entity observed time",
            minimum=0.0,
            maximum=None,
        )
        if not isinstance(self.attributes, FrozenDict):
            object.__setattr__(self, "attributes", FrozenDict(self.attributes))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ObservedEntity:
        data = _mapping(value, "observed entity")
        _exact_fields(
            data,
            {
                "entity_id",
                "kind",
                "label",
                "confidence",
                "source",
                "observed_at_monotonic_s",
                "attributes",
            },
            "observed entity",
        )
        return cls(
            entity_id=_string(data["entity_id"], "entity_id", maximum=128),
            kind=_string(data["kind"], "entity kind", maximum=40),
            label=_string(data["label"], "entity label", maximum=160),
            confidence=_number(data["confidence"], "entity confidence"),
            source=_string(data["source"], "entity source", maximum=80),
            observed_at_monotonic_s=_number(
                data["observed_at_monotonic_s"], "entity observed time"
            ),
            attributes=FrozenDict(_mapping(data["attributes"], "entity attributes")),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "entity_id": self.entity_id,
            "kind": self.kind,
            "label": self.label,
            "confidence": self.confidence,
            "source": self.source,
            "observed_at_monotonic_s": self.observed_at_monotonic_s,
            "attributes": self.attributes.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ObservationSnapshot:
    schema_version: int
    snapshot_id: str
    captured_at_monotonic_s: float
    camera: SensorSnapshot
    lidar: SensorSnapshot
    robot: RobotStateSnapshot
    safety: SafetyStateSnapshot
    battery: BatteryStateSnapshot
    task: TaskStateSnapshot
    resource_leases: tuple[ResourceLease, ...] = ()
    entities: tuple[ObservedEntity, ...] = ()

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _identifier(self.snapshot_id, "snapshot_id")
        _bounded_number(
            self.captured_at_monotonic_s,
            "snapshot capture time",
            minimum=0.0,
            maximum=None,
        )
        if not isinstance(self.camera, SensorSnapshot) or not isinstance(
            self.lidar, SensorSnapshot
        ):
            raise TypeError("observation sensors must be SensorSnapshot values")
        if self.camera.name != "camera" or self.lidar.name != "lidar":
            raise ValueError("observation sensors must be camera and lidar")
        if not isinstance(self.robot, RobotStateSnapshot):
            raise TypeError("observation robot must be RobotStateSnapshot")
        if not isinstance(self.safety, SafetyStateSnapshot):
            raise TypeError("observation safety must be SafetyStateSnapshot")
        if not isinstance(self.battery, BatteryStateSnapshot):
            raise TypeError("observation battery must be BatteryStateSnapshot")
        if not isinstance(self.task, TaskStateSnapshot):
            raise TypeError("observation task must be TaskStateSnapshot")
        if not isinstance(self.resource_leases, tuple) or any(
            not isinstance(item, ResourceLease) for item in self.resource_leases
        ):
            raise TypeError("resource_leases must be a tuple of ResourceLease values")
        if not isinstance(self.entities, tuple) or any(
            not isinstance(item, ObservedEntity) for item in self.entities
        ):
            raise TypeError("entities must be a tuple of ObservedEntity values")
        if len(self.resource_leases) > len(RESOURCES):
            raise ValueError("observation contains too many resource leases")
        lease_names = [item.resource for item in self.resource_leases]
        if len(set(lease_names)) != len(lease_names):
            raise ValueError("observation resource leases must be unique")
        if len(self.entities) > 64:
            raise ValueError("observation contains more than 64 entities")
        entity_ids = [item.entity_id for item in self.entities]
        if len(set(entity_ids)) != len(entity_ids):
            raise ValueError("observation entity IDs must be unique")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ObservationSnapshot:
        data = _mapping(value, "observation snapshot")
        _exact_fields(
            data,
            {
                "schema_version",
                "snapshot_id",
                "captured_at_monotonic_s",
                "camera",
                "lidar",
                "robot",
                "safety",
                "battery",
                "task",
                "resource_leases",
                "entities",
            },
            "observation snapshot",
        )
        leases = _sequence(data["resource_leases"], "resource_leases", maximum=4)
        entities = _sequence(data["entities"], "entities", maximum=64)
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            snapshot_id=_string(data["snapshot_id"], "snapshot_id", maximum=128),
            captured_at_monotonic_s=_number(
                data["captured_at_monotonic_s"], "snapshot capture time"
            ),
            camera=SensorSnapshot.from_mapping(_mapping(data["camera"], "camera")),
            lidar=SensorSnapshot.from_mapping(_mapping(data["lidar"], "lidar")),
            robot=RobotStateSnapshot.from_mapping(_mapping(data["robot"], "robot")),
            safety=SafetyStateSnapshot.from_mapping(_mapping(data["safety"], "safety")),
            battery=BatteryStateSnapshot.from_mapping(_mapping(data["battery"], "battery")),
            task=TaskStateSnapshot.from_mapping(_mapping(data["task"], "task")),
            resource_leases=tuple(
                ResourceLease.from_mapping(_mapping(item, "resource lease")) for item in leases
            ),
            entities=tuple(
                ObservedEntity.from_mapping(_mapping(item, "observed entity")) for item in entities
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "captured_at_monotonic_s": self.captured_at_monotonic_s,
            "camera": self.camera.as_dict(),
            "lidar": self.lidar.as_dict(),
            "robot": self.robot.as_dict(),
            "safety": self.safety.as_dict(),
            "battery": self.battery.as_dict(),
            "task": self.task.as_dict(),
            "resource_leases": [item.as_dict() for item in self.resource_leases],
            "entities": [item.as_dict() for item in self.entities],
        }

    def matching_entities(self, query: str) -> tuple[ObservedEntity, ...]:
        normalized = _normalized_label(query)
        if not normalized:
            return ()
        return tuple(
            item
            for item in self.entities
            if normalized in _normalized_label(item.label)
            or _normalized_label(item.label) in normalized
        )


@dataclass(frozen=True, slots=True)
class VerifiedFact:
    fact: str
    target: str | None
    source: str
    confidence: float

    def __post_init__(self) -> None:
        _short_string(self.fact, "verified fact", 80)
        if self.target is not None:
            _short_string(self.target, "verified fact target", 160)
        _short_string(self.source, "verified fact source", 80)
        _probability(self.confidence, "verified fact confidence")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> VerifiedFact:
        data = _mapping(value, "verified fact")
        _exact_fields(data, {"fact", "target", "source", "confidence"}, "verified fact")
        target = data["target"]
        if target is not None and not isinstance(target, str):
            raise TypeError("verified fact target must be a string or null")
        return cls(
            fact=_string(data["fact"], "verified fact", maximum=80),
            target=target,
            source=_string(data["source"], "verified fact source", maximum=80),
            confidence=_number(data["confidence"], "verified fact confidence"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "fact": self.fact,
            "target": self.target,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    schema_version: int
    task_id: str
    plan_revision: int
    step_id: str
    attempt: int
    status: str
    feedback_code: str
    snapshot_id: str | None
    verified_facts: tuple[VerifiedFact, ...]
    checkpoint: bool
    detail_code: str
    started_at_monotonic_s: float
    finished_at_monotonic_s: float | None

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _identifier(self.task_id, "task_id")
        if isinstance(self.plan_revision, bool) or self.plan_revision < 1:
            raise ValueError("plan_revision must be positive")
        _identifier(self.step_id, "step_id")
        if isinstance(self.attempt, bool) or not 1 <= self.attempt <= 3:
            raise ValueError("attempt must be between one and three")
        _enum(self.status, EXECUTION_STATUSES, "execution status")
        _enum(self.feedback_code, FEEDBACK_CODES, "execution feedback code")
        if self.snapshot_id is not None:
            _identifier(self.snapshot_id, "snapshot_id")
        if len(self.verified_facts) > 16:
            raise ValueError("execution result has too many verified facts")
        if not isinstance(self.verified_facts, tuple) or any(
            not isinstance(item, VerifiedFact) for item in self.verified_facts
        ):
            raise TypeError("verified_facts must be a tuple of VerifiedFact values")
        if not isinstance(self.checkpoint, bool):
            raise TypeError("execution checkpoint must be a boolean")
        _short_string(self.detail_code, "execution detail code", 120)
        _bounded_number(
            self.started_at_monotonic_s,
            "execution start time",
            minimum=0.0,
            maximum=None,
        )
        if self.finished_at_monotonic_s is not None:
            _bounded_number(
                self.finished_at_monotonic_s,
                "execution finish time",
                minimum=self.started_at_monotonic_s,
                maximum=None,
            )
        if self.status == "in_progress" and self.finished_at_monotonic_s is not None:
            raise ValueError("in-progress execution cannot have a finish time")
        if self.status != "in_progress" and self.finished_at_monotonic_s is None:
            raise ValueError("terminal execution result requires a finish time")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ExecutionResult:
        data = _mapping(value, "execution result")
        _exact_fields(
            data,
            {
                "schema_version",
                "task_id",
                "plan_revision",
                "step_id",
                "attempt",
                "status",
                "feedback_code",
                "snapshot_id",
                "verified_facts",
                "checkpoint",
                "detail_code",
                "started_at_monotonic_s",
                "finished_at_monotonic_s",
            },
            "execution result",
        )
        snapshot = data["snapshot_id"]
        if snapshot is not None and not isinstance(snapshot, str):
            raise TypeError("snapshot_id must be a string or null")
        finished = data["finished_at_monotonic_s"]
        facts = _sequence(data["verified_facts"], "verified_facts", maximum=16)
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            task_id=_string(data["task_id"], "task_id", maximum=128),
            plan_revision=_integer(data["plan_revision"], "plan_revision"),
            step_id=_string(data["step_id"], "step_id", maximum=128),
            attempt=_integer(data["attempt"], "attempt"),
            status=_string(data["status"], "status", maximum=32),
            feedback_code=_string(data["feedback_code"], "feedback_code", maximum=40),
            snapshot_id=snapshot,
            verified_facts=tuple(
                VerifiedFact.from_mapping(_mapping(item, "verified fact")) for item in facts
            ),
            checkpoint=_boolean(data["checkpoint"], "checkpoint"),
            detail_code=_string(data["detail_code"], "detail_code", maximum=120),
            started_at_monotonic_s=_number(data["started_at_monotonic_s"], "execution start time"),
            finished_at_monotonic_s=(
                None if finished is None else _number(finished, "execution finish time")
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "plan_revision": self.plan_revision,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "status": self.status,
            "feedback_code": self.feedback_code,
            "snapshot_id": self.snapshot_id,
            "verified_facts": [item.as_dict() for item in self.verified_facts],
            "checkpoint": self.checkpoint,
            "detail_code": self.detail_code,
            "started_at_monotonic_s": self.started_at_monotonic_s,
            "finished_at_monotonic_s": self.finished_at_monotonic_s,
        }


def _freeze_json(value: object, *, depth: int) -> object:
    if depth > 6:
        raise ValueError("JSON value exceeds maximum nesting depth")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > 500:
            raise ValueError("JSON string exceeds 500 characters")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        if len(value) > 64:
            raise ValueError("JSON mapping exceeds 64 keys")
        return FrozenDict(value, _depth=depth)
    if isinstance(value, (list, tuple)):
        if len(value) > 64:
            raise ValueError("JSON sequence exceeds 64 items")
        return tuple(_freeze_json(item, depth=depth + 1) for item in value)
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def _thaw_json(value: object) -> object:
    if isinstance(value, FrozenDict):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _exact_fields(data: Mapping[str, object], fields: set[str], name: str) -> None:
    actual = set(data)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if unknown:
            detail.append(f"unknown={unknown}")
        raise ValueError(f"{name} fields are invalid ({', '.join(detail)})")


def _version(value: object) -> None:
    if isinstance(value, bool) or value != SCHEMA_VERSION:
        raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")


def _string(value: object, name: str, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (not allow_empty and not value) or len(value) > maximum:
        qualifier = "possibly empty " if allow_empty else "non-empty "
        raise ValueError(f"{name} must be a {qualifier}string of at most {maximum} characters")
    return value


def _short_string(value: object, name: str, maximum: int) -> None:
    _string(value, name, maximum=maximum)


def _identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a bounded identifier")


def _enum(value: object, allowed: frozenset[str], name: str) -> None:
    if value not in allowed:
        raise ValueError(f"{name} is not allowed: {value!r}")


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _optional_number(value: object, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _probability(value: object, name: str) -> None:
    _bounded_number(value, name, minimum=0.0, maximum=1.0)


def _bounded_number(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float | None,
) -> None:
    number = _number(value, name)
    if number < minimum or (maximum is not None and number > maximum):
        upper = "infinity" if maximum is None else str(maximum)
        raise ValueError(f"{name} must be between {minimum} and {upper}")


def _sequence(value: object, name: str, *, maximum: int) -> list[object] | tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be an array")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds {maximum} items")
    return value


def _strings(value: object, name: str, maximum: int) -> tuple[str, ...]:
    items = _sequence(value, name, maximum=maximum)
    result = tuple(_string(item, name, maximum=160) for item in items)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _string_tuple(value: tuple[str, ...], name: str, *, maximum_items: int) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{name} must be a tuple")
    if len(value) > maximum_items:
        raise ValueError(f"{name} exceeds {maximum_items} items")
    for item in value:
        _short_string(item, name, 160)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} cannot contain duplicates")


def _normalized_label(value: str) -> str:
    return "".join(re.findall(r"[a-z0-9]+", value.lower()))
