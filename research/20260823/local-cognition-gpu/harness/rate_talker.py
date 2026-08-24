"""Row G8: rate the already-generated local replies against the hosted ones.

Split out of ``run_talker.py`` on purpose. Generation is GPU work and rating is
CPU work (the 32B judge does not fit beside the two resident models on a 32 GB
card, so it runs on the pinned CPU binary). Keeping them apart means the G7
timings are never measured while a 48-thread judge is hammering the host.

Reads ``results/talker.json``, writes ``results/talker_rated.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from evals.autorater.raters import LlamaCppJudge, default_registry
from evals.autorater.types import RatingRequest, Response, Turn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge-url", default="http://127.0.0.1:8090")
    parser.add_argument("--judge-model", default="qwen3-32b-judge")
    parser.add_argument("--source", default=str(HERE.parent / "results" / "talker.json"))
    parser.add_argument("--out", default=str(HERE.parent / "results" / "talker_rated.json"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    report = json.loads(Path(args.source).read_text())
    backend = LlamaCppJudge(base_url=args.judge_url, model=args.judge_model, timeout=1200.0)
    rater = default_registry(backend).get("pairwise_quality")

    def rate_row(row: dict) -> object:
        request = RatingRequest(
            prompt=str(row["owner_text"]),
            base=Response("base", (Turn("robot", str(row["hosted_text"])),)),
            test=Response("test", (Turn("robot", str(row["text"]) or "(empty reply)"),)),
        )
        verdict = rater.rate(request)
        row["pairwise_score"] = verdict.score
        row["pairwise_preference"] = verdict.preference
        row["pairwise_position_bias"] = verdict.position_bias
        row["pairwise_rationale"] = verdict.rationale[:300]
        print(row["thread_id"], verdict.preference, verdict.score, flush=True)
        return verdict

    # The judge server has four slots; llama.cpp batches concurrent sequences
    # into one decode, so four in flight is roughly four times the throughput
    # of one on a CPU-bound 32B. Each rater call is independent — the shared
    # backend holds no per-call state this path reads.
    for name, block in report["models"].items():
        print("rating", name, flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            verdicts = list(pool.map(rate_row, block["rows"]))
        scored = [v for v in verdicts if not v.abstained and v.score is not None]
        biases = [v.position_bias for v in scored if v.position_bias is not None]
        block["summary"]["pairwise"] = {
            "rater": rater.fingerprint,
            "judge_model": backend.model_id,
            "rated": len(scored),
            "abstentions": len(verdicts) - len(scored),
            "mean_score": round(sum(v.score for v in scored) / len(scored), 3) if scored else None,
            "local_wins": sum(1 for v in scored if v.preference == "test"),
            "hosted_wins": sum(1 for v in scored if v.preference == "base"),
            "ties": sum(1 for v in scored if v.preference == "tie"),
            "mean_position_bias": round(sum(biases) / len(biases), 3) if biases else None,
        }
        print(name, json.dumps(block["summary"]["pairwise"], indent=1), flush=True)

    out = Path(args.out)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
