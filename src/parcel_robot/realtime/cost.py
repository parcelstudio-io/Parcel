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
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

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


__all__ = [
    "ASSUMED_CACHED_INPUT_USD_PER_MTOK",
    "ASSUMED_INPUT_USD_PER_MTOK",
    "ASSUMED_OUTPUT_USD_PER_MTOK",
    "realtime_spend_usd",
    "realtime_usage_totals",
]
