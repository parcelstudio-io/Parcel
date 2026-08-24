"""C9/C10 — the one paid run: does the fixed ledger agree with the provider?

    research/20260823/ambient-ear-cost-ladder/live.sh          (the only entry point)

NOTHING HERE OPENS A SOCKET WITHOUT BOTH GUARDS
-----------------------------------------------
``PARCEL_H1_LIVE=1`` and a credential already in the environment. The credential
is loaded by ``live.sh`` using the documented launcher mechanism
(``set -a; . ~/.config/parcel/realtime.env; set +a``); this file never reads that
path, never stores the value, and the transport it uses takes a variable NAME.

THE CEILING IS $2.00 AND IT IS CHECKED AFTER EVERY RESPONSE
-----------------------------------------------------------
Priced from the RAW usage block with the published rate card, not from an
estimate, and re-checked the instant each ``response.done`` lands. The ceiling
is a module constant. A flag that can raise a spending limit is not a limit.

WHAT IS ACTUALLY BEING MEASURED
-------------------------------
1. **The split.** Text and audio phases, so the ledger's per-modality pricing is
   exercised on real ``input_token_details`` / ``output_token_details``.
2. **C9.** Three dollar figures per response: (a) the raw usage block priced by
   the rate card with the provider's own cached split; (b) the LEDGER's figure,
   which sees only the flattened five-key row the lane appends and has to
   apportion the cached total across modalities; (c) the pre-H1 ASSUMED figure.
   (a) vs (b) is C9 — it measures the error the flattening introduces. (c) is
   the instrument fault this experiment exists to fix, quantified.
3. **Is silence billed?** The whole P0 projection rests on an open socket being
   charged for the audio it is streamed. The audio phase uploads a measured
   number of seconds of digital silence with server VAD on and reads back what
   the provider counted. If silence is free, P0's floor is wrong and the
   architecture question changes shape.
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Mapping, Sequence
from typing import Any

from ladder import RESULTS_DIR, write_result

from evals.companion.realtime_convo_v1.schema import load_fixtures
from parcel_robot.realtime.cost import MINI_RATE_CARD, realtime_spend_usd
from parcel_robot.realtime.prompting import render_session_instructions
from parcel_robot.realtime.protocol import parse_server_event
from parcel_robot.realtime.spend_ledger import SpendLedger

#: Hard ceiling for this experiment, from DESIGN.md row C10. Not a flag.
BUDGET_CEILING_USD = 2.00
MODEL = "gpt-realtime-2.1-mini"
RESPONSE_TIMEOUT_S = 60.0

#: Text phase: how many owner turns to drive in total, across the first few
#: corpus threads. Several threads rather than one, because a fresh socket per
#: thread is what the corpus captured and a growing cached history is exactly
#: where the split pricing has to be right.
TEXT_TURNS = 30
TEXT_THREADS = 5

#: Audio phase: seconds of digital silence streamed before the utterance, with
#: server VAD on. The measurement that says whether an open ear is billed.
SILENCE_S = 20.0
CHUNK_MS = 100.0
PCM_RATE_HZ = 24_000
#: Three spoken turns, not one: the audio split has to be seen more than once
#: before it is a measurement, and the second and third turns carry a cached
#: audio history the first one could not.
AUDIO_TURNS = 3


class LiveRefused(RuntimeError):
    """A guard said no. Always before a socket, or immediately after a response."""


def require_enabled() -> None:
    if os.environ.get("PARCEL_H1_LIVE") != "1":
        raise LiveRefused("live calibration needs PARCEL_H1_LIVE=1; nothing was opened")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise LiveRefused("no credential in the environment; run through live.sh")


def guard(spent_usd: float, label: str) -> None:
    if spent_usd >= BUDGET_CEILING_USD:
        raise LiveRefused(
            f"H1 ceiling reached: ${spent_usd:.4f} >= ${BUDGET_CEILING_USD:.2f} at {label}"
        )


def raw_usage(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The provider's usage block, verbatim, with nothing normalised away."""

    body = payload.get("response")
    body = body if isinstance(body, Mapping) else {}
    usage = body.get("usage")
    return dict(usage) if isinstance(usage, Mapping) else {}


def flat_row(payload: Mapping[str, Any]) -> dict[str, object]:
    """The five-key row the LANE appends — the ledger's real input shape."""

    event = parse_server_event(payload)
    return {"response_id": getattr(event, "response_id", ""), **event.usage.as_dict()}


def _drain(transport: Any, deadline: float) -> list[Mapping[str, Any]]:
    frames: list[Mapping[str, Any]] = []
    while time.monotonic() < deadline:
        frame = transport.receive()
        if frame is None:
            transport.wait(0.2)
            continue
        frames.append(frame)
        if str(frame.get("type", "")) in {"response.done", "error"}:
            return frames
    raise LiveRefused(f"no response.done within {RESPONSE_TIMEOUT_S:.0f}s")


def _text(frames: Sequence[Mapping[str, Any]]) -> str:
    parts = [
        str(f.get("delta", ""))
        for f in frames
        if str(f.get("type", "")) in {"response.output_text.delta", "response.text.delta"}
    ]
    return "".join(parts).strip()


def _session(instructions: str, *, modalities: list[str], vad: bool) -> dict[str, Any]:
    audio: dict[str, Any] = {"input": {"turn_detection": {"type": "server_vad"} if vad else None}}
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": MODEL,
            "instructions": instructions,
            "output_modalities": modalities,
            "audio": audio,
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


def record(
    responses: list[dict[str, object]],
    ledger: SpendLedger,
    legacy: SpendLedger,
    phase: str,
    payload: Mapping[str, Any],
) -> float:
    """Price one response three ways and append the row. Returns its rate-card $.

    A response_id already recorded is DROPPED and priced at zero. The transport
    buffers frames, and a drain that finds no new ``response.done`` will hand
    back the previous one; counting that twice would invent spend that never
    happened, in a file whose entire job is to be believed.
    """

    usage = raw_usage(payload)
    row = flat_row(payload)
    seen = {r.get("response_id") for r in responses}
    if row.get("response_id") and row["response_id"] in seen:
        return 0.0
    priced_raw = MINI_RATE_CARD.price(usage)
    priced_flat = MINI_RATE_CARD.price(row)
    ledger.record(row, session_id=f"h1_{phase}")
    legacy.record(row, session_id=f"h1_{phase}")
    responses.append(
        {
            "phase": phase,
            "response_id": row.get("response_id", ""),
            "raw_usage": usage,
            "flat_row": row,
            "usd_raw_split": round(priced_raw.usd, 8),
            "usd_raw_basis": priced_raw.basis,
            "usd_ledger_flat": round(priced_flat.usd, 8),
            "usd_ledger_basis": priced_flat.basis,
            "usd_assumed_legacy": round(realtime_spend_usd([row]), 8),
        }
    )
    return priced_raw.usd


def text_phase(responses: list[dict[str, object]], ledger, legacy, spent: float) -> float:
    from parcel_robot.realtime.ws_transport import WebSocketTransport

    driven = 0
    for fixture in load_fixtures()[:TEXT_THREADS]:
        if driven >= TEXT_TURNS:
            break
        instructions = render_session_instructions(
            profile_id=fixture.si_profile, flags=fixture.flags
        ).text
        transport = WebSocketTransport(model=MODEL, name=f"h1-{fixture.thread_id}").open()
        try:
            transport.send(_session(instructions, modalities=["text"], vad=False))
            for turn in fixture.turns:
                if driven >= TEXT_TURNS:
                    break
                guard(spent, f"{fixture.thread_id} turn {turn.index}")
                transport.send(_owner_item(turn.owner_text))
                transport.send({"type": "response.create", "response": {}})
                frames = _drain(transport, time.monotonic() + RESPONSE_TIMEOUT_S)
                done = next(
                    (f for f in reversed(frames) if str(f.get("type")) == "response.done"), None
                )
                if done is None:
                    raise LiveRefused(f"{fixture.thread_id} turn {turn.index}: no response.done")
                spent += record(responses, ledger, legacy, "text", done)
                responses[-1]["owner_text"] = turn.owner_text
                responses[-1]["reply_text"] = _text(frames)[:400]
                driven += 1
                print(
                    f"  text {fixture.thread_id}#{turn.index} ${spent:.4f} "
                    f"{_text(frames)[:56]!r}",
                    flush=True,
                )
        finally:
            transport.close()
    return spent


def audio_phase(
    responses: list[dict[str, object]],
    ledger,
    legacy,
    spent: float,
    *,
    silence_s: float = SILENCE_S,
    label: str = "audio",
    turns: int = AUDIO_TURNS,
) -> float:
    """Stream measured silence, then utterances, and read what was counted.

    Run twice with different ``silence_s`` — that pair IS the "is an open ear
    billed?" measurement, and it is the load-bearing assumption under every P0
    number. One session cannot answer it; two identical sessions differing only
    in how much silence preceded the same utterance can.
    """

    from ladder import ACOUSTIC_DIR
    from vad_gate import read_wav_16k

    from parcel_robot.realtime.audio_gateway import RationalResampler
    from parcel_robot.realtime.ws_transport import WebSocketTransport

    fixture = load_fixtures()[0]
    instructions = render_session_instructions(
        profile_id=fixture.si_profile, flags=fixture.flags
    ).text
    clip16k = read_wav_16k(ACOUSTIC_DIR / "fixtures" / "query_01.wav")
    pcm = RationalResampler(from_hz=16_000, to_hz=PCM_RATE_HZ).process_pcm16(clip16k.tobytes())
    chunk_bytes = int(PCM_RATE_HZ * CHUNK_MS / 1000.0) * 2
    silence_chunks = int(silence_s * 1000.0 / CHUNK_MS)

    transport = WebSocketTransport(model=MODEL, name=f"h1-{label}").open()
    try:
        transport.send(_session(instructions, modalities=["audio"], vad=True))
        time.sleep(1.0)
        for _ in range(silence_chunks):
            transport.send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(b"\x00\x00" * (chunk_bytes // 2)).decode("ascii"),
                }
            )
            time.sleep(0.01)
        # Whatever the provider did with that silence, ask for nothing yet:
        # drain any frames it volunteered (speech_started would mean the VAD
        # fired on digital silence, which would itself be a finding).
        silence_frames = []
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            frame = transport.receive()
            if frame is None:
                transport.wait(0.2)
                continue
            silence_frames.append(str(frame.get("type", "")))
        print(f"  {label}: after {silence_s:.0f}s of silence: {sorted(set(silence_frames))}", flush=True)

        for utterance in range(turns):
            guard(spent, f"{label} utterance {utterance}")
            for offset in range(0, len(pcm), chunk_bytes):
                transport.send(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(
                            pcm[offset : offset + chunk_bytes]
                        ).decode("ascii"),
                    }
                )
                time.sleep(0.01)
            # Trailing silence so SERVER VAD closes the turn and creates the
            # response itself. No manual commit and no response.create: this
            # phase measures P0's actual mechanism, not one driven by hand.
            for _ in range(int(1500.0 / CHUNK_MS)):
                transport.send(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(b"\x00\x00" * (chunk_bytes // 2)).decode(
                            "ascii"
                        ),
                    }
                )
                time.sleep(0.01)
            frames = _drain(transport, time.monotonic() + RESPONSE_TIMEOUT_S)
            done = next(
                (f for f in reversed(frames) if str(f.get("type")) == "response.done"), None
            )
            if done is None:
                raise LiveRefused(f"audio utterance {utterance} ended without response.done")
            before = len(responses)
            spent += record(responses, ledger, legacy, label, done)
            if len(responses) == before:
                print(f"  {label} {utterance}: no NEW response (duplicate frame)", flush=True)
                continue
            responses[-1]["silence_uploaded_s"] = silence_s if utterance == 0 else 1.5
            responses[-1]["utterance_s"] = round(len(pcm) / 2 / PCM_RATE_HZ, 3)
            responses[-1]["audio_uploaded_s"] = round(
                (silence_s if utterance == 0 else 1.5) + len(pcm) / 2 / PCM_RATE_HZ + 1.5, 3
            )
            responses[-1]["frames_during_silence"] = sorted(set(silence_frames))
            print(
                f"  {label} {utterance} ${spent:.4f} "
                f"in={responses[-1]['flat_row']['input_audio_tokens']} audio tok "
                f"for {responses[-1]['audio_uploaded_s']}s uploaded",
                flush=True,
            )
    finally:
        transport.close()
    return spent


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phases",
        default="text,silence,nosilence",
        help="comma list of phases to run: text, silence, nosilence",
    )
    args = parser.parse_args()
    phases = {p.strip() for p in args.phases.split(",") if p.strip()}
    require_enabled()
    ledger_path = RESULTS_DIR / "live_spend_v2.jsonl"
    legacy_path = RESULTS_DIR / "live_spend_v1.jsonl"
    ledger = SpendLedger(ledger_path, rate_card=MINI_RATE_CARD)
    legacy = SpendLedger(legacy_path)

    responses: list[dict[str, object]] = []
    spent = 0.0
    failure = ""
    try:
        if "text" in phases:
            spent = text_phase(responses, ledger, legacy, spent)
        if "silence" in phases:
            spent = audio_phase(
                responses, ledger, legacy, spent, silence_s=60.0, label="audio_60s_silence"
            )
        if "nosilence" in phases:
            spent = audio_phase(
                responses, ledger, legacy, spent, silence_s=0.0, label="audio_no_silence"
            )
    except LiveRefused as error:
        failure = str(error)
        print(f"STOPPED: {error}", flush=True)
    finally:
        raw_total = sum(float(r["usd_raw_split"]) for r in responses)
        ledger_total = sum(float(r["usd_ledger_flat"]) for r in responses)
        assumed_total = sum(float(r["usd_assumed_legacy"]) for r in responses)
        payload = {
            "harness": "live_calibration",
            "model": MODEL,
            "ceiling_usd": BUDGET_CEILING_USD,
            "responses": len(responses),
            "usd_raw_split_total": round(raw_total, 6),
            "usd_ledger_flat_total": round(ledger_total, 6),
            "usd_assumed_legacy_total": round(assumed_total, 6),
            "ledger_vs_raw_error_pct": (
                round((ledger_total - raw_total) / raw_total * 100.0, 3) if raw_total else None
            ),
            "assumed_vs_raw_error_pct": (
                round((assumed_total - raw_total) / raw_total * 100.0, 3) if raw_total else None
            ),
            "ledger_month_to_date": ledger.month_to_date(force=True).as_dict(),
            "legacy_month_to_date": legacy.month_to_date(force=True).as_dict(),
            "phases": sorted(phases),
            "stopped_because": failure,
            "rows": responses,
        }
        write_result("live_calibration.json", payload)
        print(json.dumps({k: v for k, v in payload.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
