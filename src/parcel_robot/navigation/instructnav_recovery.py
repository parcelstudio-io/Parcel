"""Opus K4 wiring: GrounderV2 + ScanBehavior + SearchEntity into navigator recovery.

Pure Sol modules stay import-only. This layer owns step budgets, mid-level
commands, and PlanIR-shaped metadata — not Nav2, teleports, or oracle paths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.instructnav.grounding import GrounderV2, GroundingOutcome, GroundingResult
from parcel_robot.instructnav.memory import RememberedEntity, SemanticMemory2D
from parcel_robot.instructnav.relations import nearest_point_in_region
from parcel_robot.instructnav.scan import (
    ScanPlanSpec,
    ScanRecoveryAction,
    ScanStop,
    full_turn_scan_spec,
    recovery_for_outcome,
    scan_stops,
)
from parcel_robot.instructnav.search_entity import (
    SearchEntityPlanSpec,
    ring_frontier_candidates,
    select_frontier,
    semantic_prior_for_label,
)

from .base import MidLevelCommand, NavObservation
from .semantic_map import SemanticCandidate


@dataclass
class ScanBehaviorController:
    """Rotate-in-place ScanBehavior: dwell at stop yaws, then re-ground.

    Step-budgeted (navigator ticks), not wall-clock. Completing the stop
    sequence means the scan finished — whether the query grounded is the
    caller's job via GrounderV2.
    """

    spec: ScanPlanSpec = field(default_factory=full_turn_scan_spec)
    yaw_gain: float = 1.6
    yaw_limit: float = 0.85
    settle_rad: float = 0.12
    dwell_steps_per_stop: int = 4
    _stops: tuple[ScanStop, ...] = ()
    _stop_index: int = 0
    _dwell_left: int = 0
    _complete: bool = False
    _started: bool = False

    def reset(self) -> None:
        self._stops = ()
        self._stop_index = 0
        self._dwell_left = 0
        self._complete = False
        self._started = False

    def start(self, start_yaw_rad: float, *, spec: ScanPlanSpec | None = None) -> ScanPlanSpec:
        if spec is not None:
            self.spec = spec
        if not math.isfinite(start_yaw_rad):
            raise ValueError("start_yaw_rad must be finite")
        self._stops = scan_stops(float(start_yaw_rad), self.spec)
        self._stop_index = 0
        self._dwell_left = max(1, int(self.dwell_steps_per_stop))
        self._complete = False
        self._started = True
        return self.spec

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def started(self) -> bool:
        return self._started

    def plan_step(self) -> dict[str, object]:
        return self.spec.as_plan_step()

    def step(self, observation: NavObservation) -> MidLevelCommand | None:
        """Return a yaw command, or ``None`` when the full turn is finished."""

        if self._complete:
            return None
        if not self._started:
            yaw = _robot_yaw_rad(observation)
            self.start(yaw)
        if self._stop_index >= len(self._stops):
            self._complete = True
            return None
        stop = self._stops[self._stop_index]
        yaw = _robot_yaw_rad(observation)
        error = _wrap_pi(stop.yaw_rad - yaw)
        if abs(error) > self.settle_rad:
            vyaw = max(-self.yaw_limit, min(self.yaw_limit, self.yaw_gain * error))
            return MidLevelCommand(
                vx=0.0,
                vy=0.0,
                vyaw=vyaw,
                note="scan_behavior_rotate",
            )
        self._dwell_left -= 1
        if self._dwell_left > 0:
            return MidLevelCommand(
                vx=0.0,
                vy=0.0,
                vyaw=0.0,
                note="scan_behavior_dwell",
            )
        self._stop_index += 1
        if self._stop_index >= len(self._stops):
            self._complete = True
            return None
        self._dwell_left = max(1, int(self.dwell_steps_per_stop))
        return MidLevelCommand(
            vx=0.0,
            vy=0.0,
            vyaw=0.0,
            note="scan_behavior_dwell",
        )


def ground_query(
    query: str,
    *,
    frustum: list[SemanticCandidate],
    memory_hits: list[SemanticCandidate] | tuple[RememberedEntity, ...] = (),
    robot_xy: tuple[float, float],
    robot_yaw_rad: float,
    grounder: GrounderV2 | None = None,
    interchangeable: bool = False,
) -> tuple[GroundingResult, SemanticCandidate | None]:
    """Run GrounderV2 and map the top hit back to a SemanticCandidate when possible."""

    active = grounder or GrounderV2()
    detections = [_candidate_as_detection_dict(c, robot_xy) for c in frustum]
    memory_items: list[Any] = []
    for item in memory_hits:
        if isinstance(item, RememberedEntity):
            memory_items.append(item)
        else:
            memory_items.append(_candidate_as_detection_dict(item, robot_xy))
    result = active.ground(
        query,
        detections=detections,
        memory=memory_items,
        robot_xy=robot_xy,
        robot_yaw_rad=robot_yaw_rad,
        interchangeable=interchangeable,
    )
    if result.candidate is None:
        return result, None
    mapped = _match_semantic_candidate(result.candidate, frustum, memory_hits)
    return result, mapped


def recovery_action_for(
    outcome: GroundingOutcome | str,
    *,
    already_scanned: bool,
    already_searched: bool,
) -> ScanRecoveryAction:
    return recovery_for_outcome(
        outcome,
        already_scanned=already_scanned,
        already_searched=already_searched,
    )


def select_search_entity_frontier(
    *,
    origin_xy: tuple[float, float],
    robot_xy: tuple[float, float],
    query_label: str,
    covered: list[tuple[float, float]],
    cover_radius_m: float = 1.5,
    rings: int = 3,
    bearings: int = 12,
    ring_step_m: float = 2.0,
    max_radius_m: float = 12.0,
    travel_weight: float = 0.06,
    coverage_weight: float = 0.45,
) -> tuple[float, float] | None:
    """SearchEntity ring scoring: semantic prior − geodesic (+ coverage novelty)."""

    prior = semantic_prior_for_label(query_label)

    def _covered(xy: tuple[float, float]) -> bool:
        return any(
            math.hypot(xy[0] - cx, xy[1] - cy) <= cover_radius_m for cx, cy in covered
        )

    def geodesic_cost_fn(xy: tuple[float, float]) -> float | None:
        if _covered(xy):
            return None
        return math.hypot(xy[0] - robot_xy[0], xy[1] - robot_xy[1])

    def prior_fn(_xy: tuple[float, float]) -> float:
        return prior

    def coverage_fn(xy: tuple[float, float]) -> float:
        return 0.0 if _covered(xy) else 1.0

    candidates = ring_frontier_candidates(
        origin_xy=origin_xy,
        robot_xy=robot_xy,
        rings=rings,
        bearings=bearings,
        ring_step_m=ring_step_m,
        max_radius_m=max_radius_m,
        geodesic_cost_fn=geodesic_cost_fn,
        prior_fn=prior_fn,
        coverage_fn=coverage_fn,
        label=query_label,
    )
    best = select_frontier(
        candidates,
        travel_weight=travel_weight,
        coverage_weight=coverage_weight,
    )
    if best is None:
        return None
    return (best.x, best.y)


def search_entity_plan_step(query: str, **overrides: Any) -> dict[str, object]:
    spec = SearchEntityPlanSpec(query=query, **overrides)
    return spec.as_plan_step()


def ingest_observation_memory(
    memory: SemanticMemory2D | None,
    observation: NavObservation,
) -> None:
    """Populate SemanticMemory2D from semantic_candidates and DetectionMsg extras."""

    if memory is None:
        return
    now = float(observation.extras.get("time_s") or 0.0)
    if not math.isfinite(now):
        now = 0.0
    robot_x, robot_y = float(observation.position[0]), float(observation.position[1])
    robot_yaw = _robot_yaw_rad(observation)

    raw_dets = observation.extras.get("detections")
    if raw_dets is None:
        raw_dets = observation.extras.get("detection_msgs")
    if isinstance(raw_dets, (list, tuple)) and raw_dets:
        try:
            memory.observe_detections(
                raw_dets,  # type: ignore[arg-type]
                robot_x=robot_x,
                robot_y=robot_y,
                robot_yaw_rad=robot_yaw,
                now_s=now,
            )
        except (TypeError, ValueError):
            pass

    raw = observation.extras.get("semantic_candidates", [])
    if not isinstance(raw, (list, tuple)):
        return
    entities: list[dict[str, object]] = []
    for item in raw[:64]:
        if not isinstance(item, dict):
            continue
        entities.append(
            {
                "id": item.get("id"),
                "label": item.get("label"),
                "kind": item.get("kind", "object"),
                "position": item.get("position")
                or item.get("centroid")
                or (
                    [
                        sum(float(p[0]) for p in (item.get("polygon") or []))
                        / max(len(item.get("polygon") or []), 1),
                        sum(float(p[1]) for p in (item.get("polygon") or []))
                        / max(len(item.get("polygon") or []), 1),
                    ]
                    if item.get("polygon")
                    else None
                ),
                "polygon": item.get("polygon"),
                "confidence": item.get("confidence", 0.98),
                "embedding": item.get("embedding"),
            }
        )
    if entities:
        memory.observe(entities, now_s=now)


def _candidate_as_detection_dict(
    candidate: SemanticCandidate,
    robot_xy: tuple[float, float] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": candidate.candidate_id,
        "label": candidate.label,
        "class_id": candidate.label,
        "x": candidate.x,
        "y": candidate.y,
        "confidence": candidate.confidence,
        "score": candidate.confidence,
        "kind": candidate.kind,
        "polygon": candidate.polygon,
        "source": candidate.source,
    }
    distance = _region_aware_distance_m(candidate, robot_xy)
    if distance is not None:
        payload["distance_m"] = distance
    return payload


def _region_aware_distance_m(
    candidate: SemanticCandidate,
    robot_xy: tuple[float, float] | None,
) -> float | None:
    """Distance to the REGION, not its centroid, for polygon candidates.

    "The sidewalk" means the sidewalk you can step onto soonest: an 16 m
    strip's centroid can sit across the street while its edge is at your
    feet. Arbitration 2026-08-07 (Lane D handoff): nearest tie-breaks for
    stuff-class candidates rank by boundary distance, matching the K0
    polygon authority's own contains/distance semantics. Object candidates
    keep centroid distance (their extent is already band-modelled).
    """

    if robot_xy is None:
        return None
    polygon = candidate.polygon
    if not polygon or len(polygon) < 3:
        return None
    try:
        nearest = nearest_point_in_region(polygon, robot_xy, inset_m=0.0)
    except ValueError:
        return None
    return math.hypot(nearest[0] - robot_xy[0], nearest[1] - robot_xy[1])


def _match_semantic_candidate(
    grounded: dict[str, Any] | Any,
    frustum: list[SemanticCandidate],
    memory_hits: list[SemanticCandidate] | tuple[Any, ...],
) -> SemanticCandidate | None:
    if not isinstance(grounded, dict):
        return None
    cid = str(grounded.get("id") or grounded.get("entity_id") or "")
    pool: list[SemanticCandidate] = list(frustum)
    for item in memory_hits:
        if isinstance(item, SemanticCandidate):
            pool.append(item)
        elif isinstance(item, RememberedEntity):
            pool.append(
                SemanticCandidate(
                    candidate_id=item.entity_id,
                    label=item.label,
                    x=item.x,
                    y=item.y,
                    confidence=item.confidence,
                    kind=item.kind,
                    polygon=item.polygon or (),
                    source="semantic_memory",
                    observed_at=item.last_seen_s,
                    reachable=True,
                    metadata={},
                )
            )
    if cid:
        for candidate in pool:
            if candidate.candidate_id == cid:
                return candidate
    # Fallback: nearest same-label hit.
    label = str(grounded.get("label") or grounded.get("class_id") or "").strip().lower()
    gx = grounded.get("x")
    gy = grounded.get("y")
    if label and gx is not None and gy is not None:
        try:
            tx, ty = float(gx), float(gy)
        except (TypeError, ValueError):
            return None
        same = [c for c in pool if c.label.strip().lower() == label]
        if same:
            return min(same, key=lambda c: math.hypot(c.x - tx, c.y - ty))
        return SemanticCandidate(
            candidate_id=cid or f"grounded:{label}",
            label=label,
            x=tx,
            y=ty,
            confidence=float(grounded.get("confidence", 0.5)),
            kind="object",
            polygon=(),
            source=str(grounded.get("source") or "grounder_v2"),
            observed_at=None,
            reachable=True,
            metadata={},
        )
    return None


def _robot_yaw_rad(observation: NavObservation) -> float:
    if len(observation.position) > 2 and math.isfinite(float(observation.position[2])):
        return float(observation.position[2])
    heading = float(observation.heading_deg)
    if math.isfinite(heading):
        return math.radians(heading)
    return 0.0


def _wrap_pi(yaw: float) -> float:
    return (yaw + math.pi) % (2.0 * math.pi) - math.pi
