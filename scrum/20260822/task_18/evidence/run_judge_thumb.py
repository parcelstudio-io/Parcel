"""NM-1 correction pass — the SAME J5/J6 pair, on the 64-px crop the map feeds.

The verifier's catch: §3.1's anti-correlation was measured on 384-px crops, and
the shipping path hands the judge ``entry.thumbnail``, which is 64 px. If the
sign of the inversion depends on the crop, the generalisation has to say so.
"""
from __future__ import annotations

import base64
import json
import os
import statistics
import sys
from pathlib import Path

REPO = Path("/home/jaewoo-jang/Desktop/Projects/Parcel")
OUT = Path("/home/jaewoo-jang/.cache/parcel-nm1/evidence")
sys.path.insert(0, str(REPO / "src"))
os.environ.setdefault("PARCEL_OWLV2_ONNX", "1")

from parcel_robot.vlm_veto.judge import OwlV2NamingJudge

crops_dir = REPO / "tests/data/p1d_crops"
manifest = json.loads((crops_dir / "MANIFEST.json").read_text())
arms = json.loads((OUT / "arms_three.json").read_text())
a1 = {r["id"]: r for r in arms["A1_fullres"]["rows"]}

judge = OwlV2NamingJudge(require_env=True)
assert judge.load()

true_rows, wrong_rows = [], []
for row in manifest["crops"]:
    thumb = base64.b64decode(row["thumbnail_b64"])
    t = judge.judge(row["label"], thumb, entry_id=row["id"])
    true_rows.append({"id": row["id"], "label": row["label"],
                      "outcome": t.outcome, "strength": t.strength})
    vlm = a1.get(row["id"], {})
    proposal = vlm.get("normalized") or ""
    if proposal and not vlm.get("correct"):
        w = judge.judge(proposal, thumb, entry_id=row["id"])
        wrong_rows.append({"id": row["id"], "label": row["label"],
                           "vlm_name": proposal, "outcome": w.outcome,
                           "strength": w.strength})

by_id = {r["id"]: r for r in true_rows}
pairs = [(by_id[w["id"]]["strength"], w["strength"]) for w in wrong_rows]
beats = sum(1 for t, w in pairs if w > t)
result = {
    "crop": "thumbnail64 (the crop the map stores and the shipping path feeds)",
    "true_recall": round(sum(r["outcome"] == "accept" for r in true_rows) / len(true_rows), 4),
    "wrong_accept": round(
        sum(r["outcome"] == "accept" for r in wrong_rows) / len(wrong_rows), 4
    ),
    "paired_n": len(pairs),
    "wrong_beats_true": beats,
    "median_true_paired": round(statistics.median(t for t, _ in pairs), 4),
    "median_wrong_paired": round(statistics.median(w for _, w in pairs), 4),
    "true_rows": true_rows,
    "wrong_rows": wrong_rows,
}
print(json.dumps({k: v for k, v in result.items() if not k.endswith("rows")}, indent=1))
(OUT / "judge_thumbnail64.json").write_text(json.dumps(result, indent=1))
print("wrote judge_thumbnail64.json")
