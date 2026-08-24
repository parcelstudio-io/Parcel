"""H6 P5 — the paired, well-powered version of new-vs-seen novelty.

The frozen-gallery splits (``novelty_auc.py``) answer the question but with
n_new = 1..11, because in a small scene almost every instance turns up in the
background of the burn-in frames. This removes that problem by holding the
PROBE fixed and changing only the gallery:

  for every (instance i, frame f) whose crop the detector found and embedded,
    NEW  = novelty of that crop against a gallery of every OTHER instance's
           crops (i absent entirely)
    SEEN = the same gallery PLUS i's crops from every frame except f
           (so the probe view itself is never in the gallery — the model has
           seen this pedestrian, from other ranges and bearings, never from
           here)

Both conditions score the identical crop, so the only difference is whether
the instance is known: a paired design, n = number of probes on each side.
Novelty is ``1 - max cosine``, the same formula ``NoveltyGallery`` uses (pinned
against it in the report's ``formula_agrees_with_product`` field).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from analyze import match_frame, rank_auc

from parcel_robot.camera_channel.backends.recorded import read_clip
from parcel_robot.perception.noticing import NoveltyGallery

MIN_SCORE = 0.1
MIN_BOX_PIXELS = 32 * 32


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H6 paired novelty AUC")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--clip", default="renders_640.npz")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--label-filter", default="",
                        help="score only this label (e.g. person); empty = every scored label")
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

    client = DaemonClient(args.socket)
    # One embedding pass: every detected, matched instance-view in the corpus.
    crops: list[dict] = []
    for index in range(len(truth)):
        rgb = np.ascontiguousarray(color[index])
        response = client.detect(rgb, labels)
        rows = []
        for row in response.get("detections", []):
            u0, v0, u1, v1 = (int(v) for v in row["box"])
            if float(row["score"]) < MIN_SCORE or (u1 - u0) * (v1 - v0) < MIN_BOX_PIXELS:
                continue
            rows.append({"label": str(row["label"]), "score": float(row["score"]),
                         "box": [u0, v0, u1, v1]})
        matched, _ = match_frame(rows, truth[index], labels=label_set)
        for position, row in enumerate(rows):
            slot = matched.get(position)
            if slot is None:
                continue
            item = truth[index][slot]
            if args.label_filter and item["label"] != args.label_filter:
                continue
            seg = item.get("seg_id")
            instance = f"seg:{seg}" if seg is not None else f"photo:{index}:{slot}"
            u0, v0, u1, v1 = row["box"]
            vector = tuple(
                float(value) for value in
                client.embed_image(np.ascontiguousarray(rgb[v0:v1, u0:u1]))
            )
            crops.append({"frame": index, "instance": instance, "label": item["label"],
                          "score": row["score"], "embedding": vector})
    client.close()

    by_instance: dict[str, list[int]] = defaultdict(list)
    for position, crop in enumerate(crops):
        by_instance[crop["instance"]].append(position)

    new_scores: list[float] = []
    seen_scores: list[float] = []
    pairs: list[dict] = []
    for probe_index, probe in enumerate(crops):
        others = [
            crops[position]["embedding"] for position in range(len(crops))
            if crops[position]["instance"] != probe["instance"]
        ]
        same = [
            crops[position]["embedding"] for position in by_instance[probe["instance"]]
            if position != probe_index
        ]
        if not others or not same:
            continue
        base = np.asarray([_unit(vector) for vector in others])
        probe_unit = _unit(probe["embedding"])
        novelty_new = float(max(0.0, 1.0 - float((base @ probe_unit).max())))
        warm = np.vstack([base, np.asarray([_unit(vector) for vector in same])])
        novelty_seen = float(max(0.0, 1.0 - float((warm @ probe_unit).max())))
        new_scores.append(novelty_new)
        seen_scores.append(novelty_seen)
        pairs.append({"instance": probe["instance"], "frame": probe["frame"],
                      "label": probe["label"], "novelty_new": novelty_new,
                      "novelty_seen": novelty_seen,
                      "views_of_instance": len(by_instance[probe["instance"]])})

    # The product's own pure gallery must agree with the vectorised formula.
    agrees = True
    if pairs:
        sample = crops[0]
        gallery = NoveltyGallery(limit=len(crops))
        for position in range(1, len(crops)):
            gallery.add(crops[position]["embedding"])
        matrix = np.asarray([_unit(crops[i]["embedding"]) for i in range(1, len(crops))])
        reference = float(max(0.0, 1.0 - float((matrix @ _unit(sample["embedding"])).max())))
        agrees = abs(gallery.novelty(sample["embedding"]) - reference) < 1e-9

    report = {
        "clip": args.clip, "labels": labels, "label_filter": args.label_filter or None,
        "frames": len(truth), "embedded_instance_views": len(crops),
        "instances": len(by_instance),
        "pairs": len(pairs),
        "novelty_new_mean": float(np.mean(new_scores)) if new_scores else None,
        "novelty_seen_mean": float(np.mean(seen_scores)) if seen_scores else None,
        "novelty_new_median": float(np.median(new_scores)) if new_scores else None,
        "novelty_seen_median": float(np.median(seen_scores)) if seen_scores else None,
        "auc_new_vs_seen": rank_auc(new_scores, seen_scores),
        "paired_new_greater": sum(
            1 for pair in pairs if pair["novelty_new"] > pair["novelty_seen"]
        ),
        "paired_equal": sum(
            1 for pair in pairs if pair["novelty_new"] == pair["novelty_seen"]
        ),
        "formula_agrees_with_product": agrees,
        "rows": pairs,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))
    return 0


def _unit(vector) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float64).ravel()
    norm = float(np.linalg.norm(arr))
    return arr if norm <= 0.0 else arr / norm


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
