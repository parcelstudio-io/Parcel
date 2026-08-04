"""S3: typed channel details round-trip the runtime literal shapes."""

from __future__ import annotations

from parcel_robot.core.details import (
    FollowDetail,
    NavigationDetail,
    SpatialDetail,
    VoiceDetail,
)

# Goldens copied from runtime.py / controller idle snapshots (2026-08-04).
NAVIGATION_GOLDEN = {
    "enabled": False,
    "state": "idle",
    "directive": None,
    "goal": None,
    "reason": "navigation_disabled",
}

VOICE_GOLDEN = {
    "mode": "text",
    "status": "idle",
    "partial": "",
    "last_turn_id": None,
    "last_transcript": "",
    "last_reply": "",
    "superseded": False,
}

SPATIAL_IDLE_GOLDEN = {
    "enabled": False,
    "state": "idle",
    "intent": None,
    "target_distance_m": None,
    "orbit_radius_m": None,
    "progress": 0.0,
}

FOLLOW_IDLE_GOLDEN = {
    "enabled": False,
    "state": "idle",
    "mode": "direct",
    "desired_distance_m": 1.6,
    "heading_available": False,
    "owner_heading_rad": None,
    "owner_speed_mps": None,
    "heading_track_status": "not_observed",
    "stage_side": None,
    "perception_basis": "camera_owner_track+robot_odometry+lidar",
    "prediction": {
        "enabled": False,
        "active": False,
        "reason": "idle",
        "confidence": None,
        "lead_x_m": None,
        "lead_y_m": None,
        "speed_scale": 1.0,
    },
}


def test_navigation_as_dict_matches_runtime_literal() -> None:
    detail = NavigationDetail()
    assert detail.as_dict() == NAVIGATION_GOLDEN
    assert NavigationDetail.from_dict(NAVIGATION_GOLDEN).as_dict() == NAVIGATION_GOLDEN


def test_voice_as_dict_matches_runtime_literal() -> None:
    detail = VoiceDetail()
    assert detail.as_dict() == VOICE_GOLDEN
    assert VoiceDetail.from_dict(VOICE_GOLDEN).as_dict() == VOICE_GOLDEN


def test_spatial_as_dict_matches_idle_snapshot_shape() -> None:
    detail = SpatialDetail()
    assert detail.as_dict() == SPATIAL_IDLE_GOLDEN
    assert SpatialDetail.from_dict(SPATIAL_IDLE_GOLDEN).as_dict() == SPATIAL_IDLE_GOLDEN


def test_spatial_cancelled_reason_preserved() -> None:
    cancelled = {
        **SPATIAL_IDLE_GOLDEN,
        "enabled": False,
        "state": "cancelled",
        "reason": "manual_control",
    }
    assert SpatialDetail.from_dict(cancelled).as_dict() == cancelled


def test_follow_as_dict_matches_idle_snapshot_shape() -> None:
    detail = FollowDetail()
    assert detail.as_dict() == FOLLOW_IDLE_GOLDEN
    assert FollowDetail.from_dict(FOLLOW_IDLE_GOLDEN).as_dict() == FOLLOW_IDLE_GOLDEN


def test_replace_convenience() -> None:
    nav = NavigationDetail().replace(enabled=True, state="running", directive="kitchen")
    assert nav.enabled is True
    assert nav.directive == "kitchen"
