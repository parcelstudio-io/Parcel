"""Typed channel-detail dataclasses with JSON-stable ``as_dict()`` shapes.

Shapes are mined from ``runtime.py`` / controller snapshots so panel/tests see
identical JSON after migration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any


def _mapping(data: Mapping[str, object] | None) -> dict[str, object]:
    return dict(data) if data is not None else {}


@dataclass(frozen=True)
class NavigationDetail:
    enabled: bool = False
    state: str = "idle"
    directive: str | None = None
    goal: str | None = None
    reason: str = "navigation_disabled"

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "state": self.state,
            "directive": self.directive,
            "goal": self.goal,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> NavigationDetail:
        return cls(
            enabled=bool(data.get("enabled", False)),
            state=str(data.get("state", "idle")),
            directive=(
                None
                if data.get("directive") is None
                else str(data["directive"])
            ),
            goal=None if data.get("goal") is None else str(data["goal"]),
            reason=str(data.get("reason", "navigation_disabled")),
        )

    def replace(self, **kwargs: Any) -> NavigationDetail:
        return replace(self, **kwargs)


@dataclass(frozen=True)
class SpatialDetail:
    enabled: bool = False
    state: str = "idle"
    intent: Mapping[str, object] | None = None
    target_distance_m: float | None = None
    orbit_radius_m: float | None = None
    progress: float = 0.0
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "enabled": self.enabled,
            "state": self.state,
            "intent": None if self.intent is None else dict(self.intent),
            "target_distance_m": self.target_distance_m,
            "orbit_radius_m": self.orbit_radius_m,
            "progress": self.progress,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> SpatialDetail:
        intent_raw = data.get("intent")
        intent: Mapping[str, object] | None
        if isinstance(intent_raw, Mapping):
            intent = dict(intent_raw)
        else:
            intent = None
        reason_raw = data.get("reason")
        return cls(
            enabled=bool(data.get("enabled", False)),
            state=str(data.get("state", "idle")),
            intent=intent,
            target_distance_m=(
                None
                if data.get("target_distance_m") is None
                else float(data["target_distance_m"])  # type: ignore[arg-type]
            ),
            orbit_radius_m=(
                None
                if data.get("orbit_radius_m") is None
                else float(data["orbit_radius_m"])  # type: ignore[arg-type]
            ),
            progress=float(data.get("progress", 0.0) or 0.0),
            reason=None if reason_raw is None else str(reason_raw),
        )

    def replace(self, **kwargs: Any) -> SpatialDetail:
        return replace(self, **kwargs)


@dataclass(frozen=True)
class FollowPredictionDetail:
    enabled: bool = False
    active: bool = False
    reason: str = "idle"
    confidence: float | None = None
    lead_x_m: float | None = None
    lead_y_m: float | None = None
    speed_scale: float = 1.0

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "active": self.active,
            "reason": self.reason,
            "confidence": self.confidence,
            "lead_x_m": self.lead_x_m,
            "lead_y_m": self.lead_y_m,
            "speed_scale": self.speed_scale,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> FollowPredictionDetail:
        return cls(
            enabled=bool(data.get("enabled", False)),
            active=bool(data.get("active", False)),
            reason=str(data.get("reason", "idle")),
            confidence=(
                None
                if data.get("confidence") is None
                else float(data["confidence"])  # type: ignore[arg-type]
            ),
            lead_x_m=(
                None
                if data.get("lead_x_m") is None
                else float(data["lead_x_m"])  # type: ignore[arg-type]
            ),
            lead_y_m=(
                None
                if data.get("lead_y_m") is None
                else float(data["lead_y_m"])  # type: ignore[arg-type]
            ),
            speed_scale=float(data.get("speed_scale", 1.0) or 1.0),
        )


@dataclass(frozen=True)
class FollowDetail:
    enabled: bool = False
    state: str = "idle"
    mode: str = "direct"
    desired_distance_m: float = 1.6
    heading_available: bool = False
    owner_heading_rad: float | None = None
    owner_speed_mps: float | None = None
    heading_track_status: str = "not_observed"
    stage_side: str | None = None
    perception_basis: str = "camera_owner_track+robot_odometry+lidar"
    prediction: FollowPredictionDetail = field(default_factory=FollowPredictionDetail)

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "state": self.state,
            "mode": self.mode,
            "desired_distance_m": self.desired_distance_m,
            "heading_available": self.heading_available,
            "owner_heading_rad": self.owner_heading_rad,
            "owner_speed_mps": self.owner_speed_mps,
            "heading_track_status": self.heading_track_status,
            "stage_side": self.stage_side,
            "perception_basis": self.perception_basis,
            "prediction": self.prediction.as_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> FollowDetail:
        prediction_raw = data.get("prediction")
        prediction = (
            FollowPredictionDetail.from_dict(prediction_raw)
            if isinstance(prediction_raw, Mapping)
            else FollowPredictionDetail()
        )
        return cls(
            enabled=bool(data.get("enabled", False)),
            state=str(data.get("state", "idle")),
            mode=str(data.get("mode", "direct")),
            desired_distance_m=float(data.get("desired_distance_m", 1.6) or 1.6),
            heading_available=bool(data.get("heading_available", False)),
            owner_heading_rad=(
                None
                if data.get("owner_heading_rad") is None
                else float(data["owner_heading_rad"])  # type: ignore[arg-type]
            ),
            owner_speed_mps=(
                None
                if data.get("owner_speed_mps") is None
                else float(data["owner_speed_mps"])  # type: ignore[arg-type]
            ),
            heading_track_status=str(data.get("heading_track_status", "not_observed")),
            stage_side=(
                None if data.get("stage_side") is None else str(data["stage_side"])
            ),
            perception_basis=str(
                data.get("perception_basis", "camera_owner_track+robot_odometry+lidar")
            ),
            prediction=prediction,
        )

    def replace(self, **kwargs: Any) -> FollowDetail:
        return replace(self, **kwargs)


@dataclass(frozen=True)
class VoiceDetail:
    mode: str = "text"
    status: str = "idle"
    partial: str = ""
    last_turn_id: str | None = None
    last_transcript: str = ""
    last_reply: str = ""
    superseded: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "status": self.status,
            "partial": self.partial,
            "last_turn_id": self.last_turn_id,
            "last_transcript": self.last_transcript,
            "last_reply": self.last_reply,
            "superseded": self.superseded,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> VoiceDetail:
        turn = data.get("last_turn_id")
        return cls(
            mode=str(data.get("mode", "text")),
            status=str(data.get("status", "idle")),
            partial=str(data.get("partial", "") or ""),
            last_turn_id=None if turn is None else str(turn),
            last_transcript=str(data.get("last_transcript", "") or ""),
            last_reply=str(data.get("last_reply", "") or ""),
            superseded=bool(data.get("superseded", False)),
        )

    def replace(self, **kwargs: Any) -> VoiceDetail:
        return replace(self, **kwargs)


__all__ = [
    "FollowDetail",
    "FollowPredictionDetail",
    "NavigationDetail",
    "SpatialDetail",
    "VoiceDetail",
]
