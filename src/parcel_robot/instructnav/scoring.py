"""Episode scoring, goal-region predicates, and failure attribution (pure)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureClass(str, Enum):
    GROUNDING_ERROR = "grounding_error"
    SEARCH_ERROR = "search_error"
    PLANNING_ERROR = "planning_error"
    CONTROL_ERROR = "control_error"
    REFUSAL = "refusal"
    NONE = "none"


class AttributionLayer(str, Enum):
    """L1–L6 refinement used by oracle counterfactual replay."""

    L1_PARSE = "L1_parse"
    L2A_VOCABULARY = "L2a_vocabulary"
    L2B_VISIBILITY = "L2b_visibility_gated"
    L3_EXPLORATION = "L3_exploration"
    L4_PLANNING = "L4_planning"
    L5_CONTROL = "L5_control"
    L6_TERMINATION = "L6_termination"
    NONE = "none"


@dataclass(frozen=True)
class GoalRegion:
    kind: str  # "disc" | "polygon" | "relative_band"
    center: tuple[float, float] | None = None
    radius_m: float | None = None
    polygon: tuple[tuple[float, float], ...] | None = None
    anchor_entity: str | None = None
    band_m: tuple[float, float] | None = None
    anchor_footprint_m: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in {"disc", "polygon", "relative_band"}:
            raise ValueError(f"unsupported GoalRegion kind: {self.kind!r}")
        if self.kind == "disc":
            if self.center is None or self.radius_m is None:
                raise ValueError("disc GoalRegion requires center and radius_m")
            if not math.isfinite(self.radius_m) or self.radius_m <= 0.0:
                raise ValueError("disc radius_m must be finite and positive")
            _finite_xy(self.center)
        elif self.kind == "polygon":
            if self.polygon is None or len(self.polygon) < 3:
                raise ValueError("polygon GoalRegion requires ≥3 vertices")
            for point in self.polygon:
                _finite_xy(point)
        else:
            if self.band_m is None:
                raise ValueError("relative_band GoalRegion requires band_m")
            lo, hi = float(self.band_m[0]), float(self.band_m[1])
            if not (math.isfinite(lo) and math.isfinite(hi) and 0.0 <= lo < hi):
                raise ValueError("relative_band band_m must satisfy 0 ≤ min < max")
            if self.anchor_footprint_m < 0.0 or not math.isfinite(self.anchor_footprint_m):
                raise ValueError("anchor_footprint_m must be finite and ≥ 0")

    def contains(
        self,
        x: float,
        y: float,
        anchor_xy: tuple[float, float] | None = None,
    ) -> bool:
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
        if self.kind == "disc":
            assert self.center is not None and self.radius_m is not None
            return math.hypot(x - self.center[0], y - self.center[1]) <= self.radius_m
        if self.kind == "polygon":
            assert self.polygon is not None
            return _point_in_polygon((x, y), self.polygon)
        anchor = anchor_xy if anchor_xy is not None else self.center
        if anchor is None or self.band_m is None:
            return False
        dist = math.hypot(x - anchor[0], y - anchor[1])
        lo, hi = float(self.band_m[0]), float(self.band_m[1])
        footprint = float(self.anchor_footprint_m)
        # Must sit in the band and not overlap the anchor footprint.
        return lo <= dist <= hi and dist >= footprint

    def distance_to(
        self,
        x: float,
        y: float,
        anchor_xy: tuple[float, float] | None = None,
    ) -> float:
        if not (math.isfinite(x) and math.isfinite(y)):
            return float("inf")
        if self.contains(x, y, anchor_xy=anchor_xy):
            return 0.0
        if self.kind == "disc":
            assert self.center is not None and self.radius_m is not None
            return max(
                0.0,
                math.hypot(x - self.center[0], y - self.center[1]) - self.radius_m,
            )
        if self.kind == "polygon":
            assert self.polygon is not None
            return _distance_to_polygon((x, y), self.polygon)
        anchor = anchor_xy if anchor_xy is not None else self.center
        if anchor is None or self.band_m is None:
            return float("inf")
        dist = math.hypot(x - anchor[0], y - anchor[1])
        lo, hi = float(self.band_m[0]), float(self.band_m[1])
        footprint = float(self.anchor_footprint_m)
        # Distance to the nearest admissible ring point (outside footprint).
        target_r = max(lo, footprint)
        if dist < target_r:
            return target_r - dist
        if dist > hi:
            return dist - hi
        return 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "center": list(self.center) if self.center is not None else None,
            "radius_m": self.radius_m,
            "polygon": [list(p) for p in self.polygon] if self.polygon is not None else None,
            "anchor_entity": self.anchor_entity,
            "band_m": list(self.band_m) if self.band_m is not None else None,
            "anchor_footprint_m": self.anchor_footprint_m,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> GoalRegion:
        center_raw = data.get("center")
        center = (
            (float(center_raw[0]), float(center_raw[1]))
            if isinstance(center_raw, (list, tuple)) and len(center_raw) >= 2
            else None
        )
        polygon_raw = data.get("polygon")
        polygon = None
        if isinstance(polygon_raw, (list, tuple)) and polygon_raw:
            polygon = tuple((float(p[0]), float(p[1])) for p in polygon_raw)
        band_raw = data.get("band_m")
        band = (
            (float(band_raw[0]), float(band_raw[1]))
            if isinstance(band_raw, (list, tuple)) and len(band_raw) >= 2
            else None
        )
        radius = data.get("radius_m")
        return cls(
            kind=str(data["kind"]),
            center=center,
            radius_m=float(radius) if radius is not None else None,
            polygon=polygon,
            anchor_entity=(
                str(data["anchor_entity"]) if data.get("anchor_entity") is not None else None
            ),
            band_m=band,
            anchor_footprint_m=float(data.get("anchor_footprint_m") or 0.0),
        )


@dataclass(frozen=True)
class EpisodeScore:
    success: bool
    spl: float
    distance_to_goal_m: float
    time_to_goal_s: float | None
    failure: FailureClass
    detail: str
    oracle_success: bool = False
    oracle_sr_gap: float = 0.0  # OSR − SR for this episode (0 or 1)
    attribution_layer: AttributionLayer = AttributionLayer.NONE

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "spl": self.spl,
            "distance_to_goal_m": self.distance_to_goal_m,
            "time_to_goal_s": self.time_to_goal_s,
            "failure": self.failure.value,
            "detail": self.detail,
            "oracle_success": self.oracle_success,
            "oracle_sr_gap": self.oracle_sr_gap,
            "attribution_layer": self.attribution_layer.value,
        }


@dataclass(frozen=True)
class OracleAttribution:
    """Result of oracle counterfactual auto-replay (research addendum)."""

    layer: AttributionLayer
    grounding_gap: bool
    exploration_gap: bool
    detail: str


def score_episode(
    trace: Sequence[Mapping[str, object]],
    goal: GoalRegion,
    *,
    shortest_path_m: float,
    max_time_s: float,
    arrival_hold_s: float = 1.0,
    anchor_xy: tuple[float, float] | None = None,
    oracle_success: bool | None = None,
) -> EpisodeScore:
    """Score one instruction-nav episode.

    Success = agent inside the region, stopped, and holding for
    ``arrival_hold_s`` (agent-stop convention). SPL = S · L / max(L, P).
    """

    if not math.isfinite(shortest_path_m) or shortest_path_m < 0.0:
        raise ValueError("shortest_path_m must be finite and ≥ 0")
    if not math.isfinite(max_time_s) or max_time_s <= 0.0:
        raise ValueError("max_time_s must be finite and positive")
    if not math.isfinite(arrival_hold_s) or arrival_hold_s < 0.0:
        raise ValueError("arrival_hold_s must be finite and ≥ 0")

    if not trace:
        failure = FailureClass.REFUSAL
        return EpisodeScore(
            success=False,
            spl=0.0,
            distance_to_goal_m=float("inf"),
            time_to_goal_s=None,
            failure=failure,
            detail="empty_trace",
            oracle_success=bool(oracle_success),
            oracle_sr_gap=1.0 if oracle_success else 0.0,
            attribution_layer=_layer_for_failure(failure),
        )

    path_length_m = _path_length(trace)
    final = trace[-1]
    fx, fy = _xy(final)
    dtg = goal.distance_to(fx, fy, anchor_xy=anchor_xy)
    hold = _arrival_hold(
        trace,
        goal,
        arrival_hold_s=arrival_hold_s,
        anchor_xy=anchor_xy,
    )
    success = hold is not None
    spl = 0.0
    if success and shortest_path_m > 0.0:
        spl = shortest_path_m / max(shortest_path_m, path_length_m)
    elif success and shortest_path_m == 0.0:
        spl = 1.0 if path_length_m <= 1e-6 else 0.0

    failure = FailureClass.NONE if success else _classify_failure(trace, goal, anchor_xy)
    if oracle_success is not None:
        o_success = bool(oracle_success)
    else:
        # OSR − SR isolates termination: ever inside the region (ignore hold).
        o_success = success or _ever_inside(trace, goal, anchor_xy=anchor_xy)
    return EpisodeScore(
        success=success,
        spl=float(spl),
        distance_to_goal_m=float(dtg),
        time_to_goal_s=hold,
        failure=failure,
        detail=_detail(success, failure, trace),
        oracle_success=o_success,
        oracle_sr_gap=float(int(o_success) - int(success)),
        attribution_layer=(
            AttributionLayer.NONE if success else _layer_for_failure(failure)
        ),
    )


def score_episode_with_oracle(
    trace: Sequence[Mapping[str, object]],
    goal: GoalRegion,
    *,
    shortest_path_m: float,
    max_time_s: float,
    arrival_hold_s: float = 1.0,
    anchor_xy: tuple[float, float] | None = None,
    oracle_grounding_flips: bool,
    oracle_grounding_and_explore_flips: bool,
) -> tuple[EpisodeScore, OracleAttribution]:
    """Score plus L1–L6 attribution via oracle counterfactual hooks.

    Callers re-run failed episodes with (1) oracle grounding and (2) oracle
    grounding + scripted exploration; the first flip names the layer.
    """

    base = score_episode(
        trace,
        goal,
        shortest_path_m=shortest_path_m,
        max_time_s=max_time_s,
        arrival_hold_s=arrival_hold_s,
        anchor_xy=anchor_xy,
        oracle_success=oracle_grounding_and_explore_flips or oracle_grounding_flips,
    )
    if base.success:
        attr = OracleAttribution(
            layer=AttributionLayer.NONE,
            grounding_gap=False,
            exploration_gap=False,
            detail="success",
        )
        return base, attr

    if oracle_grounding_flips:
        layer = AttributionLayer.L2B_VISIBILITY
        # Vocabulary vs visibility: refusal / wrong label → L2a.
        if base.failure == FailureClass.GROUNDING_ERROR:
            detail_text = str(base.detail).lower()
            if "vocab" in detail_text or "unknown_label" in detail_text:
                layer = AttributionLayer.L2A_VOCABULARY
        attr = OracleAttribution(
            layer=layer,
            grounding_gap=True,
            exploration_gap=False,
            detail="oracle_grounding_flips",
        )
        return (
            EpisodeScore(
                success=base.success,
                spl=base.spl,
                distance_to_goal_m=base.distance_to_goal_m,
                time_to_goal_s=base.time_to_goal_s,
                failure=base.failure,
                detail=base.detail,
                oracle_success=True,
                oracle_sr_gap=1.0,
                attribution_layer=layer,
            ),
            attr,
        )

    if oracle_grounding_and_explore_flips:
        attr = OracleAttribution(
            layer=AttributionLayer.L3_EXPLORATION,
            grounding_gap=False,
            exploration_gap=True,
            detail="oracle_explore_flips",
        )
        return (
            EpisodeScore(
                success=base.success,
                spl=base.spl,
                distance_to_goal_m=base.distance_to_goal_m,
                time_to_goal_s=base.time_to_goal_s,
                failure=base.failure,
                detail=base.detail,
                oracle_success=True,
                oracle_sr_gap=1.0,
                attribution_layer=AttributionLayer.L3_EXPLORATION,
            ),
            attr,
        )

    # Neither oracle flip succeeds — map failure class to layer (not everything → L6).
    if base.failure == FailureClass.GROUNDING_ERROR:
        detail_text = str(base.detail).lower()
        layer = (
            AttributionLayer.L2A_VOCABULARY
            if "vocab" in detail_text or "unknown_label" in detail_text
            else AttributionLayer.L2B_VISIBILITY
        )
    elif base.failure == FailureClass.SEARCH_ERROR:
        layer = AttributionLayer.L3_EXPLORATION
    elif base.failure == FailureClass.PLANNING_ERROR:
        layer = AttributionLayer.L4_PLANNING
    elif base.failure == FailureClass.CONTROL_ERROR:
        layer = AttributionLayer.L5_CONTROL
    elif base.failure == FailureClass.REFUSAL:
        layer = AttributionLayer.L1_PARSE
    else:
        layer = AttributionLayer.L6_TERMINATION
    attr = OracleAttribution(
        layer=layer,
        grounding_gap=False,
        exploration_gap=False,
        detail="oracle_no_flip",
    )
    return (
        EpisodeScore(
            success=base.success,
            spl=base.spl,
            distance_to_goal_m=base.distance_to_goal_m,
            time_to_goal_s=base.time_to_goal_s,
            failure=base.failure,
            detail=base.detail,
            oracle_success=False,
            oracle_sr_gap=0.0,
            attribution_layer=layer,
        ),
        attr,
    )


def _classify_failure(
    trace: Sequence[Mapping[str, object]],
    goal: GoalRegion,
    anchor_xy: tuple[float, float] | None,
) -> FailureClass:
    """Precedence: refusal → grounding → search → planning → control."""

    texts = " ".join(_event_text(step) for step in trace).lower()
    flags = _collect_flags(trace)

    if flags["refusal"] or "couldn't form" in texts or "could not form" in texts:
        return FailureClass.REFUSAL
    if flags["grounding_error"] or flags["ambiguous"] or "unknown_label" in texts:
        return FailureClass.GROUNDING_ERROR
    if flags["search_error"] or flags["not_found"] or "semantic_target_not_found" in texts:
        return FailureClass.SEARCH_ERROR
    if flags["planning_error"] or flags["unreachable"] or "no_route" in texts:
        return FailureClass.PLANNING_ERROR
    if flags["collision"] or flags["control_error"] or "collision" in texts:
        return FailureClass.CONTROL_ERROR

    # Reached vicinity but never held stop → control/termination bucket.
    final = trace[-1]
    fx, fy = _xy(final)
    if goal.contains(fx, fy, anchor_xy=anchor_xy) and not _stopped(final):
        return FailureClass.CONTROL_ERROR
    if flags["attempted"]:
        return FailureClass.PLANNING_ERROR
    return FailureClass.REFUSAL


def _collect_flags(trace: Sequence[Mapping[str, object]]) -> dict[str, bool]:
    keys = (
        "refusal",
        "grounding_error",
        "search_error",
        "planning_error",
        "control_error",
        "collision",
        "not_found",
        "unreachable",
        "ambiguous",
        "attempted",
    )
    out = {key: False for key in keys}
    search_attempted = False
    unseen_or_not_found = False
    for step in trace:
        for key in keys:
            if bool(step.get(key)):
                out[key] = True
        failure = str(step.get("failure") or step.get("failure_class") or "").lower()
        if failure in out:
            out[failure] = True
        state = str(step.get("resolution_state") or step.get("grounding_outcome") or "").lower()
        if state in {"not_found", "unseen"}:
            unseen_or_not_found = True
            out["not_found"] = True
        if state in {"unreachable"}:
            out["planning_error"] = True
            out["unreachable"] = True
        if state in {"ambiguous", "grounding_error"}:
            out["grounding_error"] = True
            out["ambiguous"] = True
        if state in {"resolved", "memory_hit", "searching"}:
            out["attempted"] = True
        if state == "searching":
            search_attempted = True
        note = str(step.get("note") or "").lower()
        if "semantic_search" in note or "frontier" in note or "scan" in note:
            out["attempted"] = True
            search_attempted = True
        if bool(step.get("collision")) or note.endswith("_collision"):
            out["collision"] = True
            out["control_error"] = True
        reply = str(step.get("reply") or step.get("agent_reply") or "").lower()
        if "couldn't form" in reply or "could not form" in reply:
            out["refusal"] = True
        if "looked around" in reply and "couldn't find" in reply:
            search_attempted = True
            out["search_error"] = True
            out["not_found"] = True
        if "searched nearby" in reply:
            search_attempted = True
    # UNSEEN/not_found is grounding unless a search recovery was actually tried.
    if unseen_or_not_found and not out["search_error"]:
        if search_attempted:
            out["search_error"] = True
        else:
            out["grounding_error"] = True
    return out


def _ever_inside(
    trace: Sequence[Mapping[str, object]],
    goal: GoalRegion,
    *,
    anchor_xy: tuple[float, float] | None,
) -> bool:
    for step in trace:
        x, y = _xy(step)
        if goal.contains(x, y, anchor_xy=anchor_xy):
            return True
    return False


def _arrival_hold(
    trace: Sequence[Mapping[str, object]],
    goal: GoalRegion,
    *,
    arrival_hold_s: float,
    anchor_xy: tuple[float, float] | None,
) -> float | None:
    if arrival_hold_s <= 0.0:
        final = trace[-1]
        fx, fy = _xy(final)
        if goal.contains(fx, fy, anchor_xy=anchor_xy) and _stopped(final):
            return _time_s(final)
        return None

    hold_start: float | None = None
    for step in trace:
        t = _time_s(step)
        x, y = _xy(step)
        inside = goal.contains(x, y, anchor_xy=anchor_xy)
        stopped = _stopped(step)
        if inside and stopped:
            if hold_start is None:
                hold_start = t
            if t - hold_start >= arrival_hold_s - 1e-9:
                return t
        else:
            hold_start = None
    return None


def _path_length(trace: Sequence[Mapping[str, object]]) -> float:
    if "path_length_m" in trace[-1]:
        try:
            value = float(trace[-1]["path_length_m"])  # type: ignore[arg-type]
            if math.isfinite(value) and value >= 0.0:
                return value
        except (TypeError, ValueError):
            pass
    total = 0.0
    prev: tuple[float, float] | None = None
    for step in trace:
        xy = _xy(step)
        if prev is not None:
            total += math.hypot(xy[0] - prev[0], xy[1] - prev[1])
        prev = xy
    return total


def _xy(step: Mapping[str, object]) -> tuple[float, float]:
    if "x" in step and "y" in step:
        return float(step["x"]), float(step["y"])  # type: ignore[arg-type]
    pos = step.get("position") or step.get("xy")
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        return float(pos[0]), float(pos[1])
    return 0.0, 0.0


def _time_s(step: Mapping[str, object]) -> float:
    for key in ("t_s", "time_s", "t"):
        if key in step:
            try:
                value = float(step[key])  # type: ignore[arg-type]
                if math.isfinite(value):
                    return value
            except (TypeError, ValueError):
                continue
    return 0.0


def _stopped(step: Mapping[str, object]) -> bool:
    if "stopped" in step:
        return bool(step["stopped"])
    if "agent_stop" in step:
        return bool(step["agent_stop"])
    speed = step.get("speed_mps")
    if isinstance(speed, (int, float)) and math.isfinite(float(speed)):
        return float(speed) <= 0.05
    vx = step.get("vx")
    vy = step.get("vy")
    if isinstance(vx, (int, float)) and isinstance(vy, (int, float)):
        return math.hypot(float(vx), float(vy)) <= 0.05
    note = str(step.get("note") or "").lower()
    return "stop" in note or bool(step.get("stop"))


def _event_text(step: Mapping[str, object]) -> str:
    parts = [
        str(step.get("note") or ""),
        str(step.get("reply") or ""),
        str(step.get("agent_reply") or ""),
        str(step.get("resolution_state") or ""),
        str(step.get("grounding_outcome") or ""),
    ]
    return " ".join(parts)


def _detail(
    success: bool,
    failure: FailureClass,
    trace: Sequence[Mapping[str, object]],
) -> str:
    if success:
        return "success"
    for step in reversed(trace):
        for key in ("detail", "note", "resolution_state", "grounding_outcome", "reply"):
            value = step.get(key)
            if value:
                return str(value)
    return failure.value


def _layer_for_failure(failure: FailureClass) -> AttributionLayer:
    return {
        FailureClass.REFUSAL: AttributionLayer.L1_PARSE,
        FailureClass.GROUNDING_ERROR: AttributionLayer.L2A_VOCABULARY,
        FailureClass.SEARCH_ERROR: AttributionLayer.L3_EXPLORATION,
        FailureClass.PLANNING_ERROR: AttributionLayer.L4_PLANNING,
        FailureClass.CONTROL_ERROR: AttributionLayer.L5_CONTROL,
        FailureClass.NONE: AttributionLayer.NONE,
    }[failure]


def _finite_xy(point: tuple[float, float]) -> None:
    if not (math.isfinite(point[0]) and math.isfinite(point[1])):
        raise ValueError("coordinates must be finite")


def _point_in_polygon(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


def _distance_to_polygon(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> float:
    if _point_in_polygon(point, polygon):
        return 0.0
    best = float("inf")
    previous = polygon[-1]
    for current in polygon:
        best = min(best, _distance_point_to_segment(point, previous, current))
        previous = current
    return best


def _distance_point_to_segment(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    ax, ay = a
    bx, by = b
    px, py = point
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
