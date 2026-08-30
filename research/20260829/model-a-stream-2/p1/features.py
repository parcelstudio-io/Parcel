"""Strict causal feature extraction for the MA-2-P1 Head-1 challenger."""

from __future__ import annotations

import math
from collections import deque
from typing import Any

import numpy as np

FEATURE_NAMES = (
    "target_dx_m",
    "target_dy_m",
    "robot_vx_mps",
    "robot_vy_mps",
    "robot_yaw_rad",
    "robot_stopped",
    "cov_0",
    "cov_1",
    "cov_2",
    "cov_3",
    "range_0",
    "range_1",
    "range_2",
    "range_3",
    "range_4",
    "range_5",
    "range_6",
    "range_7",
    "freshness_age_s",
    "freshness_stale",
    "freshness_missing",
    "previous_vx",
    "previous_vy",
    "previous_vyaw",
    "gate_initial",
    "gate_admit",
    "gate_boundary_stop",
    "revision_scaled",
    "attempt_scaled",
    "parent_present",
    "queued_count_scaled",
    "accepted_event_age_s",
    "accepted_event_present",
)
BASE_DIM = len(FEATURE_NAMES)
SEQUENCE_DIM = BASE_DIM + 1
HISTORY_FRAMES = 16
POLICY_KEYS = frozenset(
    {
        "schema_version",
        "header",
        "freshness",
        "robot_estimate",
        "local_world",
        "mission",
        "path",
        "dialogue",
        "safety",
        "history",
        "semantic_map",
    }
)
FORBIDDEN_FRAGMENTS = (
    "truth",
    "oracle",
    "scorer",
    "actual_pose",
    "distance_to_goal",
    "inside_region",
    "collision_clearance",
    "future",
    "gold",
    "teacher_status",
)
GATE_VALUES = ("initial", "admit", "boundary_stop")


def _walk_keys(value: object, prefix: str = "") -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            values.append(path)
            values.extend(_walk_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            values.extend(_walk_keys(child, f"{prefix}[{index}]"))
    return values


def extract_frame(payload: dict[str, Any]) -> np.ndarray:
    if set(payload) != POLICY_KEYS or payload.get("schema_version") != 1:
        raise ValueError("P1 feature input is not the exact policy payload")
    lowered = [value.lower() for value in _walk_keys(payload)]
    for fragment in FORBIDDEN_FRAGMENTS:
        if any(fragment in value for value in lowered):
            raise ValueError(f"forbidden feature source: {fragment}")
    now_ns = int(payload["header"]["monotonic_ns"])
    observed_ns = int(payload["freshness"]["observed_at_ns"])
    if observed_ns > now_ns:
        raise ValueError("future observation")
    target_ref = payload["mission"]["target_ref"]
    candidates = payload["semantic_map"]["candidates"]
    matches = [row for row in candidates if row["entity_uuid"] == target_ref]
    if len(matches) != 1:
        raise ValueError("target pointer must resolve once")
    target = matches[0]
    robot = payload["robot_estimate"]
    covariance = robot["covariance"]
    ranges = payload["local_world"]["sector_ranges_m"]
    if len(covariance) != 4 or len(ranges) != 8:
        raise ValueError("P1 feature shape mismatch")
    previous = payload["history"]["previous_applied"]
    gate = str(payload["safety"]["previous_gate_disposition"])
    if gate not in GATE_VALUES:
        raise ValueError(f"unknown gate disposition: {gate}")
    steering = payload["dialogue"]["accepted_steering"]
    if steering is None:
        accepted_age = 0.0
        accepted_present = 0.0
    else:
        accepted_at = int(steering["accepted_at_ns"])
        if accepted_at > now_ns:
            # P0's receipt-local owner-resume event can be one nanosecond after
            # the just-applied child frame; it is not visible until the next
            # frame and therefore cannot become a P1 input yet.
            accepted_age = 0.0
            accepted_present = 0.0
        else:
            accepted_age = min((now_ns - accepted_at) / 1_000_000_000.0, 60.0)
            accepted_present = 1.0
    mission = payload["mission"]
    gate_onehot = [float(gate == name) for name in GATE_VALUES]
    values = [
        float(target["relative_x_m"]),
        float(target["relative_y_m"]),
        float(robot["vx_mps"]),
        float(robot["vy_mps"]),
        float(robot["yaw_rad"]),
        float(bool(robot["stopped"])),
        *[float(value) for value in covariance],
        *[min(float(value), 10.0) for value in ranges],
        min(float(payload["freshness"]["age_ms"]) / 1000.0, 10.0),
        float(bool(payload["freshness"]["stale"])),
        float(bool(payload["freshness"]["missing"])),
        float(previous["vx"]),
        float(previous["vy"]),
        float(previous["vyaw"]),
        *gate_onehot,
        min(float(mission["revision"]) / 10.0, 10.0),
        min(float(mission["attempt"]) / 3.0, 1.0),
        float(mission["parent_task_id"] is not None),
        min(len(mission["queued_task_ids"]) / 4.0, 1.0),
        accepted_age,
        accepted_present,
    ]
    if len(values) != BASE_DIM or not all(math.isfinite(value) for value in values):
        raise ValueError("invalid P1 numeric feature vector")
    return np.asarray(values, dtype=np.float32)


def exact_label(row: dict[str, Any]) -> np.ndarray:
    actions = row["actions"]
    if not actions["label_apply_equal"]:
        raise ValueError("P1 refuses a non-applied label")
    if actions["safety_admitted"] != actions["actuator_applied"]:
        raise ValueError("P1 refuses divergent admitted/applied action")
    applied = actions["actuator_applied"]
    return np.asarray([applied["vx"], applied["vy"], applied["vyaw"]], dtype=np.float32)


class CausalWindow:
    def __init__(self, length: int = HISTORY_FRAMES):
        self.length = length
        self._frames: deque[np.ndarray] = deque(maxlen=length)

    def push(self, frame: np.ndarray) -> np.ndarray:
        if frame.shape != (BASE_DIM,):
            raise ValueError("wrong frame feature shape")
        self._frames.append(frame.copy())
        output = np.zeros((self.length, SEQUENCE_DIM), dtype=np.float32)
        start = self.length - len(self._frames)
        for index, value in enumerate(self._frames, start=start):
            output[index, :BASE_DIM] = value
            output[index, BASE_DIM] = 1.0
        return output


def build_episode_arrays(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    window = CausalWindow()
    current: list[np.ndarray] = []
    sequences: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    for expected_frame, row in enumerate(rows):
        if row["frame"] != expected_frame:
            raise ValueError("non-contiguous causal episode")
        frame = extract_frame(row["policy_input"])
        current.append(frame)
        sequences.append(window.push(frame))
        labels.append(exact_label(row))
    return np.stack(current), np.stack(sequences), np.stack(labels)
