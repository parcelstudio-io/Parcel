#!/usr/bin/env python3
"""DSP-2 deterministic social-navigation experiment.

The implementation intentionally uses only the Python standard library.  It is
an authored 2-D algorithmic simulator, not a dynamics or physical-safety test.
Test rollouts are accepted only when the frozen source manifest validates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ARMS = ("S0", "S1", "S2", "S3")
SCHEMA_VERSION = 2
TRACE_FIELDS = (
    "tick", "time_s", "robot_x_before", "robot_y_before", "vx_before", "vy_before",
    "proposed_vx", "proposed_vy", "accepted_vx", "accepted_vy", "vx_after", "vy_after",
    "robot_x_after", "robot_y_after", "policy_state", "semantic_phase", "authorized",
    "capacity_available", "door_open", "egress_active", "sensor_fresh", "explicit_free",
    "evidence_clear", "risk_clearance_m", "hold_margin_m", "forward_margin_m",
    "monitor_intervention", "hard_envelope_admission", "oracle_safe_translation",
    "truth_forward_clear", "minimum_surface_clearance_m", "actor_into_stationary_contact",
    "near_contact", "hard_floor_violation", "authorization_violation",
    "reverse_after_entry_violation", "egress_violation", "capacity_violation",
    "door_plane_violation", "staging_violation", "release_on_missing_only", "retreat_used",
    "evasion_used", "decision_event", "translating", "minimum_ttc_s", "actors", "tracks",
    "corridor_observed", "semantic_phase_changed", "path_increment_m", "contact_within_2s_truth",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def stable_seed(*parts: Any) -> int:
    raw = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") & 0x7FFFFFFF


def q(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def add(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] + b[0], a[1] + b[1])


def sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] - b[0], a[1] - b[1])


def mul(a: tuple[float, float], scalar: float) -> tuple[float, float]:
    return (a[0] * scalar, a[1] * scalar)


def norm(a: tuple[float, float]) -> float:
    return math.hypot(a[0], a[1])


def unit(a: tuple[float, float]) -> tuple[float, float]:
    n = norm(a)
    return (0.0, 0.0) if n < 1e-12 else (a[0] / n, a[1] / n)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def percentile(values: list[float], proportion: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return q(ordered[lower])
    frac = position - lower
    return q(ordered[lower] * (1.0 - frac) + ordered[upper] * frac)


def in_intervals(t: float, intervals: list[list[float]]) -> bool:
    return any(float(start) <= t < float(end) for start, end in intervals)


def context_of(family: str) -> str:
    return family.split("_", 1)[0]


def base_name(family: str) -> str:
    result = family
    for suffix in ("_train", "_dev", "_test"):
        if result.endswith(suffix):
            result = result[: -len(suffix)]
    return result.split("_", 1)[1]


def split_of(family: str) -> str:
    if family.endswith("_train"):
        return "train"
    if family.endswith("_dev"):
        return "development"
    if family.endswith("_test"):
        return "test"
    raise ValueError(f"family lacks split suffix: {family}")


def actor(
    actor_id: str, p0: tuple[float, float], velocity: tuple[float, float], *,
    role: str = "pedestrian", responsive: bool = True,
    active: tuple[float, float] = (0.0, 99.0),
    events: list[tuple[float, float, float]] | None = None,
) -> dict[str, Any]:
    return {
        "id": actor_id,
        "p0": [q(p0[0]), q(p0[1])],
        "velocity": [q(velocity[0]), q(velocity[1])],
        "role": role,
        "responsive": responsive,
        "active_interval_s": [q(active[0]), q(active[1])],
        "velocity_events": [[q(t), q(vx), q(vy)] for t, vx, vy in (events or [])],
    }


def scenario_for(family: str, fixture: dict[str, Any]) -> dict[str, Any]:
    """Return the authored episode template. No seed-dependent truth is hidden here."""
    context = context_of(family)
    base = base_name(family)
    split = split_of(family)
    # Disjoint whole-episode geometry offsets make trajectory lineage explicit.
    split_delta = {"train": -0.11, "development": 0.07, "test": 0.19}[split]
    common: dict[str, Any] = {
        "family": family,
        "base_family": base,
        "split": split,
        "context": context,
        "start": [0.0, 0.0],
        "duration_s": fixture["simulation"]["sidewalk_duration_s"] if context == "sidewalk" else fixture["simulation"]["duration_s"],
        "authorized_windows_s": [[0.0, 99.0]],
        "door_closed_windows_s": [],
        "capacity_full_windows_s": [],
        "egress_windows_s": [],
        "occlusion_windows": {},
        "explicit_free_flicker_ticks": [],
        "expected_refusal": False,
        "otherwise_feasible": True,
        "tags": [],
        "actors": [],
    }

    if context == "sidewalk":
        common.update(goal=[8.0, 0.0], corridor_half_width_m=1.18)
        x = 4.4 + split_delta
        if base == "owner_alongside":
            common["actors"] = [actor("owner", (-0.25, 0.94), (0.77, 0.0), role="owner")]
            common["tags"] = ["responsive", "owner"]
        elif base == "same_flow_pass":
            common["actors"] = [actor("walker", (1.45 + split_delta, -0.12), (0.43, 0.0))]
            common["tags"] = ["responsive"]
        elif base == "oncoming":
            common["actors"] = [actor("oncoming", (x, 0.02), (-0.67, 0.0))]
            common["tags"] = ["responsive"]
        elif base == "oncoming_nonresponsive":
            common["actors"] = [actor("oncoming_nr", (x, 0.0), (-0.61, 0.0), responsive=False)]
            common["tags"] = ["nonresponsive"]
        elif base == "cut_in":
            common["actors"] = [actor("cutin", (2.7 + split_delta, -1.45), (0.18, 0.62), events=[(3.5, 0.56, 0.08)])]
            common["tags"] = ["responsive"]
        elif base == "crossing":
            common["actors"] = [actor("crossing", (3.5 + split_delta, -1.75), (0.0, 0.73))]
            common["tags"] = ["responsive"]
        elif base == "overtaking":
            common["actors"] = [actor("overtaking", (-1.1, 0.22), (1.08, 0.0))]
            common["tags"] = ["responsive"]
        elif base == "sudden_stop":
            common["actors"] = [actor("stopper", (2.45 + split_delta, 0.0), (0.48, 0.0), events=[(3.0, 0.0, 0.0), (7.0, 0.43, 0.0)])]
            common["tags"] = ["responsive"]
        elif base == "sudden_turn":
            common["actors"] = [actor("turner", (3.35 + split_delta, 0.72), (0.28, -0.06), events=[(3.2, -0.16, -0.52), (5.3, -0.38, 0.05)])]
            common["tags"] = ["responsive"]
        elif base == "group_gap":
            common["actors"] = [
                actor("group_left", (x, 0.63), (-0.57, 0.0)),
                actor("group_right", (x + 0.35, -0.63), (-0.57, 0.0)),
            ]
            common["tags"] = ["responsive", "group"]
        elif base == "occlusion":
            common["actors"] = [actor("occluded", (x, 0.0), (-0.58, 0.0), responsive=False)]
            common["occlusion_windows"] = {"occluded": [[2.0, 4.3]]}
            common["tags"] = ["nonresponsive", "occlusion"]
        elif base == "clear_flicker":
            common["actors"] = [actor("flicker_actor", (x, 0.05), (-0.56, 0.0))]
            common["explicit_free_flicker_ticks"] = fixture["sensor"]["explicit_free_flicker_ticks"]
            common["tags"] = ["responsive", "clear_flicker"]
        elif base == "advancing_nonresponsive":
            common["actors"] = [actor("advancing_nr", (3.0 + split_delta, 0.0), (-0.49, 0.0), responsive=False)]
            common["tags"] = ["nonresponsive"]
        else:
            raise ValueError(f"unknown sidewalk family {family}")

    elif context == "crosswalk":
        common.update(goal=[6.0, 0.0], corridor_half_width_m=1.15)
        if base == "unauthorized":
            common["authorized_windows_s"] = [[3.0, 18.0]]
            common["tags"] = ["feasible_control"]
        elif base == "lateral_flow":
            common["actors"] = [actor("lateral", (2.55 + split_delta, -2.0), (0.0, 0.75))]
            common["tags"] = ["responsive"]
        elif base == "late_entrant":
            common["actors"] = [actor("late", (4.0 + split_delta, -1.75), (0.0, 0.73), active=(3.0, 12.0))]
            common["tags"] = ["responsive"]
        elif base == "persistent_blocker":
            common["actors"] = [actor("blocker", (3.0 + split_delta, 0.0), (0.0, 0.0), responsive=False)]
            common["otherwise_feasible"] = False
            common["tags"] = ["nonresponsive", "infeasible"]
        elif base == "owner_group":
            common["actors"] = [
                actor("owner", (-0.2, 0.94), (0.72, 0.0), role="owner"),
                actor("group_cross", (3.1 + split_delta, -1.8), (0.0, 0.64)),
            ]
            common["tags"] = ["responsive", "owner", "group"]
        elif base == "mid_intrusion":
            common["actors"] = [actor("intruder", (3.35 + split_delta, -1.65), (0.0, 0.72), responsive=False, active=(3.4, 12.0))]
            common["tags"] = ["nonresponsive"]
        elif base == "clear_flicker":
            common["actors"] = [actor("cross_flicker", (2.75 + split_delta, -1.8), (0.0, 0.67))]
            common["explicit_free_flicker_ticks"] = fixture["sensor"]["explicit_free_flicker_ticks"]
            common["tags"] = ["responsive", "clear_flicker"]
        elif base == "short_authorization":
            common["authorized_windows_s"] = [[1.0, 4.0]]
            common["expected_refusal"] = True
            common["otherwise_feasible"] = False
            common["tags"] = ["short_authorization", "infeasible"]
        else:
            raise ValueError(f"unknown crosswalk family {family}")

    elif context == "elevator":
        common.update(goal=[2.55, 0.0], corridor_half_width_m=1.0)
        ex = 2.25 + split_delta
        if base == "exit_first":
            common["actors"] = [actor("egress", (ex, 0.0), (-0.57, 0.0), role="egress")]
            common["egress_windows_s"] = [[0.0, 5.5]]
            common["tags"] = ["responsive", "egress"]
        elif base == "temporary_clear":
            common["actors"] = [actor("egress", (ex, 0.0), (-0.52, 0.0), role="egress", active=(1.0, 8.0))]
            common["egress_windows_s"] = [[1.0, 5.8]]
            common["tags"] = ["responsive", "egress"]
        elif base == "occluded_egress":
            common["actors"] = [actor("egress_hidden", (ex, 0.0), (-0.54, 0.0), role="egress", responsive=False)]
            common["egress_windows_s"] = [[0.0, 6.0]]
            common["occlusion_windows"] = {"egress_hidden": [[0.8, 3.1]]}
            common["tags"] = ["nonresponsive", "egress", "occlusion"]
        elif base == "occupied_full":
            common["actors"] = [
                actor("occupant_a", (1.85, 0.52), (0.0, 0.0), responsive=False),
                actor("occupant_b", (2.15, -0.52), (0.0, 0.0), responsive=False),
            ]
            common["capacity_full_windows_s"] = [[0.0, 99.0]]
            common["expected_refusal"] = True
            common["otherwise_feasible"] = False
            common["tags"] = ["nonresponsive", "capacity", "infeasible"]
        elif base == "narrow_entry":
            common["actors"] = [actor("inside_side", (1.75 + split_delta, 0.73), (0.0, 0.0), responsive=False)]
            common["tags"] = ["nonresponsive", "narrow"]
        elif base == "closing_reopening":
            common["door_closed_windows_s"] = [[1.6, 5.2], [8.0, 9.0]]
            common["tags"] = ["door_cycle"]
        elif base == "nonresponsive_exit":
            common["actors"] = [actor("egress_nr", (ex, 0.0), (-0.58, 0.0), role="egress", responsive=False)]
            common["egress_windows_s"] = [[0.0, 6.0]]
            common["tags"] = ["nonresponsive", "egress"]
        elif base == "clear_flicker":
            common["actors"] = [actor("egress_flicker", (ex, 0.0), (-0.53, 0.0), role="egress")]
            common["egress_windows_s"] = [[0.0, 5.7]]
            common["explicit_free_flicker_ticks"] = fixture["sensor"]["explicit_free_flicker_ticks"]
            common["tags"] = ["responsive", "egress", "clear_flicker"]
        else:
            raise ValueError(f"unknown elevator family {family}")
    else:
        raise ValueError(context)

    common["trajectory_signature"] = sha256_value({
        "family": family,
        "actors": common["actors"],
        "semantic": {k: common[k] for k in (
            "authorized_windows_s", "door_closed_windows_s", "capacity_full_windows_s",
            "egress_windows_s", "occlusion_windows",
        )},
    })
    return common


def build_episode_manifest(fixture: dict[str, Any]) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    episodes: list[dict[str, Any]] = []
    for split, block in fixture["splits"].items():
        for family in block["families"]:
            scenario = scenario_for(family, fixture)
            if scenario["split"] != split:
                raise AssertionError((family, split))
            scenarios[family] = scenario
            for base_sensor_seed in block["base_sensor_seeds"]:
                sensor_seed = stable_seed("DSP-2", family, base_sensor_seed)
                for arm_name in ARMS:
                    episodes.append({
                        "key": f"{arm_name}|{family}|{base_sensor_seed}",
                        "arm": arm_name,
                        "split": split,
                        "family": family,
                        "base_sensor_seed": base_sensor_seed,
                        "sensor_seed": sensor_seed,
                        "trajectory_signature": scenario["trajectory_signature"],
                    })
    signatures_by_split = {
        split: sorted(s["trajectory_signature"] for s in scenarios.values() if s["split"] == split)
        for split in fixture["splits"]
    }
    for left in signatures_by_split:
        for right in signatures_by_split:
            if left < right and set(signatures_by_split[left]) & set(signatures_by_split[right]):
                raise AssertionError(f"trajectory signature overlap: {left}/{right}")
    return {
        "schema_version": SCHEMA_VERSION,
        "study": "DSP-2",
        "generated_from_fixture_sha256": sha256_value(fixture),
        "arms": list(ARMS),
        "scenarios": scenarios,
        "episodes": episodes,
        "split_inventory": {
            split: {
                "families": len(block["families"]),
                "sensor_seeds": len(block["base_sensor_seeds"]),
                "episodes": len(block["families"]) * len(block["base_sensor_seeds"]) * len(ARMS),
                "trajectory_signatures": signatures_by_split[split],
            }
            for split, block in fixture["splits"].items()
        },
    }


@dataclass
class ActorState:
    actor_id: str
    x: float
    y: float
    vx: float
    vy: float
    role: str
    responsive: bool
    active: bool


@dataclass
class Track:
    actor_id: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    variance: float = 0.018
    existence: float = 0.72
    last_seen_tick: int = -1
    fresh: bool = False
    missed: bool = False
    role: str = "pedestrian"


@dataclass
class PolicyMemory:
    state: str = "GO"
    clear_streak: int = 0
    approach_streak: int = 0
    creep_ticks: int = 0
    committed: bool = False
    previous_phase: str = ""
    previous_command: tuple[float, float] = (0.0, 0.0)
    escape_target_y: float | None = None


def authored_velocity(spec: dict[str, Any], t: float) -> tuple[float, float]:
    velocity = (float(spec["velocity"][0]), float(spec["velocity"][1]))
    for event_t, vx, vy in spec["velocity_events"]:
        if t >= float(event_t):
            velocity = (float(vx), float(vy))
    return velocity


def initialize_actors(scenario: dict[str, Any]) -> dict[str, ActorState]:
    return {
        spec["id"]: ActorState(
            actor_id=spec["id"], x=float(spec["p0"][0]), y=float(spec["p0"][1]),
            vx=float(spec["velocity"][0]), vy=float(spec["velocity"][1]), role=spec["role"],
            responsive=bool(spec["responsive"]), active=False,
        )
        for spec in scenario["actors"]
    }


def actor_step(
    states: dict[str, ActorState], scenario: dict[str, Any], robot: tuple[float, float], t: float, dt: float,
) -> None:
    """Frozen authored response law; policy is never told responsiveness."""
    specs = {spec["id"]: spec for spec in scenario["actors"]}
    for actor_id, state in states.items():
        spec = specs[actor_id]
        start, end = map(float, spec["active_interval_s"])
        state.active = start <= t < end
        if not state.active:
            state.vx = state.vy = 0.0
            continue
        base_v = authored_velocity(spec, t)
        vx, vy = base_v
        if state.responsive and state.role != "owner":
            rel = (robot[0] - state.x, robot[1] - state.y)
            distance = norm(rel)
            closing = (vx * rel[0] + vy * rel[1]) > 0.0
            # Deterministic authored side-step, bounded and never assumed by policy.
            if distance < 1.25 and closing:
                away_sign = 1.0 if state.y <= robot[1] else -1.0
                vy = clamp(vy + away_sign * 0.42 * (1.25 - distance) / 1.25, -0.78, 0.78)
                vx *= 0.82
        if state.role == "owner":
            target_y = robot[1] + 0.94
            vy = clamp((target_y - state.y) * 0.8, -0.35, 0.35)
        state.vx, state.vy = vx, vy
        state.x += vx * dt
        state.y += vy * dt


def semantic_values(scenario: dict[str, Any], t: float) -> tuple[bool, bool, bool, bool]:
    authorized = in_intervals(t, scenario["authorized_windows_s"])
    capacity = not in_intervals(t, scenario["capacity_full_windows_s"])
    door_open = not in_intervals(t, scenario["door_closed_windows_s"])
    egress_active = in_intervals(t, scenario["egress_windows_s"])
    return authorized, capacity, door_open, egress_active


def semantic_phase(
    scenario: dict[str, Any], robot: tuple[float, float], committed: bool,
    authorized: bool, capacity: bool, door_open: bool, egress_active: bool,
    fixture: dict[str, Any], t: float,
) -> str:
    context = scenario["context"]
    policy_cfg = fixture["policy"]
    if context == "sidewalk":
        return "SIDEWALK"
    if context == "crosswalk":
        if committed or robot[0] >= policy_cfg["crosswalk_entry_x_m"]:
            return "EXITED" if robot[0] >= policy_cfg["crosswalk_exit_x_m"] else "COMMITTED"
        remaining = max(0.0, scenario["authorized_windows_s"][-1][1] - t) if authorized else 0.0
        speed = fixture["simulation"]["nominal_speed_mps"]
        required = max(0.0, policy_cfg["crosswalk_exit_x_m"] - robot[0]) / speed + policy_cfg["crosswalk_time_to_clear_margin_s"]
        return "ENTRY_READY" if authorized and remaining >= required else "CURB_WAIT"
    if robot[0] >= policy_cfg["elevator_door_plane_x_m"]:
        return "INSIDE"
    if robot[0] >= policy_cfg["elevator_stage_x_m"] - 0.14:
        return "ENTRY_READY" if capacity and door_open and not egress_active else "STAGE"
    return "APPROACH"


def sensor_and_tracker_step(
    tracks: dict[str, Track], states: dict[str, ActorState], scenario: dict[str, Any],
    robot: tuple[float, float], tick: int, rng: random.Random,
    delivery_queue: dict[int, list[dict[str, Any]]], fixture: dict[str, Any],
) -> tuple[dict[str, Track], bool, bool, bool]:
    """Generate delayed noisy detections and retain missed tracks.

    A free certificate is a simulated *sensor observation*.  Occlusion or stale
    input prevents certification; actor truth is not passed to the policy.
    """
    dt = float(fixture["simulation"]["dt_s"])
    cfg = fixture["sensor"]
    t = tick * dt
    stale = tick in set(int(x) for x in cfg["stale_frame_ticks"])
    occluded_ids = {
        actor_id for actor_id, intervals in scenario["occlusion_windows"].items()
        if in_intervals(t, intervals)
    }
    corridor_observed = not stale
    captured: list[dict[str, Any]] = []
    for actor_id in sorted(states):
        state = states[actor_id]
        if not state.active:
            continue
        if actor_id in occluded_ids:
            # A known occlusion invalidates the corridor's free-space ray.
            if state.x >= robot[0] - 0.3 and state.x <= robot[0] + 4.0:
                corridor_observed = False
            continue
        if stale or rng.random() < float(cfg["dropout_probability"]):
            continue
        captured.append({
            "id": actor_id,
            "x": state.x + rng.gauss(0.0, float(cfg["position_noise_sigma_m"])),
            "y": state.y + rng.gauss(0.0, float(cfg["position_noise_sigma_m"])),
            "vx": state.vx + rng.gauss(0.0, 0.018),
            "vy": state.vy + rng.gauss(0.0, 0.018),
            "role": state.role,
        })
    rng.shuffle(captured)
    latency = rng.randint(int(cfg["latency_ticks_min"]), int(cfg["latency_ticks_max"]))
    delivery_queue.setdefault(tick + latency, []).extend(captured)
    delivered = delivery_queue.pop(tick, []) if not stale else []
    seen: set[str] = set()
    for detection in delivered:
        actor_id = detection["id"]
        seen.add(actor_id)
        if actor_id not in tracks:
            tracks[actor_id] = Track(
                actor_id=actor_id, x=detection["x"], y=detection["y"],
                vx=detection["vx"], vy=detection["vy"],
                variance=float(cfg["track_initial_variance_m2"]),
                role=detection["role"], last_seen_tick=tick, fresh=True,
            )
            continue
        tr = tracks[actor_id]
        tr.x = 0.76 * detection["x"] + 0.24 * (tr.x + tr.vx * dt)
        tr.y = 0.76 * detection["y"] + 0.24 * (tr.y + tr.vy * dt)
        tr.vx = 0.64 * tr.vx + 0.36 * detection["vx"]
        tr.vy = 0.64 * tr.vy + 0.36 * detection["vy"]
        tr.variance = max(0.006, tr.variance * float(cfg["track_visible_variance_decay"]))
        tr.existence = min(0.998, tr.existence + 0.2)
        tr.last_seen_tick = tick
        tr.fresh = True
        tr.missed = False
        tr.role = detection["role"]
    for actor_id in list(tracks):
        if actor_id in seen:
            continue
        tr = tracks[actor_id]
        tr.x += tr.vx * dt
        tr.y += tr.vy * dt
        tr.fresh = False
        tr.missed = True
        occluded = actor_id in occluded_ids or not corridor_observed
        tr.variance = min(2.0, tr.variance + float(
            cfg["track_occluded_variance_growth"] if occluded else cfg["track_observed_miss_variance_growth"]
        ))
        tr.existence *= float(
            cfg["track_occluded_existence_decay"] if occluded else cfg["track_observed_existence_decay"]
        )
        age_s = (tick - tr.last_seen_tick) * dt
        if tr.existence < float(cfg["track_delete_existence"]) or age_s > float(cfg["retained_track_s"]):
            del tracks[actor_id]

    relevant_visible = False
    blocked_ray = False
    for state in states.values():
        if not state.active:
            continue
        relx, rely = state.x - robot[0], state.y - robot[1]
        if -0.45 <= relx <= 3.6 and abs(rely) <= 0.82:
            relevant_visible = True
            if state.actor_id in occluded_ids:
                corridor_observed = False
            elif relx >= -0.1:
                blocked_ray = True
    explicit_free = corridor_observed and not blocked_ray
    if tick in set(int(x) for x in scenario["explicit_free_flicker_ticks"]):
        explicit_free = False
    # Fresh means a usable sensor cycle, not that every actor produced a box.
    sensor_fresh = not stale
    return tracks, sensor_fresh, corridor_observed, explicit_free


def track_rows(tracks: dict[str, Track]) -> list[list[Any]]:
    return [
        [tr.actor_id, q(tr.x), q(tr.y), q(tr.vx), q(tr.vy), q(tr.variance),
         q(tr.existence), tr.fresh, tr.missed, tr.role]
        for tr in sorted(tracks.values(), key=lambda item: item.actor_id)
    ]


def actor_rows(states: dict[str, ActorState]) -> list[list[Any]]:
    return [
        [st.actor_id, q(st.x), q(st.y), q(st.vx), q(st.vy), st.role, st.responsive, st.active]
        for st in sorted(states.values(), key=lambda item: item.actor_id)
    ]


def rotated(v: tuple[float, float], radians: float) -> tuple[float, float]:
    cosine, sine = math.cos(radians), math.sin(radians)
    return (v[0] * cosine - v[1] * sine, v[0] * sine + v[1] * cosine)


def actor_hypotheses(tr: Track, fixture: dict[str, Any], robust: bool) -> list[tuple[float, float]]:
    velocity = (tr.vx, tr.vy)
    if not robust:
        # This reproduces the old A3 mixture: CV, stop, and a single turn/slow mode.
        return [velocity, (0.0, 0.0), (velocity[0] * 0.55, velocity[1] + 0.45)]
    angle = math.radians(float(fixture["policy"]["robust_turn_degrees"]))
    speed = norm(velocity)
    direction = unit(velocity)
    accel = float(fixture["policy"]["robust_actor_acceleration_mps2"])
    return [
        velocity,
        (0.0, 0.0),
        rotated(velocity, angle),
        rotated(velocity, -angle),
        mul(direction, max(0.0, speed - accel)),
        mul(direction, speed + accel),
    ]


def predicted_clearance(
    robot: tuple[float, float], velocity: tuple[float, float], tracks: dict[str, Track],
    fixture: dict[str, Any], *, robust: bool, horizon_s: float | None = None,
    inflation_sigma: float | None = None,
) -> float:
    sim = fixture["simulation"]
    horizon = float(horizon_s if horizon_s is not None else sim["policy_horizon_s"])
    sample_dt = float(sim["policy_horizon_dt_s"])
    sigma = float(inflation_sigma if inflation_sigma is not None else (
        fixture["policy"]["robust_covariance_sigma"] if robust else 1.5
    ))
    combined_radius = float(sim["robot_radius_m"]) + float(sim["person_radius_m"])
    minimum = 9.0
    for tr in tracks.values():
        existence_floor = float(fixture["sensor"]["track_policy_existence"] if robust else 0.18)
        if tr.existence < existence_floor:
            continue
        inflation = sigma * math.sqrt(max(0.0, tr.variance))
        for actor_v in actor_hypotheses(tr, fixture, robust):
            steps = max(1, int(round(horizon / sample_dt)))
            for index in range(steps + 1):
                h = index * sample_dt
                rp = add(robot, mul(velocity, h))
                pp = (tr.x + actor_v[0] * h, tr.y + actor_v[1] * h)
                minimum = min(minimum, norm(sub(pp, rp)) - combined_radius - inflation)
    return minimum


def candidate_set(nominal: float) -> list[tuple[str, tuple[float, float]]]:
    return [
        ("hold", (0.0, 0.0)),
        ("slow", (nominal * 0.45, 0.0)),
        ("forward", (nominal, 0.0)),
        ("diag_left", (nominal * 0.72, 0.38)),
        ("diag_right", (nominal * 0.72, -0.38)),
        ("lateral_left", (0.0, 0.58)),
        ("lateral_right", (0.0, -0.58)),
        ("lateral_left_fast", (0.0, 1.0)),
        ("lateral_right_fast", (0.0, -1.0)),
        ("retreat", (-0.44, 0.0)),
        ("retreat_left", (-0.28, 0.42)),
        ("retreat_right", (-0.28, -0.42)),
    ]


def inside_corridor(scenario: dict[str, Any], robot: tuple[float, float], velocity: tuple[float, float]) -> bool:
    future_y = robot[1] + velocity[1] * 0.8
    return abs(future_y) <= float(scenario["corridor_half_width_m"])


def s0_command(
    scenario: dict[str, Any], robot: tuple[float, float], tracks: dict[str, Track],
    memory: PolicyMemory, fixture: dict[str, Any], semantic: tuple[bool, bool, bool, bool],
    fresh: bool, explicit_free: bool,
) -> tuple[tuple[float, float], float, float, bool]:
    """The prior study's A3 semantic-lattice arm, parameters unchanged."""
    authorized, capacity, door_open, egress_active = semantic
    nominal = float(fixture["simulation"]["elevator_speed_mps"] if scenario["context"] == "elevator" else fixture["simulation"]["nominal_speed_mps"])
    desired = (nominal, 0.0)
    forward_margin = predicted_clearance(robot, desired, tracks, fixture, robust=False)
    fresh_clear = fresh and explicit_free and forward_margin >= float(fixture["policy"]["s0_prediction_floor_m"])
    memory.clear_streak = memory.clear_streak + 1 if fresh_clear else 0
    if not authorized or not capacity or not door_open or egress_active:
        return (0.0, 0.0), forward_margin, predicted_clearance(robot, (0.0, 0.0), tracks, fixture, robust=False), False
    if norm(memory.previous_command) <= 0.05 and memory.clear_streak < int(fixture["policy"]["s0_clear_frames"]):
        return (0.0, 0.0), forward_margin, predicted_clearance(robot, (0.0, 0.0), tracks, fixture, robust=False), False
    # Exact prior candidate values and costs; retreat/lateral are absent by design.
    candidates = [
        (0.0, 0.0), (nominal * 0.45, 0.0), desired,
        (nominal * 0.72, 0.38), (nominal * 0.72, -0.38),
    ]
    best, best_score = (0.0, 0.0), -1e9
    for candidate in candidates:
        if not inside_corridor(scenario, robot, candidate):
            continue
        margin = predicted_clearance(robot, candidate, tracks, fixture, robust=False)
        if margin < float(fixture["policy"]["s0_prediction_floor_m"]):
            continue
        lateral_cost = 0.8 * abs(candidate[1])
        switch_cost = 0.35 * norm(sub(candidate, memory.previous_command))
        if scenario["context"] == "crosswalk":
            lateral_cost *= 2.2
            switch_cost *= 1.8
        if scenario["context"] == "elevator":
            lateral_cost *= 2.8
        score = 2.0 * candidate[0] + 0.18 * min(margin, 2.0) - lateral_cost - switch_cost
        if score > best_score:
            best, best_score = candidate, score
    return best, forward_margin, predicted_clearance(robot, (0.0, 0.0), tracks, fixture, robust=False), False


def context_gate(
    scenario: dict[str, Any], robot: tuple[float, float], phase: str,
    semantic: tuple[bool, bool, bool, bool], fixture: dict[str, Any], t: float,
) -> bool:
    authorized, capacity, door_open, egress_active = semantic
    if scenario["context"] == "crosswalk" and phase != "COMMITTED" and phase != "EXITED":
        return phase == "ENTRY_READY" and authorized
    if scenario["context"] == "elevator" and robot[0] < fixture["policy"]["elevator_door_plane_x_m"]:
        return capacity and door_open and not egress_active
    return True


def robust_candidates(
    scenario: dict[str, Any], robot: tuple[float, float], tracks: dict[str, Track],
    memory: PolicyMemory, fixture: dict[str, Any], phase: str,
) -> list[tuple[str, tuple[float, float], float, float]]:
    nominal = float(
        fixture["simulation"]["elevator_speed_mps"] if scenario["context"] == "elevator"
        else fixture["simulation"]["crosswalk_speed_mps"] if scenario["context"] == "crosswalk"
        else fixture["simulation"]["nominal_speed_mps"]
    )
    result: list[tuple[str, tuple[float, float], float, float]] = []
    robust_floor = float(fixture["policy"]["robust_floor_m"])
    for name, candidate in candidate_set(nominal):
        if phase == "COMMITTED" and candidate[0] < -0.01:
            continue
        if not inside_corridor(scenario, robot, candidate):
            continue
        margin = predicted_clearance(robot, candidate, tracks, fixture, robust=True)
        if margin < robust_floor:
            continue
        progress = candidate[0]
        lateral_cost = 0.46 * abs(candidate[1])
        reverse_cost = 0.72 * max(0.0, -candidate[0])
        switch_cost = 0.22 * norm(sub(candidate, memory.previous_command))
        margin_bonus = 0.24 * min(2.0, margin)
        recenter_gain = abs(robot[1]) - abs(robot[1] + candidate[1] * 0.8)
        score = 2.0 * progress + margin_bonus + 0.9 * recenter_gain - lateral_cost - reverse_cost - switch_cost
        result.append((name, candidate, margin, score))
    return result


def staging_target(scenario: dict[str, Any], robot: tuple[float, float], fixture: dict[str, Any]) -> tuple[float, float]:
    cfg = fixture["policy"]
    if scenario["context"] == "sidewalk":
        return (min(float(scenario["goal"][0]), robot[0] + 0.7), float(cfg["sidewalk_stage_y_m"]))
    if scenario["context"] == "elevator":
        return (float(cfg["elevator_stage_x_m"]), float(cfg["elevator_stage_y_m"]))
    return robot


def choose_robust(
    arm: str, scenario: dict[str, Any], robot: tuple[float, float], tracks: dict[str, Track],
    memory: PolicyMemory, fixture: dict[str, Any], phase: str,
    semantic: tuple[bool, bool, bool, bool], fresh: bool, explicit_free: bool, t: float,
) -> tuple[tuple[float, float], float, float, bool]:
    candidates = robust_candidates(scenario, robot, tracks, memory, fixture, phase)
    by_name = {name: (candidate, margin, score) for name, candidate, margin, score in candidates}
    nominal = float(
        fixture["simulation"]["elevator_speed_mps"] if scenario["context"] == "elevator"
        else fixture["simulation"]["crosswalk_speed_mps"] if scenario["context"] == "crosswalk"
        else fixture["simulation"]["nominal_speed_mps"]
    )
    forward_margin = predicted_clearance(robot, (nominal, 0.0), tracks, fixture, robust=True)
    hold_margin = predicted_clearance(robot, (0.0, 0.0), tracks, fixture, robust=True)
    approach = any(
        (tr.x - robot[0]) * tr.vx + (tr.y - robot[1]) * tr.vy < -0.04
        and norm((tr.x - robot[0], tr.y - robot[1])) < 2.3
        for tr in tracks.values() if tr.existence >= fixture["sensor"]["track_policy_existence"]
    )
    memory.approach_streak = memory.approach_streak + 1 if approach else 0
    gate_open = context_gate(scenario, robot, phase, semantic, fixture, t)
    evidence_clear = fresh and explicit_free and forward_margin >= float(fixture["policy"]["low_risk_clearance_m"])

    # Continue a reachable escape tube selected on an earlier frame instead of
    # stopping in the pedestrian's swept path halfway through the maneuver.
    if memory.escape_target_y is not None:
        remaining_y = memory.escape_target_y - robot[1]
        if abs(remaining_y) <= 0.07:
            memory.escape_target_y = None
        elif arm == "S2" or (arm == "S3" and fresh and not (memory.previous_phase and phase != memory.previous_phase)):
            memory.state = "YIELD_ESCAPE" if arm == "S3" else "HOLD"
            return (0.0, clamp(remaining_y / 0.8, -1.0, 1.0)), forward_margin, hold_margin, True

    if arm == "S1":
        if not gate_open:
            return (0.0, 0.0), forward_margin, hold_margin, False
        if not candidates:
            return (0.0, 0.0), forward_margin, hold_margin, False
        selected = max(candidates, key=lambda row: (row[3], row[0]))
        return selected[1], forward_margin, hold_margin, selected[0].startswith("retreat") or selected[0].startswith("lateral")

    # Context staging for S2/S3.  It is applied before progress scoring.
    hazard = forward_margin < float(fixture["policy"]["low_risk_clearance_m"]) or not gate_open
    if scenario["context"] == "sidewalk" and hazard:
        target = staging_target(scenario, robot, fixture)
        direction = unit(sub(target, robot))
        requested = mul(direction, min(0.58, norm(sub(target, robot)) / max(0.1, 0.8)))
        staged = sorted(candidates, key=lambda row: norm(sub(row[1], requested)))
        if staged:
            by_name["context_stage"] = (staged[0][1], staged[0][2], staged[0][3] + 0.7)
    if scenario["context"] == "elevator" and (not gate_open or phase in {"APPROACH", "STAGE"}):
        target = staging_target(scenario, robot, fixture)
        delta = sub(target, robot)
        if norm(delta) > 0.12:
            requested = mul(unit(delta), min(0.52, norm(delta) / 0.8))
            staged = sorted(candidates, key=lambda row: norm(sub(row[1], requested)))
            if staged:
                by_name["context_stage"] = (staged[0][1], staged[0][2], staged[0][3] + 0.9)

    escape_options = [
        row for row in candidates
        if row[0].startswith("retreat") or row[0].startswith("lateral") or abs(row[1][1]) > 0.25
    ]
    escape = max(escape_options, key=lambda row: (row[2], row[3]), default=None)

    if arm == "S2":
        memory.state = "HOLD" if memory.state not in {"GO", "HOLD"} else memory.state
        high = forward_margin < float(fixture["policy"]["high_risk_clearance_m"])
        if high or not gate_open:
            memory.state = "HOLD"
            memory.clear_streak = 0
            staged = by_name.get("context_stage")
            if staged is not None and scenario["context"] in {"sidewalk", "elevator"}:
                memory.escape_target_y = staging_target(scenario, robot, fixture)[1]
                return staged[0], forward_margin, hold_margin, True
            if scenario["context"] == "elevator" and not gate_open and norm(sub(staging_target(scenario, robot, fixture), robot)) <= 0.14:
                return (0.0, 0.0), forward_margin, hold_margin, False
            if escape is not None and (hold_margin < float(fixture["policy"]["robust_floor_m"]) or scenario["context"] in {"sidewalk", "elevator"}):
                if abs(escape[1][1]) > 0.25:
                    memory.escape_target_y = math.copysign(float(scenario["corridor_half_width_m"]) - 0.05, escape[1][1])
                return escape[1], forward_margin, hold_margin, True
            return (0.0, 0.0), forward_margin, hold_margin, False
        if memory.state == "HOLD":
            memory.clear_streak = memory.clear_streak + 1 if evidence_clear else 0
            if memory.clear_streak < int(fixture["policy"]["s2_release_clear_frames"]):
                return (0.0, 0.0), forward_margin, hold_margin, False
            memory.state = "GO"
        if not candidates:
            memory.state = "HOLD"
            return (0.0, 0.0), forward_margin, hold_margin, False
        selected = max(candidates, key=lambda row: (row[3], row[0]))
        return selected[1], forward_margin, hold_margin, selected[0].startswith(("retreat", "lateral"))

    # S3 explicit asymmetric liveness state machine.
    phase_changed = bool(memory.previous_phase and phase != memory.previous_phase)
    high = forward_margin < float(fixture["policy"]["high_risk_clearance_m"])
    rebound = forward_margin < float(fixture["policy"]["low_risk_clearance_m"])
    if not fresh or phase_changed or not gate_open:
        memory.state, memory.clear_streak, memory.creep_ticks = "BRAKE", 0, 0
    elif high:
        memory.state, memory.clear_streak, memory.creep_ticks = "BRAKE", 0, 0
    elif memory.state in {"CREEP", "GO"} and rebound:
        memory.state, memory.clear_streak, memory.creep_ticks = "BRAKE", 0, 0

    if memory.state == "BRAKE":
        staged = by_name.get("context_stage")
        if staged is not None and not gate_open and scenario["context"] in {"sidewalk", "elevator"}:
            memory.state = "YIELD_ESCAPE"
            memory.escape_target_y = staging_target(scenario, robot, fixture)[1]
            return staged[0], forward_margin, hold_margin, True
        if memory.approach_streak >= int(fixture["policy"]["persistent_approach_frames"]) and escape is not None:
            memory.state = "YIELD_ESCAPE"
            if abs(escape[1][1]) > 0.25:
                memory.escape_target_y = math.copysign(float(scenario["corridor_half_width_m"]) - 0.05, escape[1][1])
            return escape[1], forward_margin, hold_margin, True
        memory.clear_streak = memory.clear_streak + 1 if evidence_clear else 0
        if memory.clear_streak >= int(fixture["policy"]["s3_release_clear_frames"]):
            memory.state, memory.creep_ticks = "CREEP", 0
        else:
            staged = by_name.get("context_stage")
            if staged is not None and hold_margin < float(fixture["policy"]["robust_floor_m"]):
                return staged[0], forward_margin, hold_margin, True
            return (0.0, 0.0), forward_margin, hold_margin, False
    if memory.state == "YIELD_ESCAPE":
        staged = by_name.get("context_stage")
        if staged is not None and not gate_open and scenario["context"] in {"sidewalk", "elevator"}:
            return staged[0], forward_margin, hold_margin, True
        if scenario["context"] == "elevator" and not gate_open and norm(sub(staging_target(scenario, robot, fixture), robot)) <= 0.14:
            memory.state = "BRAKE"
            return (0.0, 0.0), forward_margin, hold_margin, False
        if escape is not None and not evidence_clear:
            if abs(escape[1][1]) > 0.25:
                memory.escape_target_y = math.copysign(float(scenario["corridor_half_width_m"]) - 0.05, escape[1][1])
            return escape[1], forward_margin, hold_margin, True
        memory.state, memory.clear_streak = "BRAKE", 0
        return (0.0, 0.0), forward_margin, hold_margin, False
    if memory.state == "CREEP":
        if rebound or not evidence_clear:
            memory.state, memory.clear_streak, memory.creep_ticks = "BRAKE", 0, 0
            return (0.0, 0.0), forward_margin, hold_margin, False
        memory.creep_ticks += 1
        if memory.creep_ticks >= int(fixture["policy"]["s3_creep_ticks"]):
            memory.state = "GO"
        return (float(fixture["simulation"]["creep_speed_mps"]), 0.0), forward_margin, hold_margin, False
    if not candidates:
        memory.state = "BRAKE"
        return (0.0, 0.0), forward_margin, hold_margin, False
    selected = max(candidates, key=lambda row: (row[3], row[0]))
    return selected[1], forward_margin, hold_margin, selected[0].startswith(("retreat", "lateral"))


def final_monitor(
    scenario: dict[str, Any], robot: tuple[float, float], proposed: tuple[float, float],
    tracks: dict[str, Track], phase: str, semantic: tuple[bool, bool, bool, bool],
    fixture: dict[str, Any], t: float, *, escape_continuation: bool = False,
) -> tuple[tuple[float, float], bool, bool, float]:
    """Shared last deterministic geometry/braking and semantic resource gate."""
    sim = fixture["simulation"]
    hard_floor = float(sim["hard_surface_floor_m"])
    monitor_margin = predicted_clearance(
        robot, proposed, tracks, fixture, robust=True,
        horizon_s=float(sim["final_monitor_horizon_s"]), inflation_sigma=1.0,
    )
    semantic_ok = context_gate(scenario, robot, phase, semantic, fixture, t)
    # Resource denial blocks crossing the resource boundary, not a protective
    # lateral step or retreat on the public side of that boundary.
    projected = add(robot, mul(proposed, float(sim["final_monitor_horizon_s"])))
    if scenario["context"] == "crosswalk" and phase == "CURB_WAIT":
        semantic_ok = projected[0] < float(fixture["policy"]["crosswalk_entry_x_m"])
    if scenario["context"] == "elevator" and not semantic_ok:
        semantic_ok = projected[0] < float(fixture["policy"]["elevator_door_plane_x_m"])
    if phase == "COMMITTED" and proposed[0] < -0.01:
        semantic_ok = False
    if inside_corridor(scenario, robot, proposed) and semantic_ok and monitor_margin >= hard_floor:
        return proposed, False, False, monitor_margin
    if escape_continuation and inside_corridor(scenario, robot, proposed) and semantic_ok:
        # A multi-tick escape was admitted against the full robust tube at its
        # start. During continuation, enforce the current one-step hard floor
        # and require strictly non-worsening separation versus braking in place.
        immediate_proposed = predicted_clearance(
            robot, proposed, tracks, fixture, robust=True,
            horizon_s=float(sim["dt_s"]), inflation_sigma=0.0,
        )
        immediate_hold = predicted_clearance(
            robot, (0.0, 0.0), tracks, fixture, robust=True,
            horizon_s=float(sim["dt_s"]), inflation_sigma=0.0,
        )
        if immediate_proposed >= hard_floor and immediate_proposed >= immediate_hold:
            return proposed, False, False, immediate_proposed
    # Braking command is always the fallback. An unsafe stationary prediction is
    # recorded by the scorer, never silently called a safe admission.
    hold = (0.0, 0.0)
    hold_margin = predicted_clearance(
        robot, hold, tracks, fixture, robust=True,
        horizon_s=float(sim["final_monitor_horizon_s"]), inflation_sigma=1.0,
    )
    return hold, norm(proposed) > 0.01, False, hold_margin


def move_towards(
    current: tuple[float, float], target: tuple[float, float], max_delta: float,
) -> tuple[float, float]:
    delta = sub(target, current)
    length = norm(delta)
    if length <= max_delta or length < 1e-12:
        return target
    return add(current, mul(delta, max_delta / length))


def truth_candidate_clearance(
    scenario: dict[str, Any], robot: tuple[float, float], candidate: tuple[float, float],
    states: dict[str, ActorState], fixture: dict[str, Any], horizon_s: float,
) -> float:
    sim = fixture["simulation"]
    combined = float(sim["robot_radius_m"]) + float(sim["person_radius_m"])
    minimum = 9.0
    steps = max(1, int(round(horizon_s / 0.1)))
    for index in range(1, steps + 1):
        h = index * horizon_s / steps
        rp = add(robot, mul(candidate, h))
        if abs(rp[1]) > float(scenario["corridor_half_width_m"]):
            return -9.0
        for state in states.values():
            if not state.active:
                continue
            pp = (state.x + state.vx * h, state.y + state.vy * h)
            minimum = min(minimum, norm(sub(pp, rp)) - combined)
    return minimum


def oracle_safe_translation_exists(
    scenario: dict[str, Any], robot: tuple[float, float], states: dict[str, ActorState],
    fixture: dict[str, Any], phase: str, semantic: tuple[bool, bool, bool, bool], t: float,
) -> bool:
    nominal = float(fixture["simulation"]["elevator_speed_mps"] if scenario["context"] == "elevator" else fixture["simulation"]["nominal_speed_mps"])
    for _name, candidate in candidate_set(nominal):
        if norm(candidate) <= 0.05:
            continue
        projected = add(robot, mul(candidate, fixture["simulation"]["oracle_horizon_s"]))
        semantic_ok = context_gate(scenario, robot, phase, semantic, fixture, t)
        if scenario["context"] == "crosswalk" and phase == "CURB_WAIT":
            semantic_ok = projected[0] < fixture["policy"]["crosswalk_entry_x_m"]
        if scenario["context"] == "elevator" and not semantic_ok:
            semantic_ok = projected[0] < fixture["policy"]["elevator_door_plane_x_m"]
        if not semantic_ok or (phase == "COMMITTED" and candidate[0] < -0.01):
            continue
        if truth_candidate_clearance(
            scenario, robot, candidate, states, fixture,
            float(fixture["simulation"]["oracle_horizon_s"]),
        ) >= float(fixture["simulation"]["hard_surface_floor_m"]):
            return True
    return False


def truth_ttc(
    robot: tuple[float, float], robot_v: tuple[float, float], states: dict[str, ActorState],
    fixture: dict[str, Any], horizon_s: float = 5.0,
) -> float:
    combined = float(fixture["simulation"]["robot_radius_m"]) + float(fixture["simulation"]["person_radius_m"])
    best = horizon_s
    for state in states.values():
        if not state.active:
            continue
        rel_p = (state.x - robot[0], state.y - robot[1])
        rel_v = (state.vx - robot_v[0], state.vy - robot_v[1])
        speed2 = rel_v[0] ** 2 + rel_v[1] ** 2
        if speed2 < 1e-9:
            continue
        closest_t = clamp(-(rel_p[0] * rel_v[0] + rel_p[1] * rel_v[1]) / speed2, 0.0, horizon_s)
        distance = norm(add(rel_p, mul(rel_v, closest_t)))
        if distance <= combined + float(fixture["simulation"]["near_contact_surface_m"]):
            best = min(best, closest_t)
    return best


def trace_row(values: dict[str, Any]) -> list[Any]:
    missing = [name for name in TRACE_FIELDS if name not in values]
    if missing:
        raise AssertionError(f"trace fields missing: {missing}")
    return [values[name] for name in TRACE_FIELDS]


def run_episode(
    arm: str, scenario: dict[str, Any], base_sensor_seed: int, sensor_seed: int,
    fixture: dict[str, Any], *, include_trace: bool = True,
) -> dict[str, Any]:
    if arm not in ARMS:
        raise ValueError(arm)
    sim = fixture["simulation"]
    dt = float(sim["dt_s"])
    steps = int(round(float(scenario["duration_s"]) / dt))
    rng = random.Random(sensor_seed)
    robot = (float(scenario["start"][0]), float(scenario["start"][1]))
    velocity = (0.0, 0.0)
    states = initialize_actors(scenario)
    # Make t=0 actors active before the first sensing cycle.
    for state, spec in zip(states.values(), scenario["actors"]):
        state.active = float(spec["active_interval_s"][0]) <= 0.0 < float(spec["active_interval_s"][1])
    tracks: dict[str, Track] = {}
    delivery_queue: dict[int, list[dict[str, Any]]] = {}
    memory = PolicyMemory(state="GO" if arm != "S2" else "GO")
    trace: list[list[Any]] = []
    goal_time: float | None = None
    path_length = 0.0
    lateral_travel = 0.0
    false_block_s = 0.0
    false_block_run = 0.0
    maximum_false_block_run = 0.0
    transitions = 0
    acceleration_samples: list[float] = []
    jerk_samples: list[float] = []
    previous_accel = (0.0, 0.0)
    previous_moving = False
    previous_truth_clear = False
    previous_phase = ""
    contact_ticks = near_ticks = actor_stationary_ticks = 0
    intervention_ticks = hard_admission_ticks = 0
    semantic_counts = {key: 0 for key in (
        "hard_floor", "authorization", "reverse_after_entry", "egress", "capacity",
        "door_plane", "staging",
    )}
    release_missing_ticks = retreat_ticks = evasion_ticks = 0
    min_clearance = 9.0
    min_ttc = 5.0
    central_wait_run = 0
    latency_events: list[dict[str, Any]] = []
    pending_latency: dict[str, Any] | None = None
    risk_labels: list[list[float | int]] = []

    for tick in range(steps):
        t = tick * dt
        before = robot
        velocity_before = velocity
        authorized, capacity, door_open, egress_active = semantic_values(scenario, t)
        if scenario["context"] == "crosswalk" and robot[0] >= fixture["policy"]["crosswalk_entry_x_m"]:
            memory.committed = True
        phase = semantic_phase(
            scenario, robot, memory.committed, authorized, capacity, door_open,
            egress_active, fixture, t,
        )
        phase_changed = bool(previous_phase and phase != previous_phase)
        tracks, sensor_fresh, corridor_observed, explicit_free = sensor_and_tracker_step(
            tracks, states, scenario, robot, tick, rng, delivery_queue, fixture,
        )

        semantic = (authorized, capacity, door_open, egress_active)
        if arm == "S0":
            proposed, forward_margin, hold_margin, evasion = s0_command(
                scenario, robot, tracks, memory, fixture, semantic, sensor_fresh, explicit_free,
            )
            memory.state = "GO" if norm(proposed) > 0.05 else "HOLD"
        else:
            proposed, forward_margin, hold_margin, evasion = choose_robust(
                arm, scenario, robot, tracks, memory, fixture, phase, semantic,
                sensor_fresh, explicit_free, t,
            )
        evidence_clear = bool(
            sensor_fresh and explicit_free
            and forward_margin >= float(fixture["policy"]["low_risk_clearance_m"])
        )
        state_before_monitor = memory.state
        accepted, intervention, hard_admission, _monitor_margin = final_monitor(
            scenario, robot, proposed, tracks, phase, semantic, fixture, t,
            escape_continuation=bool(evasion and memory.escape_target_y is not None),
        )
        if intervention and arm == "S3":
            memory.state, memory.clear_streak, memory.creep_ticks = "BRAKE", 0, 0
        decision_event = norm(accepted) > 0.05 and norm(memory.previous_command) <= 0.05
        release_on_missing = bool(
            decision_event and not evasion and memory.state in {"GO", "CREEP"}
            and (not sensor_fresh or not explicit_free)
        )

        velocity = move_towards(
            velocity, accepted, float(sim["max_acceleration_mps2"]) * dt,
        )
        robot = add(robot, mul(velocity, dt))
        actor_step(states, scenario, before, t, dt)
        actual_moving = norm(velocity) > float(sim["stationary_speed_mps"])
        path_increment = norm(sub(robot, before))
        path_length += path_increment
        lateral_travel += abs(robot[1] - before[1])
        accel = mul(sub(velocity, velocity_before), 1.0 / dt)
        acceleration_samples.append(norm(accel))
        jerk_samples.append(norm(mul(sub(accel, previous_accel), 1.0 / dt)))
        previous_accel = accel
        if actual_moving != previous_moving:
            transitions += 1
        previous_moving = actual_moving

        combined = float(sim["robot_radius_m"]) + float(sim["person_radius_m"])
        tick_min = 9.0
        tick_contact = False
        tick_near = False
        actor_stationary = False
        for state in states.values():
            if not state.active:
                continue
            clearance = norm((state.x - robot[0], state.y - robot[1])) - combined
            tick_min = min(tick_min, clearance)
            if clearance < 0.0:
                tick_contact = True
                if norm(velocity) < float(sim["stationary_speed_mps"]) and norm((state.vx, state.vy)) > 0.05:
                    actor_stationary = True
            if clearance < float(sim["near_contact_surface_m"]):
                tick_near = True
        min_clearance = min(min_clearance, tick_min)
        contact_ticks += int(tick_contact)
        near_ticks += int(tick_near)
        actor_stationary_ticks += int(actor_stationary)
        hard_floor = tick_min < float(sim["hard_surface_floor_m"])
        semantic_counts["hard_floor"] += int(hard_floor)

        # Semantic boundary audits use before/after crossing and actual motion.
        auth_violation = bool(
            scenario["context"] == "crosswalk" and not authorized
            and before[0] < fixture["policy"]["crosswalk_entry_x_m"] <= robot[0]
        )
        reverse_violation = bool(
            scenario["context"] == "crosswalk" and memory.committed and velocity[0] < -0.01
        )
        crossed_door = bool(
            scenario["context"] == "elevator"
            and before[0] < fixture["policy"]["elevator_door_plane_x_m"] <= robot[0]
        )
        egress_violation = crossed_door and egress_active
        capacity_violation = crossed_door and not capacity
        door_violation = crossed_door and not door_open
        central_wait = bool(
            arm in {"S2", "S3"} and scenario["context"] == "elevator"
            and (egress_active or not capacity or not door_open)
            and robot[0] >= fixture["policy"]["elevator_stage_x_m"] - 0.12
            and robot[0] < fixture["policy"]["elevator_door_plane_x_m"]
            and robot[1] > -0.36 and not actual_moving
        )
        central_wait_run = central_wait_run + 1 if central_wait else 0
        staging_violation = central_wait_run * dt > 0.6
        for key, value in (
            ("authorization", auth_violation), ("reverse_after_entry", reverse_violation),
            ("egress", egress_violation), ("capacity", capacity_violation),
            ("door_plane", door_violation), ("staging", staging_violation),
        ):
            semantic_counts[key] += int(value)

        oracle_safe = oracle_safe_translation_exists(
            scenario, before, states, fixture, phase, semantic, t,
        )
        truth_forward_margin = truth_candidate_clearance(
            scenario, before,
            (float(sim["elevator_speed_mps"] if scenario["context"] == "elevator" else sim["nominal_speed_mps"]), 0.0),
            states, fixture, float(sim["oracle_horizon_s"]),
        )
        truth_forward_clear = bool(
            truth_forward_margin >= float(sim["hard_surface_floor_m"])
            and context_gate(scenario, before, phase, semantic, fixture, t)
        )
        if not actual_moving and oracle_safe:
            false_block_s += dt
            false_block_run += dt
            maximum_false_block_run = max(maximum_false_block_run, false_block_run)
        else:
            false_block_run = 0.0

        # Separate latency legs. Multiple clear events may occur after re-blocking.
        if truth_forward_clear and not previous_truth_clear:
            if pending_latency is not None:
                pending_latency["censor_reason"] = "superseded"
                latency_events.append(pending_latency)
            pending_latency = {"truth_clear_s": t, "evidence_clear_s": None, "decision_s": None, "motion_s": None}
        if pending_latency is not None and pending_latency["evidence_clear_s"] is None and evidence_clear:
            pending_latency["evidence_clear_s"] = t
        if pending_latency is not None and pending_latency["evidence_clear_s"] is not None and pending_latency["decision_s"] is None and norm(accepted) > 0.05:
            pending_latency["decision_s"] = t
        if pending_latency is not None and pending_latency["decision_s"] is not None and pending_latency["motion_s"] is None and actual_moving:
            pending_latency["motion_s"] = t
            latency_events.append(pending_latency)
            pending_latency = None
        if not truth_forward_clear and previous_truth_clear and pending_latency is not None:
            pending_latency["censor_reason"] = "truth_reblocked"
            latency_events.append(pending_latency)
            pending_latency = None
        previous_truth_clear = truth_forward_clear

        ttc = truth_ttc(robot, velocity, states, fixture)
        min_ttc = min(min_ttc, ttc)
        contact_2s = truth_candidate_clearance(
            scenario, robot, accepted, states, fixture, float(sim["policy_horizon_s"]),
        ) < 0.0
        risk_probability = 1.0 / (1.0 + math.exp(clamp((forward_margin - 0.38) / 0.13, -30.0, 30.0)))
        risk_labels.append([q(risk_probability), int(contact_2s)])
        intervention_ticks += int(intervention)
        hard_admission_ticks += int(hard_admission)
        release_missing_ticks += int(release_on_missing)
        retreat_used = accepted[0] < -0.02
        evasion_used = evasion and norm(accepted) > 0.05
        retreat_ticks += int(retreat_used)
        evasion_ticks += int(evasion_used)

        if include_trace:
            trace.append(trace_row({
                "tick": tick, "time_s": q(t),
                "robot_x_before": q(before[0]), "robot_y_before": q(before[1]),
                "vx_before": q(velocity_before[0]), "vy_before": q(velocity_before[1]),
                "proposed_vx": q(proposed[0]), "proposed_vy": q(proposed[1]),
                "accepted_vx": q(accepted[0]), "accepted_vy": q(accepted[1]),
                "vx_after": q(velocity[0]), "vy_after": q(velocity[1]),
                "robot_x_after": q(robot[0]), "robot_y_after": q(robot[1]),
                "policy_state": memory.state, "semantic_phase": phase,
                "authorized": authorized, "capacity_available": capacity,
                "door_open": door_open, "egress_active": egress_active,
                "sensor_fresh": sensor_fresh, "explicit_free": explicit_free,
                "evidence_clear": evidence_clear, "risk_clearance_m": q(forward_margin),
                "hold_margin_m": q(hold_margin), "forward_margin_m": q(forward_margin),
                "monitor_intervention": intervention, "hard_envelope_admission": hard_admission,
                "oracle_safe_translation": oracle_safe, "truth_forward_clear": truth_forward_clear,
                "minimum_surface_clearance_m": q(tick_min),
                "actor_into_stationary_contact": actor_stationary, "near_contact": tick_near,
                "hard_floor_violation": hard_floor, "authorization_violation": auth_violation,
                "reverse_after_entry_violation": reverse_violation, "egress_violation": egress_violation,
                "capacity_violation": capacity_violation, "door_plane_violation": door_violation,
                "staging_violation": staging_violation, "release_on_missing_only": release_on_missing,
                "retreat_used": retreat_used, "evasion_used": evasion_used,
                "decision_event": decision_event, "translating": actual_moving,
                "minimum_ttc_s": q(ttc), "actors": actor_rows(states), "tracks": track_rows(tracks),
                "corridor_observed": corridor_observed, "semantic_phase_changed": phase_changed,
                "path_increment_m": q(path_increment), "contact_within_2s_truth": contact_2s,
            }))
        if goal_time is None and robot[0] >= float(scenario["goal"][0]):
            goal_time = q((tick + 1) * dt)
            memory.previous_command = accepted
            memory.previous_phase = phase
            previous_phase = phase
            break

        memory.previous_command = accepted
        memory.previous_phase = phase
        previous_phase = phase

    if pending_latency is not None:
        pending_latency["censor_reason"] = "episode_end"
        latency_events.append(pending_latency)
    refusal_correct = bool(scenario["expected_refusal"] and goal_time is None and robot[0] < (
        fixture["policy"]["crosswalk_entry_x_m"] if scenario["context"] == "crosswalk"
        else fixture["policy"]["elevator_door_plane_x_m"] if scenario["context"] == "elevator"
        else 0.0
    ))
    task_success = bool(goal_time is not None or refusal_correct)
    straight_line = norm(sub(
        (float(scenario["goal"][0]), float(scenario["goal"][1])),
        (float(scenario["start"][0]), float(scenario["start"][1])),
    ))
    completed_path_efficiency = q(straight_line / path_length) if goal_time is not None and path_length > 0 else None
    evidence_to_decision = [
        float(event["decision_s"]) - float(event["evidence_clear_s"])
        for event in latency_events if event["decision_s"] is not None and event["evidence_clear_s"] is not None
    ]
    decision_to_motion = [
        float(event["motion_s"]) - float(event["decision_s"])
        for event in latency_events if event["motion_s"] is not None and event["decision_s"] is not None
    ]
    truth_to_evidence = [
        float(event["evidence_clear_s"]) - float(event["truth_clear_s"])
        for event in latency_events if event["evidence_clear_s"] is not None
    ]
    summary = {
        "contact": contact_ticks > 0,
        "contact_ticks": contact_ticks,
        "near_contact": near_ticks > 0,
        "near_contact_ticks": near_ticks,
        "actor_into_stationary_contact": actor_stationary_ticks > 0,
        "actor_into_stationary_ticks": actor_stationary_ticks,
        "minimum_surface_clearance_m": q(min_clearance),
        "hard_envelope_admissions": hard_admission_ticks,
        "final_monitor_interventions": intervention_ticks,
        "semantic_violation_ticks": semantic_counts,
        "goal_reached": goal_time is not None,
        "goal_time_s": goal_time,
        "correct_refusal": refusal_correct,
        "task_success": task_success,
        "safety_gate_pass": bool(
            contact_ticks == 0 and hard_admission_ticks == 0 and sum(semantic_counts.values()) == 0
        ),
        "path_length_m": q(path_length),
        "path_efficiency": completed_path_efficiency,
        "false_block_s": q(false_block_s),
        "maximum_false_block_run_s": q(maximum_false_block_run),
        "wrong_stall": maximum_false_block_run > float(sim["wrong_stall_s"]),
        "deadlock": goal_time is None and false_block_s >= float(sim["deadlock_false_block_s"]),
        "retreat_used": retreat_ticks > 0,
        "retreat_ticks": retreat_ticks,
        "evasion_used": evasion_ticks > 0,
        "evasion_ticks": evasion_ticks,
        "release_on_missing_only": release_missing_ticks,
        "stop_start_transitions": transitions,
        "mean_acceleration_mps2": q(statistics.fmean(acceleration_samples)),
        "p95_acceleration_mps2": percentile(acceleration_samples, 0.95),
        "mean_jerk_mps3": q(statistics.fmean(jerk_samples)),
        "lateral_travel_m": q(lateral_travel),
        "minimum_ttc_s": q(min_ttc),
        "latency_events": latency_events,
        "latency_opportunities": {
            "truth_clear": len(latency_events),
            "evidence_clear": sum(event["evidence_clear_s"] is not None for event in latency_events),
            "decision": sum(event["decision_s"] is not None for event in latency_events),
            "motion": sum(event["motion_s"] is not None for event in latency_events),
        },
        "truth_to_evidence_s": [q(x) for x in truth_to_evidence],
        "evidence_to_decision_s": [q(x) for x in evidence_to_decision],
        "decision_to_motion_s": [q(x) for x in decision_to_motion],
        "risk_labels": risk_labels,
    }
    episode = {
        "schema_version": SCHEMA_VERSION,
        "episode_key": f"{arm}|{scenario['family']}|{base_sensor_seed}",
        "arm": arm,
        "split": scenario["split"],
        "family": scenario["family"],
        "base_family": scenario["base_family"],
        "context": scenario["context"],
        "base_sensor_seed": base_sensor_seed,
        "sensor_seed": sensor_seed,
        "trajectory_signature": scenario["trajectory_signature"],
        "tags": scenario["tags"],
        "otherwise_feasible": scenario["otherwise_feasible"],
        "expected_refusal": scenario["expected_refusal"],
        "trace_fields": list(TRACE_FIELDS),
        "trace": trace,
        "summary": summary,
    }
    episode["trace_sha256"] = sha256_value({"fields": episode["trace_fields"], "trace": trace})
    episode["normalized_sha256"] = sha256_value({key: value for key, value in episode.items() if key != "normalized_sha256"})
    return episode


def calibration(risk_labels: list[list[float | int]]) -> dict[str, Any]:
    if not risk_labels:
        return {"samples": 0, "positives": 0, "brier": None, "ece_10": None}
    brier = statistics.fmean((float(p) - int(label)) ** 2 for p, label in risk_labels)
    ece = 0.0
    for bin_index in range(10):
        lo, hi = bin_index / 10.0, (bin_index + 1) / 10.0
        rows = [(float(p), int(label)) for p, label in risk_labels if lo <= float(p) < hi or (bin_index == 9 and float(p) == 1.0)]
        if rows:
            confidence = statistics.fmean(p for p, _ in rows)
            frequency = statistics.fmean(label for _, label in rows)
            ece += len(rows) / len(risk_labels) * abs(confidence - frequency)
    return {
        "samples": len(risk_labels),
        "positives": sum(int(label) for _, label in risk_labels),
        "brier": q(brier),
        "ece_10": q(ece),
    }


def aggregate_group(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [episode["summary"] for episode in episodes]
    semantic_keys = (
        "hard_floor", "authorization", "reverse_after_entry", "egress", "capacity",
        "door_plane", "staging",
    )
    truth_evidence = [value for summary in summaries for value in summary["truth_to_evidence_s"]]
    evidence_decision = [value for summary in summaries for value in summary["evidence_to_decision_s"]]
    decision_motion = [value for summary in summaries for value in summary["decision_to_motion_s"]]
    risk_labels = [row for summary in summaries for row in summary["risk_labels"]]
    count = len(episodes)
    return {
        "episodes": count,
        "contacts": sum(int(s["contact"]) for s in summaries),
        "near_contacts": sum(int(s["near_contact"]) for s in summaries),
        "actor_into_stationary_contacts": sum(int(s["actor_into_stationary_contact"]) for s in summaries),
        "minimum_surface_clearance_m": min((s["minimum_surface_clearance_m"] for s in summaries), default=None),
        "p05_minimum_surface_clearance_m": percentile([s["minimum_surface_clearance_m"] for s in summaries], 0.05),
        "hard_envelope_admissions": sum(s["hard_envelope_admissions"] for s in summaries),
        "final_monitor_interventions": sum(s["final_monitor_interventions"] for s in summaries),
        "semantic_violation_ticks": {
            key: sum(s["semantic_violation_ticks"][key] for s in summaries) for key in semantic_keys
        },
        "goal_reached": sum(int(s["goal_reached"]) for s in summaries),
        "correct_refusals": sum(int(s["correct_refusal"]) for s in summaries),
        "task_successes": sum(int(s["task_success"]) for s in summaries),
        "safe_task_successes": sum(int(s["task_success"] and s["safety_gate_pass"]) for s in summaries),
        "completion_rate": q(sum(int(s["task_success"]) for s in summaries) / count) if count else None,
        "safe_completion_rate": q(sum(int(s["task_success"] and s["safety_gate_pass"]) for s in summaries) / count) if count else None,
        "goal_rate": q(sum(int(s["goal_reached"]) for s in summaries) / count) if count else None,
        "mean_path_efficiency": q(statistics.fmean(
            s["path_efficiency"] for s in summaries if s["path_efficiency"] is not None
        )) if any(s["path_efficiency"] is not None for s in summaries) else None,
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
            "truth_to_evidence": {
                "eligible": sum(s["latency_opportunities"]["truth_clear"] for s in summaries),
                "n": len(truth_evidence),
                "censored": sum(s["latency_opportunities"]["truth_clear"] for s in summaries) - len(truth_evidence),
                "p50": percentile(truth_evidence, 0.5), "p95": percentile(truth_evidence, 0.95),
            },
            "evidence_to_decision": {
                "eligible": sum(s["latency_opportunities"]["evidence_clear"] for s in summaries),
                "n": len(evidence_decision),
                "censored": sum(s["latency_opportunities"]["evidence_clear"] for s in summaries) - len(evidence_decision),
                "p50": percentile(evidence_decision, 0.5), "p95": percentile(evidence_decision, 0.95),
            },
            "decision_to_motion": {
                "eligible": sum(s["latency_opportunities"]["decision"] for s in summaries),
                "n": len(decision_motion),
                "censored": sum(s["latency_opportunities"]["decision"] for s in summaries) - len(decision_motion),
                "p50": percentile(decision_motion, 0.5), "p95": percentile(decision_motion, 0.95),
            },
        },
        "risk_calibration": calibration(risk_labels),
    }


def forbidden_ticks(group: dict[str, Any]) -> int:
    semantic = group["semantic_violation_ticks"]
    return sum(int(semantic[key]) for key in semantic)


def evaluate_hypotheses(
    episodes: list[dict[str, Any]], arms: dict[str, Any], contexts: dict[str, Any], strata: dict[str, Any],
) -> dict[str, Any]:
    h1_arm: dict[str, Any] = {}
    for arm_name in ("S2", "S3"):
        group = arms[arm_name]
        clauses = {
            "zero_contacts": group["contacts"] == 0,
            "zero_actor_into_stationary_contacts": group["actor_into_stationary_contacts"] == 0,
            "zero_hard_envelope_admissions": group["hard_envelope_admissions"] == 0,
            "zero_semantic_or_current_floor_violations": forbidden_ticks(group) == 0,
        }
        h1_arm[arm_name] = {
            "status": "SUPPORTED" if all(clauses.values()) else "REFUTED",
            "clauses": clauses,
        }
    h1 = all(value["status"] == "SUPPORTED" for value in h1_arm.values())

    ce_s0 = aggregate_group([e for e in episodes if e["arm"] == "S0" and e["context"] in {"crosswalk", "elevator"}])
    ce_s2 = aggregate_group([e for e in episodes if e["arm"] == "S2" and e["context"] in {"crosswalk", "elevator"}])
    completion_gain = q(ce_s2["completion_rate"] - ce_s0["completion_rate"])
    h2_clauses = {
        "crosswalk_elevator_completion_gain_at_least_0_15": completion_gain >= 0.15,
        "sidewalk_completion_not_lower": contexts["S2"]["sidewalk"]["completion_rate"] >= contexts["S0"]["sidewalk"]["completion_rate"],
        "near_contacts_not_higher": arms["S2"]["near_contacts"] <= arms["S0"]["near_contacts"],
        "zero_forbidden_events": forbidden_ticks(arms["S2"]) == 0,
    }

    s2_false = float(arms["S2"]["false_block_s"])
    false_reduction = q((s2_false - float(arms["S3"]["false_block_s"])) / s2_false) if s2_false > 0 else 0.0
    s2_transitions = int(arms["S2"]["stop_start_transitions"])
    transition_reduction = q((s2_transitions - int(arms["S3"]["stop_start_transitions"])) / s2_transitions) if s2_transitions > 0 else 0.0
    ed_p95 = arms["S3"]["latencies_s"]["evidence_to_decision"]["p95"]
    dm_p95 = arms["S3"]["latencies_s"]["decision_to_motion"]["p95"]
    h3_clauses = {
        "false_block_reduction_at_least_20pct": false_reduction >= 0.20,
        "evidence_to_decision_p95_at_most_0_4s": ed_p95 is not None and ed_p95 <= 0.4,
        "decision_to_motion_p95_at_most_0_2s": dm_p95 is not None and dm_p95 <= 0.2,
        "transition_reduction_at_least_20pct": transition_reduction >= 0.20,
        "retains_h1": h1_arm["S3"]["status"] == "SUPPORTED",
        "completion_not_worse": arms["S3"]["completion_rate"] >= arms["S2"]["completion_rate"],
    }

    nonresponsive = strata["S3"]["feasible_nonresponsive"]
    difficult_visibility = strata["S3"]["flicker_or_occlusion"]
    h4_clauses = {
        "feasible_nonresponsive_completion_at_least_80pct": nonresponsive["episodes"] > 0 and nonresponsive["completion_rate"] >= 0.8,
        "flicker_or_occlusion_completion_at_least_80pct": difficult_visibility["episodes"] > 0 and difficult_visibility["completion_rate"] >= 0.8,
        "zero_missing_only_release": arms["S3"]["release_on_missing_only"] == 0,
        "retains_h1": h1_arm["S3"]["status"] == "SUPPORTED",
    }
    return {
        "D2-H1": {"status": "SUPPORTED" if h1 else "REFUTED", "arms": h1_arm},
        "D2-H2": {
            "status": "SUPPORTED" if all(h2_clauses.values()) else "REFUTED",
            "clauses": h2_clauses,
            "crosswalk_elevator_completion_gain_points": q(100.0 * completion_gain),
            "denominators": {"S0": ce_s0["episodes"], "S2": ce_s2["episodes"]},
        },
        "D2-H3": {
            "status": "SUPPORTED" if all(h3_clauses.values()) else "REFUTED",
            "clauses": h3_clauses,
            "false_block_reduction_fraction": false_reduction,
            "transition_reduction_fraction": transition_reduction,
        },
        "D2-H4": {
            "status": "SUPPORTED" if all(h4_clauses.values()) else "REFUTED",
            "clauses": h4_clauses,
            "denominators": {
                "feasible_nonresponsive": nonresponsive["episodes"],
                "flicker_or_occlusion": difficult_visibility["episodes"],
            },
        },
    }


def aggregate_all(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {arm_name: aggregate_group([e for e in episodes if e["arm"] == arm_name]) for arm_name in ARMS}
    contexts = {
        arm_name: {
            context: aggregate_group([e for e in episodes if e["arm"] == arm_name and e["context"] == context])
            for context in ("sidewalk", "crosswalk", "elevator")
        }
        for arm_name in ARMS
    }
    families = {
        arm_name: {
            family: aggregate_group([e for e in episodes if e["arm"] == arm_name and e["family"] == family])
            for family in sorted({episode["family"] for episode in episodes})
        }
        for arm_name in ARMS
    }
    strata: dict[str, dict[str, Any]] = {}
    for arm_name in ARMS:
        arm_eps = [e for e in episodes if e["arm"] == arm_name]
        strata[arm_name] = {
            "responsive": aggregate_group([e for e in arm_eps if "responsive" in e["tags"]]),
            "nonresponsive": aggregate_group([e for e in arm_eps if "nonresponsive" in e["tags"]]),
            "feasible_nonresponsive": aggregate_group([
                e for e in arm_eps if "nonresponsive" in e["tags"] and e["otherwise_feasible"]
            ]),
            "flicker_or_occlusion": aggregate_group([
                e for e in arm_eps if "clear_flicker" in e["tags"] or "occlusion" in e["tags"]
            ]),
            "otherwise_feasible": aggregate_group([e for e in arm_eps if e["otherwise_feasible"]]),
            "expected_refusal": aggregate_group([e for e in arm_eps if e["expected_refusal"]]),
        }
    hypotheses = evaluate_hypotheses(episodes, arms, contexts, strata)
    return {
        "arms": arms,
        "contexts": contexts,
        "families": families,
        "strata": strata,
        "hypotheses": hypotheses,
    }


def verify_frozen_manifest(path: Path) -> dict[str, Any]:
    frozen = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    failures = []
    for relative, expected in frozen["files"].items():
        target = base / relative
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        if actual != expected:
            failures.append({"file": relative, "expected": expected, "actual": actual})
    if failures:
        raise RuntimeError(f"frozen source validation failed: {failures}")
    return frozen


def write_json(path: Path, value: Any, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(
        value, sort_keys=True, indent=2 if pretty else None,
        separators=None if pretty else (",", ":"), allow_nan=False,
    ) + "\n"
    path.write_text(rendered, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=directory / "fixtures.json")
    parser.add_argument("--manifest", type=Path, default=directory / "episode_manifest.json")
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--split", choices=("train", "development", "test"), default="development")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--digest-output", type=Path)
    parser.add_argument("--frozen-manifest", type=Path)
    parser.add_argument("--no-trace", action="store_true", help="development convenience only; forbidden for test")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fixture = json.loads(args.fixtures.read_text(encoding="utf-8"))
    if args.write_manifest:
        manifest = build_episode_manifest(fixture)
        write_json(args.manifest, manifest, pretty=True)
        print(json.dumps({"wrote_manifest": str(args.manifest), "episodes": len(manifest["episodes"])}, sort_keys=True))
        return 0
    if args.output is None:
        raise SystemExit("--output is required for rollout")
    if args.split == "test" and args.frozen_manifest is None:
        raise SystemExit("test rollout requires --frozen-manifest")
    frozen = verify_frozen_manifest(args.frozen_manifest) if args.frozen_manifest else None
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["generated_from_fixture_sha256"] != sha256_value(fixture):
        raise SystemExit("fixture/episode manifest lineage mismatch")
    selected = [entry for entry in manifest["episodes"] if entry["split"] == args.split]
    if args.split == "test" and len(selected) != int(fixture["expected_test_inventory"]["total_episodes"]):
        raise SystemExit(f"test inventory mismatch: {len(selected)}")
    if args.split == "test" and args.no_trace:
        raise SystemExit("test rollout requires full trace")
    started = time.monotonic()
    episodes = []
    for index, entry in enumerate(selected, 1):
        scenario = manifest["scenarios"][entry["family"]]
        episodes.append(run_episode(
            entry["arm"], scenario, int(entry["base_sensor_seed"]), int(entry["sensor_seed"]),
            fixture, include_trace=not args.no_trace,
        ))
        if index % 100 == 0:
            print(json.dumps({"progress": index, "total": len(selected)}, sort_keys=True), file=sys.stderr)
    digest_payload = {
        "schema_version": SCHEMA_VERSION,
        "study": "DSP-2",
        "split": args.split,
        "episode_digests": {episode["episode_key"]: episode["normalized_sha256"] for episode in sorted(episodes, key=lambda e: e["episode_key"])},
    }
    digest_payload["aggregate_sha256"] = sha256_value(digest_payload["episode_digests"])
    aggregate = aggregate_all(episodes)
    result = {
        "schema_version": SCHEMA_VERSION,
        "study": "DSP-2",
        "evidence_tier": fixture["evidence_tier"],
        "split": args.split,
        "run_metadata": {
            "pid": os.getpid(),
            "runtime_s": q(time.monotonic() - started),
            "python": sys.version.split()[0],
            "frozen_manifest_sha256": hashlib.sha256(args.frozen_manifest.read_bytes()).hexdigest() if args.frozen_manifest else None,
        },
        "fixture_sha256": sha256_value(fixture),
        "episode_manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "trace_fields": list(TRACE_FIELDS),
        "inventory": {
            "episodes": len(episodes),
            "arms": {arm_name: sum(e["arm"] == arm_name for e in episodes) for arm_name in ARMS},
            "families": len({e["family"] for e in episodes}),
            "base_sensor_seeds": len({e["base_sensor_seed"] for e in episodes}),
        },
        "normalized_episode_digest": digest_payload["aggregate_sha256"],
        "episodes": episodes,
        "aggregate": aggregate,
    }
    write_json(args.output, result)
    digest_path = args.digest_output or args.output.with_suffix(".digests.json")
    write_json(digest_path, digest_payload, pretty=True)
    print(json.dumps({
        "output": str(args.output), "digest_output": str(digest_path),
        "episodes": len(episodes), "normalized_episode_digest": digest_payload["aggregate_sha256"],
        "runtime_s": result["run_metadata"]["runtime_s"],
        "hypotheses": {key: value["status"] for key, value in aggregate["hypotheses"].items()},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
