#!/usr/bin/env python
"""DS-1 H-DS1b (AMENDMENTS.md D2) — parameter delta of the act stream BOTH ways,
computed from the ACTUAL patched implementation, on the `meta` device.

"Shared slice"  = the act depformer step reuses an existing per-step weight slot
                  via `depformer_weights_per_step_schedule` (the config flag).
"Per-step slice" = the act step gets its own slot (no schedule), which clones a
                  whole 6-layer depformer weight set.

Stream order: the act stream is the LAST GENERATED stream (depformer step 8),
as amended. The act-FIRST order is also reported because it is markedly cheaper
and the difference is a design finding, not a rounding error.

    PYTHONPATH=~/.cache/parcel-0e/ds1/moshi-act/moshi \
      ~/.cache/parcel-0e/venv-moshi/bin/python act_param_delta.py
"""

from __future__ import annotations

import json
from pathlib import Path

import torch
from moshi.models.lm import LMModel
from moshi.models.loaders import _lm_kwargs

HERE = Path(__file__).resolve().parent
ACT_CARDS = (90, 54, 68)
STOCK_DELAYS = list(_lm_kwargs["delays"])


def build(**over) -> LMModel:
    kw = dict(_lm_kwargs)
    kw.update(over)
    return LMModel(device="meta", dtype=torch.bfloat16, **kw)


def n(m) -> int:
    return sum(p.numel() for p in m.parameters())


def cfg(act_card: int, act_index: int, shared: bool) -> dict:
    delays = STOCK_DELAYS[: 1 + act_index] + [0] + STOCK_DELAYS[1 + act_index:]
    out = {
        "n_q": 17, "dep_q": 9, "act_card": act_card, "act_index": act_index,
        "delays": delays,
    }
    if shared:
        sched = list(range(8))
        sched.insert(act_index, act_index if act_index < 8 else 7)
        out["depformer_weights_per_step_schedule"] = sched[:9]
    return out


def main() -> int:
    base = build()
    p0 = n(base)
    rows = []
    for act_card in ACT_CARDS:
        for act_index, order in ((8, "act_last (amended)"), (0, "act_first")):
            for shared, slice_name in ((True, "shared_slice"), (False, "per_step_slice")):
                c = cfg(act_card, act_index, shared)
                m = build(**c)
                p1 = n(m)
                rows.append({
                    "act_card": act_card,
                    "stream_order": order,
                    "act_depformer_index": act_index,
                    "depformer_slice": slice_name,
                    "config_flag": (
                        "depformer_weights_per_step_schedule="
                        + str(c.get("depformer_weights_per_step_schedule"))
                        if shared else
                        "depformer_weights_per_step=True, no schedule (mult=dep_q=9)"
                    ),
                    "baseline_params": p0,
                    "variant_params": p1,
                    "delta_params": p1 - p0,
                    "delta_millions": round((p1 - p0) / 1e6, 4),
                    "bar_le_1M": bool((p1 - p0) <= 1_000_000),
                })
                del m
    out = {
        "hypothesis": "H-DS1b (AMENDMENTS.md D2)",
        "moshi_git_rev": "e6a55d2722a65870ef52a6c9f6ecfc0e90f38362",
        "baseline_params": p0,
        "note": (
            "act_last needs a NEW 2049-row depformer_emb (to embed audio "
            "codebook 7, which becomes an input once a 9th step exists); "
            "act_first needs only a 91-row one. That single table is the whole "
            "difference between the two orders."
        ),
        "rows": rows,
    }
    Path(HERE / "act_param_delta.json").write_text(json.dumps(out, indent=2))
    print(f"baseline {p0:,}\n")
    hdr = f"{'act_card':>8} {'order':>20} {'slice':>16} {'delta':>14} {'M':>10} {'<=1M':>6}"
    print(hdr); print("-" * len(hdr))
    for r in rows:
        print(f"{r['act_card']:>8} {r['stream_order']:>20} {r['depformer_slice']:>16} "
              f"{r['delta_params']:>14,} {r['delta_millions']:>10.4f} {r['bar_le_1M']!s:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
