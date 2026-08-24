"""H6 scoring — every criterion computed from the raw rows, by one set of rules.

The rules are written down here BEFORE they were run against any output, and
they are the same rules for every venue:

MATCHING  greedy, per label, score-descending, IoU >= 0.5, each ground-truth
          instance consumed at most once. COCO ``iscrowd`` person regions are
          IGNORE: a prediction that overlaps one (IoU >= 0.5 or >= 0.5 of the
          prediction's own area) is neither a hit nor a false positive.
RECALL    per INSTANCE (matched GT / all GT) and per IMAGE (images with >= 1
          matched instance / images holding any) — the 2026-08-21 bench does
          not say which "n=156" counts, so both are reported and neither is
          quietly chosen after the fact.
FP RATE   unmatched predictions of a scored label per frame.
FALSE NOTICING  a noticing is FALSE when (a) its box matches no GT of its label
          — the loop reported something that is not there — or (b) the GT
          instance it matched was already noticed earlier in this run — the
          loop re-reported a known thing. Everything else is a TRUE noticing.
TAU SWEEP the recorded novelty of every observation is independent of tau (the
          gallery is updated for every quality-passing observation, noticed or
          not), so the whole tau curve is replayed offline THROUGH THE PRODUCT
          GATE: a replay gallery hands ``NoticingLoop`` the recorded novelty in
          order, and its own cooldown and rate limiter decide. No number here
          comes from a second implementation of the policy.
AUC       novelty as the score, positives = an instance's FIRST embedded
          appearance in the run, negatives = every later appearance of an
          instance already seen. Mann-Whitney U / (n_pos * n_neg), ties 0.5.
          Observations that match no GT instance carry no identity and are
          excluded (counted separately, never silently dropped).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from parcel_robot.perception.noticing import NoticingGate, NoticingLoop, Observation

IOU_MATCH = 0.5
TAU_GRID = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60)


class _ReplayGallery:
    """Hands back the novelty each observation actually scored, in order.

    Lets the tau curve be swept through the real ``NoticingLoop`` gate — the
    cooldown and the rate limiter are the product's, not a copy of them.
    """

    def __init__(self, novelties: list[float], limit: int = 512) -> None:
        self._novelties = list(novelties)
        self._index = 0
        self._count = 0
        self._limit = limit

    def __len__(self) -> int:
        return self._count

    @property
    def limit(self) -> int:
        return self._limit

    def add(self, vector: Any) -> None:
        self._count = min(self._limit, self._count + 1)

    def nearest_cosine(self, vector: Any) -> float:
        value = self._novelties[self._index]
        self._index += 1
        return max(0.0, 1.0 - value)

    def novelty(self, vector: Any) -> float:
        return min(1.0, max(0.0, 1.0 - self.nearest_cosine(vector)))


def iou(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _ignored(box: list[float], ignores: list[list[float]]) -> bool:
    area = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    for region in ignores:
        ix0, iy0 = max(box[0], region[0]), max(box[1], region[1])
        ix1, iy1 = min(box[2], region[2]), min(box[3], region[3])
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        if inter <= 0.0:
            continue
        if iou(box, region) >= IOU_MATCH or (area > 0 and inter / area >= 0.5):
            return True
    return False


def match_frame(
    predictions: list[dict[str, Any]],
    truth: list[dict[str, Any]],
    *,
    labels: set[str],
) -> tuple[dict[int, int], list[int]]:
    """(prediction index -> gt index) and the list of unmatched prediction indices."""

    by_label: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(truth):
        if item["label"] in labels and not item.get("iscrowd", False):
            by_label[item["label"]].append(index)
    taken: set[int] = set()
    matched: dict[int, int] = {}
    unmatched: list[int] = []
    order = sorted(range(len(predictions)), key=lambda i: -float(predictions[i]["score"]))
    for prediction_index in order:
        prediction = predictions[prediction_index]
        best_index, best_iou = None, 0.0
        for gt_index in by_label.get(prediction["label"], []):
            if gt_index in taken:
                continue
            overlap = iou(prediction["box"], truth[gt_index]["box"])
            if overlap >= IOU_MATCH and overlap > best_iou:
                best_index, best_iou = gt_index, overlap
        if best_index is None:
            unmatched.append(prediction_index)
        else:
            taken.add(best_index)
            matched[prediction_index] = best_index
    return matched, unmatched


def _gt_for(gt_doc: dict, clip: str) -> list[list[dict]]:
    for entry in gt_doc["clips"]:
        if entry["clip"] == clip:
            return [record["objects"] for record in entry["records"]]
    raise SystemExit(f"no ground truth for {clip}")


def rank_auc(positives: list[float], negatives: list[float]) -> float | None:
    """Mann-Whitney U / (n_pos * n_neg) with mid-ranks for ties, O(n log n)."""

    if not positives or not negatives:
        return None
    pooled = sorted((value, index) for index, value in
                    enumerate([*positives, *negatives]))
    ranks = [0.0] * len(pooled)
    position = 0
    while position < len(pooled):
        end = position
        while end + 1 < len(pooled) and pooled[end + 1][0] == pooled[position][0]:
            end += 1
        average = (position + end) / 2.0 + 1.0
        for slot in range(position, end + 1):
            ranks[pooled[slot][1]] = average
        position = end + 1
    n_pos = len(positives)
    rank_sum = sum(ranks[:n_pos])
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * len(negatives))


def _instance_key(item: dict[str, Any], gt_frame: int, slot: int) -> tuple:
    """Identity of a ground-truth instance ACROSS frames.

    A render instance is its MuJoCo segmentation id, so the same pedestrian
    seen from a new range and bearing is the same instance (that is the whole
    point of a repeat-noticing count). A photo instance is only itself.
    """

    seg = item.get("seg_id")
    if seg is not None:
        return ("seg", int(seg))
    return ("frame", gt_frame, slot)


def annotate(run: dict, gt_doc: dict) -> list[dict[str, Any]]:
    """Every observation row, tagged with the ground-truth instance it matched."""

    truth = _gt_for(gt_doc, run["clip"])
    labels = set(run["labels"])
    by_frame: dict[int, list[dict]] = defaultdict(list)
    for detection in run["detection_rows"]:
        by_frame[detection["frame"]].append(detection)
    annotated: list[dict[str, Any]] = []
    for frame_index in sorted(by_frame):
        rows = by_frame[frame_index]
        gt_index = rows[0]["gt_frame"]
        matched, _ = match_frame(rows, truth[gt_index], labels=labels)
        ignores = [
            item["box"] for item in truth[gt_index]
            if item["label"] == "person" and item.get("iscrowd")
        ]
        for position, detection in enumerate(rows):
            slot = matched.get(position)
            key = (
                None if slot is None
                else _instance_key(truth[gt_index][slot], gt_index, slot)
            )
            annotated.append(
                {
                    **detection,
                    "instance": key,
                    "ignored": slot is None and _ignored(detection["box"], ignores),
                }
            )
    return annotated


def _score_annotated(
    annotated: list[dict[str, Any]], duration_s: float, *, field: str
) -> dict[str, Any]:
    seen: set[tuple] = set()
    noticed: set[tuple] = set()
    hallucinations = repeats = true_noticings = unidentified = 0
    novelty_new: list[float] = []
    novelty_seen: list[float] = []
    for row in annotated:
        key = row["instance"]
        if key is None:
            unidentified += 1
            if row[field] and not row["ignored"]:
                hallucinations += 1
            continue
        if key in seen:
            novelty_seen.append(row["novelty"])
        else:
            novelty_new.append(row["novelty"])
            seen.add(key)
        if row[field]:
            if key in noticed:
                repeats += 1
            else:
                true_noticings += 1
                noticed.add(key)
    minutes = duration_s / 60.0 if duration_s else 0.0
    total = sum(1 for row in annotated if row[field])
    auc = rank_auc(novelty_new, novelty_seen)
    return {
        "noticings": total,
        "true_noticings": true_noticings,
        "false_noticings": hallucinations + repeats,
        "false_hallucination": hallucinations,
        "false_repeat": repeats,
        "false_noticings_per_min": (hallucinations + repeats) / minutes if minutes else None,
        "noticings_per_min": total / minutes if minutes else None,
        "novelty_auc_first_vs_later": auc,
        "auc_first_n": len(novelty_new), "auc_later_n": len(novelty_seen),
        "observations_without_gt_identity": unidentified,
    }


def tau_sweep(
    run: dict, annotated: list[dict[str, Any]], *, max_per_minute: int | None = None
) -> dict[str, Any]:
    """The whole tau curve, replayed through the product gate (see module docstring).

    ``max_per_minute=None`` keeps the run's own rate ceiling; a large value
    lifts it, which is the only way to see the NATURAL noticing rate under the
    ceiling that the run itself was pinned at.
    """

    gate_config = run["gate"]
    ceiling = gate_config["max_per_minute"] if max_per_minute is None else int(max_per_minute)
    novelties = [row["novelty"] for row in annotated]
    curve: dict[str, Any] = {}
    for tau in TAU_GRID:
        gate = NoticingGate(
            novelty_tau=tau,
            min_score=gate_config["min_score"],
            min_box_pixels=gate_config["min_box_pixels"],
            cooldown_s=gate_config["cooldown_s"],
            max_per_minute=ceiling,
            gallery_limit=gate_config["gallery_limit"],
        )
        loop = NoticingLoop(gate=gate, gallery=_ReplayGallery(novelties, gate.gallery_limit))
        replayed = []
        for row in annotated:
            observation = Observation(
                label=row["label"], score=row["score"], box=tuple(row["box"]),
                embedding=(1.0,), monotonic_ns=row["monotonic_ns"],
            )
            replayed.append({**row, "replayed": loop.observe(observation) is not None})
        scored = _score_annotated(replayed, run["duration_s"], field="replayed")
        scored["loop_stats"] = loop.stats.as_dict()
        curve[f"{tau:.2f}"] = scored
    live_tau = f"{gate_config['novelty_tau']:.2f}"
    live = _score_annotated(annotated, run["duration_s"], field="noticed")
    curve["_rate_ceiling_per_min"] = ceiling
    curve["_replay_matches_live_run"] = (
        max_per_minute is None
        and live_tau in curve
        and curve[live_tau]["noticings"] == live["noticings"]
    )
    return curve


def score_loop(run: dict, gt_doc: dict) -> dict[str, Any]:
    """P1-P5 and P7 for one loop run."""

    annotated = annotate(run, gt_doc)
    rows = run["frame_rows"]
    latencies = [row["publish_latency_ms"] for row in rows]
    ttl_ms = 300.0
    scored = _score_annotated(annotated, run["duration_s"], field="noticed")
    return {
        "run": run["run"], "clip": run["clip"], "requested_hz": run["requested_hz"],
        "gallery_impl": run.get("gallery_impl", "numpy"),
        "query_phrases": run.get("query_phrases"),
        "resolution": run.get("resolution"),
        "frames": run["frames"], "duration_s": run["duration_s"],
        "achieved_fps": run["achieved_fps"],
        "detect_daemon_ms": _stats([row["detect_daemon_ms"] for row in rows]),
        "detect_wall_ms": _stats([row["detect_wall_ms"] for row in rows]),
        "embed_ms": _stats([row["embed_ms"] for row in rows]),
        "decide_ms": _stats([row["decide_ms"] for row in rows]),
        "publish_latency_ms": _stats(latencies),
        "frames_past_ttl": sum(1 for value in latencies if value > ttl_ms),
        "latency_histogram_ms": _histogram(latencies),
        "detections_per_frame": _stats([float(row["raw_detections"]) for row in rows]),
        "embedded_per_frame": _stats([float(row["embedded"]) for row in rows]),
        **scored,
        "tau_sweep": tau_sweep(run, annotated),
        "tau_sweep_uncapped": tau_sweep(run, annotated, max_per_minute=100000),
        "loop_stats": run["loop_stats"],
        "contention": run.get("contention"),
        "smi_start": run.get("smi_start", {}).get("gpu"),
        "smi_mid": (run.get("smi_mid") or {}).get("gpu"),
        "smi_end": run.get("smi_end", {}).get("gpu"),
        "daemon_provider": run["daemon_health_after"].get("provider_profile"),
        "daemon_execution_providers": run["daemon_health_after"].get("execution_providers"),
    }


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        low = int(position)
        high = min(low + 1, len(ordered) - 1)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {
        "n": len(ordered), "p50": round(percentile(0.5), 2), "p95": round(percentile(0.95), 2),
        "p99": round(percentile(0.99), 2), "max": round(ordered[-1], 2),
        "min": round(ordered[0], 2),
        "mean": round(sum(ordered) / len(ordered), 2),
    }


def _histogram(values: list[float]) -> dict[str, int]:
    edges = [50, 100, 150, 200, 250, 300, 400, 600, 1000]
    buckets: dict[str, int] = {}
    previous = 0
    for edge in edges:
        buckets[f"{previous}-{edge}"] = sum(1 for v in values if previous <= v < edge)
        previous = edge
    buckets[f">{edges[-1]}"] = sum(1 for v in values if v >= edges[-1])
    return buckets


def score_sweep(sweep: dict, truth_frames: list[list[dict]], thresholds: list[float]) -> dict:
    """P6: recall / precision / FP-rate per threshold, per label, from one pass."""

    labels = set(sweep["labels"])
    out: dict[str, Any] = {
        "which": sweep["which"], "provider": sweep["provider"],
        "frames": sweep["frames"], "detect_ms": sweep["detect_ms"],
        "preprocess_ms": sweep["preprocess_ms"],
        "truncated_frames": sum(1 for row in sweep["rows"] if row["truncated"]),
        "verification": sweep.get("verification"),
        "thresholds": {},
    }
    for threshold in thresholds:
        person_gt = person_hit = 0
        images_with_person = images_recalled = 0
        person_fp = 0
        all_pred = all_hit = 0
        for row, frame_truth in zip(sweep["rows"], truth_frames, strict=True):
            predictions = [
                {"label": d["label"], "score": d["score"], "box": [float(v) for v in d["box"]]}
                for d in row["detections"] if d["score"] >= threshold
            ]
            ignores = [
                item["box"] for item in frame_truth
                if item["label"] == "person" and item.get("iscrowd")
            ]
            matched, unmatched = match_frame(predictions, frame_truth, labels=labels)
            persons = [
                item for item in frame_truth
                if item["label"] == "person" and not item.get("iscrowd")
            ]
            hits = sum(
                1 for prediction_index, gt_index in matched.items()
                if frame_truth[gt_index]["label"] == "person"
                and predictions[prediction_index]["label"] == "person"
            )
            person_gt += len(persons)
            person_hit += hits
            if persons:
                images_with_person += 1
                images_recalled += 1 if hits else 0
            person_fp += sum(
                1 for index in unmatched
                if predictions[index]["label"] == "person"
                and not _ignored(predictions[index]["box"], ignores)
            )
            all_pred += len(predictions)
            all_hit += len(matched)
        out["thresholds"][f"{threshold:.3f}"] = {
            "person_gt": person_gt, "person_matched": person_hit,
            "person_recall_instance": person_hit / person_gt if person_gt else None,
            "person_recall_image": images_recalled / images_with_person
            if images_with_person else None,
            "person_false_positives": person_fp,
            "person_fp_per_frame": person_fp / sweep["frames"],
            "predictions": all_pred, "matched": all_hit,
            "precision_all_labels": all_hit / all_pred if all_pred else None,
        }
    return out


def _sweep_truth(which: str, corpus: Path) -> list[list[dict]]:
    if which == "photos_native":
        manifest = json.loads((corpus / "photos_gt.json").read_text())
        return [record["objects"] for record in manifest["records"]]
    if which == "photos_640":
        clips = json.loads((corpus / "clips" / "clips_gt.json").read_text())
        return _gt_for(clips, "photos_640.npz")
    if which == "renders_1280":
        clips = json.loads((corpus / "clips" / "clips_gt.json").read_text())
        return _gt_for(clips, "renders_1280.npz")
    if which == "renders_640":
        clips = json.loads((corpus / "clips" / "clips_gt.json").read_text())
        return _gt_for(clips, "renders_640.npz")
    raise SystemExit(f"unknown sweep corpus {which}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H6 scoring")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--runs", nargs="*", default=[])
    parser.add_argument("--sweeps", nargs="*", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    corpus = Path(args.corpus)
    gt_doc = json.loads((corpus / "clips" / "clips_gt.json").read_text())
    thresholds = [0.02, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]

    report: dict[str, Any] = {"loops": [], "sweeps": []}
    for path in args.runs:
        report["loops"].append(score_loop(json.loads(Path(path).read_text()), gt_doc))
    for path in args.sweeps:
        sweep = json.loads(Path(path).read_text())
        report["sweeps"].append(
            score_sweep(sweep, _sweep_truth(sweep["which"], corpus), thresholds)
        )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
