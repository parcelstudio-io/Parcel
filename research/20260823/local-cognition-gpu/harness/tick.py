"""One monologue tick against a llama.cpp server, with honest timings.

Streaming is not a style choice here: TTFT is a pre-registered row (G7) and the
only way to measure it is to read the first token off the wire. ``total_ms`` is
wall clock from *before* the request is built to *after* the last chunk, which
is what a cognition thread actually waits.

The decode is constrained by ``response_format.schema`` (llama.cpp compiles it
to a grammar, the same door ``providers.py`` uses). A reply that still fails
:func:`parse_decision` is recorded as a parse failure, never repaired.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from parcel_robot.brain.monologue import (
    MONOLOGUE_SYSTEM_PROMPT,
    MonologueParseError,
    TickOutcome,
    WorldDigestV1,
    decision_json_schema,
    parse_decision,
)

TICK_MAX_TOKENS = 160


@dataclass
class TickClient:
    """A llama.cpp OpenAI-compatible endpoint, used as a monologue tick."""

    base_url: str
    model: str
    timeout: float = 120.0
    temperature: float = 0.0
    max_tokens: int = TICK_MAX_TOKENS

    def payload(self, digest: WorldDigestV1) -> dict[str, object]:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {"role": "system", "content": MONOLOGUE_SYSTEM_PROMPT},
                {"role": "user", "content": digest.render()},
            ],
            "response_format": {"type": "json_object", "schema": decision_json_schema()},
        }

    def tick(self, digest: WorldDigestV1, *, digest_id: str = "") -> TickOutcome:
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/v1/chat/completions",
            data=json.dumps(self.payload(digest)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        started = time.perf_counter()
        first_token_at: float | None = None
        chunks: list[str] = []
        output_tokens = 0
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as stream:
                for raw in stream:
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    try:
                        event = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    usage = event.get("usage")
                    if isinstance(usage, dict) and usage.get("completion_tokens"):
                        output_tokens = int(usage["completion_tokens"])
                    for choice in event.get("choices") or ():
                        piece = (choice.get("delta") or {}).get("content") or ""
                        if piece:
                            if first_token_at is None:
                                first_token_at = time.perf_counter()
                            chunks.append(piece)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return TickOutcome(
                digest_id=digest_id,
                decision=None,
                error=f"transport: {error}",
                total_ms=(time.perf_counter() - started) * 1000.0,
            )
        finished = time.perf_counter()
        raw_text = "".join(chunks)
        ttft_ms = ((first_token_at or finished) - started) * 1000.0
        total_ms = (finished - started) * 1000.0
        try:
            decision = parse_decision(raw_text)
        except MonologueParseError as error:
            return TickOutcome(
                digest_id=digest_id,
                decision=None,
                error=f"parse: {error}",
                ttft_ms=ttft_ms,
                total_ms=total_ms,
                output_tokens=output_tokens,
                raw=raw_text,
            )
        return TickOutcome(
            digest_id=digest_id,
            decision=decision,
            ttft_ms=ttft_ms,
            total_ms=total_ms,
            output_tokens=output_tokens,
            raw=raw_text,
        )


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile. No interpolation, no scipy, no surprises."""

    if not values:
        return float("nan")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * len(ordered) + 0.5) - 1))
    return ordered[index]


def summarize(outcomes: list[TickOutcome]) -> dict[str, object]:
    parsed = [outcome for outcome in outcomes if outcome.parsed]
    totals = [outcome.total_ms for outcome in outcomes]
    ttfts = [outcome.ttft_ms for outcome in outcomes if outcome.ttft_ms > 0]
    tokens = [outcome.output_tokens for outcome in parsed if outcome.output_tokens]
    seconds = [outcome.total_ms / 1000.0 for outcome in parsed if outcome.total_ms > 0]
    tok_s = (sum(tokens) / sum(seconds)) if tokens and sum(seconds) > 0 else float("nan")
    return {
        "ticks": len(outcomes),
        "parsed": len(parsed),
        "parse_failures": len(outcomes) - len(parsed),
        "total_p50_ms": round(percentile(totals, 0.50), 1),
        "total_p95_ms": round(percentile(totals, 0.95), 1),
        "total_mean_ms": round(sum(totals) / len(totals), 1) if totals else float("nan"),
        "total_max_ms": round(max(totals), 1) if totals else float("nan"),
        "ttft_p50_ms": round(percentile(ttfts, 0.50), 1),
        "ttft_p95_ms": round(percentile(ttfts, 0.95), 1),
        "output_tokens_mean": round(sum(tokens) / len(tokens), 1) if tokens else 0.0,
        "tokens_per_s": round(tok_s, 1),
    }
