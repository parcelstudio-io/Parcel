"""Row G5's prerequisite: does the 32B judge uphold the author's gold labels?

Reported BEFORE any model-agreement number, because an agreement score against
labels nobody checked is a measurement of the author, not the model.

Rails: ``evals.autorater`` exactly as shipped — :class:`LlamaCppJudge` for the
backend, :class:`ComparativeAutoRater` for the both-orders presentation and the
``position_bias`` it reports, and ``parse_judge_json`` for the fail-closed
parse. Only the rubric is new, because the shipped rubrics rate conversational
replies and this rates a chosen *action*.

THE FOIL IS A RULE, NOT A TASTE
-------------------------------
Each case is judged against one competing action chosen by a fixed rule, so no
per-case authoring decision can quietly tilt the adjudication:

    gold ignore   -> remark   (the annoyance failure mode)
    gold look     -> ignore   (did the head turn need to happen?)
    gold remark   -> ignore   (was speaking worth it?)
    gold ask      -> remark   (does the answer actually change anything?)
    gold go_check -> look     (could looking have settled it?)

A judge that prefers the foil is evidence the gold label is wrong. Those cases
are listed by id in the results, never silently dropped.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from gold_set import GoldCase, gold_cases

from evals.autorater.base import ComparativeAutoRater, parse_judge_json
from evals.autorater.raters import LlamaCppJudge
from evals.autorater.types import RatingRequest, Response, Side, Turn

FOIL_RULE = {
    "ignore": "remark",
    "look": "ignore",
    "remark": "ignore",
    "ask": "remark",
    "go_check": "look",
}

JUDGE_SYSTEM = """\
You are an evaluation judge for Parcel, a companion robot dog. You are shown
the dog's world digest for one moment and two candidate actions. You decide
which action a thoughtful owner would prefer the dog to take.

Apply these rules without exception:
- A calm dog is silent. Doing nothing is a real answer and is often the best
  one. Never reward action for its own sake.
- The dog must never speak while the owner is speaking, while the voice lane
  is busy, during quiet hours, or when the owner is absent.
- The dog must not repeat anything already in RECENT.
- Cheaper is better when it is sufficient: ignore < look < remark/ask <
  go_check.
- Judge only what the digest states. Do not assume facts it does not contain.

Reply with EXACTLY ONE JSON object and no other text."""

JUDGE_TEMPLATE = """\
WORLD DIGEST
{digest}

ACTION A
{first}

ACTION B
{second}

Which action should the dog take in this moment?

Return JSON:
{{"winner": "A" | "B" | "tie",
  "margin": <0.0-1.0, how decisive; 0.0 for a tie>,
  "rationale": "<one sentence naming the digest field that decided it>"}}"""


def _describe(kind: str, target: str, text: str) -> str:
    if kind == "ignore":
        return "ignore — do nothing and stay quiet"
    if kind == "look":
        return f"look — turn the head to bearing {target} degrees"
    if kind == "go_check":
        return f"go_check — walk over to {target} and inspect it"
    return f'{kind} — say: "{text}"'


def foil_for(case: GoldCase) -> str:
    kind = FOIL_RULE[case.gold_kind]
    first = case.digest.noticings[0] if case.digest.noticings else None
    label = first.label if first else "what I can see"
    if kind == "remark":
        return _describe("remark", "", f"There's {label} over there.")
    if kind == "look":
        bearing = f"{first.bearing_deg:.0f}" if first else "0"
        return _describe("look", bearing, "")
    return _describe(kind, "", "")


def gold_action(case: GoldCase) -> str:
    first = case.digest.noticings[0] if case.digest.noticings else None
    label = first.label if first else "what I can see"
    if case.gold_kind == "look":
        bearing = f"{first.bearing_deg:.0f}" if first else "0"
        return _describe("look", bearing, "")
    if case.gold_kind == "go_check":
        target = case.digest.place if case.digest.place != "unknown" else "there"
        return f"go_check — walk over to {label} and inspect it (near {target})"
    if case.gold_kind == "remark":
        return _describe("remark", "", f"I noticed {label}.")
    if case.gold_kind == "ask":
        return _describe("ask", "", f"Do you know about {label}?")
    return _describe("ignore", "", "")


class ActionChoiceRater(ComparativeAutoRater):
    """Which of two actions serves the owner better, judged in both orders."""

    id = "h2_action_choice"
    version = "1"
    tie_band = 0.1

    def __init__(self, backend: LlamaCppJudge) -> None:
        self.backend = backend

    def _judge_once(
        self, request: RatingRequest, *, first: Side
    ) -> tuple[float, str, Mapping[str, float]]:
        second: Side = "test" if first == "base" else "base"
        sides = {"base": request.base, "test": request.test}
        user = JUDGE_TEMPLATE.format(
            digest=request.prompt,
            first=sides[first].turns[0].text,
            second=sides[second].turns[0].text,
        )
        reply = self.backend.complete(JUDGE_SYSTEM, user, max_tokens=256)
        payload = parse_judge_json(reply)
        winner = str(payload.get("winner", "")).strip().upper()
        if winner not in {"A", "B", "TIE"}:
            raise ValueError(f"judge named no winner: {payload!r}")
        margin = float(payload.get("margin", 0.0))
        rationale = str(payload.get("rationale", ""))[:300]
        if winner == "TIE":
            return 0.0, rationale, {}
        shown_side = first if winner == "A" else second
        score = margin if shown_side == "test" else -margin
        return score, rationale, {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--model", default="qwen3-32b-judge")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--out", default=str(HERE.parent / "results" / "judge_gold.json"))
    args = parser.parse_args(argv)

    backend = LlamaCppJudge(base_url=args.base_url, model=args.model, timeout=args.timeout)
    rater = ActionChoiceRater(backend)
    rows: list[dict[str, object]] = []
    for case in gold_cases():
        request = RatingRequest(
            prompt=case.digest.render(),
            base=Response("base", (Turn("robot", gold_action(case)),)),
            test=Response("test", (Turn("robot", foil_for(case)),)),
        )
        verdict = rater.rate(request)
        rows.append(
            {
                "case_id": case.case_id,
                "gold_kind": case.gold_kind,
                "foil_kind": FOIL_RULE[case.gold_kind],
                "arguable": case.arguable,
                "abstained": verdict.abstained,
                "abstain_reason": verdict.abstain_reason,
                "score": verdict.score,
                "preference": verdict.preference,
                "position_bias": verdict.position_bias,
                "order_scores": list(verdict.order_scores or ()),
                "rationale": verdict.rationale[:400],
            }
        )
        print(json.dumps(rows[-1]), flush=True)

    scored = [row for row in rows if not row["abstained"]]
    upheld = [row for row in scored if row["preference"] in ("base", "tie")]
    overturned = [row for row in scored if row["preference"] == "test"]
    biases = [row["position_bias"] for row in scored if row["position_bias"] is not None]
    report = {
        "rater": rater.fingerprint,
        "judge_model": backend.model_id,
        "cases": len(rows),
        "abstentions": len(rows) - len(scored),
        "gold_upheld": len(upheld),
        "gold_overturned": len(overturned),
        "author_judge_agreement": round(len(upheld) / len(scored), 3) if scored else None,
        "overturned_ids": [row["case_id"] for row in overturned],
        "overturned_arguable": sum(1 for row in overturned if row["arguable"]),
        "mean_position_bias": round(sum(biases) / len(biases), 3) if biases else None,
        "rows": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
