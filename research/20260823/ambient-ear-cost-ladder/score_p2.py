"""C7 — pairwise quality of the local arm against the hosted capture.

    .parcel/bin/python score_p2.py [--limit N]

Scored with the repo's own ``evals/autorater`` ``pairwise_quality`` rater, which
runs BOTH presentation orders and reports the spread between them as
``position_bias``. An abstention carries ``score=None`` and is counted as an
abstention, never as a tie — the rater's own rule, and the reason the summary
reports decisive/abstained counts beside the mean.

WHICH TURNS ARE SCORED
----------------------
The locally answered ones. A turn the ladder ESCALATED is answered by the
hosted model in both arms — the same words — so scoring it would add a
guaranteed tie per escalation and dilute the number toward zero. The escalated
turns are counted in the summary as ties by construction, and the headline is
reported both ways so neither reading is hidden.

Sides: ``base`` is the hosted capture, ``test`` is the local answer. The
rater's sign convention then reads directly — negative means hosted was better.
Results are appended per pair to ``results/p2_quality.jsonl`` as they land, so a
judge that dies at pair 100 does not cost the first 99.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from ladder import RESULTS_DIR

from evals.autorater import LlamaCppJudge, RatingRequest, Response, Turn, default_registry

JUDGE_URL = "http://127.0.0.1:8090"
RATER_ID = "pairwise_quality"
JSONL = RESULTS_DIR / "p2_quality.jsonl"

#: The mapping from the rater's signed score to the DESIGN's "points". Declared
#: here and never adjusted: 0 points is a tie, +100 means the local arm won
#: every pair decisively, -100 means the hosted arm did. C7's "-5 points" is
#: therefore a mean score of -0.10.
POINTS_PER_SCORE = 50.0


def _context(rows: list[dict], row: dict) -> tuple[Turn, ...]:
    """The thread so far, both sides, as the judge's shared context."""

    turns: list[Turn] = []
    for other in rows:
        if other["thread"] != row["thread"] or other["index"] >= row["index"]:
            continue
        turns.append(Turn("owner", str(other["owner_text"])))
        turns.append(Turn("robot", str(other["hosted_text"])))
    return tuple(turns[-8:])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="score at most N pairs")
    parser.add_argument("--judge-url", default=JUDGE_URL, help="OpenAI-compatible judge server")
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="work the pair list back to front, so a second worker on a second "
        "judge server converges toward the first instead of racing it",
    )
    parser.add_argument("--summary-only", action="store_true", help="no judging; re-summarise")
    parser.add_argument("--offset", type=int, default=0, help="start at this pair")
    parser.add_argument("--stride", type=int, default=1, help="take every Nth pair")
    args = parser.parse_args()

    ladder = json.loads((RESULTS_DIR / "p2_ladder.json").read_text(encoding="utf-8"))
    rows = ladder["rows"]
    local_rows = [r for r in rows if r["route"] == "local"]
    escalated = sum(1 for r in rows if r["route"] == "hosted")
    if args.limit:
        local_rows = local_rows[: args.limit]
    if args.reverse:
        local_rows = list(reversed(local_rows))
    if args.stride > 1 or args.offset:
        # Disjoint slices, so N workers on N judge slots do N different pairs.
        local_rows = local_rows[args.offset :: max(1, args.stride)]

    done: dict[str, dict] = {}
    if JSONL.exists():
        for line in JSONL.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                done[f"{entry['thread']}#{entry['index']}"] = entry

    registry = default_registry(LlamaCppJudge(base_url=args.judge_url, timeout=600.0))
    rater = registry.get(RATER_ID)
    JSONL.parent.mkdir(parents=True, exist_ok=True)

    for position, row in enumerate(local_rows, start=1):
        if args.summary_only:
            break
        key = f"{row['thread']}#{row['index']}"
        if key in done:
            continue
        # Re-read the shared file each pair: a second worker on a second judge
        # server is appending to it, and the point of two workers is to not do
        # the same pair twice.
        if JSONL.exists():
            for line in JSONL.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    other = json.loads(line)
                    done[f"{other['thread']}#{other['index']}"] = other
            if key in done:
                continue
        verdict = rater.rate(
            RatingRequest(
                prompt=str(row["owner_text"]),
                base=Response("base", (Turn("robot", str(row["hosted_text"])),)),
                test=Response("test", (Turn("robot", str(row["local_text"])),)),
                context=_context(rows, row),
            )
        )
        entry = {
            "thread": row["thread"],
            "index": row["index"],
            "family": row["family"],
            "owner_text": row["owner_text"],
            "score": verdict.score,
            "preference": verdict.preference,
            "abstained": verdict.abstained,
            "abstain_reason": verdict.abstain_reason,
            "position_bias": verdict.position_bias,
            "order_scores": list(verdict.order_scores),
            "rationale": verdict.rationale[:600],
        }
        with JSONL.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        done[key] = entry
        print(f"[{position}/{len(local_rows)}] {key} {verdict.preference} {verdict.score}", flush=True)

    scored = [e for e in done.values() if not e["abstained"] and e["score"] is not None]
    abstained = [e for e in done.values() if e["abstained"]]
    scores = [float(e["score"]) for e in scored]
    biases = [float(e["position_bias"]) for e in scored if e["position_bias"] is not None]
    preferences = {
        side: sum(1 for e in scored if e["preference"] == side) for side in ("base", "test", "tie")
    }
    mean_local_only = statistics.mean(scores) if scores else None
    # With the escalated turns counted as the ties they are by construction.
    with_escalated = (
        (sum(scores) / (len(scores) + escalated)) if (scores or escalated) else None
    )
    summary = {
        "harness": "p2_quality",
        "rater": rater.fingerprint,
        "judge_url": args.judge_url,
        "judge_model": "qwen3-32b-judge (Qwen3-32B-Q4_K_M, CPU)",
        "pairs_scored": len(scored),
        "pairs_abstained": len(abstained),
        "escalated_turns_tie_by_construction": escalated,
        "preferences": preferences,
        "mean_score_local_answers_only": (
            round(mean_local_only, 4) if mean_local_only is not None else None
        ),
        "points_local_answers_only": (
            round(mean_local_only * POINTS_PER_SCORE, 2) if mean_local_only is not None else None
        ),
        "mean_score_with_escalated_as_ties": (
            round(with_escalated, 4) if with_escalated is not None else None
        ),
        "points_with_escalated_as_ties": (
            round(with_escalated * POINTS_PER_SCORE, 2) if with_escalated is not None else None
        ),
        "position_bias_mean": round(statistics.mean(biases), 4) if biases else None,
        "position_bias_max": round(max(biases), 4) if biases else None,
        "points_per_score": POINTS_PER_SCORE,
    }
    Path(RESULTS_DIR / "p2_quality_summary.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
