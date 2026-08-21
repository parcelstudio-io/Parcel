#!/usr/bin/env python
"""Synthesize the corpus's IMPOSTOR category — voices that are not the owner's.

Card F1-SI, work item 5. The corpus's other 52 rows are the owner speaking; this
generates the rows that are somebody else, so the replay harness can measure the
thing the card is actually about: **does an unrecognised voice get refused, and
does its emergency phrase still latch?**

    evals/20260820/voice_corpus_v1/make_impostor_wavs.py           # write NN_*.wav
    evals/20260820/voice_corpus_v1/make_impostor_wavs.py --list    # show, write nothing

WHY SYNTHETIC, AND WHAT THAT COSTS
----------------------------------
There is no second household member on file, and recording one is an owner
action with somebody else's consent attached. espeak-ng is available on this
host, deterministic, free, and — measured — a HARDER impostor than a real human
in one specific way and an easier one in another:

* harder: the two espeak voices speaking the SAME sentence were the closest
  cross-speaker pair in the whole bench (cosine 0.431 for `en+m3` vs `en+f4`,
  ``bench_doa.md`` Bench B), because they share a synthesis engine AND content;
* easier: synthetic speech has no room, no distance and no channel, so it does
  not exercise the acoustic conditions a television actually arrives in.

Neither of those is the television, and this file does not pretend otherwise.
It is the impostor set that can exist today; a real non-owner recording is on
the owner-gated list.

The WAVs are gitignored (``/evals/20260820/voice_corpus_v1/*.wav``) — this
script is the committed artifact, and it is deterministic, so the corpus is
reproducible without carrying audio in the tree.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUERIES = HERE / "queries.tsv"

#: espeak-ng voice per corpus row. Two distinct impostors rather than one, so a
#: run cannot pass by memorising a single timbre — and deliberately NOT the
#: owner's own recording conditions.
VOICES = {
    "impostor": "en+m3",
    "impostor-estop": "en+f4",
}

#: The rate espeak reports at init. Recorded into the WAV header verbatim; the
#: gateway and the replay harness both resample, and the embedder is told the
#: rate rather than guessing it.
_ESPEAK_AUDIO_OUTPUT_RETRIEVAL = 1


def impostor_rows() -> list[tuple[str, str, str]]:
    """``(id, category, text)`` for every impostor row in the corpus TSV."""

    rows: list[tuple[str, str, str]] = []
    for line in QUERIES.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        identifier, category, text = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if category in VOICES:
            rows.append((identifier, category, text))
    return rows


def synthesize(rows: list[tuple[str, str, str]], out_dir: Path) -> int:
    try:
        lib = ctypes.CDLL("libespeak-ng.so.1")
    except OSError as error:
        print(f"espeak-ng is not available on this host ({error})", file=sys.stderr)
        return 2
    lib.espeak_Initialize.restype = ctypes.c_int
    rate = lib.espeak_Initialize(_ESPEAK_AUDIO_OUTPUT_RETRIEVAL, 0, None, 0)
    if rate <= 0:
        print(f"espeak_Initialize returned {rate}", file=sys.stderr)
        return 2

    chunks: list[bytes] = []
    callback_type = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p
    )

    def _on_audio(samples, count, _events):  # pragma: no cover - C callback
        if count > 0 and samples:
            chunks.append(bytes(ctypes.string_at(samples, count * 2)))
        return 0

    callback = callback_type(_on_audio)
    lib.espeak_SetSynthCallback(callback)
    lib.espeak_Synth.argtypes = [
        ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    for identifier, category, text in rows:
        chunks.clear()
        voice = VOICES[category]
        if lib.espeak_SetVoiceByName(voice.encode()) != 0:
            print(f"espeak has no voice {voice!r}", file=sys.stderr)
            return 2
        payload = text.encode()
        lib.espeak_Synth(payload, len(payload) + 1, 0, 1, 0, 0, None, None)
        lib.espeak_Synchronize()
        pcm = b"".join(chunks)
        target = out_dir / f"{identifier}_{category}.wav"
        with wave.open(str(target), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(pcm)
        seconds = len(pcm) / 2 / rate
        print(f"  {target.name:24s} {voice:6s} {seconds:5.2f}s  {text!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(HERE), help="where the WAVs land")
    parser.add_argument("--list", action="store_true", help="print the rows and stop")
    args = parser.parse_args(argv)

    rows = impostor_rows()
    if not rows:
        print("no impostor rows in queries.tsv", file=sys.stderr)
        return 1
    if args.list:
        for identifier, category, text in rows:
            print(f"{identifier}\t{category}\t{VOICES[category]}\t{text}")
        return 0
    print(f"synthesizing {len(rows)} impostor utterance(s):")
    return synthesize(rows, Path(args.out).expanduser())


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
