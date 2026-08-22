"""NM-1 seeded RED — mutate the PRODUCT on a byte-identical scratch copy of the
repo, watch the named test go red, restore by sha256, purge __pycache__.

The scratch copy is the point: five other wave-2 cards are running tests in the
real tree right now, and a seed that reddens their run is a seed that has
damaged somebody else's evidence.
"""
from __future__ import annotations

import hashlib
import pathlib
import shutil
import subprocess
import sys

SEED_REPO = pathlib.Path("/home/jaewoo-jang/.cache/parcel-nm1/seedrepo")
PY_ = "/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python"
T = "tests/test_nm1_promotion_and_asks.py"

SEEDS: list[tuple[str, str, str, str, str]] = [
    (
        "promotion without the judge's agreement",
        "src/parcel_robot/online_map/naming.py",
        "        if judge is not None and proposed.admissible:",
        "        if False and judge is not None and proposed.admissible:",
        (
            f"{T}::test_a_k_agreed_name_the_judge_rejects_never_reaches_known_places "
            f"{T}::test_the_judge_is_asked_about_standing_names_not_only_new_promotions"
        ),
    ),
    (
        "the judge floor lowered so everything passes",
        "src/parcel_robot/vlm_veto/judge.py",
        "JUDGE_MIN_SCORE: float = 0.10",
        "JUDGE_MIN_SCORE: float = 0.0",
        f"{T}::test_the_floor_is_the_detectors_own_shipped_threshold",
    ),
    (
        "an UNAVAILABLE judge is read as agreement",
        "src/parcel_robot/online_map/naming.py",
        "            else:\n                report.judge_unavailable += 1",
        "            elif False:\n                report.judge_unavailable += 1",
        (
            f"{T}::test_an_unavailable_judge_holds_a_new_promotion_and_never_demotes_an_old_one "
            f"{T}::test_a_judge_that_raises_holds_it_never_promotes"
        ),
    ),
    (
        "a rejected name is left promoted instead of held",
        "src/parcel_robot/online_map/naming.py",
        "            if held:\n                report.judge_held += 1\n                promoted = False",
        "            if held:\n                report.judge_held += 1",
        f"{T}::test_a_k_agreed_name_the_judge_rejects_never_reaches_known_places",
    ),
    (
        "the hold takes a supporting visit away (a demotion, not a hold)",
        "src/parcel_robot/online_map/naming.py",
        "                visits=len(name.supporting_visit_ids),\n                supporting_visit_ids=name.supporting_visit_ids,",
        "                visits=len(name.supporting_visit_ids[:-1]),\n                supporting_visit_ids=name.supporting_visit_ids[:-1],",
        f"{T}::test_a_held_name_keeps_every_visit_it_earned",
    ),
    (
        "the control loop no longer marks its thread",
        "src/parcel_robot/runtime.py",
        "        mark_control_thread()\n        try:",
        "        try:",
        f"{T}::test_the_control_loop_marks_its_own_thread",
    ),
    (
        "the control loop leaves its thread marked on exit",
        "src/parcel_robot/runtime.py",
        "            clear_control_thread()",
        "            pass  # seeded: the loop exits still marked",
        (
            f"{T}::test_the_control_loop_unmarks_itself_so_the_id_is_not_inherited "
            f"{T}::test_a_control_loop_that_raises_still_unmarks_its_thread"
        ),
    ),
    (
        "a VLM call is added to the 10 Hz loop's call graph",
        "src/parcel_robot/runtime.py",
        "            dispatch_started = time.monotonic()\n            self._dispatch_active()",
        "            dispatch_started = time.monotonic()\n            self._nm1_seat.veto_for(\"bench\", None)\n            self._dispatch_active()",
        f"{T}::test_FATAL_no_model_call_is_reachable_from_the_10_hz_control_loop",
    ),
    (
        "a model load is added one hop DEEPER than the loop itself",
        "src/parcel_robot/runtime.py",
        "        self._narrate_expired_activities()\n        now = time.monotonic()",
        "        self._narrate_expired_activities()\n        self._nm1_seat.load()\n        now = time.monotonic()",
        f"{T}::test_FATAL_no_model_call_is_reachable_from_the_10_hz_control_loop",
    ),
    (
        "the judge may run on the control thread",
        "src/parcel_robot/vlm_veto/judge.py",
        "        if in_control_thread():\n            raise ControlLoopViolation(",
        "        if False and in_control_thread():\n            raise ControlLoopViolation(",
        f"{T}::test_the_naming_judge_refuses_the_control_thread_too",
    ),
    (
        "a control-loop violation is softened into a hold",
        "src/parcel_robot/online_map/naming.py",
        "    except ControlLoopViolation:",
        "    except _NeverRaised:",
        f"{T}::test_a_judge_violation_is_never_softened_into_a_hold",
    ),
    (
        "the gate goes back to synchronous inference",
        "src/parcel_robot/perception_abstention.py",
        "        from parcel_robot.vlm_veto.bureau import bureau_for\n\n        runner = bureau_for(key).veto_callable()",
        "        from parcel_robot.vlm_veto.runner import runner_for\n\n        runner = runner_for(key).veto_callable()",
        f"{T}::test_the_gate_reads_the_bureau_and_not_the_runner",
    ),
    (
        "a stale verdict is consumed",
        "src/parcel_robot/vlm_veto/bureau.py",
        "            if not published.fresh(now):",
        "            if False and not published.fresh(now):",
        f"{T}::test_an_expired_verdict_is_not_consumed",
    ),
    (
        "a verdict about another revision of the place is consumed",
        "src/parcel_robot/vlm_veto/bureau.py",
        "            if not published.matches(noun, place.place_id, revision):",
        "            if False and not published.matches(noun, place.place_id, revision):",
        f"{T}::test_a_verdict_about_another_revision_of_the_place_is_not_consumed",
    ),
    (
        "the place revision ignores the pixels",
        "src/parcel_robot/vlm_veto/bureau.py",
        "        hashlib.sha256(crop).hexdigest() if crop else \"no-crop\",",
        "        \"no-crop\",",
        f"{T}::test_the_revision_moves_when_the_pixels_move",
    ),
    (
        "the worker queue is unbounded and the caller blocks",
        "src/parcel_robot/vlm_veto/bureau.py",
        "            queue.Queue(maxsize=max(1, int(queue_depth)))",
        "            queue.Queue(maxsize=0)",
        f"{T}::test_the_queue_is_bounded_and_overflow_is_dropped_not_blocked",
    ),
    (
        "a declined GPU moment is re-asked on every resolve",
        "src/parcel_robot/vlm_veto/bureau.py",
        "            if not published.usable:",
        "            if False and not published.usable:",
        f"{T}::test_a_declined_gpu_moment_asks_and_then_backs_off",
    ),
    (
        "the ASK falls through and dispatches motion",
        "src/parcel_robot/realtime/tool_broker.py",
        "        ask = self._ask_about_place(place)\n        if ask:",
        "        ask = self._ask_about_place(place)\n        if False and ask:",
        (
            f"{T}::test_an_uncertain_place_asks_and_touches_no_door "
            f"{T}::test_a_token_nobody_ever_issued_moves_nothing"
        ),
    ),
    (
        "any confirmation is accepted, stale or invented",
        "src/parcel_robot/realtime/tool_broker.py",
        "            if not token or confirmed != token or spent:",
        "            if not confirmed:",
        (
            f"{T}::test_a_confirmation_of_a_revision_that_has_moved_asks_again_and_moves_nothing "
            f"{T}::test_a_token_nobody_ever_issued_moves_nothing"
        ),
    ),
    (
        "the ASK speaks the query instead of the verdict's candidate",
        "src/parcel_robot/realtime/tool_broker.py",
        "            \"candidate\": str(ask.get(\"candidate\") or \"\"),",
        "            \"candidate\": str(ask.get(\"place\") or place),",
        f"{T}::test_the_ask_carries_the_verdicts_own_candidate",
    ),
    (
        "the runtime stops wiring the ASK door",
        "src/parcel_robot/runtime.py",
        "                    ask_place=self._realtime_ask_place,",
        "                    # ask_place removed",
        f"{T}::test_the_runtime_wires_the_ask_door_without_a_motion_wrapper",
    ),
    (
        "a broken ask door raises out of navigate_to",
        "src/parcel_robot/realtime/tool_broker.py",
        "        except Exception as error:  # noqa: BLE001 - a broken door asks nothing",
        "        except _NeverRaised as error:",
        f"{T}::test_a_door_that_throws_asks_nothing_and_still_navigates",
    ),
    (
        "the model is never told how to confirm",
        "src/parcel_robot/realtime/tool_broker.py",
        "                    CONFIRM_KEY: {\n                        \"type\": \"string\",",
        "                    \"_nm1_removed\": {\n                        \"type\": \"string\",",
        f"{T}::test_the_model_is_told_how_to_confirm",
    ),
    (
        "the naming pass judges by default (flag-off identity broken)",
        "src/parcel_robot/online_map/naming.py",
        "    judge: Any = None,\n) -> NamingReport:",
        "    judge: Any = object(),\n) -> NamingReport:",
        f"{T}::test_no_judge_configured_reproduces_head_exactly",
    ),
    (
        "an unavailable judge reports a strength of zero",
        "src/parcel_robot/vlm_veto/judge.py",
        "            JUDGE_UNAVAILABLE,\n            name=name,\n            entry_id=entry_id,\n            model=self.name,",
        "            JUDGE_UNAVAILABLE,\n            name=name,\n            entry_id=entry_id,\n            strength=0.0,\n            model=self.name,",
        f"{T}::test_an_unavailable_judge_reports_no_strength",
    ),
    (
        "a missing crop is a REJECTION rather than a hold",
        "src/parcel_robot/vlm_veto/judge.py",
        "        if not crop_png:\n            return self._unavailable(text, entry_id, \"no crop to look at\")",
        "        if not crop_png:\n            return JudgeVerdict(JUDGE_REJECT, name=text, entry_id=entry_id, strength=0.0, floor=self._floor, model=self.name, detail=\"no crop\")",
        f"{T}::test_a_judge_with_no_crop_holds_rather_than_rejecting",
    ),
    (
        "the detector label may be held",
        "src/parcel_robot/online_map/naming.py",
        "        if name.text != wanted or name.provenance == NAME_DETECTOR_LABEL:",
        "        if name.text != wanted:",
        f"{T}::test_the_detector_label_is_never_held",
    ),
    (
        "the runtime imports the veto package directly",
        "src/parcel_robot/runtime.py",
        "        from parcel_robot.perception_abstention import (\n            clear_control_thread,\n            mark_control_thread,\n        )",
        "        from parcel_robot.vlm_veto import (\n            clear_control_thread,\n            mark_control_thread,\n        )",
        f"{T}::test_the_runtime_still_imports_no_veto_package_and_no_tensor_library",
    ),
    # ---- correction pass (Fable's verification) -----------------------------
    (
        "the confirm token digests the SIGNALS again (churns on every frame)",
        "src/parcel_robot/runtime.py",
        '            " ".join(str(getattr(verdict, "query", "")).split()),',
        '            str(sorted(dict(getattr(verdict, "signals", {})).items())),',
        f"{T}::test_the_confirm_token_survives_the_robot_looking_at_the_place_again",
    ),
    (
        "the confirm token ignores the pixels it was asked about",
        "src/parcel_robot/runtime.py",
        '            hashlib.sha256(bytes(crop)).hexdigest() if crop else "no-crop",',
        '            "no-crop",',
        f"{T}::test_the_confirm_token_moves_when_the_SUBJECT_moves",
    ),
    (
        "a confirmation is a standing grant, not one trip",
        "src/parcel_robot/realtime/tool_broker.py",
        "            self._spend_confirmation(confirmed)",
        "            pass  # seeded: nothing retires the token",
        f"{T}::test_a_confirmation_authorises_exactly_one_trip_and_not_a_standing_grant",
    ),
    (
        "the replay memory grows without bound",
        "src/parcel_robot/realtime/tool_broker.py",
        "        while len(self._spent_confirmations) > CONFIRM_REPLAY_MEMORY:",
        "        while False and len(self._spent_confirmations) > CONFIRM_REPLAY_MEMORY:",
        f"{T}::test_the_replay_memory_is_bounded",
    ),
    (
        "an ASK is counted as motion the robot started",
        "src/parcel_robot/realtime/config.py",
        'PROACTIVE_MOTION_ALLOWED: tuple[str, ...] = ("play_gesture", "set_pose")',
        'PROACTIVE_MOTION_ALLOWED: tuple[str, ...] = ("play_gesture", "set_pose", "navigate_to")',
        f"{T}::test_an_ask_can_never_reach_the_proactive_motion_counter",
    ),
    (
        "a failed judge build latches and never retries",
        "src/parcel_robot/vlm_veto/judge.py",
        "            self._attempts += 1",
        "            if self._attempts:\n                return False\n            self._attempts += 1",
        f"{T}::test_a_judge_that_failed_to_build_tries_again_on_the_next_pass",
    ),
    (
        "the board evicts first-inserted rather than least-recently-used",
        "src/parcel_robot/vlm_veto/bureau.py",
        "                if key in self._board:\n                    self._board[key] = self._board.pop(key)",
        "                pass  # seeded: a hit no longer refreshes the entry",
        f"{T}::test_the_board_evicts_least_recently_USED_not_first_inserted",
    ),
    (
        "clearing the bureaus leaves a dead reader installed",
        "src/parcel_robot/vlm_veto/bureau.py",
        "        bureau.close()\n    clear_veto_cache()",
        "        bureau.close()",
        f"{T}::test_clearing_the_bureaus_does_not_leave_a_dead_reader_installed",
    ),
    (
        "an arrival-semantics FACE parameter reaches the model",
        "src/parcel_robot/realtime/tool_broker.py",
        "                    # ---- CARD ASK-1 (task_18) --------------------------------\n                    CONFIRM_KEY: {",
        "                    \"face\": {\"type\": \"string\"},\n                    # ---- CARD ASK-1 (task_18) --------------------------------\n                    CONFIRM_KEY: {",
        "tests/test_arrival_semantics.py::test_the_tool_schema_offers_relation_and_nothing_else_about_arrival",
    ),
    (
        "the confirm token becomes a REQUIRED parameter",
        "src/parcel_robot/realtime/tool_broker.py",
        '                "required": ["place"],',
        '                "required": ["place", "confirm"],',
        "tests/test_arrival_semantics.py::test_the_tool_schema_offers_relation_and_nothing_else_about_arrival",
    ),
    (
        "the sweep knob becomes a shipped operating point",
        "src/parcel_robot/vlm_veto/judge.py",
        "JUDGE_FLOOR_ENV = \"PARCEL_NM1_JUDGE_FLOOR\"",
        "JUDGE_FLOOR_ENV = \"PARCEL_NM1_JUDGE_FLOOR_RENAMED\"",
        f"{T}::test_the_shipped_floor_is_the_pre_registered_one_and_nothing_configures_it",
    ),
]


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge() -> None:
    for cache in SEED_REPO.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def main() -> int:
    caught = 0
    for name, rel, old, new, tests in SEEDS:
        path = SEED_REPO / rel
        before = path.read_text(encoding="utf-8")
        digest = sha(path)
        if before.count(old) != 1:
            print(f"{name:62s} ANCHOR NOT UNIQUE ({before.count(old)}) in {rel}")
            continue
        purge()
        try:
            path.write_text(before.replace(old, new), encoding="utf-8")
            proc = subprocess.run(
                [PY_, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
                 *tests.split()],
                cwd=SEED_REPO,
                env={"PATH": "/usr/bin:/bin",
                     "PYTHONPATH": str(SEED_REPO / "src"),
                     "HOME": "/home/jaewoo-jang"},
                capture_output=True,
                text=True,
                check=False,   # a RED seed is the POINT; a raise would hide it
            )
        finally:
            path.write_text(before, encoding="utf-8")
            purge()
            assert sha(path) == digest, f"{rel} not restored byte-identically"
        red = proc.returncode != 0
        caught += red
        tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "?"
        print(f"{name:62s} {'RED  ' if red else 'GREEN'}  {tail[:60]}")
    print(f"\n{caught}/{len(SEEDS)} seeds caught")
    return 0 if caught == len(SEEDS) else 1


if __name__ == "__main__":
    sys.exit(main())
