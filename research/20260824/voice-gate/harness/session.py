#!/usr/bin/env python
"""Shared session facts: where the stimuli are, and what this room sounds like.

The calibration lives here because it is the study's one honest anchor and it
must be quoted identically by every runner.

CALIBRATION METHOD (labeled, because this host has no SPL meter)
----------------------------------------------------------------
The array's own ambient tape gives the room floor in dBFS. A quiet indoor room
of this kind is taken to be ~40 dB(A); conversational speech at 1 m is 60–70
dB(A). So a stimulus is placed ``SPEECH_OVER_FLOOR_DB`` above the MEASURED floor
and that is what "60–70 dB(A) equivalent" means in every row below. It is an
SNR anchor, not a sound-level measurement, and no row may be read as one.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np

from .channel import RoomBed

HERE = Path(__file__).resolve().parent
FOLDER = HERE.parent
RESULTS = FOLDER / "results"
RATE_HZ = 16_000

#: Speech is placed this far above the room's measured RMS floor.
#: 65 dB(A) speech in a ~40 dB(A) room.
SPEECH_OVER_FLOOR_DB = 25.0


def load_manifest(path: Path | None = None) -> dict:
    return json.loads((path or RESULTS / "corpus_manifest.json").read_text(encoding="utf-8"))


def clip_samples(entry: dict) -> np.ndarray:
    with wave.open(str(entry["path"])) as handle:
        frames = handle.readframes(handle.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0


def load_bed(tape_path: Path, *, seconds: float = 600.0, channel: int = 1) -> RoomBed:
    """The real room, from the array's own recording. Channel 1 is the ASR beam."""

    raw = np.fromfile(tape_path, dtype="<i2", count=int(seconds * RATE_HZ) * 2)
    raw = raw[: raw.size - raw.size % 2].reshape(-1, 2).astype(np.float64) / 32768.0
    return RoomBed(raw[:, channel])


def speech_level_dbfs(bed: RoomBed) -> float:
    return bed.floor_dbfs + SPEECH_OVER_FLOOR_DB


def write_result(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(payload, indent=1, sort_keys=False), encoding="utf-8")
    return path


__all__ = [
    "FOLDER",
    "RATE_HZ",
    "RESULTS",
    "SPEECH_OVER_FLOOR_DB",
    "clip_samples",
    "load_bed",
    "load_manifest",
    "speech_level_dbfs",
    "write_result",
]
