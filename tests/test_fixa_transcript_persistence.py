"""FIX-A / F3: the duplex session log must record what the robot HEARD.

THE DEFECT THESE TESTS PIN
--------------------------
``turn_outcome`` recorded the robot's own filler text, its TTFT and whether it
was barged into — everything about the robot's mouth and nothing about its
ears. When the 2026-08-11 self-talk storm was investigated, the transcripts
that triggered it were gone: the panel chat deque had aged out and the session
log had rotated. The storm's shape ("him.", "Just", "[BLANK_AUDIO]") had to be
reconstructed from a screenshot.

This adds two fields per turn — the final transcript and its ORIGIN (``mic`` vs
``panel_text``) — under the EXISTING ``duplex.logging`` kill switch. The change
is additive: every pre-existing key keeps its name, type and meaning, which is
what the consumer-tolerance test below pins.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.duplex.session_log import DuplexSessionLog
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.runtime import (
    TRANSCRIPT_ORIGIN_MIC,
    TRANSCRIPT_ORIGIN_PANEL,
    RobotRuntime,
)

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "fixa-transcript"

#: Every key a turn_outcome carried BEFORE this card. Consumers keyed on these
#: must keep working unchanged; that is what "additive" has to mean.
LEGACY_TURN_OUTCOME_KEYS = {
    "type",
    "turn_id",
    "ttft_s",
    "filler_used",
    "filler_reason",
    "filler_audible",
    "barge_in",
    "wall_s",
}


class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del transcript, tools, context
        return AgentDecision("Understood.")


def _runtime(tmp_path: Path, *, logging_enabled: bool = True) -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "fixa-duplex.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
duplex:
  enabled: true
  logging: {"true" if logging_enabled else "false"}
  log_dir: {tmp_path / "duplex-logs"}
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="fixa transcript persistence fixture",
        ),
    )


def _turn_outcomes(runtime: RobotRuntime) -> list[dict]:
    log_path = runtime.duplex.log.path
    if not log_path.exists():
        return []
    return [
        row
        for row in (
            json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line
        )
        if row.get("type") == "turn_outcome"
    ]


def test_typed_command_round_trips_transcript_and_origin(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime.submit_voice_text("go to the sidewalk") == 1
        assert runtime.voice_session.wait_until_idle(3.0)
        rows = _turn_outcomes(runtime)
        assert len(rows) == 1, rows
        assert rows[0]["transcript"] == "go to the sidewalk"
        assert rows[0]["transcript_origin"] == TRANSCRIPT_ORIGIN_PANEL
    finally:
        runtime.close()


def test_microphone_transcripts_are_labelled_as_microphone(tmp_path: Path) -> None:
    """The junk finals the storm produced would now be attributable."""

    runtime = _runtime(tmp_path)
    try:
        assert runtime._submit_microphone_text("him.") == 1
        assert runtime.voice_session.wait_until_idle(3.0)
        rows = _turn_outcomes(runtime)
        assert rows[0]["transcript"] == "him."
        assert rows[0]["transcript_origin"] == TRANSCRIPT_ORIGIN_MIC
    finally:
        runtime.close()


def test_microphone_loop_is_wired_to_the_labelled_entry_point(tmp_path: Path) -> None:
    """The label is worthless if the capture loop does not use that door."""

    import inspect as _inspect

    from parcel_robot import runtime as runtime_module

    source = _inspect.getsource(runtime_module.RobotRuntime.__init__)
    assert "submit_text=self._submit_microphone_text" in source
    runtime = _runtime(tmp_path)
    try:
        # The wrapper must preserve submit_voice_text's contract exactly.
        assert runtime._submit_microphone_text("stay", is_final=False) is None
    finally:
        runtime.close()


def test_transcript_fields_obey_the_existing_duplex_logging_kill_switch(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, logging_enabled=False)
    try:
        assert runtime.duplex.log.enabled is False
        assert runtime.submit_voice_text("go to the sidewalk") == 1
        assert runtime.voice_session.wait_until_idle(3.0)
        assert _turn_outcomes(runtime) == [], "logging is off; nothing may be written"
        # The in-memory snapshot must not become a side door around the switch.
        outcomes = runtime.duplex.snapshot()["turn_outcomes"]
        assert outcomes, "the outcome itself is still recorded in memory"
        assert "transcript" not in outcomes[-1]
        assert "transcript_origin" not in outcomes[-1]
    finally:
        runtime.close()


def test_schema_change_is_purely_additive(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        assert runtime.submit_voice_text("come here") == 1
        assert runtime.voice_session.wait_until_idle(3.0)
        row = _turn_outcomes(runtime)[0]
        assert LEGACY_TURN_OUTCOME_KEYS <= set(row), sorted(set(row))
        assert set(row) - LEGACY_TURN_OUTCOME_KEYS == {"transcript", "transcript_origin"}
        # Types of the pre-existing fields are untouched.
        assert isinstance(row["turn_id"], int)
        assert isinstance(row["filler_audible"], bool)
        assert isinstance(row["barge_in"], bool)
        assert row["filler_used"] is None or isinstance(row["filler_used"], str)
    finally:
        runtime.close()


def test_legacy_consumers_tolerate_the_new_fields(tmp_path: Path) -> None:
    """The shape every known reader uses: filter on ``type``, read known keys.

    Proven against the writer itself rather than a hand-built dict, so a future
    change to ``write_turn_outcome`` cannot pass this test while breaking the
    readers.
    """

    log = DuplexSessionLog(tmp_path / "session.jsonl", enabled=True)
    log.write_turn_outcome(
        {
            "turn_id": 7,
            "ttft_s": 0.31,
            "filler_used": None,
            "filler_reason": None,
            "filler_audible": False,
            "barge_in": False,
            "transcript": "[BLANK_AUDIO]",
            "transcript_origin": TRANSCRIPT_ORIGIN_MIC,
        }
    )
    rows = [
        json.loads(line)
        for line in (tmp_path / "session.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    # tests/test_duplex_integration.py's reader, verbatim in shape.
    assert any(row.get("type") == "turn_outcome" and row.get("turn_id") == 7 for row in rows)
    # A reader that projects only the documented columns is unaffected.
    projected = {key: rows[0][key] for key in LEGACY_TURN_OUTCOME_KEYS}
    assert projected["turn_id"] == 7
    assert projected["ttft_s"] == pytest.approx(0.31)


def test_unknown_transcript_origin_is_refused(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        with pytest.raises(ValueError, match="unknown transcript origin"):
            runtime.submit_voice_text("hello", origin="telepathy")
    finally:
        runtime.close()


def test_held_transcripts_are_released_after_every_turn(tmp_path: Path) -> None:
    """A per-turn buffer must not become a transcript retention store."""

    for logging_enabled in (True, False):
        runtime = _runtime(tmp_path / f"log-{logging_enabled}", logging_enabled=logging_enabled)
        try:
            assert runtime.submit_voice_text("come here") == 1
            assert runtime.voice_session.wait_until_idle(3.0)
            assert dict(runtime._turn_transcripts) == {}
        finally:
            runtime.close()
