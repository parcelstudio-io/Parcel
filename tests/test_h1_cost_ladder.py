"""H1's capability test: the ledger tells the truth about an audio session.

Research folder: ``research/20260823/ambient-ear-cost-ladder/``.

The defect this pins is not a crash. Before H1, every hosted response — text or
audio — was priced at ``$4.00 / $0.40 / $16.00`` per million tokens, which are
the FULL model's TEXT rates, and the row carried no audio/text split at all. On
the ``gpt-realtime-2.1-mini`` sessions this repo actually opens, that is wrong by
a factor the live calibration measured at **4.4x**, in the expensive direction,
which means the owner's ``monthly_budget_usd`` was grounding the dog four times
earlier than the invoice justified. A ceiling built on a number that wrong is
not a ceiling; it is a coin flip with a units bug.

The fixture usage blocks below are VERBATIM from the 2026-08-23 live run
(``research/20260823/ambient-ear-cost-ladder/results/live_calibration.json``),
including their odd bits — reasoning tokens folded inside ``text_tokens``,
``cached_tokens_details`` present and zero. A hand-invented usage block would
have proved only that the arithmetic matches itself.

Three capabilities, one each:

1. the rate card prices a real response by modality;
2. rows written before H1 still parse, still total, and still say ASSUMED;
3. the arming gate's ceiling moves when the pricing does.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.cost import (
    BASIS_ASSUMED,
    BASIS_SPLIT,
    BASIS_SPLIT_APPORTIONED,
    FULL_RATE_CARD,
    MINI_RATE_CARD,
    RATE_CARD_AS_OF,
    priced_usd,
    rate_card_for,
    realtime_spend_usd,
)
from parcel_robot.realtime.lane import decide_realtime_arming
from parcel_robot.realtime.spend_ledger import (
    RATE_CARD_ENV,
    SPEND_LEDGER_NAME,
    SPEND_LEDGER_SCHEMA,
    SPEND_LEDGER_SCHEMA_V2,
    SpendLedger,
    spend_row,
)

#: One live AUDIO response, 2026-08-23, gpt-realtime-2.1-mini. Verbatim.
LIVE_AUDIO_USAGE = {
    "total_tokens": 888,
    "input_tokens": 498,
    "output_tokens": 390,
    "input_token_details": {
        "text_tokens": 479,
        "audio_tokens": 19,
        "image_tokens": 0,
        "cached_tokens": 0,
        "cached_tokens_details": {"text_tokens": 0, "audio_tokens": 0, "image_tokens": 0},
    },
    "output_token_details": {"text_tokens": 176, "audio_tokens": 214, "reasoning_tokens": 105},
}

#: The same response as the LANE sees it: five flat keys, no nested details.
LIVE_AUDIO_FLAT_ROW = {
    "response_id": "resp_EGFAJOLac09dkjurOiRF0",
    "input_tokens": 498,
    "output_tokens": 390,
    "input_audio_tokens": 19,
    "output_audio_tokens": 214,
    "cached_tokens": 0,
}

#: One live TEXT response from the same run, with a real cache hit on it.
LIVE_TEXT_FLAT_ROW = {
    "response_id": "resp_EGF9dUegThmdZ2qblTypA",
    "input_tokens": 513,
    "output_tokens": 231,
    "input_audio_tokens": 0,
    "output_audio_tokens": 0,
    "cached_tokens": 448,
}

#: A pre-H1 ledger row: three counts, no split, priced at the assumed rates.
V1_ROW = {"input_tokens": 2316, "cached_tokens": 384, "output_tokens": 114}


def _mini(text_in: int, cached_text: int, text_out: int, audio_in: int, audio_out: int) -> float:
    card = MINI_RATE_CARD
    return (
        text_in * card.text_input_usd_per_mtok
        + cached_text * card.text_cached_input_usd_per_mtok
        + text_out * card.text_output_usd_per_mtok
        + audio_in * card.audio_input_usd_per_mtok
        + audio_out * card.audio_output_usd_per_mtok
    ) / 1_000_000.0


# =================================================== 1. pricing by modality
def test_the_rate_card_prices_a_real_audio_response_by_modality() -> None:
    """Audio out is 55% of ONE token count and 83% of the money. That is the point."""

    price = MINI_RATE_CARD.price(LIVE_AUDIO_USAGE)

    assert price.basis == BASIS_SPLIT, "the provider reported cached_tokens_details"
    assert price.model == "gpt-realtime-2.1-mini"
    assert price.as_of == RATE_CARD_AS_OF
    assert price.rates_are_assumed is False
    assert price.usd == pytest.approx(_mini(479, 0, 176, 19, 214), abs=1e-12)

    # The whole reason a split is needed: 214 audio output tokens out of 888
    # total cost more than everything else in the response put together.
    assert price.components["audio_out"] > sum(
        value for key, value in price.components.items() if key != "audio_out"
    )

    # And the pre-H1 arithmetic, on the same response, is wrong upward — by
    # 1.6x here and by 6.7x on the TEXT row below, which is exactly the problem:
    # the error is not a constant, so it cannot be corrected by a fudge factor.
    assumed = realtime_spend_usd([LIVE_AUDIO_FLAT_ROW])
    assert assumed / price.usd == pytest.approx(1.589, abs=0.01)


def test_the_flattened_lane_row_prices_the_same_as_the_raw_usage_block() -> None:
    """C9. The ledger never sees the nested details; it must still be right."""

    raw = MINI_RATE_CARD.price(LIVE_AUDIO_USAGE)
    flat = MINI_RATE_CARD.price(LIVE_AUDIO_FLAT_ROW)

    assert flat.basis == BASIS_SPLIT_APPORTIONED, "one cached total, apportioned"
    assert flat.usd == pytest.approx(raw.usd, rel=1e-9)


def test_a_text_row_is_priced_at_text_rates_and_the_cache_is_honoured() -> None:
    card = MINI_RATE_CARD
    price = card.price(LIVE_TEXT_FLAT_ROW)

    assert price.tokens["audio_in"] == 0
    assert price.tokens["audio_out"] == 0
    assert price.tokens["text_cached_in"] == 448
    assert price.usd == pytest.approx(_mini(513 - 448, 448, 231, 0, 0), abs=1e-12)
    # The full model's card is a different bill for the same tokens: a card is
    # not a decoration, and defaulting to the wrong one is a 6x error.
    assert FULL_RATE_CARD.priced_usd(LIVE_TEXT_FLAT_ROW) > 6.0 * price.usd
    # The pre-H1 assumed rates ARE the full model's text rates, so on a text
    # row they overcharge a mini session by that same factor.
    assert realtime_spend_usd([LIVE_TEXT_FLAT_ROW]) / price.usd == pytest.approx(
        6.67, abs=0.05
    )


def test_an_unknown_model_prices_at_the_dearer_card() -> None:
    """A budget that has to guess guesses UP, or the guess is unbudgeted spend."""

    assert rate_card_for("gpt-realtime-2.1-mini") is MINI_RATE_CARD
    assert rate_card_for("something-nobody-priced") is None
    assert priced_usd(LIVE_TEXT_FLAT_ROW, model="something-nobody-priced") == pytest.approx(
        FULL_RATE_CARD.priced_usd(LIVE_TEXT_FLAT_ROW)
    )


# ================================================= 2. v1 rows still parse
def test_a_row_with_no_split_keeps_the_assumed_path_even_with_a_card() -> None:
    """A card cannot invent a division the provider never reported."""

    price = MINI_RATE_CARD.price(V1_ROW)

    assert price.basis == BASIS_ASSUMED
    assert price.rates_are_assumed is True
    assert price.usd == pytest.approx(realtime_spend_usd([V1_ROW]))


def test_the_default_ledger_writes_exactly_the_v1_row_it_always_did(tmp_path: Path) -> None:
    """Opt-in means OFF: no card, no environment variable, no change."""

    row = spend_row(LIVE_AUDIO_FLAT_ROW, session_id="rt_x", when=datetime(2026, 8, 23, tzinfo=timezone.utc))
    assert row["schema"] == SPEND_LEDGER_SCHEMA
    assert row["rates_are_assumed"] is True
    assert row["estimated_usd"] == pytest.approx(realtime_spend_usd([LIVE_AUDIO_FLAT_ROW]))
    assert "split_tokens" not in row

    ledger = SpendLedger(tmp_path / SPEND_LEDGER_NAME)
    assert ledger.rate_card is None


def test_the_environment_switch_is_off_unless_set_and_ignores_a_typo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(RATE_CARD_ENV, raising=False)
    assert SpendLedger(tmp_path / "a.jsonl").rate_card is None

    monkeypatch.setenv(RATE_CARD_ENV, "gpt-realtime-2.1-mini")
    assert SpendLedger(tmp_path / "b.jsonl").rate_card is MINI_RATE_CARD

    # A typo must NOT silently fall back to the dearer card: the variable is a
    # request for split pricing, and answering it with a 5x ceiling looks like
    # the request worked.
    monkeypatch.setenv(RATE_CARD_ENV, "gpt-realtime-2.1-minii")
    assert SpendLedger(tmp_path / "c.jsonl").rate_card is None


def test_one_month_may_hold_both_schemas_and_is_totalled_and_flagged_honestly(
    tmp_path: Path,
) -> None:
    """A migrating ledger is the normal case; a mixed month is still ASSUMED."""

    path = tmp_path / SPEND_LEDGER_NAME
    when = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)

    legacy = SpendLedger(path, now=lambda: when, cache_ttl_s=0.0)
    legacy.record(V1_ROW, session_id="old")
    priced = SpendLedger(path, now=lambda: when, cache_ttl_s=0.0, rate_card=MINI_RATE_CARD)
    priced.record(LIVE_AUDIO_FLAT_ROW, session_id="new")

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["schema"] for line in lines] == [SPEND_LEDGER_SCHEMA, SPEND_LEDGER_SCHEMA_V2]
    assert lines[1]["rates_are_assumed"] is False
    assert lines[1]["rate_card_as_of"] == RATE_CARD_AS_OF
    assert lines[1]["split_tokens"]["audio_out"] == 214

    total = priced.month_to_date(force=True)
    assert total.rows == 2
    assert total.usd == pytest.approx(
        realtime_spend_usd([V1_ROW]) + MINI_RATE_CARD.priced_usd(LIVE_AUDIO_FLAT_ROW)
    )
    assert total.rates_are_assumed is True, "one assumed row makes the month assumed"

    # A month of split rows only says so.
    fresh = tmp_path / "fresh.jsonl"
    only = SpendLedger(fresh, now=lambda: when, cache_ttl_s=0.0, rate_card=MINI_RATE_CARD)
    only.record(LIVE_AUDIO_FLAT_ROW, session_id="new")
    assert only.month_to_date(force=True).rates_are_assumed is False


# ============================================ 3. the ceiling moves with it
def test_the_arming_gate_ceiling_follows_the_split_pricing(tmp_path: Path) -> None:
    """The whole point: the same month of traffic arms or refuses by pricing.

    Sixty of the live audio responses cost $0.311 at published mini rates and
    $0.494 at the pre-H1 assumed ones. With a $0.40 ceiling that is the
    difference between a dog that can talk and a dog that cannot, on identical
    traffic — which is what "the instrument is broken" means in practice.
    """

    when = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)
    config = RealtimeConfig(enabled=True, source="test", monthly_budget_usd=0.40)

    def month(*, rate_card):
        path = tmp_path / f"{'v2' if rate_card else 'v1'}.jsonl"
        ledger = SpendLedger(path, now=lambda: when, cache_ttl_s=0.0, rate_card=rate_card)
        for _ in range(60):
            ledger.record(LIVE_AUDIO_FLAT_ROW, session_id="rt_live")
        return ledger.month_to_date(force=True)

    assumed = month(rate_card=None)
    split = month(rate_card=MINI_RATE_CARD)
    assert assumed.usd > 0.40 > split.usd

    def arm(total):
        return decide_realtime_arming(
            config=config,
            handshake_token="csrf",
            mic_gesture=True,
            spend_usd=total.usd,
            spend_readable=total.readable,
            spend_month=total.month,
        )

    assert arm(assumed).armed is False, "the pre-H1 instrument grounds the dog"
    assert arm(split).armed is True, "at published rates the same traffic is affordable"
