"""C-2 live proof — build the map from C-1's REAL stream, score it against truth.

This is a replay, and the word is meant literally: the frames are the 16
``CameraDetectionFrame`` rows C-1 published from a live run of the real stack —
real MuJoCo renders of W-1's textured ``city_block`` scene (sha ``e89f4f12...``),
real OWLv2-b16 int8 on CPU, real robot poses, real query batch
``['person', 'lamppost']``. No pixel here is synthetic and no detection here was
invented by C-2.

What it measures, and against what
----------------------------------
``evals/nav_instruct/scene_truth.json`` is the PG-2 surface-convention artifact:
17 surfaces with polygon parts, ``measure: surface`` for objects. The map's
entry is scored by the distance from its fused surface point to the nearest
point on the truth polygon of the matching part — 0.0 when it lands inside.
That is the PG-2 convention applied honestly, not a centroid comparison
retitled.

Null controls are scored in the same pass and with the same code path, because
a retrieval result without a null control is a claim that its author declined
to falsify.

Run:
    PYTHONPATH=src .parcel/bin/python scrum/20260821/task_12b/evidence/run_c2_replay.py
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from parcel_robot.online_map import (
    OnlineMapStore,
    OnlineSemanticMap,
    WriterProvenance,
    map_freshness_report,
    observations_from_frame,
)

FIXTURE = REPO / "tests" / "data" / "c2_online_map_frames.json"
SCENE_TRUTH = REPO / "evals" / "nav_instruct" / "scene_truth.json"

#: Pre-registered null controls: nouns with no instance in this scene. Fixed
#: before the map was built; see C2_PREREGISTRATION.md.
NULL_CONTROLS = (
    "fire hydrant",
    "mailbox",
    "fountain",
    "traffic cone",
    "bicycle rack",
    "vending machine",
)

#: Pre-registered PG-2 surface tolerance for a live CPU patrol.
TOLERANCE_M = 1.0


class _Rec:
    def __init__(self, data: dict) -> None:
        self.__dict__.update(data)
        self.box = tuple(float(v) for v in data["box"])


class _Frame:
    def __init__(self, data: dict) -> None:
        self.__dict__.update(data)
        self.detections = tuple(_Rec(d) for d in data["detections"])
        self.queries = tuple(data.get("queries", ()))

    @property
    def publish_latency_ns(self) -> int:
        return int(self.published_monotonic_ns) - int(
            self.capture_started_monotonic_ns
        )


def _point_to_segment(px: float, py: float, ax: float, ay: float, bx: float,
                      by: float) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _inside(px: float, py: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            xin = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < xin:
                inside = not inside
    return inside


def surface_distance(px: float, py: float, parts: list[dict]) -> float:
    """PG-2 surface measure: distance to the nearest part surface, 0 inside.

    Handles both part shapes the truth artifact actually uses. The lampposts
    are ``shape: circle`` (centre + 0.06 m radius) and the buildings/benches are
    ``shape: rect`` polygons; an earlier draft of this scorer only understood
    polygons and silently returned ``inf`` for every lamppost — a scorer that
    cannot score the class under test is worse than no scorer, so both shapes
    are handled and an unrecognised one raises rather than returning a number.
    """

    best = float("inf")
    for part in parts:
        shape = part.get("shape")
        if shape == "circle":
            centre = part["center"]
            radius = float(part.get("radius_m", 0.0))
            best = min(
                best,
                max(0.0, math.hypot(px - float(centre[0]), py - float(centre[1]))
                    - radius),
            )
            continue
        poly = part.get("polygon") or []
        if len(poly) < 3:
            raise ValueError(f"unscoreable truth part: {part!r}")
        if _inside(px, py, poly):
            return 0.0
        for i in range(len(poly)):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % len(poly)]
            best = min(best, _point_to_segment(px, py, x1, y1, x2, y2))
    return best


def _part_centre(spec: dict) -> tuple[float, float]:
    part = spec["parts"][0]
    if part.get("shape") == "circle":
        return float(part["center"][0]), float(part["center"][1])
    poly = part["polygon"]
    return (
        sum(p[0] for p in poly) / len(poly),
        sum(p[1] for p in poly) / len(poly),
    )


#: Plausible metric extents per class, used ONLY to synthesize arm-B boxes.
_ARM_B_EXTENTS = {
    "lamppost": (0.12, 3.2),
    "tree": (1.6, 5.0),
    "planter": (0.9, 0.6),
    "bench": (1.4, 0.9),
    "door": (1.0, 2.1),
    "building": (8.0, 6.0),
}


def _run_truth_derived_arm(truth: dict, scratch: Path) -> dict:
    import random

    from parcel_robot.online_map import MapObservation

    random.seed(20260821)
    provenance = WriterProvenance(
        session_id="c2-arm-b",
        seat="async_keyframe_map",
        detector_name="truth-derived-synthetic",
        scene_id="city_block",
    )
    store_path = scratch / "c2_arm_b_map.sqlite3"
    if store_path.exists():
        store_path.unlink()
    store = OnlineMapStore(store_path)
    the_map = OnlineSemanticMap(store, provenance=provenance)

    targets = {
        key: spec
        for key, spec in truth.items()
        if spec.get("measure") == "surface" and spec.get("label") in _ARM_B_EXTENTS
    }
    queries = tuple(sorted({spec["label"] for spec in targets.values()}))

    # The robot walks a lap that passes every target, so navigability is
    # measured rather than assumed — same rule as arm A.
    for visit in range(3):
        for key, spec in sorted(targets.items()):
            cx, cy = _part_centre(spec)
            for step in range(8):
                angle = 2.0 * math.pi * step / 8
                the_map.note_pose(cx + 1.5 * math.cos(angle),
                                  cy + 1.5 * math.sin(angle))
        for frame_index in range(8):
            the_map.note_frame(queries)
            for key, spec in sorted(targets.items()):
                cx, cy = _part_centre(spec)
                label = spec["label"]
                w, h = _ARM_B_EXTENTS[label]
                the_map.observe(
                    MapObservation(
                        label=label,
                        score=0.55,
                        surface_x=cx + random.gauss(0.0, 0.05),
                        surface_y=cy + random.gauss(0.0, 0.05),
                        surface_z=1.0,
                        range_m=4.0,
                        bearing_rad=0.0,
                        depth_m=4.0,
                        extent_w_m=w,
                        extent_h_m=h,
                        inlier_pixels=4000,
                        frame_id=f"b{visit}-{frame_index}-{key}",
                        visit_id=f"arm-b-visit-{visit}",
                        observed_wall_s=1000.0 + visit * 100 + frame_index,
                        robot_x=cx,
                        robot_y=cy,
                        provenance=provenance,
                    )
                )
    the_map.persist()
    store.close()

    store2 = OnlineMapStore(store_path)
    reloaded = OnlineSemanticMap(store2, provenance=provenance)
    for key, spec in sorted(targets.items()):
        cx, cy = _part_centre(spec)
        for step in range(8):
            angle = 2.0 * math.pi * step / 8
            reloaded.note_pose(cx + 1.5 * math.cos(angle), cy + 1.5 * math.sin(angle))
    for _ in range(24):
        reloaded.note_frame(queries)

    rows = []
    within = 0
    admitted = 0
    for label in queries:
        result = reloaded.resolve(label)
        best = result.best
        if best is None:
            rows.append({"query": label, "candidates": 0, "surface_distance_m": None,
                         "within_tolerance": False, "pg3_admitted": False,
                         "pg3_reason": result.verdict.reason})
            continue
        distances = sorted(
            (surface_distance(best.x, best.y, spec.get("parts", [])), key)
            for key, spec in targets.items()
            if spec.get("label") == label
        )
        distance, matched = distances[0]
        ok = distance <= TOLERANCE_M
        within += int(ok)
        admitted += int(result.admitted)
        rows.append({
            "query": label,
            "candidates": len(result.candidates),
            "map_xy": [round(best.x, 4), round(best.y, 4)],
            "truth_part": matched,
            "surface_distance_m": round(distance, 4),
            "within_tolerance": ok,
            "evidence_frames": best.evidence_frames,
            "visits": best.visits,
            "pg3_admitted": bool(result.admitted),
            "pg3_reason": result.verdict.reason,
            "pg3_ranking_margin": round(
                float(result.verdict.signals.get("ranking_margin", 0.0)), 4),
            "ranking_background_degenerate":
                result.diagnostics["ranking_background_degenerate"],
        })

    nulls = []
    null_admitted = 0
    for query in NULL_CONTROLS:
        result = reloaded.resolve(query)
        null_admitted += int(result.admitted)
        nulls.append({"query": query, "candidates": len(result.candidates),
                      "admitted": bool(result.admitted),
                      "reason": result.verdict.reason})
    entries = len(reloaded)
    store2.close()
    return {
        "what_this_is": (
            "map path only: detections synthesized at scene_truth surfaces. "
            "NOT a perception claim."
        ),
        "entries": entries,
        "queries": list(queries),
        "query_table": rows,
        "within_tolerance": within,
        "pg3_admitted": admitted,
        "null_controls": nulls,
        "null_controls_admitted": null_admitted,
    }


def main() -> int:
    started = time.time()
    payload = json.loads(FIXTURE.read_text())
    frames = tuple(_Frame(f) for f in payload["frames"])
    truth = json.loads(SCENE_TRUTH.read_text())["surfaces"]

    scratch = Path(
        os.environ.get("C2_SCRATCH")
        or "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/"
        "799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/c2_live"
    )
    scratch.mkdir(parents=True, exist_ok=True)
    store_path = scratch / "c2_replay_map.sqlite3"
    if store_path.exists():
        store_path.unlink()

    provenance = WriterProvenance(
        session_id=f"c2-replay-{int(started)}",
        seat="in_loop_query",
        detector_name="owlv2-b16-int8",
        scene_id="city_block",
    )

    store = OnlineMapStore(store_path)
    the_map = OnlineSemanticMap(store, provenance=provenance)

    observed = 0
    persisted = 0
    refused_volatile = 0
    for frame in frames:
        the_map.note_frame(frame.queries)
        the_map.note_pose(frame.robot_x, frame.robot_y)
        for observation in observations_from_frame(
            frame, visit_id="replay-visit-1", provenance=provenance
        ):
            outcome = the_map.observe(observation)
            observed += 1
            persisted += int(outcome.persisted)
            refused_volatile += int(
                outcome.persisted is False and outcome.hygiene.note == "volatile_class_refused"
            )
    written = the_map.persist()
    store.close()

    # ---- the query table, with distances and null controls ----------------
    store2 = OnlineMapStore(store_path)
    reloaded = OnlineSemanticMap(store2, provenance=provenance)
    for frame in frames:  # the pose history is not persisted; re-walk it
        reloaded.note_frame(frame.queries)
        reloaded.note_pose(frame.robot_x, frame.robot_y)

    rows = []
    corpus_hits = 0
    for entry in reloaded.entries():
        result = reloaded.resolve(entry.label, robot_xy=(frames[-1].robot_x,
                                                         frames[-1].robot_y))
        best = result.best
        candidates = []
        for key, spec in truth.items():
            if spec.get("label") == entry.label and spec.get("measure") == "surface":
                candidates.append(
                    (surface_distance(entry.surface_x, entry.surface_y,
                                      spec.get("parts", [])), key)
                )
        candidates.sort()
        distance, matched = candidates[0] if candidates else (None, None)
        within = distance is not None and distance <= TOLERANCE_M
        corpus_hits += int(within)
        nav, nav_source = reloaded.navigability(entry)
        rows.append(
            {
                "query": entry.label,
                "entry_id": entry.entry_id,
                "map_xy": [round(entry.surface_x, 4), round(entry.surface_y, 4)],
                "truth_part": matched,
                "surface_distance_m": (round(distance, 4) if distance is not None
                                       else None),
                "all_truth_distances_m": {
                    key: round(value, 4) for value, key in candidates
                },
                "metric_extent_wh_m": [round(entry.extent_w_m, 3),
                                       round(entry.extent_h_m, 3)],
                "within_tolerance": within,
                "evidence_frames": entry.evidence_frames,
                "visits": entry.visits,
                "peak_score": round(entry.peak_score, 4),
                "hygiene_note": entry.hygiene_note,
                "navigability": round(nav, 3),
                "navigability_source": nav_source,
                "pg3_admitted": bool(result.admitted),
                "pg3_reason": result.verdict.reason,
                "pg3_ranking_margin": round(
                    float(result.verdict.signals.get("ranking_margin", 0.0)), 4
                ),
                "ranking_background_degenerate": result.diagnostics[
                    "ranking_background_degenerate"
                ],
                "candidates": len(result.candidates),
                "best_is_this_entry": bool(best and best.entry_id == entry.entry_id),
            }
        )

    nulls = []
    null_admitted = 0
    null_candidates = 0
    for query in NULL_CONTROLS:
        result = reloaded.resolve(query)
        null_admitted += int(result.admitted)
        null_candidates += len(result.candidates)
        nulls.append(
            {
                "query": query,
                "candidates": len(result.candidates),
                "admitted": bool(result.admitted),
                "reason": result.verdict.reason,
                "asked": result.diagnostics["asked"],
            }
        )
    store2.close()

    # ---- ARM B: the map path alone, with truth-derived detections ---------
    #
    # NOT A PERCEPTION CLAIM. Arm A above measures detector + localizer + map
    # together and, on this stream, the detector is the term that fails. Arm B
    # removes the detector from the loop by synthesizing detections AT the
    # surfaces `scene_truth.json` says exist, so that "the map mislocated it"
    # and "the detector saw something else" stop being confounded. Every number
    # in this arm is a statement about fusion, retrieval, hygiene and
    # persistence — and about nothing that was seen.
    arm_b = _run_truth_derived_arm(truth, scratch)

    owner = REPO / "parcel_memory.sqlite3"
    owner_sha = (
        hashlib.sha256(owner.read_bytes()).hexdigest()[:16] if owner.exists() else None
    )

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "C-1 rerun_live_20260821T235718Z on_frames.json (verbatim)",
        "source_summary_sha256": payload["source_summary_sha256"],
        "scene_sha256_pin": json.loads(SCENE_TRUTH.read_text())["scene"],
        "frames": len(frames),
        "freshness": map_freshness_report(frames),
        "observations": observed,
        "persisted": persisted,
        "refused_volatile": refused_volatile,
        "map_stats_after_reload": reloaded.stats(),
        "arm_b_map_path_only": arm_b,
        "entries_written": written,
        "store_path": str(store_path),
        "reload_entry_count": len(reloaded),
        "tolerance_m": TOLERANCE_M,
        "query_table": rows,
        "corpus_within_tolerance": corpus_hits,
        "null_controls": nulls,
        "null_controls_admitted": null_admitted,
        "null_controls_candidates": null_candidates,
        "owner_store_sha16": owner_sha,
        "elapsed_s": round(time.time() - started, 3),
    }
    out = Path(__file__).parent / "c2_replay_summary.json"
    out.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=1, sort_keys=True))
    print(f"\nwrote {out}")

    # ---- the harness's own falsifiability check ---------------------------
    #
    # A retrieval result with no null control is a claim its author declined to
    # falsify, so this harness refuses to report a success it cannot falsify.
    # Seed 7 empties NULL_CONTROLS and this is what goes red.
    failures = []
    if len(NULL_CONTROLS) < 5:
        failures.append(
            f"live-proof scoring needs >=5 null controls, got {len(NULL_CONTROLS)}"
        )
    if null_admitted != 0:
        failures.append(f"{null_admitted} null control(s) were ADMITTED")
    if null_candidates != 0:
        failures.append(f"null controls produced {null_candidates} candidate(s)")
    if arm_b["null_controls_admitted"] != 0:
        failures.append("arm B admitted a null control")
    if failures:
        for line in failures:
            print(f"SELF-CHECK FAILED: {line}", file=sys.stderr)
        return 1
    print("\nself-check OK: "
          f"{len(NULL_CONTROLS)} null controls, 0 admitted, 0 candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
