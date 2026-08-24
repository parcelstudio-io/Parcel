#!/usr/bin/env python
"""Rows about WORDS: critical slots and the wake phrase's own hit rate.

Critical-slot accuracy (>= 0.95) asks a narrower question than word error rate:
when the owner names a place, the dog, or the stop word, does the slot survive
the gate and the local transcriber? A turn whose every other word is wrong but
whose place name is right is a turn the dog can act on; the reverse is not.

Scored on the ADMITTED window — pre-roll included, hangover included — because
that is the audio a decision would actually be made from.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from .arena import build as build_arena
from .asr import WhisperClient
from .gate import GateConfig, run_gate, vad_only_arm
from .rows import overlaps
from .run_arms import WAKE_TOKENS
from .session import RATE_HZ, load_bed, load_manifest, speech_level_dbfs, write_result


def normalize(text: str) -> str:
    return re.sub(r"[^a-z ]+", " ", text.lower())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tape", type=Path, required=True)
    args = parser.parse_args()

    manifest = load_manifest()
    bed = load_bed(args.tape)
    arena = build_arena(manifest, bed, speech_level_dbfs(bed))
    client = WhisperClient()
    if not client.available():
        raise SystemExit("whisper-server is not answering on 127.0.0.1:8099")

    slot_admissions, _ = run_gate(arena.slots, vad_only_arm, config=GateConfig())
    per_kind: dict[str, list[int]] = {}
    rows = []
    for placement in arena.slots.placements:
        span = next(
            (
                admission
                for admission in slot_admissions
                if admission.admitted
                and overlaps(admission, placement.speech_start_s, placement.speech_end_s)
            ),
            None,
        )
        _, kind, slot = placement.role.split(":", 2)
        if span is None:
            per_kind.setdefault(kind, []).append(0)
            rows.append({"name": placement.name, "slot": slot, "hit": 0, "text": "<not admitted>"})
            continue
        start = int(span.upload_from_s * RATE_HZ)
        end = int(span.close_s * RATE_HZ)
        transcript = client.transcribe(arena.slots.samples[start:end].astype(float) / 32768.0)
        hit = int(slot in normalize(transcript.text))
        per_kind.setdefault(kind, []).append(hit)
        rows.append(
            {"name": placement.name, "slot": slot, "hit": hit, "text": transcript.text.strip()}
        )

    wake_admissions, _ = run_gate(arena.wake, vad_only_arm, config=GateConfig())
    wake_hits = 0
    wake_rows = []
    for placement in arena.wake.placements:
        span = next(
            (
                admission
                for admission in wake_admissions
                if admission.admitted
                and overlaps(admission, placement.speech_start_s, placement.speech_end_s)
            ),
            None,
        )
        if span is None:
            wake_rows.append({"name": placement.name, "hit": 0, "text": "<not admitted>"})
            continue
        start = int(span.upload_from_s * RATE_HZ)
        end = int(span.close_s * RATE_HZ)
        transcript = client.transcribe(arena.wake.samples[start:end].astype(float) / 32768.0)
        hit = int(any(token in transcript.normalized for token in WAKE_TOKENS))
        wake_hits += hit
        wake_rows.append({"name": placement.name, "hit": hit, "text": transcript.text.strip()})

    total = [value for values in per_kind.values() for value in values]
    payload = {
        "tier": "replay",
        "hosted_usd": 0.0,
        "asr": "whisper.cpp base.en, resident, 8 threads, 127.0.0.1:8099",
        "critical_slot": {
            "n": len(total),
            "hits": sum(total),
            "accuracy": sum(total) / len(total) if total else float("nan"),
            "by_kind": {
                kind: {"n": len(values), "hits": sum(values), "accuracy": sum(values) / len(values)}
                for kind, values in sorted(per_kind.items())
            },
            "rows": rows,
        },
        "wake_phrase": {
            "n": len(arena.wake.placements),
            "hits": wake_hits,
            "detection_rate": wake_hits / len(arena.wake.placements),
            "tokens": list(WAKE_TOKENS),
            "rows": wake_rows,
        },
        "voice_note": (
            "content rows use espeak-ng voices because arbitrary words cannot be put in the "
            "mouth of the only real speech on this host; the identity rows use the real "
            "voices instead"
        ),
    }
    path = write_result("content.json", payload)
    print(
        f"critical slots {payload['critical_slot']['accuracy']:.3f} "
        f"(n={payload['critical_slot']['n']}), wake "
        f"{payload['wake_phrase']['detection_rate']:.3f} -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
