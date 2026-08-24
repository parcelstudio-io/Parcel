"""A7 — the ear that gates before the wire, and the envelope that stops it.

Card: ``scrum/20260824/task_2/IMPLEMENTATION_PLAN.md`` lane A row A7, bound to
three measured records:

* **H1** (``research/20260823/ambient-ear-cost-ladder/``) — the published rate
  card, the +335.8 % over-charge the old ledger applied on 34 live responses,
  the 960.6 VAD opens/hour on ambient speech, and 0 % first-word truncation at
  >= 500 ms of pre-roll.
* **EVENT-BUDGET** (``research/20260824/event-driven-companion-budget/``) —
  $30.72/month p95 nominal against $572.36 ungated and $777.60 on a 1 Hz tick,
  and the ``HostedCallGovernor`` the verdict says is missing.
* **VOICE-GATE v2** (``research/20260824/voice-gate/``) — push-to-talk ships for
  M1; ``voice_identity.DEFAULT_THRESHOLD`` = 0.55 admits the owner 16.7 % of the
  time through a room, while 0.352 buys 0.95 recall at 0.000 impostor
  acceptance with EER 0.000 at >= 2 s.

**No hosted call is made anywhere in this file.** Every dollar row is computed
from ``tests/data/a7_live_usage.jsonl`` — the 34 usage blocks of the 2026-08-23
live run, verbatim, with the study's own per-row prices carried alongside so a
drift in either direction reddens.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parcel_robot.realtime.cost import MINI_RATE_CARD, RATE_CARD_AS_OF, realtime_spend_usd
from parcel_robot.realtime.ear_gate import (
    CODE_ADMITTED_IDENTITY,
    CODE_ADMITTED_PTT,
    CODE_BUDGET_REFUSED,
    CODE_NOT_OWNER,
    MEASURED_IDENTITY_THRESHOLD,
    MEASURED_MIN_SPEECH_S,
    MEASURED_PRE_ROLL_MS,
    EarGate,
    EarGateConfig,
    enrollment_channel_matches,
)
from parcel_robot.realtime.hosted_budget import (
    CLASS_CRITICAL,
    CODE_ADMITTED,
    CODE_DAY_CAP_REACHED,
    CODE_ENVELOPE_REACHED,
    CODE_LEDGER_UNKNOWN,
    CODE_NEVER_GOVERNED,
    DEFAULT_ENVELOPE_USD,
    DEFAULT_RESERVE_USD,
    DEFAULT_WARN_USD,
    GovernorConfig,
    HostedCallGovernor,
    HostedCallRefused,
)
from parcel_robot.realtime.protocol import (
    TURN_DETECTION_SERVER_VAD,
    SessionUpdate,
    TurnDetection,
)
from parcel_robot.realtime.spend_ledger import (
    SPEND_LEDGER_SCHEMA_V2,
    SpendLedger,
    day_key,
)
from parcel_robot.voice.engagement import TIER_HEAR_ONLY, triage

REPO = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "data" / "a7_live_usage.jsonl"
CORPUS = REPO / "evals" / "companion" / "realtime_convo_v1" / "fixtures"

#: The study's own totals over the same 34 responses
#: (``results/live_calibration.json``). Both are pinned so a change to either
#: side of the comparison is visible rather than absorbed.
LIVE_ASSUMED_TOTAL_USD = 0.09035
LIVE_PUBLISHED_TOTAL_USD = 0.020734
LIVE_OVERCHARGE_PCT = 335.751

#: H1's modelled median audio turn and its measured ambient open rate. The two
#: numbers that turn "the gate is missing" into a dollar figure.
H1_MEDIAN_AUDIO_TURN_USD = 0.004371
H1_TV_OPENS_PER_HOUR = 960.6

PCM_BYTES_PER_SECOND = 24_000 * 2


def _rows() -> list[dict]:
    with FIXTURE.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _frames(seconds: float, *, frame_ms: float = 20.0, fill: bytes = b"\x01\x02") -> list[bytes]:
    """PCM16 @ 24 kHz cut into ``frame_ms`` frames. Content is irrelevant here."""

    per_frame = int(PCM_BYTES_PER_SECOND * frame_ms / 1000.0)
    count = max(1, round(seconds * 1000.0 / frame_ms))
    block = (fill * (per_frame // len(fill) + 1))[:per_frame]
    return [block for _ in range(count)]


def _source(name: str) -> str:
    return (REPO / "src" / "parcel_robot" / name).read_text(encoding="utf-8")


def _function(module_source: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(module_source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _calls(node: ast.AST) -> list[str]:
    """Dotted attribute names of every call in source order."""

    found: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if isinstance(target, ast.Attribute):
            found.append((target.lineno, target.attr))
        elif isinstance(target, ast.Name):
            found.append((target.lineno, target.id))
    return [name for _, name in sorted(found)]


# ============================================ 1. the measured rate card, wired
def test_the_shipped_card_carries_the_measured_prices() -> None:
    """H1's rate card, six numbers, read off the pricing page by hand."""

    assert MINI_RATE_CARD.model == "gpt-realtime-2.1-mini"
    assert MINI_RATE_CARD.as_of == RATE_CARD_AS_OF == "2026-08-23"
    assert MINI_RATE_CARD.audio_input_usd_per_mtok == 10.00
    assert MINI_RATE_CARD.audio_cached_input_usd_per_mtok == 0.30
    assert MINI_RATE_CARD.audio_output_usd_per_mtok == 20.00
    assert MINI_RATE_CARD.text_input_usd_per_mtok == 0.60
    assert MINI_RATE_CARD.text_cached_input_usd_per_mtok == 0.06
    assert MINI_RATE_CARD.text_output_usd_per_mtok == 2.40


def test_the_recorded_run_reprices_from_plus_336_percent_to_the_published_total() -> None:
    """34 recorded responses, both arithmetics, no socket. H1's C9/C10."""

    rows = _rows()
    assert len(rows) == 34

    assumed = sum(realtime_spend_usd([row["flat_row"]]) for row in rows)
    published = sum(MINI_RATE_CARD.priced_usd(row["flat_row"]) for row in rows)

    assert assumed == pytest.approx(LIVE_ASSUMED_TOTAL_USD, rel=1e-4)
    assert published == pytest.approx(LIVE_PUBLISHED_TOTAL_USD, rel=1e-4)
    overcharge = (assumed - published) / published * 100.0
    assert overcharge == pytest.approx(LIVE_OVERCHARGE_PCT, rel=1e-3)

    # And the error is not a constant, which is why no fudge factor could have
    # fixed it: per-row ratios span text-heavy and audio-heavy turns.
    ratios = [
        realtime_spend_usd([row["flat_row"]]) / MINI_RATE_CARD.priced_usd(row["flat_row"])
        for row in rows
        if MINI_RATE_CARD.priced_usd(row["flat_row"]) > 0.0
    ]
    assert max(ratios) / min(ratios) > 3.0


def test_each_recorded_row_prices_exactly_as_the_study_recorded_it() -> None:
    """Row-by-row, against the study's own per-row dollars. No aggregate hiding."""

    for row in _rows():
        priced = MINI_RATE_CARD.price(row["flat_row"])
        assert priced.usd == pytest.approx(row["usd_ledger_flat"], abs=5e-9), row["response_id"]
        assert priced.basis == row["usd_ledger_basis"]
        raw = MINI_RATE_CARD.price(row["raw_usage"])
        assert raw.usd == pytest.approx(row["usd_raw_split"], abs=5e-9), row["response_id"]


def test_every_hosted_call_lands_one_itemized_ledger_row(tmp_path: Path) -> None:
    """Card A7 item 1: modality, tokens and dollars on EVERY row, not a total."""

    ledger = SpendLedger(tmp_path / "spend.jsonl", cache_ttl_s=0.0, rate_card=MINI_RATE_CARD)
    rows = _rows()
    for row in rows:
        assert ledger.record(row["flat_row"], session_id="a7") is True

    written = [
        json.loads(line)
        for line in (tmp_path / "spend.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(written) == len(rows)
    for entry, row in zip(written, rows, strict=True):
        assert entry["schema"] == SPEND_LEDGER_SCHEMA_V2
        assert entry["rates_are_assumed"] is False
        assert entry["rate_card_model"] == "gpt-realtime-2.1-mini"
        assert entry["rate_card_as_of"] == RATE_CARD_AS_OF
        assert entry["pricing_basis"] == row["usd_ledger_basis"]
        assert set(entry["split_tokens"]) == {
            "audio_in",
            "audio_cached_in",
            "audio_out",
            "text_in",
            "text_cached_in",
            "text_out",
        }
        assert entry["estimated_usd"] == pytest.approx(row["usd_ledger_flat"], abs=5e-9)

    total = ledger.month_to_date(force=True)
    assert total.readable is True
    assert total.rows == len(rows)
    assert total.usd == pytest.approx(LIVE_PUBLISHED_TOTAL_USD, rel=1e-4)
    assert total.rates_are_assumed is False


def test_the_runtime_resolves_the_card_from_the_model_it_opens() -> None:
    """The wiring H1's verdict named: `runtime.py` built the ledger with none."""

    from parcel_robot.runtime import RobotRuntime

    class _Stub:
        def __init__(self, model: str) -> None:
            self.realtime_config = type("C", (), {"model": model})()
            self.notes: list[str] = []

        def _emit(self, *args: object) -> None:
            self.notes.append(" ".join(str(a) for a in args))

    known = _Stub("gpt-realtime-2.1-mini")
    assert RobotRuntime._realtime_rate_card(known) is MINI_RATE_CARD
    assert known.notes == []

    unknown = _Stub("some-model-nobody-priced")
    assert RobotRuntime._realtime_rate_card(unknown) is None
    assert any("ASSUMED" in note for note in unknown.notes), (
        "an unpriced model must SAY the rows are assumed, not quietly guess upward"
    )


def test_the_ledger_constructor_is_handed_the_card(tmp_path: Path) -> None:
    """Structural: the one keyword the H1 verdict asked for is on the call."""

    call = None
    for node in ast.walk(ast.parse(_source("runtime.py"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "SpendLedger"
        ):
            call = node
    assert call is not None, "runtime.py no longer constructs a SpendLedger"
    keywords = {kw.arg for kw in call.keywords}
    assert "rate_card" in keywords, (
        "runtime.py builds the SpendLedger WITHOUT a rate card again — every row "
        "it writes would be priced at the full model's text rates (+336 %)"
    )


def test_the_day_burn_is_read_from_the_same_durable_file(tmp_path: Path) -> None:
    """EVENT-BUDGET asks for per-day pacing; a restart may not forget it."""

    path = tmp_path / "spend.jsonl"
    today = day_key(datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc))
    lines = [
        {"wall": "2026-08-23T23:59:00Z", "month": "2026-08", "estimated_usd": 5.0},
        {"wall": "2026-08-24T00:01:00Z", "month": "2026-08", "estimated_usd": 1.5},
        {"wall": "2026-08-24T23:59:00Z", "month": "2026-08", "estimated_usd": 2.5},
        {"wall": "not-a-date", "month": "2026-08", "estimated_usd": 99.0},
    ]
    path.write_text("\n".join(json.dumps(row) for row in lines) + "\n", encoding="utf-8")
    ledger = SpendLedger(path, cache_ttl_s=0.0)

    day = ledger.day_to_date(day=today)
    assert day.readable is True
    assert day.rows == 2
    assert day.usd == pytest.approx(4.0)
    # A different process, a fresh object: the burn survives, because it is on
    # disk and not in a counter.
    assert SpendLedger(path, cache_ttl_s=0.0).day_to_date(day=today).usd == pytest.approx(4.0)
    # And the month still totals everything, unchanged by this card.
    assert ledger.month_to_date(force=True).usd == pytest.approx(108.0)


# ================================= 2. the identity gate, BEFORE a byte goes up
def _gate(**overrides: object) -> EarGate:
    verify = overrides.pop("verify", None)
    config = EarGateConfig(**overrides)  # type: ignore[arg-type]
    return EarGate(config=config, verify=verify)


def test_no_byte_leaves_the_host_until_the_local_gate_admits() -> None:
    """Codex freeze finding 3, as a property of the code rather than a promise."""

    gate = _gate(verify=lambda _payload: 0.90)
    gate.press()

    uploaded: list[bytes] = []
    seconds = 0.0
    for frame in _frames(3.0):
        out = gate.offer_frame(frame)
        if not uploaded:
            seconds += len(frame) / PCM_BYTES_PER_SECOND
        uploaded.append(out)

    first = next(index for index, payload in enumerate(uploaded) if payload)
    # Nothing at all before the verdict, and the verdict cannot arrive before
    # the 2 s VOICE-GATE says the model needs.
    assert all(payload == b"" for payload in uploaded[:first])
    assert gate.admission.speech_s >= MEASURED_MIN_SPEECH_S
    assert gate.admission.code == CODE_ADMITTED_IDENTITY
    assert gate.admission.score == pytest.approx(0.90)


def test_a_voice_below_the_operating_point_uploads_zero_bytes() -> None:
    """The whole card in one row: refused identity, zero hosted bytes, erased."""

    gate = _gate(verify=lambda _payload: 0.20)
    gate.press()
    uploaded = [gate.offer_frame(frame) for frame in _frames(6.0)]

    assert gate.bytes_uploaded == 0
    assert all(payload == b"" for payload in uploaded)
    assert gate.admission.admitted is False
    assert gate.admission.code == CODE_NOT_OWNER
    assert gate.bytes_erased > 0, "a refused turn's buffer must be erased, not kept"
    assert "0.200" in gate.admission.reason and "0.352" in gate.admission.reason


def test_the_upload_call_is_spied_through_the_runtime_hop() -> None:
    """The product caller, not the unit: `_realtime_owner_audio` -> `send_audio`."""

    from parcel_robot.runtime import RobotRuntime

    class _Lane:
        active = True

        def __init__(self) -> None:
            self.sent: list[bytes] = []

        def send_audio(self, pcm: bytes) -> None:
            self.sent.append(pcm)

    class _Stub:
        def __init__(self, score: float) -> None:
            self.realtime_lane = _Lane()
            self.realtime_ear = EarGate(config=EarGateConfig(), verify=lambda _p: score)
            self.realtime_ear.press()

        def _emit(self, *args: object) -> None:
            pass

    stranger = _Stub(0.20)
    for frame in _frames(6.0):
        RobotRuntime._realtime_owner_audio(stranger, frame)
    assert stranger.realtime_lane.sent == [], (
        "a refused voice reached lane.send_audio: the gate is not in the hop"
    )

    owner = _Stub(0.90)
    for frame in _frames(6.0):
        RobotRuntime._realtime_owner_audio(owner, frame)
    assert owner.realtime_lane.sent, "the owner's own voice was never relayed"
    assert sum(len(chunk) for chunk in owner.realtime_lane.sent) == owner.realtime_ear.bytes_uploaded


def test_the_gate_stands_between_the_frame_and_the_wire_structurally() -> None:
    """AST: `offer_frame` is called BEFORE `send_audio`, on the only such hop."""

    source = _source("runtime.py")
    hop = _function(source, "_realtime_owner_audio")
    names = _calls(hop)
    assert "offer_frame" in names and "send_audio" in names
    assert names.index("offer_frame") < names.index("send_audio")

    tree = ast.parse(source)
    senders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "send_audio"
    ]
    assert len(senders) == 1, (
        f"runtime.py has {len(senders)} calls to send_audio; a second one would be "
        "a second route to the wire that this gate does not stand in"
    )


def test_the_operating_point_is_the_one_voice_gate_measured() -> None:
    """0.352, not 0.55 — and the difference is the owner being heard at all."""

    assert MEASURED_IDENTITY_THRESHOLD == 0.352
    assert MEASURED_MIN_SPEECH_S == 2.0
    assert EarGateConfig().identity_threshold == MEASURED_IDENTITY_THRESHOLD

    # VOICE-GATE F1's headline pair: the owner's own p50 through this room.
    room_p50 = 0.47
    admitted = _gate(verify=lambda _p: room_p50)
    admitted.press()
    for frame in _frames(3.0):
        admitted.offer_frame(frame)
    assert admitted.admission.admitted is True

    shipped_0_55 = _gate(identity_threshold=0.55, verify=lambda _p: room_p50)
    shipped_0_55.press()
    for frame in _frames(3.0):
        shipped_0_55.offer_frame(frame)
    assert shipped_0_55.admission.admitted is False
    assert shipped_0_55.bytes_uploaded == 0


def test_channel_matched_enrollment_is_a_precondition_not_advice() -> None:
    """A studio gallery scored against a room is not identity (VOICE-GATE F1)."""

    assert enrollment_channel_matches("xvf3800 living room, 2026-08-24", "xvf3800") is True
    assert enrollment_channel_matches("laptop mic, quiet booth", "xvf3800") is False
    # Unstated is not a match: the operator has not said, so nothing is claimed.
    assert enrollment_channel_matches("xvf3800", "") is False


def test_an_unverifiable_host_falls_back_to_push_to_talk_and_says_so() -> None:
    """This host's real state: no enrolled owner audio exists anywhere on it."""

    gate = _gate()  # no verifier
    assert gate.identity_available is False
    gate.press()
    uploaded = [gate.offer_frame(frame) for frame in _frames(1.0)]
    assert any(payload for payload in uploaded)
    assert gate.admission.code == CODE_ADMITTED_PTT
    assert "push-to-talk" in gate.admission.reason


def test_ambient_admission_is_off_and_a_frame_without_a_press_never_goes_up() -> None:
    """VOICE-GATE decided PTT for M1; the ambient arm has no evidence behind it."""

    assert EarGateConfig().ambient is False
    gate = _gate()
    uploaded = [gate.offer_frame(frame) for frame in _frames(5.0)]
    assert all(payload == b"" for payload in uploaded)
    assert gate.bytes_uploaded == 0
    # Even with the knob on: a press is still what admits. The knob exists so
    # the decision is visible, not so an unmeasured arm can be switched on.
    loud = _gate(ambient=True)
    assert all(loud.offer_frame(frame) == b"" for frame in _frames(5.0))
    assert loud.bytes_uploaded == 0


# ==================================================== 3. the pre-roll, measured
def test_every_admitted_turn_carries_at_least_500ms_of_pre_roll() -> None:
    """H1 C3: 0 % first-word truncation at >= 500 ms, non-zero below it."""

    assert MEASURED_PRE_ROLL_MS == 500.0
    assert EarGateConfig().pre_roll_s == 0.5

    for verify in (None, lambda _p: 0.90):
        gate = _gate(verify=verify)
        gate.press()
        for frame in _frames(4.0):
            gate.offer_frame(frame)
        assert gate.admission.admitted is True
        assert gate.admission.pre_roll_s >= 0.5, (
            f"{gate.admission.code} admitted with only "
            f"{gate.admission.pre_roll_s * 1000:.0f} ms of pre-roll"
        )


def test_nothing_goes_up_before_the_pre_roll_is_in_hand() -> None:
    """The bar is a precondition of the FIRST upload, not a statistic after it."""

    gate = _gate()
    gate.press()
    sent = 0.0
    for frame in _frames(0.48):  # 480 ms — one frame short of the bar
        assert gate.offer_frame(frame) == b""
        sent += len(frame) / PCM_BYTES_PER_SECOND
    assert gate.bytes_uploaded == 0
    flushed = b"".join(gate.offer_frame(frame) for frame in _frames(0.04))
    assert len(flushed) / PCM_BYTES_PER_SECOND >= 0.5


def test_a_released_button_uploads_nothing_it_had_not_admitted() -> None:
    """A 300 ms tap is not a turn, and its audio does not become one later."""

    gate = _gate()
    gate.press()
    for frame in _frames(0.30):
        gate.offer_frame(frame)
    gate.release()
    assert gate.bytes_uploaded == 0
    assert all(gate.offer_frame(frame) == b"" for frame in _frames(1.0))
    assert gate.bytes_uploaded == 0


def test_the_shared_turn_state_is_held_under_one_leaf_lock() -> None:
    """`offer_frame` is the socket reader's thread; `press`/`release` are not.

    Structural rather than timing-based: a race this small would not reproduce
    reliably, and the property that matters is that every door onto the shared
    turn buffer takes the lock.
    """

    import threading

    source = (REPO / "src" / "parcel_robot" / "realtime" / "ear_gate.py").read_text()
    for name in ("offer_frame", "press", "release", "note_owner_turn", "note_addressed"):
        body = ast.unparse(_function(source, name))
        assert "self._lock" in body, f"EarGate.{name} touches shared state unlocked"

    gate = _gate()
    assert isinstance(gate._lock, type(threading.RLock()))

    # And it is a LEAF: the governor's file read happens before the lock is
    # taken, so a slow disk cannot stall the frame relay.
    snap = ast.unparse(_function(source, "snapshot"))
    assert snap.index("governor.snapshot()") < snap.index("with self._lock")


# ================================================ 4. server VAD stays ON (H1)
def test_the_session_shape_the_billing_fact_was_measured_on_still_ships() -> None:
    """H1's silence result is proven for SERVER-VAD sessions only. Pin the shape.

    The second read is explicit: "a lane that disables server VAD and commits
    buffers manually would tokenise what it commits, so the design must keep
    server VAD ON behind the local gate". The knob is config-time; this is the
    pin the note asks for.
    """

    payload = SessionUpdate(
        model="gpt-realtime-2.1-mini", instructions="x", voice="alloy"
    ).to_payload()
    detection = payload["session"]["audio"]["input"]["turn_detection"]
    assert detection == {"type": TURN_DETECTION_SERVER_VAD}
    assert TurnDetection().type == TURN_DETECTION_SERVER_VAD
    # There is no "off": every accepted type is a server-side endpointer, so no
    # config can produce the manually-committed shape the billing fact excludes.
    from parcel_robot.realtime.protocol import TURN_DETECTION_TYPES

    assert set(TURN_DETECTION_TYPES) == {"server_vad", "semantic_vad"}


# ================================================= 5. the governor, seeded red
class _Total:
    def __init__(self, usd: float, *, readable: bool = True, month: str = "2026-08") -> None:
        self.usd = usd
        self.readable = readable
        self.month = month


class _Day:
    def __init__(self, usd: float, day: str = "2026-08-24") -> None:
        self.usd = usd
        self.day = day


def test_the_envelope_defaults_are_the_hld_numbers() -> None:
    """$160 application envelope + $40 reserve inside the owner's $200 ceiling."""

    config = GovernorConfig()
    assert (config.envelope_usd, config.reserve_usd) == (160.0, 40.0)
    assert (DEFAULT_ENVELOPE_USD, DEFAULT_RESERVE_USD, DEFAULT_WARN_USD) == (160.0, 40.0, 150.0)
    assert config.ceiling_usd == 200.0
    assert config.daily_cap_usd == 0.0, "no daily bar was measured; pacing is opt-in"


def test_cap_not_reached_admits() -> None:
    governor = HostedCallGovernor(month_to_date=lambda: _Total(30.72))
    decision = governor.admit("the owner's hosted conversation")
    assert decision.admitted is True
    assert decision.code == CODE_ADMITTED
    assert decision.warning == ""
    assert governor.admitted == 1


def test_cap_reached_refuses_a_non_critical_call_with_a_typed_reason() -> None:
    """Seeded red: the ledger says $160.01 and the next call must not happen."""

    notes: list[str] = []
    governor = HostedCallGovernor(
        month_to_date=lambda: _Total(160.01),
        on_event=notes.append,
    )
    decision = governor.admit("the owner's hosted conversation")
    assert decision.admitted is False
    assert decision.code == CODE_ENVELOPE_REACHED
    assert "$160.01" in decision.reason and "$160.00" in decision.reason
    assert "reserve" in decision.reason and "STOP" in decision.reason
    assert notes, "a refusal that nobody is told about is a silent grounding"

    with pytest.raises(HostedCallRefused) as raised:
        governor.require("the owner's hosted conversation")
    assert raised.value.code == CODE_ENVELOPE_REACHED
    assert raised.value.decision.month_usd == pytest.approx(160.01)


def test_a_repeated_refusal_is_announced_once() -> None:
    """Five presses against a spent envelope is one thing to say, not five."""

    notes: list[str] = []
    governor = HostedCallGovernor(month_to_date=lambda: _Total(300.0), on_event=notes.append)
    for _ in range(5):
        assert governor.admit("a hosted turn").admitted is False
    assert governor.refused == 5
    assert len(notes) == 1, notes


def test_the_warning_line_fires_before_the_refusal_line() -> None:
    notes: list[str] = []
    governor = HostedCallGovernor(month_to_date=lambda: _Total(151.0), on_event=notes.append)
    decision = governor.admit("a hosted turn")
    assert decision.admitted is True
    assert "$150.00" in decision.warning
    assert notes and "$150.00" in notes[0]


def test_a_critical_call_is_never_governed_and_never_reads_the_ledger() -> None:
    """The structural half: money is not consulted on a critical path AT ALL."""

    reads = {"count": 0}

    def _month() -> object:
        reads["count"] += 1
        return _Total(999.0)

    governor = HostedCallGovernor(config=GovernorConfig(envelope_usd=0.0), month_to_date=_month)
    decision = governor.admit("a safety-class fact", call_class=CLASS_CRITICAL)
    assert decision.admitted is True
    assert decision.code == CODE_NEVER_GOVERNED
    assert reads["count"] == 0, (
        "a critical call read the spend ledger; money may not be able to delay "
        "or fail a critical path even by succeeding slowly"
    )
    # Same governor, same exhausted envelope, a routine call: refused, and NOW
    # the ledger is read.
    assert governor.admit("a routine call").admitted is False
    assert reads["count"] == 1


def test_the_day_cap_paces_without_touching_the_month() -> None:
    governor = HostedCallGovernor(
        config=GovernorConfig(daily_cap_usd=2.0),
        month_to_date=lambda: _Total(4.10),
        day_to_date=lambda: _Day(2.25),
    )
    decision = governor.admit("a hosted turn")
    assert decision.admitted is False
    assert decision.code == CODE_DAY_CAP_REACHED
    assert "pacing" in decision.reason
    assert decision.month_usd == pytest.approx(4.10)


def test_an_unreadable_ledger_refuses_non_critical_calls_and_says_why() -> None:
    """HLD §10: refuse nonessential calls when ledger/rate state is unknown."""

    governor = HostedCallGovernor(month_to_date=lambda: _Total(0.0, readable=False))
    decision = governor.admit("a hosted turn")
    assert decision.admitted is False
    assert decision.code == CODE_LEDGER_UNKNOWN
    assert "stays local" in decision.reason

    # And the knob restores the ledger's own fail-OPEN direction for an operator
    # who would rather keep talking than keep counting.
    lenient = HostedCallGovernor(
        config=GovernorConfig(refuse_when_unknown=False),
        month_to_date=lambda: _Total(0.0, readable=False),
    )
    assert lenient.admit("a hosted turn").admitted is True


def test_a_ledger_nobody_wired_is_not_unknown_spend() -> None:
    """No meter is not a broken meter: the pre-A7 behaviour is what ships."""

    assert HostedCallGovernor().admit("a hosted turn").admitted is True


def test_the_governor_refusal_reaches_the_microphone_press() -> None:
    """The product path: press -> governor -> refusal, and no session opens."""

    gate = EarGate(
        config=EarGateConfig(),
        governor=HostedCallGovernor(month_to_date=lambda: _Total(200.0)),
    )
    admission = gate.press()
    assert admission.admitted is False
    assert admission.code == CODE_BUDGET_REFUSED
    assert admission.budget_refused is True
    # And a refused press does not open a turn: frames still go nowhere.
    assert all(gate.offer_frame(frame) == b"" for frame in _frames(4.0))
    assert gate.bytes_uploaded == 0

    healthy = EarGate(
        config=EarGateConfig(),
        governor=HostedCallGovernor(month_to_date=lambda: _Total(1.0)),
    )
    assert healthy.press().budget_refused is False


def test_the_typed_hosted_turn_is_governed_too_and_refuses_as_a_RuntimeError() -> None:
    """A typed turn opens a billed session as surely as a press does.

    ``HostedCallRefused`` subclasses ``RuntimeError`` on purpose: the panel's
    POST handler already renders a ``RuntimeError`` as 409 with its message, so
    a refused turn reaches the owner as the reason rather than a stack trace.
    """

    from parcel_robot.runtime import RobotRuntime

    class _Stub:
        realtime_governor = HostedCallGovernor(month_to_date=lambda: _Total(500.0))

    assert issubclass(HostedCallRefused, RuntimeError)
    with pytest.raises(HostedCallRefused) as raised:
        RobotRuntime._require_hosted_budget(_Stub(), "the owner's typed hosted turn")
    assert raised.value.code == CODE_ENVELOPE_REACHED
    assert "typed hosted turn" in raised.value.reason

    class _Unmetered:
        realtime_governor = None

    # No governor wired: the pre-A7 behaviour, exactly.
    assert RobotRuntime._require_hosted_budget(_Unmetered(), "a turn") is None


def test_the_press_only_raises_on_a_budget_refusal() -> None:
    """A press that has not been admitted YET is not a refusal. Regression."""

    from parcel_robot.runtime import RobotRuntime

    source = _source("runtime.py")
    gesture = _function(source, "_realtime_mic_gesture")
    assert "budget_refused" in ast.unparse(gesture), (
        "the press is being read as a refusal whenever it is not yet admitted, "
        "which refuses every turn ever spoken"
    )
    assert RobotRuntime._raise_hosted_refusal is not None


# ============================ 6. safety never routes through the money, at all
SAFETY_MODULES = (
    "audio/stop_hotword.py",
    "core/hard_stop.py",
    "safety.py",
    "core/arbiter.py",
    "core/stop_ramp.py",
    "lethal_veto.py",
)
GOVERNED_MODULES = ("parcel_robot.realtime.hosted_budget", "parcel_robot.realtime.ear_gate")


def test_no_safety_module_imports_the_governor_or_the_ear() -> None:
    """A budget that can silence a stop is a hazard with an accountant."""

    offenders: dict[str, list[str]] = {}
    for name in SAFETY_MODULES:
        source = _source(name)
        found = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                if any(node.module.startswith(mod) for mod in GOVERNED_MODULES):
                    found.append(node.module)
            elif isinstance(node, ast.Import):
                found.extend(
                    alias.name
                    for alias in node.names
                    if any(alias.name.startswith(mod) for mod in GOVERNED_MODULES)
                )
        if found:
            offenders[name] = found
    assert not offenders, (
        f"safety module(s) reached the hosted-call budget: {offenders}. STOP is "
        "local by cards A6/A2 and must stay so."
    )


def test_the_stop_latch_path_never_consults_the_budget() -> None:
    """The A6 methods by name: no governor, no ear, no ledger on the latch."""

    source = _source("runtime.py")
    for name in ("_stop_hotword_latched", "_build_stop_hotword", "_stop_hotword_bare_window"):
        body = ast.unparse(_function(source, name))
        for forbidden in ("realtime_governor", "realtime_ear", "_require_hosted_budget"):
            assert forbidden not in body, f"{name} reaches {forbidden}"


def test_the_governor_is_only_asked_where_a_hosted_call_is_opened() -> None:
    """Every call site named, so a new one has to be argued for."""

    source = _source("runtime.py")
    sites = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef):
            body = ast.unparse(node)
            if "_require_hosted_budget(" in body and node.name != "_require_hosted_budget":
                sites.add(node.name)
            if ".press()" in body:
                sites.add(node.name)
    assert sites == {"submit_realtime_text", "_realtime_mic_gesture"}, sites


# ================================== 7. the owner is read in an exchange (H1)
def _corpus_turns() -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    for path in sorted(CORPUS.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        for turn in record["turns"]:
            turns.append((record["thread_id"], turn["owner_text"]))
    return turns


def test_the_owner_corpus_is_misread_context_free_and_read_in_its_exchange() -> None:
    """H1's number, reproduced through the PRODUCT caller. 66/174 -> 8/174."""

    turns = _corpus_turns()
    assert len(turns) == 174, "the frozen corpus changed size"

    context_free = sum(1 for _, text in turns if triage(text).tier == TIER_HEAR_ONLY)
    assert context_free == 66, (
        "the context-free reading no longer misses 66 of the owner's own 174 "
        "turns; the card's premise moved and the wiring needs re-arguing"
    )

    clock = {"now": 0.0}
    gate = EarGate(config=EarGateConfig(), monotonic=lambda: clock["now"])
    in_exchange = 0
    thread = None
    for owner_thread, text in turns:
        if owner_thread != thread:
            thread = owner_thread
            # A new conversation: the dog has not been addressed in this one.
            gate = EarGate(config=EarGateConfig(), monotonic=lambda: clock["now"])
        clock["now"] += 3.0
        if gate.note_owner_turn(text).tier == TIER_HEAR_ONLY:
            in_exchange += 1
    assert in_exchange == 8
    assert context_free - in_exchange == 58, "58 owner turns recovered by context"


def test_the_exchange_window_expires_and_does_not_make_the_dog_deaf_forever() -> None:
    clock = {"now": 0.0}
    gate = EarGate(config=EarGateConfig(), monotonic=lambda: clock["now"])
    assert gate.note_owner_turn("parcel, can you hear me").tier != TIER_HEAR_ONLY
    clock["now"] += 5.0
    assert gate.note_owner_turn("the one by the petrol station").tier != TIER_HEAR_ONLY
    # Past the window, a marker-free sentence is background again.
    clock["now"] += EarGateConfig().exchange_window_s + 10.0
    assert gate.note_owner_turn("the one by the petrol station").tier == TIER_HEAR_ONLY


def test_the_runtime_reads_owner_turns_through_the_ear() -> None:
    """Structural: the hosted transcript path calls the in-exchange reader."""

    body = ast.unparse(_function(_source("runtime.py"), "submit_realtime_transcript"))
    assert "note_owner_turn" in body, (
        "hosted owner turns are being read context-free again; H1 measured that "
        "as 66 of 174 owner sentences called `hear_only`"
    )


# ======================= 8. bytes -> dollars: what the gate is worth, on record
def test_the_gate_is_the_difference_between_thirty_dollars_and_five_hundred() -> None:
    """H1 C5 priced on the measured card, and the gated ear beside it.

    No socket: the open rate is H1's measured 960.6/hour on ambient speech and
    the per-turn dollar figure is its modelled median audio turn, both from the
    study's own results. The point of the row is the RATIO and the zero.
    """

    ungated_per_month = H1_TV_OPENS_PER_HOUR * 4.0 * 30.0 * H1_MEDIAN_AUDIO_TURN_USD
    assert ungated_per_month == pytest.approx(503.9, rel=0.02)
    assert ungated_per_month > DEFAULT_ENVELOPE_USD * 3.0

    # The same television through the shipped gate: no press, no bytes, and a
    # ledger with nothing in it to price.
    gate = _gate()
    for _ in range(int(H1_TV_OPENS_PER_HOUR / 60.0) + 1):
        for frame in _frames(3.0):
            gate.offer_frame(frame)
    assert gate.bytes_uploaded == 0
    assert realtime_spend_usd([]) == 0.0
    assert MINI_RATE_CARD.priced_usd({"input_tokens": 0, "output_tokens": 0}) == 0.0


def test_admitted_bytes_are_counted_so_a_regression_is_a_number() -> None:
    """Uploaded bytes are the ear's own meter; a leak shows up as a count."""

    gate = _gate(verify=lambda _p: 0.90)
    gate.press()
    total = 0
    for frame in _frames(5.0):
        total += len(gate.offer_frame(frame))
    assert total == gate.bytes_uploaded
    # An ADMITTED turn loses nothing: every byte the gate held is flushed, which
    # is what "pre-roll" means and why the bar can be a precondition.
    assert gate.bytes_seen == gate.bytes_uploaded == total
    assert gate.bytes_erased == 0
    snapshot = gate.snapshot()
    assert snapshot["bytes_uploaded"] == total
    assert snapshot["admission"]["code"] == CODE_ADMITTED_IDENTITY

    # A REFUSED turn is the other direction: seen, erased, never uploaded.
    refused = _gate(verify=lambda _p: 0.10)
    refused.press()
    for frame in _frames(5.0):
        refused.offer_frame(frame)
    assert refused.bytes_seen > 0
    assert refused.bytes_uploaded == 0
    assert refused.bytes_erased > 0


# ============================================== 9. the config, refused by name
def test_an_unknown_ear_key_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="pre_rol_ms"):
        EarGateConfig.from_mapping({"pre_rol_ms": 500})
    with pytest.raises(ValueError, match="envelop_usd"):
        EarGateConfig.from_mapping({"governor": {"envelop_usd": 160}})
    with pytest.raises(TypeError):
        EarGateConfig.from_mapping({"ambient": "yes"})
    with pytest.raises(ValueError):
        GovernorConfig.from_mapping({"envelope_usd": -1.0})


def test_the_ear_block_is_reachable_from_the_audio_subtree() -> None:
    """`config.py` is ON the DEC-0 ceiling; the block nests under an exempt parent."""

    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS
    from parcel_robot.realtime.audio_gateway import (
        AUDIO_CONFIG_KEYS,
        resolve_audio_gateway_selection,
    )

    assert "audio" in OVERLAY_INTRODUCIBLE_KEYS
    assert "ear" in AUDIO_CONFIG_KEYS
    # The gateway resolver still ignores it and still refuses a typo beside it.
    assert resolve_audio_gateway_selection({"gateway": "browser", "ear": {"ambient": False}}) == (
        "browser",
        None,
    )
    with pytest.raises(ValueError, match="eer"):
        resolve_audio_gateway_selection({"eer": {}})
    # And `config.py` has not grown past the ceiling this card was told to respect.
    assert len((REPO / "src" / "parcel_robot" / "config.py").read_text().splitlines()) <= 1000


def test_the_defaults_load_when_the_block_is_absent() -> None:
    assert EarGateConfig.from_mapping(None) == EarGateConfig()
    assert EarGateConfig.from_mapping({}) == EarGateConfig()
    assert GovernorConfig.from_mapping(None) == GovernorConfig()
