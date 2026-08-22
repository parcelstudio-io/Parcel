"""ROAM-1 — the roam behavior measured through the PRODUCT path.

MOVE-1's harness (``scrum/20260821/task_20/evidence/run_move1_patrol.py``) is
the reference and this is deliberately NOT a copy of it. MOVE-1 drove
``PatrolRunner`` itself: it owned the clock, the sensing and the submit call,
so what it measured was the policy. This card's claim is about the PRODUCT —
whether the runtime's own control loop ever asks the policy anything — so this
harness never constructs a policy, a runner or a sense. It says "go explore"
through ``submit_realtime_transcript`` and then only WATCHES ``snapshot()``.

Every row it reports is therefore a row about the shipped behavior, and the
only thing this file contributes is the stopwatch.
"""

from __future__ import annotations

import os

os.environ.setdefault("MUJOCO_GL", "egl")

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scrum" / "20260821" / "task_20" / "evidence"))

#: The PROTOTYPE profile's social zone (card P1-E), because that is the robot
#: the card is about. 1.2 m is the shipped value and MOVE-1's condition; it is
#: available as ``--person-stop`` so the two are comparable.
CONFIG = """
skills:
  root: {skills}
simulation:
  scene: {scene}
navigation:
  enabled: true
safety:
  person_stop_m: {person_stop}
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
duplex:
  log_dir: {log_dir}
perception:
  spatial_sensors: [camera, lidar]
  camera_ingress: true
  camera_ingress_rate_hz: 2.0
  camera_ingress_queue_capacity: 64
  camera_ingress_max_detections_per_frame: 8
  camera_ingress_queries: [{queries}]
"""

from run_move1_diagnosis import sha256_file, start_simulator, stop_simulator


def _clearance(snapshot: dict, envelope_m: float) -> float | None:
    """Nearest person clearance the way the patrol adapter computes it."""

    robot = snapshot.get("robot") or {}
    best: float | None = None
    nearest = snapshot.get("nearest_person")
    if isinstance(nearest, dict) and isinstance(nearest.get("distance_m"), (int, float)):
        best = float(nearest["distance_m"])
    owner = snapshot.get("owner") or {}
    if owner.get("visible"):
        try:
            distance = math.hypot(
                float(owner["x"]) - float(robot["x"]), float(owner["y"]) - float(robot["y"])
            )
        except (KeyError, TypeError, ValueError):
            distance = None
        if distance is not None:
            adjusted = max(0.0, distance - envelope_m)
            best = adjusted if best is None else min(best, adjusted)
    return best


#: Half-extent of the dev scene's rendered road plane, metres. ``city_block``
#: renders a 24 x 24 m plane and nothing fences it: past the edge the robot is
#: driving across an unfenced infinite ground plane, and every metre it banks
#: out there is net displacement measured off the map. Card ROAM-1's untethered
#: run did exactly that (out at t = 85 s, 138 of 479 samples outside), so the
#: metric now carries a QUALIFIER rather than a footnote.
BLOCK_HALF_EXTENT_M = 12.0


def in_block_metrics(samples: list[dict], half_extent_m: float) -> dict:
    """Net displacement WITH the in-bounds qualifier, plus the raw number.

    Two numbers, both reported, neither replacing the other:

    * ``net_displacement_m`` — ``|last - first|`` over every sample, which is
      what the card's row was measured with and what the 20.67 m run scored.
    * ``net_displacement_in_block_m`` — the same distance evaluated at the LAST
      sample that was still inside the plane. For a run that never leaves, the
      two are identical by construction; for one that does, the difference is
      exactly the credit taken off the rendered map.

    ``in_bounds`` is the flag: False means the run left the plane and its raw
    net displacement is not a number about this scene.
    """

    if not samples:
        return {
            "block_half_extent_m": half_extent_m,
            "in_bounds": True,
            "net_displacement_m": 0.0,
            "net_displacement_in_block_m": 0.0,
            "out_of_block_samples": 0,
            "left_block_at_s": None,
            "max_abs_x_m": None,
            "max_abs_y_m": None,
        }

    def inside(sample: dict) -> bool:
        return abs(float(sample["x"])) <= half_extent_m and abs(float(sample["y"])) <= half_extent_m

    first = samples[0]
    raw = math.hypot(samples[-1]["x"] - first["x"], samples[-1]["y"] - first["y"])
    outside = [s for s in samples if not inside(s)]
    last_inside = None
    for sample in samples:
        if inside(sample):
            last_inside = sample
        else:
            break
    if last_inside is None:
        last_inside = first
    in_block = math.hypot(last_inside["x"] - first["x"], last_inside["y"] - first["y"])
    return {
        "block_half_extent_m": half_extent_m,
        "in_bounds": not outside,
        "net_displacement_m": round(raw, 6),
        "net_displacement_in_block_m": round(in_block, 6),
        "out_of_block_samples": len(outside),
        "left_block_at_s": float(outside[0]["t_s"]) if outside else None,
        "max_abs_x_m": round(max(abs(float(s["x"])) for s in samples), 6),
        "max_abs_y_m": round(max(abs(float(s["y"])) for s in samples), 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=120.0)
    parser.add_argument("--scene", default="city_block")
    parser.add_argument("--person-stop", type=float, default=0.7)
    parser.add_argument("--static-city", dest="static", action="store_true", default=True)
    parser.add_argument("--dynamic-city", dest="static", action="store_false")
    parser.add_argument("--sample-hz", type=float, default=4.0)
    parser.add_argument("--block-half-extent", type=float, default=BLOCK_HALF_EXTENT_M)
    #: Where the sim's unix socket lives. Never the owner's
    #: ``/tmp/parcel_sim.sock``: the name always carries this process's pid, and
    #: a concurrent session can point the whole thing at its own scratch dir.
    parser.add_argument("--socket-dir", default="/tmp")
    #: Where the duplex session log goes. Correction pass 2: without this the
    #: runtime writes ``logs/duplex/<session>.jsonl`` INTO THE REPOSITORY (the
    #: `duplex.log_dir` default is a relative path), so every measurement run
    #: left a file behind in a directory that already holds 13 000 of them.
    #: Gitignored, but not this harness's to grow.
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from parcel_robot.patrol import ingress_queries
    from parcel_robot.web_panel import build_runtime

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    arm = "static" if args.static else "dynamic"
    out_dir = Path(args.out or (Path(__file__).parent / f"roam_{arm}_{stamp}"))
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = REPO / "src" / "parcel_robot" / "scenes" / f"{args.scene}.xml"
    if not scene.is_file():
        raise SystemExit(f"no such scene: {scene}")

    batch = ingress_queries(8)
    log_dir = Path(args.log_dir or (Path(args.socket_dir) / "duplex-logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    config_path = out_dir / "roam.yaml"
    config_path.write_text(
        CONFIG.format(
            skills=REPO / "configs" / "skills",
            scene=scene,
            queries=", ".join(batch),
            person_stop=args.person_stop,
            log_dir=log_dir,
        ),
        encoding="utf-8",
    )

    # THE OWNER'S STORE, from the product's own authority. Correction pass 2:
    # this used to hash ``~/.parcel/parcel_memory.sqlite3``, which the product
    # does not use — the file does not exist on this host, so the run recorded
    # ``owner_store.unchanged: true`` about nothing at all. ``owner_store_paths()``
    # is the same function ``memory_path`` uses to decide what an owner store IS,
    # and its first entry (``<repo>/parcel_memory.sqlite3``) is the real one.
    from parcel_robot.memory_path import owner_store_paths

    store = Path(owner_store_paths()[0])
    owner_before = sha256_file(store) if store.is_file() else None
    owner_mtime_before = store.stat().st_mtime if store.is_file() else None

    socket_path = Path(args.socket_dir) / f"parcel-roam1-{os.getpid()}.sock"
    process, handle = start_simulator(
        config_path=config_path,
        socket_path=socket_path,
        log_path=out_dir / "simulator.log",
        static_city=args.static,
    )

    samples: list[dict] = []
    report: dict = {}
    try:
        runtime = build_runtime(config_path, socket_path, use_llm=False)
        runtime.start()
        try:
            # Let the first observations land so the roam does not start blind.
            time.sleep(2.0)
            envelope = runtime.spatial.config.owner_collision_envelope_m

            # ---- ROW R1: spoken "go explore" -> patrol ticking -------------
            asked_at = time.monotonic()
            outcome = runtime.submit_realtime_transcript("Go explore.")
            returned_at = time.monotonic()
            first_tick_at = None
            while time.monotonic() - asked_at < 5.0:
                if int(runtime.roam_snapshot().get("ticks") or 0) > 0:
                    first_tick_at = time.monotonic()
                    break
                time.sleep(0.02)

            started = time.monotonic()
            period = 1.0 / args.sample_hz
            while time.monotonic() - started < args.budget:
                snapshot = runtime.snapshot()
                roam = snapshot.get("roam") or {}
                robot = snapshot.get("robot") or {}
                samples.append(
                    {
                        "t_s": round(time.monotonic() - started, 4),
                        "x": float(robot.get("x", 0.0)),
                        "y": float(robot.get("y", 0.0)),
                        "heading_deg": float(robot.get("heading", 0.0)),
                        "collision": bool(snapshot.get("collision")),
                        "roam_active": bool(roam.get("active")),
                        "roam_reason": str(roam.get("reason", "")),
                        "person_clearance_m": _clearance(snapshot, envelope),
                    }
                )
                time.sleep(period)

            # ---- ROW R3: "stop roaming" latches to idle --------------------
            stop_asked = time.monotonic()
            was_active = bool(runtime.roam_snapshot().get("active"))
            if not was_active:
                runtime.start_roam(30.0)
                time.sleep(0.5)
            stop_outcome = runtime.submit_realtime_transcript("stop roaming")
            stop_returned = time.monotonic()
            stop_state = runtime.roam_snapshot()
            final_roam = runtime.roam_snapshot()
            report = {
                "ingress": outcome.as_dict(),
                "ingress_latency_s": round(returned_at - asked_at, 4),
                "first_tick_latency_s": (
                    round(first_tick_at - asked_at, 4) if first_tick_at else None
                ),
                "stop": stop_outcome.as_dict(),
                "stop_latency_s": round(stop_returned - stop_asked, 4),
                "stop_active_after": bool(stop_state.get("active")),
                "roam_final": final_roam,
                "loop_period_s": runtime.loop_period,
            }
        finally:
            runtime.close()
    finally:
        returncode = stop_simulator(process, handle, socket_path)

    owner_after = sha256_file(store) if store.is_file() else None
    owner_mtime_after = store.stat().st_mtime if store.is_file() else None

    path_length = 0.0
    for before, after in pairwise(samples):
        path_length += math.hypot(after["x"] - before["x"], after["y"] - before["y"])
    net = (
        math.hypot(samples[-1]["x"] - samples[0]["x"], samples[-1]["y"] - samples[0]["y"])
        if len(samples) >= 2
        else 0.0
    )
    clearances = [s["person_clearance_m"] for s in samples if s["person_clearance_m"] is not None]
    reasons: dict[str, int] = {}
    for sample in samples:
        reasons[sample["roam_reason"]] = reasons.get(sample["roam_reason"], 0) + 1

    bounds = in_block_metrics(samples, float(args.block_half_extent))

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "arm": arm,
        "budget_s": args.budget,
        "person_stop_m": args.person_stop,
        "scene": str(scene),
        "scene_sha256": sha256_file(scene),
        "repo_head": subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "simulator_returncode": returncode,
        "samples": len(samples),
        "path_length_m": round(path_length, 6),
        "net_displacement_m": round(net, 6),
        # Card ROAM-1 correction pass: the qualifier travels with the metric.
        "in_bounds": bounds["in_bounds"],
        "net_displacement_in_block_m": bounds["net_displacement_in_block_m"],
        "bounds": bounds,
        "collision_ticks": sum(1 for s in samples if s["collision"]),
        "roam_active_samples": sum(1 for s in samples if s["roam_active"]),
        "min_person_clearance_m": round(min(clearances), 6) if clearances else None,
        "reasons": dict(sorted(reasons.items())),
        "owner_store": {
            "path": str(store),
            "exists": store.is_file(),
            "sha256_before": owner_before,
            "sha256_after": owner_after,
            "mtime_before": owner_mtime_before,
            "mtime_after": owner_mtime_after,
            # ``unchanged`` on a file that does not exist is a sentence about
            # nothing, so the two are reported apart.
            "unchanged": bool(store.is_file()) and owner_before == owner_after,
        },
        **report,
        "trace": samples,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    headline = {
        key: payload[key]
        for key in (
            "arm",
            "person_stop_m",
            "path_length_m",
            "net_displacement_m",
            "net_displacement_in_block_m",
            "in_bounds",
            "bounds",
            "collision_ticks",
            "min_person_clearance_m",
            "roam_active_samples",
            "samples",
            "reasons",
            "ingress_latency_s",
            "first_tick_latency_s",
            "stop_latency_s",
            "stop_active_after",
            "owner_store",
        )
    }
    print(json.dumps(headline, indent=2))
    print(f"\nwrote {out_dir}/summary.json")


if __name__ == "__main__":
    main()
