from __future__ import annotations

from dataclasses import dataclass, field

from .base import MidLevelCommand, NavObservation
from .goals import SemanticGoal
from .semantic_map import SemanticCandidate, SemanticMap


@dataclass
class ActiveSemanticSearch:
    max_steps: int = 80
    yaw_rate: float = 0.35
    _steps: int = 0
    _seen: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 1 <= self.max_steps <= 10_000:
            raise ValueError("semantic search max_steps must be between 1 and 10000")
        if not 0.05 <= self.yaw_rate <= 1.5:
            raise ValueError("semantic search yaw_rate must be between 0.05 and 1.5")

    def reset(self) -> None:
        self._steps = 0
        self._seen.clear()

    def observe(
        self,
        goal: SemanticGoal,
        semantic_map: SemanticMap,
        observation: NavObservation,
    ) -> SemanticCandidate | MidLevelCommand:
        self._steps += 1
        candidates = semantic_map.query(goal, observation)
        for candidate in candidates:
            if candidate.confidence < goal.minimum_confidence or not candidate.reachable:
                continue
            self._seen[candidate.candidate_id] = self._seen.get(candidate.candidate_id, 0) + 1
            if self._seen[candidate.candidate_id] >= goal.required_observations:
                return candidate
        if self._steps >= self.max_steps:
            return MidLevelCommand(stop=True, note="semantic_target_not_found")
        return MidLevelCommand(vx=0.0, vy=0.0, vyaw=self.yaw_rate, note="semantic_search_scan")
