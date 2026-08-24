#!/usr/bin/env python
"""Laying stimuli on a timeline against the array's own recorded room.

A "tape" is a synthetic listening period with real audio on it. The silence
between utterances is NOT synthetic dither — that was H1's headline caveat — it
is the XVF3800's own ambient recording, so the noise floor a VAD is asked to
ignore is this room's actual floor at its actual level.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .channel import Geometry, RoomBed, present
from .gate import RATE_HZ, Placement, Tape


@dataclass(frozen=True)
class Item:
    """One stimulus to place: its audio, its truth, and how to present it."""

    name: str
    role: str
    voice: str
    text: str
    samples: np.ndarray
    geometry: Geometry
    replay: bool = False
    #: Extra attenuation applied AFTER presentation (the self-speech rows use
    #: this to sweep a hypothetical AEC).
    extra_db: float = 0.0


def to_pcm16(samples: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(np.asarray(samples) * 32768.0), -32768, 32767).astype(np.int16)


def energy_bounds(samples: np.ndarray, floor: float, *, floor_db: float = 10.0) -> tuple[int, int]:
    block = 256
    usable = samples.size - samples.size % block
    if usable <= 0:
        return 0, samples.size
    rms = np.sqrt(np.maximum(1e-12, (samples[:usable].reshape(-1, block) ** 2).mean(axis=1)))
    hits = np.flatnonzero(rms >= floor * (10.0 ** (floor_db / 20.0)))
    if hits.size == 0:
        return 0, samples.size
    return int(hits[0] * block), int((hits[-1] + 1) * block)


def build_tape(
    items: Sequence[Item],
    bed: RoomBed,
    *,
    gap_s: float = 4.0,
    lead_s: float = 3.0,
    speech_dbfs_at_1m: float = -26.0,
) -> Tape:
    """Place every item on one timeline, separated by real recorded room."""

    floor = float(np.sqrt(np.mean(bed.tape**2)) + 1e-12)
    pieces: list[np.ndarray] = [bed.slice(int(lead_s * RATE_HZ))]
    placements: list[Placement] = []
    cursor = lead_s
    for item in items:
        rendered = present(
            item.samples,
            bed,
            geometry=item.geometry,
            speech_dbfs_at_1m=speech_dbfs_at_1m,
            replay=item.replay,
        )
        if item.extra_db:
            rendered = rendered * (10.0 ** (item.extra_db / 20.0))
        start_sample, end_sample = energy_bounds(rendered, floor)
        placements.append(
            Placement(
                name=item.name,
                role=item.role,
                voice=item.voice,
                text=item.text,
                start_s=cursor,
                speech_start_s=cursor + start_sample / RATE_HZ,
                speech_end_s=cursor + end_sample / RATE_HZ,
                geometry=item.geometry.label,
                replay=item.replay,
            )
        )
        pieces.append(rendered)
        cursor += rendered.size / RATE_HZ
        pieces.append(bed.slice(int(gap_s * RATE_HZ)))
        cursor += gap_s
    return Tape(samples=to_pcm16(np.concatenate(pieces)), placements=placements)


__all__ = ["Item", "build_tape", "energy_bounds", "to_pcm16"]
