"""H11 isolated spatiotemporal-noticing experiment.

The neural observations are regenerated from H6's render protocol. Map and
tracker errors are deliberately a seeded mechanism simulation because H6 did
not preserve synchronized SLAM/tracker observations. See DESIGN.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

LABELS = ("person", "bench", "tree", "building", "lamppost", "planter", "door")
MIN_SCORE = 0.10
MIN_BOX_PIXELS = 32 * 32
IOU_THRESHOLD = 0.50
VISUAL_SCALE = 0.20
MAP_CELL_M = 0.75
AGE_HORIZON_S = 30.0
NOTICE_THRESHOLD = 0.70
REPLAY_HZ = 2.0
H6_HALLUCINATION_FLOOR_PER_MIN = 0.40
H6_HISTORICAL_AUC = 0.7235915492957746
SEEDS = tuple(range(100))


@dataclass(frozen=True)
class Crop:
    """One detector-matched, actually embedded H6 render crop."""

    frame: int
    instance: int
    label: str
    score: float
    embedding: np.ndarray
    world_xy: tuple[float, float]


@dataclass(frozen=True)
class Pair:
    """Same probe under counterfactual new and seen galleries."""

    crop: Crop
    visual_new: float
    visual_seen: float
    age_seen: float


def _unit(vector: np.ndarray) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float64).ravel()
    norm = float(np.linalg.norm(array))
    return array if norm <= 0.0 else array / norm


def _iou(left: list[float], right: list[float]) -> float:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    ix0, iy0 = max(lx0, rx0), max(ly0, ry0)
    ix1, iy1 = min(lx1, rx1), min(ly1, ry1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if intersection <= 0.0:
        return 0.0
    left_area = max(0.0, lx1 - lx0) * max(0.0, ly1 - ly0)
    right_area = max(0.0, rx1 - rx0) * max(0.0, ry1 - ry0)
    union = left_area + right_area - intersection
    return intersection / union if union > 0.0 else 0.0


def _match(
    predictions: list[dict[str, Any]], truth: list[dict[str, Any]]
) -> dict[int, int]:
    by_label: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(truth):
        if item["label"] in LABELS:
            by_label[str(item["label"])].append(index)
    consumed: set[int] = set()
    matches: dict[int, int] = {}
    order = sorted(range(len(predictions)), key=lambda index: -predictions[index]["score"])
    for prediction_index in order:
        prediction = predictions[prediction_index]
        candidates = (
            (index, _iou(prediction["box"], truth[index]["box"]))
            for index in by_label.get(prediction["label"], ())
            if index not in consumed
        )
        eligible = [(index, overlap) for index, overlap in candidates if overlap >= IOU_THRESHOLD]
        if not eligible:
            continue
        best_index, _ = max(eligible, key=lambda item: item[1])
        consumed.add(best_index)
        matches[prediction_index] = best_index
    return matches


def _rank_auc(positives: list[float], negatives: list[float]) -> float:
    """Mann-Whitney AUC with half credit for ties."""

    if not positives or not negatives:
        raise ValueError("AUC requires both classes")
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def _percentile(values: list[float], quantile: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), quantile))


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "p05": _percentile(values, 0.05),
        "median": statistics.median(values),
        "p95": _percentile(values, 0.95),
        "max": max(values),
    }


def _visual(raw_novelty: float) -> float:
    return min(1.0, max(0.0, raw_novelty / VISUAL_SCALE))


def _fused(visual: float, map_novel: float, track_novel: float, age: float) -> float:
    return 0.35 * visual + 0.35 * map_novel + 0.20 * track_novel + 0.10 * age


def _ablation(visual: float, signal: float, signal_weight: float) -> float:
    return (0.35 * visual + signal_weight * signal) / (0.35 + signal_weight)


def _cell(position: tuple[float, float]) -> tuple[int, int]:
    return math.floor(position[0] / MAP_CELL_M), math.floor(position[1] / MAP_CELL_M)


def _noisy(
    position: tuple[float, float], rng: np.random.Generator, sigma_m: float
) -> tuple[float, float]:
    noise = rng.normal(0.0, sigma_m, size=2)
    return position[0] + float(noise[0]), position[1] + float(noise[1])


def _map_novelty(
    probe: Crop,
    instances: dict[int, Crop],
    *,
    include_self: bool,
    sigma_m: float,
    rng: np.random.Generator,
) -> float:
    observed_cell = _cell(_noisy(probe.world_xy, rng, sigma_m))
    for instance, memory in instances.items():
        if memory.label != probe.label:
            continue
        if instance == probe.instance and not include_self:
            continue
        memory_cell = _cell(_noisy(memory.world_xy, rng, sigma_m))
        if max(abs(observed_cell[0] - memory_cell[0]), abs(observed_cell[1] - memory_cell[1])) <= 1:
            return 0.0
    return 1.0


def _score_pairs(
    pairs: list[Pair],
    instances: dict[int, Crop],
    *,
    seed: int,
    sigma_m: float,
    track_recall: float,
    false_association: float,
) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    arms: dict[str, tuple[list[float], list[float]]] = {
        name: ([], [])
        for name in (
            "visual",
            "visual_age",
            "visual_map",
            "visual_track",
            "fused",
            "refuter_no_age",
            "refuter_coupled_age",
        )
    }
    map_new_false_familiar = map_seen_missed = 0
    for pair in pairs:
        visual_new = _visual(pair.visual_new)
        visual_seen = _visual(pair.visual_seen)
        map_new = _map_novelty(
            pair.crop, instances, include_self=False, sigma_m=sigma_m, rng=rng
        )
        map_seen = _map_novelty(
            pair.crop, instances, include_self=True, sigma_m=sigma_m, rng=rng
        )
        track_new = 0.0 if rng.random() < false_association else 1.0
        track_seen = 0.0 if rng.random() < track_recall else 1.0
        map_new_false_familiar += map_new == 0.0
        map_seen_missed += map_seen == 1.0
        # Post-run refuter: age cannot be looked up without an association.
        # A false new-object association inherits a recent age (0), while an
        # unassociated repeat looks unseen (1). This was added after the
        # headline run and never changes its frozen criteria.
        coupled_age_new = 1.0 if map_new == 1.0 and track_new == 1.0 else 0.0
        coupled_age_seen = (
            pair.age_seen if map_seen == 0.0 or track_seen == 0.0 else 1.0
        )
        values = {
            "visual": (visual_new, visual_seen),
            "visual_age": (
                _ablation(visual_new, 1.0, 0.10),
                _ablation(visual_seen, pair.age_seen, 0.10),
            ),
            "visual_map": (
                _ablation(visual_new, map_new, 0.35),
                _ablation(visual_seen, map_seen, 0.35),
            ),
            "visual_track": (
                _ablation(visual_new, track_new, 0.20),
                _ablation(visual_seen, track_seen, 0.20),
            ),
            "fused": (
                _fused(visual_new, map_new, track_new, 1.0),
                _fused(visual_seen, map_seen, track_seen, pair.age_seen),
            ),
            "refuter_no_age": (
                (0.35 * visual_new + 0.35 * map_new + 0.20 * track_new) / 0.90,
                (0.35 * visual_seen + 0.35 * map_seen + 0.20 * track_seen) / 0.90,
            ),
            "refuter_coupled_age": (
                _fused(visual_new, map_new, track_new, coupled_age_new),
                _fused(visual_seen, map_seen, track_seen, coupled_age_seen),
            ),
        }
        for name, (new_score, seen_score) in values.items():
            arms[name][0].append(new_score)
            arms[name][1].append(seen_score)
    report: dict[str, float] = {}
    for name, (new_scores, seen_scores) in arms.items():
        report[f"{name}_auc"] = _rank_auc(new_scores, seen_scores)
    fused_new = arms["fused"][0]
    report["new_recall"] = sum(score >= NOTICE_THRESHOLD for score in fused_new) / len(fused_new)
    coupled_new = arms["refuter_coupled_age"][0]
    report["refuter_coupled_new_recall"] = sum(
        score >= NOTICE_THRESHOLD for score in coupled_new
    ) / len(coupled_new)
    report["map_new_false_familiar_rate"] = map_new_false_familiar / len(pairs)
    report["map_seen_miss_rate"] = map_seen_missed / len(pairs)
    return report


def _causal_replay(
    crops: list[Crop],
    *,
    seed: int,
    sigma_m: float,
    track_recall: float,
    false_association: float,
) -> dict[str, float | int]:
    rng = np.random.default_rng(seed)
    gallery: list[np.ndarray] = []
    map_memory: dict[int, tuple[str, tuple[float, float]]] = {}
    last_seen: dict[int, float] = {}
    new_total = new_triggered = repeat_total = repeat_triggered = 0
    for crop in sorted(crops, key=lambda item: (item.frame, item.instance)):
        now_s = crop.frame / REPLAY_HZ
        is_new = crop.instance not in last_seen
        if gallery:
            matrix = np.vstack(gallery)
            raw_visual = max(0.0, 1.0 - float((matrix @ crop.embedding).max()))
        else:
            raw_visual = 1.0
        visual = _visual(raw_visual)
        observed_cell = _cell(_noisy(crop.world_xy, rng, sigma_m))
        familiar_cell = False
        for label, position in map_memory.values():
            if label != crop.label:
                continue
            memory_cell = _cell(position)
            if max(
                abs(observed_cell[0] - memory_cell[0]),
                abs(observed_cell[1] - memory_cell[1]),
            ) <= 1:
                familiar_cell = True
                break
        map_novel = 0.0 if familiar_cell else 1.0
        if is_new:
            track_novel = 0.0 if rng.random() < false_association else 1.0
            age = 1.0
            new_total += 1
        else:
            track_novel = 0.0 if rng.random() < track_recall else 1.0
            age = min(1.0, max(0.0, (now_s - last_seen[crop.instance]) / AGE_HORIZON_S))
            repeat_total += 1
        score = _fused(visual, map_novel, track_novel, age)
        if score >= NOTICE_THRESHOLD:
            if is_new:
                new_triggered += 1
            else:
                repeat_triggered += 1
        gallery.append(crop.embedding)
        map_memory[crop.instance] = (crop.label, _noisy(crop.world_xy, rng, sigma_m))
        last_seen[crop.instance] = now_s
    exposure_min = (max(crop.frame for crop in crops) + 1) / REPLAY_HZ / 60.0
    false_repeat_per_min = repeat_triggered / exposure_min
    return {
        "new_instances": new_total,
        "new_triggered": new_triggered,
        "new_recall": new_triggered / new_total,
        "repeat_observations": repeat_total,
        "repeat_triggered": repeat_triggered,
        "repeat_suppression": 1.0 - repeat_triggered / repeat_total,
        "false_repeats_per_min": false_repeat_per_min,
        "false_plus_h6_floor_per_min": false_repeat_per_min
        + H6_HALLUCINATION_FLOOR_PER_MIN,
        "exposure_min": exposure_min,
    }


def _benchmark() -> dict[str, float | int | str]:
    rng = np.random.default_rng(20260824)
    values = rng.random((100_000, 4))
    chunks_ms_per_observation: list[float] = []
    checksum = 0.0
    for start in range(0, len(values), 100):
        before = time.perf_counter_ns()
        for visual, map_novel, track_novel, age in values[start : start + 100]:
            checksum += _fused(float(visual), float(map_novel), float(track_novel), float(age))
        elapsed_ms = (time.perf_counter_ns() - before) / 1e6
        chunks_ms_per_observation.append(elapsed_ms / 100.0)
    return {
        "scope": "weighted scalar fusion arithmetic only",
        "excluded": (
            "map lookup, track association, age lookup, feature extraction, "
            "serialization, and IPC"
        ),
        "decisions": len(values),
        "p50_ms_per_observation": _percentile(chunks_ms_per_observation, 0.50),
        "p95_ms_per_observation": _percentile(chunks_ms_per_observation, 0.95),
        "checksum": checksum,
    }


def _world_positions(repo: Path) -> dict[int, tuple[float, float]]:
    import mujoco

    scene = repo / "src/parcel_robot/scenes/city_block.xml"
    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return {
        (geom_id + 1) & 0xFFFF: (
            float(data.geom_xpos[geom_id][0]),
            float(data.geom_xpos[geom_id][1]),
        )
        for geom_id in range(model.ngeom)
    }


def _collect_crops(
    repo: Path, corpus: Path, socket_path: Path
) -> tuple[list[Crop], dict[str, Any]]:
    from parcel_robot.perception_daemon.client import DaemonClient

    manifest = json.loads((corpus / "renders_gt.json").read_text())
    with np.load(corpus / "renders.npz") as archive:
        colors = np.ascontiguousarray(archive["color"][:, ::2, ::2, :])
    positions = _world_positions(repo)
    crops: list[Crop] = []
    detections = matched = 0
    started = time.perf_counter()
    client = DaemonClient(str(socket_path), request_timeout_s=30.0)
    try:
        client.embed_image(np.zeros((32, 32, 3), dtype=np.uint8))
        for frame_index, record in enumerate(manifest["records"]):
            rgb = colors[frame_index]
            response = client.detect(rgb, LABELS)
            rows: list[dict[str, Any]] = []
            for item in response.get("detections", []):
                u0, v0, u1, v1 = (int(value) for value in item["box"])
                score = float(item["score"])
                if score < MIN_SCORE or (u1 - u0) * (v1 - v0) < MIN_BOX_PIXELS:
                    continue
                rows.append(
                    {
                        "label": str(item["label"]),
                        "score": score,
                        "box": [u0, v0, u1, v1],
                    }
                )
            detections += len(rows)
            truth = [
                {
                    **item,
                    "box": [float(value) / 2.0 for value in item["box"]],
                }
                for item in record["gt"]
            ]
            matches = _match(rows, truth)
            matched += len(matches)
            for prediction_index, truth_index in matches.items():
                row = rows[prediction_index]
                item = truth[truth_index]
                instance = int(item["seg_id"])
                position = positions.get(instance)
                if position is None:
                    continue
                u0, v0, u1, v1 = row["box"]
                embedding = _unit(client.embed_image(np.ascontiguousarray(rgb[v0:v1, u0:u1])))
                crops.append(
                    Crop(
                        frame=frame_index,
                        instance=instance,
                        label=str(item["label"]),
                        score=float(row["score"]),
                        embedding=embedding,
                        world_xy=position,
                    )
                )
        health = client.health()
    finally:
        client.close()
    return crops, {
        "frames": len(colors),
        "quality_detections": detections,
        "matched_and_embedded": matched,
        "usable_crops": len(crops),
        "elapsed_s": time.perf_counter() - started,
        "daemon_health": health,
    }


def _make_pairs(crops: list[Crop]) -> list[Pair]:
    by_instance: dict[int, list[int]] = defaultdict(list)
    for index, crop in enumerate(crops):
        by_instance[crop.instance].append(index)
    pairs: list[Pair] = []
    for probe_index, probe in enumerate(crops):
        same_indices = [index for index in by_instance[probe.instance] if index != probe_index]
        other_indices = [
            index for index, crop in enumerate(crops) if crop.instance != probe.instance
        ]
        if not same_indices or not other_indices:
            continue
        other_matrix = np.vstack([crops[index].embedding for index in other_indices])
        same_matrix = np.vstack([crops[index].embedding for index in same_indices])
        novelty_new = max(0.0, 1.0 - float((other_matrix @ probe.embedding).max()))
        warm_matrix = np.vstack((other_matrix, same_matrix))
        novelty_seen = max(0.0, 1.0 - float((warm_matrix @ probe.embedding).max()))
        nearest_frame = min(abs(probe.frame - crops[index].frame) for index in same_indices)
        age_seen = min(1.0, nearest_frame / REPLAY_HZ / AGE_HORIZON_S)
        pairs.append(Pair(probe, novelty_new, novelty_seen, age_seen))
    return pairs


def _generate_corpus(repo: Path, corpus: Path) -> None:
    builder = repo / "research/20260823/noticing-loop-perception/harness/build_render_corpus.py"
    subprocess.run(
        [str(repo / ".parcel/bin/python"), str(builder), str(corpus)],
        cwd=repo,
        check=True,
    )


def _start_daemon(repo: Path, socket_path: Path, log_path: Path) -> subprocess.Popen[str]:
    environment = dict(os.environ)
    environment.update(
        {
            "PARCEL_PERCEPTION_PROVIDER": "cuda_fp16",
            "PARCEL_OWLV2_ONNX": "1",
            "PARCEL_SIGLIP2_ONNX": "1",
        }
    )
    log = log_path.open("w")
    process = subprocess.Popen(
        [
            str(repo / ".parcel/bin/python"),
            "-m",
            "parcel_robot.perception_daemon",
            "--socket",
            str(socket_path),
            "--preload",
        ],
        cwd=repo,
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process._h11_log = log  # type: ignore[attr-defined]
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log.close()
            raise RuntimeError(f"private perception daemon exited {process.returncode}")
        if socket_path.exists():
            return process
        time.sleep(0.2)
    process.terminate()
    process.wait(timeout=10)
    log.close()
    raise TimeoutError("private perception daemon did not become ready")


def _stop_daemon(process: subprocess.Popen[str], socket_path: Path) -> None:
    from parcel_robot.perception_daemon.client import DaemonClient

    try:
        client = DaemonClient(str(socket_path))
        client.shutdown()
    except Exception:  # noqa: BLE001 - bounded cleanup of this harness's child only
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    log = getattr(process, "_h11_log", None)
    if log is not None:
        log.close()


def _revision(repo: Path) -> dict[str, str]:
    scene = repo / "src/parcel_robot/scenes/city_block.xml"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    return {
        "git_head": head,
        "scene_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(),
    }


def run(repo: Path, work_dir: Path) -> dict[str, Any]:
    corpus = work_dir / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    _generate_corpus(repo, corpus)
    socket_path = work_dir / "h11-perception.sock"
    daemon = _start_daemon(repo, socket_path, work_dir / "daemon.log")
    try:
        crops, collection = _collect_crops(repo, corpus, socket_path)
    finally:
        _stop_daemon(daemon, socket_path)
    pairs = _make_pairs(crops)
    if not pairs:
        raise RuntimeError("no paired observations were produced")
    instances = {crop.instance: crop for crop in crops}

    nominal_runs = [
        _score_pairs(
            pairs,
            instances,
            seed=seed,
            sigma_m=0.20,
            track_recall=0.85,
            false_association=0.02,
        )
        for seed in SEEDS
    ]
    paired_summary = {
        key: _summary([run_row[key] for run_row in nominal_runs])
        for key in nominal_runs[0]
    }

    replay_runs = [
        _causal_replay(
            crops,
            seed=seed,
            sigma_m=0.20,
            track_recall=0.85,
            false_association=0.02,
        )
        for seed in SEEDS
    ]
    replay_summary = {
        key: _summary([float(run_row[key]) for run_row in replay_runs])
        for key in (
            "new_recall",
            "repeat_suppression",
            "false_repeats_per_min",
            "false_plus_h6_floor_per_min",
        )
    }
    replay_counts = {
        key: replay_runs[0][key]
        for key in ("new_instances", "repeat_observations", "exposure_min")
    }

    sensitivity: list[dict[str, float]] = []
    for sigma_m in (0.10, 0.20, 0.40, 0.75):
        for track_recall in (0.65, 0.75, 0.85, 0.95):
            for false_association in (0.00, 0.02, 0.05):
                rows = [
                    _score_pairs(
                        pairs,
                        instances,
                        seed=seed,
                        sigma_m=sigma_m,
                        track_recall=track_recall,
                        false_association=false_association,
                    )
                    for seed in SEEDS
                ]
                sensitivity.append(
                    {
                        "map_sigma_m": sigma_m,
                        "track_recall": track_recall,
                        "new_false_association": false_association,
                        "fused_auc_median": statistics.median(row["fused_auc"] for row in rows),
                        "new_recall_median": statistics.median(
                            row["new_recall"] for row in rows
                        ),
                        "coupled_age_auc_median": statistics.median(
                            row["refuter_coupled_age_auc"] for row in rows
                        ),
                        "coupled_age_new_recall_median": statistics.median(
                            row["refuter_coupled_new_recall"] for row in rows
                        ),
                    }
                )

    visual_auc = paired_summary["visual_auc"]["median"]
    benchmark = _benchmark()
    criteria = {
        "S1_visual_drift_within_0_03": abs(visual_auc - H6_HISTORICAL_AUC) <= 0.03,
        "S2_fused_auc_at_least_0_80": paired_summary["fused_auc"]["median"] >= 0.80,
        "S3_new_recall_at_least_0_80": paired_summary["new_recall"]["median"] >= 0.80,
        "S4_repeat_suppression_at_least_0_95": replay_summary["repeat_suppression"][
            "median"
        ]
        >= 0.95,
        "S5_false_total_at_most_1_per_min": replay_summary[
            "false_plus_h6_floor_per_min"
        ]["median"]
        <= 1.0,
        "S6_decision_p95_at_most_0_5_ms": benchmark["p95_ms_per_observation"] <= 0.5,
    }
    arithmetic_criteria_met = all(criteria.values())
    evidence_sufficiency = {
        "sufficient_for_mechanism_direction": True,
        "sufficient_for_prototype_confirmation": False,
        "S5_false_rate_exposure_sufficient": False,
        "S5_exposure_min_per_seed": replay_counts["exposure_min"],
        "S5_h6_floor_is_fixed_point_estimate": True,
        "map_track_age_are_empirical_sensor_signals": False,
        "fusion_latency_is_end_to_end": False,
        "reason": (
            "each causal replay is 0.35 min; map, track, and age signals are "
            "generated around simulator truth identity/class; the H6 0.40/min "
            "hallucination value is added as a fixed point estimate; and the "
            "latency benchmark times scalar arithmetic only"
        ),
    }
    overall_criteria_met = arithmetic_criteria_met and evidence_sufficiency[
        "sufficient_for_prototype_confirmation"
    ]
    return {
        "experiment": "H11-spatiotemporal-noticing",
        "evidence_tier": "desktop-render-replay + seeded mechanism simulation",
        "overall_hypothesis_status": (
            "INCONCLUSIVE_FOR_PROTOTYPE__MECHANISM_DIRECTION_SUPPORTED"
        ),
        "revision": _revision(repo),
        "fixed_parameters": {
            "visual_scale": VISUAL_SCALE,
            "weights": {"visual": 0.35, "map": 0.35, "track": 0.20, "age": 0.10},
            "notice_threshold": NOTICE_THRESHOLD,
            "map_cell_m": MAP_CELL_M,
            "age_horizon_s": AGE_HORIZON_S,
            "nominal_map_sigma_m": 0.20,
            "nominal_track_recall": 0.85,
            "nominal_new_false_association": 0.02,
            "seeds": [min(SEEDS), max(SEEDS)],
        },
        "h6_anchor": {
            "historical_paired_auc": H6_HISTORICAL_AUC,
            "historical_pairs": 142,
            "historical_false_hallucinations_per_min": H6_HALLUCINATION_FLOOR_PER_MIN,
            "raw_pair_rows_preserved": False,
            "synchronized_spatial_track_rows_preserved": False,
            "false_hallucination_floor_usage": (
                "fixed 0.40/min point estimate added to each simulated repeat rate; "
                "no uncertainty distribution was propagated"
            ),
        },
        "signal_provenance": {
            "visual": "actual OWLv2/SigLIP outputs over regenerated simulator renders",
            "class_and_identity": "MuJoCo segmentation truth",
            "map": (
                "simulator-truth class/geometry position plus seeded Gaussian noise; "
                "not a SLAM observation"
            ),
            "track": (
                "seeded Bernoulli association around simulator-truth identity; "
                "not tracker output"
            ),
            "age": (
                "simulator frame order and truth-derived association; not a measured "
                "runtime memory lookup"
            ),
        },
        "collection": collection,
        "paired_observations": len(pairs),
        "unique_instances": len(instances),
        "nominal_paired": paired_summary,
        "post_run_refuter": {
            "status": "exploratory; added after headline results without moving any bar",
            "question": (
                "does the result survive removing age or making age depend on a map/track "
                "association?"
            ),
            "no_age_auc": paired_summary["refuter_no_age_auc"],
            "coupled_age_auc": paired_summary["refuter_coupled_age_auc"],
            "coupled_age_new_recall": paired_summary["refuter_coupled_new_recall"],
            "map_new_false_familiar_rate": paired_summary[
                "map_new_false_familiar_rate"
            ],
            "map_seen_miss_rate": paired_summary["map_seen_miss_rate"],
        },
        "nominal_causal_replay": {**replay_counts, **replay_summary},
        "sensitivity": sensitivity,
        "benchmark": benchmark,
        "criteria_scope": "pre-registered arithmetic comparisons; not evidence sufficiency",
        "criteria": criteria,
        "pre_registered_arithmetic_criteria_met": arithmetic_criteria_met,
        "evidence_sufficiency": evidence_sufficiency,
        "all_required_criteria_met": overall_criteria_met,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    report = run(repo, work_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["all_required_criteria_met"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
