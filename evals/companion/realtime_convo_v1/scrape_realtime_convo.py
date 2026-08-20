"""Live scraper for the realtime companion corpus (card R2-C, task_3).

WHAT IT DOES
------------
Drives each authored scenario through the hosted Realtime API in the **text**
modality, with the three companion tools DECLARED so the model actually emits
``navigate_to`` / ``get_status`` / ``play_gesture`` proposals, answers those
proposals with scripted synthetic world results, and writes one fixture per
thread into ``fixtures/``. The fixtures are then replayable offline forever by
``tests/test_realtime_corpus_replay.py``, which never opens a socket.

WHAT IT IS NOT
--------------
It is not a test and can never become one. Nothing under ``tests/`` imports its
run path; the two things tests *do* import are :func:`guard_budget` and
:func:`require_scrape_enabled`, which are pure functions with no I/O. Running
the scrape needs ``PARCEL_REALTIME_SCRAPE=1`` **and** a credential in the
environment, and refuses without both — a corpus refresh is an owner decision
with a bill attached, not something a green suite can trigger.

THE BUDGET GUARD IS THE POINT OF THE PREFLIGHT
----------------------------------------------
25 threads × up to 12 turns, each turn re-sending a system prompt, is the shape
of run that quietly costs more than anyone meant it to. So: an estimate is
printed and checked against a hard ceiling BEFORE the first socket opens, and
the measured spend is re-checked after every single response. Either check
tripping aborts the whole run. The prices below are an operator ESTIMATE, not a
fetched price list — see :data:`ASSUMED_INPUT_USD_PER_MTOK`.

WHY IT SPEAKS RAW FRAMES INSTEAD OF USING ``RealtimeLane``
----------------------------------------------------------
The lane is a *voice* lane: it coalesces PCM, owns a speaker, and its typed
codec only knows the audio-shaped event names. A text-modality scrape sends
``conversation.item.create`` + ``response.create`` and reads
``response.output_text.*``, which that codec deliberately does not implement.
Rather than widen an audited, frozen codec for a data-collection script, the
scraper talks raw JSON over the R1.5 ``WebSocketTransport`` and normalises what
it hears into the corpus schema. The *fixture* is the contract between the two
worlds, and ``schema.fixture_to_script`` turns it back into frames the real
lane does drive.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from evals.companion.realtime_convo_v1.schema import (
    DECLARED_TOOLS,
    FIXTURE_SOURCE_SCRAPE,
    FIXTURES_DIR,
    SCHEMA_VERSION,
    SCRAPE_MODEL,
    USAGE_KEYS,
    Scenario,
    load_scenarios,
)
from parcel_robot.realtime.prompting import (
    DI_VERSION,
    SI_VERSION,
    render_developer_instruction,
    render_session_instructions,
)

#: Both are required. Either missing is a refusal, never a smaller run.
SCRAPE_ENV = "PARCEL_REALTIME_SCRAPE"
API_KEY_ENV = "OPENAI_API_KEY"

#: The hard ceiling from the card. Not configurable upward by a flag: a flag
#: that can raise a spending limit is not a spending limit.
BUDGET_CEILING_USD = 5.0

#: Assumed text-modality prices, USD per 1M tokens. These are an operator
#: ESTIMATE — deliberately generous so the ceiling bites early — and are NOT
#: read from any price list. Whoever runs a future real scrape should replace
#: them with the billed rates and re-run ``--dry-run`` before spending.
ASSUMED_INPUT_USD_PER_MTOK = 4.00
ASSUMED_CACHED_INPUT_USD_PER_MTOK = 0.40
ASSUMED_OUTPUT_USD_PER_MTOK = 16.00

#: Rough characters-per-token for the preflight estimate only. Never used to
#: report spend: reported spend always comes from the provider's usage block.
CHARS_PER_TOKEN = 4.0

#: Assumed model reply length, in tokens, for the estimate.
ASSUMED_REPLY_TOKENS = 60

#: How long one thread may take before the scraper gives up on it.
THREAD_TIMEOUT_S = 90.0
RESPONSE_TIMEOUT_S = 45.0
#: Verified live 2026-08-18: rate-limited responses close as status='failed'
#: with zero usage; three retries with linear backoff cleared every one.
RESPONSE_ATTEMPTS = 4
RETRY_BACKOFF_S = 3.0

#: What the scraper answers a tool proposal with. Synthetic, stated as such, and
#: the same every run so a re-scrape differs only by the model's own words.
SYNTHETIC_TOOL_RESULTS: Mapping[str, Mapping[str, Any]] = {
    "navigate_to": {
        "accepted": True,
        "note": "synthetic world result: route accepted, motion not simulated",
    },
    "get_status": {
        "battery_pct": 74,
        "moving": False,
        "note": "synthetic world result: fixed values, no robot was queried",
    },
    "play_gesture": {
        "accepted": True,
        "note": "synthetic world result: gesture acknowledged, nothing moved",
    },
}

#: Tool schemas handed to the provider. Names match ``DECLARED_TOOLS``; R1's
#: broker refuses all three, and capturing the PROPOSAL is exactly the point.
TOOL_SCHEMAS: tuple[Mapping[str, Any], ...] = (
    {
        "type": "function",
        "name": "navigate_to",
        "description": "Walk to a named place the owner has asked for.",
        "parameters": {
            "type": "object",
            "properties": {
                "place": {"type": "string"},
                "pace": {"type": "string", "enum": ["slow", "normal"]},
            },
            "required": ["place"],
        },
    },
    {
        "type": "function",
        "name": "get_status",
        "description": "Report the robot's own battery and motion state.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "play_gesture",
        "description": "Play one social gesture, such as a paw wave.",
        "parameters": {
            "type": "object",
            "properties": {"gesture": {"type": "string"}},
            "required": ["gesture"],
        },
    },
)


class ScrapeRefused(RuntimeError):
    """The scraper declined to run. Never downgraded into a partial run."""


class BudgetExceeded(ScrapeRefused):
    """A ceiling was crossed, or would be. Aborts the whole run."""


# ------------------------------------------------------------------- guards
def require_scrape_enabled(environ: Mapping[str, str] | None = None) -> None:
    """Two independent yeses: the flag, and a credential. Neither implies the other."""

    env = os.environ if environ is None else environ
    if str(env.get(SCRAPE_ENV, "")).strip() != "1":
        raise ScrapeRefused(
            f"the live scrape is off: set {SCRAPE_ENV}=1 to authorise it. "
            f"A corpus refresh spends real money and is an owner decision."
        )
    if not str(env.get(API_KEY_ENV, "")).strip():
        raise ScrapeRefused(
            f"no credential: environment variable {API_KEY_ENV} is unset or empty. "
            f"The key belongs in a file outside this repository (mode 600)."
        )


def guard_budget(
    *,
    estimate_usd: float,
    ceiling_usd: float = BUDGET_CEILING_USD,
    label: str = "preflight estimate",
) -> float:
    """Refuse anything at or above the ceiling. Returns the value it accepted.

    Called once before the first socket opens and again after every response.
    ``>=`` rather than ``>`` on purpose: a run that lands exactly on the limit
    has no headroom for the turn that is already in flight.
    """

    value = float(estimate_usd)
    if not value >= 0.0:
        raise BudgetExceeded(f"{label} is not a non-negative number: {estimate_usd!r}")
    if value >= float(ceiling_usd):
        raise BudgetExceeded(
            f"{label} ${value:.2f} meets or exceeds the ${float(ceiling_usd):.2f} hard "
            f"ceiling; aborting before anything is spent. This limit is not raisable "
            f"by a command-line flag."
        )
    return value


def spend_usd(usage: Mapping[str, int]) -> float:
    """Dollars for one response, from the provider's own usage block."""

    cached = int(usage.get("cached_tokens", 0) or 0)
    billed_input = max(0, int(usage.get("input_tokens", 0) or 0) - cached)
    output = int(usage.get("output_tokens", 0) or 0)
    return (
        billed_input * ASSUMED_INPUT_USD_PER_MTOK
        + cached * ASSUMED_CACHED_INPUT_USD_PER_MTOK
        + output * ASSUMED_OUTPUT_USD_PER_MTOK
    ) / 1_000_000.0


def estimate_thread_usd(scenario: Scenario) -> float:
    """Preflight estimate for one thread. Pessimistic by construction.

    Assumes zero cache hits and a full instruction re-send on every turn, which
    is the worst case the cost model has; a real run should land under it.
    """

    instructions = render_session_instructions(
        profile_id=scenario.si_profile, flags=scenario.flags
    ).text
    instruction_tokens = len(instructions) / CHARS_PER_TOKEN
    owner_tokens = sum(len(turn) for turn in scenario.owner_turns) / CHARS_PER_TOKEN
    turns = len(scenario.owner_turns)
    # Turn n carries the instructions plus every earlier turn: n(n+1)/2 growth.
    history_tokens = (owner_tokens + ASSUMED_REPLY_TOKENS * turns) * (turns + 1) / 2.0
    input_tokens = instruction_tokens * turns + history_tokens
    output_tokens = ASSUMED_REPLY_TOKENS * turns
    return (
        input_tokens * ASSUMED_INPUT_USD_PER_MTOK + output_tokens * ASSUMED_OUTPUT_USD_PER_MTOK
    ) / 1_000_000.0


def estimate_corpus_usd(scenarios: Sequence[Scenario]) -> float:
    return sum(estimate_thread_usd(scenario) for scenario in scenarios)


def _zero_usage() -> dict[str, int]:
    return dict.fromkeys(USAGE_KEYS, 0)


def _add_usage(total: dict[str, int], row: Mapping[str, int]) -> dict[str, int]:
    for key in USAGE_KEYS:
        total[key] += int(row.get(key, 0) or 0)
    return total


def _usage_from_response(payload: Mapping[str, Any]) -> dict[str, int]:
    """Normalise one ``response.done`` usage block into the corpus's five keys."""

    response = payload.get("response")
    body = response if isinstance(response, Mapping) else {}
    raw = body.get("usage")
    usage: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    detail_in = usage.get("input_token_details")
    detail_out = usage.get("output_token_details")
    detail_in = detail_in if isinstance(detail_in, Mapping) else {}
    detail_out = detail_out if isinstance(detail_out, Mapping) else {}
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "input_audio_tokens": int(detail_in.get("audio_tokens", 0) or 0),
        "output_audio_tokens": int(detail_out.get("audio_tokens", 0) or 0),
        "cached_tokens": int(detail_in.get("cached_tokens", 0) or 0),
    }


# -------------------------------------------------------------------- driver
def _session_payload(instructions: str, model: str) -> dict[str, Any]:
    # Shape verified ON THE WIRE 2026-08-17 (first live scrape attempt): the GA
    # API refuses a session object without "type": "realtime"
    # (missing_required_parameter), and turn_detection moved INSIDE
    # audio.input — top-level turn_detection is unknown_parameter. VAD is off
    # because the scraper drives turns itself with explicit response.create.
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": model,
            "instructions": instructions,
            "output_modalities": ["text"],
            "tools": [dict(schema) for schema in TOOL_SCHEMAS],
            "tool_choice": "auto",
            "audio": {"input": {"turn_detection": None}},
        },
    }


def _owner_item(text: str) -> dict[str, Any]:
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        },
    }


def _tool_output_item(call_id: str, name: str) -> dict[str, Any]:
    result = SYNTHETIC_TOOL_RESULTS.get(
        name, {"accepted": False, "note": f"synthetic world result: no script for {name}"}
    )
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(result, sort_keys=True),
        },
    }


def _drain(transport: Any, deadline: float) -> list[Mapping[str, Any]]:
    """Collect frames until ``response.done``, an error, or the deadline."""

    frames: list[Mapping[str, Any]] = []
    while time.monotonic() < deadline:
        frame = transport.receive()
        if frame is None:
            transport.wait(0.2)
            continue
        frames.append(frame)
        kind = str(frame.get("type", ""))
        if kind in {"response.done", "error"}:
            return frames
    raise ScrapeRefused(f"no response.done within {RESPONSE_TIMEOUT_S:.0f}s")


def _reply_text(frames: Sequence[Mapping[str, Any]]) -> str:
    """Concatenate whichever text-delta spelling the provider used."""

    parts: list[str] = []
    for frame in frames:
        kind = str(frame.get("type", ""))
        if kind in {"response.output_text.delta", "response.text.delta"}:
            delta = frame.get("delta")
            if isinstance(delta, str):
                parts.append(delta)
    return "".join(parts).strip()


def _tool_calls(frames: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []
    for frame in frames:
        if str(frame.get("type", "")) != "response.function_call_arguments.done":
            continue
        calls.append(
            {
                "call_id": str(frame.get("call_id", "")),
                "name": str(frame.get("name", "")),
                "arguments": str(frame.get("arguments", "") or "{}"),
            }
        )
    return calls


def scrape_thread(
    scenario: Scenario,
    *,
    model: str,
    spent_so_far: float,
    ceiling_usd: float = BUDGET_CEILING_USD,
) -> tuple[dict[str, Any], float]:
    """One thread, one socket. Returns (fixture payload, dollars spent here)."""

    from parcel_robot.realtime.ws_transport import WebSocketTransport

    rendered = render_session_instructions(profile_id=scenario.si_profile, flags=scenario.flags)
    di = render_developer_instruction(scenario.flags, version=DI_VERSION)
    transport = WebSocketTransport(model=model, name=scenario.thread_id).open()
    turns: list[dict[str, Any]] = []
    totals = _zero_usage()
    thread_spend = 0.0
    thread_deadline = time.monotonic() + THREAD_TIMEOUT_S
    try:
        transport.send(_session_payload(rendered.text, model))
        for index, owner_text in enumerate(scenario.owner_turns):
            transport.send(_owner_item(owner_text))
            # `response.done` is NOT success: under load the provider closes a
            # response with status "failed" (rate limiting) and ZERO usage, and
            # the first 25-thread run silently recorded 103 empty turns that
            # way (2026-08-18). Verify status and retry the response — the
            # owner item is already in the conversation, so a retry is just a
            # fresh response.create. A failed response bills nothing.
            frames: list[Mapping[str, Any]] = []
            status = ""
            for attempt in range(RESPONSE_ATTEMPTS):
                if attempt:
                    time.sleep(RETRY_BACKOFF_S * attempt)
                transport.send({"type": "response.create", "response": {}})
                frames = _drain(
                    transport, min(thread_deadline, time.monotonic() + RESPONSE_TIMEOUT_S)
                )
                done = next(
                    (f for f in reversed(frames) if str(f.get("type")) == "response.done"), None
                )
                if done is None:
                    raise ScrapeRefused(
                        f"{scenario.thread_id}: turn {index} ended without a response"
                    )
                body = done.get("response")
                status = (
                    str(body.get("status", "completed"))
                    if isinstance(body, Mapping)
                    else "completed"
                )
                usage = _usage_from_response(done)
                _add_usage(totals, usage)
                thread_spend += spend_usd(usage)
                # After EVERY response, not just at the end of a thread.
                guard_budget(
                    estimate_usd=spent_so_far + thread_spend,
                    ceiling_usd=ceiling_usd,
                    label=f"measured spend after {scenario.thread_id} turn {index}",
                )
                if status == "completed":
                    break
            if status != "completed":
                raise ScrapeRefused(
                    f"{scenario.thread_id}: turn {index} status {status!r} "
                    f"after {RESPONSE_ATTEMPTS} attempts"
                )
            calls = _tool_calls(frames)
            for call in calls:
                transport.send(_tool_output_item(call["call_id"], call["name"]))
            response_body = done.get("response")
            response_id = ""
            if isinstance(response_body, Mapping):
                response_id = str(response_body.get("id", ""))
            turns.append(
                {
                    "index": index,
                    "owner_item_id": f"item_owner_{scenario.thread_id}_{index:02d}",
                    "owner_text": owner_text,
                    "response_id": response_id or f"resp_{scenario.thread_id}_{index:02d}",
                    "robot_item_id": f"item_robot_{scenario.thread_id}_{index:02d}",
                    "robot_text": _reply_text(frames),
                    "tool_calls": calls,
                    "usage": usage,
                }
            )
    finally:
        transport.close()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "thread_id": scenario.thread_id,
        "title": scenario.title,
        "family": scenario.family,
        "probes": list(scenario.probes),
        "source": FIXTURE_SOURCE_SCRAPE,
        "model": model,
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "si_profile": scenario.si_profile,
        "si_version": SI_VERSION,
        "si_digest": rendered.si.digest,
        "di_version": DI_VERSION,
        "di_digest": di.digest,
        "di_flags": scenario.flags.as_dict(),
        "declared_tools": list(DECLARED_TOOLS),
        "turns": turns,
        "usage_totals": totals,
        "notes": "Captured live. Tool results were synthetic; no robot moved.",
    }
    return payload, thread_spend


def self_test() -> int:
    """Offline assertions about the guards. Cheap, and it needs no key.

    This is what a reviewer runs to confirm the two refusals still refuse. It
    is deliberately duplicated by ``tests/test_realtime_corpus_replay.py`` —
    the suite is the gate, this is the thing you can run in one line.
    """

    failures: list[str] = []

    try:
        require_scrape_enabled({})
    except ScrapeRefused:
        pass
    else:
        failures.append("require_scrape_enabled({}) did not refuse")

    try:
        require_scrape_enabled({SCRAPE_ENV: "1"})
    except ScrapeRefused:
        pass
    else:
        failures.append("require_scrape_enabled without a credential did not refuse")

    try:
        guard_budget(estimate_usd=BUDGET_CEILING_USD + 0.01)
    except BudgetExceeded:
        pass
    else:
        failures.append("guard_budget did not refuse an over-ceiling estimate")

    try:
        guard_budget(estimate_usd=BUDGET_CEILING_USD)
    except BudgetExceeded:
        pass
    else:
        failures.append("guard_budget did not refuse an exactly-at-ceiling estimate")

    try:
        guard_budget(estimate_usd=0.01)
    except BudgetExceeded:
        failures.append("guard_budget refused a clearly affordable estimate")

    for line in failures:
        print(f"SELF-TEST FAIL: {line}")
    if failures:
        return 1
    print(f"SELF-TEST OK: budget ceiling ${BUDGET_CEILING_USD:.2f}, both refusals hold")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=SCRAPE_MODEL)
    parser.add_argument("--dry-run", action="store_true", help="print the estimate and stop")
    parser.add_argument("--self-test", action="store_true", help="offline guard checks")
    parser.add_argument("--only", default="", help="comma-separated thread ids")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    scenarios = load_scenarios()
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        scenarios = tuple(s for s in scenarios if s.thread_id in wanted)
        if not scenarios:
            print("no scenario matched --only")
            return 2

    estimate = estimate_corpus_usd(scenarios)
    print(f"threads: {len(scenarios)}  model: {args.model}")
    print(f"preflight estimate: ${estimate:.2f}  hard ceiling: ${BUDGET_CEILING_USD:.2f}")
    print(
        "prices are an operator ESTIMATE, not a fetched price list "
        f"(in ${ASSUMED_INPUT_USD_PER_MTOK}/Mtok, out ${ASSUMED_OUTPUT_USD_PER_MTOK}/Mtok)"
    )
    guard_budget(estimate_usd=estimate)
    if args.dry_run:
        print("dry run: nothing was sent")
        return 0

    require_scrape_enabled()
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    written = 0
    for scenario in scenarios:
        payload, thread_spend = scrape_thread(scenario, model=args.model, spent_so_far=spent)
        spent += thread_spend
        path = FIXTURES_DIR / f"{scenario.thread_id}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1
        print(f"{scenario.thread_id}: {len(payload['turns'])} turns, ${thread_spend:.4f}")
    print(f"wrote {written} fixture(s); measured spend ${spent:.2f}")
    print("now regenerate the manifest: python build_manifest.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
