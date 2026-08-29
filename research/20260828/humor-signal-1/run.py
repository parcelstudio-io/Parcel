#!/usr/bin/env python
"""HS-1 — can the dog tell that a joke was funny? (the reward signal)

Runs the three sub-hypotheses of research/20260828/humor-signal-1/DESIGN.md as
amended by AMENDMENTS.md, and writes every pre-registered number to results.json.

    ~/.cache/parcel-0e/venv/bin/python run.py --all
    ~/.cache/parcel-0e/venv/bin/python run.py --laughter   # HS1a
    ~/.cache/parcel-0e/venv/bin/python run.py --prior      # HS1b
    ~/.cache/parcel-0e/venv/bin/python run.py --taste      # HS1c

No hosted API calls of any kind. Models and corpora are local; set
HF_HOME=~/.cache/parcel-0e/hf and keep the download cache in
~/.cache/parcel-0e/data (see README.md for the exact sources + checksums).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("HF_HOME", os.path.expanduser("~/.cache/parcel-0e/hf"))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "32")
os.environ.setdefault("OMP_NUM_THREADS", "32")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="run every sub-hypothesis")
    ap.add_argument("--laughter", action="store_true", help="HS1a — laughter detection")
    ap.add_argument("--prior", action="store_true", help="HS1b — LM funniness prior")
    ap.add_argument("--taste", action="store_true", help="HS1c — owner-taste variance")
    args = ap.parse_args()
    if not any((args.all, args.laughter, args.prior, args.taste)):
        ap.print_help()
        return 2

    from hs_common import RESULTS_JSON, load_results, merge_results

    t0 = time.time()
    # HS1c first: pure numpy, seconds, and it produces owner_taste_prior.json
    # that HS1b then folds its joke categories into.
    if args.all or args.taste:
        import hs1c_taste
        print("=== HS1c — owner taste is real variance, not noise", flush=True)
        hs1c_taste.run()
    if args.all or args.laughter:
        import hs1a_laughter
        print("=== HS1a — laughter is detectable locally", flush=True)
        hs1a_laughter.run()
    if args.all or args.prior:
        import hs1b_prior
        print("=== HS1b — a funniness prior without the laugh", flush=True)
        hs1b_prior.run()

    merge_results("_run", {
        "completed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wall_seconds": round(time.time() - t0, 1),
        "sections": [a for a in ("hs1a", "hs1b", "hs1c") if a in load_results()],
        "design": "research/20260828/humor-signal-1/DESIGN.md",
        "amendments": "research/20260828/humor-signal-1/AMENDMENTS.md (H1-H7, all applied)",
        "hosted_calls": 0,
        "hosted_cost_usd": 0.0,
    })
    res = load_results()
    print(f"\n=== wrote {RESULTS_JSON} with sections: "
          f"{sorted(k for k in res if not k.startswith('_'))} "
          f"in {time.time() - t0:.0f} s", flush=True)
    print(json.dumps({
        "hs1a_esc50_auroc": res.get("hs1a", {}).get("headline_esc50_family_max", {}).get("auroc"),
        "hs1a_speech_auroc_ci": res.get("hs1a", {}).get("per_slice", {})
            .get("speech_librispeech", {}).get("auroc_ci95"),
        "hs1b_spearman_mean": res.get("hs1b", {}).get("correlations", {})
            .get("mean_of_paraphrases", {}).get("spearman"),
        "hs1c_improvement_over_biases_only": res.get("hs1c", {}).get("heldout_rmse", {})
            .get("improvement_over_biases_only"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
