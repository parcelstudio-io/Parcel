from __future__ import annotations

import math
from dataclasses import dataclass, field

from parcel_robot.instructnav.relations import nearest_point_in_region

from .attributes import filter_candidates_by_attributes
from .base import MAP_FRAME, MidLevelCommand, NavObservation, pose_in
from .goals import SemanticGoal
from .semantic_map import SemanticCandidate, SemanticMap


@dataclass
class ActiveSemanticSearch:
    max_steps: int = 80
    yaw_rate: float = 0.35
    _steps: int = 0
    _seen: dict[str, int] = field(default_factory=dict)
    _confirmed: dict[str, SemanticCandidate] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 1 <= self.max_steps <= 10_000:
            raise ValueError("semantic search max_steps must be between 1 and 10000")
        if not 0.05 <= self.yaw_rate <= 1.5:
            raise ValueError("semantic search yaw_rate must be between 0.05 and 1.5")

    def reset(self) -> None:
        self._steps = 0
        self._seen.clear()
        self._confirmed = {}

    def observe(
        self,
        goal: SemanticGoal,
        semantic_map: SemanticMap,
        observation: NavObservation,
    ) -> SemanticCandidate | MidLevelCommand:
        self._steps += 1
        candidates = semantic_map.query(goal, observation)
        # Multi-view confirmation is a second selection point, so the attribute
        # has to hold here too — otherwise "the big tree" would be confirmed by
        # whichever tree happened to be observed twice first.
        attributes = tuple(getattr(goal, "attributes", ()) or ())
        if attributes:
            candidates = list(filter_candidates_by_attributes(candidates, attributes).kept)
        # Interchangeable (stuff-class / explicit "nearest") goals must not be
        # won by whichever instance confirms first: which sidewalk is nearest
        # is only answerable after the sweep, and first-confirmed made the
        # answer depend on sweep direction (arbitration 2026-08-07,
        # region-instance selection — same rule as the ScanBehavior path).
        interchangeable = goal.kind == "region" or (
            getattr(goal, "superlative", None) == "nearest"
        )
        qualified: list[SemanticCandidate] = []
        confirmed: list[SemanticCandidate] = []
        for candidate in candidates:
            if candidate.confidence < goal.minimum_confidence or not candidate.reachable:
                continue
            qualified.append(candidate)
            self._seen[candidate.candidate_id] = self._seen.get(candidate.candidate_id, 0) + 1
            self._confirmed[candidate.candidate_id] = candidate
            if self._seen[candidate.candidate_id] >= goal.required_observations:
                if not interchangeable:
                    return candidate
                confirmed.append(candidate)
        if interchangeable and len(qualified) >= 2 and len(confirmed) == len(qualified):
            # A comparative choice exists in ONE view: nearest-of-visible is
            # well-defined and sweep-direction-independent — commit it. Only
            # a lone visible instance forces the full look-around below.
            #
            # ``len(confirmed) == len(qualified)``, not merely ``confirmed``
            # (REGION_INSTANCE_STATUS.md residual 1, 2026-08-07): minimising
            # over the confirmed subset while a *nearer* qualified instance is
            # still one sighting short of ``required_observations`` commits the
            # first-confirmed one — first-confirmed-wins in the exact case
            # ruling 2 outlaws. It cannot fire when both instances enter the
            # frustum on the same tick, because then their sighting counts
            # advance together, which is why no case in the suite caught it.
            # Waiting for every *visible* qualified instance keeps the branch's
            # whole point (a comparison inside one view) and costs at most the
            # remaining sightings, still bounded by the sweep below.
            # MAP: candidate polygons are world-frame semantics, so "which one
            # is nearest" is a MAP-frame question (stratum-1 pose seam).
            robot_xy = pose_in(observation, MAP_FRAME).xy
            return min(
                confirmed,
                key=lambda c: (
                    _region_boundary_distance_m(c, robot_xy),
                    c.candidate_id,
                ),
            )
        sweep_complete = self._steps >= self.max_steps
        if interchangeable and not sweep_complete:
            # "Look-around complete" is whichever comes first: the search
            # budget, or one revolution at yaw_rate on the 10 Hz tick.
            # MEASURED at the shipping values (max_steps 80, yaw_rate 0.35,
            # configs/navigation/default.yaml semantic_search): the BUDGET
            # always binds first — 80 ticks is 8.0 s and 2.8 rad = 160 deg of
            # body rotation, not a full turn, which needs 180 ticks. So the
            # sweep is a bounded look-around, not a guaranteed revolution, and
            # it costs 8 s per lone-visible interchangeable goal. The
            # revolution term is live only for a configuration that turns at
            # >= 2*pi/(0.1*max_steps) rad/s (>= 0.79 rad/s at max_steps 80).
            sweep_complete = self._steps * self.yaw_rate * 0.1 >= 2.0 * math.pi
        if interchangeable and sweep_complete:
            pool = [
                item
                for cid, item in self._confirmed.items()
                if self._seen.get(cid, 0) >= goal.required_observations
            ]
            if pool:
                # MAP, same reason as the in-view branch above.
                robot_xy = pose_in(observation, MAP_FRAME).xy
                return min(
                    pool,
                    key=lambda c: (
                        _region_boundary_distance_m(c, robot_xy),
                        c.candidate_id,
                    ),
                )
        if self._steps >= self.max_steps:
            return MidLevelCommand(stop=True, note="semantic_target_not_found")
        return MidLevelCommand(vx=0.0, vy=0.0, vyaw=self.yaw_rate, note="semantic_search_scan")


def _region_boundary_distance_m(
    candidate: SemanticCandidate, robot_xy: tuple[float, float]
) -> float:
    polygon = getattr(candidate, "polygon", None)
    if polygon and len(polygon) >= 3:
        try:
            nearest = nearest_point_in_region(polygon, robot_xy, inset_m=0.0)
        except ValueError:
            pass
        else:
            return math.hypot(nearest[0] - robot_xy[0], nearest[1] - robot_xy[1])
    return math.hypot(candidate.x - robot_xy[0], candidate.y - robot_xy[1])
