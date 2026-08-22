"""Card AIR-1 — the through-air scorecard, and the six ways it could lie.

WHY A SCHEMA GETS A TEST OF ITS OWN
-----------------------------------
The week-3 Go2 purchase decision reads this file. A scorecard is therefore not
a convenience format — it is the artefact a spending decision is made against,
and the interesting failure is not a crash but a card that looks fine and is
not. Five shapes of that:

* thresholds edited after the fact, so a miss reads as a pass;
* a ``verdict`` that does not follow from its own ``value``;
* a ``pass`` with nothing behind it — no file, no capture, no run;
* an ``unmeasured`` that quietly carries a number anyway;
* ``interrupt p50`` claimed as "the median of twenty" from four samples.

``verify_scorecard`` refuses all of them, and each one below is a seeded example
of the lie rather than a paraphrase of the rule.

THE ARM THAT SCORES ITSELF
--------------------------
``score_monologue`` is exercised against a session written by the **product**
tee (``realtime.audio_gateway.SessionAudioCapture``), not by a hand-made
``index.json``: a false-barge-in rate computed from a fixture of my own
imagination would prove only that I can write JSON. The same session is passed
through the product's ``verify_capture_index`` first, so the input to the metric
is a real index by the product's own definition.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parcel_robot.realtime.audio_gateway import SessionAudioCapture, verify_capture_index
from parcel_robot.voice_audio import pcm16_wav

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "bargein_through_air.py"

RATE = 24_000
#: 20 ms of near-silence and 20 ms of speech-level tone, as the owner stream.
QUIET_FRAME = (b"\x05\x00" * 480)
LOUD_FRAME = (b"\x00\x40" * 480)


@pytest.fixture(scope="module")
def air():
    spec = importlib.util.spec_from_file_location("bargein_through_air", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bargein_through_air"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _settle(capture: SessionAudioCapture, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while capture._queue and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)


def _session(tmp_path: Path, *, utterances: int, interrupted: set[int],
             loud_owner: str = "none") -> Path:
    """A real R17 session, written by the product tee.

    ``loud_owner`` places the speech-level owner frames on the wall clock, which
    is the whole point of the two-population check:

    * ``"gap"`` — before any utterance opens, so the frames land in robot-silent
      time and only a person can have made them;
    * ``"playback"`` — inside an open robot segment, which is where the robot's
      own voice coming back through the air lands.
    """

    capture = SessionAudioCapture(
        root=tmp_path / "recordings", session_id="sess_air1", sample_rate_hz=RATE
    )
    capture.start()
    speech = b"\x33\x44" * 960
    if loud_owner == "gap":
        for _ in range(4 * utterances):
            capture.offer_owner(LOUD_FRAME)
        _settle(capture)
    for index in range(1, utterances + 1):
        capture.begin_utterance(index)
        capture.offer_robot(pcm16_wav(speech, sample_rate_hz=RATE))
        capture.offer_owner(LOUD_FRAME if loud_owner == "playback" else QUIET_FRAME)
        if index in interrupted:
            capture.note_interrupt(index)
        _settle(capture)
    capture.close("test")
    return capture.directory


class _Clock:
    """A wall clock the test drives, so a session with real gaps costs no sleep."""

    def __init__(self, start: float = 1_766_000_000.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)


def _barge_in_session(tmp_path: Path, *, gaps: list[float]) -> Path:
    """A real R17 session in which the owner interrupts the robot ``len(gaps)`` times.

    Written by the PRODUCT tee (``SessionAudioCapture``), with its own wall
    clock supplied so the owner stream really does go quiet for longer than
    ``owner_gap_s`` between bursts — which is what cuts a new ``owner_turn``
    segment, which is the only onset evidence that exists on disk.
    """

    clock = _Clock()
    capture = SessionAudioCapture(
        root=tmp_path / "recordings", session_id="sess_bargein",
        sample_rate_hz=RATE, wall_clock=clock,
    )
    capture.start()
    speech = b"\x33\x44" * 960
    # The microphone opens and streams quietly: segment 0, which is a gesture
    # and not an onset.
    capture.offer_owner(QUIET_FRAME)
    clock.advance(0.02)
    capture.offer_owner(QUIET_FRAME)
    _settle(capture)
    for index, gap in enumerate(gaps, start=1):
        clock.advance(2.0)                     # the owner says nothing at all
        capture.begin_utterance(index)
        capture.offer_robot(pcm16_wav(speech, sample_rate_hz=RATE))
        clock.advance(0.5)
        capture.offer_owner(LOUD_FRAME)        # THE ONSET: a new owner segment
        clock.advance(gap)
        capture.note_interrupt(index)          # THE INTERRUPT: interrupted_at
        clock.advance(0.02)
        capture.offer_owner(LOUD_FRAME)        # same burst, no new segment
        _settle(capture)
    capture.close("test")
    return capture.directory


def _good_card(air) -> dict:
    """A complete, honest card: every row measured, every row passing."""

    return {
        "schema": air.SCORECARD_SCHEMA,
        "note": "seeded",
        "rows": [
            air.make_row("erle_db", 23.4, evidence=["erle.json"]),
            air.make_row("robot_utterances_as_owner_turns", 0, n=20, evidence=["turns.jsonl"]),
            air.make_row("interrupt_p50_s", 0.41, n=20, evidence=["events.jsonl"]),
            air.make_row("false_barge_in_rate", 0.0, n=42, evidence=["sess/"]),
            air.make_row("tv_owner_attributed_turns", 0, evidence=["tv.jsonl"]),
            air.make_row("doa_ok_fraction", 0.99, n=100, evidence=["probe.json"]),
            air.make_row("hosted_spend_usd", 1.12, evidence=["spend.jsonl"]),
        ],
    }


# ================================================================= it holds
def test_a_complete_honest_card_verifies(air) -> None:
    card = _good_card(air)
    assert air.verify_scorecard(card) == []
    assert air.summarise_scorecard(card) == {"pass": 7, "fail": 0, "unmeasured": 0}


def test_the_rows_are_exactly_the_cards_pre_registered_acceptance(air) -> None:
    """The seven rows, with the card's own numbers. Change one and change this."""

    assert {row.row_id: (row.direction, row.threshold) for row in air.ROWS} == {
        "erle_db": ("min", 20.0),
        "robot_utterances_as_owner_turns": ("max", 0.0),
        "interrupt_p50_s": ("max", 0.52),
        "false_barge_in_rate": ("max", 0.02),
        "tv_owner_attributed_turns": ("max", 0.0),
        "doa_ok_fraction": ("min", 0.95),
        "hosted_spend_usd": ("max", 2.0),
    }


# ================================================================== it refuses
def test_a_moved_goalpost_is_refused(air) -> None:
    card = _good_card(air)
    card["rows"][0]["threshold"] = 10.0  # "ERLE >= 10 dB was always the gate"
    problems = air.verify_scorecard(card)
    assert any("the goalposts moved" in problem for problem in problems)


def test_a_flipped_direction_is_refused(air) -> None:
    card = _good_card(air)
    card["rows"][3]["direction"] = "min"  # more false barge-ins is now better
    assert any("direction is" in problem for problem in air.verify_scorecard(card))


def test_a_verdict_that_does_not_follow_from_its_value_is_refused(air) -> None:
    card = _good_card(air)
    card["rows"][2]["value"] = 0.98  # nearly a second, still says pass
    problems = air.verify_scorecard(card)
    assert any("interrupt_p50_s" in problem and "'fail'" in problem for problem in problems)


def test_a_pass_with_no_evidence_is_refused(air) -> None:
    card = _good_card(air)
    card["rows"][0]["evidence"] = []
    assert any("cites no evidence" in problem for problem in air.verify_scorecard(card))


def test_an_unmeasured_row_may_not_carry_a_number(air) -> None:
    card = _good_card(air)
    card["rows"][5]["verdict"] = "unmeasured"
    card["rows"][5]["unmeasured_reason"] = "the udev rule was not in"
    problems = air.verify_scorecard(card)
    assert any("carries the value" in problem for problem in problems)


def test_an_unmeasured_row_must_say_what_is_missing(air) -> None:
    card = _good_card(air)
    card["rows"][5].update({"verdict": "unmeasured", "value": None, "unmeasured_reason": "  "})
    assert any("with no reason" in problem for problem in air.verify_scorecard(card))


def test_a_median_of_twenty_needs_twenty_samples(air) -> None:
    card = _good_card(air)
    card["rows"][2]["n"] = 4
    problems = air.verify_scorecard(card)
    assert any("only meaningful at n>=20" in problem for problem in problems)


def test_a_miss_must_name_its_mechanism(air) -> None:
    card = _good_card(air)
    card["rows"][0].update({"value": 11.0, "verdict": "fail", "mechanism": ""})
    assert any("no mechanism" in problem for problem in air.verify_scorecard(card))


def test_a_missing_row_and_an_invented_row_are_both_refused(air) -> None:
    card = _good_card(air)
    dropped = card["rows"].pop(1)
    problems = air.verify_scorecard(card)
    assert any("missing pre-registered row" in problem for problem in problems)

    card["rows"].append(dropped)
    card["rows"].append(dict(dropped))
    assert any("appears 2 times" in problem for problem in air.verify_scorecard(card))

    card = _good_card(air)
    card["rows"].append({"id": "felt_like_a_creature", "verdict": "pass", "value": 5})
    assert any("unknown row id" in problem for problem in air.verify_scorecard(card))


def test_a_card_of_another_schema_is_refused(air) -> None:
    card = _good_card(air)
    card["schema"] = "parcel.air1.scorecard.v2"
    assert any("schema is" in problem for problem in air.verify_scorecard(card))


# ========================================================= the measured arm
def test_false_barge_ins_come_from_a_real_r17_session(air, tmp_path: Path) -> None:
    directory = _session(tmp_path, utterances=10, interrupted={3, 7})
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    assert verify_capture_index(index, session_dir=directory) == []

    scored = air.score_monologue(directory)
    assert scored["utterances"] == 10
    assert scored["interrupted"] == 2
    assert scored["rate"] == pytest.approx(0.2)
    assert scored["owner_silence"]["owner_spoke"] is False
    assert scored["owner_silence"]["echo_in_owner_stream"] is False


def test_speech_in_a_robot_silent_gap_makes_the_arm_unmeasurable(air, tmp_path: Path) -> None:
    """Nothing but a person makes a noise while the robot is not talking.

    An interrupt in that session cannot be attributed to echo, so the arm is
    genuinely unmeasurable — and this is the ONLY case that earns ``unmeasured``.
    """

    directory = _session(tmp_path, utterances=6, interrupted={1}, loud_owner="gap")
    scored = air.score_monologue(directory)
    assert scored["owner_silence"]["owner_spoke"] is True
    assert scored["owner_silence"]["loud_in_robot_silent_gaps"] > 0

    card = air.build_scorecard(monologue=scored, evidence={"capture": str(directory)})
    row = next(entry for entry in card["rows"] if entry["id"] == "false_barge_in_rate")
    assert row["verdict"] == "unmeasured"
    assert "robot-silent gaps" in row["unmeasured_reason"]
    assert air.verify_scorecard(card) == []


def test_echo_during_playback_is_a_fail_and_not_an_absence(air, tmp_path: Path) -> None:
    """The B3 failure this whole card exists to catch must not read as 'unmeasured'.

    Speech-level energy in the owner stream *during* robot playback is the
    robot's own voice arriving uncancelled — a speaker that is not on the
    array's own DAC. The count of self-interrupts is still real, so the value
    stays; the row is a **fail** with that mechanism, because a session whose
    echo path is broken has not passed anything.
    """

    directory = _session(tmp_path, utterances=10, interrupted=set(), loud_owner="playback")
    scored = air.score_monologue(directory)
    assert scored["owner_silence"]["owner_spoke"] is False       # nobody talked
    assert scored["owner_silence"]["echo_in_owner_stream"] is True  # but it was loud anyway
    assert scored["rate"] == 0.0                                 # and nothing self-interrupted

    card = air.build_scorecard(monologue=scored, evidence={"capture": str(directory)})
    row = next(entry for entry in card["rows"] if entry["id"] == "false_barge_in_rate")
    assert row["value"] == 0.0            # the number is kept, not discarded
    assert row["verdict"] == "fail"       # ... and the row still fails
    assert "not on the array's own DAC" in row["mechanism"]
    assert "echo path this arm exists to test is broken" in row["override_reason"]
    assert air.verify_scorecard(card) == []


def test_the_measured_arm_flows_into_the_card(air, tmp_path: Path) -> None:
    directory = _session(tmp_path, utterances=100, interrupted={5})
    card = air.build_scorecard(
        monologue=air.score_monologue(directory), evidence={"capture": str(directory)}
    )
    row = next(entry for entry in card["rows"] if entry["id"] == "false_barge_in_rate")
    assert row["value"] == pytest.approx(0.01)
    assert row["verdict"] == "pass"  # 1 % is inside the 2 % gate
    assert air.verify_scorecard(card) == []


# ==================================================== the row that cannot run
def test_interrupt_latency_is_unmeasured_and_says_why(air) -> None:
    """No evidence at all is still an honest absence, and it names the half.

    Corrected by FINISH-1: MARK-1's ``interrupted_at`` landed, so the reason may
    no longer claim the interrupt is unstamped. It is the ONSET that is missing.
    """

    card = air.build_scorecard()
    row = next(entry for entry in card["rows"] if entry["id"] == "interrupt_p50_s")
    assert row["verdict"] == "unmeasured"
    assert row["value"] is None
    assert "interrupted_at" in row["unmeasured_reason"]
    assert "MARK-1-STAMP is CLOSED" in row["unmeasured_reason"]
    assert air.verify_scorecard(card) == []


def test_latency_is_measured_when_the_events_are_wall_stamped(air) -> None:
    rows = []
    for index, gap in enumerate((0.30, 0.41, 0.55, 0.44)):
        base = 100.0 + index * 10.0
        rows.append({"t": base, "kind": "speech_started"})
        rows.append({"t": base + gap, "kind": "sink.interrupt"})
    scored = air.score_interrupt_latency(rows)

    assert scored["pairs"] == 4
    assert scored["p50_s"] == pytest.approx(0.44)


def test_an_empty_card_is_seven_honest_absences(air) -> None:
    card = air.build_scorecard()
    assert air.verify_scorecard(card) == []
    assert air.summarise_scorecard(card) == {"pass": 0, "fail": 0, "unmeasured": 7}
    assert all(entry["unmeasured_reason"] for entry in card["rows"])


def test_make_row_derives_the_verdict_rather_than_taking_one(air) -> None:
    """There is no way to hand ``make_row`` a verdict; it computes one."""

    assert air.make_row("erle_db", 19.9, evidence=["x"])["verdict"] == "fail"
    assert air.make_row("erle_db", 20.0, evidence=["x"])["verdict"] == "pass"
    assert air.make_row("false_barge_in_rate", 0.02, n=1, evidence=["x"])["verdict"] == "pass"
    assert air.make_row("false_barge_in_rate", 0.021, n=1, evidence=["x"])["verdict"] == "fail"


def test_deepcopy_of_a_good_card_still_verifies(air) -> None:
    """Guards against a verifier that accidentally mutates what it inspects."""

    card = _good_card(air)
    before = copy.deepcopy(card)
    assert air.verify_scorecard(card) == []
    assert card == before


# ========================= the ERLE number the card refuses to launder
def test_an_erle_report_that_could_not_be_measured_does_not_become_a_pass(air) -> None:
    """Two legs at different loudness produce a subtraction, not a measurement.

    ``measure_erle.build_report`` already refuses to call that a pass. The
    scorecard must not undo the refusal by reading ``erle_db`` and grading it.
    """

    untrustworthy = {
        "schema": "parcel.air1.erle_report.v1",
        "asr_beam_echo_attenuation_db": 25.0,
        "erle_db": 25.0,
        "verdict": "unmeasured",
        "problems": ["the reference microphone heard the two legs +6.0 dB apart"],
    }
    card = air.build_scorecard(erle=untrustworthy, evidence={"erle": "erle.json"})
    row = next(entry for entry in card["rows"] if entry["id"] == "erle_db")

    assert row["verdict"] == "unmeasured"
    assert row["value"] is None
    assert "6.0 dB apart" in row["unmeasured_reason"]
    assert air.verify_scorecard(card) == []


def test_a_measured_erle_miss_lands_as_a_miss_with_its_mechanism(air) -> None:
    """A miss is a miss. It is a row, not an absence."""

    missed = {
        "schema": "parcel.air1.erle_report.v1",
        "asr_beam_echo_attenuation_db": 11.2,
        "erle_db": 11.2,
        "verdict": "fail",
        "problems": ["11.2 dB is below the 20.0 dB gate; a clipped amplifier"],
    }
    card = air.build_scorecard(erle=missed, evidence={"erle": "erle.json"})
    row = next(entry for entry in card["rows"] if entry["id"] == "erle_db")

    assert row["verdict"] == "fail"
    assert row["value"] == pytest.approx(11.2)
    assert "clipped amplifier" in row["mechanism"]
    assert air.verify_scorecard(card) == []


# ====================================================== the spend-ledger join
def test_zero_matched_ledger_rows_is_not_a_zero_dollar_pass(air) -> None:
    """The vacuous pass this row used to hand out.

    The spend ledger is keyed by the PROVIDER's ``rt_`` session; the capture tee
    names folders with its own ``sess_`` id. Matching one against the other
    selects nothing, and nothing summed is ``$0.00`` — which sailed through a
    ``<= $2`` gate for a session that may have cost real money.
    """

    ledger = [
        {"schema": "parcel.realtime_spend.v1", "wall": "2026-08-22T09:14:02Z",
         "session_id": "rt_ab12cd34ef56", "estimated_usd": 0.94},
        {"schema": "parcel.realtime_spend.v1", "wall": "2026-08-22T09:16:40Z",
         "session_id": "rt_ab12cd34ef56", "estimated_usd": 0.31},
    ]

    missed = air.score_spend(ledger, session_ids=["sess_air1"])
    assert missed["usd"] == 0.0
    assert missed["matched"] is False
    assert missed["rows_skipped"] == 2

    card = air.build_scorecard(spend=missed, evidence={"spend": "spend.jsonl"})
    row = next(entry for entry in card["rows"] if entry["id"] == "hosted_spend_usd")
    assert row["verdict"] == "unmeasured"
    assert row["value"] is None
    assert "not $0.00" in row["unmeasured_reason"]
    assert air.verify_scorecard(card) == []


def test_the_provider_session_id_makes_the_join_work(air) -> None:
    ledger = [
        {"wall": "2026-08-22T09:14:02Z", "session_id": "rt_ab12", "estimated_usd": 0.94},
        {"wall": "2026-08-22T09:16:40Z", "session_id": "rt_ab12", "estimated_usd": 0.31},
        {"wall": "2026-08-22T11:00:00Z", "session_id": "rt_other", "estimated_usd": 9.99},
    ]
    scored = air.score_spend(ledger, session_ids=["rt_ab12"])

    assert scored["matched"] is True
    assert scored["usd"] == pytest.approx(1.25)
    assert scored["rows"] == 2

    card = air.build_scorecard(spend=scored, evidence={"spend": "spend.jsonl"})
    row = next(entry for entry in card["rows"] if entry["id"] == "hosted_spend_usd")
    assert row["verdict"] == "pass"
    assert air.verify_scorecard(card) == []


def test_the_capture_wall_window_is_the_other_join(air, tmp_path: Path) -> None:
    """No provider id to hand? The capture's own wall span selects the rows."""

    directory = _session(tmp_path, utterances=3, interrupted=set())
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    window = air.capture_wall_window(index)
    assert window is not None

    inside = datetime.fromtimestamp(window[0] + 1.0, tz=timezone.utc)
    outside = datetime.fromtimestamp(window[0] - 3600.0, tz=timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    ledger = [
        {"wall": inside.strftime(fmt), "session_id": "rt_x", "estimated_usd": 0.50},
        {"wall": outside.strftime(fmt), "session_id": "rt_y", "estimated_usd": 7.00},
    ]
    scored = air.score_spend(ledger, window=window)

    assert scored["matched"] is True
    assert scored["usd"] == pytest.approx(0.50)


def test_the_provider_session_id_is_recovered_from_the_evidence_log(air) -> None:
    rows = [
        {"seq": 1, "stream": "marker", "wall": "2026-08-22T09:13:00Z", "kind": "log_opened"},
        {"seq": 2, "stream": "event", "wall": "2026-08-22T09:14:02Z", "kind": "retained_event",
         "type": "conversation.item.truncated", "session_id": "rt_ab12cd34ef56",
         "fields": {"audio_end_ms": 1200}},
    ]
    assert air.event_session_ids(rows) == ["rt_ab12cd34ef56"]


# ============================================ the override, and its one direction
def test_a_row_may_be_called_worse_than_its_number_but_never_better(air) -> None:
    card = _good_card(air)

    # Worse, with a reason: legal.
    card["rows"][3].update({
        "verdict": "fail",
        "mechanism": "speech-level energy in the owner stream during playback",
        "override_reason": "the echo path this arm exists to test is broken",
    })
    assert air.verify_scorecard(card) == []

    # Worse, with no reason: refused.
    card["rows"][3]["override_reason"] = ""
    assert any("no override_reason" in problem for problem in air.verify_scorecard(card))

    # Better than the number says: refused, reason or no reason.
    card = _good_card(air)
    card["rows"][0].update({
        "value": 11.0, "verdict": "pass",
        "override_reason": "it felt fine on the day",
    })
    problems = air.verify_scorecard(card)
    assert any("'fail'" in problem for problem in problems)


def test_a_mechanism_on_a_passing_row_is_refused(air) -> None:
    """Otherwise 'a miss must name its mechanism' is satisfiable by a builder
    that fills the field unconditionally, and the check proves nothing."""

    card = _good_card(air)
    card["rows"][3]["mechanism"] = "residual echo above the barge-in threshold"
    assert any("mechanisms explain misses" in p for p in air.verify_scorecard(card))


# ======================================== an ERLE report has to BE an ERLE report
def test_a_mapping_that_is_not_an_erle_report_is_not_evidence(air) -> None:
    """The deny-list bug: anything without the literal word 'unmeasured' passed."""

    for bogus in ({}, {"erle_db": 25.0}, {"schema": "something.else", "verdict": "pass"}):
        card = air.build_scorecard(erle=bogus, evidence={"erle": "erle.json"})
        row = next(entry for entry in card["rows"] if entry["id"] == "erle_db")
        assert row["verdict"] == "unmeasured", bogus
        assert row["value"] is None, bogus
        assert air.verify_scorecard(card) == []


def test_a_report_from_a_different_schema_is_refused_even_when_it_looks_perfect(air) -> None:
    """Isolates the schema check itself.

    This mapping has a legal verdict and a numeric attenuation, so every OTHER
    check in the validator waves it through. Only the schema comparison catches
    it — which is the point: a v2 report may mean something different by the
    same field names, and the gate reads this number to decide on a purchase.
    """

    card = air.build_scorecard(
        erle={"schema": "parcel.air1.erle_report.v2", "verdict": "pass",
              "asr_beam_echo_attenuation_db": 30.0, "erle_db": 30.0},
        evidence={"erle": "erle.json"},
    )
    row = next(entry for entry in card["rows"] if entry["id"] == "erle_db")
    assert row["verdict"] == "unmeasured"
    assert row["value"] is None
    assert "erle_report.v2" in row["unmeasured_reason"]
    assert air.verify_scorecard(card) == []


def test_an_erle_report_with_a_nonsense_verdict_is_refused(air) -> None:
    card = air.build_scorecard(
        erle={"schema": "parcel.air1.erle_report.v1", "verdict": "probably fine",
              "asr_beam_echo_attenuation_db": 30.0},
        evidence={"erle": "erle.json"},
    )
    row = next(entry for entry in card["rows"] if entry["id"] == "erle_db")
    assert row["verdict"] == "unmeasured"
    assert "probably fine" in row["unmeasured_reason"]


def test_the_renamed_attenuation_field_is_what_is_read(air) -> None:
    """``erle_db`` is an alias; the primary name is what the report leads with."""

    card = air.build_scorecard(
        erle={"schema": "parcel.air1.erle_report.v1", "verdict": "pass",
              "asr_beam_echo_attenuation_db": 24.0},
        evidence={"erle": "erle.json"},
    )
    row = next(entry for entry in card["rows"] if entry["id"] == "erle_db")
    assert row["value"] == pytest.approx(24.0)
    assert row["verdict"] == "pass"


# ============================== the two rows nothing in this tree can produce
def test_the_turn_rows_name_the_tool_that_does_not_exist(air) -> None:
    """No silent 'unmeasured'. The row says WHICH producer is missing and why."""

    card = air.build_scorecard()
    for row_id in ("robot_utterances_as_owner_turns", "tv_owner_attributed_turns"):
        row = next(entry for entry in card["rows"] if entry["id"] == row_id)
        assert row["verdict"] == "unmeasured"
        assert "OWNER-GATED ON A TOOL THAT DOES NOT EXIST YET" in row["unmeasured_reason"]
        assert "speaker_label_rows" in row["unmeasured_reason"]
        assert "RT-TURNS-1" in row["unmeasured_reason"]


def test_latency_names_the_one_missing_half_and_no_longer_the_closed_one(air) -> None:
    """FINISH-1 replaced ``test_latency_names_both_missing_halves_not_one``.

    ``interrupted_at`` is on disk now, so exactly one half is missing and the
    row has to say which one — and must not go on blaming ``mark_interrupted``
    for dropping a stamp it writes.
    """

    card = air.build_scorecard()
    row = next(entry for entry in card["rows"] if entry["id"] == "interrupt_p50_s")
    reason = row["unmeasured_reason"]
    assert "interrupted_at" in reason
    assert "MARK-1-STAMP is CLOSED" in reason
    assert "speech_started" in reason
    assert "TURN-1-ONSET" in reason
    assert "drops the wall stamp" not in reason


# ================== the seam MARK-1 opened: the tee times its own barge-in
def test_the_tee_alone_yields_an_interrupt_median(air, tmp_path: Path) -> None:
    """SEED E1. Stop reading ``interrupted_at`` in ``capture_latency_events``
    (or drop the field from the index) and this median disappears.

    A real product-tee session: the owner stream goes quiet between bursts, so
    each burst opens a new ``owner_turn`` segment, and every robot segment
    carries MARK-1's wall stamp. No ``--events`` file is involved.
    """

    directory = _barge_in_session(tmp_path, gaps=[0.30, 0.41, 0.55, 0.44])
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    assert verify_capture_index(index, session_dir=directory) == []

    events = air.capture_latency_events(index)
    kinds = [entry["kind"] for entry in events]
    assert kinds.count(air.CAPTURE_INTERRUPT_KIND) == 4
    assert kinds.count(air.CAPTURE_ONSET_KIND) == 4, "the first owner segment is not an onset"
    assert all(
        entry.get("interrupted_byte") is not None and entry.get("interrupted_t_s") is not None
        for entry in events
        if entry["kind"] == air.CAPTURE_INTERRUPT_KIND
    )

    scored = air.score_interrupt_latency(capture_events=events)
    assert scored["pairs"] == 4
    assert scored["p50_s"] == pytest.approx(0.44, abs=0.02)
    assert scored["interrupts_stamped_by_the_tee"] == 4
    assert scored["onset_is_an_estimate"] is True
    assert scored["positions_into_reply_s"], "interrupted_t_s rides along as a POSITION"


def test_a_capture_without_the_stamp_is_unmeasured_not_zero(air, tmp_path: Path) -> None:
    """The other half of seed E1: absent ``interrupted_at`` ⇒ no median at all."""

    directory = _barge_in_session(tmp_path, gaps=[0.30, 0.41, 0.55, 0.44])
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    for segment in index["streams"]["robot"]["segments"]:
        segment.pop("interrupted_at", None)
        segment.pop("interrupted_byte", None)
        segment.pop("interrupted_t_s", None)

    events = air.capture_latency_events(index)
    assert not [entry for entry in events if entry["kind"] == air.CAPTURE_INTERRUPT_KIND]
    scored = air.score_interrupt_latency(capture_events=events)
    assert scored["p50_s"] is None
    assert scored["interrupts"] == 0
    assert scored["onsets"] == 4

    card = air.build_scorecard(latency=scored, evidence={"capture": str(directory)})
    row = next(entry for entry in card["rows"] if entry["id"] == "interrupt_p50_s")
    assert row["verdict"] == "unmeasured"
    assert row["value"] is None
    assert air.verify_scorecard(card) == []


def test_one_interrupt_seen_by_two_witnesses_is_one_interrupt(air) -> None:
    """The tee's stamp and the provider's echo of the same truncate."""

    capture_events = [
        {"t": 100.4, "kind": air.CAPTURE_INTERRUPT_KIND},
        {"t": 110.4, "kind": air.CAPTURE_INTERRUPT_KIND},
    ]
    rows = [
        {"t": 100.0, "kind": "speech_started"},
        {"t": 100.6, "kind": "conversation.item.truncated"},
        {"t": 110.0, "kind": "speech_started"},
        {"t": 110.6, "kind": "conversation.item.truncated"},
    ]
    scored = air.score_interrupt_latency(rows, capture_events=capture_events)

    assert scored["interrupts"] == 2, "not four"
    assert scored["pairs"] == 2
    # The tee's own stamp is the one that survives, so the median is 0.4 s and
    # not the provider echo's 0.6 s.
    assert scored["p50_s"] == pytest.approx(0.4)


def test_a_truncate_far_from_any_stamp_is_a_second_interrupt(air) -> None:
    """The de-duplication is a window, not a blanket. Out of it, both count."""

    scored = air.score_interrupt_latency(
        [{"t": 200.0, "kind": "speech_started"},
         {"t": 260.0, "kind": "conversation.item.truncated"}],
        capture_events=[{"t": 100.4, "kind": air.CAPTURE_INTERRUPT_KIND}],
    )
    assert scored["interrupts"] == 2


def test_an_evidence_log_with_truncates_and_no_onsets_yields_no_median(air) -> None:
    rows = [
        {"stream": "event", "wall": "2026-08-22T09:14:02Z", "kind": "retained_event",
         "type": "conversation.item.truncated", "session_id": "rt_a", "fields": {}},
        {"stream": "event", "wall": "2026-08-22T09:14:09Z", "kind": "retained_event",
         "type": "conversation.item.truncated", "session_id": "rt_a", "fields": {}},
    ]
    scored = air.score_interrupt_latency(rows)

    assert scored["interrupts"] == 2
    assert scored["onsets"] == 0
    assert scored["p50_s"] is None
    # FINISH-1: the sentence moved with the seam. The interrupt half is stamped
    # now; what this log is missing is the ONSET, and the reason has to say so.
    assert "no burst boundary" in scored["unpaired_reason"]
    assert "the onset is the half that is missing" in scored["unpaired_reason"]
