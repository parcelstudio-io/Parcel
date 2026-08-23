"""ROAM-2 — COVERAGE measured through the PRODUCT path.

Card `scrum/20260822/task_33`, pre-registered in `../PREREGISTRATION.md`.

This is ROAM-1's harness (`../../task_23/evidence/run_roam1.py`) with one thing
added and nothing taken away. Like it, this file **never constructs a
PatrolPolicy, a PatrolRunner or a PatrolSense**: it says "Go explore." through
``submit_realtime_transcript`` and then only WATCHES ``snapshot()`` /
``roam_snapshot()``. The only things it contributes are the stopwatch and the
post-hoc geometry.

WHAT IS ADDED, and why each piece is here:

* ``navigation.config: configs/navigation/prototype.yaml`` — the learned-map
  profile. Under the shipping ``oracle`` source the runtime constructs no
  learned map at all and this whole card is inert (DESIGN §g risk 4), so this
  is a CONDITION OF THE NUMBER, recorded in every summary.
* ``PARCEL_ONLINE_MAP_PATH`` — P1-B's store, always an absolute path under the
  card's own scratch dir. Never the owner's ``parcel_memory.sqlite3``.
* ``roam: {coverage: true|false}`` — THE ONE LINE that separates the two arms.
* The coverage metric itself, computed **from the map's own visibility rule**
  (``OnlineSemanticMap._was_expected_visible``, the same predicate
  ``close_visit`` decays against) over the SEED map's entries and this run's
  sampled path. Sim ground truth is never read.

The seed map is copied fresh into every run, so ``|S|`` is the same integer in
both arms and the denominator cannot drift between them.
"""

from __future__ import annotations

import os

os.environ.setdefault("MUJOCO_GL", "egl")

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scrum" / "20260821" / "task_20" / "evidence"))

#: ROAM-1's config, plus the three blocks named in the module docstring. The
#: ``roam`` block is written by ``main`` so the coverage line is visible in the
#: on-disk config of every run and a verifier can diff arm A against arm B.
CONFIG = """
skills:
  root: {skills}
simulation:
  scene: {scene}
navigation:
  enabled: true
  config: {nav_config}
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
roam:
  budget_s: {roam_budget}
  coverage: {coverage}
  tether_m: {tether}
perception:
  spatial_sensors: [camera, lidar]
  camera_ingress: true
  camera_ingress_rate_hz: 2.0
  camera_ingress_queue_capacity: 64
  camera_ingress_max_detections_per_frame: 8
  camera_ingress_queries: [{queries}]
"""

from run_move1_diagnosis import sha256_file, start_simulator, stop_simulator

BLOCK_HALF_EXTENT_M = 12.0


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


def in_block_metrics(samples: list[dict], half_extent_m: float) -> dict:
    """ROAM-1's in-bounds qualifier, verbatim (``run_roam1.py``)."""

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


# ===========================================================================
# THE METRIC (PREREGISTRATION §1)
# ===========================================================================
def read_seed_entries(store_path: Path) -> tuple[list[dict], float]:
    """``S`` — the entries the learned map knows AT THE START, and its rule.

    Opened through ``OnlineSemanticMap`` itself rather than by reading the
    sqlite file, so the set is exactly what the runtime will reload and the
    visibility number is the map's own.
    """

    from parcel_robot.online_map import OnlineMapStore, OnlineSemanticMap
    from parcel_robot.online_map.entries import WriterProvenance

    probe = OnlineSemanticMap(
        OnlineMapStore(str(store_path)),
        provenance=WriterProvenance(
            session_id="roam2-probe",
            seat="in_loop_query",
            detector_name="owlv2-b16-int8",
            scene_id="city_block",
        ),
        reload=True,
    )
    rows = [
        {
            "entry_id": entry.entry_id,
            "label": entry.label,
            "surface_x": float(entry.surface_x),
            "surface_y": float(entry.surface_y),
            "last_seen_wall_s": float(entry.last_seen_wall_s),
        }
        for entry in probe.active_entries()
    ]
    reach = float(probe._visibility_range_m)
    probe.close()
    return rows, reach


def coverage_metrics(
    seed_rows: list[dict], reach_m: float, samples: list[dict]
) -> dict:
    """C1 and C2 exactly as pre-registered, by the MAP'S OWN visibility rule.

    An entry is covered iff some sample of the path lies within the map's
    ``visibility_range_m`` of it — which is character for character what
    ``OnlineSemanticMap._was_expected_visible`` does, and this function calls
    that method rather than restating it, so the metric cannot drift from the
    rule the product uses.
    """

    from parcel_robot.online_map import OnlineSemanticMap
    from parcel_robot.online_map.entries import WriterProvenance

    ruler = OnlineSemanticMap(
        provenance=WriterProvenance(
            session_id="roam2-ruler",
            seat="in_loop_query",
            detector_name="owlv2-b16-int8",
            scene_id="city_block",
        ),
        visibility_range_m=reach_m,
    )
    path = [(float(s["x"]), float(s["y"])) for s in samples]

    class _E:
        __slots__ = ("surface_x", "surface_y")

        def __init__(self, x: float, y: float) -> None:
            self.surface_x = x
            self.surface_y = y

    total = len(seed_rows)
    covered: list[str] = []
    far: list[str] = []
    covered_far: list[str] = []
    start = path[0] if path else (0.0, 0.0)
    for row in seed_rows:
        entry = _E(row["surface_x"], row["surface_y"])
        seen = ruler._was_expected_visible(entry, path)  # the map's own rule
        visible_at_start = math.dist(start, (entry.surface_x, entry.surface_y)) <= reach_m
        if seen:
            covered.append(row["entry_id"])
        if not visible_at_start:
            far.append(row["entry_id"])
            if seen:
                covered_far.append(row["entry_id"])
    return {
        "visibility_range_m": reach_m,
        "entries_known_at_start": total,
        "covered": len(covered),
        # C1 — the headline. ``None`` (not 0.0) when there is no denominator:
        # a ratio out of nothing is not a zero.
        "c1": round(len(covered) / total, 6) if total else None,
        "entries_far_at_start": len(far),
        "covered_far": len(covered_far),
        "c2": round(len(covered_far) / len(far), 6) if far else None,
        "covered_ids": sorted(covered),
        "far_ids": sorted(far),
    }


def branch_label(reasons: dict[str, int], samples: list[dict]) -> dict:
    """FINISH-1's two modes, read off this run's own trace (PREREG §4).

    *escape* = the run reached the tether (``turn_tether`` appears) with few
    ``turn_hold`` samples; *boxed* = the budget went on blocked lanes near home
    (FINISH-1 measured ``turn_hold`` 61-98 boxed against 7-12 escape).
    """

    holds = int(reasons.get("turn_hold", 0))
    first_tether = None
    for sample in samples:
        if sample["roam_reason"] == "turn_tether":
            first_tether = float(sample["t_s"])
            break
    if first_tether is not None:
        label = "escape"
    elif holds >= 40:
        label = "boxed"
    else:
        label = "unclassified"
    return {
        "branch": label,
        "turn_hold_samples": holds,
        "first_turn_tether_s": first_tether,
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
    parser.add_argument("--socket-dir", default=str(Path.home() / ".cache" / "parcel-roam2"))
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--out", required=True)
    #: THE ONE LINE that separates the two arms.
    parser.add_argument(
        "--coverage", choices=("true", "false"), required=True,
        help="roam.coverage — arm B is 'true', the ROAM-1 baseline arm is 'false'",
    )
    #: The frozen seed map, copied fresh into this run. Absent = a warm-up
    #: run that BUILDS one; its coverage rows are then reported as null.
    parser.add_argument("--seed-map", default=None)
    #: ``null`` is unbounded (``DEFAULT_ROAM_TETHER_M`` is 10.0). Both MEASURED
    #: arms run at 10.0, ROAM-1's and FINISH-1's condition. The warm-up runs
    #: that BUILD the seed map run untethered on purpose: a seed map learned
    #: entirely within one tether radius is saturated at the first sample and
    #: measures nothing (see ``../PREREGISTRATION.md`` §2, deviation D1).
    parser.add_argument("--tether", default="10.0")
    #: Accumulate into an existing store instead of copying a frozen seed over
    #: it — how the second and third warm-up runs extend the first one's map,
    #: which is P1-B's ``reload_on_start`` doing exactly what it is for.
    parser.add_argument("--extend-store", default=None)
    args = parser.parse_args()

    from parcel_robot.patrol import ingress_queries
    from parcel_robot.web_panel import build_runtime

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = REPO / "src" / "parcel_robot" / "scenes" / f"{args.scene}.xml"
    if not scene.is_file():
        raise SystemExit(f"no such scene: {scene}")

    # ---- the run's own map store, always absolute, always in scratch --------
    store_path = (out_dir / "online_map.sqlite3").resolve()
    seed_rows: list[dict] = []
    reach = 8.0
    seed_sha = None
    if args.seed_map:
        seed = Path(args.seed_map).resolve()
        shutil.copyfile(seed, store_path)
        seed_sha = sha256_file(seed)
        seed_rows, reach = read_seed_entries(store_path)
    elif args.extend_store:
        shutil.copyfile(Path(args.extend_store).resolve(), store_path)
    os.environ["PARCEL_ONLINE_MAP_PATH"] = str(store_path)
    # LEDGERS REDIRECTED (COMMON brief). The runtime does not write
    # ``evals/nav_instruct/results/ledger.jsonl`` — that is the nav_instruct
    # eval harness's file — but the observability latency ledger IS a runtime
    # writer, so it is pointed into this run's own directory and the eval
    # ledger's sha256 is recorded before and after to PROVE the run left it
    # alone rather than asserting it.
    os.environ["PARCEL_LATENCY_LEDGER"] = str(out_dir / "latency_ledger.jsonl")

    batch = ingress_queries(8)
    log_dir = Path(args.log_dir or (Path(args.socket_dir) / "duplex-logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    config_path = out_dir / "roam.yaml"
    config_path.write_text(
        CONFIG.format(
            skills=REPO / "configs" / "skills",
            scene=scene,
            nav_config=REPO / "configs" / "navigation" / "prototype.yaml",
            queries=", ".join(batch),
            person_stop=args.person_stop,
            log_dir=log_dir,
            roam_budget=args.budget,
            coverage=args.coverage,
            tether=args.tether,
        ),
        encoding="utf-8",
    )

    from parcel_robot.memory_path import owner_store_paths

    owner_store = Path(owner_store_paths()[0])
    owner_before = sha256_file(owner_store) if owner_store.is_file() else None
    nav_ledger = REPO / "evals" / "nav_instruct" / "results" / "ledger.jsonl"
    nav_before = sha256_file(nav_ledger) if nav_ledger.is_file() else None

    socket_path = Path(args.socket_dir) / f"r2-{os.getpid()}.sock"
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    wall_started = time.time()
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
            time.sleep(2.0)
            envelope = runtime.spatial.config.owner_collision_envelope_m
            map_at_start = len(getattr(runtime, "_p1b_learned_map", None) or ())

            asked_at = time.monotonic()
            outcome = runtime.submit_realtime_transcript("Go explore.")
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
                cov = roam.get("coverage") or {}
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
                        # ROAM-2's own columns, straight off the product's
                        # snapshot — never recomputed here.
                        "coverage_enabled": bool(cov.get("enabled")),
                        "coverage_legs": int(cov.get("legs") or 0),
                        "coverage_target": cov.get("target"),
                        "coverage_age_s": cov.get("age_s"),
                        "coverage_candidates": int(cov.get("candidates") or 0),
                    }
                )
                time.sleep(period)

            final_roam = runtime.roam_snapshot()
            learned = getattr(runtime, "_p1b_learned_map", None)
            report = {
                "ingress": outcome.as_dict(),
                "first_tick_latency_s": (
                    round(first_tick_at - asked_at, 4) if first_tick_at else None
                ),
                "roam_final": final_roam,
                "roam_active_at_end": bool(final_roam.get("active")),
                "coverage_legs_final": int(
                    (final_roam.get("coverage") or {}).get("legs") or 0
                ),
                "coverage_enabled_final": bool(
                    (final_roam.get("coverage") or {}).get("enabled")
                ),
                "map_entries_at_start": map_at_start,
                "map_entries_at_end": len(learned) if learned is not None else None,
                "semantic_source": (
                    runtime.learned_map_snapshot().get("semantic_source")
                    if hasattr(runtime, "learned_map_snapshot")
                    else None
                ),
            }
        finally:
            runtime.close()
    finally:
        returncode = stop_simulator(process, handle, socket_path)
    wall_s = time.time() - wall_started

    owner_after = sha256_file(owner_store) if owner_store.is_file() else None
    nav_after = sha256_file(nav_ledger) if nav_ledger.is_file() else None

    path_length = 0.0
    for before, after in pairwise(samples):
        path_length += math.hypot(after["x"] - before["x"], after["y"] - before["y"])
    clearances = [s["person_clearance_m"] for s in samples if s["person_clearance_m"] is not None]
    reasons: dict[str, int] = {}
    for sample in samples:
        reasons[sample["roam_reason"]] = reasons.get(sample["roam_reason"], 0) + 1

    bounds = in_block_metrics(samples, float(args.block_half_extent))
    cov = (
        coverage_metrics(seed_rows, reach, samples)
        if seed_rows
        else {"entries_known_at_start": 0, "c1": None, "c2": None}
    )

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "arm": "coverage" if args.coverage == "true" else "baseline",
        "roam_coverage_config": args.coverage,
        "roam_tether_config": args.tether,
        "wall_clock_s": round(wall_s, 1),
        "budget_s": args.budget,
        "person_stop_m": args.person_stop,
        "scene": str(scene),
        "navigation_config": str(REPO / "configs" / "navigation" / "prototype.yaml"),
        "online_map_store": str(store_path),
        "seed_map_sha256": seed_sha,
        "repo_head": subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        ).stdout.strip(),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "simulator_returncode": returncode,
        "samples": len(samples),
        "path_length_m": round(path_length, 6),
        "in_bounds": bounds["in_bounds"],
        "net_displacement_in_block_m": bounds["net_displacement_in_block_m"],
        "bounds": bounds,
        "collision_ticks": sum(1 for s in samples if s["collision"]),
        "roam_active_samples": sum(1 for s in samples if s["roam_active"]),
        "min_person_clearance_m": round(min(clearances), 6) if clearances else None,
        "reasons": dict(sorted(reasons.items())),
        "branch": branch_label(reasons, samples),
        "coverage": cov,
        "owner_store": {
            "path": str(owner_store),
            "exists": owner_store.is_file(),
            "unchanged": bool(owner_store.is_file()) and owner_before == owner_after,
        },
        "nav_instruct_ledger": {
            "path": str(nav_ledger),
            "exists": nav_ledger.is_file(),
            "unchanged": nav_before == nav_after,
        },
        **report,
        "trace": samples,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    headline = {k: payload[k] for k in (
        "arm", "roam_coverage_config", "roam_tether_config",
        "wall_clock_s", "coverage", "branch",
        "path_length_m", "net_displacement_in_block_m", "in_bounds",
        "collision_ticks", "min_person_clearance_m", "roam_active_samples",
        "coverage_legs_final", "coverage_enabled_final", "roam_active_at_end",
        "map_entries_at_start", "map_entries_at_end", "reasons", "owner_store",
        "nav_instruct_ledger",
    )}
    print(json.dumps(headline, indent=2))
    print(f"\nwrote {out_dir}/summary.json")


if __name__ == "__main__":
    main()
