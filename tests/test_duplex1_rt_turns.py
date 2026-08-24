"""Card DUPLEX-1 / RT-TURNS-1: per-turn identity with a WALL stamp.

AIR-1's correction pass found that two of its seven scorecard rows had no
producing path at all: nothing in this tree writes the speaker / origin /
``was_robot`` JSONL that ``tools/bargein_through_air.py::score_turns`` reads.
Its handoff named the fix — a wall clock instead of ``time.monotonic()`` and a
sink other than a 400-row in-memory ring — and this is it.

The runtime here is REAL (``RobotRuntime`` on a scratch store, hosted lane in
text mode) and the rows are written through the product ledger door, because
the whole point of the finding was that a row nobody produces is not a row.

THE HALF THIS DOES NOT CLOSE, ASSERTED RATHER THAN GLOSSED
----------------------------------------------------------
``score_turns``'s second row, ``robot_as_owner``, asks whether a turn credited
to the owner was really the robot arriving back through the microphone. The
runtime cannot answer that: an owner turn that overlaps robot playback is what
a barge-in IS, so "the robot was speaking" is not evidence. The export
therefore writes ``was_robot: null`` — never ``false`` — and a test below pins
that, because a ``false`` would make AIR-1's 0/20 row pass for exactly the
vacuous reason its own verification caught in ``hosted_spend_usd``.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO / "tools" / "bargein_through_air.py"


def _tool():
    """AIR-1's scorer, loaded from the file (it is a script, not a package)."""

    spec = importlib.util.spec_from_file_location("bargein_through_air", TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["bargein_through_air"] = module
    spec.loader.exec_module(module)
    return module


def _runtime_config(tmp_path: Path, store: Path) -> Path:
    path = tmp_path / "duplex1-runtime.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: {store}
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from parcel_robot.audio.devices import AudioDeviceStatus
    from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
    from parcel_robot.models import AgentDecision, VelocityCommand
    from parcel_robot.realtime.config import REALTIME_CONFIG_ENV
    from parcel_robot.runtime import RobotRuntime

    class _Backend:
        name = "duplex1-runtime"

        def reset(self) -> None:
            return None

        def observe(self) -> SimObservation:
            return SimObservation(
                time_s=0.0,
                pose=RobotPose(),
                owner=OwnerTrack(),
                nearest_obstacle_m=10.0,
                backend="duplex1-runtime",
            )

        def move(self, command: VelocityCommand) -> None:
            del command

        def stop(self) -> None:
            return None

        def emergency_stop(self) -> None:
            return None

        def pose(self, pose: object) -> None:
            del pose

    class _SilentModel:
        def decide(self, transcript, tools, context) -> AgentDecision:
            del transcript, tools, context
            return AgentDecision("Understood.")

    realtime = tmp_path / "realtime.yaml"
    realtime.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(realtime))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PARCEL_REALTIME_KEY_ENV", raising=False)

    built = RobotRuntime(
        _runtime_config(tmp_path, tmp_path / "duplex1_store.sqlite3"),
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="duplex1 fixture",
        ),
    )
    yield built
    with contextlib.suppress(AttributeError, OSError, RuntimeError, TypeError, ValueError):
        built.close()


def _three_turns(runtime) -> None:
    """Two owner turns and one robot turn, through the PRODUCT ledger door."""

    runtime._write_realtime_ledger(
        "owner", "are you there", item_id="item_1", session_id="rt_duplex1"
    )
    runtime._write_realtime_ledger(
        "robot", "I am right here", item_id="item_2", session_id="rt_duplex1"
    )
    runtime._write_realtime_ledger(
        "owner", "come to the kitchen", item_id="item_3", session_id="rt_duplex1"
    )


# ================================================================ the schema
def test_every_ledger_row_becomes_one_turn_row_with_a_wall_stamp(runtime) -> None:
    """AIR-1's minimum viable schema, one row per ledger row.

    Seed: return the ring's ``at_s`` as ``wall`` and the ISO parse below fails —
    a monotonic clock is seconds since boot and is not a time of day.
    """

    _three_turns(runtime)
    rows = runtime.realtime_turn_rows()

    assert len(rows) == 3
    assert [row["speaker"] for row in rows] == ["owner", "robot", "owner"]
    assert [row["item_id"] for row in rows] == ["item_1", "item_2", "item_3"]
    assert {row["session_id"] for row in rows} == {"rt_duplex1"}
    assert {row["origin"] for row in rows} == {"realtime"}

    now = datetime.now(UTC)
    for row in rows:
        stamped = datetime.fromisoformat(str(row["wall"]))
        assert stamped.tzinfo is not None, "a wall stamp without a zone is not a wall stamp"
        assert abs((now - stamped).total_seconds()) < 300.0
        assert isinstance(row["monotonic_s"], float)
        identity = row["identity"]
        assert isinstance(identity, dict)
        assert set(identity) >= {"verdict", "cosine", "enrolled", "doa_deg"}


def test_the_rows_are_in_the_order_the_conversation_happened_in(runtime) -> None:
    _three_turns(runtime)
    rows = runtime.realtime_turn_rows()
    stamps = [float(row["monotonic_s"]) for row in rows]
    assert stamps == sorted(stamps)


def test_was_robot_is_null_and_says_why_rather_than_claiming_false(runtime) -> None:
    """The row AIR-1 needs and the runtime cannot answer.

    ``false`` would be a vacuous pass of AIR-1's 0/20 robot-as-owner row — the
    same shape as the ``hosted_spend_usd`` finding its verification caught.
    """

    _three_turns(runtime)
    for row in runtime.realtime_turn_rows():
        assert row["was_robot"] is None
        assert "acoustic" in str(row["was_robot_reason"])


def test_the_limit_is_honoured_so_a_long_session_can_be_tailed(runtime) -> None:
    _three_turns(runtime)
    assert len(runtime.realtime_turn_rows(limit=2)) == 2


# ================================================================= the export
def test_the_export_is_jsonl_that_air1s_own_scorer_reads(runtime, tmp_path: Path) -> None:
    """The producer AIR-1's ``--turns`` flag never had.

    Not a schema this test invented: the file is handed to
    ``score_turns`` out of ``tools/bargein_through_air.py``.
    """

    _three_turns(runtime)
    target = tmp_path / "turns.jsonl"
    result = runtime.export_realtime_turns(target)

    assert result["written"] == 3
    assert result["reason"] == ""
    assert Path(str(result["path"])) == target

    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3

    scored = _tool().score_turns(rows)
    assert scored["owner_turns"] == 2
    # ...and the half that is NOT closed. The scorer reads a missing/None
    # ``was_robot`` as false, so this number is 0 for a reason the export
    # cannot stand behind. DUPLEX1_STATUS.md files it as a handoff rather than
    # claiming the row.
    assert scored["robot_as_owner"] == 0


def test_the_export_refuses_to_guess_a_path_when_capture_is_off(runtime) -> None:
    """``realtime.capture`` disabled ⇒ there is nowhere beside the WAVs.

    A refusal with a reason, not a file dropped in the working directory.
    """

    _three_turns(runtime)
    result = runtime.export_realtime_turns()
    assert result["written"] == 0
    assert result["path"] is None
    assert "capture" in str(result["reason"])


def test_an_unwritable_path_is_a_reason_and_not_an_exception(runtime, tmp_path: Path) -> None:
    """This is called at the end of a session, from a panel or a runbook."""

    _three_turns(runtime)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    result = runtime.export_realtime_turns(blocker / "turns.jsonl")
    assert result["written"] == 0
    assert result["reason"]


def test_an_empty_session_exports_an_empty_file_rather_than_nothing(
    runtime, tmp_path: Path
) -> None:
    """"No turns" and "the export never ran" must not look the same."""

    target = tmp_path / "turns.jsonl"
    result = runtime.export_realtime_turns(target)
    assert result["written"] == 0
    assert target.exists()
    assert target.read_text(encoding="utf-8") == ""
