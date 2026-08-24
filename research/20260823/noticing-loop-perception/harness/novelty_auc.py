"""H6 P5 — new-vs-seen novelty, de-confounded from gallery growth.

The naive measurement (score every observation as the loop runs, call an
instance's first appearance "new") returns AUC 1.0 on this corpus, and that
number is an ARTIFACT: the gallery starts empty, so the earliest observations
score ~1.0 novelty whatever they are, and "first appearance" correlates almost
perfectly with "early". It measures time, not novelty. It is reported in
RESULTS as the confounded row, and this is the row that answers the question.

Protocol (pre-declared):
  1. BURN-IN — stream a fixed subset of frames through the loop so the gallery
     is warm and its size is no longer changing much.
  2. FREEZE — the gallery stops updating. Every probe observation is scored
     with ``NoticingLoop.novelty_of``, which by contract cannot mutate state,
     so scoring one probe can never make the next one look familiar.
  3. PROBE — every frame of the corpus, including the burn-in frames. A probe
     observation is SEEN when the ground-truth instance it matches was
     observed during burn-in, and NEW when it was not.
  4. AUC — Mann-Whitney U / (n_new * n_seen), ties 0.5.

Photos: burn-in is the first half of the photo set, so "new" instances are
real objects in unseen photographs. Renders: burn-in is the frames focused on
pedestrians 1-4, so a "seen" instance is the SAME pedestrian from a different
range and bearing — a cross-viewpoint re-identification, which is the harder
and more honest version of the question.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from analyze import match_frame
from noticing_loop import NumpyGallery

from parcel_robot.camera_channel.backends.recorded import read_clip
from parcel_robot.perception.noticing import NoticingGate, NoticingLoop, Observation


def _detect_and_embed(client: Any, rgb: np.ndarray, labels: list[str], gate: NoticingGate,
                      max_embeds: int) -> list[Observation]:
    response = client.detect(rgb, labels)
    survivors = []
    for row in response.get("detections", []):
        u0, v0, u1, v1 = (int(v) for v in row["box"])
        if float(row["score"]) < gate.min_score:
            continue
        if (u1 - u0) * (v1 - v0) < gate.min_box_pixels:
            continue
        survivors.append((float(row["score"]), str(row["label"]), (u0, v0, u1, v1)))
    survivors.sort(key=lambda item: -item[0])
    observations = []
    for score, label, box in survivors[:max_embeds]:
        u0, v0, u1, v1 = box
        vector = tuple(
            float(v) for v in client.embed_image(np.ascontiguousarray(rgb[v0:v1, u0:u1]))
        )
        observations.append(
            Observation(label=label, score=score, box=box, embedding=vector,
                        monotonic_ns=time.monotonic_ns())
        )
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H6 novelty AUC (frozen-gallery protocol)")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--clip", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--burn-in", required=True,
                        help="'first-half' or 'focus:pedestrian_1,pedestrian_2,...'")
    parser.add_argument("--max-embeds", type=int, default=5)
    parser.add_argument("--exclude-burn-in-frames", action="store_true",
                        help="probe only frames the gallery never saw — makes a SEEN instance a "
                             "genuine re-encounter from a new viewpoint instead of the same pixels")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    from parcel_robot.perception_daemon.client import DaemonClient

    corpus = Path(args.corpus)
    clips = json.loads((corpus / "clips" / "clips_gt.json").read_text())
    entry = next(item for item in clips["clips"] if item["clip"] == args.clip)
    truth = [record["objects"] for record in entry["records"]]
    _, color, _ = read_clip(corpus / "clips" / args.clip)
    labels = [phrase.strip() for phrase in args.labels.split(",") if phrase.strip()]
    label_set = set(labels)

    if args.burn_in == "first-half":
        burn_in = set(range(len(truth) // 2))
    elif args.burn_in.startswith("focus:"):
        wanted = {name.strip() for name in args.burn_in[len("focus:"):].split(",")}
        burn_in = {
            record["sequence"] for record in entry["records"] if record.get("focus") in wanted
        }
    else:
        raise SystemExit(f"unknown burn-in spec {args.burn_in}")

    client = DaemonClient(args.socket)
    gate = NoticingGate()
    loop = NoticingLoop(gate=gate, gallery=NumpyGallery(gate.gallery_limit))

    def identity_of(frame_index: int, slot: int) -> tuple[str, int, int]:
        """Stable instance key: a render instance is its seg id ACROSS viewpoints."""

        item = truth[frame_index][slot]
        seg = item.get("seg_id")
        if seg is not None:
            return ("seg", int(seg), 0)
        return ("photo", frame_index, slot)

    seen_instances: set[tuple[str, int, int]] = set()
    for index in sorted(burn_in):
        observations = _detect_and_embed(
            client, np.ascontiguousarray(color[index]), labels, gate, args.max_embeds
        )
        matched, _ = match_frame(
            [{"label": o.label, "score": o.score, "box": list(o.box)} for o in observations],
            truth[index], labels=label_set,
        )
        for position in range(len(observations)):
            slot = matched.get(position)
            if slot is not None:
                seen_instances.add(identity_of(index, slot))
        loop.observe_frame(observations)
    gallery_size = len(loop.gallery)

    probe_frames = [
        index for index in range(len(truth))
        if not (args.exclude_burn_in_frames and index in burn_in)
    ]
    probes: list[dict[str, Any]] = []
    for index in probe_frames:
        observations = _detect_and_embed(
            client, np.ascontiguousarray(color[index]), labels, gate, args.max_embeds
        )
        matched, _ = match_frame(
            [{"label": o.label, "score": o.score, "box": list(o.box)} for o in observations],
            truth[index], labels=label_set,
        )
        for position, observation in enumerate(observations):
            slot = matched.get(position)
            identity = None if slot is None else identity_of(index, slot)
            probes.append(
                {
                    "frame": index, "label": observation.label, "score": observation.score,
                    "box": list(observation.box), "novelty": loop.novelty_of(observation),
                    "identified": identity is not None,
                    "instance": None if identity is None else list(identity),
                    "seen_in_burn_in": identity is not None and identity in seen_instances,
                }
            )
    assert gallery_size == len(loop.gallery), "the gallery moved during probing"

    new = [p["novelty"] for p in probes if p["identified"] and not p["seen_in_burn_in"]]
    seen = [p["novelty"] for p in probes if p["identified"] and p["seen_in_burn_in"]]
    auc = None
    if new and seen:
        wins = sum(
            1.0 if a > b else (0.5 if a == b else 0.0)
            for a in new for b in seen
        )
        auc = wins / (len(new) * len(seen))
    report = {
        "clip": args.clip, "labels": labels, "burn_in": args.burn_in,
        "burn_in_frames": len(burn_in), "probe_frames": len(probe_frames),
        "exclude_burn_in_frames": bool(args.exclude_burn_in_frames),
        "gallery_size": gallery_size,
        "probes": len(probes),
        "identified": sum(1 for p in probes if p["identified"]),
        "new_n": len(new), "seen_n": len(seen),
        "novelty_new_mean": float(np.mean(new)) if new else None,
        "novelty_seen_mean": float(np.mean(seen)) if seen else None,
        "novelty_new_median": float(np.median(new)) if new else None,
        "novelty_seen_median": float(np.median(seen)) if seen else None,
        "auc": auc,
        "rows": probes,
    }
    client.close()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
