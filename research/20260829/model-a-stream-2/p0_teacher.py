"""Observation-only deterministic demonstrator for MA-2-P0."""

from __future__ import annotations

from typing import Any

from p0_contracts import quantize, validate_action, validate_policy_payload


def _clip(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def propose(payload: dict[str, Any]) -> dict[str, float]:
    """Return a requested command from the serialized causal payload only."""

    validate_policy_payload(payload)
    target_ref = payload["mission"]["target_ref"]
    candidates = payload["semantic_map"]["candidates"]
    target = next(row for row in candidates if row["entity_uuid"] == target_ref)
    dx = float(target["relative_x_m"])
    dy = float(target["relative_y_m"])
    if dx * dx + dy * dy <= 0.18 * 0.18:
        requested = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}
    else:
        requested = {
            "vx": quantize(_clip(0.8 * dx, -0.70, 0.70)),
            "vy": quantize(_clip(0.8 * dy, -0.70, 0.70)),
            "vyaw": 0.0,
        }
    return validate_action(requested)


def champion_executive_proposal(
    payload: dict[str, Any], *, operation: str, parent_task_id: str
) -> dict[str, Any]:
    """P0's explicit Head-2 label source; this is not a learned head."""

    validate_policy_payload(payload)
    mission = payload["mission"]
    return {
        "schema_version": 1,
        "proposal": operation,
        "task_id": mission["task_id"],
        "revision": mission["revision"],
        "step_id": mission["step_id"],
        "attempt": mission["attempt"],
        "target": parent_task_id,
        "reason_code": "explicit_owner_resume_after_child_terminal",
        "confidence": 1.0,
        "valid_until_ns": int(payload["header"]["monotonic_ns"]) + 500_000_000,
    }
