#!/usr/bin/env python
"""The nine tapes every arm is judged on, and the truth that comes with them.

One place builds them so that arm (a) and arm (e) are answering about the same
seconds of audio. Sizes are chosen for the pre-registered n, not for a pretty
runtime: the STOP tape carries n >= 60 because A9's bar is a finite-sample one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .channel import Geometry, RoomBed
from .gate import Tape
from .identity import voiced_segments
from .session import clip_samples
from .tapes import Item, build_tape

GEOMETRIES = (
    Geometry(1.0, 0),
    Geometry(1.0, 30),
    Geometry(1.0, 60),
    Geometry(3.0, 0),
    Geometry(3.0, 30),
    Geometry(3.0, 60),
)

#: How far below the owner's 1 m level a television across the room sits.
TV_EXTRA_DB = -8.0

#: The AEC attenuations the self-speech row sweeps. The real one is unmeasured
#: on this host (no verified loudspeaker), so the row is reported as a function
#: of it rather than at one unproven value.
AEC_SWEEP_DB = (0.0, -10.0, -20.0, -30.0)


@dataclass
class Arena:
    owner: Tape
    owner_replay: Tape
    second_person: Tape
    tv: Tape
    self_tts: Tape
    stop: Tape
    wake: Tape
    slots: Tape
    fan: Tape

    def named(self) -> dict[str, Tape]:
        return {
            "owner": self.owner,
            "owner_replay": self.owner_replay,
            "second_person": self.second_person,
            "tv": self.tv,
            "self_tts": self.self_tts,
            "stop": self.stop,
            "wake": self.wake,
            "slots": self.slots,
            "fan": self.fan,
        }


def by_family(manifest: dict, family: str) -> list[dict]:
    return [entry for entry in manifest["clips"] if entry["family"] == family]


def by_role(manifest: dict, role: str) -> list[dict]:
    return [entry for entry in manifest["clips"] if entry["role"] == role]


def owner_held_out(manifest: dict, *, enroll_until_s: float = 15.0) -> list[np.ndarray]:
    """Owner-proxy segments the gallery has never seen."""

    owner = next(
        entry for entry in manifest["clips"] if entry["role"] == "owner_real"
    )
    samples = clip_samples(owner)
    tail = samples[int(enroll_until_s * 16_000) :]
    return [chunk for _offset, chunk in voiced_segments(tail, segment_s=2.5, hop_s=2.5)]


def build(manifest: dict, bed: RoomBed, speech_dbfs: float) -> Arena:
    def tape(items: list[Item], gap_s: float = 4.0) -> Tape:
        return build_tape(items, bed, gap_s=gap_s, speech_dbfs_at_1m=speech_dbfs)

    held_out = owner_held_out(manifest)
    owner_items = [
        Item(f"owner_{index}_{geometry.label}", "owner", "conv_a", "", chunk, geometry)
        for geometry in GEOMETRIES
        for index, chunk in enumerate(held_out)
    ]
    replay_items = [
        Item(f"replay_{index}_{geometry.label}", "owner_replay", "conv_a", "", chunk,
             geometry, replay=True)
        for geometry in GEOMETRIES
        for index, chunk in enumerate(held_out)
    ]

    second_items: list[Item] = []
    for entry in by_role(manifest, "impostor_real"):
        samples = clip_samples(entry)
        for index, (_offset, chunk) in enumerate(
            voiced_segments(samples, segment_s=2.5, hop_s=2.5)
        ):
            for geometry in (GEOMETRIES[0], GEOMETRIES[4]):
                second_items.append(
                    Item(
                        f"second_{entry['voice']}_{index}_{geometry.label}",
                        "second_person",
                        entry["voice"],
                        "",
                        chunk,
                        geometry,
                    )
                )

    tv_items: list[Item] = []
    tv_reads = by_role(manifest, "tv")
    conversational = [
        entry for entry in by_role(manifest, "impostor_real") if entry["voice"].startswith("conv")
    ]
    round_index = 0
    while len(tv_items) < 220:
        for entry in tv_reads:
            tv_items.append(
                Item(
                    f"tv_{entry['name']}_{round_index}",
                    "tv",
                    entry["voice"],
                    entry["text"],
                    clip_samples(entry),
                    GEOMETRIES[4],
                    extra_db=TV_EXTRA_DB,
                )
            )
        for entry in conversational:
            samples = clip_samples(entry)
            for index, (_offset, chunk) in enumerate(
                voiced_segments(samples, segment_s=4.0, hop_s=4.0)
            ):
                tv_items.append(
                    Item(
                        f"tv_{entry['voice']}_{round_index}_{index}",
                        "tv",
                        entry["voice"],
                        "",
                        chunk,
                        GEOMETRIES[4],
                        extra_db=TV_EXTRA_DB,
                    )
                )
        round_index += 1

    self_items = [
        Item(
            f"{entry['name']}_aec{int(-attenuation)}",
            "self_tts",
            entry["voice"],
            entry["text"],
            clip_samples(entry),
            GEOMETRIES[0],
            extra_db=attenuation,
        )
        for attenuation in AEC_SWEEP_DB
        for entry in by_role(manifest, "self_tts")
    ]

    stop_items = [
        Item(
            f"{entry['name']}_{geometry.label}",
            "stop",
            entry["voice"],
            entry["text"],
            clip_samples(entry),
            geometry,
        )
        for geometry in (GEOMETRIES[0], GEOMETRIES[4], GEOMETRIES[5], GEOMETRIES[3])
        for entry in by_role(manifest, "stop")
    ]

    wake_items = [
        Item(f"{entry['name']}_{geometry.label}", "wake", entry["voice"], entry["text"],
             clip_samples(entry), geometry)
        for geometry in (GEOMETRIES[0], GEOMETRIES[4])
        for entry in by_role(manifest, "wake")
    ]

    slot_items = [
        Item(f"{entry['name']}_{geometry.label}", entry["role"], entry["voice"], entry["text"],
             clip_samples(entry), geometry)
        for geometry in (GEOMETRIES[0], GEOMETRIES[4])
        for entry in manifest["clips"]
        if entry["role"].startswith("slot:")
    ]

    fan_entry = next(entry for entry in manifest["clips"] if entry["role"] == "wind")
    fan_items = [
        Item("fan_proxy", "wind", "pink+gust", "", clip_samples(fan_entry), GEOMETRIES[0])
    ]

    return Arena(
        owner=tape(owner_items),
        owner_replay=tape(replay_items),
        second_person=tape(second_items),
        tv=tape(tv_items, gap_s=1.5),
        self_tts=tape(self_items),
        stop=tape(stop_items),
        wake=tape(wake_items),
        slots=tape(slot_items),
        fan=tape(fan_items, gap_s=1.0),
    )


__all__ = ["AEC_SWEEP_DB", "GEOMETRIES", "TV_EXTRA_DB", "Arena", "build", "owner_held_out"]
