"""DUPLEX-1 seeded-RED harness.

For each guard: sha the PRODUCT file, apply a one-edit seed, run the named
test and require it to FAIL, restore the exact bytes, verify the sha, purge
__pycache__, re-run and require GREEN.

The tree is shared with five other executors, so every window is kept to one
targeted test and the restore is verified by sha256 before moving on.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/jaewoo-jang/Desktop/Projects/Parcel")
PY = REPO / ".parcel" / "bin" / "python"

LANE = "src/parcel_robot/realtime/lane.py"
GATEWAY = "src/parcel_robot/realtime/audio_gateway.py"
PANEL = "src/parcel_robot/ui/index.html"
RUNTIME = "src/parcel_robot/runtime.py"
CONTROLLER = "src/parcel_robot/duplex/turn_controller.py"

SEEDS: list[tuple[str, str, str, str, str]] = [
    # (label, file, old, new, nodeid)
    (
        "S1 the duck is asked for at all",
        LANE,
        "        self._apply_turn_action(self.turn_controller.note_owner_started(now))",
        "        self.turn_controller.note_owner_started(now)",
        "tests/test_duplex1_rows.py::test_duplex1_d1_the_reply_goes_quiet_within_100ms_of_the_onset",
    ),
    (
        "S2 the reply comes back up after a backchannel",
        LANE,
        "            self._apply_turn_action(self.turn_controller.note_owner_stopped(speech_ended_at))",
        "            self.turn_controller.note_owner_stopped(speech_ended_at)",
        "tests/test_duplex1_rows.py::test_a_surviving_backchannel_ducks_and_then_comes_back_up",
    ),
    (
        "S3 a 'mm-hmm' does not leave a turn owed (MARK-1 H-4c)",
        LANE,
        "            if self._voice_turn_owed and not self._owed_at_hold_open:",
        "            if False:",
        "tests/test_duplex1_rows.py::test_a_survived_backchannel_does_not_leave_a_turn_owed",
    ),
    (
        "S4 the onset reaches the capture index (MARK-1 H-7)",
        GATEWAY,
        '                self._open["interrupted_onset_at"] = _iso(wall - ago)',
        '                self._open["onset_typo_at"] = _iso(wall - ago)',
        "tests/test_duplex1_turn_controller.py::test_the_cut_now_carries_the_onset_and_not_only_the_commit",
    ),
    (
        "S5 a duck with no reply to attenuate is refused",
        GATEWAY,
        "            if conn is None or seq <= 0:",
        "            if conn is None:",
        "tests/test_duplex1_rows.py::test_the_gateway_refuses_a_duck_with_no_reply_to_attenuate",
    ),
    (
        "S6 every playback source goes through the gain node",
        PANEL,
        "      source.connect(mic.gain || mic.playback.destination);",
        "      source.connect(mic.playback.destination);",
        "tests/test_duplex1_panel_duck.py::test_every_playback_source_goes_through_the_gain_node",
    ),
    (
        "S7 a stale duck cannot attenuate the next reply (gjs)",
        PANEL,
        "      if (utterance !== mic.utterance) return null;",
        "      if (false) return null;",
        "tests/test_duplex1_panel_duck.py::test_a_duck_for_another_utterance_is_refused_by_the_panel",
    ),
    (
        "S8 stop puts the panel's gain back to unity",
        PANEL,
        "      resetDuck(mic);  // card DUPLEX-1: the next reply is not the ducked one",
        "      // card DUPLEX-1: the next reply is not the ducked one",
        "tests/test_duplex1_panel_duck.py::test_the_gain_returns_to_unity_on_both_frames_that_end_an_utterance",
    ),
    (
        "S9 initiative is refused while anyone holds the floor",
        CONTROLLER,
        "            allowed = self._state == STATE_LISTEN and not self._owed",
        "            allowed = True",
        "tests/test_duplex1_rows.py::test_duplex1_d4_initiative_is_refused_whenever_anyone_holds_the_floor",
    ),
    (
        "S10 an owed turn survives every transition",
        CONTROLLER,
        "        if state != self._state:\n            self.transitions += 1",
        "        if state != self._state:\n            self.transitions += 1\n            self._owed = False",
        "tests/test_duplex1_turn_controller.py::test_an_owed_turn_survives_every_state_transition",
    ),
    (
        "S11 one overlap per reply: a second VAD start does not re-arm the floor",
        CONTROLLER,
        "            if self._state == STATE_OVERLAP:\n                # One overlap per reply. A second VAD start inside the same\n                # burst is the same turn and must not re-arm the deadline.\n                return _noop(now, \"already overlapping\")",
        "            if False:\n                return _noop(now, \"already overlapping\")",
        "tests/test_duplex1_turn_controller.py::test_a_second_vad_start_inside_one_burst_does_not_rearm_the_deadline",
    ),
    (
        "S12 RT-TURNS-1 stamps a WALL clock, not a monotonic one",
        RUNTIME,
        "            wall = None if monotonic_s is None else wall_now - (monotonic_now - monotonic_s)",
        "            wall = monotonic_s",
        "tests/test_duplex1_rt_turns.py::test_every_ledger_row_becomes_one_turn_row_with_a_wall_stamp",
    ),
    (
        "S14 the state machine does not outlive its socket",
        LANE,
        "        self.turn_controller.reset(keep_owed=False)",
        "        pass  # seeded: the controller outlives the socket",
        "tests/test_duplex1_rows.py::test_the_state_machine_does_not_survive_the_hang_up_that_ends_its_reply",
    ),
    (
        "S15 the panel refuses a non-number gain (correction pass, finding 1)",
        PANEL,
        '      if (typeof body.gain !== "number" || !Number.isFinite(body.gain)) return null;',
        "      if (!Number.isFinite(Number(body.gain))) return null;",
        "tests/test_duplex1_panel_duck.py::test_the_panel_refuses_every_gain_that_is_not_a_number",
    ),
    (
        "S16 no duck may be clamped to silence (correction pass, finding 1)",
        PANEL,
        "      return Math.max(MIN_DUCK_GAIN, Math.min(1, body.gain));",
        "      return Math.max(0, Math.min(1, body.gain));",
        "tests/test_duplex1_panel_duck.py::test_the_panel_never_produces_a_silent_reply",
    ),
    (
        "S17 a stop past the deadline is a commit, not a backchannel (finding 2)",
        LANE,
        "        if speech_ended_at is not None and speech_ended_at <= hold.deadline:",
        "        if speech_ended_at is not None:",
        "tests/test_duplex1_rows.py::test_a_stop_that_lands_past_the_deadline_never_splits_the_two_deciders",
    ),
    (
        "S18 a linear gain never reaches a decibel duck (finding 3)",
        LANE,
        '        if sink is None or not getattr(sink, "accepts_gain_duck", False):',
        '        if sink is None or getattr(sink, "duck", None) is None:',
        "tests/test_duplex1_turn_controller.py::test_the_lane_never_hands_a_linear_gain_to_a_decibel_duck",
    ),
    (
        "S19 the LANE derives the onset the capture index stamps (finding 4)",
        LANE,
        "        self._barge_in_onset = now",
        "        self._barge_in_onset = None",
        "tests/test_duplex1_rows.py::test_the_lane_itself_derives_the_onset_that_reaches_the_capture_index",
    ),
    (
        "S20 reading the gate does not move the counters it is scored from",
        CONTROLLER,
        "        with self._lock:\n            return self._state == STATE_LISTEN and not self._owed",
        "        with self._lock:\n            self.initiative_refusals += 1\n            return self._state == STATE_LISTEN and not self._owed",
        "tests/test_duplex1_turn_controller.py::test_the_gate_counts_both_answers_so_never_asked_is_visible",
    ),
    (
        "S13 was_robot is null, never a vacuous false",
        RUNTIME,
        '                    "was_robot": None,',
        '                    "was_robot": False,',
        "tests/test_duplex1_rt_turns.py::test_was_robot_is_null_and_says_why_rather_than_claiming_false",
    ),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge() -> None:
    for cache in REPO.rglob("__pycache__"):
        if ".parcel" in cache.parts:
            continue
        shutil.rmtree(cache, ignore_errors=True)


def run(nodeid: str) -> int:
    proc = subprocess.run(
        [str(PY), "-m", "pytest", nodeid, "-q", "-p", "no:randomly", "--no-header", "-x"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    return proc.returncode


def main() -> int:
    failures = 0
    for label, relative, old, new, nodeid in SEEDS:
        path = REPO / relative
        before = path.read_text(encoding="utf-8")
        before_sha = sha(path)
        occurrences = before.count(old)
        if occurrences < 1:
            print(f"[{label}] SEED SITE ABSENT — SKIPPED")
            failures += 1
            continue
        try:
            path.write_text(before.replace(old, new), encoding="utf-8")
            purge()
            red = run(nodeid)
        finally:
            path.write_text(before, encoding="utf-8")
            purge()
        after_sha = sha(path)
        green = run(nodeid)
        ok = red != 0 and green == 0 and after_sha == before_sha
        if not ok:
            failures += 1
        print(
            f"[{label}] seeded={'RED' if red else 'GREEN(!)'} "
            f"restored={'GREEN' if green == 0 else 'RED(!)'} "
            f"sha={'identical' if after_sha == before_sha else 'DRIFTED(!)'} "
            f"({before_sha[:12]}, {occurrences} site(s)) -> {'OK' if ok else 'PROBLEM'}"
        )
    print(f"\n{len(SEEDS) - failures}/{len(SEEDS)} seeds behaved")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
