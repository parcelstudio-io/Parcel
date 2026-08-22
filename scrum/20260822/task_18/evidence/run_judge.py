"""NM-1 rows J1-J7 and F — the correctness judge, on the real OWLv2 seat.

Runs in ``.parcel`` (onnxruntime-gpu + cv2 + numpy). The VLM does NOT run here:
P1-D's full-resolution arm is REPLAYED from its committed per-visit answers
(``row5_kgate_fullres.json``), so the arm this card must beat is the exact one
it measured, name for name, and the only live model in the loop is the judge.
"""
from __future__ import annotations

import collections
import json
import os
import statistics
import sys
from pathlib import Path

REPO = Path("/home/jaewoo-jang/Desktop/Projects/Parcel")
P1D = Path("/home/jaewoo-jang/.cache/parcel-p1d/evidence")
OUT = Path("/home/jaewoo-jang/.cache/parcel-nm1/evidence")
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("PARCEL_OWLV2_ONNX", "1")

import cv2
import numpy as np

from parcel_robot.camera_channel.ingress import _encode_thumbnail
from parcel_robot.online_map import (
    EmbeddingStamp,
    MapObservation,
    OnlineSemanticMap,
    WriterProvenance,
)
from parcel_robot.online_map.naming import run_naming_pass
from parcel_robot.vlm_veto.judge import (
    JUDGE_MIN_SCORE,
    OwlV2NamingJudge,
)

SYNONYMS = {
    "bench": ["bench", "seat"],
    "tree": ["tree", "bush", "plant", "foliage"],
    "building": ["building", "house", "wall", "facade", "structure"],
    "door": ["door", "doorway", "entrance", "gate"],
    "planter": ["planter", "pot", "flower pot", "plant", "flowerpot", "vase"],
    "lamppost": ["lamp", "lamppost", "streetlight", "street light",
                 "light pole", "pole"],
    "traffic light": ["traffic light", "signal", "stoplight", "traffic signal"],
    "crate": ["crate", "box", "cube"],
    "bollard": ["bollard", "post", "pole", "pillar"],
    "bicycle": ["bicycle", "bike", "cycle"],
}
EXTENTS = {
    "bench": (1.6, 0.9), "bicycle": (1.6, 1.0), "bollard": (0.25, 0.9),
    "building": (8.0, 6.0), "crate": (0.8, 0.8), "door": (1.0, 2.1),
    "lamppost": (0.3, 3.2), "planter": (0.9, 0.8),
    "traffic light": (0.3, 1.0), "tree": (1.6, 3.5),
}
STAMP = EmbeddingStamp(model_id="p1d-placeholder", revision="1", dim=4, preprocessing="none")


def norm(text: str) -> str:
    return " ".join(
        "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower()).split()
    )


def name_correct(answer: str, label: str) -> bool:
    a = norm(answer)
    if not a:
        return False
    for syn in SYNONYMS.get(label, [label]):
        s = norm(syn)
        if s and (s in a or a in s):
            return True
    return False


def png_from_npy(path: str) -> bytes:
    arr = np.load(path)
    ok, buf = cv2.imencode(".png", arr[:, :, ::-1])
    assert ok, path
    return buf.tobytes()


def build_map(objects, views_by_key):
    provenance = WriterProvenance(
        session_id="nm1-row5", seat="qwen3-vl-2b", detector_name="scene_gt",
        scene_id="city_block",
    )
    smap = OnlineSemanticMap(provenance=provenance)
    entry_of = {}
    for index, key in enumerate(sorted(objects)):
        label = objects[key]
        for visit in range(3):
            smap.observe(
                MapObservation(
                    label=label, score=0.8,
                    surface_x=float(10 * index), surface_y=0.0, surface_z=0.4,
                    range_m=3.0, bearing_rad=0.0, depth_m=3.0,
                    extent_w_m=EXTENTS[label][0], extent_h_m=EXTENTS[label][1],
                    inlier_pixels=5000, frame_id=f"f{index}-{visit}",
                    visit_id=f"visit-{visit}", observed_wall_s=1000.0 + visit,
                    robot_x=0.0, robot_y=0.0, provenance=provenance,
                    thumbnail=views_by_key[key][visit]["thumb"],
                    relief_m=0.2, relief_samples=40,
                    embedding=(0.1, 0.2, 0.3, 0.4), embedding_stamp=STAMP,
                )
            )
    for entry in smap.active_entries():
        for index, key in enumerate(sorted(objects)):
            if abs(entry.surface_x - 10 * index) < 0.5:
                entry_of[entry.entry_id] = key
    return smap, entry_of


def replay_arm(objects, views_by_key, recorded, judge, thumb_kind):
    """P1-D's fullres arm, replayed name-for-name, optionally judged.

    ``recorded`` is ``{object_key: [answer per visit]}`` taken verbatim from
    P1-D's ``row4_naming.json`` for the same three views the k-gate arm used.
    Entry ids are not reproducible across runs, so the replay is keyed on the
    OBJECT, which is.
    """
    smap, entry_of = build_map(objects, views_by_key)
    reports = []
    for visit in range(3):
        for entry in smap.active_entries():
            key = entry_of.get(entry.entry_id)
            if key:
                entry.thumbnail = views_by_key[key][visit][thumb_kind]
        by_id = {
            e.entry_id: recorded.get(entry_of.get(e.entry_id, ""), ["", "", ""])[visit]
            for e in smap.active_entries()
        }
        thumb_to_answer = {
            id(e.thumbnail): by_id[e.entry_id] for e in smap.active_entries()
        }

        def describe(_thumb, _table=thumb_to_answer):
            return type("A", (), {"text": _table.get(id(_thumb), "")})()

        reports.append(
            run_naming_pass(
                smap, describe, visit_id=f"visit-{visit}", budget_s=0.0, judge=judge
            )
        )
    rows, false_promotions, blocked_correct = [], 0, 0
    for entry in smap.active_entries():
        key = entry_of.get(entry.entry_id)
        if not key:
            continue
        for name in entry.names:
            if name.provenance == "detector_label":
                continue
            ok = name_correct(name.text, objects[key])
            rows.append({
                "object": key, "true_label": objects[key], "name": name.text,
                "provenance": name.provenance, "visits": name.visits,
                "admissible": name.admissible, "correct": ok,
            })
            if name.admissible and not ok:
                false_promotions += 1
            if not name.admissible and ok and name.visits >= 3:
                blocked_correct += 1
    return {
        "promotions": sum(1 for r in rows if r["admissible"]),
        "false_promotions": false_promotions,
        "correct_names_blocked": blocked_correct,
        "known_places": list(smap.known_places()),
        "rows": rows,
        "per_visit": [r.as_dict() for r in reports],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"floor": JUDGE_MIN_SCORE}

    fname = json.loads((P1D / "F_NAME.json").read_text())
    by_object = collections.defaultdict(list)
    for row in fname:
        by_object[row["object_key"]].append(row)
    objects = {k: v[0]["label"] for k, v in by_object.items() if len(v) >= 3}
    views_by_key = {}
    for key, views in by_object.items():
        if key not in objects:
            continue
        entries = []
        for v in views[:3]:
            arr = np.load(v["path"])
            entries.append({"full": png_from_npy(v["path"]),
                            "thumb": _encode_thumbnail(arr),
                            "id": v["id"]})
        views_by_key[key] = entries
    print("objects:", sorted(objects), flush=True)

    # P1-D's own recorded VLM answers, per object, for the three views the
    # k-gate arm used. Deterministic decoding (do_sample=False), so this is the
    # same arm, name for name, with the model taken out of the loop.
    row4 = {r["id"]: r["raw"] for r in json.loads((P1D / "row4_naming.json").read_text())}
    recorded = {
        key: [row4.get(v["id"], "") for v in by_object[key][:3]] for key in objects
    }
    print("replayed answers:", json.dumps(recorded), flush=True)

    judge = OwlV2NamingJudge(require_env=True)
    assert judge.load(), "OWLv2 judge could not be built"
    print("judge loaded; floor =", judge.floor, flush=True)

    # ---- row F: judge OFF must reproduce P1-D's arm --------------------------
    result["arm_F_judge_off"] = replay_arm(objects, views_by_key, recorded, None, "full")
    print("F  judge OFF:", result["arm_F_judge_off"]["promotions"],
          "promotions,", result["arm_F_judge_off"]["false_promotions"], "false", flush=True)

    # ---- rows J3/J4: judge ON -----------------------------------------------
    result["arm_J_judge_on"] = replay_arm(objects, views_by_key, recorded, judge, "full")
    print("J3 judge ON :", result["arm_J_judge_on"]["promotions"],
          "promotions,", result["arm_J_judge_on"]["false_promotions"], "false,",
          result["arm_J_judge_on"]["correct_names_blocked"], "correct blocked", flush=True)

    # ---- rows J1/J2: the two consistently-wrong names, view by view ----------
    named = {"traffic_light_1": "pole", "bollard_1": "yellow cylinder"}
    j12 = []
    for key, wrong in named.items():
        for i, view in enumerate(views_by_key[key]):
            v = judge.judge(wrong, view["full"], entry_id=key)
            j12.append({"object": key, "view": view["id"], "name": wrong,
                        "outcome": v.outcome, "strength": v.strength})
    result["rows_J1_J2"] = j12
    for r in j12:
        print("J1/J2", r["object"], r["name"], r["outcome"], r["strength"], flush=True)

    # ---- rows J5/J6: the judge's own operating point on the 40 crops ---------
    crops_dir = REPO / "tests/data/p1d_crops"
    manifest = json.loads((crops_dir / "MANIFEST.json").read_text())
    arms = json.loads((OUT / "arms_three.json").read_text())
    a1 = {r["id"]: r for r in arms["A1_fullres"]["rows"]}
    true_rows, wrong_rows, lat = [], [], []
    for row in manifest["crops"]:
        crop = (crops_dir / row["file"]).read_bytes()
        v = judge.judge(row["label"], crop, entry_id=row["id"])
        lat.append(v.latency_ms)
        true_rows.append({"id": row["id"], "label": row["label"],
                          "outcome": v.outcome, "strength": v.strength})
        vlm = a1.get(row["id"], {})
        proposal = vlm.get("normalized") or ""
        if proposal and not vlm.get("correct"):
            w = judge.judge(proposal, crop, entry_id=row["id"])
            lat.append(w.latency_ms)
            wrong_rows.append({"id": row["id"], "label": row["label"],
                               "vlm_name": proposal, "outcome": w.outcome,
                               "strength": w.strength})
    result["row_J5_true_names"] = {
        "n": len(true_rows),
        "accepted": sum(r["outcome"] == "accept" for r in true_rows),
        "recall": round(sum(r["outcome"] == "accept" for r in true_rows) / len(true_rows), 4),
        "per_class": {},
        "rows": true_rows,
    }
    per_class = collections.defaultdict(lambda: [0, 0])
    for r in true_rows:
        per_class[r["label"]][1] += 1
        per_class[r["label"]][0] += r["outcome"] == "accept"
    result["row_J5_true_names"]["per_class"] = {
        k: f"{v[0]}/{v[1]}" for k, v in sorted(per_class.items())
    }
    accepted_wrong = sum(r["outcome"] == "accept" for r in wrong_rows)
    result["row_J6_wrong_names"] = {
        "n": len(wrong_rows),
        "accepted": accepted_wrong,
        "accept_rate": round(accepted_wrong / len(wrong_rows), 4) if wrong_rows else 0.0,
        "rows": wrong_rows,
    }
    result["row_J7_latency"] = {
        "n": len(lat),
        "p50_ms": round(statistics.median(lat), 2),
        "p95_ms": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 2),
    }
    print("J5 recall:", result["row_J5_true_names"]["recall"],
          result["row_J5_true_names"]["per_class"], flush=True)
    print("J6 wrong-name accept:", result["row_J6_wrong_names"]["accept_rate"],
          f"({accepted_wrong}/{len(wrong_rows)})", flush=True)
    print("J7 latency:", result["row_J7_latency"], flush=True)

    # ---- POST-HOC (declared): does ANY floor separate? --------------------
    # Pre-registration §2 fixed the floor at OWLv2's own shipped threshold and
    # said so before the first crop ran. J3 missed. This sweep is added AFTER
    # the fact and is labelled as such: it exists to answer "was the floor the
    # lever, or is the signal itself not separable here?" — not to re-point the
    # row.
    sweep = []
    strengths_true = [r["strength"] for r in true_rows if r["strength"] is not None]
    strengths_wrong = [r["strength"] for r in wrong_rows if r["strength"] is not None]
    for floor in (0.02, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.70, 0.90):
        swept = OwlV2NamingJudge(require_env=True, floor=floor)
        arm = replay_arm(objects, views_by_key, recorded, swept, "full")
        sweep.append({
            "floor": floor,
            "promotions": arm["promotions"],
            "false_promotions": arm["false_promotions"],
            "correct_names_blocked": arm["correct_names_blocked"],
            "true_name_recall": round(
                sum(v >= floor for v in strengths_true) / len(strengths_true), 4
            ),
            "wrong_name_accept": round(
                sum(v >= floor for v in strengths_wrong) / len(strengths_wrong), 4
            ),
        })
        print("SWEEP", sweep[-1], flush=True)
    result["post_hoc_floor_sweep"] = sweep

    # ---- the SHIPPING crop (64 px), same judge ----------------------------
    result["arm_J_thumbnail64"] = replay_arm(
        objects, views_by_key, recorded, judge, "thumb"
    )
    print("shipping 64px arm:", result["arm_J_thumbnail64"]["promotions"],
          "promotions,", result["arm_J_thumbnail64"]["false_promotions"], "false",
          flush=True)

    (OUT / "judge_rows.json").write_text(json.dumps(result, indent=1))
    print("wrote", OUT / "judge_rows.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
