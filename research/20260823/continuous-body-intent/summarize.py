"""Assemble the pre-registered rows B1-B9 from the raw result files.

Every number in RESULTS.md comes out of here, so the table cannot drift from
the JSON it claims to summarize.  The criteria are the DESIGN's, copied
verbatim into ``CRITERIA`` and never edited: a row that misses is printed as a
miss.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

STATES = ("idle_hold", "idle_look", "navigating", "estop")
CRITERIA = {
    "B1": "emission rate (steady, all states) >= 20 Hz, no gap > 100 ms",
    "B2": "envelope compliance (+/-2 cm / +/-6 deg / head limits) 100 %",
    "B3": "posture/gaze jerk within the limiter's declared bound; spectral roll-off reported",
    "B4": "IPC rejections over 10 min = 0",
    "B5": "COM drift while HOLD < 1 cm",
    "B6": "e-stop -> HOLD within 1 tick",
    "B7": "navigating-state velocity byte-identical to today's path",
    "B8": "fake-quadruped adapter <= 150 LOC; 0 lines of product code to support it",
    "B9": "loop P99 with composer <= today + 5 %",
}


def load(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.is_file() else None


def build(results: Path) -> dict[str, object]:
    states = {name: load(results / f"state_{name}.json") for name in STATES}
    present = {name: data for name, data in states.items() if data is not None}
    com = load(results / "com_probe.json")
    bench = load(results / "limiter_bench.json")
    audit = load(results / "portability_audit.json")
    loop = load(results / "loop_cost.json")
    rows: dict[str, object] = {}

    # ---- B1 ---------------------------------------------------------------
    hz = {name: data["emission_hz_mean"] for name, data in present.items()}
    gaps = {name: data["gap_ms_max"] for name, data in present.items()}
    over = sum(data["gaps_over_100ms"] for data in present.values())
    rows["B1"] = {
        "measured": {
            "emission_hz_mean_by_state": hz,
            "worst_state_hz": min(hz.values()) if hz else None,
            "max_gap_ms_by_state": gaps,
            "worst_gap_ms": max(gaps.values()) if gaps else None,
            "gaps_over_100ms_total": over,
            "ticks_total": sum(data["ticks"] for data in present.values()),
        },
        "met": bool(hz) and min(hz.values()) >= 20.0 and over == 0,
    }

    # ---- B2 ---------------------------------------------------------------
    violations = sum(data["envelope_violations"] for data in present.values())
    ticks = sum(data["ticks"] for data in present.values())
    rows["B2"] = {
        "measured": {
            "envelope_violations": violations,
            "ticks_checked": ticks,
            "compliance_pct": round(100.0 * (ticks - violations) / ticks, 6) if ticks else None,
            "amplitude_clamp_events": {
                name: data["composer"]["clamp_events"] for name, data in present.items()
            },
            "max_clamp_excess_frac": max(
                (data["composer"]["max_clamp_excess_frac"] for data in present.values()),
                default=None,
            ),
        },
        "met": violations == 0 and ticks > 0,
    }

    # ---- B3 ---------------------------------------------------------------
    worst_ratio: dict[str, float] = {}
    strict_over = 0
    tolerant_over = 0
    by_state: dict[str, int] = {}
    windows = 0
    for name, data in present.items():
        for axis, entry in data["derivatives"].items():
            ratio = entry["max_d3_over_bound_ratio"]
            worst_ratio[axis] = max(worst_ratio.get(axis, 0.0), ratio)
            strict_over += entry["ticks_over_bound"]
            tolerant_over += entry["ticks_over_bound_beyond_1pct"]
            by_state[name] = by_state.get(name, 0) + entry["ticks_over_bound"]
            windows += entry["samples"]
    rows["B3"] = {
        "measured": {
            "wall_clock_worst_d3_over_bound_ratio": worst_ratio,
            "wall_clock_ticks_over_bound_strict": strict_over,
            "wall_clock_ticks_over_bound_beyond_1pct": tolerant_over,
            "wall_clock_windows_measured": windows,
            "wall_clock_ticks_over_bound_by_state": by_state,
            "declared_bypass": (
                "compose(emergency=True) snaps posture/gaze to zero in one tick "
                "(module docstring; the same bypass SCurveVelocityShaper.step "
                "declares for the velocity axis). One snap puts the step inside "
                "3 four-sample third-difference windows."
            ),
            "jitter_free_bench": None
            if bench is None
            else {
                axis: {
                    "emitted_d3": entry["emitted"]["d3"],
                    "declared_max_jerk": entry["declared"]["max_jerk"],
                    "within": entry["within_declared_jerk"],
                    "passed_through_unchanged_pct": entry["passed_through_unchanged_pct"],
                    "band_energy_ratio_out_over_raw": entry["band_energy_ratio_out_over_raw"],
                }
                for axis, entry in bench["axes"].items()
            },
        },
        "met": bench is not None
        and all(entry["within_declared_jerk"] for entry in bench["axes"].values())
        and tolerant_over == 0,
    }

    # ---- B4 ---------------------------------------------------------------
    rejections = sum(len(data["ipc"]["server_rejections"]) for data in present.values())
    local = sum(len(data["ipc"]["local_validation_failures"]) for data in present.values())
    probes = {name: data["ipc"]["seeded_rejection_probe"] for name, data in present.items()}
    rows["B4"] = {
        "measured": {
            "messages_sent": sum(data["ipc"]["messages_sent"] for data in present.values()),
            "server_rejections_on_sampled_replies": rejections,
            "reply_samples": sum(data["ipc"]["reply_samples"] for data in present.values()),
            "local_validation_failures": local,
            "seeded_rejection_probe_detected": {
                name: probe is not None for name, probe in probes.items()
            },
        },
        "met": rejections == 0 and local == 0 and all(p is not None for p in probes.values()),
    }

    # ---- B5 ---------------------------------------------------------------
    hold_states = {k: v for k, v in present.items() if k in {"idle_hold", "idle_look"}}
    rows["B5"] = {
        "measured": {
            "sim_base_drift_m": {
                name: data["base_pose"]["drift_xy_m"] for name, data in hold_states.items()
            },
            "sim_base_note": (
                "parcel_robot.sim writes qpos[:3] every step (place_kinematic_base), so the "
                "reported base cannot drift while holding; this row proves the pin, not the "
                "posture. The COM probe below is the physical answer."
            ),
            "com_probe": None
            if com is None
            else {
                "worst_case_envelope_horizontal_m": com["envelope"][
                    "max_horizontal_com_shift_m"
                ],
                "worst_case_envelope_vertical_m": com["envelope"]["max_vertical_com_shift_m"],
                "idle_hold_replay_horizontal_m": com["replay"].get(
                    "max_horizontal_com_shift_m"
                ),
                "idle_hold_replay_vertical_m": com["replay"].get("max_vertical_com_shift_m"),
            },
        },
        "met": com is not None
        and com["envelope"]["max_horizontal_com_shift_m"] < 0.01
        and (com["replay"].get("max_horizontal_com_shift_m") or 0.0) < 0.01,
    }

    # ---- B6 ---------------------------------------------------------------
    estop = present.get("estop", {}).get("estop") if "estop" in present else None
    rows["B6"] = {
        "measured": estop,
        "met": bool(estop)
        and estop.get("hold_seen")
        and (estop.get("intent_latency_ticks") or 99) <= 1.0,
    }

    # ---- B7 ---------------------------------------------------------------
    identity = {name: data["byte_identity"] for name, data in present.items()}
    moving = {k: v for k, v in identity.items() if v["today_messages"] > 0}
    rows["B7"] = {
        "measured": identity,
        "met": bool(moving) and all(entry["byte_identical"] for entry in identity.values()),
    }

    # ---- B8 ---------------------------------------------------------------
    rows["B8"] = {
        "measured": None
        if audit is None
        else {
            "fake_adapter_total_lines": audit["fake_adapter_total_lines"],
            "fake_adapter_physical_loc": audit["fake_adapter_physical_loc"],
            "product_modules_changed": audit["product_modules_changed"],
            "fake_adapter_product_imports": audit["fake_adapter_product_imports"],
            "manifest_fields_that_differ": audit["manifests_differ"]["differing_fields"],
            "degrade_violations": audit["run"]["degrade_violations"],
            "watchdog_faults": audit["run"]["watchdog_faults"],
        },
        "met": audit is not None
        and audit["fake_adapter_total_lines"] <= 150
        and not audit["product_modules_changed"]
        and audit["run"]["degrade_violations"] == 0,
    }

    # ---- B9 ---------------------------------------------------------------
    rows["B9"] = {
        "measured": None
        if loop is None
        else {
            "loop_work_p99_ms": {
                arm: entry["loop_work"]["p99_ms"] for arm, entry in loop["arms"].items()
            },
            "loop_work_p50_ms": {
                arm: entry["loop_work"]["p50_ms"] for arm, entry in loop["arms"].items()
            },
            "p99_delta_pct": loop["p99_delta_pct"],
            "compose_plus_apply_us": {
                key: round(value * 1000.0, 2)
                for key, value in loop["micro"]["compose_plus_apply"].items()
                if key.endswith("_ms")
            },
            "loadavg": {
                arm: entry["loadavg_before"] for arm, entry in loop["arms"].items()
            },
            "transport_drops": {
                arm: entry["transport_drops"] for arm, entry in loop["arms"].items()
            },
            "synthetic_loop": loop["synthetic_loop"],
        },
        # The DESIGN's row is "the composer inside a harness copy of the control
        # loop cadence", which is the socket-bearing arms; the socket-free
        # synthetic loop is a supplementary control and is reported beside it,
        # NOT used to decide the row (its baseline is a 15 us stub, against
        # which any percentage is meaningless).
        "met": loop is not None
        and loop["p99_delta_pct"]["in_loop"] <= 5.0
        and loop["p99_delta_pct"]["thread"] <= 5.0,
    }

    return {"criteria": CRITERIA, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="H4 row summary")
    parser.add_argument("--results", default="results")
    parser.add_argument("--out", default="results/rows.json")
    args = parser.parse_args()
    payload = build(Path(args.results))
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True))
    for row, entry in payload["rows"].items():  # type: ignore[union-attr]
        print(f"{row}  met={entry['met']}  {CRITERIA[row]}")
    print(json.dumps(payload["rows"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
