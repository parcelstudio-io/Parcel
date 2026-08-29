"""FL-1 orchestration -> results.json.

    ~/.cache/parcel-0e/venv/bin/python run.py --all --seed 20260828
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np
import owners as O
import samples
import torch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", default=None, help="a|b|c|d|e (comma separated)")
    ap.add_argument("--seed", type=int, default=O.SEED_BASE)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    which = list("abcde") if (args.all or not args.only) else args.only.split(",")

    t0 = time.time()
    out: dict = {
        "experiment": "FL-1",
        "seed": args.seed,
        "design": "DESIGN.md + AMENDMENTS.md (pre-run, binding)",
        "amendments_present": (HERE / "AMENDMENTS.md").exists(),
        "evidence_tier": "desktop-sim",
        "owner_source": "synthetic Beta-mixture prior (AMENDMENTS F1); "
                        "humor-signal-1/owner_taste_prior.json ABSENT at run time",
        "hs1_operating_point": O.load_hs1_operating_point(),
        "taste_prior": O.TASTE_PRIOR,
        "detector": O.DETECTOR,
        "threshold": O.THRESH,
        "reward": {"hit": O.R_HIT, "false_chuckle": O.R_FALSE, "silent": O.R_NONE},
        "env": {"python": platform.python_version(), "torch": torch.__version__,
                "numpy": np.__version__,
                "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
    }
    samples.write_samples(HERE / "sample_owners.txt", args.seed)

    if "a" in which:
        import fl1a
        fl1a.run(args.seed, out, quick=args.quick)
        (HERE / "fl1a.json").write_text(json.dumps(out["fl1a"], indent=1))
    if "b" in which:
        import fl1b
        fl1b.run(args.seed, out, quick=args.quick)
        (HERE / "fl1b.json").write_text(json.dumps(out["fl1b"], indent=1))
    if "c" in which:
        import fl1c
        fl1c.run(args.seed, out, quick=args.quick)
        (HERE / "fl1c.json").write_text(json.dumps(out["fl1c"], indent=1))
    if "d" in which:
        import fl1d
        fl1d.run(args.seed, out, quick=args.quick)
        (HERE / "fl1d.json").write_text(json.dumps(out["fl1d"], indent=1))
    if "e" in which:
        import fl1e
        fl1e.run(args.seed, out, quick=args.quick)
        (HERE / "fl1e.json").write_text(json.dumps(out["fl1e"], indent=1))

    # a partial run merges into any existing results.json rather than losing rows
    res_path = HERE / "results.json"
    merged = {}
    if res_path.exists():
        try:
            merged = json.loads(res_path.read_text())
        except Exception:  # noqa: BLE001
            merged = {}
    merged.update(out)
    merged["wall_s"] = round(time.time() - t0, 1)
    res_path.write_text(json.dumps(merged, indent=1))
    print(f"wrote {res_path} ({merged['wall_s']}s)")


if __name__ == "__main__":
    main()
