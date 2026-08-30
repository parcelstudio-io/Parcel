"""MB-2 — the read-only bridge to MB-1's frozen instrument.

MB-1's corpus, scorer, trigger table and steering policy are IMPORTED BY PATH
and never modified.  Everything MB-2 measures is measured on that instrument
unchanged, so an MB-2 row and an MB-1 row are comparable by construction.
"""

from __future__ import annotations

import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
REPO_ROOT = FOLDER.parents[2]
MB1 = REPO_ROOT / "research/20260829/model-b-narration-1"

if not MB1.is_dir():  # pragma: no cover - a wiring error, not a result
    raise RuntimeError(f"MB-1's folder is missing: {MB1}")

for _extra in (str(MB1), str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import events as ev
import narrate as nr
import scorer as sc
import steer as st

MB1_RESULTS = MB1 / "results.json"
MB1_ADJUDICATION_PROMPT = MB1 / "adjudication_prompt.txt"

#: The band values MB-1 published, read from the wave realtime.yaml when it is
#: reachable and asserted against these constants otherwise.
BANDS = {"max_updates_per_minute": 2, "min_gap_s": 15.0}

#: MB-1's own "a receipt this close behind an owner turn belongs to that turn".
IMMEDIATE_RECEIPT_S = 0.6

__all__ = [
    "BANDS",
    "IMMEDIATE_RECEIPT_S",
    "MB1",
    "MB1_ADJUDICATION_PROMPT",
    "MB1_RESULTS",
    "ev",
    "nr",
    "sc",
    "st",
]
