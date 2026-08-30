#!/usr/bin/env python3
"""Independent stdlib verifier for DSP-2 result artifacts.

This module deliberately does not import experiment.py and contains no policy
selector. It reconstructs lineage, actor/robot dynamics, semantic phases,
per-tick safety events, episode metrics, aggregates, and hypotheses from the
frozen manifest and result traces.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


ARMS = ("S0", "S1", "S2", "S3")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def q(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def norm(v: tuple[float, float]) -> float:
    return math.hypot(v[0], v[1])


def add(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] + b[0], a[1] + b[1])


def sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] - b[0], a[1] - b[1])


def mul(v: tuple[float, float], scale: float) -> tuple[float, float]:
    return (v[0] * scale, v[1] * scale)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def unit(v: tuple[float, float]) -> tuple[float, float]:
    length = norm(v)
    return (0.0, 0.0) if length < 1e-12 else (v[0] / length, v[1] / length)


def in_intervals(t: float, intervals: list[list[float]]) -> bool:
    return any(float(start) <= t < float(end) for start, end in intervals)


def percentile(values: list[float], proportion: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lo, hi = int(math.floor(position)), int(math.ceil(position))
    if lo == hi:
        return q(ordered[lo])
    frac = position - lo
    return q(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)


def close(a: Any, b: Any, tolerance: float = 2e-5) -> bool:
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tolerance
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y, tolerance) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(close(a[key], b[key], tolerance) for key in a)
    return a == b


class Audit:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def authored_velocity(spec: dict[str, Any], t: float) -> tuple[float, float]:
    velocity = (float(spec["velocity"][0]), float(spec["velocity"][1]))
    for event_t, vx, vy in spec["velocity_events"]:
        if t >= float(event_t):
            velocity = (float(vx), float(vy))
    return velocity


def actor_update(
    states: dict[str, dict[str, Any]], specs: dict[str, dict[str, Any]],
    robot: tuple[float, float], t: float, dt: float,
) -> None:
    for actor_id, state in states.items():
        spec = specs[actor_id]
        start, end = map(float, spec["active_interval_s"])
        active = start <= t < end
        state["active"] = active
        if not active:
            state["vx"] = state["vy"] = 0.0
            continue
        vx, vy = authored_velocity(spec, t)
        if state["responsive"] and state["role"] != "owner":
            rel = (robot[0] - state["x"], robot[1] - state["y"])
            distance = norm(rel)
            if distance < 1.25 and vx * rel[0] + vy * rel[1] > 0.0:
                sign = 1.0 if state["y"] <= robot[1] else -1.0
                vy = clamp(vy + sign * 0.42 * (1.25 - distance) / 1.25, -0.78, 0.78)
                vx *= 0.82
        if state["role"] == "owner":
            vy = clamp((robot[1] + 0.94 - state["y"]) * 0.8, -0.35, 0.35)
        state["vx"], state["vy"] = vx, vy
        state["x"] += vx * dt
        state["y"] += vy * dt


def actor_rows(states: dict[str, dict[str, Any]]) -> list[list[Any]]:
    return [
        [actor_id, q(st["x"]), q(st["y"]), q(st["vx"]), q(st["vy"]),
         st["role"], st["responsive"], st["active"]]
        for actor_id, st in sorted(states.items())
    ]


def move_towards(current: tuple[float, float], target: tuple[float, float], delta: float) -> tuple[float, float]:
    difference = sub(target, current)
    length = norm(difference)
    return target if length <= delta or length < 1e-12 else add(current, mul(difference, delta / length))


def semantic_values(scenario: dict[str, Any], t: float) -> tuple[bool, bool, bool, bool]:
    return (
        in_intervals(t, scenario["authorized_windows_s"]),
        not in_intervals(t, scenario["capacity_full_windows_s"]),
        not in_intervals(t, scenario["door_closed_windows_s"]),
        in_intervals(t, scenario["egress_windows_s"]),
    )


def phase_for(
    scenario: dict[str, Any], robot: tuple[float, float], committed: bool,
    semantics: tuple[bool, bool, bool, bool], fixture: dict[str, Any], t: float,
) -> str:
    authorized, capacity, door_open, egress = semantics
    cfg = fixture["policy"]
    context = scenario["context"]
    if context == "sidewalk":
        return "SIDEWALK"
    if context == "crosswalk":
        if committed or robot[0] >= cfg["crosswalk_entry_x_m"]:
            return "EXITED" if robot[0] >= cfg["crosswalk_exit_x_m"] else "COMMITTED"
        remaining = max(0.0, scenario["authorized_windows_s"][-1][1] - t) if authorized else 0.0
        required = max(0.0, cfg["crosswalk_exit_x_m"] - robot[0]) / fixture["simulation"]["nominal_speed_mps"] + cfg["crosswalk_time_to_clear_margin_s"]
        return "ENTRY_READY" if authorized and remaining >= required else "CURB_WAIT"
    if robot[0] >= cfg["elevator_door_plane_x_m"]:
        return "INSIDE"
    if robot[0] >= cfg["elevator_stage_x_m"] - 0.14:
        return "ENTRY_READY" if capacity and door_open and not egress else "STAGE"
    return "APPROACH"


def rotated(v: tuple[float, float], radians: float) -> tuple[float, float]:
    c, s = math.cos(radians), math.sin(radians)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def actor_hypotheses(track: dict[str, Any], fixture: dict[str, Any]) -> list[tuple[float, float]]:
    velocity = (float(track["vx"]), float(track["vy"]))
    angle = math.radians(float(fixture["policy"]["robust_turn_degrees"]))
    direction = unit(velocity)
    speed = norm(velocity)
    acceleration = float(fixture["policy"]["robust_actor_acceleration_mps2"])
    return [
        velocity, (0.0, 0.0), rotated(velocity, angle), rotated(velocity, -angle),
        mul(direction, max(0.0, speed - acceleration)), mul(direction, speed + acceleration),
    ]


def predicted_clearance(
    robot: tuple[float, float], velocity: tuple[float, float], tracks: list[list[Any]],
    fixture: dict[str, Any], horizon: float, sigma: float,
) -> float:
    sim = fixture["simulation"]
    combined = sim["robot_radius_m"] + sim["person_radius_m"]
    minimum = 9.0
    for row in tracks:
        track = {"x": row[1], "y": row[2], "vx": row[3], "vy": row[4], "variance": row[5], "existence": row[6]}
        if track["existence"] < fixture["sensor"]["track_policy_existence"]:
            continue
        inflation = sigma * math.sqrt(max(0.0, track["variance"]))
        steps = max(1, int(round(horizon / sim["policy_horizon_dt_s"])))
        for actor_v in actor_hypotheses(track, fixture):
            for index in range(steps + 1):
                h = index * sim["policy_horizon_dt_s"]
                rp = add(robot, mul(velocity, h))
                pp = (track["x"] + actor_v[0] * h, track["y"] + actor_v[1] * h)
                minimum = min(minimum, norm(sub(pp, rp)) - combined - inflation)
    return minimum


def inside_corridor(scenario: dict[str, Any], robot: tuple[float, float], velocity: tuple[float, float]) -> bool:
    return abs(robot[1] + velocity[1] * 0.8) <= scenario["corridor_half_width_m"]


def semantic_motion_ok(
    scenario: dict[str, Any], robot: tuple[float, float], proposed: tuple[float, float],
    phase: str, semantics: tuple[bool, bool, bool, bool], fixture: dict[str, Any],
) -> bool:
    authorized, capacity, door, egress = semantics
    if scenario["context"] == "crosswalk" and phase not in {"COMMITTED", "EXITED"}:
        base = phase == "ENTRY_READY" and authorized
    elif scenario["context"] == "elevator" and robot[0] < fixture["policy"]["elevator_door_plane_x_m"]:
        base = capacity and door and not egress
    else:
        base = True
    projected = add(robot, mul(proposed, fixture["simulation"]["final_monitor_horizon_s"]))
    if scenario["context"] == "crosswalk" and phase == "CURB_WAIT":
        base = projected[0] < fixture["policy"]["crosswalk_entry_x_m"]
    if scenario["context"] == "elevator" and not base:
        base = projected[0] < fixture["policy"]["elevator_door_plane_x_m"]
    if phase == "COMMITTED" and proposed[0] < -0.01:
        base = False
    return base


def ttc(
    robot: tuple[float, float], robot_v: tuple[float, float], states: dict[str, dict[str, Any]],
    fixture: dict[str, Any], horizon: float = 5.0,
) -> float:
    combined = fixture["simulation"]["robot_radius_m"] + fixture["simulation"]["person_radius_m"]
    best = horizon
    for st in states.values():
        if not st["active"]:
            continue
        rp = (st["x"] - robot[0], st["y"] - robot[1])
        rv = (st["vx"] - robot_v[0], st["vy"] - robot_v[1])
        speed2 = rv[0] ** 2 + rv[1] ** 2
        if speed2 < 1e-9:
            continue
        closest = clamp(-(rp[0] * rv[0] + rp[1] * rv[1]) / speed2, 0.0, horizon)
        if norm(add(rp, mul(rv, closest))) <= combined + fixture["simulation"]["near_contact_surface_m"]:
            best = min(best, closest)
    return best


def candidate_set(nominal: float) -> list[tuple[float, float]]:
    return [
        (nominal * 0.45, 0.0), (nominal, 0.0), (nominal * 0.72, 0.38),
        (nominal * 0.72, -0.38), (0.0, 0.58), (0.0, -0.58),
        (0.0, 1.0), (0.0, -1.0), (-0.44, 0.0), (-0.28, 0.42), (-0.28, -0.42),
    ]


def truth_clearance(
    scenario: dict[str, Any], robot: tuple[float, float], velocity: tuple[float, float],
    states: dict[str, dict[str, Any]], fixture: dict[str, Any], horizon: float,
) -> float:
    combined = fixture["simulation"]["robot_radius_m"] + fixture["simulation"]["person_radius_m"]
    minimum = 9.0
    steps = max(1, int(round(horizon / 0.1)))
    for index in range(1, steps + 1):
        h = index * horizon / steps
        rp = add(robot, mul(velocity, h))
        if abs(rp[1]) > scenario["corridor_half_width_m"]:
            return -9.0
        for state in states.values():
            if state["active"]:
                pp = (state["x"] + state["vx"] * h, state["y"] + state["vy"] * h)
                minimum = min(minimum, norm(sub(pp, rp)) - combined)
    return minimum


def context_gate(
    scenario: dict[str, Any], robot: tuple[float, float], phase: str,
    semantics: tuple[bool, bool, bool, bool], fixture: dict[str, Any], t: float,
) -> bool:
    authorized, capacity, door, egress = semantics
    if scenario["context"] == "crosswalk" and phase not in {"COMMITTED", "EXITED"}:
        return phase == "ENTRY_READY" and authorized
    if scenario["context"] == "elevator" and robot[0] < fixture["policy"]["elevator_door_plane_x_m"]:
        return capacity and door and not egress
    return True


def oracle_exists(
    scenario: dict[str, Any], robot: tuple[float, float], states: dict[str, dict[str, Any]],
    fixture: dict[str, Any], phase: str, semantics: tuple[bool, bool, bool, bool], t: float,
) -> bool:
    sim = fixture["simulation"]
    nominal = sim["elevator_speed_mps"] if scenario["context"] == "elevator" else sim["nominal_speed_mps"]
    for candidate in candidate_set(nominal):
        projected = add(robot, mul(candidate, sim["oracle_horizon_s"]))
        okay = context_gate(scenario, robot, phase, semantics, fixture, t)
        if scenario["context"] == "crosswalk" and phase == "CURB_WAIT":
            okay = projected[0] < fixture["policy"]["crosswalk_entry_x_m"]
        if scenario["context"] == "elevator" and not okay:
            okay = projected[0] < fixture["policy"]["elevator_door_plane_x_m"]
        if not okay or (phase == "COMMITTED" and candidate[0] < -0.01):
            continue
        if truth_clearance(scenario, robot, candidate, states, fixture, sim["oracle_horizon_s"]) >= sim["hard_surface_floor_m"]:
            return True
    return False


def reconstruct_latency(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    previous_truth = False
    for row in rows:
        truth = bool(row["truth_forward_clear"])
        t = float(row["time_s"])
        if truth and not previous_truth:
            if pending is not None:
                pending["censor_reason"] = "superseded"
                events.append(pending)
            pending = {"truth_clear_s": t, "evidence_clear_s": None, "decision_s": None, "motion_s": None}
        if pending is not None and pending["evidence_clear_s"] is None and row["evidence_clear"]:
            pending["evidence_clear_s"] = t
        if pending is not None and pending["evidence_clear_s"] is not None and pending["decision_s"] is None and norm((row["accepted_vx"], row["accepted_vy"])) > 0.05:
            pending["decision_s"] = t
        if pending is not None and pending["decision_s"] is not None and pending["motion_s"] is None and row["translating"]:
            pending["motion_s"] = t
            events.append(pending)
            pending = None
        if not truth and previous_truth and pending is not None:
            pending["censor_reason"] = "truth_reblocked"
            events.append(pending)
            pending = None
        previous_truth = truth
    if pending is not None:
        pending["censor_reason"] = "episode_end"
        events.append(pending)
    return events


def verify_episode(
    episode: dict[str, Any], scenario: dict[str, Any], fixture: dict[str, Any], audit: Audit,
) -> dict[str, Any]:
    label = episode.get("episode_key", "<missing>")
    fields = episode.get("trace_fields", [])
    audit.require(fields == episode.get("trace_fields"), f"{label}: malformed trace fields")
    audit.require(len(fields) == len(set(fields)), f"{label}: duplicate trace fields")
    field_set = set(fields)
    required = {
        "tick", "time_s", "robot_x_before", "robot_y_before", "vx_before", "vy_before",
        "proposed_vx", "proposed_vy", "accepted_vx", "accepted_vy", "vx_after", "vy_after",
        "robot_x_after", "robot_y_after", "semantic_phase", "authorized", "capacity_available",
        "door_open", "egress_active", "minimum_surface_clearance_m", "actors", "tracks",
        "hard_floor_violation", "hard_envelope_admission", "monitor_intervention",
        "actor_into_stationary_contact", "near_contact", "authorization_violation",
        "reverse_after_entry_violation", "egress_violation", "capacity_violation",
        "door_plane_violation", "staging_violation", "path_increment_m", "translating",
        "oracle_safe_translation", "truth_forward_clear", "evidence_clear", "minimum_ttc_s",
        "contact_within_2s_truth", "forward_margin_m", "evasion_used", "release_on_missing_only",
    }
    audit.require(required <= field_set, f"{label}: missing trace fields {sorted(required - field_set)}")
    index = {name: position for position, name in enumerate(fields)}
    trace = episode.get("trace", [])
    audit.require(sha({"fields": fields, "trace": trace}) == episode.get("trace_sha256"), f"{label}: trace digest mismatch")
    normalized = {key: value for key, value in episode.items() if key != "normalized_sha256"}
    audit.require(sha(normalized) == episode.get("normalized_sha256"), f"{label}: normalized digest mismatch")

    def unpack(raw: list[Any]) -> dict[str, Any]:
        return {name: raw[position] for name, position in index.items()}

    rows = [unpack(raw) for raw in trace]
    sim = fixture["simulation"]
    dt = float(sim["dt_s"])
    specs = {spec["id"]: spec for spec in scenario["actors"]}
    states = {
        actor_id: {
            "x": float(spec["p0"][0]), "y": float(spec["p0"][1]),
            "vx": float(spec["velocity"][0]), "vy": float(spec["velocity"][1]),
            "role": spec["role"], "responsive": bool(spec["responsive"]), "active": False,
        }
        for actor_id, spec in specs.items()
    }
    robot = (float(scenario["start"][0]), float(scenario["start"][1]))
    velocity = (0.0, 0.0)
    committed = False
    previous_phase = ""
    previous_moving = False
    previous_accel = (0.0, 0.0)
    central_wait_run = 0
    path_length = lateral = false_block = wrong_run = max_wrong = 0.0
    transitions = contacts = near = actor_stationary = interventions = hard_admissions = 0
    retreats = evasions = missing_releases = 0
    min_clearance = 9.0
    min_ttc = 5.0
    accelerations: list[float] = []
    jerks: list[float] = []
    semantic_counts = {key: 0 for key in (
        "hard_floor", "authorization", "reverse_after_entry", "egress", "capacity", "door_plane", "staging",
    )}
    risk_labels: list[list[float | int]] = []
    goal_time: float | None = None
    reconstructed: list[dict[str, Any]] = []

    for expected_tick, row in enumerate(rows):
        prefix = f"{label}:tick{expected_tick}"
        audit.require(row["tick"] == expected_tick, f"{prefix}: nonsequential tick")
        t = expected_tick * dt
        audit.require(close(row["time_s"], t), f"{prefix}: time mismatch")
        audit.require(close([row["robot_x_before"], row["robot_y_before"]], list(robot)), f"{prefix}: robot-before mismatch")
        audit.require(close([row["vx_before"], row["vy_before"]], list(velocity)), f"{prefix}: velocity-before mismatch")
        semantics = semantic_values(scenario, t)
        audit.require([row["authorized"], row["capacity_available"], row["door_open"], row["egress_active"]] == list(semantics), f"{prefix}: semantic schedule mismatch")
        if scenario["context"] == "crosswalk" and robot[0] >= fixture["policy"]["crosswalk_entry_x_m"]:
            committed = True
        phase = phase_for(scenario, robot, committed, semantics, fixture, t)
        audit.require(row["semantic_phase"] == phase, f"{prefix}: semantic phase mismatch")
        audit.require(bool(row.get("semantic_phase_changed")) == bool(previous_phase and phase != previous_phase), f"{prefix}: phase-change flag mismatch")

        proposed = (float(row["proposed_vx"]), float(row["proposed_vy"]))
        accepted = (float(row["accepted_vx"]), float(row["accepted_vy"]))
        expected_velocity = move_towards(velocity, accepted, sim["max_acceleration_mps2"] * dt)
        expected_robot = add(robot, mul(expected_velocity, dt))
        audit.require(close([row["vx_after"], row["vy_after"]], list(expected_velocity)), f"{prefix}: acceleration/accepted-action mismatch")
        audit.require(close([row["robot_x_after"], row["robot_y_after"]], list(expected_robot)), f"{prefix}: robot integration mismatch")
        actor_update(states, specs, robot, t, dt)
        audit.require(close(row["actors"], actor_rows(states), 3e-5), f"{prefix}: actor trajectory mismatch")
        track_ids = [track[0] for track in row["tracks"]]
        audit.require(len(track_ids) == len(set(track_ids)), f"{prefix}: duplicate track id")
        audit.require(all(len(track) == 10 and all(math.isfinite(float(track[pos])) for pos in range(1, 7)) for track in row["tracks"]), f"{prefix}: invalid track row")

        full_margin = predicted_clearance(robot, proposed, row["tracks"], fixture, sim["final_monitor_horizon_s"], 1.0)
        full_ok = inside_corridor(scenario, robot, proposed) and semantic_motion_ok(scenario, robot, proposed, phase, semantics, fixture) and full_margin >= sim["hard_surface_floor_m"]
        immediate_prop = predicted_clearance(robot, proposed, row["tracks"], fixture, dt, 0.0)
        immediate_hold = predicted_clearance(robot, (0.0, 0.0), row["tracks"], fixture, dt, 0.0)
        escape_ok = bool(row["evasion_used"] and inside_corridor(scenario, robot, proposed) and semantic_motion_ok(scenario, robot, proposed, phase, semantics, fixture) and immediate_prop >= sim["hard_surface_floor_m"] and immediate_prop >= immediate_hold)
        expected_hard_admission = norm(accepted) > 0.01 and not (full_ok or escape_ok)
        audit.require(bool(row["hard_envelope_admission"]) == expected_hard_admission, f"{prefix}: hard-envelope admission mismatch")
        expected_intervention = norm(proposed) > 0.01 and norm(sub(proposed, accepted)) > 1e-5
        audit.require(bool(row["monitor_intervention"]) == expected_intervention, f"{prefix}: monitor-intervention mismatch")

        combined = sim["robot_radius_m"] + sim["person_radius_m"]
        tick_min, tick_contact, tick_near, tick_actor_stationary = 9.0, False, False, False
        for state in states.values():
            if not state["active"]:
                continue
            clearance = norm((state["x"] - expected_robot[0], state["y"] - expected_robot[1])) - combined
            tick_min = min(tick_min, clearance)
            if clearance < 0.0:
                tick_contact = True
                if norm(expected_velocity) < sim["stationary_speed_mps"] and norm((state["vx"], state["vy"])) > 0.05:
                    tick_actor_stationary = True
            tick_near = tick_near or clearance < sim["near_contact_surface_m"]
        hard_floor = tick_min < sim["hard_surface_floor_m"]
        audit.require(close(row["minimum_surface_clearance_m"], tick_min, 3e-5), f"{prefix}: clearance mismatch")
        audit.require(row["actor_into_stationary_contact"] == tick_actor_stationary, f"{prefix}: actor-into-stationary mismatch")
        audit.require(row["near_contact"] == tick_near, f"{prefix}: near-contact mismatch")
        audit.require(row["hard_floor_violation"] == hard_floor, f"{prefix}: hard-floor mismatch")

        auth_bad = scenario["context"] == "crosswalk" and not semantics[0] and robot[0] < fixture["policy"]["crosswalk_entry_x_m"] <= expected_robot[0]
        reverse_bad = scenario["context"] == "crosswalk" and committed and expected_velocity[0] < -0.01
        crossed_door = scenario["context"] == "elevator" and robot[0] < fixture["policy"]["elevator_door_plane_x_m"] <= expected_robot[0]
        egress_bad, capacity_bad, door_bad = crossed_door and semantics[3], crossed_door and not semantics[1], crossed_door and not semantics[2]
        central = episode["arm"] in {"S2", "S3"} and scenario["context"] == "elevator" and (semantics[3] or not semantics[1] or not semantics[2]) and expected_robot[0] >= fixture["policy"]["elevator_stage_x_m"] - 0.12 and expected_robot[0] < fixture["policy"]["elevator_door_plane_x_m"] and expected_robot[1] > -0.36 and norm(expected_velocity) <= sim["stationary_speed_mps"]
        central_wait_run = central_wait_run + 1 if central else 0
        staging_bad = central_wait_run * dt > 0.6
        semantic_row = {
            "authorization_violation": auth_bad, "reverse_after_entry_violation": reverse_bad,
            "egress_violation": egress_bad, "capacity_violation": capacity_bad,
            "door_plane_violation": door_bad, "staging_violation": staging_bad,
        }
        for key, expected in semantic_row.items():
            audit.require(bool(row[key]) == bool(expected), f"{prefix}: {key} mismatch")

        oracle = oracle_exists(scenario, robot, states, fixture, phase, semantics, t)
        audit.require(row["oracle_safe_translation"] == oracle, f"{prefix}: oracle-safe flag mismatch")
        nominal = sim["elevator_speed_mps"] if scenario["context"] == "elevator" else sim["nominal_speed_mps"]
        truth_forward = truth_clearance(scenario, robot, (nominal, 0.0), states, fixture, sim["oracle_horizon_s"]) >= sim["hard_surface_floor_m"] and context_gate(scenario, robot, phase, semantics, fixture, t)
        audit.require(row["truth_forward_clear"] == truth_forward, f"{prefix}: truth-clear mismatch")
        contact_2s = truth_clearance(scenario, expected_robot, accepted, states, fixture, sim["policy_horizon_s"]) < 0.0
        audit.require(row["contact_within_2s_truth"] == contact_2s, f"{prefix}: two-second contact label mismatch")
        tick_ttc = ttc(expected_robot, expected_velocity, states, fixture)
        audit.require(close(row["minimum_ttc_s"], tick_ttc, 3e-5), f"{prefix}: TTC mismatch")

        moving = norm(expected_velocity) > sim["stationary_speed_mps"]
        if moving != previous_moving:
            transitions += 1
        previous_moving = moving
        path_inc = norm(sub(expected_robot, robot))
        audit.require(close(row["path_increment_m"], path_inc), f"{prefix}: path increment mismatch")
        path_length += path_inc
        lateral += abs(expected_robot[1] - robot[1])
        accel = mul(sub(expected_velocity, velocity), 1.0 / dt)
        accelerations.append(norm(accel))
        jerks.append(norm(mul(sub(accel, previous_accel), 1.0 / dt)))
        previous_accel = accel
        if not moving and oracle:
            false_block += dt
            wrong_run += dt
            max_wrong = max(max_wrong, wrong_run)
        else:
            wrong_run = 0.0
        contacts += int(tick_contact)
        near += int(tick_near)
        actor_stationary += int(tick_actor_stationary)
        interventions += int(row["monitor_intervention"])
        hard_admissions += int(row["hard_envelope_admission"])
        retreats += int(row["retreat_used"])
        evasions += int(row["evasion_used"])
        missing_releases += int(row["release_on_missing_only"])
        min_clearance = min(min_clearance, tick_min)
        min_ttc = min(min_ttc, tick_ttc)
        semantic_counts["hard_floor"] += int(hard_floor)
        for summary_key, trace_key in (
            ("authorization", "authorization_violation"), ("reverse_after_entry", "reverse_after_entry_violation"),
            ("egress", "egress_violation"), ("capacity", "capacity_violation"),
            ("door_plane", "door_plane_violation"), ("staging", "staging_violation"),
        ):
            semantic_counts[summary_key] += int(row[trace_key])
        probability = 1.0 / (1.0 + math.exp(clamp((float(row["forward_margin_m"]) - 0.38) / 0.13, -30.0, 30.0)))
        risk_labels.append([q(probability), int(contact_2s)])
        reconstructed.append(row)
        robot, velocity, previous_phase = expected_robot, expected_velocity, phase
        if goal_time is None and robot[0] >= float(scenario["goal"][0]):
            goal_time = q((expected_tick + 1) * dt)

    latency_events = reconstruct_latency(reconstructed)
    truth_evidence = [float(e["evidence_clear_s"]) - float(e["truth_clear_s"]) for e in latency_events if e["evidence_clear_s"] is not None]
    evidence_decision = [float(e["decision_s"]) - float(e["evidence_clear_s"]) for e in latency_events if e["decision_s"] is not None and e["evidence_clear_s"] is not None]
    decision_motion = [float(e["motion_s"]) - float(e["decision_s"]) for e in latency_events if e["motion_s"] is not None and e["decision_s"] is not None]
    refusal_limit = fixture["policy"]["crosswalk_entry_x_m"] if scenario["context"] == "crosswalk" else fixture["policy"]["elevator_door_plane_x_m"] if scenario["context"] == "elevator" else 0.0
    refusal = bool(scenario["expected_refusal"] and goal_time is None and robot[0] < refusal_limit)
    task_success = goal_time is not None or refusal
    straight = norm(sub(tuple(scenario["goal"]), tuple(scenario["start"])))
    summary = {
        "contact": contacts > 0, "contact_ticks": contacts,
        "near_contact": near > 0, "near_contact_ticks": near,
        "actor_into_stationary_contact": actor_stationary > 0,
        "actor_into_stationary_ticks": actor_stationary,
        "minimum_surface_clearance_m": q(min_clearance),
        "hard_envelope_admissions": hard_admissions,
        "final_monitor_interventions": interventions,
        "semantic_violation_ticks": semantic_counts,
        "goal_reached": goal_time is not None, "goal_time_s": goal_time,
        "correct_refusal": refusal, "task_success": task_success,
        "safety_gate_pass": contacts == 0 and hard_admissions == 0 and sum(semantic_counts.values()) == 0,
        "path_length_m": q(path_length),
        "path_efficiency": q(straight / path_length) if goal_time is not None and path_length > 0 else None,
        "false_block_s": q(false_block), "maximum_false_block_run_s": q(max_wrong),
        "wrong_stall": max_wrong > sim["wrong_stall_s"],
        "deadlock": goal_time is None and false_block >= sim["deadlock_false_block_s"],
        "retreat_used": retreats > 0, "retreat_ticks": retreats,
        "evasion_used": evasions > 0, "evasion_ticks": evasions,
        "release_on_missing_only": missing_releases,
        "stop_start_transitions": transitions,
        "mean_acceleration_mps2": q(statistics.fmean(accelerations)),
        "p95_acceleration_mps2": percentile(accelerations, 0.95),
        "mean_jerk_mps3": q(statistics.fmean(jerks)), "lateral_travel_m": q(lateral),
        "minimum_ttc_s": q(min_ttc), "latency_events": latency_events,
        "latency_opportunities": {
            "truth_clear": len(latency_events),
            "evidence_clear": sum(e["evidence_clear_s"] is not None for e in latency_events),
            "decision": sum(e["decision_s"] is not None for e in latency_events),
            "motion": sum(e["motion_s"] is not None for e in latency_events),
        },
        "truth_to_evidence_s": [q(x) for x in truth_evidence],
        "evidence_to_decision_s": [q(x) for x in evidence_decision],
        "decision_to_motion_s": [q(x) for x in decision_motion], "risk_labels": risk_labels,
    }
    audit.require(close(summary, episode.get("summary"), 5e-5), f"{label}: recomputed episode summary mismatch")
    return summary


def calibration(labels: list[list[float | int]]) -> dict[str, Any]:
    if not labels:
        return {"samples": 0, "positives": 0, "brier": None, "ece_10": None}
    brier = statistics.fmean((float(p) - int(y)) ** 2 for p, y in labels)
    ece = 0.0
    for bin_index in range(10):
        lo, hi = bin_index / 10.0, (bin_index + 1) / 10.0
        rows = [(float(p), int(y)) for p, y in labels if lo <= float(p) < hi or (bin_index == 9 and float(p) == 1.0)]
        if rows:
            ece += len(rows) / len(labels) * abs(statistics.fmean(p for p, _ in rows) - statistics.fmean(y for _, y in rows))
    return {"samples": len(labels), "positives": sum(int(y) for _, y in labels), "brier": q(brier), "ece_10": q(ece)}


def aggregate_group(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [episode["summary"] for episode in episodes]
    keys = ("hard_floor", "authorization", "reverse_after_entry", "egress", "capacity", "door_plane", "staging")
    te = [x for s in summaries for x in s["truth_to_evidence_s"]]
    ed = [x for s in summaries for x in s["evidence_to_decision_s"]]
    dm = [x for s in summaries for x in s["decision_to_motion_s"]]
    labels = [x for s in summaries for x in s["risk_labels"]]
    count = len(summaries)
    opportunities = lambda leg: sum(s["latency_opportunities"][leg] for s in summaries)
    successes = sum(int(s["task_success"]) for s in summaries)
    safe_successes = sum(int(s["task_success"] and s["safety_gate_pass"]) for s in summaries)
    efficiencies = [s["path_efficiency"] for s in summaries if s["path_efficiency"] is not None]
    return {
        "episodes": count,
        "contacts": sum(int(s["contact"]) for s in summaries),
        "near_contacts": sum(int(s["near_contact"]) for s in summaries),
        "actor_into_stationary_contacts": sum(int(s["actor_into_stationary_contact"]) for s in summaries),
        "minimum_surface_clearance_m": min((s["minimum_surface_clearance_m"] for s in summaries), default=None),
        "p05_minimum_surface_clearance_m": percentile([s["minimum_surface_clearance_m"] for s in summaries], 0.05),
        "hard_envelope_admissions": sum(s["hard_envelope_admissions"] for s in summaries),
        "final_monitor_interventions": sum(s["final_monitor_interventions"] for s in summaries),
        "semantic_violation_ticks": {key: sum(s["semantic_violation_ticks"][key] for s in summaries) for key in keys},
        "goal_reached": sum(int(s["goal_reached"]) for s in summaries),
        "correct_refusals": sum(int(s["correct_refusal"]) for s in summaries),
        "task_successes": successes, "safe_task_successes": safe_successes,
        "completion_rate": q(successes / count) if count else None,
        "safe_completion_rate": q(safe_successes / count) if count else None,
        "goal_rate": q(sum(int(s["goal_reached"]) for s in summaries) / count) if count else None,
        "mean_path_efficiency": q(statistics.fmean(efficiencies)) if efficiencies else None,
        "false_block_s": q(sum(s["false_block_s"] for s in summaries)),
        "mean_false_block_s": q(statistics.fmean(s["false_block_s"] for s in summaries)) if summaries else None,
        "wrong_stalls": sum(int(s["wrong_stall"]) for s in summaries),
        "deadlocks": sum(int(s["deadlock"]) for s in summaries),
        "retreat_episodes": sum(int(s["retreat_used"]) for s in summaries),
        "evasion_episodes": sum(int(s["evasion_used"]) for s in summaries),
        "release_on_missing_only": sum(s["release_on_missing_only"] for s in summaries),
        "stop_start_transitions": sum(s["stop_start_transitions"] for s in summaries),
        "mean_stop_start_transitions": q(statistics.fmean(s["stop_start_transitions"] for s in summaries)) if summaries else None,
        "mean_acceleration_mps2": q(statistics.fmean(s["mean_acceleration_mps2"] for s in summaries)) if summaries else None,
        "mean_jerk_mps3": q(statistics.fmean(s["mean_jerk_mps3"] for s in summaries)) if summaries else None,
        "mean_lateral_travel_m": q(statistics.fmean(s["lateral_travel_m"] for s in summaries)) if summaries else None,
        "minimum_ttc_s": min((s["minimum_ttc_s"] for s in summaries), default=None),
        "latencies_s": {
            "truth_to_evidence": {"eligible": opportunities("truth_clear"), "n": len(te), "censored": opportunities("truth_clear") - len(te), "p50": percentile(te, 0.5), "p95": percentile(te, 0.95)},
            "evidence_to_decision": {"eligible": opportunities("evidence_clear"), "n": len(ed), "censored": opportunities("evidence_clear") - len(ed), "p50": percentile(ed, 0.5), "p95": percentile(ed, 0.95)},
            "decision_to_motion": {"eligible": opportunities("decision"), "n": len(dm), "censored": opportunities("decision") - len(dm), "p50": percentile(dm, 0.5), "p95": percentile(dm, 0.95)},
        },
        "risk_calibration": calibration(labels),
    }


def forbidden(group: dict[str, Any]) -> int:
    return sum(int(value) for value in group["semantic_violation_ticks"].values())


def hypotheses(episodes: list[dict[str, Any]], arms: dict[str, Any], contexts: dict[str, Any], strata: dict[str, Any]) -> dict[str, Any]:
    h1_arms: dict[str, Any] = {}
    for arm in ("S2", "S3"):
        group = arms[arm]
        clauses = {
            "zero_contacts": group["contacts"] == 0,
            "zero_actor_into_stationary_contacts": group["actor_into_stationary_contacts"] == 0,
            "zero_hard_envelope_admissions": group["hard_envelope_admissions"] == 0,
            "zero_semantic_or_current_floor_violations": forbidden(group) == 0,
        }
        h1_arms[arm] = {"status": "SUPPORTED" if all(clauses.values()) else "REFUTED", "clauses": clauses}
    h1 = all(row["status"] == "SUPPORTED" for row in h1_arms.values())
    ce0 = aggregate_group([e for e in episodes if e["arm"] == "S0" and e["context"] in {"crosswalk", "elevator"}])
    ce2 = aggregate_group([e for e in episodes if e["arm"] == "S2" and e["context"] in {"crosswalk", "elevator"}])
    gain = q(ce2["completion_rate"] - ce0["completion_rate"])
    h2 = {
        "crosswalk_elevator_completion_gain_at_least_0_15": gain >= 0.15,
        "sidewalk_completion_not_lower": contexts["S2"]["sidewalk"]["completion_rate"] >= contexts["S0"]["sidewalk"]["completion_rate"],
        "near_contacts_not_higher": arms["S2"]["near_contacts"] <= arms["S0"]["near_contacts"],
        "zero_forbidden_events": forbidden(arms["S2"]) == 0,
    }
    s2_false, s2_transitions = arms["S2"]["false_block_s"], arms["S2"]["stop_start_transitions"]
    false_reduction = q((s2_false - arms["S3"]["false_block_s"]) / s2_false) if s2_false > 0 else 0.0
    transition_reduction = q((s2_transitions - arms["S3"]["stop_start_transitions"]) / s2_transitions) if s2_transitions > 0 else 0.0
    ed95 = arms["S3"]["latencies_s"]["evidence_to_decision"]["p95"]
    dm95 = arms["S3"]["latencies_s"]["decision_to_motion"]["p95"]
    h3 = {
        "false_block_reduction_at_least_20pct": false_reduction >= 0.2,
        "evidence_to_decision_p95_at_most_0_4s": ed95 is not None and ed95 <= 0.4,
        "decision_to_motion_p95_at_most_0_2s": dm95 is not None and dm95 <= 0.2,
        "transition_reduction_at_least_20pct": transition_reduction >= 0.2,
        "retains_h1": h1_arms["S3"]["status"] == "SUPPORTED",
        "completion_not_worse": arms["S3"]["completion_rate"] >= arms["S2"]["completion_rate"],
    }
    nr, visibility = strata["S3"]["feasible_nonresponsive"], strata["S3"]["flicker_or_occlusion"]
    h4 = {
        "feasible_nonresponsive_completion_at_least_80pct": nr["episodes"] > 0 and nr["completion_rate"] >= 0.8,
        "flicker_or_occlusion_completion_at_least_80pct": visibility["episodes"] > 0 and visibility["completion_rate"] >= 0.8,
        "zero_missing_only_release": arms["S3"]["release_on_missing_only"] == 0,
        "retains_h1": h1_arms["S3"]["status"] == "SUPPORTED",
    }
    return {
        "D2-H1": {"status": "SUPPORTED" if h1 else "REFUTED", "arms": h1_arms},
        "D2-H2": {"status": "SUPPORTED" if all(h2.values()) else "REFUTED", "clauses": h2, "crosswalk_elevator_completion_gain_points": q(100 * gain), "denominators": {"S0": ce0["episodes"], "S2": ce2["episodes"]}},
        "D2-H3": {"status": "SUPPORTED" if all(h3.values()) else "REFUTED", "clauses": h3, "false_block_reduction_fraction": false_reduction, "transition_reduction_fraction": transition_reduction},
        "D2-H4": {"status": "SUPPORTED" if all(h4.values()) else "REFUTED", "clauses": h4, "denominators": {"feasible_nonresponsive": nr["episodes"], "flicker_or_occlusion": visibility["episodes"]}},
    }


def aggregate_all(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {arm: aggregate_group([e for e in episodes if e["arm"] == arm]) for arm in ARMS}
    contexts = {arm: {context: aggregate_group([e for e in episodes if e["arm"] == arm and e["context"] == context]) for context in ("sidewalk", "crosswalk", "elevator")} for arm in ARMS}
    family_names = sorted({e["family"] for e in episodes})
    families = {arm: {family: aggregate_group([e for e in episodes if e["arm"] == arm and e["family"] == family]) for family in family_names} for arm in ARMS}
    strata: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        rows = [e for e in episodes if e["arm"] == arm]
        strata[arm] = {
            "responsive": aggregate_group([e for e in rows if "responsive" in e["tags"]]),
            "nonresponsive": aggregate_group([e for e in rows if "nonresponsive" in e["tags"]]),
            "feasible_nonresponsive": aggregate_group([e for e in rows if "nonresponsive" in e["tags"] and e["otherwise_feasible"]]),
            "flicker_or_occlusion": aggregate_group([e for e in rows if "clear_flicker" in e["tags"] or "occlusion" in e["tags"]]),
            "otherwise_feasible": aggregate_group([e for e in rows if e["otherwise_feasible"]]),
            "expected_refusal": aggregate_group([e for e in rows if e["expected_refusal"]]),
        }
    return {"arms": arms, "contexts": contexts, "families": families, "strata": strata, "hypotheses": hypotheses(episodes, arms, contexts, strata)}


def trajectory_signature(scenario: dict[str, Any]) -> str:
    return sha({
        "family": scenario["family"], "actors": scenario["actors"],
        "semantic": {key: scenario[key] for key in (
            "authorized_windows_s", "door_closed_windows_s", "capacity_full_windows_s", "egress_windows_s", "occlusion_windows",
        )},
    })


def verify_frozen(path: Path, audit: Audit) -> None:
    frozen = json.loads(path.read_text())
    for relative, expected in frozen["files"].items():
        target = path.parent / relative
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        audit.require(actual == expected, f"frozen file mismatch: {relative}")


def verify_document(
    result: dict[str, Any], fixture: dict[str, Any], manifest: dict[str, Any],
    result_path: Path, manifest_path: Path, frozen_path: Path | None,
) -> Audit:
    audit = Audit()
    if frozen_path:
        verify_frozen(frozen_path, audit)
    audit.require(result.get("fixture_sha256") == sha(fixture), "result fixture digest mismatch")
    audit.require(manifest.get("generated_from_fixture_sha256") == sha(fixture), "manifest fixture lineage mismatch")
    audit.require(result.get("episode_manifest_sha256") == hashlib.sha256(manifest_path.read_bytes()).hexdigest(), "result episode-manifest digest mismatch")
    if frozen_path:
        audit.require(result.get("run_metadata", {}).get("frozen_manifest_sha256") == hashlib.sha256(frozen_path.read_bytes()).hexdigest(), "result frozen-manifest digest mismatch")
    signatures: dict[str, set[str]] = {split: set() for split in fixture["splits"]}
    for family, scenario in manifest["scenarios"].items():
        expected = trajectory_signature(scenario)
        audit.require(scenario["trajectory_signature"] == expected, f"{family}: trajectory signature mismatch")
        signatures[scenario["split"]].add(expected)
    split_names = sorted(signatures)
    for i, left in enumerate(split_names):
        for right in split_names[i + 1:]:
            audit.require(not (signatures[left] & signatures[right]), f"trajectory lineage overlap: {left}/{right}")

    split = result.get("split")
    expected_entries = [entry for entry in manifest["episodes"] if entry["split"] == split]
    expected_by_key = {entry["key"]: entry for entry in expected_entries}
    actual_episodes = result.get("episodes", [])
    actual_by_key = {episode.get("episode_key"): episode for episode in actual_episodes}
    audit.require(len(actual_by_key) == len(actual_episodes), "duplicate episode key")
    audit.require(set(actual_by_key) == set(expected_by_key), "episode inventory mismatch")
    if split == "test":
        audit.require(len(actual_episodes) == fixture["expected_test_inventory"]["total_episodes"], "test episode count mismatch")
        audit.require(all(episode.get("trace") for episode in actual_episodes), "test result contains empty trace")
    recomputed: list[dict[str, Any]] = []
    for key in sorted(set(actual_by_key) & set(expected_by_key)):
        episode, entry = actual_by_key[key], expected_by_key[key]
        scenario = manifest["scenarios"][entry["family"]]
        for field in ("arm", "split", "family", "base_sensor_seed", "sensor_seed", "trajectory_signature"):
            expected_value = entry[field if field != "base_sensor_seed" else "base_sensor_seed"]
            audit.require(episode.get(field) == expected_value, f"{key}: metadata mismatch {field}")
        audit.require(episode.get("tags") == scenario["tags"], f"{key}: tags mismatch")
        audit.require(episode.get("otherwise_feasible") == scenario["otherwise_feasible"], f"{key}: feasibility stratum mismatch")
        summary = verify_episode(episode, scenario, fixture, audit)
        recomputed.append({
            "arm": episode["arm"], "context": episode["context"], "family": episode["family"],
            "tags": episode["tags"], "otherwise_feasible": episode["otherwise_feasible"],
            "expected_refusal": episode["expected_refusal"], "summary": summary,
        })
    digest_map = {key: actual_by_key[key]["normalized_sha256"] for key in sorted(actual_by_key)}
    audit.require(result.get("normalized_episode_digest") == sha(digest_map), "aggregate normalized episode digest mismatch")
    expected_inventory = {
        "episodes": len(actual_episodes),
        "arms": {arm: sum(e.get("arm") == arm for e in actual_episodes) for arm in ARMS},
        "families": len({e.get("family") for e in actual_episodes}),
        "base_sensor_seeds": len({e.get("base_sensor_seed") for e in actual_episodes}),
    }
    audit.require(result.get("inventory") == expected_inventory, "reported inventory mismatch")
    if len(recomputed) == len(actual_episodes):
        expected_aggregate = aggregate_all(recomputed)
        audit.require(close(result.get("aggregate"), expected_aggregate, 6e-5), "recomputed aggregate/hypothesis mismatch")
    return audit


def tamper_tests(
    original: dict[str, Any], fixture: dict[str, Any], manifest: dict[str, Any],
    result_path: Path, manifest_path: Path, frozen_path: Path | None,
) -> dict[str, Any]:
    outcomes: dict[str, Any] = {}
    action = copy.deepcopy(original)
    action["episodes"][0]["trace"][0][action["episodes"][0]["trace_fields"].index("accepted_vx")] += 0.123
    outcomes["action"] = len(verify_document(action, fixture, manifest, result_path, manifest_path, frozen_path).errors) > 0
    actor = copy.deepcopy(original)
    changed = False
    for episode in actor["episodes"]:
        actor_index = episode["trace_fields"].index("actors")
        for row in episode["trace"]:
            if row[actor_index]:
                row[actor_index][0][1] += 0.111
                changed = True
                break
        if changed:
            break
    outcomes["actor_trajectory"] = changed and len(verify_document(actor, fixture, manifest, result_path, manifest_path, frozen_path).errors) > 0
    semantic = copy.deepcopy(original)
    phase_index = semantic["episodes"][0]["trace_fields"].index("semantic_phase")
    semantic["episodes"][0]["trace"][0][phase_index] = "TAMPERED_PHASE"
    outcomes["semantic_phase"] = len(verify_document(semantic, fixture, manifest, result_path, manifest_path, frozen_path).errors) > 0
    return {"all_rejected": all(outcomes.values()), "tamper_rejected": outcomes}


def main() -> int:
    directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--fixtures", type=Path, default=directory / "fixtures.json")
    parser.add_argument("--manifest", type=Path, default=directory / "episode_manifest.json")
    parser.add_argument("--frozen-manifest", type=Path)
    parser.add_argument("--tamper-self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.loads(args.result.read_text())
    fixture = json.loads(args.fixtures.read_text())
    manifest = json.loads(args.manifest.read_text())
    audit = verify_document(result, fixture, manifest, args.result, args.manifest, args.frozen_manifest)
    report: dict[str, Any] = {
        "result": str(args.result), "status": "PASS" if not audit.errors else "FAIL",
        "errors": audit.errors, "checks": {"independent_policy_import": False, "error_count": len(audit.errors)},
    }
    if args.tamper_self_test and not audit.errors:
        report["tamper_self_test"] = tamper_tests(result, fixture, manifest, args.result, args.manifest, args.frozen_manifest)
        if not report["tamper_self_test"]["all_rejected"]:
            report["status"] = "FAIL"
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
