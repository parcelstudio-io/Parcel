#!/usr/bin/env python
"""Owner-ID's operating curve: what the gate can buy, and what it costs to buy it.

Arm (b) has two free parameters the DESIGN does not fix, and a single arbitrary
choice of either would decide the study by accident:

* **how long the gate may listen before deciding.** TitaNet on 1.0 s of speech
  is a different instrument from TitaNet on 2.5 s. Longer is more accurate and
  slower to admit — an admission-latency cost the owner feels on every turn.
* **the enrollment channel.** The product's enroller takes clean WAVs. The
  operating condition is a room. Enrolling THROUGH the same channel is free and
  changes the numbers, so both galleries are measured rather than assumed.

The threshold is NOT swept to make a bar: 0.55 is the product's
``DEFAULT_THRESHOLD`` and every pass/fail row is read there. The rest of the
curve is reported so a reader can see what a different threshold would cost.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from parcel_robot.realtime.voice_identity import DEFAULT_THRESHOLD

from .arena import GEOMETRIES, owner_held_out
from .channel import present
from .identity import OwnerIdentity, enroll_research_gallery, voiced_segments
from .session import clip_samples, load_bed, load_manifest, speech_level_dbfs, write_result

WINDOWS_S = (0.5, 1.0, 1.5, 2.0, 2.5)


def pcm(samples: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(samples * 32768.0), -32768, 32767).astype(np.int16)


def roc(owner: list[float], impostor: list[float]) -> dict:
    """Product-threshold rates, the EER, and the price of a 0.95-recall threshold."""

    owner_array = np.asarray(owner)
    impostor_array = np.asarray(impostor)
    grid = np.unique(np.concatenate([owner_array, impostor_array]))
    best = None
    for threshold in grid:
        recall = float((owner_array >= threshold).mean())
        false_accept = float((impostor_array >= threshold).mean())
        gap = abs((1.0 - recall) - false_accept)
        if best is None or gap < best[0]:
            best = (gap, float(threshold), recall, false_accept)
    at_95 = [t for t in grid if float((owner_array >= t).mean()) >= 0.95]
    threshold_95 = float(max(at_95)) if at_95 else float("nan")
    fa_95 = (
        float((impostor_array >= threshold_95).mean()) if at_95 else float("nan")
    )
    return {
        "n_owner": int(owner_array.size),
        "n_impostor": int(impostor_array.size),
        "at_product_threshold": {
            "threshold": DEFAULT_THRESHOLD,
            "owner_recall": float((owner_array >= DEFAULT_THRESHOLD).mean()),
            "impostor_false_accept": float((impostor_array >= DEFAULT_THRESHOLD).mean()),
        },
        "eer_threshold": best[1] if best else float("nan"),
        "eer": float((1.0 - best[2] + best[3]) / 2.0) if best else float("nan"),
        "threshold_for_recall_0p95": threshold_95,
        "impostor_false_accept_at_that_threshold": fa_95,
        "owner_p5": float(np.percentile(owner_array, 5)),
        "owner_p50": float(np.percentile(owner_array, 50)),
        "impostor_p95": float(np.percentile(impostor_array, 95)),
        "impostor_max": float(impostor_array.max()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--tape", type=Path, required=True)
    args = parser.parse_args()

    manifest = load_manifest()
    bed = load_bed(args.tape)
    level = speech_level_dbfs(bed)
    owner_entry = next(e for e in manifest["clips"] if e["role"] == "owner_real")
    owner_samples = clip_samples(owner_entry)

    matched_head = np.concatenate(
        [present(owner_samples[: 15 * 16_000], bed, geometry=GEOMETRIES[0],
                 speech_dbfs_at_1m=level)]
    )
    galleries = {
        "clean": enroll_research_gallery(owner_samples, args.scratch / "gallery"),
        "channel_matched": enroll_research_gallery(
            matched_head, args.scratch / "gallery_matched", enroll_until_s=15.0
        ),
    }

    held = owner_held_out(manifest)
    impostor_chunks: list[np.ndarray] = []
    for entry in manifest["clips"]:
        if entry["role"] != "impostor_real":
            continue
        impostor_chunks.extend(
            chunk for _offset, chunk in voiced_segments(clip_samples(entry),
                                                        segment_s=2.5, hop_s=2.5)
        )

    payload: dict = {
        "tier": "replay",
        "hosted_usd": 0.0,
        "product_threshold": DEFAULT_THRESHOLD,
        "windows_s": list(WINDOWS_S),
        "geometries": [geometry.label for geometry in GEOMETRIES],
        "room_floor_dbfs": bed.floor_dbfs,
        "galleries": {},
    }
    for gallery_name, enrollment in galleries.items():
        identity = OwnerIdentity(enrollment.profile_path)
        per_window: dict[str, dict] = {}
        for window_s in WINDOWS_S:
            samples = int(window_s * 16_000)
            owner_scores: list[float] = []
            owner_by_cell: dict[str, list[float]] = {}
            replay_scores: list[float] = []
            for geometry in GEOMETRIES:
                for chunk in held:
                    rendered = present(chunk, bed, geometry=geometry, speech_dbfs_at_1m=level)
                    value = identity.score(pcm(rendered[:samples]))
                    owner_scores.append(value)
                    owner_by_cell.setdefault(geometry.label, []).append(value)
                    spoof = present(chunk, bed, geometry=geometry, speech_dbfs_at_1m=level,
                                    replay=True)
                    replay_scores.append(identity.score(pcm(spoof[:samples])))
            impostor_scores = [
                identity.score(
                    pcm(present(chunk, bed, geometry=GEOMETRIES[0], speech_dbfs_at_1m=level)[
                        :samples
                    ])
                )
                for chunk in impostor_chunks
            ]
            curve = roc(owner_scores, impostor_scores)
            calibrated = curve["threshold_for_recall_0p95"]
            replay_array = np.asarray(replay_scores)
            curve["replay_acceptance_at_product_threshold"] = float(
                (replay_array >= DEFAULT_THRESHOLD).mean()
            )
            # The honesty row (A9): at the threshold the owner actually needs, is a
            # recording of the owner still the owner? Reported, never claimed away.
            curve["replay_acceptance_at_calibrated_threshold"] = (
                float((replay_array >= calibrated).mean())
                if np.isfinite(calibrated)
                else float("nan")
            )
            curve["replay_p50"] = float(np.median(replay_scores))
            curve["owner_recall_by_cell"] = {
                cell: float((np.asarray(values) >= DEFAULT_THRESHOLD).mean())
                for cell, values in sorted(owner_by_cell.items())
            }
            per_window[f"{window_s:g}s"] = curve
        payload["galleries"][gallery_name] = {
            "profile_path": str(enrollment.profile_path),
            "enroll_stdout": enrollment.stdout,
            "by_decision_window": per_window,
        }
        best = max(
            per_window.items(),
            key=lambda item: item[1]["at_product_threshold"]["owner_recall"],
        )
        print(
            f"{gallery_name:16s} best window {best[0]}: recall "
            f"{best[1]['at_product_threshold']['owner_recall']:.3f} "
            f"FA {best[1]['at_product_threshold']['impostor_false_accept']:.3f} "
            f"EER {best[1]['eer']:.3f}"
        )
    path = write_result("identity_roc.json", payload)
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
