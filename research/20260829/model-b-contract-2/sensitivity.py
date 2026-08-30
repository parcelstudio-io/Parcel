"""MB-2 — post-hoc sensitivity over the SAME stored candidates.  Not pre-registered.

`run.py` measured the checker `DESIGN.md` describes: a no-ADDITION rule.  Every
claim a candidate makes must be licensed by the turn's acts and supported by a
receipt; the content post-conditions it enforces are the ones that carry a
refusal, an offer, a clarification and a goal name through the rewording.

It does not require the act's HEADLINE CLAIM to survive.  Arm T+P's coverage and
`b2` fell against arm T, and this file measures why, and what a claim-preserving
checker would have cost — offline, on the candidates `results/TP.json` already
holds, with NO new model call.  Everything it prints is labelled POST-HOC in
`RESULTS.md` and none of it moves a pre-registered criterion.

    .parcel/bin/python research/20260829/model-b-contract-2/sensitivity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
if str(FOLDER) not in sys.path:
    sys.path.insert(0, str(FOLDER))

import contract as ct
from mb1 import sc

#: The claim class each act exists to make.  A paraphrase that drops it has kept
#: the contract and lost the news, which is exactly what coverage measures.
HEADLINE_CLAIM: dict[str, str] = {
    ct.ACT_ACK: sc.CLAIM_ACCEPT,
    ct.ACT_COMPLETED: sc.CLAIM_ARRIVAL,
    ct.ACT_BLOCKED: sc.CLAIM_BLOCKED,
    ct.ACT_FAILED: sc.CLAIM_FAILED,
    ct.ACT_CANCELLED: sc.CLAIM_CANCELLED,
    ct.ACT_RESUMED: sc.CLAIM_RESUMED,
    ct.ACT_PROGRESS: sc.CLAIM_MOTION,
}


def main() -> int:
    rows = json.loads((FOLDER / "results/TP.json").read_text(encoding="utf-8"))["turns"]

    lost: list[dict[str, object]] = []
    would_reject = 0
    already_rejected = 0
    for row in rows:
        acts = tuple(
            ct.SpeechAct(a["act"], {k: (tuple(v) if isinstance(v, list) else v)
                                     for k, v in a["slots"].items()})
            for a in row["acts"]["acts"]
        )
        if row["fell_back"]:
            already_rejected += 1
            continue
        spoken = row["spoken"]
        present = {c for c, _ in sc.extract_claims(spoken)}
        missing = [
            HEADLINE_CLAIM[a.act]
            for a in acts
            if a.act in HEADLINE_CLAIM and HEADLINE_CLAIM[a.act] not in present
        ]
        if missing:
            would_reject += 1
            lost.append(
                {
                    "scenario_id": row["scenario_id"],
                    "at_s": row["at_s"],
                    "lost": sorted(set(missing)),
                    "template": row["template"],
                    "spoken": spoken,
                }
            )

    total = len(rows)
    payload = {
        "post_hoc": True,
        "not_pre_registered": True,
        "question": (
            "What would the checker have cost, and bought, if it had ALSO required "
            "each act's headline claim class to survive the paraphrase?"
        ),
        "model_calls": 0,
        "turns": total,
        "fallbacks_as_run": already_rejected,
        "fallbacks_as_run_rate": round(already_rejected / total, 4),
        "additional_rejections": would_reject,
        "fallback_rate_with_claim_preservation": round(
            (already_rejected + would_reject) / total, 4
        ),
        "turns_that_lost_the_headline_claim": lost,
    }
    (FOLDER / "results/sensitivity.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in payload.items()
                      if k != "turns_that_lost_the_headline_claim"}, indent=1))
    for row in lost:
        print(f"  lost {row['lost']}  T: {row['template']}")
        print(f"                     P: {row['spoken']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
