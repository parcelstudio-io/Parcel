"""Thin runtime / test hook for Phase-4 route memory (extras-shaped).

Does not wire into RobotRuntime by default — learned proposers stay behind
gates. Tests and optional sim injectors use this seam.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.route_memory.citywalker import CityWalkerInferenceAdapter, CityWalkerResult
from parcel_robot.route_memory.proposer import RouteMemoryProposer
from parcel_robot.route_memory.teach_repeat import TeachRepeatSession

EXTRAS_KEY = "route_memory"

DOES_NOT_PROVE = (
    (
        "RouteMemoryRuntimeHook only publishes extras / proposer snapshots; "
        "it does not enable learned velocity, bypass GoalArbiter, or claim "
        "field route-memory validation (HR-12)."
    ),
)


@dataclass
class RouteMemoryRuntimeHook:
    """Hold a TeachRepeatSession + optional CityWalker adapter for tests/sim."""

    session: TeachRepeatSession = field(default_factory=TeachRepeatSession)
    citywalker: CityWalkerInferenceAdapter | None = None
    active_path_id: str | None = None
    _follower: RouteMemoryProposer | None = field(default=None, init=False, repr=False)

    def teach_poses(self, poses, **kwargs) -> str:
        path = self.session.teach(poses, **kwargs)
        return path.path_id

    def arm_follow(self, path_id: str, *, gate_enabled: bool = False, **kwargs) -> RouteMemoryProposer:
        proposer = self.session.follow(path_id, gate_enabled=gate_enabled, **kwargs)
        self.active_path_id = path_id
        self._follower = proposer
        return proposer

    def propose_route(
        self,
        *,
        now_s: float,
        robot_x: float,
        robot_y: float,
        robot_yaw: float = 0.0,
    ):
        if self._follower is None:
            return None
        return self._follower.propose(
            now_s=now_s,
            robot_x=robot_x,
            robot_y=robot_y,
            robot_yaw=robot_yaw,
        )

    def propose_citywalker(self, observation, *, now_s: float) -> CityWalkerResult | None:
        if self.citywalker is None:
            return None
        return self.citywalker.propose(observation, now_s=now_s)

    def inject_extras(
        self,
        extras: MutableMapping[str, Any],
        *,
        now_s: float,
        snapshot: Mapping[str, Any] | None = None,
    ) -> MutableMapping[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "active_path_id": self.active_path_id,
            "gate_enabled": bool(self._follower.gate_enabled) if self._follower else False,
            "paths": list(self.session.list_paths()),
            "does_not_prove": list(DOES_NOT_PROVE),
            "now_s": float(now_s),
        }
        if self._follower is not None:
            payload["follower"] = self._follower.as_dict()
        if self.citywalker is not None:
            payload["citywalker"] = self.citywalker.availability()
        if snapshot is not None:
            payload["snapshot"] = dict(snapshot)
        extras[EXTRAS_KEY] = payload
        return extras
