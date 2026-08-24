"""What a hosted session cost, from the provider's own usage rows (card R2/R3).

WHY THIS IS SEPARATE FROM THE LANE
----------------------------------
The lane parses ``response.done`` usage and appends one row per response; it
deliberately knows nothing about money. Prices change, they differ per model,
and — this is the part that matters for the register — the rates below are
ASSUMED, taken from the same constants the corpus scrape uses
(``evals/companion/realtime_convo_v1/scrape_realtime_convo.py``) and NOT from a
fetched price list or an invoice. Keeping the arithmetic here, in one function
with the assumption stated in its own name, is what lets a status doc say
"estimated $X at assumed rates" without ever presenting it as a billed figure.

Cached input is priced separately because the cached-audio discount is the
entire cost model of a long companion session: the memory tail goes up once and
every later turn re-reads it at the cached rate.

WHAT H1 ADDED, AND WHY THE OLD PATH IS STILL HERE
-------------------------------------------------
:class:`RateCard` carries the *published* per-modality rates with an ``as_of``
date, and :meth:`RateCard.price` uses the audio/text/cached split the provider
reports in ``input_token_details`` / ``output_token_details``. That split is the
whole story for a companion: on ``gpt-realtime-2.1-mini`` an audio input token
costs **16.7x** a text input token, so pricing an audio session at text rates —
which is what :func:`realtime_spend_usd` does, at the FULL model's text rates,
on every existing row — is wrong in both directions at once and by a different
factor per turn.

The old function keeps its exact arithmetic and its exact name. Every row ever
written by :mod:`parcel_robot.realtime.spend_ledger` before this change was
priced by it, ``rates_are_assumed: true`` says so on each of those rows, and
re-pricing history from a rate card the rows never saw would be a worse lie than
the one it replaces. New pricing is therefore OPT-IN: a caller that hands a
:class:`RateCard` gets split pricing and a row that says ``rates_are_assumed:
false``; a caller that hands nothing gets exactly what it got yesterday.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

#: USD per million tokens. ASSUMED — see the module docstring. Same numbers as
#: the corpus scrape so two evidence packs cannot quote different prices.
ASSUMED_INPUT_USD_PER_MTOK = 4.00
ASSUMED_CACHED_INPUT_USD_PER_MTOK = 0.40
ASSUMED_OUTPUT_USD_PER_MTOK = 16.00

_PER_TOKEN = 1_000_000.0


def _whole(row: Mapping[str, object], key: str) -> int:
    value = row.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def realtime_spend_usd(rows: Iterable[Mapping[str, object]]) -> float:
    """Estimated spend for a sequence of lane usage rows, at assumed rates.

    Cached input tokens are billed at the cached rate and subtracted from the
    uncached input count, matching how the provider reports them (``input_tokens``
    is the total; ``cached_tokens`` is the discounted subset of it).
    """

    total = 0.0
    for row in rows:
        cached = _whole(row, "cached_tokens")
        billed_input = max(0, _whole(row, "input_tokens") - cached)
        output = _whole(row, "output_tokens")
        total += (
            billed_input * ASSUMED_INPUT_USD_PER_MTOK
            + cached * ASSUMED_CACHED_INPUT_USD_PER_MTOK
            + output * ASSUMED_OUTPUT_USD_PER_MTOK
        ) / _PER_TOKEN
    return total


def realtime_usage_totals(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Token totals plus the estimate, shaped for a status-doc evidence block."""

    collected = [dict(row) for row in rows]
    totals = {
        key: sum(_whole(row, key) for row in collected)
        for key in (
            "input_tokens",
            "output_tokens",
            "input_audio_tokens",
            "output_audio_tokens",
            "cached_tokens",
        )
    }
    return {
        "responses": len(collected),
        **totals,
        "estimated_usd": round(realtime_spend_usd(collected), 6),
        "rates_are_assumed": True,
    }


# =============================================================== rate cards
#: The published prices, USD per million tokens, read off the OpenAI pricing
#: page on this date by hand. NOT fetched at runtime and NOT an invoice — but,
#: unlike ``ASSUMED_*`` above, these are the real per-modality numbers for the
#: models this repo actually opens sockets to.
RATE_CARD_AS_OF = "2026-08-23"


@dataclass(frozen=True)
class RateCard:
    """Published per-modality prices for one Realtime model.

    Six numbers, because the provider bills six things: text in, cached text in,
    text out, audio in, cached audio in, audio out. Collapsing them to three (the
    ``ASSUMED_*`` constants) is what made the old estimate wrong; collapsing them
    to one would be worse. ``as_of`` is on the card rather than in a comment so a
    priced row can carry the date the price was true.
    """

    model: str
    as_of: str
    text_input_usd_per_mtok: float
    text_cached_input_usd_per_mtok: float
    text_output_usd_per_mtok: float
    audio_input_usd_per_mtok: float
    audio_cached_input_usd_per_mtok: float
    audio_output_usd_per_mtok: float
    source: str = "openai pricing page, read by hand"

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "as_of": self.as_of,
            "text_in": self.text_input_usd_per_mtok,
            "text_cached_in": self.text_cached_input_usd_per_mtok,
            "text_out": self.text_output_usd_per_mtok,
            "audio_in": self.audio_input_usd_per_mtok,
            "audio_cached_in": self.audio_cached_input_usd_per_mtok,
            "audio_out": self.audio_output_usd_per_mtok,
            "source": self.source,
        }

    def price(self, row: Mapping[str, object]) -> RowPrice:
        """Price one usage row. Never raises; unknown shapes fall back to ASSUMED."""

        split = usage_split(row)
        if split is None:
            return RowPrice(
                usd=realtime_spend_usd([row]),
                basis=BASIS_ASSUMED,
                model=self.model,
                as_of=self.as_of,
                components={},
            )
        components = {
            "text_in": split["text_in"] * self.text_input_usd_per_mtok / _PER_TOKEN,
            "text_cached_in": (
                split["text_cached_in"] * self.text_cached_input_usd_per_mtok / _PER_TOKEN
            ),
            "text_out": split["text_out"] * self.text_output_usd_per_mtok / _PER_TOKEN,
            "audio_in": split["audio_in"] * self.audio_input_usd_per_mtok / _PER_TOKEN,
            "audio_cached_in": (
                split["audio_cached_in"] * self.audio_cached_input_usd_per_mtok / _PER_TOKEN
            ),
            "audio_out": split["audio_out"] * self.audio_output_usd_per_mtok / _PER_TOKEN,
        }
        return RowPrice(
            usd=sum(components.values()),
            basis=str(split["basis"]),
            model=self.model,
            as_of=self.as_of,
            components=components,
            tokens={key: int(value) for key, value in split.items() if key != "basis"},
        )

    def priced_usd(self, row: Mapping[str, object]) -> float:
        """Dollars for one usage row, split-aware. The number a ceiling reads."""

        return self.price(row).usd


#: gpt-realtime-2.1-mini. The model every live run in this repo has used.
MINI_RATE_CARD = RateCard(
    model="gpt-realtime-2.1-mini",
    as_of=RATE_CARD_AS_OF,
    text_input_usd_per_mtok=0.60,
    text_cached_input_usd_per_mtok=0.06,
    text_output_usd_per_mtok=2.40,
    audio_input_usd_per_mtok=10.00,
    audio_cached_input_usd_per_mtok=0.30,
    audio_output_usd_per_mtok=20.00,
)

#: gpt-realtime-2.1, the full-size sibling.
FULL_RATE_CARD = RateCard(
    model="gpt-realtime-2.1",
    as_of=RATE_CARD_AS_OF,
    text_input_usd_per_mtok=4.00,
    text_cached_input_usd_per_mtok=0.40,
    text_output_usd_per_mtok=24.00,
    audio_input_usd_per_mtok=32.00,
    audio_cached_input_usd_per_mtok=0.40,
    audio_output_usd_per_mtok=64.00,
)

#: Every spelling of a model id this repo has written down, mapped to its card.
RATE_CARDS: Mapping[str, RateCard] = {
    "gpt-realtime-2.1-mini": MINI_RATE_CARD,
    "gpt-realtime-mini": MINI_RATE_CARD,
    "gpt-4o-realtime-mini": MINI_RATE_CARD,
    "gpt-realtime-2.1": FULL_RATE_CARD,
    "gpt-realtime": FULL_RATE_CARD,
}

#: What a ceiling prices with when the model is not known. The DEARER card, on
#: purpose: a budget that has to guess must guess upward, or the guess is a way
#: of spending money the owner did not agree to.
DEFAULT_RATE_CARD = FULL_RATE_CARD

BASIS_ASSUMED = "assumed"
BASIS_SPLIT = "split"
BASIS_SPLIT_APPORTIONED = "split_apportioned"


@dataclass(frozen=True)
class RowPrice:
    """What one usage row cost, and on what evidence."""

    usd: float
    basis: str
    model: str
    as_of: str
    components: Mapping[str, float]
    tokens: Mapping[str, int] = ()  # type: ignore[assignment]

    @property
    def rates_are_assumed(self) -> bool:
        return self.basis == BASIS_ASSUMED

    def as_dict(self) -> dict[str, object]:
        return {
            "usd": round(self.usd, 9),
            "basis": self.basis,
            "model": self.model,
            "as_of": self.as_of,
            "components": {key: round(value, 9) for key, value in dict(self.components).items()},
            "tokens": dict(self.tokens or {}),
        }


def rate_card_for(model: str | None) -> RateCard | None:
    """The card for a model id, or ``None`` when the id is not one we priced."""

    if not isinstance(model, str) or not model.strip():
        return None
    return RATE_CARDS.get(model.strip())


def usage_split(row: Mapping[str, object]) -> dict[str, object] | None:
    """Six token counts from one usage row, or ``None`` if the row has no split.

    Two row shapes are accepted, and they are NOT equally good:

    ``split``
        The raw ``response.done`` usage block, with ``input_token_details`` and
        ``output_token_details``. Cached audio and cached text are read from
        ``cached_tokens_details`` and nothing is inferred.

    ``split_apportioned``
        The flattened five-key row the lane appends (``input_audio_tokens``,
        ``output_audio_tokens``, ``cached_tokens``, ...). It records ONE cached
        number for both modalities, so the cached total is apportioned across
        audio and text in proportion to the input tokens of each. The
        apportionment is named in the basis so a reader never mistakes it for a
        reported figure. It matters: on mini, cached audio is $0.30/Mtok and
        cached text $0.06/Mtok, so a mis-apportioned cache moves the row by up
        to 5x on its cached component.

    A row with neither shape (the pre-H1 three-key ledger row) returns ``None``
    and must keep the ASSUMED path.
    """

    detail_in = row.get("input_token_details")
    detail_out = row.get("output_token_details")
    if isinstance(detail_in, Mapping) or isinstance(detail_out, Mapping):
        detail_in = detail_in if isinstance(detail_in, Mapping) else {}
        detail_out = detail_out if isinstance(detail_out, Mapping) else {}
        cached_detail = detail_in.get("cached_tokens_details")
        cached_detail = cached_detail if isinstance(cached_detail, Mapping) else {}
        audio_in = _whole(detail_in, "audio_tokens")
        text_in = _whole(detail_in, "text_tokens")
        cached_total = _whole(detail_in, "cached_tokens")
        cached_audio = _whole(cached_detail, "audio_tokens")
        cached_text = _whole(cached_detail, "text_tokens")
        if not cached_detail:
            cached_audio, cached_text = _apportion(cached_total, audio_in, text_in)
            basis = BASIS_SPLIT_APPORTIONED
        else:
            basis = BASIS_SPLIT
        audio_out = _whole(detail_out, "audio_tokens")
        text_out = _whole(detail_out, "text_tokens")
        if not text_out:
            text_out = max(0, _whole(row, "output_tokens") - audio_out)
        return _split(
            audio_in=audio_in,
            text_in=text_in,
            cached_audio=cached_audio,
            cached_text=cached_text,
            audio_out=audio_out,
            text_out=text_out,
            basis=basis,
        )
    if "input_audio_tokens" not in row and "output_audio_tokens" not in row:
        return None
    audio_in = _whole(row, "input_audio_tokens")
    text_in = max(0, _whole(row, "input_tokens") - audio_in)
    audio_out = _whole(row, "output_audio_tokens")
    text_out = max(0, _whole(row, "output_tokens") - audio_out)
    cached_audio, cached_text = _apportion(_whole(row, "cached_tokens"), audio_in, text_in)
    return _split(
        audio_in=audio_in,
        text_in=text_in,
        cached_audio=cached_audio,
        cached_text=cached_text,
        audio_out=audio_out,
        text_out=text_out,
        basis=BASIS_SPLIT_APPORTIONED,
    )


def _apportion(cached: int, audio_in: int, text_in: int) -> tuple[int, int]:
    """Split one cached total across audio and text by their share of the input."""

    total = audio_in + text_in
    if cached <= 0 or total <= 0:
        return 0, min(cached, text_in) if cached > 0 else 0
    cached = min(cached, total)
    cached_audio = min(audio_in, round(cached * audio_in / total))
    return cached_audio, cached - cached_audio


def _split(
    *,
    audio_in: int,
    text_in: int,
    cached_audio: int,
    cached_text: int,
    audio_out: int,
    text_out: int,
    basis: str,
) -> dict[str, object]:
    """Uncached counts, cached counts, and the basis — the shape ``price`` bills."""

    cached_audio = min(cached_audio, audio_in)
    cached_text = min(cached_text, text_in)
    return {
        "audio_in": audio_in - cached_audio,
        "text_in": text_in - cached_text,
        "audio_cached_in": cached_audio,
        "text_cached_in": cached_text,
        "audio_out": audio_out,
        "text_out": text_out,
        "basis": basis,
    }


def priced_usd(
    row: Mapping[str, object],
    *,
    model: str | None = None,
    card: RateCard | None = None,
) -> float:
    """Dollars for one usage row at published rates.

    Resolution order: an explicit ``card``, then ``model``, then the row's own
    ``model`` field, then :data:`DEFAULT_RATE_CARD` (the dearer one).
    """

    resolved = card or rate_card_for(model) or rate_card_for(row.get("model"))  # type: ignore[arg-type]
    return (resolved or DEFAULT_RATE_CARD).priced_usd(row)


def realtime_spend_usd_priced(
    rows: Iterable[Mapping[str, object]],
    *,
    model: str | None = None,
    card: RateCard | None = None,
) -> float:
    """:func:`realtime_spend_usd`'s job, done with a rate card."""

    return sum(priced_usd(row, model=model, card=card) for row in rows)


__all__ = [
    "ASSUMED_CACHED_INPUT_USD_PER_MTOK",
    "ASSUMED_INPUT_USD_PER_MTOK",
    "ASSUMED_OUTPUT_USD_PER_MTOK",
    "BASIS_ASSUMED",
    "BASIS_SPLIT",
    "BASIS_SPLIT_APPORTIONED",
    "DEFAULT_RATE_CARD",
    "FULL_RATE_CARD",
    "MINI_RATE_CARD",
    "RATE_CARDS",
    "RATE_CARD_AS_OF",
    "RateCard",
    "RowPrice",
    "priced_usd",
    "rate_card_for",
    "realtime_spend_usd",
    "realtime_spend_usd_priced",
    "realtime_usage_totals",
    "usage_split",
]
