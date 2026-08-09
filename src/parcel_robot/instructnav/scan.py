"""ScanBehavior helpers and PlanIR-shaped step specs (pure).

Hillclimb rung 3 / K4: rotate-in-place full turn to populate memory, then
re-ground. No runtime wiring — emits waypoints / plan-step dicts only.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from parcel_robot.instructnav.grounding import GroundingOutcome


class ScanRecoveryAction(str, Enum):
    """What the executive should do after a grounding outcome (rung 2→3)."""

    NAVIGATE = "navigate"  # RESOLVED / MEMORY_HIT → go
    SCAN = "scan"  # UNSEEN → offer ScanBehavior
    CLARIFY = "clarify"  # AMBIGUOUS → grounded clarification
    SEARCH = "search"  # UNSEEN after scan → SearchEntity
    REPORT = "report"  # exhausted recovery → honest report


@dataclass(frozen=True)
class ScanPlanSpec:
    """Pure PlanIR-shaped ScanBehavior arguments (skill name PascalCase)."""

    skill: str = "ScanBehavior"
    total_yaw_rad: float = 2.0 * math.pi
    n_stops: int = 8
    dwell_s: float = 0.35
    angular_speed_rad_s: float = 0.85
    plan_step_id: str = "scan_full_turn"
    frame: str = "base"
    populate_memory: bool = True
    re_ground: bool = True

    def __post_init__(self) -> None:
        if self.skill != "ScanBehavior":
            raise ValueError("ScanPlanSpec.skill must be 'ScanBehavior'")
        if not math.isfinite(self.total_yaw_rad) or abs(self.total_yaw_rad) < 1e-6:
            raise ValueError("total_yaw_rad must be finite and non-zero")
        if self.n_stops < 2:
            raise ValueError("n_stops must be ≥ 2")
        if not math.isfinite(self.dwell_s) or self.dwell_s < 0.0:
            raise ValueError("dwell_s must be finite and ≥ 0")
        if not math.isfinite(self.angular_speed_rad_s) or self.angular_speed_rad_s <= 0.0:
            raise ValueError("angular_speed_rad_s must be finite and positive")
        if not self.plan_step_id:
            raise ValueError("plan_step_id must be non-empty")

    def estimated_duration_s(self) -> float:
        turn = abs(self.total_yaw_rad) / self.angular_speed_rad_s
        return turn + self.dwell_s * float(self.n_stops)

    def as_plan_step(self) -> dict[str, object]:
        """Dict shaped like brain ``PlanStep`` fields (no brain import)."""

        return {
            "step_id": self.plan_step_id,
            "skill": self.skill,
            "arguments": {
                "total_yaw_rad": self.total_yaw_rad,
                "n_stops": self.n_stops,
                "dwell_s": self.dwell_s,
                "angular_speed_rad_s": self.angular_speed_rad_s,
                "frame": self.frame,
                "populate_memory": self.populate_memory,
                "re_ground": self.re_ground,
            },
        }


@dataclass(frozen=True)
class ScanStop:
    """One rotate-and-dwell stop along the scan."""

    index: int
    yaw_rad: float
    yaw_delta_from_start_rad: float
    dwell_s: float


def full_turn_scan_spec(
    *,
    n_stops: int = 8,
    dwell_s: float = 0.35,
    angular_speed_rad_s: float = 0.85,
    plan_step_id: str = "scan_full_turn",
    clockwise: bool = False,
) -> ScanPlanSpec:
    """VLFM-style initialization: one full in-place turn."""

    sign = -1.0 if clockwise else 1.0
    return ScanPlanSpec(
        total_yaw_rad=sign * 2.0 * math.pi,
        n_stops=n_stops,
        dwell_s=dwell_s,
        angular_speed_rad_s=angular_speed_rad_s,
        plan_step_id=plan_step_id,
    )


def scan_stops(start_yaw_rad: float, spec: ScanPlanSpec) -> tuple[ScanStop, ...]:
    """Yaw targets for each dwell stop (inclusive of start, exclusive of wrap)."""

    if not math.isfinite(start_yaw_rad):
        raise ValueError("start_yaw_rad must be finite")
    stops: list[ScanStop] = []
    for index in range(spec.n_stops):
        frac = index / float(spec.n_stops)
        delta = frac * spec.total_yaw_rad
        yaw = _wrap_pi(start_yaw_rad + delta)
        stops.append(
            ScanStop(
                index=index,
                yaw_rad=yaw,
                yaw_delta_from_start_rad=delta,
                dwell_s=spec.dwell_s,
            )
        )
    return tuple(stops)


def recovery_for_outcome(
    outcome: GroundingOutcome | str,
    *,
    already_scanned: bool = False,
    already_searched: bool = False,
) -> ScanRecoveryAction:
    """Map Grounder v2 outcomes onto the scan → search → report ladder."""

    value = outcome.value if isinstance(outcome, GroundingOutcome) else str(outcome)
    if value in {GroundingOutcome.RESOLVED.value, GroundingOutcome.MEMORY_HIT.value}:
        return ScanRecoveryAction.NAVIGATE
    if value == GroundingOutcome.AMBIGUOUS.value:
        return ScanRecoveryAction.CLARIFY
    if value == GroundingOutcome.UNSEEN.value:
        if already_searched:
            return ScanRecoveryAction.REPORT
        if already_scanned:
            return ScanRecoveryAction.SEARCH
        return ScanRecoveryAction.SCAN
    raise ValueError(f"unknown grounding outcome: {value!r}")


def scan_spec_from_mapping(raw: Mapping[str, object]) -> ScanPlanSpec:
    """Parse a plan-step arguments mapping into a validated ScanPlanSpec."""

    args = raw.get("arguments") if "arguments" in raw else raw
    if not isinstance(args, Mapping):
        raise TypeError("scan arguments must be a mapping")
    return ScanPlanSpec(
        skill=str(raw.get("skill", "ScanBehavior")),
        total_yaw_rad=float(args.get("total_yaw_rad", 2.0 * math.pi)),
        n_stops=int(args.get("n_stops", 8)),
        dwell_s=float(args.get("dwell_s", 0.35)),
        angular_speed_rad_s=float(args.get("angular_speed_rad_s", 0.85)),
        plan_step_id=str(raw.get("step_id") or raw.get("plan_step_id") or "scan_full_turn"),
        frame=str(args.get("frame", "base")),
        populate_memory=bool(args.get("populate_memory", True)),
        re_ground=bool(args.get("re_ground", True)),
    )


def _wrap_pi(yaw: float) -> float:
    wrapped = (yaw + math.pi) % (2.0 * math.pi) - math.pi
    return wrapped
