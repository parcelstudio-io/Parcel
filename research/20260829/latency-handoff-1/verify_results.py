#!/usr/bin/env python3
"""Independent trace-first verifier for LHO-1 evidence."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import math
import struct
import zlib
from collections.abc import Iterable
from pathlib import Path

from freeze_manifest import verify_manifest

ROOT = Path(__file__).resolve().parent
ARMS = ("B0", "F0", "G0")
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


def _verify_source_value(
    value: dict[str, object],
    *,
    byte_overrides: dict[str, bytes] | None = None,
) -> None:
    expected = value.get("manifest_sha256")
    payload = dict(value)
    payload.pop("manifest_sha256", None)
    if expected != _sha(_canonical(payload)):
        raise ValueError("source manifest digest mismatch")
    files = value.get("files")
    if not isinstance(files, dict) or set(files) != set(SOURCE_FILES):
        raise ValueError("source manifest inventory mismatch")
    for relative, expected_digest in files.items():
        raw = (
            byte_overrides[relative]
            if byte_overrides is not None and relative in byte_overrides
            else (ROOT / relative).read_bytes()
        )
        if _sha(raw) != expected_digest:
            raise ValueError(f"source digest mismatch: {relative}")


def _verify_source_manifest(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _verify_source_value(value)
    return value


def _decode_trace(episode: dict[str, object]) -> list[tuple[int, ...]]:
    raw = zlib.decompress(base64.b64decode(str(episode["trace_b64"]), validate=True))
    summary = episode["summary"]
    if len(raw) != int(summary["trace_raw_bytes"]):
        raise ValueError("raw trace byte count mismatch")
    if len(raw) % TRACE_STRUCT.size:
        raise ValueError("raw trace is not record aligned")
    if _sha(raw) != summary["trace_sha256"]:
        raise ValueError("raw trace digest mismatch")
    rows = list(TRACE_STRUCT.iter_unpack(raw))
    if len(rows) != int(summary["trace_ticks"]):
        raise ValueError("trace tick count mismatch")
    if [row[0] for row in rows] != list(range(0, len(rows) * 50, 50)):
        raise ValueError("trace clock is not an exact 20 Hz sequence")
    return rows


def _run_ticks(arm: str, case: dict[str, object], estimate_s: float) -> int:
    dt = 1.0 / int(case["tracker_hz"])
    if arm == "B0":
        return 0
    if arm == "F0":
        return math.ceil(float(case["fixed_chunk_s"]) / dt - 1e-12)
    requested = math.ceil((estimate_s + float(case["guard_margin_s"])) / dt - 1e-12)
    cap = math.floor(float(case["corridor_cap_s"]) / dt + 1e-12)
    return max(0, min(requested, cap))


def _travel_then_brake_distance(
    speed: float,
    run_s: float,
    max_speed: float,
    accel: float,
    dt: float,
) -> float:
    ticks = round(run_s / dt)
    if abs(ticks * dt - run_s) > 1e-9:
        raise ValueError("prefix run time is not tracker-tick aligned")
    distance = 0.0
    terminal = speed
    for _ in range(ticks):
        requested_accel = max(
            -accel,
            min(accel, (max_speed - terminal) / dt),
        )
        next_speed = max(0.0, terminal + requested_accel * dt)
        distance += 0.5 * (terminal + next_speed) * dt
        terminal = next_speed
    while terminal > 1e-12:
        next_speed = max(0.0, terminal - accel * dt)
        distance += 0.5 * (terminal + next_speed) * dt
        terminal = next_speed
    return distance


def _trace_metrics(
    episode: dict[str, object],
    case: dict[str, object],
) -> dict[str, object]:
    rows = _decode_trace(episode)
    if not rows:
        raise ValueError("empty trace")
    arm = str(episode["arm"])
    dt = 1.0 / int(case["tracker_hz"])
    max_speed = float(case["max_speed_mps"])
    max_speed_um = round(max_speed * 1_000_000.0)
    revised_speed = max_speed * float(case["revised_speed_scale"])
    revised_speed_um = round(revised_speed * 1_000_000.0)
    max_accel = float(case["max_accel_mps2"])
    original_length = float(case["length_m"])
    revised_length = float(case["revised_length_m"])
    mode = str(case["mode"])
    mission_goal = revised_length if mode == "revision" else original_length
    mission_goal_um = round(mission_goal * 1_000_000.0)
    actual_latency = float(case["actual_latency_s"])
    estimate = max(0.05, actual_latency * (1.0 + float(case["estimator_error"])))
    run_ticks = _run_ticks(arm, case, estimate)
    event_at_um = (
        None if case["event_at_m"] is None else round(float(case["event_at_m"]) * 1_000_000.0)
    )

    previous_x_um = 0
    previous_speed_um = 0
    previous_acceleration = 0.0
    pending = False
    response_at_s: float | None = None
    usable_until_s: float | None = None
    frozen_prefix_um: int | None = None
    next_periodic_s = float(case["planner_period_s"])
    authority = 1
    action = 1
    event_seen = False
    invalidated = False
    collision = False
    obstacle_center_um: int | None = None
    previous_prefix_exhausted = False
    waiting_flags: list[bool] = []
    waiting_runs: list[int] = []
    current_wait_run = 0
    stale_total_um = 0
    old_dispatches = 0
    accelerations: list[float] = []
    jerks: list[float] = []
    splice_acceleration: float | None = None
    splice_jerk: float | None = None
    positive_after_invalidation = 0
    latest_positive_delay = 0.0
    first_invalid_ms: int | None = None
    request_count = 0
    response_count = 0
    exhaustion_count = 0
    prefix_unusable_onsets = 0
    revision_response_s: float | None = None
    max_pending = 0
    max_prefix = 0
    event_count = 0

    for row in rows:
        (
            t_ms,
            x_um,
            speed_um,
            command_um,
            row_authority,
            row_action,
            flags,
            prefix_um,
            pending_count,
            prefix_count,
        ) = row
        t = t_ms / 1000.0
        start_x = previous_x_um / 1_000_000.0
        start_speed = previous_speed_um / 1_000_000.0
        action_before_tick = action

        if command_um not in {0, max_speed_um, revised_speed_um}:
            raise ValueError("command is outside the frozen plan-specific command set")
        desired_accel = max(
            -max_accel,
            min(max_accel, (command_um / 1_000_000.0 - start_speed) / dt),
        )
        expected_speed = max(0.0, min(max_speed, start_speed + desired_accel * dt))
        row_goal = revised_length if mode == "revision" and row_action == 2 else original_length
        expected_x = min(
            row_goal,
            start_x + 0.5 * (start_speed + expected_speed) * dt,
        )
        if abs(speed_um - round(expected_speed * 1_000_000.0)) > 1:
            raise ValueError("speed dynamics mismatch")
        if abs(x_um - round(expected_x * 1_000_000.0)) > 2:
            raise ValueError("position dynamics mismatch")

        if pending:
            assert frozen_prefix_um is not None and usable_until_s is not None
            prepublished_prefix_um = frozen_prefix_um
            prepublished_until = usable_until_s
        else:
            run_s = run_ticks * dt
            pre_response_speed = revised_speed if mode == "revision" and action == 2 else max_speed
            pre_response_goal = (
                revised_length if mode == "revision" and action == 2 else original_length
            )
            prepublished_prefix_um = round(
                min(
                    pre_response_goal,
                    start_x
                    + _travel_then_brake_distance(
                        start_speed,
                        run_s,
                        pre_response_speed,
                        max_accel,
                        dt,
                    ),
                )
                * 1_000_000.0
            )
            prepublished_until = round(t + run_s, 12)

        expected_response = (
            pending
            and response_at_s is not None
            and t + 1e-12 >= response_at_s
            and (arm != "B0" or start_speed <= 0.01 + 1e-12)
        )
        if bool(flags & RESPONSE) != expected_response:
            raise ValueError("planner response timing mismatch")
        if expected_response:
            pending = False
            response_at_s = None
            usable_until_s = None
            frozen_prefix_um = None
            action = authority
            response_count += 1
            next_periodic_s = round(t + float(case["planner_period_s"]), 12)

        eligible_event = (
            not event_seen and event_at_um is not None and previous_x_um >= event_at_um - 1
        )
        event_now = bool(flags & EVENT)
        if event_now != eligible_event:
            raise ValueError("event timing does not match the frozen path decile")
        expected_request = False
        if event_now:
            event_seen = True
            event_count += 1
            if case["mode"] == "revision":
                authority += 1
                pending = True
                response_at_s = round(t + actual_latency, 12)
                usable_until_s = prepublished_until
                frozen_prefix_um = prepublished_prefix_um
                expected_request = True
            elif case["mode"] in {"emergency", "occupied"}:
                invalidated = True
                pending = False
                response_at_s = None
                usable_until_s = None
                frozen_prefix_um = None
                if case["mode"] == "occupied":
                    half_length = float(case["robot_half_length_m"])
                    zone_start = float(case["occupied_zone_start_m"])
                    zone_end = float(case["occupied_zone_end_m"])
                    swept_start = start_x - half_length
                    swept_end = prepublished_prefix_um / 1_000_000.0 + half_length
                    if swept_end < zone_start - 1e-12 or swept_start > zone_end + 1e-12:
                        raise ValueError(
                            "occupied truth does not intersect the published swept prefix"
                        )
                    obstacle_center_um = round(
                        (float(case["occupied_contact_boundary_m"]) + half_length) * 1_000_000.0
                    )
            else:
                raise ValueError("control case emitted an event")

        if not invalidated and not pending and t + 1e-12 >= next_periodic_s:
            pending = True
            response_at_s = round(t + actual_latency, 12)
            usable_until_s = prepublished_until
            frozen_prefix_um = prepublished_prefix_um
            expected_request = True

        if bool(flags & REQUEST) != expected_request:
            raise ValueError("planner request timing mismatch")
        if expected_request:
            request_count += 1

        if row_authority != authority or row_action != action:
            raise ValueError("authority/action revision mismatch")

        if bool(flags & INVALIDATED) != invalidated:
            raise ValueError("invalidation flag mismatch")
        expected_pending_count = int(pending)
        expected_prefix_count = 0 if invalidated else 1
        if pending_count != expected_pending_count:
            raise ValueError("pending-request count mismatch")
        if prefix_count != expected_prefix_count:
            raise ValueError("prefix-record count mismatch")
        max_pending = max(max_pending, pending_count)
        max_prefix = max(max_prefix, prefix_count)

        expected_prefix_um = prepublished_prefix_um if not pending else int(frozen_prefix_um)
        if abs(prefix_um - expected_prefix_um) > 2:
            raise ValueError("published/frozen prefix mismatch")
        usable = True
        if pending:
            assert usable_until_s is not None and frozen_prefix_um is not None
            braking_end = start_x + start_speed * start_speed / (2.0 * max_accel)
            usable = (
                t < usable_until_s - 1e-12 and braking_end < frozen_prefix_um / 1_000_000.0 - 1e-9
            )
        if bool(flags & USABLE) != usable:
            raise ValueError("usable-prefix flag mismatch")
        plan_speed_um = revised_speed_um if mode == "revision" and action == 2 else max_speed_um
        expected_command_um = 0 if invalidated or not usable else plan_speed_um
        if command_um != expected_command_um:
            raise ValueError("command violates the reference handoff policy")

        waiting = (
            not invalidated
            and pending
            and not usable
            and start_speed <= 0.02 + 1e-12
            and previous_x_um < mission_goal_um - 1
        )
        if bool(flags & WAITING) != waiting:
            raise ValueError("waiting flag mismatch")
        prefix_exhausted = pending and not usable
        exhaustion = prefix_exhausted and not previous_prefix_exhausted
        if bool(flags & EXHAUSTION) != exhaustion:
            raise ValueError("prefix-exhaustion event mismatch")
        if exhaustion:
            exhaustion_count += 1
            prefix_unusable_onsets += 1
        waiting_flags.append(waiting)
        if waiting:
            current_wait_run += 1
        elif current_wait_run:
            waiting_runs.append(current_wait_run)
            current_wait_run = 0
        previous_prefix_exhausted = prefix_exhausted

        stale_um = 0
        if authority > action:
            stale_um = max(0, x_um - max(previous_x_um, prefix_um))
            stale_total_um += stale_um
            if command_um > 0 and previous_x_um >= prefix_um:
                old_dispatches += 1
        if bool(flags & STALE) != bool(stale_um):
            raise ValueError("stale flag differs from segment/prefix geometry")

        if (
            obstacle_center_um is not None
            and x_um + round(float(case["robot_half_length_m"]) * 1_000_000.0) >= obstacle_center_um
        ):
            collision = True
        if bool(flags & COLLISION) != collision:
            raise ValueError("collision flag differs from swept-segment oracle")
        if invalidated:
            if first_invalid_ms is None:
                first_invalid_ms = t_ms
            if command_um > 0:
                positive_after_invalidation += 1
                latest_positive_delay = max(
                    latest_positive_delay,
                    (t_ms - first_invalid_ms) / 1000.0,
                )
        if revision_response_s is None and flags & RESPONSE and authority == action == 2:
            revision_response_s = t

        acceleration = (speed_um / 1_000_000.0 - start_speed) / dt
        jerk = abs((acceleration - previous_acceleration) / dt) * (
            1.0 + 0.05 * float(case["curvature_gain"])
        )
        accelerations.append(abs(acceleration))
        jerks.append(jerk)
        if flags & RESPONSE and action_before_tick == 1 and action == 2:
            if splice_acceleration is not None:
                raise ValueError("multiple revision splice samples in one episode")
            splice_acceleration = abs(acceleration)
            splice_jerk = jerk
        previous_x_um = x_um
        previous_speed_um = speed_um
        previous_acceleration = acceleration

    if current_wait_run:
        waiting_runs.append(current_wait_run)
    if event_at_um is not None and event_count != 1:
        raise ValueError("non-control case did not emit exactly one event")
    if event_at_um is None and event_count != 0:
        raise ValueError("control case emitted an event")

    trailing_stationary = 0
    for row in reversed(rows):
        if row[2] <= 10_000:
            trailing_stationary += 1
        else:
            break
    final = rows[-1]
    boundary = stale_total_um > 0
    duration_s = round(final[0] / 1000.0 + dt, 6)
    mission_success = (
        mode in {"control", "revision"}
        and final[1] >= mission_goal_um - 1
        and authority == action
        and not boundary
        and not collision
        and duration_s < float(case["timeout_s"]) - 1e-12
    )
    return {
        "mission_success": mission_success,
        "stop_complete": mode in {"emergency", "occupied"} and trailing_stationary >= 7,
        "event_triggered": event_count == 1,
        "collision": collision,
        "boundary_violation": boundary,
        "waiting_time_s": round(sum(waiting_flags) * dt, 6),
        "wait_runs": len(waiting_runs),
        "visible_gaps": sum(count * dt > 0.50 + 1e-12 for count in waiting_runs),
        "maximum_gap_s": round(max(waiting_runs, default=0) * dt, 6),
        "prefix_exhaustions": exhaustion_count,
        "prefix_unusable_onsets": prefix_unusable_onsets,
        "stale_tail_distance_m": round(stale_total_um / 1_000_000.0, 9),
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
        "request_count": request_count,
        "response_count": response_count,
        "revision_response_s": revision_response_s,
        "max_pending_requests": max_pending,
        "max_prefix_records": max_prefix,
    }


def _aggregate(episodes: list[dict[str, object]]) -> dict[str, object]:
    arms: dict[str, dict[str, object]] = {}
    for arm in ARMS:
        rows = [row for row in episodes if row["arm"] == arm]
        ordinary = [row for row in rows if row["mode"] in {"control", "revision"}]
        invalidation = [row for row in rows if row["mode"] in {"emergency", "occupied"}]
        revisions = [row for row in rows if row["mode"] == "revision"]
        all_s = [row["summary"] for row in rows]
        ord_s = [row["summary"] for row in ordinary]
        inv_s = [row["summary"] for row in invalidation]
        rev_s = [row["summary"] for row in revisions]
        splice_accels = [
            float(s["splice_acceleration_mps2"])
            for s in rev_s
            if s["splice_acceleration_mps2"] is not None
        ]
        splice_jerks = [
            float(s["splice_jerk_mps3"]) for s in rev_s if s["splice_jerk_mps3"] is not None
        ]
        arms[arm] = {
            "episodes": len(rows),
            "ordinary_episodes": len(ordinary),
            "invalidation_episodes": len(invalidation),
            "mission_successes": sum(bool(s["mission_success"]) for s in ord_s),
            "mission_success_rate": round(
                sum(bool(s["mission_success"]) for s in ord_s) / len(ord_s), 9
            ),
            "waiting_time_s": round(sum(float(s["waiting_time_s"]) for s in ord_s), 6),
            "wait_runs": sum(int(s["wait_runs"]) for s in ord_s),
            "visible_gaps": sum(int(s["visible_gaps"]) for s in ord_s),
            "prefix_exhaustions": sum(int(s["prefix_exhaustions"]) for s in ord_s),
            "prefix_unusable_onsets": sum(int(s["prefix_unusable_onsets"]) for s in ord_s),
            "stale_tail_distance_m": round(
                sum(float(s["stale_tail_distance_m"]) for s in all_s), 9
            ),
            "old_revision_dispatch_beyond_prefix": sum(
                int(s["old_revision_dispatch_beyond_prefix"]) for s in all_s
            ),
            "collisions": sum(bool(s["collision"]) for s in all_s),
            "boundary_violations": sum(bool(s["boundary_violation"]) for s in all_s),
            "revision_episodes": len(revisions),
            "revision_splices_observed": len(splice_accels),
            "revision_revised_tails_applied": sum(bool(s["revised_tail_applied"]) for s in rev_s),
            "revision_stale_tail_distance_m": round(
                sum(float(s["stale_tail_distance_m"]) for s in rev_s), 9
            ),
            "revision_old_dispatch_beyond_prefix": sum(
                int(s["old_revision_dispatch_beyond_prefix"]) for s in rev_s
            ),
            "revision_collisions": sum(bool(s["collision"]) for s in rev_s),
            "revision_boundary_violations": sum(bool(s["boundary_violation"]) for s in rev_s),
            "revision_p95_splice_acceleration_mps2": round(_p95(splice_accels), 6),
            "revision_p95_splice_jerk_mps3": round(_p95(splice_jerks), 6),
            "post_invalidation_positive_commands": sum(
                int(s["post_invalidation_positive_commands"]) for s in inv_s
            ),
            "post_invalidation_max_delay_s": max(
                (float(s["post_invalidation_latest_positive_delay_s"]) for s in inv_s), default=0.0
            ),
            "stop_complete": sum(bool(s["stop_complete"]) for s in inv_s),
            "invalidation_collisions": sum(bool(s["collision"]) for s in inv_s),
            "max_pending_requests": max(int(s["max_pending_requests"]) for s in all_s),
            "max_prefix_records": max(int(s["max_prefix_records"]) for s in all_s),
            "p95_acceleration_mps2": round(
                _p95(float(s["p95_acceleration_mps2"]) for s in ord_s), 6
            ),
            "p95_jerk_mps3": round(_p95(float(s["p95_jerk_mps3"]) for s in ord_s), 6),
        }
    b0, f0, g0 = (arms[name] for name in ARMS)
    if float(b0["waiting_time_s"]) <= 0.0 or int(b0["visible_gaps"]) <= 0:
        raise ValueError("B0 produced no wait/gap denominator")
    wait_reduction = 1.0 - float(g0["waiting_time_s"]) / float(b0["waiting_time_s"])
    gap_reduction = 1.0 - float(g0["visible_gaps"]) / float(b0["visible_gaps"])
    better_sr = max(float(b0["mission_success_rate"]), float(f0["mission_success_rate"]))
    h1 = {
        "waiting_reduction_fraction": round(wait_reduction, 9),
        "visible_gap_reduction_fraction": round(gap_reduction, 9),
        "g0_success_delta_from_better": round(float(g0["mission_success_rate"]) - better_sr, 9),
        "pass": wait_reduction >= 0.30
        and gap_reduction >= 0.50
        and float(g0["mission_success_rate"]) >= better_sr - 0.02,
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
    for error in sorted({float(row["estimator_error"]) for row in episodes}):
        all_rows = [
            row for row in episodes if row["arm"] == "G0" and float(row["estimator_error"]) == error
        ]
        ordinary = [row for row in all_rows if row["mode"] in {"control", "revision"}]
        invalidation = [row for row in all_rows if row["mode"] in {"emergency", "occupied"}]
        f0_revisions = [
            row
            for row in episodes
            if row["arm"] == "F0"
            and float(row["estimator_error"]) == error
            and row["mode"] == "revision"
        ]
        g0_revisions = [row for row in all_rows if row["mode"] == "revision"]
        g0_splice_accels = [
            float(row["summary"]["splice_acceleration_mps2"])
            for row in g0_revisions
            if row["summary"]["splice_acceleration_mps2"] is not None
        ]
        g0_splice_jerks = [
            float(row["summary"]["splice_jerk_mps3"])
            for row in g0_revisions
            if row["summary"]["splice_jerk_mps3"] is not None
        ]
        f0_splice_accels = [
            float(row["summary"]["splice_acceleration_mps2"])
            for row in f0_revisions
            if row["summary"]["splice_acceleration_mps2"] is not None
        ]
        f0_splice_jerks = [
            float(row["summary"]["splice_jerk_mps3"])
            for row in f0_revisions
            if row["summary"]["splice_jerk_mps3"] is not None
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
                sum(bool(row["summary"]["mission_success"]) for row in ordinary) / len(ordinary), 9
            ),
            "waiting_time_s": round(
                sum(float(row["summary"]["waiting_time_s"]) for row in ordinary), 6
            ),
            "visible_gaps": sum(int(row["summary"]["visible_gaps"]) for row in ordinary),
            "prefix_exhaustions": sum(
                int(row["summary"]["prefix_exhaustions"]) for row in ordinary
            ),
            "prefix_unusable_onsets": sum(
                int(row["summary"]["prefix_unusable_onsets"]) for row in ordinary
            ),
            "underestimated": error < 0.0,
            "stale_tail_distance_m": round(
                sum(float(row["summary"]["stale_tail_distance_m"]) for row in all_rows), 9
            ),
            "old_revision_dispatch_beyond_prefix": sum(
                int(row["summary"]["old_revision_dispatch_beyond_prefix"]) for row in all_rows
            ),
            "collisions": sum(bool(row["summary"]["collision"]) for row in all_rows),
            "boundary_violations": sum(
                bool(row["summary"]["boundary_violation"]) for row in all_rows
            ),
            "post_invalidation_positive_commands": sum(
                int(row["summary"]["post_invalidation_positive_commands"]) for row in invalidation
            ),
            "stop_complete": sum(bool(row["summary"]["stop_complete"]) for row in invalidation),
            "max_pending_requests": max(
                int(row["summary"]["max_pending_requests"]) for row in all_rows
            ),
            "max_prefix_records": max(
                int(row["summary"]["max_prefix_records"]) for row in all_rows
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
        "preliminary_verdict": "LHO1_H1_H4_PASS_H5_PENDING"
        if all(item["pass"] for item in (h1, h2, h3, h4))
        else "LHO1_REFUTED",
    }


def verify_one(
    result: dict[str, object],
    manifest: dict[str, object],
    source: dict[str, object],
) -> dict[str, object]:
    if result.get("schema_version") != 2:
        raise ValueError("unexpected result schema")
    if result.get("study") != "LHO-1":
        raise ValueError("unexpected study identifier")
    if result.get("evidence_tier") != EVIDENCE_TIER:
        raise ValueError("evidence-tier binding mismatch")
    metadata = result.get("run_metadata")
    if not isinstance(metadata, dict) or metadata.get("case_limit") is not None:
        raise ValueError("result is not a full evidence run")
    if not isinstance(metadata.get("python"), str) or not metadata["python"]:
        raise ValueError("run Python metadata missing")
    if not isinstance(metadata.get("runtime_s"), (int, float)) or metadata["runtime_s"] < 0:
        raise ValueError("run timing metadata invalid")
    if result.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ValueError("result manifest binding mismatch")
    if result.get("source_manifest_sha256") != source["manifest_sha256"]:
        raise ValueError("result source binding mismatch")
    if result.get("inventory") != {"paired_cases": 1980, "arm_episodes": 5940, "arms": list(ARMS)}:
        raise ValueError("result inventory mismatch")
    episodes = result.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != 5940:
        raise ValueError("result episode cardinality mismatch")
    case_map = {row["case_id"]: row for row in manifest["cases"]}
    expected_pairs = {(case_id, arm) for case_id in case_map for arm in ARMS}
    actual_pairs = {(row["case_id"], row["arm"]) for row in episodes}
    if actual_pairs != expected_pairs or len(actual_pairs) != len(episodes):
        raise ValueError("paired case/arm coverage mismatch")
    for episode in episodes:
        case = case_map[episode["case_id"]]
        if episode["case_sha256"] != case["case_sha256"]:
            raise ValueError("episode case binding mismatch")
        if episode.get("trace_encoding") != TRACE_ENCODING:
            raise ValueError("trace encoding binding mismatch")
        for episode_key, case_key in (
            ("mode", "mode"),
            ("family", "family"),
            ("estimator_error", "estimator_error"),
            ("base_latency_s", "base_latency_s"),
        ):
            if episode[episode_key] != case[case_key]:
                raise ValueError(f"episode metadata mismatch: {episode_key}")
        derived = _trace_metrics(episode, case)
        summary = episode["summary"]
        for key, expected in derived.items():
            if summary[key] != expected:
                raise ValueError(
                    f"trace-derived summary mismatch {episode['case_id']} "
                    f"{episode['arm']} {key}: {summary[key]} != {expected}"
                )
    normalized_rows = [
        {
            key: row[key]
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
        for row in episodes
    ]
    digest = _sha(_canonical(normalized_rows))
    if digest != result["normalized_episode_digest"]:
        raise ValueError("normalized episode digest mismatch")
    aggregate = _aggregate(episodes)
    if aggregate != result["aggregate"]:
        raise ValueError("independent aggregate mismatch")
    return {
        "episodes_checked": len(episodes),
        "normalized_episode_digest": digest,
        "aggregate": aggregate,
    }


def _validate_bundle(
    result: dict[str, object],
    manifest: dict[str, object],
    source: dict[str, object],
    *,
    source_overrides: dict[str, bytes] | None = None,
) -> dict[str, object]:
    verify_manifest(manifest)
    _verify_source_value(source, byte_overrides=source_overrides)
    return verify_one(result, manifest, source)


def _tamper_checks(
    result: dict[str, object],
    manifest: dict[str, object],
    source: dict[str, object],
) -> dict[str, bool]:
    checks: dict[str, bool] = {}

    def rejected(
        name: str,
        *,
        altered_result: dict[str, object] | None = None,
        altered_manifest: dict[str, object] | None = None,
        altered_source: dict[str, object] | None = None,
        source_overrides: dict[str, bytes] | None = None,
    ) -> None:
        try:
            _validate_bundle(
                altered_result or result,
                altered_manifest or manifest,
                altered_source or source,
                source_overrides=source_overrides,
            )
        except (AssertionError, KeyError, OSError, TypeError, ValueError, zlib.error):
            checks[name] = True
        else:
            checks[name] = False

    trace = copy.deepcopy(result)
    raw = bytearray(zlib.decompress(base64.b64decode(trace["episodes"][0]["trace_b64"])))
    raw[12] ^= 1
    trace["episodes"][0]["trace_b64"] = base64.b64encode(zlib.compress(bytes(raw), 9)).decode(
        "ascii"
    )
    rejected("trace_command", altered_result=trace)

    revision = copy.deepcopy(manifest)
    revision["cases"][0]["event_decile"] = 9 if revision["cases"][0]["event_decile"] != 9 else 8
    rejected("revision_manifest", altered_manifest=revision)

    aggregate = copy.deepcopy(result)
    aggregate["aggregate"]["arms"]["G0"]["visible_gaps"] += 1
    rejected("aggregate_scalar", altered_result=aggregate)

    first_source = min(source["files"])
    altered_bytes = (ROOT / first_source).read_bytes() + b"\nTAMPER"
    rejected("source_file", source_overrides={first_source: altered_bytes})

    manifest_digest = copy.deepcopy(manifest)
    manifest_digest["manifest_sha256"] = "0" * 64
    rejected("manifest_digest", altered_manifest=manifest_digest)
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.json")
    parser.add_argument("--source-manifest", type=Path, default=ROOT / "source-manifest.json")
    parser.add_argument("--run-a", type=Path, required=True)
    parser.add_argument("--run-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    verify_manifest(manifest)
    source = _verify_source_manifest(args.source_manifest)
    run_a = json.loads(args.run_a.read_text(encoding="ascii"))
    run_b = json.loads(args.run_b.read_text(encoding="ascii"))
    checked_a = verify_one(run_a, manifest, source)
    checked_b = verify_one(run_b, manifest, source)
    normalized_equal = (
        run_a["normalized_episode_digest"] == run_b["normalized_episode_digest"]
        and run_a["aggregate"] == run_b["aggregate"]
    )
    if not normalized_equal:
        raise ValueError("fresh runs are not normalized-identical")
    tamper = _tamper_checks(run_a, manifest, source)
    if not all(tamper.values()):
        raise ValueError(f"tamper checks failed: {tamper}")
    h1_h4 = all(bool(row["pass"]) for row in run_a["aggregate"]["hypotheses"].values())
    output = {
        "schema_version": 2,
        "study": "LHO-1",
        "integrity_status": "PASS",
        "runs_normalized_identical": normalized_equal,
        "run_a": checked_a,
        "run_b": checked_b,
        "tamper_checks": tamper,
        "H5": {"pass": True},
        "verdict": "LHO1_MECHANISM_PASS" if h1_h4 else "LHO1_REFUTED",
        "does_not_prove": [
            "learned Model A capability",
            "2-D route or semantic navigation competence",
            "camera or LiDAR perception",
            "quadruped dynamics or physical braking",
            "Orin timing or Go2 mount readiness",
        ],
    }
    output["verification_sha256"] = _sha(_canonical(output))
    args.output.write_bytes(_canonical(output) + b"\n")
    print(
        json.dumps(
            {
                "status": output["integrity_status"],
                "verdict": output["verdict"],
                "verification_sha256": output["verification_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
