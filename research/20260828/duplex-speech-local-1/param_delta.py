#!/usr/bin/env python
"""DS-1 H-DS1b — exact parameter cost of adding a Parcel act stream to Moshi.

Builds the real `moshi.models.lm.LMModel` on the `meta` device (no memory, no
weights) for the stock moshiko config and for each proposed act-stream variant,
surgically resizes the act-specific modules to the act vocabulary, and diffs
`sum(p.numel())`. Nothing here is hand-arithmetic: the numbers come out of the
released module definitions.

    ~/.cache/parcel-0e/venv-moshi/bin/python param_delta.py --out param_delta.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from moshi.models.lm import LMModel
from moshi.models.loaders import _lm_kwargs
from torch import nn

HERE = Path(__file__).resolve().parent

# Parcel ActTokenCodec vocabulary sizes (src/parcel_robot/duplex/act_codec.py).
ACT_CARD_DESIGN = 90  # DESIGN.md's "~90 tokens" budget
ACT_CARD_BARE = 54  # ActTokenCodec(twist=default_twist_bins()) today
ACT_CARD_LOADED = 68  # ... plus 8 skills + 6 emotes


def build(**overrides) -> LMModel:
    kwargs = dict(_lm_kwargs)
    kwargs.update(overrides)
    return LMModel(device="meta", dtype=torch.bfloat16, **kwargs)


def nparams(m: nn.Module) -> int:
    return sum(p.numel() for p in m.parameters())


def _scaled_emb_like(proto, num_embeddings: int, dim: int):
    """A ScaledEmbedding with the same flags as `proto` but act-sized."""
    from moshi.models.lm_utils import ScaledEmbedding

    return ScaledEmbedding(
        num_embeddings, dim, norm=getattr(proto, "norm", False),
        zero_idx=getattr(proto, "zero_idx", -1), device="meta", dtype=torch.bfloat16,
    )


def variant_dedicated(act_card: int) -> tuple[LMModel, str]:
    """V1: act is a 9th depformer stream with its OWN per-step depformer weights."""
    delays = list(_lm_kwargs["delays"])
    delays = [delays[0], 0] + delays[1:]  # act rides alongside text, delay 0
    m = build(n_q=17, dep_q=9, delays=delays)
    _retarget(m, act_card)
    return m, "act = 9th depformer step with a dedicated per-step weight slot"


def variant_shared(act_card: int) -> tuple[LMModel, str]:
    """V2: act is depformer step 0, REUSING audio codebook 0's per-step weights
    via `depformer_weights_per_step_schedule`."""
    delays = list(_lm_kwargs["delays"])
    delays = [delays[0], 0] + delays[1:]
    m = build(
        n_q=17, dep_q=9, delays=delays,
        depformer_weights_per_step_schedule=[0, 0, 1, 2, 3, 4, 5, 6, 7],
    )
    _retarget(m, act_card)
    return m, "act = depformer step 0 sharing step 0's weights (schedule 0,0,1..7)"


def variant_extra_head(act_card: int) -> tuple[LMModel, str]:
    """V3: act is a parallel head straight off the temporal transformer, using
    Moshi's existing `extra_heads` mechanism. Depformer untouched."""
    delays = list(_lm_kwargs["delays"])
    delays = [delays[0], 0] + delays[1:]
    m = build(
        n_q=17, dep_q=8, delays=delays,
        extra_heads_num_heads=1, extra_heads_dim=act_card,
    )
    # Only the temporal-transformer input embedding is act-sized here.
    m.emb[16] = _scaled_emb_like(m.emb[0], act_card + 1, _lm_kwargs["dim"])
    return m, "act = extra_head off the temporal transformer (no depformer change)"


def _retarget(m: LMModel, act_card: int) -> None:
    """Resize the three act-specific modules from audio cardinality to act."""
    dim = _lm_kwargs["dim"]
    ddim = _lm_kwargs["depformer_dim"]
    # temporal-transformer input embedding for the act stream (last emb slot)
    m.emb[16] = _scaled_emb_like(m.emb[0], act_card + 1, dim)
    # depformer input embedding consumed by step 1 (which sees the act token)
    assert m.depformer_emb is not None
    m.depformer_emb[0] = _scaled_emb_like(m.depformer_emb[0], act_card + 1, ddim)
    # depformer output head for step 0 (emits the act token)
    m.linears[0] = nn.Linear(ddim, act_card, bias=False, device="meta", dtype=torch.bfloat16)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "param_delta.json"))
    args = ap.parse_args()

    base = build()
    p0 = nparams(base)
    rows = []
    for act_card in (ACT_CARD_DESIGN, ACT_CARD_BARE, ACT_CARD_LOADED):
        for name, fn in (
            ("V1_dedicated_depformer_step", variant_dedicated),
            ("V2_shared_depformer_slot", variant_shared),
            ("V3_extra_head", variant_extra_head),
        ):
            m, desc = fn(act_card)
            p1 = nparams(m)
            rows.append({
                "variant": name,
                "description": desc,
                "act_card": act_card,
                "baseline_params": p0,
                "variant_params": p1,
                "delta_params": p1 - p0,
                "delta_millions": round((p1 - p0) / 1e6, 4),
                "bar_le_1M": bool((p1 - p0) <= 1_000_000),
                "pct_of_baseline": round(100.0 * (p1 - p0) / p0, 4),
            })
            del m

    # Per-module attribution for the headline variant (V2 @ 90 tokens).
    v2, _ = variant_shared(ACT_CARD_DESIGN)
    attribution = {
        "emb[16] act input embedding (temporal transformer)": nparams(v2.emb[16]),
        "depformer_emb[0] act token -> depformer": nparams(v2.depformer_emb[0]),
        "linears[0] act output head": nparams(v2.linears[0]),
    }
    attribution["sum"] = sum(attribution.values())

    out = {
        "hypothesis": "H-DS1b",
        "moshi_version": __import__("moshi").__version__,
        "moshi_git_rev": "e6a55d2722a65870ef52a6c9f6ecfc0e90f38362",
        "baseline_config": "moshi.models.loaders._lm_kwargs (moshiko-pytorch-bf16)",
        "baseline_params": p0,
        "baseline_params_billions": round(p0 / 1e9, 4),
        "act_vocab_sizes": {
            "design_budget": ACT_CARD_DESIGN,
            "act_codec_bare_today": ACT_CARD_BARE,
            "act_codec_with_8_skills_6_emotes": ACT_CARD_LOADED,
        },
        "variants": rows,
        "v2_module_attribution_at_90": attribution,
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(json.dumps(out["variants"], indent=2))
    print("\nV2@90 attribution:", json.dumps(attribution, indent=2))
    print(f"baseline params: {p0:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
