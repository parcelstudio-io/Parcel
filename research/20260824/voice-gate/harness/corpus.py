#!/usr/bin/env python
"""Every sound VOICE-GATE can present on this host, and what each one honestly is.

    corpus.py --out <dir>            # synthesize, cut and write manifest.json

WHAT THIS HOST ACTUALLY HAS
---------------------------
No loudspeaker except the array's own DAC (measured: the two other ALSA cards
report every non-``off`` profile ``available: no``, and no Bluetooth sink is
paired). A stimulus therefore cannot be presented *through air* — playing the
owner through the robot's own speaker would hand the XVF3800's on-chip AEC its
own reference and cancel the very thing being measured. So every source below
is a file, mixed against the REAL room floor recorded from the array, and the
evidence tier of anything built on it is ``replay``, never ``desktop-real-sensor``.

THE FOUR VOICE FAMILIES, AND WHY EACH ONE IS HERE
-------------------------------------------------
``real``      the six human voice prompts shipped with ``models/csm-1b`` — the
              only genuine human speech on this host. Fixed content, so they
              carry the IDENTITY rows (owner recall, impostor false accept) and
              nothing else.
``espeak``    formant synthesis, many voices, arbitrary content: the CONTENT
              rows (spoken STOP, wake phrase, critical slots). ``queries.tsv``'s
              own impostor rows already use ``en+m3``/``en+f4``, so the corpus
              day's choice is kept.
``piper``     ``models/piper/voice.onnx`` — the robot's OWN voice. Self-speech
              rows only; never an "owner", because a robot that answers its own
              voice is the failure the self-speech rows look for.
``noise``     pink noise with a gust envelope (fan/wind proxy) and the real
              room tape itself.

The owner's real voice is NOT among them: no owner recording exists on this
disk (``evals/20260820/voice_corpus_v1/`` keeps only its six espeak impostors;
its 52 owner WAVs are gitignored and gone, and ``recordings/`` holds no
``owner.wav``). Every "owner" here is a designated proxy, and the RESULTS say so.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
RATE_HZ = 16_000
ESPEAK_RETRIEVAL = 1

#: Real human prompt audio. The speaker labels are the file stems: CSM ships one
#: speaker per prompt file, and the cosine matrix in ``results/identity_panel``
#: is what actually decides whether that is true on this model.
REAL_VOICES = {
    "conv_a": "models/csm-1b/prompts/conversational_a.wav",
    "conv_b": "models/csm-1b/prompts/conversational_b.wav",
    "read_a": "models/csm-1b/prompts/read_speech_a.wav",
    "read_b": "models/csm-1b/prompts/read_speech_b.wav",
    "read_c": "models/csm-1b/prompts/read_speech_c.wav",
    "read_d": "models/csm-1b/prompts/read_speech_d.wav",
}

#: The designated RESEARCH owner. Not the owner's voice — the owner is not here.
OWNER_REAL = "conv_a"

ESPEAK_VOICES = ("en+m3", "en+f4", "en-us+m7", "en+f2")

STOP_PHRASES = (
    "Stop.",
    "Stop!",
    "Parcel, stop.",
    "Hey, stop stop stop.",
)

WAKE_PHRASES = ("Hey Parcel.", "Hey Parcel, come here.", "Hey Parcel, what is that?")

#: Owner turns with a critical slot in them: a place name, the dog's name, or
#: the stop word. These are what "critical-slot accuracy >= 0.95" is scored on.
CRITICAL_SLOT_TURNS = (
    ("place", "sidewalk", "Go to the sidewalk."),
    ("place", "lamppost", "Go to the lamppost."),
    ("place", "bench", "Walk to the bench."),
    ("place", "crosswalk", "Can you get to the crosswalk?"),
    ("place", "coffee shop", "Head over to the coffee shop."),
    ("place", "kitchen", "Go wait in the kitchen."),
    ("name", "parcel", "Parcel, come here."),
    ("name", "parcel", "Good boy Parcel."),
    ("stop", "stop", "Stop right there."),
    ("stop", "stop", "Stop and wait for me."),
)

#: What the robot says to itself. Two of them contain a motion command on
#: purpose: row R5 is "no self-transcribed motion command", and a tape with no
#: motion command in it cannot fail.
SELF_TTS_LINES = (
    "Okay, going to the bench now.",
    "I will stop right there and wait.",
    "Sure, following you.",
    "That is a lamppost, I think.",
    "I am holding still until you tell me otherwise.",
)

#: Television proxy. Real conversational human speech is the closest thing this
#: host has to a television; the news-reader lines are espeak and are labeled a
#: PROXY everywhere they are reported.
TV_LINES = (
    "Police say the driver stopped at the intersection before the collision.",
    "Markets closed lower today as investors weighed the latest inflation report.",
    "Go to our website for the full story and the latest weather.",
    "The prime minister said the talks would continue through the weekend.",
    "Follow me now to the studio for tonight's headline interview.",
)


@dataclass(frozen=True)
class Clip:
    """One stimulus file and everything a row needs to know about it."""

    name: str
    family: str
    voice: str
    role: str
    text: str
    path: str
    seconds: float
    speech_start_s: float
    speech_end_s: float


def write_wav(path: Path, samples: np.ndarray, rate_hz: int = RATE_HZ) -> None:
    payload = np.clip(np.rint(samples * 32768.0), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate_hz)
        handle.writeframes(payload.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def resample(samples: np.ndarray, source_hz: int, target_hz: int = RATE_HZ) -> np.ndarray:
    """Windowed-linear resample. Good enough for 16 kHz speech; deterministic."""

    if source_hz == target_hz:
        return samples
    count = round(samples.size * target_hz / source_hz)
    source_index = np.linspace(0.0, samples.size - 1.0, count)
    return np.interp(source_index, np.arange(samples.size), samples)


def energy_bounds(samples: np.ndarray, *, floor_db: float = 25.0) -> tuple[float, float]:
    """First and last sample more than ``floor_db`` over the clip's quiet floor.

    An energy witness, deliberately not a Silero one: the first-word-loss row
    compares a Silero gate against this, and a ground truth drawn from the same
    model would be measuring the model against itself.
    """

    window = 256
    usable = samples.size - samples.size % window
    if usable <= 0:
        return 0.0, samples.size / RATE_HZ
    blocks = samples[:usable].reshape(-1, window)
    rms = np.sqrt(np.maximum(1e-12, (blocks**2).mean(axis=1)))
    floor = float(np.percentile(rms, 5.0))
    hits = np.flatnonzero(rms >= floor * (10.0 ** (floor_db / 20.0)))
    if hits.size == 0:
        return 0.0, samples.size / RATE_HZ
    return float(hits[0] * window / RATE_HZ), float((hits[-1] + 1) * window / RATE_HZ)


class Espeak:
    """espeak-ng through ctypes, one process, many voices."""

    def __init__(self) -> None:
        self.lib = ctypes.CDLL("libespeak-ng.so.1")
        self.lib.espeak_Initialize.restype = ctypes.c_int
        self.rate_hz = int(self.lib.espeak_Initialize(ESPEAK_RETRIEVAL, 0, None, 0))
        if self.rate_hz <= 0:
            raise RuntimeError(f"espeak_Initialize returned {self.rate_hz}")
        self._chunks: list[bytes] = []
        callback_type = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p
        )

        def on_audio(samples, count, _events):  # pragma: no cover - a C callback
            if count > 0 and samples:
                self._chunks.append(bytes(ctypes.string_at(samples, count * 2)))
            return 0

        self._callback = callback_type(on_audio)
        self.lib.espeak_SetSynthCallback(self._callback)
        self.lib.espeak_Synth.argtypes = [
            ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
        ]

    def say(self, text: str, voice: str) -> np.ndarray:
        self._chunks.clear()
        if self.lib.espeak_SetVoiceByName(voice.encode()) != 0:
            raise RuntimeError(f"espeak has no voice {voice!r}")
        payload = text.encode()
        self.lib.espeak_Synth(payload, len(payload) + 1, 0, 1, 0, 0, None, None)
        self.lib.espeak_Synchronize()
        pcm = np.frombuffer(b"".join(self._chunks), dtype="<i2").astype(np.float64) / 32768.0
        return resample(pcm, self.rate_hz)


def piper_say(text: str, scratch: Path) -> np.ndarray:
    """One utterance in the robot's own voice, through the shipped piper binary."""

    import subprocess

    target = scratch / "piper_tmp.wav"
    binary = REPO_ROOT / "third_party" / "piper" / "piper"
    subprocess.run(
        [
            str(binary),
            "--model", str(REPO_ROOT / "models" / "piper" / "voice.onnx"),
            "--espeak_data", str(REPO_ROOT / "third_party" / "piper" / "espeak-ng-data"),
            "--output_file", str(target),
        ],
        input=text.encode(),
        check=True,
        capture_output=True,
        env={"LD_LIBRARY_PATH": str(REPO_ROOT / "third_party" / "piper"), "PATH": "/usr/bin:/bin"},
    )
    samples, rate = read_wav(target)
    return resample(samples, rate)


def pad(samples: np.ndarray, *, lead_s: float = 0.4, tail_s: float = 0.6) -> np.ndarray:
    return np.concatenate(
        [np.zeros(int(lead_s * RATE_HZ)), samples, np.zeros(int(tail_s * RATE_HZ))]
    )


def normalize_peak(samples: np.ndarray, peak: float = 0.7) -> np.ndarray:
    highest = float(np.abs(samples).max())
    if highest <= 0:
        return samples
    return samples * (peak / highest)


def build(out_dir: Path) -> list[Clip]:
    out_dir.mkdir(parents=True, exist_ok=True)
    clips: list[Clip] = []

    def emit(name: str, family: str, voice: str, role: str, text: str, samples: np.ndarray) -> None:
        samples = normalize_peak(pad(samples))
        path = out_dir / f"{name}.wav"
        write_wav(path, samples)
        start, end = energy_bounds(samples)
        clips.append(
            Clip(
                name=name,
                family=family,
                voice=voice,
                role=role,
                text=text,
                path=str(path),
                seconds=samples.size / RATE_HZ,
                speech_start_s=start,
                speech_end_s=end,
            )
        )

    # ---------------------------------------------------------------- real
    for label, relative in REAL_VOICES.items():
        samples, rate = read_wav(REPO_ROOT / relative)
        samples = resample(samples, rate)
        role = "owner_real" if label == OWNER_REAL else "impostor_real"
        emit(f"real_{label}", "real", label, role, "", samples)

    # -------------------------------------------------------------- espeak
    espeak = Espeak()
    for index, voice in enumerate(ESPEAK_VOICES):
        tag = voice.replace("+", "_").replace("-", "_")
        for phrase_index, phrase in enumerate(STOP_PHRASES):
            emit(f"stop_{tag}_{phrase_index}", "espeak", voice, "stop", phrase,
                 espeak.say(phrase, voice))
        for phrase_index, phrase in enumerate(WAKE_PHRASES):
            emit(f"wake_{tag}_{phrase_index}", "espeak", voice, "wake", phrase,
                 espeak.say(phrase, voice))
        if index < 2:
            for slot_index, (kind, slot, text) in enumerate(CRITICAL_SLOT_TURNS):
                emit(f"slot_{tag}_{slot_index}", "espeak", voice, f"slot:{kind}:{slot}", text,
                     espeak.say(text, voice))
        if index >= 2:
            for line_index, line in enumerate(TV_LINES):
                emit(f"tvread_{tag}_{line_index}", "espeak", voice, "tv", line,
                     espeak.say(line, voice))

    # --------------------------------------------------------------- piper
    scratch = out_dir / "_scratch"
    scratch.mkdir(exist_ok=True)
    for index, line in enumerate(SELF_TTS_LINES):
        emit(f"self_tts_{index}", "piper", "en_US-lessac-medium", "self_tts", line,
             piper_say(line, scratch))

    # --------------------------------------------------------------- noise
    rng = np.random.default_rng(20260824)
    seconds = 120.0
    white = rng.standard_normal(int(seconds * RATE_HZ))
    spectrum = np.fft.rfft(white)
    frequencies = np.fft.rfftfreq(white.size, 1.0 / RATE_HZ)
    shaped = spectrum / np.sqrt(np.maximum(frequencies, 1.0))
    fan = np.fft.irfft(shaped, white.size)
    gust = 1.0 + 0.6 * np.sin(2 * np.pi * 0.07 * np.arange(fan.size) / RATE_HZ)
    fan = fan * gust
    emit("fan_proxy", "noise", "pink+gust", "wind", "", fan / (np.abs(fan).max() + 1e-9))

    return clips


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    clips = build(args.out)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(
            {
                "rate_hz": RATE_HZ,
                "owner_real": OWNER_REAL,
                "count": len(clips),
                "clips": [asdict(clip) for clip in clips],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    families: dict[str, int] = {}
    for clip in clips:
        families[clip.family] = families.get(clip.family, 0) + 1
    print(f"{len(clips)} clips -> {args.out}  ({families})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
