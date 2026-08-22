"""NM-1 work item 1 — three arms on the SAME 40 crops (pre-registration §1).

Runs in the NM-1 bench venv (torch 2.13+cu129, transformers 5.15.1) against the
repo's own ``parcel_robot.vlm_veto`` wrappers — not a re-implementation — so the
arms measure the shipping seat. Weights are FOUND in the 2026-08-21 research
cache; nothing is downloaded.
"""
from __future__ import annotations

import base64
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path("/home/jaewoo-jang/Desktop/Projects/Parcel")
OUT = Path("/home/jaewoo-jang/.cache/parcel-nm1/evidence")
WEIGHTS_CACHE = (
    "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/"
    "799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/cutover-research/bench-vlm/hf/hub"
)
sys.path.insert(0, str(REPO / "src"))

from parcel_robot.online_map.naming import normalize_proposal
from parcel_robot.vlm_veto import (
    NAME_PROMPT,
    NAME_PROMPT_CLASS_ANCHORED,
    Qwen3VLVerifier,
    resolve_weights,
)

# P1-D's frozen synonym table, verbatim from
# /home/jaewoo-jang/.cache/parcel-p1d/scratch/run_vlm.py.
SYNONYMS = {
    "person": ["person", "man", "woman", "pedestrian", "people", "boy", "girl",
               "guy", "human", "cyclist", "rider"],
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


def norm(text: str) -> str:
    return " ".join(
        "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower()).split()
    )


def name_correct(answer: str, label: str) -> bool:
    """Verbatim from bench-vlm/code/common.py::name_correct."""
    a = norm(answer)
    if not a:
        return False
    for syn in SYNONYMS.get(label, [label]):
        s = norm(syn)
        if s and (s in a or a in s):
            return True
    return False


def main() -> int:
    crops_dir = REPO / "tests/data/p1d_crops"
    manifest = json.loads((crops_dir / "MANIFEST.json").read_text())
    rows = manifest["crops"]
    assert len(rows) == 40, len(rows)

    weights = resolve_weights(caches=[WEIGHTS_CACHE])
    print("weights:", weights, flush=True)
    seat = Qwen3VLVerifier(weights=weights)
    seat.load()
    # Two throwaway answers, the runner's own warm-up shape.
    from parcel_robot.vlm_veto.verifier import warm_up_png
    for _ in range(2):
        seat.describe(warm_up_png())

    arms = {
        "A1_fullres": {"source": "png", "prompt": None},
        "A2_thumb64": {"source": "thumb", "prompt": None},
        "A3_prompt": {"source": "png", "prompt": NAME_PROMPT_CLASS_ANCHORED},
    }
    results: dict[str, dict] = {}
    for arm, spec in arms.items():
        out_rows = []
        lat = []
        t0 = time.time()
        for row in rows:
            if spec["source"] == "png":
                crop = (crops_dir / row["file"]).read_bytes()
            else:
                crop = base64.b64decode(row["thumbnail_b64"])
            ans = seat.describe(crop, prompt=spec["prompt"])
            raw = ans.text
            normed = normalize_proposal(raw)
            ok = name_correct(normed or raw, row["label"])
            lat.append(ans.latency_ms)
            out_rows.append(
                {
                    "id": row["id"],
                    "label": row["label"],
                    "object_key": row["object_key"],
                    "raw": raw,
                    "normalized": normed,
                    "correct": bool(ok),
                    "ms": round(ans.latency_ms, 2),
                }
            )
        correct = sum(r["correct"] for r in out_rows)
        per_class: dict[str, list[int]] = {}
        for r in out_rows:
            per_class.setdefault(r["label"], [0, 0])
            per_class[r["label"]][1] += 1
            per_class[r["label"]][0] += int(r["correct"])
        results[arm] = {
            "prompt": spec["prompt"] or NAME_PROMPT,
            "source": spec["source"],
            "n": len(out_rows),
            "correct": correct,
            "accuracy": round(correct / len(out_rows), 4),
            "p50_ms": round(statistics.median(lat), 2),
            "p95_ms": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 2),
            "wall_s": round(time.time() - t0, 1),
            "per_class": {k: f"{v[0]}/{v[1]}" for k, v in sorted(per_class.items())},
            "rows": out_rows,
        }
        print(arm, correct, "/", len(out_rows), results[arm]["per_class"], flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "arms_three.json").write_text(json.dumps(results, indent=1))
    print("wrote", OUT / "arms_three.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
