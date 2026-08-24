#!/usr/bin/env python
"""Row: how good is the identity proxy at all? Enrollment + the cosine panel.

Before any arm can be believed, the reader needs to know what "owner" means in
this study. This writes the whole matrix — every voice against every voice —
next to the enrollment the product tool produced, so the owner-ID rows can be
read against their own proxy's quality rather than against the 0.802/0.033
figure measured on somebody else's material.
"""

from __future__ import annotations

import argparse
import platform
import subprocess
from pathlib import Path

import numpy as np

from parcel_robot.realtime.voice_identity import DEFAULT_THRESHOLD, SherpaSpeakerEmbedder

from .identity import MODEL_PATH, cosine_matrix, enroll_research_gallery, voiced_segments
from .session import clip_samples, load_bed, load_manifest, write_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--tape", type=Path, required=True)
    args = parser.parse_args()

    manifest = load_manifest()
    bed = load_bed(args.tape)
    real = {
        entry["voice"]: clip_samples(entry)
        for entry in manifest["clips"]
        if entry["family"] == "real"
    }
    owner_label = manifest["owner_real"]

    enrollment = enroll_research_gallery(real[owner_label], args.scratch / "gallery")

    embedder = SherpaSpeakerEmbedder(MODEL_PATH)
    panels = {
        label: [chunk for _offset, chunk in voiced_segments(samples, segment_s=2.0, hop_s=2.0)]
        for label, samples in real.items()
    }
    matrix = cosine_matrix(embedder, panels)

    same = matrix[owner_label][owner_label]
    cross = [matrix[owner_label][label] for label in matrix if label != owner_label]
    payload = {
        "tier": "replay",
        "host": platform.node(),
        "owner_proxy": owner_label,
        "owner_proxy_source": "models/csm-1b/prompts/conversational_a.wav (real human speech)",
        "why_a_proxy": (
            "the owner is not present and no recording of the owner's voice exists on this "
            "disk: evals/20260820/voice_corpus_v1 keeps only its six espeak impostors and "
            "recordings/ holds no owner.wav"
        ),
        "gallery_path": str(enrollment.profile_path),
        "gallery_utterances": enrollment.utterances,
        "enroll_stdout": enrollment.stdout,
        "product_threshold": DEFAULT_THRESHOLD,
        "segments_per_voice": {label: len(chunks) for label, chunks in panels.items()},
        "cosine_matrix": matrix,
        "owner_same_voice_mean_cosine": same,
        "owner_cross_voice_mean_cosine": float(np.mean(cross)),
        "owner_cross_voice_max_cosine": float(np.max(cross)),
        "room_floor_dbfs": bed.floor_dbfs,
        "python": platform.python_version(),
        "git_head": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip(),
    }
    path = write_result("identity_panel.json", payload)
    print(f"owner {owner_label}: same {same:.3f}  cross mean {np.mean(cross):.3f} "
          f"max {np.max(cross):.3f}  -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
