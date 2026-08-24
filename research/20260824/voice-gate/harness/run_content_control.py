#!/usr/bin/env python
"""The control the espeak content rows need: the same words in a neural voice.

``run_content.py`` scored critical slots at 0.700 and the wake phrase at 0.542,
and the transcripts say why: espeak says "lampost" for lamppost and "Pausell"
for Parcel. Those rows measure the PROXY VOICE at least as much as they measure
the gate and the transcriber, and a study that reported them as a pipeline
result would be blaming the wrong component.

So the same sentences are re-synthesized with ``models/piper/voice.onnx`` — a
neural voice, and the only other TTS on this host — and put through the same
channel, the same gate and the same transcriber. The gap between the two runs is
the proxy's contribution; neither number is the owner's real voice, which is not
on this disk.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from .arena import GEOMETRIES
from .asr import WhisperClient
from .corpus import CRITICAL_SLOT_TURNS, WAKE_PHRASES, normalize_peak, pad, piper_say
from .gate import GateConfig, Placement, run_gate, vad_only_arm
from .rows import overlaps
from .run_arms import WAKE_TOKENS
from .run_content import normalize
from .session import RATE_HZ, load_bed, speech_level_dbfs, write_result
from .tapes import Item, build_tape


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()

    bed = load_bed(args.tape)
    level = speech_level_dbfs(bed)
    scratch = args.scratch / "piper_control"
    scratch.mkdir(parents=True, exist_ok=True)

    items: list[Item] = []
    for geometry in (GEOMETRIES[0], GEOMETRIES[4]):
        for index, (kind, slot, text) in enumerate(CRITICAL_SLOT_TURNS):
            samples = normalize_peak(pad(piper_say(text, scratch)))
            items.append(
                Item(f"pslot_{index}_{geometry.label}", f"slot:{kind}:{slot}", "piper",
                     text, samples, geometry)
            )
        for index, phrase in enumerate(WAKE_PHRASES):
            samples = normalize_peak(pad(piper_say(phrase, scratch)))
            items.append(
                Item(f"pwake_{index}_{geometry.label}", "wake", "piper", phrase,
                     samples, geometry)
            )
    tape = build_tape(items, bed, speech_dbfs_at_1m=level)

    client = WhisperClient()
    if not client.available():
        raise SystemExit("whisper-server is not answering on 127.0.0.1:8099")
    admissions, _transport = run_gate(tape, vad_only_arm, config=GateConfig())

    def window(placement: Placement) -> np.ndarray | None:
        span = next(
            (
                admission
                for admission in admissions
                if admission.admitted
                and overlaps(admission, placement.speech_start_s, placement.speech_end_s)
            ),
            None,
        )
        if span is None:
            return None
        return tape.samples[int(span.upload_from_s * RATE_HZ) : int(span.close_s * RATE_HZ)]

    slot_hits: dict[str, list[int]] = {}
    slot_rows = []
    wake_hits = 0
    wake_rows = []
    for placement in tape.placements:
        chunk = window(placement)
        text = "" if chunk is None else client.transcribe(chunk.astype(float) / 32768.0).text
        if placement.role == "wake":
            hit = int(any(token in normalize(text) for token in WAKE_TOKENS))
            wake_hits += hit
            wake_rows.append({"name": placement.name, "hit": hit, "text": text.strip()})
            continue
        _, kind, slot = placement.role.split(":", 2)
        hit = int(slot in normalize(text))
        slot_hits.setdefault(kind, []).append(hit)
        slot_rows.append({"name": placement.name, "slot": slot, "hit": hit, "text": text.strip()})

    total = [value for values in slot_hits.values() for value in values]
    wake_n = sum(1 for placement in tape.placements if placement.role == "wake")
    payload = {
        "tier": "replay",
        "hosted_usd": 0.0,
        "voice": "models/piper/voice.onnx (en_US-lessac-medium) — the CONTROL for espeak",
        "critical_slot": {
            "n": len(total),
            "hits": sum(total),
            "accuracy": sum(total) / len(total) if total else float("nan"),
            "by_kind": {
                kind: {"n": len(values), "hits": sum(values), "accuracy": sum(values) / len(values)}
                for kind, values in sorted(slot_hits.items())
            },
            "rows": slot_rows,
        },
        "wake_phrase": {
            "n": wake_n,
            "hits": wake_hits,
            "detection_rate": wake_hits / wake_n if wake_n else float("nan"),
            "rows": wake_rows,
        },
    }
    path = write_result("content_control_piper.json", payload)
    print(
        f"piper control: slots {payload['critical_slot']['accuracy']:.3f} "
        f"(n={payload['critical_slot']['n']}), wake "
        f"{payload['wake_phrase']['detection_rate']:.3f} (n={wake_n}) -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
