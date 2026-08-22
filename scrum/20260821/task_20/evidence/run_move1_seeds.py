"""MOVE-1 seeds — prove each test can fail before trusting that it passes.

One mutation per behavioural claim, applied to the real source, with the test
suite run against it. A seed that stays GREEN is a test that asserts nothing,
and is reported as a failure of the test, not waved through.

Discipline, per the house rules:
* ``__pycache__`` purged on every restore, so no seed can be judged against a
  stale bytecode cache;
* the tree is restored from an in-memory copy taken before the first mutation
  and hash-verified after every restore;
* a fresh-interpreter canary after the last restore;
* a final sweep that postdates the last source write.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
MISSION = REPO / "src" / "parcel_robot" / "patrol" / "mission.py"
TESTS = REPO / "tests" / "test_move1_patrol.py"
PYTHON = REPO / ".parcel" / "bin" / "python"

# (id, claim, target file, old, new, tests that MUST go red)
SEEDS: list[tuple[str, str, Path, str, str, list[str]]] = [
    (
        "S01",
        "the person standoff makes the patrol turn instead of pushing",
        MISSION,
        ("        if self._person_blocks(sense, limits.min_person_clearance_m):\n"
        "            return self._turn(sense, \"turn_person\")\n"),
        "",
        [
            "test_turns_instead_of_pushing_into_a_person",
            "test_c1_geometry_turns_instead_of_pushing",
            "test_person_priority_beats_geometry",
        ],
    ),
    (
        "S02",
        "a short lane makes the patrol turn",
        MISSION,
        ("        forward = sense.forward_clearance_m\n"
        "        if forward is not None and forward < limits.min_forward_clearance_m:\n"
        "            return self._turn(sense, \"turn_blocked\")\n"),
        "        forward = sense.forward_clearance_m\n",
        ["test_turns_when_the_lane_ahead_is_short"],
    ),
    (
        "S03",
        "a turn does not translate",
        MISSION,
        "        return PatrolCommand(vyaw=limits.turn_vyaw * sign, reason=reason)",
        ("        return PatrolCommand(\n"
        "            vx=limits.cruise_vx,\n"
        "            vyaw=limits.turn_vyaw * self._turn_sign,\n"
        "            reason=reason,\n"
        "        )"),
        [
            "test_turns_instead_of_pushing_into_a_person",
            "test_turns_when_the_lane_ahead_is_short",
            "test_c1_geometry_turns_instead_of_pushing",
        ],
    ),
    (
        "S04",
        "hysteresis holds the turn through the release margin",
        MISSION,
        "            release = limits.min_forward_clearance_m + limits.clearance_release_margin_m",
        "            release = limits.min_forward_clearance_m",
        ["test_hysteresis_holds_the_turn_until_the_release_margin"],
    ),
    (
        "S05",
        "a fruitless turn flips direction",
        MISSION,
        ("        if turning_for >= limits.turn_flip_after_s:\n"
        "            self._turn_sign = -self._turn_sign\n"
        "            self._turning_since = sense.elapsed_s\n"),
        "",
        ["test_turn_direction_flips_when_a_turn_finds_no_lane"],
    ),
    (
        "S06",
        "a boxed-in patrol gives up instead of spinning out the budget",
        MISSION,
        "        if turning_for >= limits.turn_giveup_after_s:",
        "        if False:",
        [
            "test_boxed_in_gives_up_rather_than_spinning_out_the_budget",
            "test_runner_ends_early_when_boxed_in",
        ],
    ),
    (
        "S07",
        "the budget outranks a clear lane",
        MISSION,
        "        if sense.elapsed_s >= limits.budget_s:",
        "        if False:",
        ["test_budget_exhausted_stops_and_outranks_a_clear_lane"],
    ),
    (
        "S08",
        "contact outranks everything below the budget",
        MISSION,
        "        if sense.collision:\n            return self._turn(sense, \"turn_contact\")\n",
        "",
        ["test_contact_beats_everything_below_budget"],
    ),
    (
        "S09",
        "forward clearance only reads rays inside the body-forward cone",
        MISSION,
        "        if abs(angle) >= half_angle_rad:\n            continue\n",
        "",
        ["test_forward_clearance_takes_the_shortest_ray_inside_the_cone_only"],
    ),
    (
        "S10",
        "NaN rays are dropouts, not zero-distance obstacles",
        MISSION,
        "        if math.isnan(distance) or not math.isfinite(distance):\n            continue\n",
        "        if math.isnan(distance):\n            distance = 0.0\n",
        [
            "test_forward_clearance_ignores_nan_rays_and_returns_none_when_all_invalid"
        ],
    ),
    (
        "S11",
        "range_max means no return, not an obstacle at range_max",
        MISSION,
        "        if range_max_m is not None and distance >= range_max_m:\n            continue\n",
        "",
        [
            "test_forward_clearance_treats_range_max_as_no_return",
            "test_forward_clearance_takes_the_shortest_ray_inside_the_cone_only",
        ],
    ),
    (
        "S12",
        "the owner carries a collision envelope on top of the person standoff",
        MISSION,
        "                        max(0.0, owner_distance - owner_envelope_m),",
        "                        owner_distance,",
        ["test_c1_geometry_turns_instead_of_pushing"],
    ),
    (
        "S13",
        "an absent pose is not a pose at the origin",
        MISSION,
        ("    robot = snapshot.get(\"robot\")\n"
        "    if not isinstance(robot, Mapping):\n"
        "        return None\n"),
        ("    robot = snapshot.get(\"robot\")\n"
        "    if not isinstance(robot, Mapping):\n"
        "        robot = {\"x\": 0.0, \"y\": 0.0}\n"),
        ["test_sense_from_snapshot_without_a_pose_is_none_not_the_origin"],
    ),
    (
        "S14",
        "the runner never drives on a tick with no pose",
        MISSION,
        ("            if sense is None:\n"
        "                # No pose this tick. Do not drive blind, do not end the\n"
        "                # mission on one gap; skip and let the budget run.\n"
        "                report.reasons[\"no_sense\"] = report.reasons.get(\"no_sense\", 0) + 1\n"
        "                self._sleep(self._tick_s)\n"
        "                continue\n"),
        ("            if sense is None:\n"
        "                report.reasons[\"no_sense\"] = report.reasons.get(\"no_sense\", 0) + 1\n"
        "                sense = PatrolSense(elapsed_s=elapsed, x=0.0, y=0.0, yaw=0.0)\n"),
        ["test_runner_skips_ticks_without_a_pose_and_never_drives_blind"],
    ),
    (
        "S15",
        "refused submissions are counted",
        MISSION,
        "            if not self._submit(command):\n                report.refused += 1\n",
        "            self._submit(command)\n",
        ["test_runner_counts_refused_submissions_without_ending_the_mission"],
    ),
    (
        "S16",
        "the T1 sweep vocabulary carries no volatile class",
        MISSION,
        "    \"building\",",
        "    \"building\",\n    \"person\",",
        ["test_sweep_vocabulary_carries_no_volatile_class"],
    ),
    (
        "S17",
        "the map-growth record is stamped with the tick it belongs to",
        MISSION,
        ("                report.map_growth.append(\n"
        "                    replace(self._map_probe(), t_s=sense.elapsed_s)\n"
        "                )"),
        "                report.map_growth.append(self._map_probe())",
        ["test_runner_records_path_map_growth_and_stops_on_budget"],
    ),
    (
        "S18",
        "the ingress batch always takes the person safety lease",
        MISSION,
        "    return (SAFETY_LEASE_QUERY, *sweep)",
        "    return tuple(sweep)",
        [
            "test_ingress_batch_always_takes_the_person_safety_lease",
            "test_ingress_batch_is_accepted_by_the_real_camera_stream_config",
        ],
    ),
    (
        "S19",
        "the lease query never leaks into the map sweep vocabulary",
        MISSION,
        "DEFAULT_MAP_SWEEP_VOCABULARY: tuple[str, ...] = (\n    \"building\",",
        "DEFAULT_MAP_SWEEP_VOCABULARY: tuple[str, ...] = (\n    \"person\",\n    \"building\",",
        [
            "test_ingress_batch_is_the_query_set_not_the_map_set",
            "test_sweep_vocabulary_carries_no_volatile_class",
        ],
    ),
    (
        "S20",
        "the person standoff asks about DIRECTION, not distance alone",
        MISSION,
        "        return abs(wrapped) < FORWARD_HALF_ANGLE_RAD",
        "        return True",
        [
            "test_person_behind_does_not_block_the_lane_ahead",
            "test_turn_hold_releases_once_the_heading_is_off_the_person",
            "test_sense_from_snapshot_reports_owner_bearing_in_the_body_frame",
        ],
    ),
    (
        "S21",
        "an unknown person bearing fails closed",
        MISSION,
        "        if bearing is None:\n            return True  # unknown bearing fails closed",
        "        if bearing is None:\n            return False",
        ["test_unknown_person_bearing_fails_closed"],
    ),
    (
        "S22",
        "the turn goes away from the person",
        MISSION,
        "                sign = -1 if bearing > 0.0 else 1",
        "                sign = 1 if bearing > 0.0 else -1",
        [
            "test_turn_goes_away_from_the_person_not_whichever_way_the_counter_points"
        ],
    ),
    (
        "S23",
        "the owner bearing is reported in the body frame, not the world frame",
        MISSION,
        "                        math.atan2(owner_dy, owner_dx) - yaw,",
        "                        math.atan2(owner_dy, owner_dx),",
        ["test_sense_from_snapshot_reports_owner_bearing_in_the_body_frame"],
    ),
    (
        "S24",
        "the snapshot heading is degrees and is converted before use",
        MISSION,
        '        yaw = math.radians(float(robot.get("heading", 0.0)))',
        '        yaw = float(robot.get("heading", 0.0))',
        [
            "test_snapshot_heading_is_read_as_degrees_not_radians",
            "test_sense_from_snapshot_reports_owner_bearing_in_the_body_frame",
        ],
    ),
]


def purge_pycache() -> None:
    for target in (REPO / "src", REPO / "tests"):
        for cache in target.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tests(node_ids: list[str]) -> tuple[int, str]:
    # Targeted by design. The FULL final sweep postdating the last source write
    # is the card's exit ``scripts/ci_gate.py`` run, which is recorded in
    # MOVE1_STATUS.md; running the whole suite here as well (twice, including
    # the nightly `slow` tier) bought nothing but wall clock.
    argv = [str(PYTHON), "-m", "pytest", "-q", "-p", "no:randomly"]
    argv += [f"{TESTS}::{name}" for name in node_ids] or [str(TESTS)]
    proc = subprocess.run(
        argv, cwd=str(REPO), capture_output=True, text=True, check=False
    )
    return proc.returncode, (proc.stdout + proc.stderr)[-600:]


def main() -> None:
    originals = {MISSION: MISSION.read_text(encoding="utf-8")}
    baseline = {path: sha256(path) for path in originals}

    purge_pycache()
    code, output = run_tests([])
    results: list[dict] = []
    green_baseline = {"returncode": code, "tail": output.strip().splitlines()[-1:]}

    for seed_id, claim, path, old, new, node_ids in SEEDS:
        source = originals[path]
        if old not in source:
            results.append(
                {
                    "seed": seed_id,
                    "claim": claim,
                    "verdict": "SEED_BROKEN",
                    "detail": "anchor text not found in source",
                }
            )
            continue
        if source.count(old) != 1:
            results.append(
                {
                    "seed": seed_id,
                    "claim": claim,
                    "verdict": "SEED_BROKEN",
                    "detail": f"anchor matched {source.count(old)} times, need exactly 1",
                }
            )
            continue
        try:
            path.write_text(source.replace(old, new, 1), encoding="utf-8")
            purge_pycache()
            code, output = run_tests(node_ids)
        finally:
            path.write_text(source, encoding="utf-8")
            purge_pycache()
        assert sha256(path) == baseline[path], f"{seed_id} failed to restore {path}"
        results.append(
            {
                "seed": seed_id,
                "claim": claim,
                "tests": node_ids,
                "verdict": "RED" if code != 0 else "GREEN — TEST ASSERTS NOTHING",
                "returncode": code,
                "tail": output.strip().splitlines()[-1:],
            }
        )

    # Fresh-interpreter canary: a brand-new process, no warm imports, after the
    # last restore. If a seed leaked, this is where it shows.
    purge_pycache()
    canary = subprocess.run(  # noqa: PLW1510 - returncode is the datum
        [
            str(PYTHON),
            "-c",
            ("import sys; sys.path.insert(0, 'src');"
            " from parcel_robot.patrol import PatrolPolicy, PatrolSense;"
            " c = PatrolPolicy().step(PatrolSense(elapsed_s=0.0, x=0.0, y=0.0, yaw=0.0,"
            " person_clearance_m=1.2));"
            " print(c.reason, c.vx)"),
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    final_code, final_output = run_tests([])

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "repo_head": subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "baseline_green": green_baseline,
        "seeds": results,
        "red_count": sum(1 for row in results if row.get("verdict") == "RED"),
        "seed_count": len(SEEDS),
        "restored_hashes_match": all(
            sha256(path) == digest for path, digest in baseline.items()
        ),
        "fresh_interpreter_canary": {
            "returncode": canary.returncode,
            "stdout": canary.stdout.strip(),
            "expected": "turn_person 0.0",
            "ok": canary.stdout.strip() == "turn_person 0.0",
        },
        "final_sweep": {
            "returncode": final_code,
            "tail": final_output.strip().splitlines()[-1:],
        },
    }
    out = Path(__file__).parent / "MOVE1_SEEDS.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "seeds"}, indent=2))
    for row in results:
        print(f"  {row['seed']}  {row['verdict']:<32}  {row['claim']}")
    print(f"\nwrote {out}")
    if summary["red_count"] != summary["seed_count"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
