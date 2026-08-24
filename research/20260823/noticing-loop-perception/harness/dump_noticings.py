"""H6 P4 — write every noticing out as a picture so it can be hand-checked.

The criterion is "<= 1 FALSE noticing per minute", and "false" is an automated
verdict (no ground-truth match, or a repeat of an instance already noticed).
Automated verdicts on open-vocabulary detections are exactly the kind of number
that deserves a human look: COCO does not label everything in a photograph, so
a "hallucination" may be a real object the annotation is silent about. This
writes a contact sheet of the noticed crops, labelled with the verdict, so the
RESULTS row can say which they were instead of assuming.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from analyze import annotate

from parcel_robot.camera_channel.backends.recorded import read_clip

TILE = 180


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H6 noticing contact sheet")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--columns", type=int, default=6)
    args = parser.parse_args(argv)

    corpus = Path(args.corpus)
    run = json.loads(Path(args.run).read_text())
    gt_doc = json.loads((corpus / "clips" / "clips_gt.json").read_text())
    _, color, _ = read_clip(corpus / "clips" / run["clip"])
    annotated = annotate(run, gt_doc)

    seen: set[tuple] = set()
    noticed_instances: set[tuple] = set()
    tiles: list[tuple[np.ndarray, str, str]] = []
    for row in annotated:
        key = row["instance"]
        if key is not None:
            seen.add(key)
        if not row["noticed"]:
            continue
        if key is None:
            verdict = "IGNORED" if row["ignored"] else "FALSE:no-gt-match"
        elif key in noticed_instances:
            verdict = "FALSE:repeat"
        else:
            verdict = "TRUE"
            noticed_instances.add(key)
        u0, v0, u1, v1 = (int(v) for v in row["box"])
        crop = np.ascontiguousarray(color[row["gt_frame"]][v0:v1, u0:u1])
        if crop.size == 0:
            continue
        tiles.append((crop, f"{row['label']} {row['score']:.2f} nov={row['novelty']:.2f}", verdict))

    if not tiles:
        print(json.dumps({"noticings": 0}))
        return 0
    columns = min(args.columns, len(tiles))
    rows = (len(tiles) + columns - 1) // columns
    sheet = np.full((rows * (TILE + 34), columns * TILE, 3), 30, dtype=np.uint8)
    for index, (crop, caption, verdict) in enumerate(tiles):
        row_index, column_index = divmod(index, columns)
        resized = cv2.resize(crop[:, :, ::-1], (TILE, TILE), interpolation=cv2.INTER_AREA)
        y = row_index * (TILE + 34)
        x = column_index * TILE
        sheet[y : y + TILE, x : x + TILE] = resized
        colour = (90, 220, 90) if verdict == "TRUE" else (90, 90, 240)
        cv2.putText(sheet, caption, (x + 3, y + TILE + 13), cv2.FONT_HERSHEY_SIMPLEX,
                    0.36, (220, 220, 220), 1, cv2.LINE_AA)
        cv2.putText(sheet, verdict, (x + 3, y + TILE + 28), cv2.FONT_HERSHEY_SIMPLEX,
                    0.38, colour, 1, cv2.LINE_AA)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, sheet)
    print(json.dumps({
        "noticings": len(tiles),
        "true": sum(1 for _, _, v in tiles if v == "TRUE"),
        "false": sum(1 for _, _, v in tiles if v.startswith("FALSE")),
        "sheet": args.out,
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
