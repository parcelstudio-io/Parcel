#!/usr/bin/env python
"""Build the frozen corpus for evals/companion/acoustic_loop_v1.

WHY TTS-BUILT TEST SPEECH
    Ground-truth turn ends are the whole endpointing measurement, and human
    recordings do not come with them. Synthesizing the corpus is the published
    FD-Bench methodology: the utterance is known, the pause structure is
    constructed, and the turn end is derived by one pinned algorithm instead of
    by annotation. The cost is that this is synthetic speech — see the pack
    README's does_not_prove list.

DETERMINISM
    Piper is a VITS model and samples noise by default. ``--noise_scale 0
    --noise_w 0`` removes both sources, so a rebuild on the same pinned voice
    reproduces the same waveform. Regeneration is still not the contract: the
    fixtures are FROZEN artifacts pinned by sha256 in manifest.json, and the
    runner verifies those pins before it measures anything.

GROUND TRUTH
    ``speech_end_s`` is the end of the last Silero-VAD speech frame, computed
    offline with the same pinned models/endpointing/silero_vad_v6.onnx the
    runtime uses. Deriving it from the model under test would be circular, so
    note carefully what it is and is not: it is an acoustic tail marker, not a
    linguistic turn boundary. Endpointing latency is measured against it
    because the alternative (waveform end) includes the synthesizer's trailing
    silence and would flatter every number.

USAGE
    .parcel/bin/python scripts/build_acoustic_corpus.py            # build
    .parcel/bin/python scripts/build_acoustic_corpus.py --freeze   # + rewrite pins
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "evals" / "companion" / "acoustic_loop_v1" / "fixtures"
PIPER_BIN = REPO_ROOT / "third_party" / "piper" / "piper"
PIPER_VOICE = REPO_ROOT / "models" / "piper" / "voice.onnx"
SILERO = REPO_ROOT / "models" / "endpointing" / "silero_vad_v6.onnx"

VOICE_RATE_HZ = 22_050
ANALYSIS_RATE_HZ = 16_000
SILERO_FRAME = 512
SILERO_SPEECH_THRESHOLD = 0.5
RNG_SEED = 20260804

# kind, name, text, internal pause (s) split marker "||" inside the text
CORPUS: tuple[tuple[str, str, str], ...] = (
    # --- complete turns: a well-formed sentence that clearly ends ----------
    ("complete", "complete_01", "Let's walk to the park bench by the fountain."),
    ("complete", "complete_02", "Can you follow me down the block?"),
    ("complete", "complete_03", "Stop right there and wait for me."),
    ("complete", "complete_04", "What is the weather like this afternoon?"),
    ("complete", "complete_05", "Turn around and look at the red door."),
    ("complete", "complete_06", "Thank you, that is exactly what I needed."),
    # --- incomplete turns: trail off mid-clause; must NOT commit early -----
    ("incomplete", "incomplete_01", "I was thinking that maybe we could"),
    ("incomplete", "incomplete_02", "Could you take me to the"),
    ("incomplete", "incomplete_03", "The thing I wanted to ask you about is"),
    ("incomplete", "incomplete_04", "Let's go over to the corner and then"),
    # --- pause-heavy: a real mid-utterance silence the endpointer must ride
    ("pause_heavy", "pause_01", "Walk to the bench || and then wait for me there."),
    ("pause_heavy", "pause_02", "I need you to || follow me to the car."),
    ("pause_heavy", "pause_03", "Give me a second || okay, let's head home now."),
    # --- barge-in material --------------------------------------------------
    (
        "robot_long",
        "robot_long_01",
        (
            "There are several routes we could take from here. The first one follows "
        "the main avenue past the bakery and the flower shop, which is the "
        "flattest path and takes about eight minutes at a comfortable walking "
        "pace. The second route cuts through the park, which is quieter and "
            "shaded, but it does involve a short set of stairs near the north gate."
        ),
    ),
    ("interrupt", "interrupt_01", "Wait, stop."),
    ("interrupt", "interrupt_02", "Actually, never mind that."),
    # --- expressive reply for the prosody / nod-sync case -------------------
    (
        "expressive",
        "expressive_01",
        (
            "Yes! That is a great idea. We should absolutely do that today, and I "
            "think you will really enjoy the walk."
        ),
    ),
    # --- duplex query material ---------------------------------------------
    ("query", "query_01", "Where are we going next?"),
    ("query", "query_02", "How far is it from here?"),
    ("query", "query_03", "Is the park still open right now?"),
)

PAUSE_GAP_S = 0.75
LEAD_SILENCE_S = 0.30
TAIL_SILENCE_S = 0.60


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def piper_say(text: str) -> np.ndarray:
    """Synthesize one phrase to int16 PCM at the voice's native rate."""

    result = subprocess.run(
        [
            str(PIPER_BIN),
            "--model",
            str(PIPER_VOICE),
            "--output-raw",
            "--noise_scale",
            "0",
            "--noise_w",
            "0",
        ],
        input=text.encode("utf-8"),
        capture_output=True,
        check=True,
        timeout=180,
    )
    pcm = np.frombuffer(result.stdout, dtype=np.int16)
    if pcm.size == 0:
        raise RuntimeError(f"piper produced no audio for {text!r}")
    return pcm


def silence(seconds: float, rate: int = VOICE_RATE_HZ) -> np.ndarray:
    return np.zeros(int(seconds * rate), dtype=np.int16)


def build_utterance(text: str) -> np.ndarray:
    """Synthesize, honouring the ``||`` internal-pause marker."""

    parts = [segment.strip() for segment in text.split("||")]
    chunks: list[np.ndarray] = [silence(LEAD_SILENCE_S)]
    for index, part in enumerate(parts):
        if index:
            chunks.append(silence(PAUSE_GAP_S))
        chunks.append(piper_say(part))
    chunks.append(silence(TAIL_SILENCE_S))
    return np.concatenate(chunks)


def resample_to_16k(pcm: np.ndarray) -> np.ndarray:
    """22.05 kHz -> 16 kHz with a windowed-sinc lowpass, for Silero only."""

    ratio = ANALYSIS_RATE_HZ / VOICE_RATE_HZ
    taps = 101
    cutoff = 0.5 * ratio  # normalized to the source rate's Nyquist
    n = np.arange(taps) - (taps - 1) / 2
    kernel = np.sinc(2 * cutoff * n) * np.hanning(taps)
    kernel /= kernel.sum()
    filtered = np.convolve(pcm.astype(np.float64), kernel, mode="same")
    out_len = int(pcm.size * ratio)
    source_index = np.arange(out_len) / ratio
    resampled = np.interp(source_index, np.arange(pcm.size), filtered)
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def silero_speech_bounds(pcm16k: np.ndarray) -> tuple[float | None, float | None]:
    """(first, last) speech-frame times in seconds, from the pinned Silero."""

    from parcel_robot.endpointing import SileroVad

    vad = SileroVad(str(SILERO))
    if not vad.available:
        raise RuntimeError(f"Silero model unavailable at {SILERO}")
    speech_frames: list[int] = []
    total = pcm16k.size // SILERO_FRAME
    for index in range(total):
        window = pcm16k[index * SILERO_FRAME : (index + 1) * SILERO_FRAME]
        if float(vad.process(window)) >= SILERO_SPEECH_THRESHOLD:
            speech_frames.append(index)
    if not speech_frames:
        return None, None
    start = speech_frames[0] * SILERO_FRAME / ANALYSIS_RATE_HZ
    end = (speech_frames[-1] + 1) * SILERO_FRAME / ANALYSIS_RATE_HZ
    return start, end


def write_wav(path: Path, pcm: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm.tobytes())


def build_noise(name: str, seed: int, seconds: float = 3.0) -> np.ndarray:
    """Non-speech noise for the false-barge-in case.

    Deliberately NOT white noise: a shaped, amplitude-modulated band of energy
    at conversational level is what actually fools an energy VAD, so it is the
    honest negative control.
    """

    rng = np.random.default_rng(seed)
    samples = int(seconds * VOICE_RATE_HZ)
    raw = rng.normal(0.0, 1.0, samples)
    # crude bandpass 300-3000 Hz via difference-of-moving-averages
    def smooth(signal: np.ndarray, width: int) -> np.ndarray:
        kernel = np.ones(width) / width
        return np.convolve(signal, kernel, mode="same")

    band = smooth(raw, 7) - smooth(raw, 73)
    envelope = 0.5 + 0.5 * np.sin(
        2 * np.pi * 2.5 * np.arange(samples) / VOICE_RATE_HZ
    )
    shaped = band * envelope
    peak = float(np.max(np.abs(shaped))) or 1.0
    scaled = (shaped / peak) * 6000.0
    del name
    return np.concatenate(
        [silence(LEAD_SILENCE_S), scaled.astype(np.int16), silence(TAIL_SILENCE_S)]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="rewrite fixtures/corpus.json with the freshly measured pins",
    )
    args = parser.parse_args()

    for required in (PIPER_BIN, PIPER_VOICE, SILERO):
        if not required.exists():
            print(f"missing prerequisite: {required}", file=sys.stderr)
            return 1

    FIXTURES.mkdir(parents=True, exist_ok=True)
    entries = []

    for kind, name, text in CORPUS:
        pcm = build_utterance(text)
        path = FIXTURES / f"{name}.wav"
        write_wav(path, pcm, VOICE_RATE_HZ)
        analysis = resample_to_16k(pcm)
        start, end = silero_speech_bounds(analysis)
        if end is None:
            print(f"WARNING: no speech detected in {name}", file=sys.stderr)
        entries.append(
            {
                "name": name,
                "kind": kind,
                "text": text,
                "file": f"fixtures/{name}.wav",
                "sha256": sha256_of(path),
                "sample_rate_hz": VOICE_RATE_HZ,
                "duration_s": round(pcm.size / VOICE_RATE_HZ, 6),
                "speech_start_s": round(start, 6) if start is not None else None,
                "speech_end_s": round(end, 6) if end is not None else None,
                "has_internal_pause": "||" in text,
            }
        )
        print(
            f"  {name:16s} {kind:12s} {pcm.size / VOICE_RATE_HZ:6.2f}s  "
            f"speech {start:.2f}-{end:.2f}s"
            if end is not None
            else f"  {name:16s} {kind:12s} (no speech)"
        )

    for index, noise_name in enumerate(("noise_01", "noise_02")):
        pcm = build_noise(noise_name, RNG_SEED + index)
        path = FIXTURES / f"{noise_name}.wav"
        write_wav(path, pcm, VOICE_RATE_HZ)
        entries.append(
            {
                "name": noise_name,
                "kind": "noise",
                "text": "",
                "file": f"fixtures/{noise_name}.wav",
                "sha256": sha256_of(path),
                "sample_rate_hz": VOICE_RATE_HZ,
                "duration_s": round(pcm.size / VOICE_RATE_HZ, 6),
                "speech_start_s": None,
                "speech_end_s": None,
                "has_internal_pause": False,
            }
        )
        print(f"  {noise_name:16s} noise        {pcm.size / VOICE_RATE_HZ:6.2f}s")

    corpus = {
        "schema_version": 1,
        "generator": "scripts/build_acoustic_corpus.py",
        "rng_seed": RNG_SEED,
        "voice": "en_US-lessac-medium (models/piper/voice.onnx)",
        "voice_sha256": sha256_of(PIPER_VOICE),
        "piper_binary_sha256": sha256_of(PIPER_BIN),
        "piper_flags": ["--noise_scale", "0", "--noise_w", "0"],
        "ground_truth_method": (
            "last Silero v6.2 speech frame (threshold 0.5, 512-sample windows) "
            "over a 16 kHz windowed-sinc resample of the fixture"
        ),
        "silero_sha256": sha256_of(SILERO),
        "lead_silence_s": LEAD_SILENCE_S,
        "tail_silence_s": TAIL_SILENCE_S,
        "internal_pause_s": PAUSE_GAP_S,
        "utterances": entries,
    }
    out = FIXTURES / "corpus.json"
    if args.freeze or not out.exists():
        out.write_text(json.dumps(corpus, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {out} ({len(entries)} utterances)")
    else:
        print(f"\n{out} left alone (pass --freeze to rewrite)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
