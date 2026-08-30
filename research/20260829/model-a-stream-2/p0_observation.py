"""Causal, allow-listed observation adapter for MA-2-P0.

This module accepts only serialized adapter products. It deliberately has no
import path to the simulation implementation or evaluation predicates.
"""

from __future__ import annotations

from typing import Any

from p0_contracts import canonical_bytes, validate_policy_payload

SENSOR_PACKET_KEYS = frozenset(
    {
        "observed_at_ns",
        "pose_estimate",
        "velocity_estimate",
        "sector_ranges_m",
        "semantic_candidates",
        "localization_covariance",
    }
)
MISSION_KEYS = frozenset(
    {
        "task_id",
        "revision",
        "step_id",
        "attempt",
        "target_ref",
        "parent_task_id",
        "queued_task_ids",
    }
)


def build_policy_payload(
    *,
    sequence: int,
    monotonic_ns: int,
    boot_epoch: str,
    sensor_packet: dict[str, Any],
    mission: dict[str, Any],
    accepted_steering: dict[str, Any] | None,
    previous_applied: dict[str, float],
    previous_gate_disposition: str,
    accepted_history: list[dict[str, Any]],
) -> dict[str, Any]:
    if set(sensor_packet) != SENSOR_PACKET_KEYS:
        raise ValueError("sensor adapter packet has unexpected or missing fields")
    if set(mission) != MISSION_KEYS:
        raise ValueError("mission adapter packet has unexpected or missing fields")
    observed_at = int(sensor_packet["observed_at_ns"])
    if observed_at > monotonic_ns:
        raise ValueError("sensor packet comes from the future")
    pose = sensor_packet["pose_estimate"]
    velocity = sensor_packet["velocity_estimate"]
    payload = {
        "schema_version": 1,
        "header": {
            "boot_epoch": boot_epoch,
            "sequence": sequence,
            "monotonic_ns": monotonic_ns,
        },
        "freshness": {
            "observed_at_ns": observed_at,
            "age_ms": (monotonic_ns - observed_at) / 1_000_000.0,
            "missing": False,
            "stale": monotonic_ns - observed_at > 200_000_000,
        },
        "robot_estimate": {
            "x_m": float(pose["x_m"]),
            "y_m": float(pose["y_m"]),
            "yaw_rad": float(pose["yaw_rad"]),
            "covariance": [float(v) for v in sensor_packet["localization_covariance"]],
            "vx_mps": float(velocity["vx_mps"]),
            "vy_mps": float(velocity["vy_mps"]),
            "stopped": abs(float(velocity["vx_mps"])) < 0.03
            and abs(float(velocity["vy_mps"])) < 0.03,
        },
        "local_world": {
            "sector_ranges_m": [float(v) for v in sensor_packet["sector_ranges_m"]],
            "occupancy_source": "lidar_adapter_v1",
        },
        "mission": dict(mission),
        "path": {
            "committed_prefix_frames": 0,
            "prefix_end_sequence": sequence - 1,
            "accepted_route_generation": int(mission["revision"]),
        },
        "dialogue": {
            "accepted_steering": accepted_steering,
            "owner_speaking": False,
            "stop_latch": False,
        },
        "safety": {
            "health": "ok",
            "capability_digest": "p0-kinematic-no-authority",
            "previous_gate_disposition": previous_gate_disposition,
        },
        "history": {
            "previous_applied": dict(previous_applied),
            "accepted_events_2_to_60_s": [dict(row) for row in accepted_history[-32:]],
        },
        "semantic_map": {
            "source": "semantic_map_estimator_v1",
            "candidates": [dict(row) for row in sensor_packet["semantic_candidates"]],
        },
    }
    validate_policy_payload(payload)
    # Canonical serialization is part of the adapter boundary, not an optional
    # report-time conversion.
    canonical_bytes(payload)
    return payload
