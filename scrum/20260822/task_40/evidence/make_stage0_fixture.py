"""Build the SYNTHESISED Stage-0 replay fixture. Card HW-2 (task_40).

Nothing in this tree ever recorded ``SportModeState_`` or a Livox datagram to
disk: ``scrum/20260813/task_1/`` holds the Stage-0 PLAN, the channel matrix and
the run sheet, not samples. So the fixture the tests replay is synthesised
here, deterministically, and says so in its own header line.

Run:  .parcel/bin/python scrum/20260822/task_40/evidence/make_stage0_fixture.py \
          --out tests/data/hw2_stage0_replay.jsonl

**It refuses to write into the tree unless you say where** (verifier finding
F7: an earlier version ignored argv entirely and rewrote the shipped fixture on
any invocation -- the verifier's own `--help` regenerated it, byte-identically
because the generator is deterministic, but a fixture that rewrites itself when
someone reads its help is a fixture nobody can trust). With no `--out` it
prints the recording to stdout.

The scene is a Stage-0 take: the dog STANDS (nothing is commanded, which is
what Stage 0 means) while a wall ahead is re-measured six times at 10 Hz from
2.0 m down to 0.85 m -- so one recording carries both a `clear` frame and a
`stopped` frame through the real `reactive_safety` gate, with `obstacle_slow_m
1.2` / `obstacle_stop_m 0.65` (configs/robot.yaml:312) as the thresholds and
the footprint radius 0.32 m subtracted by `nearest_obstacle_from_scan`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from parcel_robot.lidar import LivoxDataType, build_point_frame

REPO = Path(__file__).resolve().parents[4]

#: The path the shipped fixture lives at. NOT a default: `--out` must name it.
SHIPPED = "tests/data/hw2_stage0_replay.jsonl"

#: Metres, one per point frame. The wall the dog is looking at.
WALL_DISTANCES_M = (2.00, 2.00, 1.60, 1.20, 0.95, 0.85)

#: 50 Hz state, 10 Hz frames -- the Go2's own `rt/sportmodestate` rate and a
#: conservative Mid-360 publish rate (design §5.3; the real cadence is a
#: box-day measurement).
STATE_PERIOD_S = 0.02
FRAME_PERIOD_S = 0.10

#: Above `BandProfile.z_hi_m` (0.60), so the band must drop them. They are in
#: the recording on purpose: a fixture with only in-band points cannot show
#: that the filter filters.
CEILING_Z_M = 1.50

#: The dog is standing. Stage 0 commands nothing, so these are the resting
#: numbers `CommissioningObserver` refuses to see exceeded.
RESTING_VELOCITY = (0.0, 0.0, 0.0)


def _wall_points(distance_m: float) -> list[tuple[int, int, int, int, int]]:
    """A wall ahead, a ceiling above it, and a far wall behind. Wire units (mm)."""

    points: list[tuple[int, int, int, int, int]] = []
    y = -0.60
    while y <= 0.60 + 1e-9:
        points.append((round(distance_m * 1000), round(y * 1000), 300, 40, 0))
        points.append((round(distance_m * 1000), round(y * 1000), round(CEILING_Z_M * 1000), 12, 0))
        y += 0.05
    for y_behind in (-0.2, 0.0, 0.2):
        points.append((-3000, round(y_behind * 1000), 250, 30, 0))
    return points


def _state(index: int, yaw: float) -> dict[str, object]:
    return {
        "stamp_ns": 1_700_000_000_000_000_000 + index * int(STATE_PERIOD_S * 1e9),
        "mode": 1,
        "gait_type": 0,
        "error_code": 0,
        "position": [0.0, 0.0, 0.32],
        "velocity": list(RESTING_VELOCITY),
        "yaw_speed": 0.0,
        "foot_force": [118, 121, 119, 120],
        "imu_state": {
            "present": True,
            "rpy_rad": [0.0, 0.0, yaw],
            "accelerometer_mps2": [0.0, 0.0, 9.81],
            "gyroscope_rps": [0.0, 0.0, 0.0],
        },
    }


def build_lines() -> list[str]:
    lines: list[str] = [
        json.dumps(
            {
                "schema": "parcel.stage0_replay.v1",
                "synthesised": True,
                "generator": "scrum/20260822/task_40/evidence/make_stage0_fixture.py",
                "session_epoch": "hw2-synthetic-2026-08-23",
                "note": (
                    "NOT A RECORDING OF A ROBOT. No Go2 and no Mid-360 exist on this "
                    "host (owner, 2026-08-22). The SportModeState field names are this "
                    "tree's own decoder's (scripts/parcel_capture/ingest/dds.py"
                    ":decode_sport_mode_state) and frame_hex is a real Livox SDK2 "
                    "datagram built by parcel_robot.lidar.build_point_frame, so one "
                    "real box-day capture replaces this file without a format change. "
                    "Box-day HW-9 falsifies it in one datagram."
                ),
                "scene": (
                    "the dog stands still while a wall ahead is measured six times at "
                    "10 Hz from 2.00 m to 0.85 m"
                ),
            },
            sort_keys=True,
        )
    ]

    events: list[tuple[float, dict[str, object]]] = []
    total_s = len(WALL_DISTANCES_M) * FRAME_PERIOD_S
    for index in range(round(total_s / STATE_PERIOD_S)):
        offset = round(index * STATE_PERIOD_S, 6)
        events.append(
            (
                offset,
                {
                    "t_s": offset,
                    "channel": "rt/sportmodestate",
                    "sport_mode_state": _state(index, yaw=0.0),
                },
            )
        )
    for index, distance in enumerate(WALL_DISTANCES_M):
        offset = round(index * FRAME_PERIOD_S, 6)
        payload = build_point_frame(
            _wall_points(distance),
            data_type=LivoxDataType.CARTESIAN_HIGH,
            frame_cnt=index % 256,
            udp_cnt=index,
            base_timestamp_ns=1_700_000_000_000_000_000 + index * int(FRAME_PERIOD_S * 1e9),
            time_interval_raw=1000,
        )
        events.append(
            (
                offset + 1e-9,  # a frame lands just after the state sample it follows
                {
                    "t_s": offset,
                    "channel": "livox/mid360/points",
                    "frame_hex": payload.hex(),
                    "wall_distance_m": distance,
                },
            )
        )

    events.sort(key=lambda item: item[0])
    lines.extend(json.dumps(record, sort_keys=True) for _offset, record in events)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the synthesised HW-2 Stage-0 replay fixture.",
        epilog=f"the shipped fixture lives at {SHIPPED}",
    )
    parser.add_argument(
        "--out",
        default=None,
        help=f"write here (e.g. {SHIPPED}); without it the recording goes to stdout",
    )
    args = parser.parse_args(argv)

    lines = build_lines()
    document = "\n".join(lines) + "\n"
    if args.out is None:
        sys.stdout.write(document)
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")
    print(f"{out}: {len(lines)} lines, {out.stat().st_size} bytes", file=sys.stderr)
    print(
        f"wall distances {WALL_DISTANCES_M}; clearances "
        f"{tuple(round(max(0.0, d - 0.32), 3) for d in WALL_DISTANCES_M)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
