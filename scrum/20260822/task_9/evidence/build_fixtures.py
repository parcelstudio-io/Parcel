"""P1-D: freeze F-NAME (40 entries) and F-VETO from the textured crop pool.

Selection is deterministic and stated before it runs: orbit poses only (one
consistent viewing protocol), sorted by crop id, up to 4 per class, 10 classes,
40 entries. Nothing is picked after seeing a model output.

F-VETO reuses the same 40 crops twice: once asked about the TRUE class (the
veto must NOT fire) and once about a DECOY class from the same scene (the veto
MUST fire). The decoy is the next class in a fixed rotation, so it is not chosen
per-crop either.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

EV = Path("/home/jaewoo-jang/.cache/parcel-p1d/evidence")
POOL = EV / "scene_crops/meta.json"
PER_CLASS = 4

CLASSES = [
    "bench",
    "bicycle",
    "bollard",
    "building",
    "crate",
    "door",
    "lamppost",
    "planter",
    "traffic light",
    "tree",
]


def main() -> None:
    pool = json.loads(POOL.read_text())
    orbit = [row for row in pool if row["frame"].startswith("orbit")]
    name_rows = []
    for label in CLASSES:
        rows = sorted(
            (r for r in orbit if r["label"] == label), key=lambda r: r["id"]
        )
        name_rows.extend(rows[:PER_CLASS])
    assert len(name_rows) == 40, len(name_rows)

    veto_rows = []
    for index, row in enumerate(name_rows):
        decoy = CLASSES[(CLASSES.index(row["label"]) + 1 + index % 3) % len(CLASSES)]
        if decoy == row["label"]:
            decoy = CLASSES[(CLASSES.index(row["label"]) + 1) % len(CLASSES)]
        veto_rows.append(
            {"id": row["id"], "path": row["path"], "label": row["label"], "ask": row["label"], "expect": "present"}
        )
        veto_rows.append(
            {"id": row["id"], "path": row["path"], "label": row["label"], "ask": decoy, "expect": "absent"}
        )

    (EV / "F_NAME.json").write_text(json.dumps(name_rows, indent=1))
    (EV / "F_VETO.json").write_text(json.dumps(veto_rows, indent=1))
    digest = hashlib.sha256(
        json.dumps([r["sha256"] for r in name_rows]).encode()
    ).hexdigest()
    import collections

    print("F_NAME", len(name_rows), dict(collections.Counter(r["label"] for r in name_rows)))
    print("F_VETO", len(veto_rows), dict(collections.Counter(r["expect"] for r in veto_rows)))
    print("F_NAME_SHA256", digest)


if __name__ == "__main__":
    main()
