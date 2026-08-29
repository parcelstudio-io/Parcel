"""Amendment H2 — the negative slices that actually matter for the reward signal.

(i)  SPEECH  — 100 read-speech clips from LibriSpeech dev-clean (public corpus).
(ii) OWN TTS — 50 short sentences rendered with THE REPO'S OWN Piper voice, via
     the same binary + voice file `PiperSpeechProvider` uses in production
     (read-only use; nothing under src/ or models/ is modified).

A false laugh-trigger on the dog's own TTS would make the reward signal
self-exciting, so this slice is the one the amended verdict rides on.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

import numpy as np
from hs_common import DATA, SEED, sha256_file

REPO = pathlib.Path("/home/jaewoo-jang/Desktop/Projects/Parcel")
PIPER_BIN = REPO / "third_party" / "piper" / "piper"
PIPER_VOICE = REPO / "models" / "piper" / "voice.onnx"
PIPER_SR = 22050  # from models/piper/voice.onnx.json
TTS_DIR = DATA / "piper_tts"
LIBRI_ROOT = DATA / "librispeech" / "LibriSpeech" / "dev-clean"

N_SPEECH = 100
N_TTS = 50

# 50 short companion-dog utterances, the kind the runtime actually speaks.
TTS_SENTENCES = [
    "Good morning. I noticed you left the window open.",
    "I am here if you want to talk about it.",
    "That is a new sound. I will go look.",
    "Your coffee has been sitting there for an hour.",
    "I like this part of the room in the afternoon.",
    "Do you want me to follow you, or wait here?",
    "The front door just closed. Was that you?",
    "I have been watching the street for a while now.",
    "You seem quieter than usual today.",
    "There is something under the couch. I cannot reach it.",
    "I remember you said that last Tuesday.",
    "Should I stop talking for a bit?",
    "The light changed. It is getting late.",
    "I found the ball. It was behind the chair.",
    "That is a good question. Let me think.",
    "I do not know the answer to that one.",
    "Your phone has been buzzing on the table.",
    "I would rather stay in this room, if that is alright.",
    "Something smells different in the kitchen.",
    "I am going to sit down now.",
    "You have not eaten anything since this morning.",
    "That was louder than I expected.",
    "I can hear the neighbours through the wall.",
    "Do you want the lamp on?",
    "I will remember that for next time.",
    "There is a package by the door.",
    "I lost track of what you were saying.",
    "The floor is cold over here.",
    "You always say that right before you leave.",
    "I think it is going to rain later.",
    "Let me get out of your way.",
    "I have not seen that person before.",
    "Is it alright if I come closer?",
    "That is the third time today.",
    "I am not sure I understood you.",
    "Your shoes are still by the stairs.",
    "I was waiting for you to come back.",
    "Something moved in the hallway.",
    "That sounded like it hurt.",
    "I will keep an eye on it.",
    "You left the tap running again.",
    "I am happy to just sit here with you.",
    "The room got very quiet.",
    "Do you need help with that?",
    "I noticed the plant is drooping.",
    "It has been a long day for both of us.",
    "I will be right here when you get back.",
    "That is one of my favourite things about you.",
    "The battery is getting low.",
    "Good night. I will keep watch.",
]


def build_tts(force: bool = False) -> list[dict]:
    """Render the 50 sentences with the repo's own Piper voice (read-only)."""
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = TTS_DIR / "meta.json"
    if meta_path.exists() and not force:
        return json.loads(meta_path.read_text())
    if not (PIPER_BIN.is_file() and PIPER_VOICE.is_file()):
        raise FileNotFoundError(f"piper missing: {PIPER_BIN} / {PIPER_VOICE}")
    out = []
    for i, sent in enumerate(TTS_SENTENCES[:N_TTS]):
        raw = TTS_DIR / f"tts_{i:03d}.raw"
        if not raw.exists() or force:
            proc = subprocess.run(
                [str(PIPER_BIN), "--model", str(PIPER_VOICE), "--output-raw"],
                input=sent.encode("utf-8"), capture_output=True, timeout=60, check=True,
                cwd=str(REPO),
            )
            raw.write_bytes(proc.stdout)
        pcm = np.frombuffer(raw.read_bytes(), dtype="<i2")
        out.append({"path": str(raw), "text": sent, "sample_rate": PIPER_SR,
                    "seconds": round(len(pcm) / PIPER_SR, 3)})
    meta_path.write_text(json.dumps(out, indent=2))
    print(f"[neg] rendered {len(out)} Piper TTS clips "
          f"(total {sum(c['seconds'] for c in out):.1f} s)")
    return out


def load_tts_wave(entry: dict, target_sr: int) -> np.ndarray:
    import librosa

    pcm = np.frombuffer(pathlib.Path(entry["path"]).read_bytes(), dtype="<i2")
    y = pcm.astype(np.float32) / 32768.0
    if entry["sample_rate"] != target_sr:
        y = librosa.resample(y, orig_sr=entry["sample_rate"], target_sr=target_sr)
    return y


def speech_clips(n: int = N_SPEECH, seed: int = SEED) -> list[pathlib.Path]:
    """n LibriSpeech dev-clean utterances, one per speaker where possible."""
    if not LIBRI_ROOT.exists():
        raise FileNotFoundError(f"missing {LIBRI_ROOT}")
    flacs = sorted(LIBRI_ROOT.rglob("*.flac"))
    by_spk: dict[str, list[pathlib.Path]] = {}
    for f in flacs:
        by_spk.setdefault(f.name.split("-")[0], []).append(f)
    rng = np.random.default_rng(seed)
    speakers = sorted(by_spk)
    rng.shuffle(speakers)
    picked: list[pathlib.Path] = []
    round_i = 0
    while len(picked) < n:
        added = False
        for s in speakers:
            if len(by_spk[s]) > round_i:
                picked.append(by_spk[s][round_i])
                added = True
                if len(picked) == n:
                    break
        if not added:
            break
        round_i += 1
    print(f"[neg] {len(picked)} LibriSpeech dev-clean clips from "
          f"{len({p.name.split('-')[0] for p in picked})} speakers")
    return picked


def provenance() -> dict:
    return {
        "speech": {
            "source": "https://www.openslr.org/resources/12/dev-clean.tar.gz",
            "corpus": "LibriSpeech dev-clean",
            "archive_sha256": sha256_file(DATA / "librispeech-dev-clean.tar.gz")
            if (DATA / "librispeech-dev-clean.tar.gz").exists() else None,
            "n_clips": N_SPEECH,
        },
        "own_tts": {
            "source": "the repo's production Piper path, used read-only",
            "binary": str(PIPER_BIN),
            "voice": str(PIPER_VOICE),
            "voice_sha256": sha256_file(PIPER_VOICE) if PIPER_VOICE.exists() else None,
            "voice_dataset": "lessac medium, en_US, 22050 Hz",
            "caller_in_product": "src/parcel_robot/providers.py::PiperSpeechProvider",
            "n_clips": N_TTS,
        },
        "chuckle_asset_search": {
            "searched": "src/**  for *.wav *.mp3 *.ogg *chuckle* *laugh*",
            "found": ["src/parcel_robot/runtime_assets/configs/skills/trajectories/chuckle.yaml"],
            "note": "the only 'chuckle' asset in src/ is a MOTION trajectory (YAML), "
                    "not audio; the repo ships no laugh/chuckle audio asset, so that "
                    "sub-slice of H2 is empty and is recorded as such",
        },
    }


if __name__ == "__main__":
    build_tts()
    speech_clips()
    print(json.dumps(provenance(), indent=2))
