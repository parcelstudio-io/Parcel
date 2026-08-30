#!/usr/bin/env python3
"""Run the frozen LHO-1 paired handoff scheduling simulation."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import platform
import struct
import time
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from freeze_manifest import verify_manifest

ROOT = Path(__file__).resolve().parent
ARMS = ("B0", "F0", "G0")
# t_ms, x_um, speed_um_s, command_um_s, authority, action, flags,
# authorized_prefix_end_um, pending_request_count, prefix_record_count
TRACE_STRUCT = struct.Struct("<IiiiHHHihh")
WAITING = 1 << 0
INVALIDATED = 1 << 1
COLLISION = 1 << 2
STALE = 1 << 3
USABLE = 1 << 4
REQUEST = 1 << 5
RESPONSE = 1 << 6
EXHAUSTION = 1 << 7
EVENT = 1 << 8
EVIDENCE_TIER = "deterministic scalar scheduling/kinematic simulation; no physical claim"
TRACE_ENCODING = "zlib+base64 little-endian <IiiiHHHihh; x/v/cmd/prefix in microunits"
SOURCE_FILES = (
    "DESIGN.md",
    "AMENDMENT_1_COVERING_ARRAY.md",
    "AMENDMENT_2_PRE_EVIDENCE_AUDIT.md",
    "AMENDMENT_3_FREEZE_READINESS.md",
    "freeze_manifest.py",
    "freeze_sources.py",
    "run.py",
    "verify_results.py",
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _p95(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _run_ticks(arm: str, case: dict[str, object], estimate_s: float) -> int:
    dt = 1.0 / int(case["tracker_hz"])
    if arm == "B0":
        return 0
    if arm == "F0":
        return math.ceil(float(case["fixed_chunk_s"]) / dt - 1e-12)
    requested = math.ceil((estimate_s + float(case["guard_margin_s"])) / dt - 1e-12)
    corridor_limit = math.floor(float(case["corridor_cap_s"]) / dt + 1e-12)
    return max(0, min(requested, corridor_limit))


def _travel_then_brake_distance(
    speed: float,
    run_s: float,
    max_speed: float,
    accel: float,
    dt: float,
) -> float:
    ticks = round(run_s / dt)
    if abs(ticks * dt - run_s) > 1e-9:
        raise ValueError("prefix run time must be tracker-tick aligned")
    distance = 0.0
    terminal_speed = speed
    for _ in range(ticks):
        desired_accel = max(
            -accel,
            min(accel, (max_speed - terminal_speed) / dt),
        )
        new_speed = max(0.0, terminal_speed + desired_accel * dt)
        distance += 0.5 * (terminal_speed + new_speed) * dt
        terminal_speed = new_speed
    while terminal_speed > 1e-12:
        new_speed = max(0.0, terminal_speed - accel * dt)
        distance += 0.5 * (terminal_speed + new_speed) * dt
        terminal_speed = new_speed
    return distance


def verify_source_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    expected = value.get("manifest_sha256")
    payload = dict(value)
    payload.pop("manifest_sha256", None)
    if expected != _sha(_canonical(payload)):
        raise ValueError("source manifest digest mismatch")
    rows = value.get("files")
    if not isinstance(rows, dict) or set(rows) != set(SOURCE_FILES):
        raise ValueError("source manifest file inventory mismatch")
    for relative, digest in rows.items():
        if _sha((ROOT / relative).read_bytes()) != digest:
            raise ValueError(f"source changed after freeze: {relative}")
    return value


@dataclass(frozen=True)
class PlannerRequest:
    response_at_s: float
    usable_until_s: float
    authorized_prefix_end_m: float
    request_kind: str


def _decode_trace(raw: bytes) -> list[tuple[int, ...]]:
    if len(raw) % TRACE_STRUCT.size:
        raise ValueError("internal trace is not record aligned")
    return list(TRACE_STRUCT.iter_unpack(raw))


def _summary_from_trace(raw: bytes, case: dict[str, object]) -> dict[str, object]:
    rows = _decode_trace(raw)
    if not rows:
        raise ValueError("episode emitted no trace rows")
    dt = 1.0 / int(case["tracker_hz"])
    waiting_flags = [bool(row[6] & WAITING) for row in rows]
    collision_flags = [bool(row[6] & COLLISION) for row in rows]
    event_flags = [bool(row[6] & EVENT) for row in rows]
    waiting_runs: list[int] = []
    run = 0
    for waiting in waiting_flags:
        if waiting:
            run += 1
        elif run:
            waiting_runs.append(run)
            run = 0
    if run:
        waiting_runs.append(run)

    previous_x_um = 0
    previous_speed = 0.0
    previous_acceleration = 0.0
    stale_um = 0
    old_dispatches = 0
    accelerations: list[float] = []
    jerks: list[float] = []
    splice_acceleration: float | None = None
    splice_jerk: float | None = None
    positive_after_invalidation = 0
    latest_positive_delay = 0.0
    first_invalid_ms: int | None = None
    revision_response_s: float | None = None
    previous_action = 1
    previous_prefix_exhausted = False
    prefix_unusable_onsets = 0
    for row in rows:
        t_ms, x_um, speed_um, command_um, authority, action, flags, prefix_um, _, _ = row
        speed = speed_um / 1_000_000.0
        acceleration = (speed - previous_speed) / dt
        jerk = abs((acceleration - previous_acceleration) / dt) * (
            1.0 + 0.05 * float(case["curvature_gain"])
        )
        accelerations.append(abs(acceleration))
        jerks.append(jerk)
        if flags & RESPONSE and previous_action == 1 and action == 2:
            if splice_acceleration is not None:
                raise ValueError("multiple revision splice samples in one episode")
            splice_acceleration = abs(acceleration)
            splice_jerk = jerk
        if authority > action:
            stale_um += max(0, x_um - max(previous_x_um, prefix_um))
            if command_um > 0 and previous_x_um >= prefix_um:
                old_dispatches += 1
        if flags & INVALIDATED:
            if first_invalid_ms is None:
                first_invalid_ms = t_ms
            if command_um > 0:
                positive_after_invalidation += 1
                latest_positive_delay = max(
                    latest_positive_delay,
                    (t_ms - first_invalid_ms) / 1000.0,
                )
        if revision_response_s is None and flags & RESPONSE and authority == action == 2:
            revision_response_s = t_ms / 1000.0
        prefix_exhausted = row[8] == 1 and not bool(flags & USABLE)
        if prefix_exhausted and not previous_prefix_exhausted:
            prefix_unusable_onsets += 1
        previous_prefix_exhausted = prefix_exhausted
        previous_x_um = x_um
        previous_speed = speed
        previous_acceleration = acceleration
        previous_action = action

    trailing_stationary = 0
    for row in reversed(rows):
        if row[2] <= 10_000:
            trailing_stationary += 1
        else:
            break
    final = rows[-1]
    mode = str(case["mode"])
    mission_goal_m = (
        float(case["revised_length_m"]) if mode == "revision" else float(case["length_m"])
    )
    duration_s = round(final[0] / 1000.0 + dt, 6)
    collision = any(collision_flags)
    boundary = stale_um > 0
    mission_success = (
        mode in {"control", "revision"}
        and final[1] >= round(mission_goal_m * 1_000_000.0) - 1
        and final[4] == final[5]
        and not collision
        and not boundary
        and duration_s < float(case["timeout_s"]) - 1e-12
    )
    trace_sha = _sha(raw)
    compressed = zlib.compress(raw, level=9)
    return {
        "mission_success": mission_success,
        "stop_complete": mode in {"emergency", "occupied"} and trailing_stationary >= 7,
        "event_triggered": any(event_flags),
        "collision": collision,
        "boundary_violation": boundary,
        "waiting_time_s": round(sum(waiting_flags) * dt, 6),
        "wait_runs": len(waiting_runs),
        "visible_gaps": sum(count * dt > 0.50 + 1e-12 for count in waiting_runs),
        "maximum_gap_s": round(max(waiting_runs, default=0) * dt, 6),
        "prefix_exhaustions": sum(bool(row[6] & EXHAUSTION) for row in rows),
        "prefix_unusable_onsets": prefix_unusable_onsets,
        "stale_tail_distance_m": round(stale_um / 1_000_000.0, 9),
        "old_revision_dispatch_beyond_prefix": old_dispatches,
        "post_invalidation_positive_commands": positive_after_invalidation,
        "post_invalidation_latest_positive_delay_s": round(latest_positive_delay, 6),
        "p95_acceleration_mps2": round(_p95(accelerations), 6),
        "p95_jerk_mps3": round(_p95(jerks), 6),
        "splice_acceleration_mps2": (
            None if splice_acceleration is None else round(splice_acceleration, 6)
        ),
        "splice_jerk_mps3": None if splice_jerk is None else round(splice_jerk, 6),
        "revised_tail_applied": mode == "revision" and any(row[5] == 2 for row in rows),
        "final_tail_token": (
            case["revised_tail_token"]
            if mode == "revision" and final[5] == 2
            else case["original_tail_token"]
        ),
        "duration_s": duration_s,
        "final_position_m": round(final[1] / 1_000_000.0, 9),
        "final_speed_mps": round(final[2] / 1_000_000.0, 9),
        "request_count": sum(bool(row[6] & REQUEST) for row in rows),
        "response_count": sum(bool(row[6] & RESPONSE) for row in rows),
        "revision_response_s": revision_response_s,
        "max_pending_requests": max(row[8] for row in rows),
        "max_prefix_records": max(row[9] for row in rows),
        "trace_ticks": len(rows),
        "trace_sha256": trace_sha,
        "trace_raw_bytes": len(raw),
        "trace_zlib_bytes": len(compressed),
    }


def _simulate(case: dict[str, object], arm: str) -> dict[str, object]:
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm}")
    hz = int(case["tracker_hz"])
    dt = 1.0 / hz
    max_speed = float(case["max_speed_mps"])
    max_accel = float(case["max_accel_mps2"])
    original_length = float(case["length_m"])
    revised_length = float(case["revised_length_m"])
    mission_goal = revised_length if str(case["mode"]) == "revision" else original_length
    timeout = float(case["timeout_s"])
    mode = str(case["mode"])
    event_at_m = case["event_at_m"]
    actual_latency = float(case["actual_latency_s"])
    estimate = max(0.05, actual_latency * (1.0 + float(case["estimator_error"])))
    run_ticks = _run_ticks(arm, case, estimate)

    t = 0.0
    x = 0.0
    speed = 0.0
    authority_revision = 1
    action_revision = 1
    pending: PlannerRequest | None = None
    next_periodic_request_s = float(case["planner_period_s"])
    event_triggered = False
    invalidated_at_s: float | None = None
    obstacle_center_um: int | None = None
    stationary_since_s: float | None = None
    was_prefix_exhausted = False
    collision = False
    boundary_violation = False
    trace = bytearray()

    def plan_speed() -> float:
        if mode == "revision" and action_revision == 2:
            return max_speed * float(case["revised_speed_scale"])
        return max_speed

    def plan_goal() -> float:
        if mode == "revision" and action_revision == 2:
            return revised_length
        return original_length

    def publish_prefix() -> tuple[float, float]:
        run_s = run_ticks * dt
        end = x + _travel_then_brake_distance(
            speed,
            run_s,
            plan_speed(),
            max_accel,
            dt,
        )
        return min(plan_goal(), end), round(t + run_s, 12)

    maximum_ticks = math.floor(timeout / dt + 1e-12)
    for _tick in range(maximum_ticks):
        request_issued = False
        response_received = False
        exhaustion = False
        event_now = False
        start_x_um = round(x * 1_000_000.0)

        # Publication happens before this tick's response/event inputs. A
        # revision can retain this prefix, never create a hindsight prefix.
        if pending is None:
            prepublished_end, prepublished_until = publish_prefix()
        else:
            prepublished_end = pending.authorized_prefix_end_m
            prepublished_until = pending.usable_until_s

        if (
            pending is not None
            and t + 1e-12 >= pending.response_at_s
            and (arm != "B0" or speed <= 0.01 + 1e-12)
        ):
            pending = None
            action_revision = authority_revision
            response_received = True
            next_periodic_request_s = round(t + float(case["planner_period_s"]), 12)

        if not event_triggered and event_at_m is not None and x + 1e-12 >= float(event_at_m):
            event_triggered = True
            event_now = True
            if mode == "revision":
                authority_revision += 1
                pending = PlannerRequest(
                    response_at_s=round(t + actual_latency, 12),
                    usable_until_s=prepublished_until,
                    authorized_prefix_end_m=prepublished_end,
                    request_kind="revision",
                )
                request_issued = True
            elif mode in {"emergency", "occupied"}:
                invalidated_at_s = t
                pending = None
                if mode == "occupied":
                    half_length = float(case["robot_half_length_m"])
                    zone_start = float(case["occupied_zone_start_m"])
                    zone_end = float(case["occupied_zone_end_m"])
                    swept_start = start_x_um / 1_000_000.0 - half_length
                    swept_end = prepublished_end + half_length
                    if swept_end < zone_start - 1e-12 or swept_start > zone_end + 1e-12:
                        raise RuntimeError(
                            "occupied case does not intersect published swept prefix"
                        )
                    obstacle_center_um = round(
                        (float(case["occupied_contact_boundary_m"]) + half_length) * 1_000_000.0
                    )

        if invalidated_at_s is None and pending is None and t + 1e-12 >= next_periodic_request_s:
            pending = PlannerRequest(
                response_at_s=round(t + actual_latency, 12),
                usable_until_s=prepublished_until,
                authorized_prefix_end_m=prepublished_end,
                request_kind="periodic",
            )
            request_issued = True

        invalidated = invalidated_at_s is not None
        active_prefix = prepublished_end if pending is None else pending.authorized_prefix_end_m
        usable = True
        if pending is not None:
            braking_end = x + speed * speed / (2.0 * max_accel)
            usable = (
                t < pending.usable_until_s - 1e-12
                and braking_end < pending.authorized_prefix_end_m - 1e-9
            )
        command = 0.0 if invalidated or not usable else plan_speed()
        waiting = (
            not invalidated
            and pending is not None
            and not usable
            and speed <= 0.02 + 1e-12
            and x < mission_goal - 1e-6
        )
        prefix_exhausted = pending is not None and not usable
        if prefix_exhausted and not was_prefix_exhausted:
            exhaustion = True
        was_prefix_exhausted = prefix_exhausted

        desired_accel = max(-max_accel, min(max_accel, (command - speed) / dt))
        new_speed = max(0.0, min(max_speed, speed + desired_accel * dt))
        x = min(plan_goal(), x + 0.5 * (speed + new_speed) * dt)
        speed = new_speed
        x_um = round(x * 1_000_000.0)
        speed_um = round(speed * 1_000_000.0)
        command_um = round(command * 1_000_000.0)
        prefix_um = round(active_prefix * 1_000_000.0)

        stale_um = 0
        if authority_revision > action_revision:
            stale_um = max(0, x_um - max(start_x_um, prefix_um))
            if stale_um:
                boundary_violation = True
        if (
            obstacle_center_um is not None
            and x_um + round(float(case["robot_half_length_m"]) * 1_000_000.0) >= obstacle_center_um
        ):
            collision = True

        flags = 0
        flags |= WAITING if waiting else 0
        flags |= INVALIDATED if invalidated else 0
        flags |= COLLISION if collision else 0
        flags |= STALE if stale_um else 0
        flags |= USABLE if usable else 0
        flags |= REQUEST if request_issued else 0
        flags |= RESPONSE if response_received else 0
        flags |= EXHAUSTION if exhaustion else 0
        flags |= EVENT if event_now else 0
        prefix_records = 0 if invalidated else 1
        trace.extend(
            TRACE_STRUCT.pack(
                round(t * 1000.0),
                x_um,
                speed_um,
                command_um,
                authority_revision,
                action_revision,
                flags,
                prefix_um,
                int(pending is not None),
                prefix_records,
            )
        )

        if (
            mode in {"control", "revision"}
            and action_revision == authority_revision
            and x >= mission_goal - 1e-9
        ):
            break
        if invalidated:
            if speed <= 0.01:
                if stationary_since_s is None:
                    stationary_since_s = t
                elif t - stationary_since_s >= 0.30 - 1e-12:
                    break
            else:
                stationary_since_s = None
        if collision or boundary_violation:
            break
        t = round(t + dt, 12)

    raw = bytes(trace)
    compressed = zlib.compress(raw, level=9)
    summary = _summary_from_trace(raw, case)
    return {
        "case_id": case["case_id"],
        "case_sha256": case["case_sha256"],
        "arm": arm,
        "mode": mode,
        "family": case["family"],
        "estimator_error": case["estimator_error"],
        "base_latency_s": case["base_latency_s"],
        "summary": summary,
        "trace_encoding": TRACE_ENCODING,
        "trace_b64": base64.b64encode(compressed).decode("ascii"),
    }


def _aggregate(episodes: list[dict[str, object]]) -> dict[str, object]:
    arms: dict[str, dict[str, object]] = {}
    for arm in ARMS:
        rows = [item for item in episodes if item["arm"] == arm]
        ordinary = [item for item in rows if item["mode"] in {"control", "revision"}]
        invalidation = [item for item in rows if item["mode"] in {"emergency", "occupied"}]
        revisions = [item for item in rows if item["mode"] == "revision"]
        summaries = [item["summary"] for item in rows]
        ordinary_summaries = [item["summary"] for item in ordinary]
        invalidation_summaries = [item["summary"] for item in invalidation]
        revision_summaries = [item["summary"] for item in revisions]
        splice_accels = [
            float(s["splice_acceleration_mps2"])
            for s in revision_summaries
            if s["splice_acceleration_mps2"] is not None
        ]
        splice_jerks = [
            float(s["splice_jerk_mps3"])
            for s in revision_summaries
            if s["splice_jerk_mps3"] is not None
        ]
        arms[arm] = {
            "episodes": len(rows),
            "ordinary_episodes": len(ordinary),
            "invalidation_episodes": len(invalidation),
            "mission_successes": sum(bool(s["mission_success"]) for s in ordinary_summaries),
            "mission_success_rate": round(
                sum(bool(s["mission_success"]) for s in ordinary_summaries) / len(ordinary),
                9,
            ),
            "waiting_time_s": round(sum(float(s["waiting_time_s"]) for s in ordinary_summaries), 6),
            "wait_runs": sum(int(s["wait_runs"]) for s in ordinary_summaries),
            "visible_gaps": sum(int(s["visible_gaps"]) for s in ordinary_summaries),
            "prefix_exhaustions": sum(int(s["prefix_exhaustions"]) for s in ordinary_summaries),
            "prefix_unusable_onsets": sum(
                int(s["prefix_unusable_onsets"]) for s in ordinary_summaries
            ),
            "stale_tail_distance_m": round(
                sum(float(s["stale_tail_distance_m"]) for s in summaries), 9
            ),
            "old_revision_dispatch_beyond_prefix": sum(
                int(s["old_revision_dispatch_beyond_prefix"]) for s in summaries
            ),
            "collisions": sum(bool(s["collision"]) for s in summaries),
            "boundary_violations": sum(bool(s["boundary_violation"]) for s in summaries),
            "revision_episodes": len(revisions),
            "revision_splices_observed": len(splice_accels),
            "revision_revised_tails_applied": sum(
                bool(s["revised_tail_applied"]) for s in revision_summaries
            ),
            "revision_stale_tail_distance_m": round(
                sum(float(s["stale_tail_distance_m"]) for s in revision_summaries), 9
            ),
            "revision_old_dispatch_beyond_prefix": sum(
                int(s["old_revision_dispatch_beyond_prefix"]) for s in revision_summaries
            ),
            "revision_collisions": sum(bool(s["collision"]) for s in revision_summaries),
            "revision_boundary_violations": sum(
                bool(s["boundary_violation"]) for s in revision_summaries
            ),
            "revision_p95_splice_acceleration_mps2": round(_p95(splice_accels), 6),
            "revision_p95_splice_jerk_mps3": round(_p95(splice_jerks), 6),
            "post_invalidation_positive_commands": sum(
                int(s["post_invalidation_positive_commands"]) for s in invalidation_summaries
            ),
            "post_invalidation_max_delay_s": max(
                (
                    float(s["post_invalidation_latest_positive_delay_s"])
                    for s in invalidation_summaries
                ),
                default=0.0,
            ),
            "stop_complete": sum(bool(s["stop_complete"]) for s in invalidation_summaries),
            "invalidation_collisions": sum(bool(s["collision"]) for s in invalidation_summaries),
            "max_pending_requests": max(int(s["max_pending_requests"]) for s in summaries),
            "max_prefix_records": max(int(s["max_prefix_records"]) for s in summaries),
            "p95_acceleration_mps2": round(
                _p95(float(s["p95_acceleration_mps2"]) for s in ordinary_summaries), 6
            ),
            "p95_jerk_mps3": round(_p95(float(s["p95_jerk_mps3"]) for s in ordinary_summaries), 6),
        }

    b0, f0, g0 = (arms[name] for name in ARMS)
    b0_wait = float(b0["waiting_time_s"])
    b0_gaps = int(b0["visible_gaps"])
    if b0_wait <= 0.0 or b0_gaps <= 0:
        raise ValueError("B0 produced no measurable wait/gap denominator")
    wait_reduction = 1.0 - float(g0["waiting_time_s"]) / b0_wait
    gap_reduction = 1.0 - float(g0["visible_gaps"]) / b0_gaps
    better_sr = max(float(b0["mission_success_rate"]), float(f0["mission_success_rate"]))
    h1 = {
        "waiting_reduction_fraction": round(wait_reduction, 9),
        "visible_gap_reduction_fraction": round(gap_reduction, 9),
        "g0_success_delta_from_better": round(float(g0["mission_success_rate"]) - better_sr, 9),
        "pass": (
            wait_reduction >= 0.30
            and gap_reduction >= 0.50
            and float(g0["mission_success_rate"]) >= better_sr - 0.02
        ),
    }
    h2 = {
        "pass": (
            float(g0["revision_stale_tail_distance_m"]) == 0.0
            and int(g0["revision_old_dispatch_beyond_prefix"]) == 0
            and int(g0["revision_collisions"]) == 0
            and int(g0["revision_boundary_violations"]) == 0
            and int(g0["revision_splices_observed"]) == int(g0["revision_episodes"])
            and int(g0["revision_revised_tails_applied"]) == int(g0["revision_episodes"])
            and float(g0["revision_p95_splice_acceleration_mps2"])
            <= 1.10 * float(f0["revision_p95_splice_acceleration_mps2"]) + 1e-12
            and float(g0["revision_p95_splice_jerk_mps3"])
            <= 1.10 * float(f0["revision_p95_splice_jerk_mps3"]) + 1e-12
        )
    }
    h3 = {
        "pass": all(
            int(arms[name]["post_invalidation_positive_commands"]) == 0
            and float(arms[name]["post_invalidation_max_delay_s"]) <= 0.05 + 1e-12
            and int(arms[name]["invalidation_collisions"]) == 0
            and int(arms[name]["stop_complete"]) == int(arms[name]["invalidation_episodes"])
            for name in ARMS
        )
    }
    strata: dict[str, dict[str, object]] = {}
    for error in sorted({float(item["estimator_error"]) for item in episodes}):
        all_rows = [
            item
            for item in episodes
            if item["arm"] == "G0" and float(item["estimator_error"]) == error
        ]
        ordinary = [item for item in all_rows if item["mode"] in {"control", "revision"}]
        invalidation = [item for item in all_rows if item["mode"] in {"emergency", "occupied"}]
        f0_revisions = [
            item
            for item in episodes
            if item["arm"] == "F0"
            and float(item["estimator_error"]) == error
            and item["mode"] == "revision"
        ]
        g0_revisions = [item for item in all_rows if item["mode"] == "revision"]
        g0_splice_accels = [
            float(item["summary"]["splice_acceleration_mps2"])
            for item in g0_revisions
            if item["summary"]["splice_acceleration_mps2"] is not None
        ]
        g0_splice_jerks = [
            float(item["summary"]["splice_jerk_mps3"])
            for item in g0_revisions
            if item["summary"]["splice_jerk_mps3"] is not None
        ]
        f0_splice_accels = [
            float(item["summary"]["splice_acceleration_mps2"])
            for item in f0_revisions
            if item["summary"]["splice_acceleration_mps2"] is not None
        ]
        f0_splice_jerks = [
            float(item["summary"]["splice_jerk_mps3"])
            for item in f0_revisions
            if item["summary"]["splice_jerk_mps3"] is not None
        ]
        splice_within_bound = (
            len(g0_splice_accels) == len(g0_revisions)
            and len(f0_splice_accels) == len(f0_revisions)
            and _p95(g0_splice_accels) <= 1.10 * _p95(f0_splice_accels) + 1e-12
            and _p95(g0_splice_jerks) <= 1.10 * _p95(f0_splice_jerks) + 1e-12
        )
        strata[f"{error:+.2f}"] = {
            "episodes": len(ordinary),
            "invalidation_episodes": len(invalidation),
            "mission_success_rate": round(
                sum(bool(item["summary"]["mission_success"]) for item in ordinary) / len(ordinary),
                9,
            ),
            "waiting_time_s": round(
                sum(float(item["summary"]["waiting_time_s"]) for item in ordinary), 6
            ),
            "visible_gaps": sum(int(item["summary"]["visible_gaps"]) for item in ordinary),
            "prefix_exhaustions": sum(
                int(item["summary"]["prefix_exhaustions"]) for item in ordinary
            ),
            "prefix_unusable_onsets": sum(
                int(item["summary"]["prefix_unusable_onsets"]) for item in ordinary
            ),
            "underestimated": error < 0.0,
            "stale_tail_distance_m": round(
                sum(float(item["summary"]["stale_tail_distance_m"]) for item in all_rows), 9
            ),
            "old_revision_dispatch_beyond_prefix": sum(
                int(item["summary"]["old_revision_dispatch_beyond_prefix"]) for item in all_rows
            ),
            "collisions": sum(bool(item["summary"]["collision"]) for item in all_rows),
            "boundary_violations": sum(
                bool(item["summary"]["boundary_violation"]) for item in all_rows
            ),
            "post_invalidation_positive_commands": sum(
                int(item["summary"]["post_invalidation_positive_commands"]) for item in invalidation
            ),
            "stop_complete": sum(bool(item["summary"]["stop_complete"]) for item in invalidation),
            "max_pending_requests": max(
                int(item["summary"]["max_pending_requests"]) for item in all_rows
            ),
            "max_prefix_records": max(
                int(item["summary"]["max_prefix_records"]) for item in all_rows
            ),
            "splice_within_f0_10_percent": splice_within_bound,
        }
    h4 = {
        "error_strata": strata,
        "pass": all(
            float(row["stale_tail_distance_m"]) == 0.0
            and int(row["old_revision_dispatch_beyond_prefix"]) == 0
            and int(row["collisions"]) == 0
            and int(row["boundary_violations"]) == 0
            and int(row["post_invalidation_positive_commands"]) == 0
            and int(row["stop_complete"]) == int(row["invalidation_episodes"])
            and int(row["prefix_exhaustions"]) == int(row["prefix_unusable_onsets"])
            and int(row["max_pending_requests"]) <= 1
            and int(row["max_prefix_records"]) <= 1
            and bool(row["splice_within_f0_10_percent"])
            for row in strata.values()
        ),
    }
    return {
        "arms": arms,
        "hypotheses": {"H1": h1, "H2": h2, "H3": h3, "H4": h4},
        "preliminary_verdict": (
            "LHO1_H1_H4_PASS_H5_PENDING"
            if all(bool(item["pass"]) for item in (h1, h2, h3, h4))
            else "LHO1_REFUTED"
        ),
    }


def run(manifest: dict[str, object], *, limit: int | None = None) -> dict[str, object]:
    cases = list(manifest["cases"])
    if limit is not None:
        cases = cases[:limit]
    started = time.monotonic()
    episodes = [_simulate(case, arm) for case in cases for arm in ARMS]
    aggregate = _aggregate(episodes) if limit is None else {"smoke_only": True}
    normalized_rows = [
        {
            key: item[key]
            for key in (
                "case_id",
                "case_sha256",
                "arm",
                "mode",
                "family",
                "estimator_error",
                "base_latency_s",
                "summary",
            )
        }
        for item in episodes
    ]
    return {
        "schema_version": 2,
        "study": "LHO-1",
        "evidence_tier": EVIDENCE_TIER,
        "manifest_sha256": manifest["manifest_sha256"],
        "source_manifest_sha256": None,
        "run_metadata": {
            "python": platform.python_version(),
            "runtime_s": round(time.monotonic() - started, 6),
            "case_limit": limit,
        },
        "inventory": {
            "paired_cases": len(cases),
            "arm_episodes": len(episodes),
            "arms": list(ARMS),
        },
        "normalized_episode_digest": _sha(_canonical(normalized_rows)),
        "aggregate": aggregate,
        "episodes": episodes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.json")
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=ROOT / "source-manifest.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-unfrozen", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    verify_manifest(manifest)
    source_manifest = None
    if not args.allow_unfrozen:
        source_manifest = verify_source_manifest(args.source_manifest)
    result = run(manifest, limit=args.limit)
    if source_manifest is not None:
        result["source_manifest_sha256"] = source_manifest["manifest_sha256"]
    args.output.write_bytes(_canonical(result) + b"\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "episodes": result["inventory"]["arm_episodes"],
                "digest": result["normalized_episode_digest"],
                "verdict": result["aggregate"].get("preliminary_verdict"),
                "runtime_s": result["run_metadata"]["runtime_s"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
