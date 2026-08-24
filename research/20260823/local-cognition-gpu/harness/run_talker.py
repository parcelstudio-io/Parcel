"""Rows G7 and G8: can a local model hold the owner's turn?

30 owner turns are drawn from the repo's own live hosted capture
(``evals/companion/realtime_convo_v1/fixtures`` — 25 threads, 174 turns,
``gpt-realtime-2.1-mini``, captured 2026-08-18). Each local reply is generated
under the SAME rendered SI+DI the hosted capture used
(``render_session_instructions``), and against the SAME prior turns, so G8
compares two answers to one question rather than two different questions.

Two latencies, and they are different things:

* ``ttft_ms`` — first token on the wire (G7's first half).
* ``first_clause_ms`` — the moment enough text exists to *start speaking*: the
  first clause boundary (``. ? ! ; :`` , an em dash, a comma after >= 12
  characters, or a newline). On a duplex voice lane this, not TTFT, is when
  the owner hears something.

G8 runs the shipped ``pairwise_quality`` AutoRater with the hosted transcript
as ``base`` and the local reply as ``test``, both orders, position bias
reported. A negative score favours hosted; positive favours local.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from gpu import snapshot
from tick import percentile

from evals.autorater.raters import LlamaCppJudge, default_registry
from evals.autorater.types import RatingRequest, Response, Turn
from parcel_robot.realtime.prompting import DeveloperFlags, render_session_instructions

FIXTURES = REPO / "evals" / "companion" / "realtime_convo_v1" / "fixtures"
MODELS = {
    "ministral-8b": ("http://127.0.0.1:8082", "ministral-8b"),
    "gemma-26b": ("http://127.0.0.1:8081", "gemma-4-26b-a4b"),
}


def first_clause_index(text: str) -> int | None:
    """Index just past the first clause boundary, or ``None``."""

    for index, char in enumerate(text):
        if char in ".?!;:\n" or char == "—":
            return index + 1
        if char == "," and index >= 12:
            return index + 1
    return None


def sample_turns(count: int) -> list[dict[str, object]]:
    """Deterministic spread: turn k of thread k, cycling, in thread-id order."""

    threads = []
    for path in sorted(FIXTURES.glob("rt-conv-*.json")):
        threads.append(json.loads(path.read_text()))
    picked: list[dict[str, object]] = []
    offset = 0
    while len(picked) < count and offset < 12:
        for thread in threads:
            turns = thread["turns"]
            if offset >= len(turns):
                continue
            turn = turns[offset]
            picked.append(
                {
                    "thread_id": thread["thread_id"],
                    "family": thread["family"],
                    "si_profile": thread["si_profile"],
                    "di_flags": thread["di_flags"],
                    "index": turn["index"],
                    "owner_text": turn["owner_text"],
                    "hosted_text": turn["robot_text"],
                    "context": [
                        {"owner": prior["owner_text"], "robot": prior["robot_text"]}
                        for prior in turns[:offset]
                    ][-4:],
                }
            )
            if len(picked) >= count:
                break
        offset += 1
    return picked


def stream_reply(
    base_url: str, model: str, system: str, messages: list[dict[str, str]], max_tokens: int
) -> dict[str, object]:
    payload = {
        "model": model,
        "temperature": 0.7,
        "top_p": 0.95,
        "max_tokens": max_tokens,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "system", "content": system}, *messages],
    }
    request = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    ttft: float | None = None
    clause_at: float | None = None
    text = ""
    try:
        with urllib.request.urlopen(request, timeout=180) as stream:
            for raw in stream:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    event = json.loads(body)
                except json.JSONDecodeError:
                    continue
                for choice in event.get("choices") or ():
                    piece = (choice.get("delta") or {}).get("content") or ""
                    if not piece:
                        continue
                    if ttft is None:
                        ttft = time.perf_counter()
                    text += piece
                    if clause_at is None and first_clause_index(text) is not None:
                        clause_at = time.perf_counter()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"error": str(error), "text": "", "ttft_ms": None, "first_clause_ms": None}
    done = time.perf_counter()
    return {
        "error": "",
        "text": text.strip(),
        "ttft_ms": round(((ttft or done) - started) * 1000.0, 1),
        "first_clause_ms": round(((clause_at or done) - started) * 1000.0, 1),
        "total_ms": round((done - started) * 1000.0, 1),
        "chars": len(text.strip()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=30)
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--judge-url", default="", help="empty = skip G8 rating")
    parser.add_argument("--judge-model", default="qwen3-32b-judge")
    parser.add_argument("--out", default=str(HERE.parent / "results" / "talker.json"))
    args = parser.parse_args(argv)

    samples = sample_turns(args.turns)
    report: dict[str, object] = {"turns": len(samples), "models": {}, "gpu": []}
    models: dict[str, object] = report["models"]  # type: ignore[assignment]
    gpu_rows: list[dict[str, object]] = report["gpu"]  # type: ignore[assignment]

    rater = None
    if args.judge_url:
        backend = LlamaCppJudge(base_url=args.judge_url, model=args.judge_model, timeout=900.0)
        rater = default_registry(backend).get("pairwise_quality")

    for name in (part.strip() for part in args.models.split(",") if part.strip()):
        base_url, model_id = MODELS[name]
        gpu_rows.append(snapshot(f"talker:{name}:start"))
        rows: list[dict[str, object]] = []
        for sample in samples:
            flags = DeveloperFlags.from_mapping(sample["di_flags"])
            rendered = render_session_instructions(
                profile_id=str(sample["si_profile"]), flags=flags
            )
            messages: list[dict[str, str]] = []
            for prior in sample["context"]:  # type: ignore[union-attr]
                messages.append({"role": "user", "content": prior["owner"]})
                messages.append({"role": "assistant", "content": prior["robot"]})
            messages.append({"role": "user", "content": str(sample["owner_text"])})
            result = stream_reply(
                base_url, model_id, rendered.text, messages, args.max_tokens
            )
            rows.append({**{k: sample[k] for k in ("thread_id", "family", "index")}, **result,
                         "owner_text": sample["owner_text"],
                         "hosted_text": sample["hosted_text"]})
        gpu_rows.append(snapshot(f"talker:{name}:end"))

        ttfts = [row["ttft_ms"] for row in rows if row["ttft_ms"] is not None]
        clauses = [row["first_clause_ms"] for row in rows if row["first_clause_ms"] is not None]
        summary: dict[str, object] = {
            "replies": len(rows),
            "errors": sum(1 for row in rows if row["error"]),
            "ttft_p50_ms": round(percentile(ttfts, 0.50), 1),
            "ttft_p95_ms": round(percentile(ttfts, 0.95), 1),
            "first_clause_p50_ms": round(percentile(clauses, 0.50), 1),
            "first_clause_p95_ms": round(percentile(clauses, 0.95), 1),
            "reply_chars_p50": round(percentile([float(row["chars"]) for row in rows], 0.50), 1),
        }

        if rater is not None:
            verdicts = []
            for row, sample in zip(rows, samples, strict=True):
                context = tuple(
                    turn
                    for prior in sample["context"]  # type: ignore[union-attr]
                    for turn in (
                        Turn("owner", prior["owner"]),
                        Turn("robot", prior["robot"]),
                    )
                )
                request = RatingRequest(
                    prompt=str(sample["owner_text"]),
                    base=Response("base", (Turn("robot", str(row["hosted_text"])),)),
                    test=Response("test", (Turn("robot", str(row["text"]) or "(empty)"),)),
                    context=context,
                )
                verdict = rater.rate(request)
                verdicts.append(verdict)
                row["pairwise_score"] = verdict.score
                row["pairwise_preference"] = verdict.preference
                row["pairwise_position_bias"] = verdict.position_bias
                row["pairwise_rationale"] = verdict.rationale[:300]
                print(name, row["thread_id"], verdict.preference, verdict.score, flush=True)
            scored = [v for v in verdicts if not v.abstained and v.score is not None]
            biases = [v.position_bias for v in scored if v.position_bias is not None]
            summary["pairwise"] = {
                "rater": rater.fingerprint,
                "rated": len(scored),
                "abstentions": len(verdicts) - len(scored),
                "mean_score": round(sum(v.score for v in scored) / len(scored), 3)
                if scored
                else None,
                "local_wins": sum(1 for v in scored if v.preference == "test"),
                "hosted_wins": sum(1 for v in scored if v.preference == "base"),
                "ties": sum(1 for v in scored if v.preference == "tie"),
                "mean_position_bias": round(sum(biases) / len(biases), 3) if biases else None,
            }
        models[name] = {"summary": summary, "rows": rows}
        print(name, json.dumps(summary, indent=1), flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
