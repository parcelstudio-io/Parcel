from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.companion.run_embodied_plan_v1 import (
    MANIFEST_PATH,
    EmbodiedPlanError,
    _HeadlessRuntimeBridge,
    _physical_report,
    _pose,
    _safety_checks,
    load_frozen_suite,
    run_suite,
    write_report,
)
from parcel_robot.headless_city import HeadlessCityQualityHarness, HeadlessCityWorld


@pytest.fixture(scope="module")
def report() -> dict[str, object]:
    return run_suite(
        run_id="embodied-plan-v1-test",
        recorded_at_utc="2026-08-03T17:00:00Z",
        change_description="Deterministic focused test",
    )


def _case(report: dict[str, object], case_id: str) -> dict[str, object]:
    return next(item for item in report["cases"] if item["case_id"] == case_id)


@pytest.mark.slow  # card P0-E: frozen-digest integrity is a nightly evidence ratchet
def test_manifest_hash_locks_every_physical_input_and_unique_seed() -> None:
    manifest, cases, accepted = load_frozen_suite()

    assert manifest["frozen"] is True
    assert manifest["base_motion"] == "deterministic_kinematic_mujoco_geometry"
    assert manifest["evaluator_truth_available_to_policy"] is False
    assert set(manifest["locked_inputs"]) == {
        "episodes",
        "planner_cases",
        "accepted_plans",
        "city_scene",
        "robot_config",
        "result_schema",
    }
    assert [case["case_id"] for case in cases] == list(accepted)
    assert len({case["seed"] for case in cases}) == 5


def test_manifest_rejects_changed_locked_digest(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["locked_inputs"]["episodes"]["sha256"] = "0" * 64
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EmbodiedPlanError, match="episodes failed SHA-256"):
        load_frozen_suite(changed)


def test_full_gate_executes_physics_and_separates_unsupported(report) -> None:
    aggregate = report["aggregate"]

    assert aggregate == {
        "case_count": 5,
        "passed_case_count": 4,
        "failed_case_count": 0,
        "unsupported_case_count": 1,
        "supported_case_count": 4,
        "supported_case_success_rate": 1.0,
        "physical_skill_episode_count": 6,
        # Baseline re-frozen 2026-08-04 after the movement-speed raise
        # (cruise_vx 0.60->0.85, max_vx 0.6->1.0): success, collisions, and
        # minimum clearance are unchanged; missions simply finish faster.
        # (Prior 2026-08-03 re-freeze: stub_v0 -> grid_v1, 1137 -> 1303.)
        #
        # Re-frozen 2026-08-06: 1146 -> 1072. Measured 2x2 attribution (HEAD
        # 4f6342d vs working tree) x (HEAD navigation config vs current):
        #   HEAD code + HEAD cfg     1146   (the 2026-08-04 row)
        #   HEAD code + current cfg  1111
        #   tree code + HEAD cfg     1107
        #   tree code + current cfg  1072
        # -35 configs/navigation/default.yaml safety.max_vx 0.45 -> 0.9 (the
        #     2026-08-05 speed-authority completion; reverting only this knob
        #     restores 1107/1072 -> 1146/1111, and reverting predictive_mode,
        #     person_slow_m, align_enter_deg, or the watchdog window each moves
        #     this suite by exactly 0 steps).
        # -37 K0 shared-GoalRegion arrival trigger in navigation/pipeline.py
        #     (`_inside_arrival_goal_region`): a mission may now terminate on
        #     GoalRegion membership, not only on the geometric approach-pose
        #     tolerance, so the two lamppost `near` cases stop ~1 step-band
        #     earlier (disabling only that trigger returns the total to 1109).
        #  -2 residual working-tree navigation changes, unattributed.
        # Success, collision, timeout, and minimum-clearance rows are all
        # bit-identical across the four cells: this is pacing, not capability.
        # Re-frozen 2026-08-07: 1072 -> 1250 (+178 across the two region-goal
        # legs' bounded look-arounds; NOT "one full sweep" — max_steps is 80,
        # the look-around is 160 deg/8 s, and the residual comes from the
        # extra approach distance to the boundary-nearest instance; the
        # original derivation claim was wrong and is corrected here).
        # Region-instance selection arbitration: an
        # interchangeable (stuff-class) goal with only ONE instance visible
        # completes the look-around before committing, so "the sidewalk"
        # resolves to the boundary-nearest instance (north, 2.2 m) instead of
        # whichever entered the frustum first (south, scan-direction-
        # dependent). This is what turned sidewalk_then_lamppost from FAILED
        # (lamppost unreachable across the road from the south sidewalk) to
        # PASSED. Collision, timeout, and clearance rows bit-identical:
        # pacing + correct instance choice, not capability loss.
        # Re-frozen 2026-08-09 (Wave-2): 1250 -> 1219 (-31). Measured 2x2
        # attribution ((Wave-1 nav code b75ed05 vs be20471) x (gesture library
        # + config)): reverting ONLY approach.py + pipeline.py + instructnav to
        # the b75ed05 freeze point, with the embodied gesture library
        # (configs/skills/*) and every config at HEAD, restores 1250 total /
        # 153 correction / 362 sidewalk_then_lamppost and min_clearance
        # 0.883147 bit-for-bit. So the gesture library moves this suite by
        # exactly 0 (its five cases invoke no gesture/pose/emote skill),
        # configs/navigation + authority.py are unchanged in be20471, and the
        # whole movement is card near-band-inset:
        #  -29 correct_active_task_to_lamppost (153->124): the lamppost `near`
        #      approach pose insets from the band OUTER edge (stand_off_m
        #      metadata 1.32 = vicinity - arrival_radius) to the band centre
        #      1.28 m via approach.py::_near_planning_band, so the terminal
        #      approach stops ~4 cm sooner. A FASTER, now-verifying arrival, not
        #      a regression: still passed, near_surface_le_1m + off_road True,
        #      collision 0, plan_revision 2, checkpoint semantics identical.
        #  -2 sidewalk_then_lamppost (362->360): same inset on the compound's
        #      lamppost leg; passed before and after.
        # search-reground (near_arrival.py fallback) moves 0 here: it fires only
        # when safe_approach_pose returns None, and both lamppost cases commit a
        # valid approach pose (fallback dormant). Success/collision/timeout/
        # min-clearance rows bit-identical across cells: arrival inset, not
        # capability loss.
        # Re-frozen 2026-08-09 (Wave-2, card seamless-pacing): 1219 -> 997
        # (-222). Measured seam-by-seam by toggling the two new pacing constants
        # off (GridNavigator.TERMINAL_APPROACH_FLOOR_MPS=0,
        # DirectiveNavigator.SCAN_CREEP_MPS=0):
        #   seam 3 alone (region "inside" convergence) 1219 -> 1190 (-29):
        #     sidewalk_then_hold -23, sidewalk_then_lamppost -6 (its sidewalk
        #     leg); the lamppost `near` case is untouched (relation "near", not
        #     "inside"). The region goals now declare arrival the instant the
        #     robot stands inside the committed polygon with the SAME terminal
        #     clearance the verification requires, instead of spinning `align_goal`
        #     in place to the step limit.
        #   seam 2 terminal creep floor (+ seam 1 scan creep) 1190 -> 997 (-193):
        #     sidewalk_then_hold -59, sidewalk_then_lamppost -94,
        #     correct_active_task_to_lamppost -40 (153->124->84 total). The last
        #     ~0.5 m no longer crawls at ~0.032 m/s; it holds >=0.12 m/s until the
        #     arrival radius where the point-goal fallback owns the stop.
        # ALL five cases still pass; collision 0, timeout 0, and min-clearance
        # 0.883147 are bit-identical (that min is five_steps_away_then_hold, which
        # moves 0). Faster arrivals that still verify, not weakened capability.
        "simulator_step_count": 997,
        "collision_count": 0,
        "timeout_count": 0,
        "minimum_clearance_m": pytest.approx(0.883147),
        "simulator_steps_per_case": {
            "count": 5,
            "minimum": 64.0,
            # Median 282 -> 200 and mean 243.8 -> 199.4: the two region legs and
            # the lamppost `near` case all sped up (seams 2/3); min (64,
            # five_steps) and max (389, orbit unsupported) cases move 0.
            "median": 200.0,
            "mean": 199.4,
            "maximum": 389.0,
        },
    }
    for case in report["cases"]:
        physical = case["physical"]
        assert physical["simulator_step_count"] > 0
        assert physical["collision_count"] == 0
        assert physical["timeout_count"] == 0
        assert physical["minimum_clearance_m"] >= 0.65
        assert physical["terminal_stopped"] is True
        assert physical["evaluator_truth_available_to_policy"] is False
        assert physical["policy_observation_contract"] == [
            "camera",
            "lidar",
            "owner_track",
            "odometry",
        ]


def test_sidewalk_and_lamppost_use_evaluator_truth_after_execution(report) -> None:
    sidewalk = _case(report, "sidewalk_then_hold")
    compound = _case(report, "sidewalk_then_lamppost")

    assert sidewalk["status"] == "passed"
    assert sidewalk["semantic"]["checks"]["inside"] is True
    assert sidewalk["semantic"]["checks"]["off_road"] is True
    assert compound["status"] == "passed"
    assert compound["semantic"]["checks"]["sidewalk_inside"] is True
    assert compound["semantic"]["checks"]["lamppost_near_surface_le_1m"] is True
    assert compound["semantic"]["checks"]["lamppost_off_road"] is True
    lamp = compound["semantic"]["metrics"]["lamppost"]
    assert 0.0 <= lamp["surface_distance_m"] <= 1.0
    assert lamp["support_region_id"] == "sidewalk"


def test_five_steps_scores_owner_relative_distance_not_plan_text(report) -> None:
    case = _case(report, "five_steps_away_then_hold")
    metrics = case["semantic"]["metrics"]

    assert case["status"] == "passed"
    assert case["executive"]["final_task"]["state"] == "succeeded"
    assert case["semantic"]["checks"]["five_step_distance"] is True
    assert metrics["target_distance_m"] == pytest.approx(1.25)
    assert metrics["projected_away_distance_m"] == pytest.approx(1.21935)
    assert metrics["owner_distance_after_m"] > metrics["owner_distance_before_m"]


def test_orbit_prefix_is_scored_but_follow_is_never_laundered(report) -> None:
    case = _case(report, "orbit_then_follow_behind")
    checks = case["semantic"]["checks"]

    assert case["status"] == "unsupported"
    assert case["semantic"]["passed"] is None
    assert checks["controller_completed"] is True
    assert checks["clockwise_winding"] is True
    assert checks["full_angular_coverage"] is True
    assert checks["radial_corridor"] is True
    assert checks["endpoint_closed"] is True
    assert checks["follow_behind_supported"] is False
    assert case["support"]["unsupported_skills"][0]["skill"] == "FollowFormation"
    assert case["executive"]["final_task"]["state"] == "failed"
    assert case["physical"]["executions"][-1]["supported"] is False
    assert case["physical"]["executions"][-1]["simulator_step_count"] == 0


def test_correction_waits_for_checkpoint_then_executes_replacement(report) -> None:
    case = _case(report, "correct_active_task_to_lamppost")
    checkpoint = case["executive"]["checkpoint_correction"]

    assert case["status"] == "passed"
    assert checkpoint == {
        "replacement_deferred": True,
        "replacement_activated_at_checkpoint": True,
        "stale_incumbent_dispatch_reconciled": True,
        "incumbent_simulator_steps": 0,
    }
    assert case["executive"]["final_task"]["plan_revision"] == 2
    # Re-frozen with the grid_v1 default navigator (was 194 under stub_v0).
    # 236 -> 186 with the 2026-08-04 speed raise (same route, faster cruise).
    # 186 -> 153 (2026-08-06): -5 from safety.max_vx 0.45 -> 0.9 and -28 from
    # the K0 shared-GoalRegion arrival trigger (this case terminates at the
    # lamppost `near` band instead of the geometric approach pose). Same
    # route, same checkpoint semantics, same clearance — see the aggregate
    # row above for the measured 2x2 attribution.
    # 153 -> 124 (2026-08-09, Wave-2): card near-band-inset insets the lamppost
    # `near` approach pose from the band outer edge (1.32 m) to the band centre
    # (1.28 m), so the terminal approach stops ~4 cm sooner. Faster, still-
    # verifying arrival, not a regression: still passed, near_surface_le_1m +
    # off_road True, collision 0, plan_revision 2, checkpoint semantics
    # identical. Attribution measured in the aggregate row above — the gesture
    # library and every config move this case by exactly 0 steps.
    # 124 -> 84 (2026-08-09, Wave-2, card seamless-pacing seam 2): the terminal
    # creep floor stops the final ~0.5 m of the lamppost `near` approach crawling
    # at ~0.032 m/s (now >=0.12 m/s until the arrival radius). Same route, same
    # checkpoint semantics, same clearance; still near_surface_le_1m + off_road
    # True. Seam 3 (region convergence) moves this "near" case by 0.
    assert case["physical"]["simulator_step_count"] == 84
    assert case["semantic"]["checks"]["near_surface_le_1m"] is True
    assert case["semantic"]["checks"]["off_road"] is True


def test_timeout_is_counted_without_cleanup_laundering() -> None:
    world = HeadlessCityWorld()
    world.reset(robot=(0.0, -1.0, -1.5707963267948966), owner=(2.0, -0.5))
    bridge = _HeadlessRuntimeBridge(
        HeadlessCityQualityHarness(world),
        max_steps_per_skill=1,
    )
    initial = _pose(world.observe())

    bridge.navigate("sidewalk")
    physical = _physical_report(bridge, initial)

    assert physical["simulator_step_count"] == 1
    assert physical["timeout_count"] == 1
    assert physical["executions"][0]["controller_status"] == "timed_out"
    assert physical["executions"][0]["terminal_stopped"] is False
    assert _safety_checks(bridge)["no_timeout"] is False


def test_seeded_case_replay_is_bitwise_stable_for_physical_outputs(report) -> None:
    replay = run_suite(
        case_ids=("five_steps_away_then_hold",),
        run_id="embodied-plan-v1-away-replay",
        recorded_at_utc="2026-08-03T17:01:00Z",
        change_description="Determinism replay",
    )
    original = _case(report, "five_steps_away_then_hold")
    repeated = replay["cases"][0]

    assert repeated["seed"] == original["seed"] == 41003
    assert repeated["physical"] == original["physical"]
    assert repeated["semantic"] == original["semantic"]
    assert repeated["plan"] == original["plan"]


def test_result_writer_is_immutable(tmp_path: Path, report) -> None:
    target = tmp_path / "result.json"
    write_report(report, target)

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_report(report, target)
