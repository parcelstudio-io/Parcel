"""Crossing / curb policy — hard geofence, voice initiation only.

Binding (ADJUDICATION Owner amendment P3 + Fable G4):
  curb-stop → announcement → owner voice initiation → gated crossing.
  Zero autonomous road entry. Fail-closed. Voice never overrides an
  unconditional proximity/collision gate (callers must still check that).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum

from parcel_robot.maps.graph import CurbRecord, FootwayCrossingGraph

# Phrases that may initiate leaving the curb (companion moment).
VOICE_CROSS_PHRASES = frozenset(
    {
        "go",
        "go ahead",
        "let's go",
        "lets go",
        "cross",
        "cross now",
        "okay go",
        "ok go",
        "ready",
        "we're ready",
        "were ready",
    }
)

DOES_NOT_PROVE = (
    (
        "Sim curb/crossing policy does not prove field curb detection or leashed "
        "course crossing behavior (HR-11)."
    ),
    "Voice initiation unlocks crossing mode only; it never releases a proximity stop.",
)


class CrossingState(str, Enum):
    SIDEWALK = "sidewalk"
    APPROACHING_CURB = "approaching_curb"
    CURB_STOPPED = "curb_stopped"
    CROSSING_AUTHORIZED = "crossing_authorized"
    # Entering road without authorization is always rejected (fail-closed).
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CrossingPolicyConfig:
    curb_approach_radius_m: float = 2.0
    curb_stop_radius_m: float = 0.75
    # How long a voice authorization remains valid (sim ticks / seconds).
    authorization_ttl_s: float = 30.0
    require_announcement: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("curb_approach_radius_m", self.curb_approach_radius_m),
            ("curb_stop_radius_m", self.curb_stop_radius_m),
            ("authorization_ttl_s", self.authorization_ttl_s),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.curb_stop_radius_m > self.curb_approach_radius_m:
            raise ValueError("curb_stop_radius_m must be ≤ curb_approach_radius_m")
        if not isinstance(self.require_announcement, bool):
            raise TypeError("require_announcement must be a boolean")


@dataclass(frozen=True, slots=True)
class CrossingDecision:
    state: CrossingState
    allow_crossing_edges: bool
    stop_required: bool
    announcement: str | None
    reason: str
    curb_id: str | None = None
    autonomous_road_entry_blocked: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "allow_crossing_edges": self.allow_crossing_edges,
            "stop_required": self.stop_required,
            "announcement": self.announcement,
            "reason": self.reason,
            "curb_id": self.curb_id,
            "autonomous_road_entry_blocked": self.autonomous_road_entry_blocked,
        }


@dataclass
class CrossingModePolicy:
    """Stateful curb-stop + voice-initiation gate over a footway graph."""

    graph: FootwayCrossingGraph
    config: CrossingPolicyConfig | None = None
    _state: CrossingState = CrossingState.SIDEWALK
    _active_curb_id: str | None = None
    _announced: bool = False
    _authorized_until_s: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.graph, FootwayCrossingGraph):
            raise TypeError("graph must be FootwayCrossingGraph")
        if self.config is None:
            self.config = CrossingPolicyConfig()
        elif not isinstance(self.config, CrossingPolicyConfig):
            raise TypeError("config must be CrossingPolicyConfig")

    @property
    def state(self) -> CrossingState:
        return self._state

    @property
    def active_curb_id(self) -> str | None:
        return self._active_curb_id

    def reset(self) -> None:
        self._state = CrossingState.SIDEWALK
        self._active_curb_id = None
        self._announced = False
        self._authorized_until_s = None

    def parse_voice_initiation(self, transcript: str) -> bool:
        """Return True when transcript is an accepted curb-leave phrase."""

        if not isinstance(transcript, str):
            raise TypeError("transcript must be a string")
        clean = " ".join(transcript.strip().lower().split())
        return clean in VOICE_CROSS_PHRASES

    def request_voice_initiation(self, transcript: str, *, now_s: float) -> bool:
        """Authorize crossing only from CURB_STOPPED + accepted phrase.

        Fail-closed: wrong state, unknown phrase, or expired context → False.
        """

        if not isinstance(now_s, (int, float)) or isinstance(now_s, bool):
            raise TypeError("now_s must be numeric")
        if not math.isfinite(float(now_s)):
            raise ValueError("now_s must be finite")
        assert self.config is not None
        if self._state is not CrossingState.CURB_STOPPED:
            return False
        if self.config.require_announcement and not self._announced:
            return False
        if not self.parse_voice_initiation(transcript):
            return False
        self._state = CrossingState.CROSSING_AUTHORIZED
        self._authorized_until_s = float(now_s) + self.config.authorization_ttl_s
        return True

    def nearest_curb(
        self, x: float, y: float
    ) -> tuple[CurbRecord, float] | None:
        best: tuple[CurbRecord, float] | None = None
        for curb in self.graph.curbs.values():
            node = self.graph.nodes[curb.node_id]
            d = math.hypot(node.x - x, node.y - y)
            if best is None or d < best[1]:
                best = (curb, d)
        return best

    def evaluate(
        self,
        *,
        robot_x: float,
        robot_y: float,
        now_s: float,
        proposed_goal_xy: tuple[float, float] | None = None,
    ) -> CrossingDecision:
        """Advance curb state and gate road entry / crossing edges."""

        for name, value in (("robot_x", robot_x), ("robot_y", robot_y), ("now_s", now_s)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        assert self.config is not None
        cfg = self.config

        # Expire authorization.
        if (
            self._state is CrossingState.CROSSING_AUTHORIZED
            and self._authorized_until_s is not None
            and float(now_s) > self._authorized_until_s
        ):
            self._state = CrossingState.CURB_STOPPED
            self._authorized_until_s = None

        # Hard geofence: autonomous (or any) pose already in road without auth.
        in_road = self.graph.is_road_keepout(robot_x, robot_y)
        if in_road and self._state is not CrossingState.CROSSING_AUTHORIZED:
            self._state = CrossingState.BLOCKED
            return CrossingDecision(
                state=CrossingState.BLOCKED,
                allow_crossing_edges=False,
                stop_required=True,
                announcement=None,
                reason="autonomous_road_entry_blocked",
                curb_id=self._active_curb_id,
                autonomous_road_entry_blocked=True,
            )

        # Proposed goal into road without authorization → veto.
        if proposed_goal_xy is not None:
            gx, gy = proposed_goal_xy
            if self.graph.is_road_keepout(gx, gy) and self._state is not (
                CrossingState.CROSSING_AUTHORIZED
            ):
                return CrossingDecision(
                    state=self._state,
                    allow_crossing_edges=False,
                    stop_required=self._state
                    in (CrossingState.CURB_STOPPED, CrossingState.APPROACHING_CURB),
                    announcement=None,
                    reason="goal_in_road_keepout_without_voice",
                    curb_id=self._active_curb_id,
                    autonomous_road_entry_blocked=True,
                )

        nearest = self.nearest_curb(robot_x, robot_y)
        if nearest is None:
            self._state = CrossingState.SIDEWALK
            self._active_curb_id = None
            self._announced = False
            return CrossingDecision(
                state=CrossingState.SIDEWALK,
                allow_crossing_edges=False,
                stop_required=False,
                announcement=None,
                reason="no_curb_in_graph",
                autonomous_road_entry_blocked=True,
            )

        curb, distance = nearest
        if self._state is CrossingState.CROSSING_AUTHORIZED:
            # Cleared far from curb / road → return to sidewalk.
            if not in_road and distance > cfg.curb_approach_radius_m:
                self.reset()
                return CrossingDecision(
                    state=CrossingState.SIDEWALK,
                    allow_crossing_edges=False,
                    stop_required=False,
                    announcement=None,
                    reason="crossing_complete",
                    autonomous_road_entry_blocked=True,
                )
            return CrossingDecision(
                state=CrossingState.CROSSING_AUTHORIZED,
                allow_crossing_edges=True,
                stop_required=False,
                announcement=None,
                reason="voice_authorized_crossing",
                curb_id=curb.id,
                autonomous_road_entry_blocked=False,
            )

        if distance <= cfg.curb_stop_radius_m:
            self._state = CrossingState.CURB_STOPPED
            self._active_curb_id = curb.id
            announcement = None
            if not self._announced:
                announcement = curb.announcement
                self._announced = True
            return CrossingDecision(
                state=CrossingState.CURB_STOPPED,
                allow_crossing_edges=False,
                stop_required=True,
                announcement=announcement,
                reason="curb_stop_awaiting_voice",
                curb_id=curb.id,
                autonomous_road_entry_blocked=True,
            )

        if distance <= cfg.curb_approach_radius_m:
            self._state = CrossingState.APPROACHING_CURB
            self._active_curb_id = curb.id
            return CrossingDecision(
                state=CrossingState.APPROACHING_CURB,
                allow_crossing_edges=False,
                stop_required=False,
                announcement=None,
                reason="approaching_curb",
                curb_id=curb.id,
                autonomous_road_entry_blocked=True,
            )

        # Away from curb.
        if self._state is not CrossingState.SIDEWALK:
            self.reset()
        return CrossingDecision(
            state=CrossingState.SIDEWALK,
            allow_crossing_edges=False,
            stop_required=False,
            announcement=None,
            reason="on_sidewalk",
            autonomous_road_entry_blocked=True,
        )

    def may_enter_road(self) -> bool:
        return self._state is CrossingState.CROSSING_AUTHORIZED

    def allow_crossing_edges(self) -> bool:
        return self._state is CrossingState.CROSSING_AUTHORIZED

    def with_config(self, **kwargs: object) -> CrossingModePolicy:
        assert self.config is not None
        return CrossingModePolicy(
            graph=self.graph,
            config=replace(self.config, **kwargs),
        )


def decision_blocks_autonomous_road(decision: CrossingDecision) -> bool:
    """Test helper / gate: True when road entry must be refused."""

    return bool(decision.autonomous_road_entry_blocked) and not decision.allow_crossing_edges


def summarize_policy(policy: CrossingModePolicy) -> Mapping[str, object]:
    return {
        "state": policy.state.value,
        "active_curb_id": policy.active_curb_id,
        "may_enter_road": policy.may_enter_road(),
        "fixture_id": policy.graph.fixture_id,
    }
