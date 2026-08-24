"""DIAGNOSTIC (not a pre-registered row): what would it take to hit G1?

G1's budget is spent almost entirely on decode, not on prefill, so the honest
follow-up question when G1 misses is "how many output tokens can this model
afford, and can a decision fit in them?" This script answers it by measuring
the same 8B tick with one added instruction — minified JSON, six-word reason —
and reporting the token count and latency beside the unchanged run.

It moves no criterion. G1/G2 stay exactly as ``run_latency.py`` measured them;
this is the sizing evidence the milestone design needs about *where* the
budget goes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3] / "src"))

from gold_set import gold_cases
from gpu import snapshot
from tick import TickClient, summarize

from parcel_robot.brain.monologue import MONOLOGUE_SYSTEM_PROMPT

COMPACT_SUFFIX = (
    "\n\nEmit MINIFIED JSON on one line with no spaces or newlines between "
    "tokens. Keep \"reason\" to at most six words."
)


class CompactTickClient(TickClient):
    """Identical to the tick, plus one output-shape instruction."""

    def payload(self, digest):  # type: ignore[override]
        body = super().payload(digest)
        messages = list(body["messages"])  # type: ignore[arg-type]
        messages[0] = {
            "role": "system",
            "content": MONOLOGUE_SYSTEM_PROMPT + COMPACT_SUFFIX,
        }
        body["messages"] = messages
        return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=120)
    parser.add_argument("--base-url", default="http://127.0.0.1:8082")
    parser.add_argument("--model", default="ministral-8b")
    parser.add_argument(
        "--out", default=str(HERE.parent / "results" / "compact_diagnostic.json")
    )
    args = parser.parse_args(argv)

    cases = gold_cases()
    client = CompactTickClient(args.base_url, args.model)
    for _ in range(3):
        client.tick(cases[0].digest, digest_id="warmup")
    before = snapshot("compact:start")
    outcomes = [
        client.tick(cases[index % len(cases)].digest, digest_id=cases[index % len(cases)].case_id)
        for index in range(args.ticks)
    ]
    after = snapshot("compact:end")
    summary = summarize(outcomes)
    kinds: dict[str, int] = {}
    for outcome in outcomes:
        if outcome.decision:
            kinds[outcome.decision.kind] = kinds.get(outcome.decision.kind, 0) + 1
    report = {
        "note": "DIAGNOSTIC — not a pre-registered row; G1/G2 stand as measured",
        "model": args.model,
        "summary": summary,
        "kinds": kinds,
        "gpu": [before, after],
        "raw": [outcome.as_dict() for outcome in outcomes],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=1))
    print(json.dumps(kinds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
