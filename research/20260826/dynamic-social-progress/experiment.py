"""Frozen, deterministic 2-D social-progress experiment.

This is deliberately independent of Parcel's product path.  It tests policy
mechanisms against authored geometry; it is not a physical safety validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent
ARMS = ("A0", "A1", "A2", "A3", "A4")


@dataclass(frozen=True)
class Actor:
    actor_id: str
    kind: str
    p0: tuple[float, float]
    velocity: tuple[float, float]
    stop_at_s: float | None = None
    turn_at_s: float | None = None
    turn_velocity: tuple[float, float] | None = None
    hidden: tuple[float, float] | None = None
    ghost: bool = False

    def position(self, t: float) -> np.ndarray:
        p = np.asarray(self.p0, dtype=float)
        v = np.asarray(self.velocity, dtype=float)
        if self.stop_at_s is not None:
            return p + v * min(t, self.stop_at_s)
        if self.turn_at_s is not None and self.turn_velocity is not None:
            before = min(t, self.turn_at_s)
            after = max(0.0, t - self.turn_at_s)
            return p + v * before + np.asarray(self.turn_velocity) * after
        return p + v * t

    def visible(self, t: float) -> bool:
        if self.ghost:
            # Authored false detection exists briefly, then explicit free-space
            # observations should be allowed to retire it.
            return 1.5 <= t < 4.0
        return self.hidden is None or not (self.hidden[0] <= t < self.hidden[1])


@dataclass
class Track:
    mean: np.ndarray
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2))
    variance: float = 0.02
    existence: float = 0.75
    last_seen: float = 0.0
    seen_streak: int = 1
    missed: bool = False


@dataclass(frozen=True)
class Scenario:
    template_id: str
    context: str
    goal_x: float
    width: float
    authorized: bool
    capacity: bool
    egress_until_s: float
    expected_refusal: bool
    actors: tuple[Actor, ...]


def scenario_for(template_id: str, seed: int) -> Scenario:
    del seed  # stochasticity is sensor-only; authored truth is seed invariant.
    context, rest = template_id.split("_", 1)
    base = rest.rsplit("_", 1)[0]
    actors: list[Actor] = []
    goal, width = (8.0, 1.35) if context == "sidewalk" else (6.0, 1.2)
    authorized, capacity, egress, refusal = True, True, 0.0, False

    if context == "sidewalk":
        if base == "same_flow":
            actors.append(Actor("p0", "stranger", (2.2, 0.0), (0.32, 0.0)))
        elif base == "oncoming":
            actors.append(Actor("p0", "stranger", (7.0, 0.0), (-0.65, 0.0)))
        elif base == "crossing":
            actors.append(Actor("p0", "stranger", (3.5, -2.0), (0.0, 0.62)))
        elif base in {"sudden_stop", "sudden_turn"}:
            turn_v = (0.0, 0.62) if base == "sudden_turn" else None
            actors.append(
                Actor(
                    "p0", "stranger", (2.0, 0.0), (0.55, 0.0),
                    stop_at_s=4.2 if turn_v is None else None,
                    turn_at_s=4.2 if turn_v is not None else None,
                    turn_velocity=turn_v,
                )
            )
        elif base == "group_gap":
            actors.extend(
                [
                    Actor("p0", "stranger", (3.4, -1.8), (0.0, 0.55)),
                    Actor("p1", "stranger", (4.3, 1.8), (0.0, -0.55), turn_at_s=3.0, turn_velocity=(0.0, -0.2)),
                ]
            )
        elif base == "false_positive":
            actors.append(Actor("ghost", "stranger", (2.6, 0.25), (0.0, 0.0), ghost=True))
        elif base == "occluded_survivor":
            actors.append(Actor("p0", "stranger", (3.4, 0.0), (0.0, 0.0), hidden=(2.8, 8.5)))
        # owner_parallel is intentionally clear: owner consent/identity is supplied.
    elif context == "crosswalk":
        if base == "unauthorized":
            authorized, refusal = False, True
        elif base == "lateral":
            actors.append(Actor("p0", "stranger", (3.0, -1.8), (0.0, 0.6)))
        elif base == "late_entry":
            actors.append(Actor("p0", "stranger", (4.1, 1.9), (0.0, -0.72), hidden=(0.0, 3.2)))
        elif base == "owner_group":
            actors.extend(
                [
                    Actor("p0", "stranger", (2.8, -1.5), (0.0, 0.5)),
                    Actor("p1", "stranger", (3.8, 1.5), (0.0, -0.45)),
                ]
            )
        elif base == "persistent":
            actors.append(Actor("p0", "stranger", (3.0, 0.0), (0.0, 0.0)))
    else:
        goal, width = 3.2, 0.62
        if base in {"egress", "temporary_clear", "occluded_egress"}:
            hidden = (1.2, 4.0) if base == "occluded_egress" else None
            v = (-0.48, 0.0) if base != "temporary_clear" else (-0.62, 0.0)
            actors.append(Actor("p0", "egress", (2.7, 0.0), v, hidden=hidden))
            egress = 5.5 if base != "temporary_clear" else 4.2
        elif base == "occupied":
            actors.append(Actor("p0", "stranger", (2.45, 0.28), (0.0, 0.0)))
        elif base == "capacity_full":
            capacity, refusal = False, True
            actors.extend(
                [Actor("p0", "stranger", (2.3, -0.25), (0.0, 0.0)), Actor("p1", "stranger", (2.3, 0.25), (0.0, 0.0))]
            )
        elif base == "narrow":
            actors.append(Actor("p0", "stranger", (2.6, 0.32), (0.0, 0.0)))
    return Scenario(template_id, context, goal, width, authorized, capacity, egress, refusal, tuple(actors))


def features(clearance: float, rel: np.ndarray, bearing: float, track: Track, context: str, kind: str) -> np.ndarray:
    return np.asarray(
        [
            np.clip(clearance, -0.5, 3.0),
            np.clip(rel[0], -2.0, 2.0),
            np.clip(rel[1], -2.0, 2.0),
            math.cos(bearing),
            math.sin(bearing),
            np.clip(track.variance, 0.0, 1.5),
            np.clip(track.existence, 0.0, 1.0),
            float(context == "crosswalk"),
            float(context == "elevator"),
            float(kind == "egress"),
        ]
    )


def sigmoid(x: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


def train_critic(fixtures: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
    def make(split: str) -> tuple[np.ndarray, np.ndarray]:
        xs: list[np.ndarray] = []
        ys: list[int] = []
        sim = fixtures["simulation"]
        for template in fixtures["splits"][split]["template_ids"]:
            for seed in fixtures["splits"][split]["seeds"]:
                rng = np.random.default_rng(seed + 991)
                sc = scenario_for(template, seed)
                for _ in range(90):
                    t = float(rng.uniform(0.0, 12.0))
                    robot = np.asarray([min(sc.goal_x, 0.62 * t), float(rng.uniform(-0.3, 0.3))])
                    robot_v = np.asarray([0.8, 0.0])
                    if sc.actors:
                        actor = sc.actors[int(rng.integers(0, len(sc.actors)))]
                        if actor.ghost:
                            continue
                        pos = actor.position(t) + rng.normal(0.0, sim["sensor_noise_sigma_m"], 2)
                        apos2 = actor.position(t + 2.0)
                        av = (apos2 - actor.position(t)) / 2.0
                        track = Track(pos, av, variance=float(rng.uniform(0.01, 0.25)), existence=float(rng.uniform(0.65, 1.0)))
                        relp = pos - robot
                        relv = av - robot_v
                        clearance = float(np.linalg.norm(relp) - sim["robot_radius_m"] - sim["person_radius_m"])
                        bearing = math.atan2(relp[1], relp[0])
                        future = [
                            np.linalg.norm(actor.position(t + h) - (robot + robot_v * h)) - sim["robot_radius_m"] - sim["person_radius_m"]
                            for h in np.linspace(0.1, 2.0, 20)
                        ]
                        label = int(min(future) < 0.0)
                    else:
                        relp = np.asarray([float(rng.uniform(0.3, 4.0)), float(rng.uniform(-1.5, 1.5))])
                        track = Track(robot + relp, np.zeros(2), variance=0.02, existence=0.9)
                        relv = -robot_v
                        clearance = float(np.linalg.norm(relp) - 0.6)
                        bearing = math.atan2(relp[1], relp[0])
                        label = 0
                    xs.append(features(clearance, relv, bearing, track, sc.context, "stranger"))
                    ys.append(label)
        return np.stack(xs), np.asarray(ys, dtype=float)

    x_train, y_train = make("train")
    x_dev, y_dev = make("dev")
    mean, scale = x_train.mean(axis=0), x_train.std(axis=0) + 1e-6
    z = (x_train - mean) / scale
    zd = (x_dev - mean) / scale
    z = np.column_stack([np.ones(len(z)), z])
    zd = np.column_stack([np.ones(len(zd)), zd])
    w = np.zeros(z.shape[1])
    cfg = fixtures["a4"]
    for _ in range(cfg["iterations"]):
        p = sigmoid(z @ w)
        grad = z.T @ (p - y_train) / len(z)
        grad[1:] += cfg["l2"] * w[1:]
        w -= cfg["learning_rate"] * grad
    pdev = np.asarray(sigmoid(zd @ w))
    candidates = cfg["candidate_thresholds"]
    valid = []
    for threshold in candidates:
        pred = pdev >= threshold
        fn = int(np.sum((pred == 0) & (y_dev == 1)))
        positives = max(1, int(np.sum(y_dev == 1)))
        fnr = fn / positives
        progress = float(np.mean(~pred))
        if fnr <= cfg["maximum_dev_false_negative_rate"]:
            valid.append((progress, threshold, fnr))
    if valid:
        _, threshold, dev_fnr = max(valid)
    else:
        threshold, dev_fnr = min(
            ((t, float(np.sum((pdev < t) & (y_dev == 1))) / max(1, int(np.sum(y_dev == 1)))) for t in candidates),
            key=lambda pair: (pair[1], pair[0]),
        )
    info = {
        "train_examples": len(y_train), "train_positive_rate": float(y_train.mean()),
        "dev_examples": len(y_dev), "dev_positive_rate": float(y_dev.mean()),
        "selected_threshold": threshold, "dev_false_negative_rate": dev_fnr,
        "selection_rule": "highest predicted-progress listed threshold with dev FNR <= 0.01; otherwise minimum-FNR fallback",
    }
    return info, w, mean, scale


def track_step(
    tracks: dict[str, Track], sc: Scenario, t: float, robot: np.ndarray,
    rng: np.random.Generator, fixtures: dict[str, Any], measurement_queue: list[list[tuple[str, np.ndarray, str]]],
) -> tuple[dict[str, Track], set[str], bool]:
    cfg = fixtures["simulation"]
    measurements: list[tuple[str, np.ndarray, str]] = []
    corridor_observed = True
    for actor in sc.actors:
        visible = actor.visible(t)
        if not visible and not actor.ghost:
            corridor_observed = False
        if visible and rng.random() >= cfg["sensor_dropout_probability"]:
            measurements.append((actor.actor_id, actor.position(t) + rng.normal(0.0, cfg["sensor_noise_sigma_m"], 2), actor.kind))
    measurement_queue.append(measurements)
    delayed = measurement_queue.pop(0) if len(measurement_queue) > cfg["sensor_latency_ticks"] else []
    seen: set[str] = set()
    for actor_id, pos, _ in delayed:
        seen.add(actor_id)
        if actor_id in tracks:
            tr = tracks[actor_id]
            dt_seen = max(cfg["dt_s"], t - tr.last_seen)
            measured_v = (pos - tr.mean) / dt_seen
            tr.velocity = 0.65 * tr.velocity + 0.35 * measured_v
            tr.mean = 0.7 * pos + 0.3 * (tr.mean + tr.velocity * cfg["dt_s"])
            tr.variance = max(0.012, 0.58 * tr.variance)
            tr.existence = min(0.995, tr.existence + 0.16)
            tr.last_seen, tr.seen_streak, tr.missed = t, tr.seen_streak + 1, False
        else:
            tracks[actor_id] = Track(pos.copy(), last_seen=t)
    for actor_id in list(tracks):
        if actor_id not in seen:
            tr = tracks[actor_id]
            tr.mean = tr.mean + tr.velocity * cfg["dt_s"]
            tr.variance = min(1.5, tr.variance + (0.018 if corridor_observed else 0.055))
            tr.existence *= 0.74 if corridor_observed else 0.97
            tr.seen_streak = 0
            tr.missed = True
            if tr.existence < 0.04:
                del tracks[actor_id]
    return tracks, seen, corridor_observed


def predicted_clearance(robot: np.ndarray, velocity: np.ndarray, tr: Track, mixture: bool) -> float:
    minima: list[float] = []
    for person_v in ([tr.velocity] if not mixture else [tr.velocity, np.zeros(2), np.asarray([tr.velocity[0] * 0.55, tr.velocity[1] + 0.45])]):
        vals = []
        for h in np.linspace(0.0, 2.0, 21):
            rp = robot + velocity * h
            pp = tr.mean + person_v * h
            vals.append(float(np.linalg.norm(pp - rp) - 0.60))
        minima.append(min(vals))
    uncertainty = (1.5 if mixture else 0.5) * math.sqrt(tr.variance)
    return min(minima) - uncertainty


def allowed_by_envelope(robot: np.ndarray, velocity: np.ndarray, tracks: dict[str, Track], mixture: bool) -> tuple[bool, float]:
    worst = 9.0
    for tr in tracks.values():
        if tr.existence < (0.18 if mixture else 0.35):
            continue
        clearance = predicted_clearance(robot, velocity, tr, mixture)
        worst = min(worst, clearance)
        if clearance < 0.15:
            return False, worst
    return True, worst


def critic_probability(
    robot: np.ndarray, velocity: np.ndarray, tracks: dict[str, Track], sc: Scenario,
    weights: np.ndarray, mean: np.ndarray, scale: np.ndarray,
) -> float:
    probs = [0.0]
    for actor_id, tr in tracks.items():
        relp = tr.mean - robot
        clearance = float(np.linalg.norm(relp) - 0.60)
        relv = tr.velocity - velocity
        bearing = math.atan2(relp[1], relp[0])
        kind = "egress" if actor_id.startswith("egress") else "stranger"
        x = features(clearance, relv, bearing, tr, sc.context, kind)
        z = np.r_[1.0, (x - mean) / scale]
        probs.append(float(sigmoid(z @ weights)))
    return max(probs)


def command(
    arm: str, sc: Scenario, robot: np.ndarray, tracks: dict[str, Track], clear_streak: int,
    t: float, model: tuple[np.ndarray, np.ndarray, np.ndarray, float], previous: np.ndarray,
    corridor_observed: bool,
) -> tuple[np.ndarray, int, bool]:
    nominal = 0.48 if sc.context == "elevator" else 0.8
    desired = np.asarray([nominal, 0.0])
    release_on_missing = False
    if arm == "A0":
        blocked = any(tr.existence >= 0.35 and np.linalg.norm(tr.mean - robot) - 0.60 < 1.2 for tr in tracks.values())
        return (np.zeros(2) if blocked else desired), (0 if blocked else clear_streak + 1), bool(blocked and any(tr.missed for tr in tracks.values()))

    mixture = arm in {"A2", "A3", "A4"}
    forward_ok, predicted = allowed_by_envelope(robot, desired, tracks, mixture)
    fresh_clear = corridor_observed and all(
        predicted_clearance(robot, desired, tr, mixture) >= 0.15
        for tr in tracks.values()
        if tr.existence >= 0.18
    )
    clear_streak = clear_streak + 1 if fresh_clear else 0
    if arm in {"A1", "A2"}:
        if not forward_ok or clear_streak < 2:
            release_on_missing = previous[0] < 0.05 and not forward_ok and any(tr.missed for tr in tracks.values())
            return np.zeros(2), clear_streak, release_on_missing
        speed_scale = float(np.clip((predicted - 0.15) / 0.75, 0.25, 1.0))
        return desired * speed_scale, clear_streak, False

    # Authored semantic resource gates precede trajectory scoring.
    if not sc.authorized or not sc.capacity or t < sc.egress_until_s:
        return np.zeros(2), clear_streak, False
    # A3/A4 inherit A2's evidence-conditioned release. Once translating,
    # candidate scoring may continue without introducing stop/start chatter.
    if np.linalg.norm(previous) <= 0.05 and clear_streak < 2:
        return np.zeros(2), clear_streak, False
    candidates = [
        np.zeros(2), np.asarray([nominal * 0.45, 0.0]), desired,
        np.asarray([nominal * 0.72, 0.38]), np.asarray([nominal * 0.72, -0.38]),
    ]
    weights, mean, scale, threshold = model
    best, best_score = np.zeros(2), -1e9
    for candidate in candidates:
        if abs(robot[1] + candidate[1] * 0.8) > sc.width:
            continue
        ok, margin = allowed_by_envelope(robot, candidate, tracks, True)
        if not ok:
            continue
        progress = candidate[0]
        lateral_cost = 0.8 * abs(candidate[1])
        switch_cost = 0.35 * float(np.linalg.norm(candidate - previous))
        if sc.context == "crosswalk":
            lateral_cost *= 2.2
            switch_cost *= 1.8
        if sc.context == "elevator":
            lateral_cost *= 2.8
        score = 2.0 * progress + 0.18 * min(margin, 2.0) - lateral_cost - switch_cost
        if arm == "A4":
            probability = critic_probability(robot, candidate, tracks, sc, weights, mean, scale)
            score -= 1.1 * probability + (0.45 if probability >= threshold else 0.0)
        if score > best_score:
            best, best_score = candidate, score
    return best, clear_streak, False


def oracle_safe(sc: Scenario, robot: np.ndarray, t: float, candidate: np.ndarray, fixtures: dict[str, Any]) -> bool:
    if (not sc.authorized or not sc.capacity or t < sc.egress_until_s) and np.linalg.norm(candidate) > 0.05:
        return False
    for h in np.linspace(0.1, fixtures["simulation"]["oracle_horizon_s"], 5):
        rp = robot + candidate * h
        if abs(rp[1]) > sc.width:
            return False
        for actor in sc.actors:
            if actor.ghost:
                continue
            clearance = np.linalg.norm(actor.position(t + h) - rp) - 0.60
            if clearance < fixtures["simulation"]["hard_surface_floor_m"]:
                return False
    return True


def run_episode(
    arm: str, template: str, seed: int, fixtures: dict[str, Any],
    model: tuple[np.ndarray, np.ndarray, np.ndarray, float],
) -> dict[str, Any]:
    sc = scenario_for(template, seed)
    cfg = fixtures["simulation"]
    # Identical seed gives every arm the same per-tick sensor mutation stream.
    rng = np.random.default_rng(seed)
    robot = np.asarray([0.0, 0.0])
    tracks: dict[str, Track] = {}
    queue: list[list[tuple[str, np.ndarray, str]]] = []
    clear_streak = 2
    previous = np.zeros(2)
    clearances: list[float] = []
    false_block_s = unsafe_motion_s = 0.0
    wrong_run = max_wrong_run = 0.0
    contacts = near = 0
    actor_into_stationary_ticks = 0
    transitions = 0
    accelerations: list[float] = []
    lateral_distance = 0.0
    semantic = {"authorization": 0, "egress": 0, "capacity": 0, "hard_floor": 0}
    release_on_missing = 0
    truth_occupied: list[bool] = []
    moving: list[bool] = []
    visibility: list[bool] = []
    evidence_clear: list[bool] = []
    time_to_goal: float | None = None
    steps = int(cfg["duration_s"] / cfg["dt_s"])
    candidates = [np.asarray([0.4, 0.0]), np.asarray([0.6, 0.35]), np.asarray([0.6, -0.35])]
    for tick in range(steps):
        t = tick * cfg["dt_s"]
        tracks, _, corridor_observed = track_step(tracks, sc, t, robot, rng, fixtures, queue)
        nominal = 0.48 if sc.context == "elevator" else 0.8
        sensing_says_clear = corridor_observed and all(
            predicted_clearance(robot, np.asarray([nominal, 0.0]), tr, True) >= 0.15
            for tr in tracks.values()
            if tr.existence >= 0.18
        )
        velocity, clear_streak, _ = command(
            arm, sc, robot, tracks, clear_streak, t, model, previous, corridor_observed,
        )
        is_moving = bool(np.linalg.norm(velocity) > 0.05)
        release_on_missing += int(is_moving and np.linalg.norm(previous) <= 0.05 and not corridor_observed)
        safe_exists = any(oracle_safe(sc, robot, t, c, fixtures) for c in candidates)
        if not is_moving and safe_exists:
            false_block_s += cfg["dt_s"]
            wrong_run += cfg["dt_s"]
            max_wrong_run = max(max_wrong_run, wrong_run)
        else:
            wrong_run = 0.0
        if is_moving and not safe_exists:
            unsafe_motion_s += cfg["dt_s"]
        if is_moving and not sc.authorized:
            semantic["authorization"] += 1
        if is_moving and t < sc.egress_until_s:
            semantic["egress"] += 1
        if is_moving and not sc.capacity:
            semantic["capacity"] += 1
        next_robot = robot + velocity * cfg["dt_s"]
        current_min = 9.0
        contact_actor_advancing = False
        for actor in sc.actors:
            if actor.ghost:
                continue
            clearance = float(np.linalg.norm(actor.position(t + cfg["dt_s"]) - next_robot) - 0.60)
            current_min = min(current_min, clearance)
            actor_speed = float(np.linalg.norm(actor.position(t + cfg["dt_s"]) - actor.position(t)) / cfg["dt_s"])
            contact_actor_advancing |= clearance < 0.0 and actor_speed > 0.05
        clearances.append(current_min)
        if current_min < 0.0:
            contacts += 1
            actor_into_stationary_ticks += int(not is_moving and contact_actor_advancing)
        if current_min < cfg["near_contact_surface_m"]:
            near += 1
        if is_moving and current_min < cfg["hard_surface_floor_m"]:
            semantic["hard_floor"] += 1
        transitions += int(is_moving != (np.linalg.norm(previous) > 0.05))
        accelerations.append(float(np.linalg.norm(velocity - previous) / cfg["dt_s"]))
        lateral_distance += abs(float(velocity[1])) * cfg["dt_s"]
        # Truth occupancy is a forward-corridor state, distinct from radial proximity.
        occupied = any(
            not actor.ghost
            and 0.0 < actor.position(t)[0] - robot[0] < 1.7
            and abs(actor.position(t)[1] - robot[1]) < 0.52
            for actor in sc.actors
        )
        truth_occupied.append(occupied)
        visibility.append(corridor_observed)
        evidence_clear.append(sensing_says_clear)
        moving.append(is_moving)
        robot = next_robot
        previous = velocity
        if robot[0] >= sc.goal_x:
            time_to_goal = t + cfg["dt_s"]
            break

    refusal_ok = robot[0] < 0.25
    completed = bool(refusal_ok if sc.expected_refusal else time_to_goal is not None)
    # First transition to continuously-clear truth; separately record visible clear.
    unblock: list[float] = []
    visible_unblock: list[float] = []
    evidence_to_motion: list[float] = []
    window = round(1.0 / cfg["dt_s"])
    for i in range(1, max(1, len(truth_occupied) - window)):
        if truth_occupied[i - 1] and not any(truth_occupied[i : i + window]):
            later = next((j for j in range(i, len(moving)) if moving[j]), None)
            if later is not None:
                latency = (later - i) * cfg["dt_s"]
                unblock.append(latency)
                if all(visibility[i : min(i + 2, len(visibility))]):
                    visible_unblock.append(latency)
            break
    for i in range(1, len(evidence_clear)):
        if not evidence_clear[i - 1] and evidence_clear[i]:
            later = next((j for j in range(i, len(moving)) if moving[j]), None)
            if later is not None:
                evidence_to_motion.append((later - i) * cfg["dt_s"])
    min_clear = min(clearances) if clearances else 9.0
    return {
        "arm": arm, "template_id": template, "seed": seed, "context": sc.context,
        "completed": completed, "time_to_goal_s": time_to_goal,
        "final_x_m": float(robot[0]), "minimum_surface_clearance_m": min_clear,
        "contact": min_clear < 0.0, "near_contact": min_clear < cfg["near_contact_surface_m"],
        "contact_ticks": contacts, "near_contact_ticks": near,
        "actor_into_stationary_contact": actor_into_stationary_ticks > 0,
        "actor_into_stationary_contact_ticks": actor_into_stationary_ticks,
        "false_block_s": false_block_s, "unsafe_motion_s": unsafe_motion_s,
        "wrong_stall": max_wrong_run > 1.0,
        "deadlock": (not completed) and false_block_s >= 8.0,
        "stop_start_transitions": transitions, "lateral_distance_m": lateral_distance,
        "mean_acceleration_proxy": float(np.mean(accelerations)) if accelerations else 0.0,
        "semantic_violations": semantic, "release_on_missing_count": release_on_missing,
        "unblock_latencies_s": unblock, "visible_unblock_latencies_s": visible_unblock,
        "evidence_to_motion_latencies_s": evidence_to_motion,
    }


def rank_auc(y: np.ndarray, p: np.ndarray) -> float:
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    return float(np.mean(pos[:, None] > neg[None, :]) + 0.5 * np.mean(pos[:, None] == neg[None, :]))


def critic_test_metrics(fixtures: dict[str, Any], weights: np.ndarray, mean: np.ndarray, scale: np.ndarray, threshold: float) -> dict[str, float]:
    # Reuse the frozen static counterfactual construction with disjoint test IDs/seeds.
    copy = json.loads(json.dumps(fixtures))
    copy["splits"]["dev"] = copy["splits"]["test"]
    _, _, _, _ = weights, mean, scale, threshold
    xs, ys = [], []
    sim = fixtures["simulation"]
    for template in fixtures["splits"]["test"]["template_ids"]:
        for seed in fixtures["splits"]["test"]["seeds"]:
            rng = np.random.default_rng(seed + 1991)
            sc = scenario_for(template, seed)
            for _ in range(70):
                t = float(rng.uniform(0.0, 12.0))
                robot = np.asarray([min(sc.goal_x, 0.62 * t), float(rng.uniform(-0.3, 0.3))])
                if not sc.actors or all(a.ghost for a in sc.actors):
                    relp = np.asarray([float(rng.uniform(0.3, 4.0)), float(rng.uniform(-1.5, 1.5))])
                    tr = Track(robot + relp, np.zeros(2), variance=0.02, existence=0.9)
                    relv, label = np.asarray([-0.8, 0.0]), 0
                    clearance = float(np.linalg.norm(relp) - 0.6)
                else:
                    valid = [a for a in sc.actors if not a.ghost]
                    actor = valid[int(rng.integers(0, len(valid)))]
                    pos = actor.position(t) + rng.normal(0.0, sim["sensor_noise_sigma_m"], 2)
                    av = (actor.position(t + 2.0) - actor.position(t)) / 2.0
                    tr = Track(pos, av, variance=float(rng.uniform(0.01, 0.25)), existence=float(rng.uniform(0.65, 1.0)))
                    relp, relv = pos - robot, av - np.asarray([0.8, 0.0])
                    clearance = float(np.linalg.norm(relp) - 0.6)
                    label = int(min(np.linalg.norm(actor.position(t + h) - (robot + np.asarray([0.8, 0.0]) * h)) - 0.60 for h in np.linspace(0.1, 2.0, 20)) < 0.0)
                xs.append(features(clearance, relv, math.atan2(relp[1], relp[0]), tr, sc.context, "stranger"))
                ys.append(label)
    x, y = np.stack(xs), np.asarray(ys)
    z = np.column_stack([np.ones(len(x)), (x - mean) / scale])
    p = np.asarray(sigmoid(z @ weights))
    pred = p >= threshold
    positives, negatives = max(1, int(np.sum(y == 1))), max(1, int(np.sum(y == 0)))
    return {
        "examples": len(y), "positive_rate": float(y.mean()), "auroc": rank_auc(y, p),
        "brier": float(np.mean((p - y) ** 2)),
        "false_negative_rate": float(np.sum((pred == 0) & (y == 1))) / positives,
        "false_positive_rate": float(np.sum((pred == 1) & (y == 0))) / negatives,
    }


def aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for arm in ARMS:
        eps = [e for e in episodes if e["arm"] == arm]
        contexts = {}
        for context in ("sidewalk", "crosswalk", "elevator"):
            ce = [e for e in eps if e["context"] == context]
            contexts[context] = {"episodes": len(ce), "completion_rate": sum(e["completed"] for e in ce) / len(ce)}
        lat = [v for e in eps for v in e["unblock_latencies_s"]]
        vislat = [v for e in eps for v in e["visible_unblock_latencies_s"]]
        evidence_lat = [v for e in eps for v in e["evidence_to_motion_latencies_s"]]
        output[arm] = {
            "episodes": len(eps), "completion_rate": sum(e["completed"] for e in eps) / len(eps),
            "contacts": sum(e["contact"] for e in eps), "near_contact_episodes": sum(e["near_contact"] for e in eps),
            "actor_into_stationary_contact_episodes": sum(e["actor_into_stationary_contact"] for e in eps),
            "minimum_surface_clearance_m": min(e["minimum_surface_clearance_m"] for e in eps),
            "p05_surface_clearance_m": float(np.quantile([e["minimum_surface_clearance_m"] for e in eps], 0.05)),
            "false_block_s": sum(e["false_block_s"] for e in eps),
            "unsafe_motion_s": sum(e["unsafe_motion_s"] for e in eps),
            "wrong_stall_episodes": sum(e["wrong_stall"] for e in eps), "deadlocks": sum(e["deadlock"] for e in eps),
            "median_unblock_latency_s": float(np.median(lat)) if lat else None,
            "median_visible_unblock_latency_s": float(np.median(vislat)) if vislat else None,
            "median_evidence_to_motion_latency_s": float(np.median(evidence_lat)) if evidence_lat else None,
            "release_on_missing_count": sum(e["release_on_missing_count"] for e in eps),
            "semantic_violations": {k: sum(e["semantic_violations"][k] for e in eps) for k in ("authorization", "egress", "capacity", "hard_floor")},
            "mean_stop_start_transitions": float(np.mean([e["stop_start_transitions"] for e in eps])),
            "mean_lateral_distance_m": float(np.mean([e["lateral_distance_m"] for e in eps])),
            "mean_acceleration_proxy": float(np.mean([e["mean_acceleration_proxy"] for e in eps])),
            "contexts": contexts,
        }
    return output


def hypotheses(summary: dict[str, Any], critic: dict[str, float], episodes: list[dict[str, Any]]) -> dict[str, Any]:
    a0, a2, a3, a4 = (summary[a] for a in ("A0", "A2", "A3", "A4"))
    a0_lat, a2_lat = a0["median_visible_unblock_latency_s"], a2["median_visible_unblock_latency_s"]
    h1_latency = a0_lat is not None and a2_lat is not None and a2_lat <= 0.6 and a2_lat <= 0.5 * a0_lat
    occluded = [e for e in episodes if e["arm"] == "A2" and "occluded_survivor" in e["template_id"]]
    h1_occ = all(not e["contact"] and e["release_on_missing_count"] == 0 for e in occluded)
    fb_reduction_a2 = 1.0 - a2["false_block_s"] / max(a0["false_block_s"], 1e-9)
    completion_gain_a2 = a2["completion_rate"] - a0["completion_rate"]
    h2 = fb_reduction_a2 >= 0.40 and completion_gain_a2 >= 0.15 and a2["contacts"] == 0 and a2["near_contact_episodes"] <= a0["near_contact_episodes"]
    ce2 = [e for e in episodes if e["arm"] == "A2" and e["context"] in {"crosswalk", "elevator"}]
    ce3 = [e for e in episodes if e["arm"] == "A3" and e["context"] in {"crosswalk", "elevator"}]
    gain3 = sum(e["completed"] for e in ce3) / len(ce3) - sum(e["completed"] for e in ce2) / len(ce2)
    semantic3 = sum(sum(e["semantic_violations"].values()) for e in ce3)
    h3 = gain3 >= 0.15 and semantic3 == 0 and a3["contacts"] == 0 and a3["contexts"]["sidewalk"]["completion_rate"] >= a2["contexts"]["sidewalk"]["completion_rate"]
    fb_reduction_a4 = 1.0 - a4["false_block_s"] / max(a3["false_block_s"], 1e-9)
    h4 = critic["auroc"] >= 0.85 and critic["false_negative_rate"] <= 0.01 and fb_reduction_a4 >= 0.10 and a4["contacts"] == 0 and sum(a4["semantic_violations"].values()) == 0
    return {
        "H1": {"status": "PASS" if h1_latency and h1_occ else "REFUTED", "latency_condition": h1_latency, "occluded_survivor_condition": h1_occ, "A0_visible_median_s": a0_lat, "A2_visible_median_s": a2_lat},
        "H2": {"status": "PASS" if h2 else "REFUTED", "false_block_reduction": fb_reduction_a2, "completion_gain_points": completion_gain_a2, "A2_contacts": a2["contacts"], "A2_near_contact_episodes": a2["near_contact_episodes"], "A0_near_contact_episodes": a0["near_contact_episodes"]},
        "H3": {"status": "PASS" if h3 else "REFUTED", "crosswalk_elevator_completion_gain_points": gain3, "A3_semantic_violation_ticks": semantic3, "A3_contacts": a3["contacts"], "sidewalk_completion_delta": a3["contexts"]["sidewalk"]["completion_rate"] - a2["contexts"]["sidewalk"]["completion_rate"]},
        "H4": {"status": "PASS" if h4 else "REFUTED", "auroc": critic["auroc"], "false_negative_rate": critic["false_negative_rate"], "false_block_reduction": fb_reduction_a4, "A4_contacts": a4["contacts"], "A4_semantic_violation_ticks": sum(a4["semantic_violations"].values())},
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=ROOT / "fixtures.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "results.json")
    args = parser.parse_args()
    fixtures = json.loads(args.fixtures.read_text())
    training, weights, mean, scale = train_critic(fixtures)
    threshold = float(training["selected_threshold"])
    model = (weights, mean, scale, threshold)
    episodes = [
        run_episode(arm, template, seed, fixtures, model)
        for arm in ARMS
        for template in fixtures["splits"]["test"]["template_ids"]
        for seed in fixtures["splits"]["test"]["seeds"]
    ]
    summary = aggregate(episodes)
    critic = critic_test_metrics(fixtures, weights, mean, scale, threshold)
    hs = hypotheses(summary, critic, episodes)
    episode_digest = hashlib.sha256(json.dumps(episodes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = {
        "schema_version": 1,
        "evidence_tier": "authored deterministic 2-D desktop simulation; not physical validation",
        "fixtures_sha256": digest(args.fixtures), "experiment_sha256": digest(Path(__file__)),
        "episode_result_sha256": episode_digest, "episodes": len(episodes),
        "critic_training": training, "critic_test": critic, "summary": summary,
        "hypotheses": hs, "episode_results": episodes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "episode_result_sha256": episode_digest, "hypotheses": {k: v["status"] for k, v in hs.items()}}, indent=2))


if __name__ == "__main__":
    main()
