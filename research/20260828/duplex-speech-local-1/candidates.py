#!/usr/bin/env python
"""DS-1 H-DS1c (AMENDMENTS.md D4) — open full-duplex candidates as a decision
input: license, languages, parameters, duplex style, and the Orin bandwidth
arithmetic (weights x bytes / memory bandwidth -> steps/s ceiling).

Facts and citations come from research/20260828/literature/notes/duplex-speech-llms.md
(the sibling agent's sweep) and, for Moshi, from THIS experiment's measurement.

    ~/.cache/parcel-0e/venv-moshi/bin/python candidates.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

ORIN_BW_GBS = 204.8  # nvidia.com Jetson AGX Orin 64 GB, 64 GB LPDDR5
ORIN_RAM_GB = 64
MOSHI_FRAME_HZ = 12.5  # required steps/s for a Moshi-style 80 ms frame
# Measured on this host in H-DS1a: the LM step reaches this fraction of the
# pure weight-sweep floor. Used to turn a theoretical ceiling into a realistic one.
ROOFLINE_EFFICIENCY = 0.83

CANDIDATES = [
    {
        "name": "Kyutai Moshi (moshiko-pytorch-bf16)",
        "params_b": 7.688,
        "params_source": "MEASURED in this experiment (results.json lm_params)",
        "weights_license": "CC-BY-4.0 (model card front-matter `license: cc-by-4.0`)",
        "code_license": "MIT (python) / Apache-2.0 (rust)",
        "languages": "English only (model card `language: - en`). NO Korean.",
        "duplex_style": "native full-duplex, 17 parallel token streams at 12.5 Hz",
        "measured_here": True,
        "notes": "the only candidate measured on this host; act stream verified to run",
    },
    {
        "name": "Kyutai Hibiki-1B",
        "params_b": 1.0,
        "params_source": "literature note 1.3 (github.com/kyutai-labs/hibiki)",
        "weights_license": "CC-BY-4.0",
        "code_license": "MIT",
        "languages": "speech translation (fr->en). NOT a dialogue model.",
        "duplex_style": "same Moshi multistream architecture, 8 RVQ/stream, 12.5 Hz",
        "measured_here": False,
        "notes": "MLX-Swift build tested on iPhone 16 Pro — the only phone-class "
                 "evidence for this architecture; proves the budget, not the task",
    },
    {
        "name": "MiniCPM-o 4.5",
        "params_b": 9.0,
        "params_source": "literature note 2.5",
        "weights_license": "Apache-2.0",
        "code_license": "Apache-2.0",
        "languages": "Qwen3-8B backbone (multilingual; Korean coverage NOT verified "
                     "by any source fetched here)",
        "duplex_style": "full-duplex by time-division multiplexing (ms-scale slices)",
        "measured_here": False,
        "notes": "19 GB bf16 / 11 GB int4; 154 tok/s bf16, 212 int4 (desktop GPU); "
                 "LLaMA-Factory / SWIFT fine-tuning; ingests live video + audio",
    },
    {
        "name": "Qwen2.5-Omni-7B",
        "params_b": 7.0,
        "params_source": "literature note 2.4",
        "weights_license": "Apache-2.0",
        "code_license": "Apache-2.0",
        "languages": "multilingual (Korean coverage NOT verified by any source "
                     "fetched here)",
        "duplex_style": "turn-based streaming, NOT full-duplex (would need "
                        "OmniFlatten-style duplex post-training)",
        "measured_here": False,
        "notes": "the ONLY candidate with a published measurement on the actual "
                 "board: 15.3-16.1 tok/s at Q8_0, llama.cpp, AGX Orin 64 GB "
                 "(github.com/ggml-org/llama.cpp/issues/15923); backbone RoboOmni "
                 "used to emit action tokens",
    },
]


def arithmetic(params_b: float) -> dict:
    out = {}
    for prec, bytes_per in (("bf16", 2), ("int8", 1), ("int4", 0.5)):
        gb = params_b * 1e9 * bytes_per / 1e9
        ceiling = ORIN_BW_GBS / gb          # theoretical steps/s
        realistic = ceiling * ROOFLINE_EFFICIENCY
        out[prec] = {
            "weights_gb": round(gb, 2),
            "fits_orin_64gb": bool(gb < ORIN_RAM_GB * 0.8),
            "theoretical_steps_per_s": round(ceiling, 1),
            "realistic_steps_per_s_at_83pct": round(realistic, 1),
            "meets_12p5hz": bool(realistic >= MOSHI_FRAME_HZ),
            "headroom_vs_12p5hz": round(realistic / MOSHI_FRAME_HZ, 2),
        }
    return out


def main() -> int:
    rows = []
    for c in CANDIDATES:
        r = dict(c)
        r["orin_arithmetic"] = arithmetic(c["params_b"])
        rows.append(r)
    out = {
        "hypothesis": "H-DS1c (AMENDMENTS.md D4)",
        "orin_bandwidth_gbs": ORIN_BW_GBS,
        "orin_bandwidth_source":
            "https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/",
        "method": (
            "batch-1 decode sweeps the whole weight set once per step, so "
            "steps/s ceiling = memory_bandwidth / (params x bytes_per_param). "
            "The realistic column applies the 0.83 roofline efficiency MEASURED "
            "on this host in H-DS1a; Orin may well do worse."
        ),
        "frame_hz_required": MOSHI_FRAME_HZ,
        "roofline_efficiency_measured": ROOFLINE_EFFICIENCY,
        "candidates": rows,
        "korean_caveat": (
            "Moshi's model card declares English only. No source fetched in this "
            "experiment verifies Korean for any candidate. If Korean is a "
            "requirement, that is an open question for every row here, and it is "
            "a REFUTING consideration for Moshi specifically."
        ),
    }
    Path(HERE / "candidates.json").write_text(json.dumps(out, indent=2))

    for r in rows:
        print(f"\n{r['name']}  ({r['params_b']} B)  {r['weights_license']}")
        print(f"  languages : {r['languages']}")
        print(f"  duplex    : {r['duplex_style']}")
        for prec, a in r["orin_arithmetic"].items():
            print(f"  {prec:5} {a['weights_gb']:>6} GB | ceiling {a['theoretical_steps_per_s']:>6} steps/s"
                  f" | realistic {a['realistic_steps_per_s_at_83pct']:>6} | >=12.5 Hz: {a['meets_12p5hz']}"
                  f" (x{a['headroom_vs_12p5hz']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
