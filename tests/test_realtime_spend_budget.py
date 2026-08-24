"""Card R25 — the budget that actually refuses (full audit §Ops-2).

WHAT THIS FILE PINS
-------------------
``monthly_budget_usd`` was documented in the owner's own ``realtime.yaml`` as
an arming refusal — "the arming gate refuses to open a session once this
month's estimated spend reaches this number" — and the arming gate never read
it. The comparison existed in ``decide_realtime_arming`` from R1; the only
caller, ``RealtimeLane.arm``, never passed a figure, so the gate compared its
``0.0`` default against ``25.0`` on every session for twenty-four cards. The
owner has been operating for weeks believing a ceiling existed.

Four claims are asserted here, and each has a named seed in R25_STATUS.md §Seeds
that turns it red:

1. **The ceiling refuses** — a readable ledger at or past the budget refuses to
   arm, and the refusal names the figure, the period and the key.
2. **The ceiling is durable** — it is read from a file, so it survives a
   restart. A ceiling computed from ``lane.usage_rows`` would reset on every
   reboot, which is the same moment a runaway loop restarts.
3. **The ceiling fails OPEN** — an unreadable ledger arms anyway, loudly. This
   is the one deliberate inversion of this package's fail-closed doctrine, and
   it is pinned in BOTH directions so a future "hardening" reddens a test
   instead of grounding the robot.
4. **Safety outranks the ceiling** — on an open session, SAFETY-class
   narrations (``whisperer.CRITICAL_KINDS``) are spoken past the budget and
   non-safety chatter is not, which is the same asymmetry those classes already
   have against ``max_updates_per_minute``. The over-correction — a budget gate
   that silences the emergency latch — is its own seed.

NO CLOCKS, NO NETWORK, NO SLEEPS. The ledger's wall clock and its monotonic
cache clock are both injected, so "last month" and "the cache expired" are
function calls rather than waits.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.config import (
    REALTIME_CONFIG_ENV,
    RealtimeConfig,
    resolve_capture_dir,
)
from parcel_robot.realtime.cost import realtime_spend_usd
from parcel_robot.realtime.fake_server import FakeRealtimeServer, Step, handshake, happy_turn
from parcel_robot.realtime.lane import (
    CODE_ARMED,
    CODE_BUDGET_EXHAUSTED,
    RealtimeLane,
    RealtimeLaneError,
    decide_realtime_arming,
)
from parcel_robot.realtime.spend_ledger import (
    SPEND_LEDGER_NAME,
    SPEND_LEDGER_SCHEMA,
    MonthToDateSpend,
    SpendLedger,
    month_key,
    resolve_spend_ledger_path,
    spend_row,
)
from parcel_robot.realtime.transport import transport_pair
from parcel_robot.realtime.whisperer import (
    CRITICAL_KINDS,
    KIND_EMERGENCY_STOP,
    KIND_REFUSAL,
    KIND_VOICE_REJECTED,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]

#: One million uncached input tokens at the assumed $4.00/Mtok. A round dollar
#: makes every assertion below readable without a calculator.
ONE_DOLLAR_ROW = {"input_tokens": 250_000, "output_tokens": 0, "cached_tokens": 0}


class _Clock:
    """Monotonic seconds a test advances by hand."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _Wall:
    """UTC wall clock a test sets by hand, for month boundaries."""

    def __init__(self, moment: datetime | None = None) -> None:
        self.moment = moment or datetime(2026, 8, 21, 9, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.moment


def _ledger(path: Path, **kwargs) -> SpendLedger:
    notes: list[str] = []
    ledger = SpendLedger(path, on_note=notes.append, **kwargs)
    ledger.notes = notes  # type: ignore[attr-defined]
    return ledger


def _config(**overrides) -> RealtimeConfig:
    return RealtimeConfig(**{"enabled": True, "source": "test", **overrides})


# ======================================================= the arithmetic first
def test_one_priced_row_carries_the_schema_the_month_and_the_assumed_flag() -> None:
    """The flag is on EVERY row, not once in a header (module docstring)."""

    row = spend_row(
        ONE_DOLLAR_ROW,
        session_id="rt_abc",
        when=datetime(2026, 8, 21, 9, 14, 2, tzinfo=timezone.utc),
    )
    assert row["schema"] == SPEND_LEDGER_SCHEMA
    assert row["month"] == "2026-08"
    assert row["wall"] == "2026-08-21T09:14:02Z"
    assert row["session_id"] == "rt_abc"
    assert row["rates_are_assumed"] is True
    assert row["estimated_usd"] == pytest.approx(1.0)
    assert row["estimated_usd"] == pytest.approx(realtime_spend_usd([ONE_DOLLAR_ROW]))


def test_the_ledger_is_append_only_and_totals_only_the_current_month(
    tmp_path: Path,
) -> None:
    """Durability, and the period the ceiling is measured over."""

    wall = _Wall(datetime(2026, 7, 15, tzinfo=timezone.utc))
    path = tmp_path / SPEND_LEDGER_NAME
    ledger = _ledger(path, now=wall, cache_ttl_s=0.0)
    ledger.record(ONE_DOLLAR_ROW, session_id="july")
    wall.moment = datetime(2026, 8, 2, tzinfo=timezone.utc)
    ledger.record(ONE_DOLLAR_ROW, session_id="august")
    ledger.record(ONE_DOLLAR_ROW, session_id="august")

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3, "append-only: nothing rewrites an earlier row"
    assert [json.loads(line)["month"] for line in lines] == ["2026-07", "2026-08", "2026-08"]

    august = ledger.month_to_date()
    assert august.month == "2026-08"
    assert august.usd == pytest.approx(2.0), "July's dollar is not this month's"
    assert august.rows == 2
    assert august.readable is True
    assert august.rates_are_assumed is True
    assert ledger.month_to_date(month="2026-07").usd == pytest.approx(1.0)


def test_a_second_process_reading_the_same_file_sees_the_first_process_spend(
    tmp_path: Path,
) -> None:
    """THE POINT OF DURABILITY. A ceiling that resets on reboot is not a ceiling.

    ``lane.usage_rows`` is emptied by every process restart, which is also the
    moment a runaway loop restarts. This is the same file read by a ledger
    object that shares nothing with the writer.
    """

    path = tmp_path / SPEND_LEDGER_NAME
    first = _ledger(path, now=_Wall())
    for _ in range(3):
        first.record(ONE_DOLLAR_ROW, session_id="before-the-restart")

    after_restart = _ledger(path, now=_Wall())
    assert after_restart.rows_written == 0, "a fresh object has written nothing itself"
    assert after_restart.month_to_date().usd == pytest.approx(3.0)


def test_an_absent_ledger_is_a_readable_zero_not_a_broken_file(tmp_path: Path) -> None:
    """A fresh install must not wear a warning it did not earn."""

    total = _ledger(tmp_path / "never-written.jsonl", now=_Wall()).month_to_date()
    assert (total.readable, total.usd, total.rows, total.note) == (True, 0.0, 0, "")


def test_corrupt_rows_are_skipped_counted_and_declared_an_undercount(
    tmp_path: Path,
) -> None:
    """Fail-open in the same DIRECTION as an unreadable file, never a second policy."""

    path = tmp_path / SPEND_LEDGER_NAME
    ledger = _ledger(path, now=_Wall(), cache_ttl_s=0.0)
    ledger.record(ONE_DOLLAR_ROW, session_id="good")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json at all\n")
        handle.write(json.dumps({"month": "2026-08", "estimated_usd": "free"}) + "\n")
        handle.write(json.dumps({"month": "2026-08", "estimated_usd": float("nan")}) + "\n")
        handle.write("\n")  # blank lines are not corruption
    total = ledger.month_to_date()
    assert total.readable is True, "a bad LINE is not a bad FILE"
    assert total.usd == pytest.approx(1.0)
    assert total.skipped_rows == 3
    assert "UNDERCOUNT" in total.note


def test_an_unreadable_ledger_reports_unreadable_rather_than_zero(tmp_path: Path) -> None:
    """``readable=False`` is the fail-open contract, and it is LOUD."""

    path = tmp_path / SPEND_LEDGER_NAME
    path.mkdir()  # a directory where a file should be: open() raises IsADirectoryError
    ledger = _ledger(path, now=_Wall())
    total = ledger.month_to_date()
    assert total.readable is False
    assert total.usd == 0.0
    assert "NOT being enforced" in total.note
    assert ledger.notes and "NOT being enforced" in ledger.notes[0]  # type: ignore[attr-defined]


def test_a_write_that_cannot_land_is_counted_and_never_raises(tmp_path: Path) -> None:
    """``record`` runs on the pump thread (card R22 §Safety-1). It may not raise."""

    path = tmp_path / "wall" / SPEND_LEDGER_NAME
    (tmp_path / "wall").write_text("I am a file, not a directory", encoding="utf-8")
    ledger = _ledger(path, now=_Wall())
    assert ledger.record(ONE_DOLLAR_ROW) is False
    assert ledger.write_failures == 1
    assert ledger.last_write_failure and "Error" in ledger.last_write_failure
    assert ledger.notes and "UNDERCOUNT" in ledger.notes[0]  # type: ignore[attr-defined]


def test_the_cached_total_is_exact_between_re_reads(tmp_path: Path) -> None:
    """The narration gate asks per fact; it must not touch the disk per fact."""

    monotonic = _Clock()
    ledger = _ledger(
        tmp_path / SPEND_LEDGER_NAME, now=_Wall(), monotonic=monotonic, cache_ttl_s=5.0
    )
    assert ledger.month_to_date().usd == 0.0
    ledger.record(ONE_DOLLAR_ROW)
    # Still inside the TTL: the number is right anyway, because record() updated
    # the cache in place rather than only invalidating it.
    assert ledger.month_to_date().usd == pytest.approx(1.0)
    monotonic.advance(10.0)
    assert ledger.month_to_date().usd == pytest.approx(1.0), "and the re-read agrees"


# ===================================================== the gate, in isolation
def test_the_gate_refuses_at_the_ceiling_and_names_figure_period_and_key() -> None:
    decision = decide_realtime_arming(
        config=_config(monthly_budget_usd=25.0),
        handshake_token="csrf",
        mic_gesture=True,
        spend_usd=25.0,
        spend_month="2026-08",
    )
    assert decision.armed is False
    assert decision.code == CODE_BUDGET_EXHAUSTED
    assert "$25.00" in decision.reason, "the figure spent"
    assert "in 2026-08" in decision.reason, "the period"
    assert "monthly_budget_usd" in decision.reason, "how to raise it"
    assert "ASSUMED" in decision.reason, "never presented as an invoice"
    assert "1st of next month" in decision.reason


def test_a_sub_cent_ceiling_still_names_a_figure_the_owner_can_act_on() -> None:
    """Found by this card's own live proof, act A.

    With ``monthly_budget_usd: 0.001`` the first refusal read "an estimated
    $0.00 in 2026-08 has reached the $0.00 ceiling" — two-decimal formatting on
    a sub-cent ceiling, which is the "refusal reason silent" failure with a
    number in front of it. Both figures now share ONE precision, chosen off the
    smaller of the two, so they can never disagree about scale either.
    """

    decision = decide_realtime_arming(
        config=_config(monthly_budget_usd=0.001),
        handshake_token="csrf",
        mic_gesture=True,
        spend_usd=0.001,
        spend_month="2026-08",
    )
    assert decision.code == CODE_BUDGET_EXHAUSTED
    assert "$0.0010" in decision.reason
    assert "$0.00 " not in decision.reason, decision.reason


def test_the_gate_arms_one_cent_below_the_ceiling() -> None:
    decision = decide_realtime_arming(
        config=_config(monthly_budget_usd=25.0),
        handshake_token="csrf",
        mic_gesture=True,
        spend_usd=24.99,
        spend_month="2026-08",
    )
    assert decision.code == CODE_ARMED and decision.armed is True


def test_an_unreadable_ledger_arms_with_a_warning_instead_of_refusing() -> None:
    """FAIL-OPEN, pinned. A broken spend file must never brick the robot."""

    decision = decide_realtime_arming(
        config=_config(monthly_budget_usd=25.0),
        handshake_token="csrf",
        mic_gesture=True,
        # A huge figure that would refuse ten times over IF it were believed.
        spend_usd=9_999.0,
        spend_readable=False,
        spend_note="spend ledger unreadable; the monthly ceiling is NOT being enforced",
        spend_month="2026-08",
    )
    assert decision.armed is True and decision.code == CODE_ARMED
    assert decision.warnings, "a degraded yes must still say something"
    assert "NOT being enforced" in decision.warnings[0]
    assert decision.as_dict()["warnings"] == list(decision.warnings)


def test_the_budget_is_the_fourth_no_and_never_substitutes_for_the_first_three() -> None:
    """Over budget does not make a missing gesture acceptable, or vice versa."""

    over = {"spend_usd": 99.0, "spend_month": "2026-08"}
    assert (
        decide_realtime_arming(
            config=_config(enabled=False), handshake_token="csrf", mic_gesture=True, **over
        ).code
        != CODE_BUDGET_EXHAUSTED
    )
    assert (
        decide_realtime_arming(
            config=_config(), handshake_token=None, mic_gesture=True, **over
        ).code
        != CODE_BUDGET_EXHAUSTED
    )
    assert (
        decide_realtime_arming(
            config=_config(), handshake_token="csrf", mic_gesture=False, **over
        ).code
        != CODE_BUDGET_EXHAUSTED
    )


# ===================================================== the lane, end to end
def _lane(
    tmp_path: Path,
    *,
    budget: float = 25.0,
    script: list[Step] | None = None,
    ledger: SpendLedger | None = None,
) -> tuple[RealtimeLane, SpendLedger, list[FakeRealtimeServer]]:
    clock = _Clock()
    servers: list[FakeRealtimeServer] = []
    steps = list(script or (handshake() + happy_turn()))

    def factory():
        lane_end, server_end = transport_pair(clock=clock)
        servers.append(FakeRealtimeServer(transport=server_end, script=list(steps), clock=clock))
        return lane_end

    spend = ledger or _ledger(tmp_path / SPEND_LEDGER_NAME, now=_Wall(), cache_ttl_s=0.0)
    lane = RealtimeLane(
        config=_config(monthly_budget_usd=budget),
        instructions="be a good dog",
        transport_factory=factory,
        clock=clock,
        spend_ledger=spend,
    )
    return lane, spend, servers


def test_the_lane_arming_path_actually_reads_the_ledger(tmp_path: Path) -> None:
    """THE AUDIT'S DEFECT, as one assertion.

    ``RealtimeLane.arm`` did not pass a spend figure, so this refusal was
    unreachable for the whole of R1-R24 no matter what the ledger said.
    """

    lane, spend, _ = _lane(tmp_path, budget=2.0)
    assert lane.arm(handshake_token="csrf", mic_gesture=True).armed is True

    spend.record(ONE_DOLLAR_ROW)
    spend.record(ONE_DOLLAR_ROW)

    decision = lane.arm(handshake_token="csrf", mic_gesture=True)
    assert decision.armed is False
    assert decision.code == CODE_BUDGET_EXHAUSTED
    assert "$2.00" in decision.reason


def test_an_over_budget_lane_refuses_to_open_a_session_at_all(tmp_path: Path) -> None:
    lane, spend, servers = _lane(tmp_path, budget=1.0)
    spend.record(ONE_DOLLAR_ROW)
    with pytest.raises(RealtimeLaneError) as caught:
        lane.open_session(handshake_token="csrf", mic_gesture=True)
    assert "monthly_budget_usd" in str(caught.value)
    assert lane.transport is None and not servers, "no socket was ever opened"


def test_the_refusal_survives_a_restart_because_the_ledger_is_on_disk(
    tmp_path: Path,
) -> None:
    """Work item 2, as a behaviour rather than a claim."""

    path = tmp_path / SPEND_LEDGER_NAME
    first, spend, _ = _lane(tmp_path, budget=1.0, ledger=_ledger(path, now=_Wall(), cache_ttl_s=0.0))
    spend.record(ONE_DOLLAR_ROW)
    assert first.arm(handshake_token="csrf", mic_gesture=True).armed is False

    # A brand-new lane and a brand-new ledger object over the same path: this is
    # what "the robot rebooted" looks like from the ceiling's point of view.
    reborn, _, _ = _lane(tmp_path, budget=1.0, ledger=_ledger(path, now=_Wall(), cache_ttl_s=0.0))
    decision = reborn.arm(handshake_token="csrf", mic_gesture=True)
    assert decision.armed is False and decision.code == CODE_BUDGET_EXHAUSTED


def test_a_lane_with_no_ledger_behaves_exactly_as_it_did_before_this_card(
    tmp_path: Path,
) -> None:
    """``spend_ledger=None`` is 'not metered', which is not 'over budget'."""

    del tmp_path
    lane = RealtimeLane(
        config=_config(monthly_budget_usd=0.01),
        instructions="x",
        transport_factory=lambda: transport_pair()[0],
    )
    decision = lane.arm(handshake_token="csrf", mic_gesture=True)
    assert decision.armed is True
    assert lane.snapshot()["month_to_date"] is None
    assert lane.narrate_event("a fact", critical=False) is False  # no session, not budget


def test_a_broken_ledger_lets_the_lane_open_and_says_so(tmp_path: Path) -> None:
    """Fail-open, all the way through the lane. The over-correction is a seed."""

    broken = tmp_path / SPEND_LEDGER_NAME
    broken.mkdir()
    lane, _, servers = _lane(tmp_path, budget=0.01, ledger=_ledger(broken, now=_Wall()))
    session = lane.open_session(handshake_token="csrf", mic_gesture=True)
    assert session and servers, "a read-only disk may not ground the robot"
    decision = lane.arming
    assert decision is not None and decision.armed is True
    assert any("NOT being enforced" in warning for warning in decision.warnings)
    assert any("NOT being enforced" in note for note in lane.events)


def test_a_completed_response_writes_one_durable_priced_row(tmp_path: Path) -> None:
    """The write path: ``response.done`` -> priced row -> the ceiling's file."""

    lane, spend, servers = _lane(tmp_path, budget=25.0)
    lane.open_session(handshake_token="csrf", mic_gesture=True)
    servers[-1].pump()
    lane.pump()
    lane.send_audio(b"\x00\x00" * 2400)
    servers[-1].pump()
    lane.pump()

    assert lane.usage_rows, "the fake server completed a response"
    rows = [
        json.loads(line)
        for line in (tmp_path / SPEND_LEDGER_NAME).read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == len(lane.usage_rows)
    assert rows[0]["session_id"] == lane.session_id
    assert rows[0]["rates_are_assumed"] is True
    assert rows[0]["estimated_usd"] == pytest.approx(
        realtime_spend_usd([lane.usage_rows[0]]), abs=1e-9
    )
    assert spend.month_to_date().rows == len(rows)


def test_a_ledger_that_raises_never_takes_the_pump_down(tmp_path: Path) -> None:
    """Card R22's law applied to R25's new write: counted, noted, never raised."""

    class _Exploding:
        def record(self, row, *, session_id=None):
            raise RuntimeError("disk on fire")

        def month_to_date(self):
            return MonthToDateSpend(month="2026-08", usd=0.0, rows=0, readable=True)

    lane, _, servers = _lane(tmp_path, ledger=_Exploding())  # type: ignore[arg-type]
    lane.open_session(handshake_token="csrf", mic_gesture=True)
    servers[-1].pump()
    lane.pump()
    lane.send_audio(b"\x00\x00" * 2400)
    servers[-1].pump()
    lane.pump()
    assert lane.usage_rows, "the turn completed"
    assert lane.spend_ledger_failures == 1
    assert any("spend ledger row not written" in note for note in lane.events)


def test_a_month_to_date_read_that_raises_fails_open_rather_than_refusing(
    tmp_path: Path,
) -> None:
    class _Exploding:
        def record(self, row, *, session_id=None):
            return True

        def month_to_date(self):
            raise OSError("no")

    lane, _, _ = _lane(tmp_path, budget=0.01, ledger=_Exploding())  # type: ignore[arg-type]
    assert lane.arm(handshake_token="csrf", mic_gesture=True).armed is True
    assert lane.spend_ledger_failures == 1


# ============================== work item 4: the safety/cost asymmetry, pinned
def _open_over_budget(tmp_path: Path) -> tuple[RealtimeLane, SpendLedger, list]:
    """A lane with an OPEN session whose ledger is past the ceiling.

    The ceiling refuses to OPEN a session; it never hangs up one that is
    already open. Reaching this state is therefore ordinary: the owner started
    talking under the ceiling and the conversation crossed it.
    """

    lane, spend, servers = _lane(tmp_path, budget=1.0)
    lane.open_session(handshake_token="csrf", mic_gesture=True)
    servers[-1].pump()
    lane.pump()
    spend.record(ONE_DOLLAR_ROW)  # now at the ceiling
    assert lane.active, "the ceiling does not hang up an open session"
    return lane, spend, servers


def test_a_safety_narration_is_spoken_past_the_ceiling(tmp_path: Path) -> None:
    """THE DECISION, pinned: safety facts outrank the owner's cost knob.

    Same asymmetry ``CRITICAL_KINDS`` already has against
    ``max_updates_per_minute``, for the same reason C's bench measured
    disqualifyingly: a robot that will not say "I have stopped" because of a
    money knob is the failure the knob exists to prevent.
    """

    lane, _, _ = _open_over_budget(tmp_path)
    assert lane.narrate_event("The robot has stopped: emergency stop.", critical=True) is True
    assert lane.narrations == 1
    assert lane.narrations_over_budget == 1
    assert lane.narrations_skipped_budget == 0
    assert any("PAST this month" in note for note in lane.events)


def test_non_safety_chatter_is_held_back_by_the_ceiling(tmp_path: Path) -> None:
    """The other half of the asymmetry. Without this the ceiling is decorative."""

    lane, _, _ = _open_over_budget(tmp_path)
    assert lane.narrate_event("The battery is getting low.", critical=False) is False
    assert lane.narrations == 0
    assert lane.narrations_skipped == 1
    assert lane.narrations_skipped_budget == 1
    assert lane.narrations_over_budget == 0
    assert any("held back by this month" in note for note in lane.events)


def test_under_the_ceiling_both_classes_narrate_normally(tmp_path: Path) -> None:
    """The gate must be the BUDGET and not a new unconditional narration rule."""

    # One narration per lane: the floor gate refuses a second while the first
    # response is still outstanding, and that refusal is not the budget's.
    for index, critical in enumerate((False, True)):
        lane, _, servers = _lane(tmp_path / f"under-{index}", budget=1000.0)
        lane.open_session(handshake_token="csrf", mic_gesture=True)
        servers[-1].pump()
        lane.pump()
        assert lane.narrate_event("A fact.", critical=critical) is True
        assert lane.narrations == 1
        assert (lane.narrations_skipped_budget, lane.narrations_over_budget) == (0, 0)


def test_the_budget_is_the_LAST_narration_no_so_skips_are_attributed_honestly(
    tmp_path: Path,
) -> None:
    """A narration the floor gate would have dropped is not the budget's fault."""

    lane, spend, servers = _lane(tmp_path, budget=1.0)
    lane.open_session(handshake_token="csrf", mic_gesture=True)
    servers[-1].pump()
    lane.pump()
    spend.record(ONE_DOLLAR_ROW)
    lane._responses_pending = 1  # the owner is owed an answer
    assert lane.narrate_event("A fact.", critical=False) is False
    assert lane.narrations_skipped == 1
    assert lane.narrations_skipped_budget == 0, "attributed to the floor, not the money"


def test_the_bypass_set_is_exactly_the_whisperers_critical_set() -> None:
    """ONE list, one answer. Two lists would drift, and this one is safety-shaped.

    Card R25 work item 4, and F1-SI open risk 10.2 answered on the record: a
    voice rejection is deliberately NOT in the set. The critical set exists for
    facts about the OWNER'S OWN requests; a rejection is by construction a fact
    about somebody else's, and a talkative television must not be able to spend
    past a ceiling the owner set. The counter and the panel event for a
    rejection are unconditional either way, so the fact is never lost — only the
    spoken sentence waits.
    """

    assert KIND_EMERGENCY_STOP in CRITICAL_KINDS
    assert KIND_REFUSAL in CRITICAL_KINDS
    assert KIND_VOICE_REJECTED not in CRITICAL_KINDS


# ================================================== work item 3: the surfaces
def test_the_lane_snapshot_answers_how_close_am_i(tmp_path: Path) -> None:
    lane, spend, _ = _lane(tmp_path, budget=4.0)
    spend.record(ONE_DOLLAR_ROW)
    snapshot = lane.snapshot()
    month = snapshot["month_to_date"]
    assert isinstance(month, dict)
    assert month["usd"] == pytest.approx(1.0)
    assert month["month"] == month_key(datetime(2026, 8, 21, tzinfo=timezone.utc))
    assert month["readable"] is True
    assert month["rates_are_assumed"] is True
    assert snapshot["monthly_budget_usd"] == 4.0
    assert snapshot["narrations_skipped_budget"] == 0
    assert snapshot["narrations_over_budget"] == 0


def test_the_ledger_snapshot_carries_the_ceiling_and_the_derived_answers(
    tmp_path: Path,
) -> None:
    """The panel does no arithmetic, so it cannot disagree with the gate."""

    spend = _ledger(tmp_path / SPEND_LEDGER_NAME, now=_Wall(), cache_ttl_s=0.0)
    spend.record(ONE_DOLLAR_ROW)
    snapshot = spend.snapshot(budget_usd=4.0)
    assert snapshot["budget_usd"] == 4.0
    assert snapshot["remaining_usd"] == pytest.approx(3.0)
    assert snapshot["fraction_of_budget"] == pytest.approx(0.25)
    assert snapshot["over_budget"] is False
    assert snapshot["rows_written"] == 1

    for _ in range(3):
        spend.record(ONE_DOLLAR_ROW)
    assert spend.snapshot(budget_usd=4.0)["over_budget"] is True


def test_an_unreadable_ledger_is_not_reported_as_a_zero_spend_month(
    tmp_path: Path,
) -> None:
    """"$0.00 this month" and "I cannot tell you" are different claims."""

    broken = tmp_path / SPEND_LEDGER_NAME
    broken.mkdir()
    snapshot = _ledger(broken, now=_Wall()).snapshot(budget_usd=25.0)
    assert snapshot["readable"] is False
    assert snapshot["over_budget"] is False, "unreadable never refuses (fail-open)"
    assert "NOT being enforced" in str(snapshot["note"])


def test_the_panel_renders_the_three_ledger_states_distinctly() -> None:
    """The panel must not collapse 'no ledger' / 'unreadable' / 'a number'."""

    source = (REPO / "src" / "parcel_robot" / "ui" / "index.html").read_text(encoding="utf-8")
    assert "realtimeBudgetLabel" in source
    assert "no spend ledger (monthly ceiling not enforced)" in source
    assert "spend ledger UNREADABLE" in source
    assert "CEILING REACHED, new sessions refused" in source
    assert "realtime.month_to_date" in source


# ================================================ the runtime wires it for real
class _Backend:
    """The smallest backend a RobotRuntime will boot on."""

    name = "r25-spend"

    def __init__(self) -> None:
        self.commands: list[VelocityCommand] = []

    def reset(self) -> SimObservation:
        return self.observe()

    def observe(self) -> SimObservation:
        return SimObservation(
            robot=RobotPose(0.0, 0.0, 0.0),
            owner=OwnerTrack(1.0, 0.0, True),
            obstacle_distance=5.0,
            timestamp=0.0,
        )

    def apply(self, command: VelocityCommand) -> SimObservation:
        self.commands.append(command)
        return self.observe()

    def close(self) -> None:
        return None

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del transcript, tools, context
        return AgentDecision("Understood.")


def _runtime(tmp_path: Path) -> RobotRuntime:
    path = tmp_path / "r25.yaml"
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
  logging: false
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
            detail="r25 spend fixture",
        ),
    )


def test_the_runtime_arms_a_ledger_and_hands_it_to_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmonthly_budget_usd: 3.0\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.setenv("PARCEL_REALTIME_SPEND_LEDGER", str(tmp_path / SPEND_LEDGER_NAME))
    runtime = _runtime(tmp_path)
    try:
        ledger = runtime._realtime_spend_ledger
        assert ledger is not None, "the ceiling must be armed wherever the lane is"
        assert runtime.realtime_lane is not None
        assert runtime.realtime_lane._spend_ledger is ledger

        month = runtime.realtime_snapshot()["month_to_date"]
        assert isinstance(month, dict)
        assert month["budget_usd"] == 3.0
        assert month["over_budget"] is False
        assert month["readable"] is True

        ledger.record(ONE_DOLLAR_ROW)
        ledger.record(ONE_DOLLAR_ROW)
        ledger.record(ONE_DOLLAR_ROW)
        after = runtime.realtime_snapshot()["month_to_date"]
        assert isinstance(after, dict)
        assert after["over_budget"] is True
        assert after["remaining_usd"] == pytest.approx(0.0)

        decision = runtime.realtime_lane.arm(handshake_token="csrf", mic_gesture=True)
        assert decision.code == CODE_BUDGET_EXHAUSTED
    finally:
        runtime.close()


def test_the_runtime_marks_safety_classes_critical_on_the_way_to_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag has to survive the trip, or the lane's exemption is unreachable.

    Both robot-initiated doors are covered: ``_whisper`` (the event path, used
    by refusals and mission terminals) and ``_step_whisperer``'s loop (the
    digest path, which is how the EMERGENCY LATCH reaches the model). A card
    that exempted safety in the lane and then handed ``critical=False`` from
    every caller would pass every lane-level test in this file and still gag the
    latch, so the flag is asserted at the door it is produced at.
    """

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.setenv("PARCEL_REALTIME_SPEND_LEDGER", str(tmp_path / SPEND_LEDGER_NAME))
    runtime = _runtime(tmp_path)
    try:
        seen: list[tuple[str, bool]] = []
        monkeypatch.setattr(
            runtime,
            "_narrate_mission",
            lambda text, *, critical=False: (seen.append((text, critical)), True)[1],
        )
        whisperer = runtime.realtime_whisperer
        assert whisperer is not None

        from parcel_robot.realtime.whisperer import StateEvent

        # Rejection first: it is min-gap ELIGIBLE, so offering it after the
        # (min-gap exempt) refusal would have it suppressed by the whisperer and
        # never reach the door this test is about.
        runtime._whisper(
            StateEvent(kind=KIND_VOICE_REJECTED, key="voice:1", fact="Someone else asked.")
        )
        runtime._whisper(
            StateEvent(kind=KIND_REFUSAL, key="refusal:1", fact="The robot refused.")
        )
        assert [critical for _, critical in seen] == [False, True]

        # The digest path, which is the one the emergency latch travels. The
        # whisperer's differ needs a BEFORE digest, so the unlatched tick is the
        # baseline and the latched tick is the edge that produces the fact.
        runtime._step_whisperer(None, now=10_000.0)
        seen.clear()
        runtime.arbiter.engage_emergency_stop()
        runtime._step_whisperer(None, now=10_010.0)
        assert seen, "the latch produced no forwarded fact at all"
        assert all(critical for _, critical in seen), seen
        assert any("stop" in text.lower() for text, _ in seen), seen
    finally:
        runtime.close()


def test_the_narration_door_and_the_lane_agree_on_the_critical_keyword() -> None:
    """A signature mismatch here is SILENT, so it gets its own assertion.

    ``_narrate_mission`` wraps its lane call in
    ``except (RuntimeError, TypeError, ValueError)`` — narration is a nicety and
    must never take a mission terminal down. The cost of that catch is that a
    lane whose ``narrate_event`` does not accept ``critical`` raises TypeError
    on EVERY fact and the runtime reports it as "nothing to say": no exception,
    no counter, a robot that has simply gone quiet. Card R25 hit exactly that
    (21 suite failures across five files whose lane doubles had the old
    signature), so the agreement is now pinned rather than discovered.
    """

    import inspect

    lane_kwargs = inspect.signature(RealtimeLane.narrate_event).parameters
    door_kwargs = inspect.signature(RobotRuntime._narrate_mission).parameters
    assert "critical" in lane_kwargs
    assert "critical" in door_kwargs
    assert lane_kwargs["critical"].kind is inspect.Parameter.KEYWORD_ONLY
    assert door_kwargs["critical"].kind is inspect.Parameter.KEYWORD_ONLY
    assert lane_kwargs["critical"].default is False, "off by default keeps R1-R24 behaviour"


def test_the_default_ledger_path_is_beside_the_recordings_and_never_in_evals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Work item 2's placement, asserted rather than described.

    ``resolve_capture_dir`` is the shared resolver, so the ledger inherits its
    evals/ refusal and its resolve-against-the-repo-root rule for free.
    """

    del tmp_path
    monkeypatch.delenv("PARCEL_REALTIME_SPEND_LEDGER", raising=False)
    monkeypatch.delenv("PARCEL_SESSION_EVIDENCE_DIR", raising=False)
    resolved = resolve_spend_ledger_path(resolve_capture_dir("recordings"))
    assert resolved.name == SPEND_LEDGER_NAME
    assert resolved.parent == resolve_capture_dir("recordings")
    assert resolved.is_absolute()
    assert "evals" not in resolved.parts
