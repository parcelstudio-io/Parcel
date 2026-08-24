"""H6 corpus A — rebuild the real-photo person set the 2026-08-21 bench used.

The bench's own 156 real photos lived in a session scratchpad that no longer
exists (``scrum/20260821/perception/bench_detectors.md`` points at
``/tmp/claude-1000/.../799cb356-.../bench-owl/frames/``; that path is gone).
This rebuilds an EQUIVALENT set from the same public source the bench's "COCO
control" came from: COCO val2017, streamed through the HuggingFace
datasets-server (``rafaelpadilla/coco2017``) because ``images.cocodataset.org``
is not reachable from this host.

Selection is pre-declared and unturned:
  * rows are taken in dataset order from offset 0 — no cherry-picking;
  * an image is kept when it holds >= 1 non-crowd ``person`` instance;
  * every non-crowd person instance in a kept image is ground truth, with NO
    area filter (a small person is still a person; filtering by size is how a
    recall number gets flattered);
  * ``iscrowd`` person regions are recorded separately and are IGNORE regions:
    a prediction that lands on one is neither a hit nor a false positive.
Collection stops at 156 KEPT IMAGES. The bench reports "real photos (n=156)"
without saying whether n counts photos or person instances, so the corpus is
sized to 156 photos and BOTH readings are reported: per-instance micro recall
over every non-crowd person instance, and per-image recall (a photo counts as
recalled when >= 1 of its person instances is matched).
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DATASET = "rafaelpadilla/coco2017"
CONFIG = "default"
SPLIT = "val"
ROWS_URL = "https://datasets-server.huggingface.co/rows"
PERSON_LABEL = 1  # ClassLabel index for "person" in this dataset's names list
#: The dataset's ClassLabel names come back in every /rows response's feature
#: block; every object (not only persons) is stored so the noticing rows have
#: multi-label ground truth.
TARGET_IMAGES = 156
PAGE = 100


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.load(response)


def _page(offset: int, length: int) -> tuple[list[dict], list[str]]:
    query = urllib.parse.urlencode(
        {"dataset": DATASET, "config": CONFIG, "split": SPLIT,
         "offset": offset, "length": length}
    )
    payload = _get_json(f"{ROWS_URL}?{query}")
    names: list[str] = []
    for feature in payload.get("features", []):
        if feature["name"] == "objects":
            names = list(feature["type"]["label"]["feature"]["names"])
    return payload.get("rows", []), names


def main(out_dir: str) -> int:
    out = Path(out_dir)
    images_dir = out / "photos"
    images_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    records: list[dict] = []
    persons = 0
    offset = 0
    while len(records) < TARGET_IMAGES and offset < 5000:
        rows, page_names = _page(offset, PAGE)
        names = page_names or names
        for row in rows:
            payload = row["row"]
            objects = payload["objects"]
            labels = objects["label"]
            boxes = objects["bbox"]
            crowds = objects["iscrowd"]
            gt = [
                [float(b[0]), float(b[1]), float(b[0]) + float(b[2]), float(b[1]) + float(b[3])]
                for b, lab, crowd in zip(boxes, labels, crowds, strict=True)
                if int(lab) == PERSON_LABEL and not bool(crowd)
            ]
            ignore = [
                [float(b[0]), float(b[1]), float(b[0]) + float(b[2]), float(b[1]) + float(b[3])]
                for b, lab, crowd in zip(boxes, labels, crowds, strict=True)
                if int(lab) == PERSON_LABEL and bool(crowd)
            ]
            if not gt:
                continue
            image_id = int(payload["image_id"])
            path = images_dir / f"{image_id:012d}.jpg"
            if not path.is_file():
                with urllib.request.urlopen(payload["image"]["src"], timeout=120) as src:
                    path.write_bytes(src.read())
            records.append(
                {
                    "image_id": image_id,
                    "file": path.name,
                    "width": int(payload["image"]["width"]),
                    "height": int(payload["image"]["height"]),
                    "persons": gt,
                    "ignore": ignore,
                    "objects": [
                        {
                            "label": names[int(lab)],
                            "box": [
                                float(b[0]), float(b[1]),
                                float(b[0]) + float(b[2]), float(b[1]) + float(b[3]),
                            ],
                            "iscrowd": bool(crowd),
                        }
                        for b, lab, crowd in zip(boxes, labels, crowds, strict=True)
                    ],
                }
            )
            persons += len(gt)
            if len(records) >= TARGET_IMAGES:
                break
        offset += PAGE
        print(f"offset={offset} images={len(records)} person_instances={persons}", flush=True)
    manifest = {
        "source": f"{DATASET}:{CONFIG}:{SPLIT} via datasets-server (COCO val2017)",
        "selection": "dataset order from offset 0; keep images with >=1 non-crowd person",
        "images": len(records),
        "person_instances": persons,
        "ignore_regions": sum(len(r["ignore"]) for r in records),
        "object_instances": sum(len(r["objects"]) for r in records),
        "label_names": names,
        "records": records,
    }
    (out / "photos_gt.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps({k: v for k, v in manifest.items() if k != "records"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
