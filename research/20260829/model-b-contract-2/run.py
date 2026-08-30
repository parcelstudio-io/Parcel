"""MB-2 — the runner.  T first, then T+P, then the report-only judge.

    .parcel/bin/python research/20260829/model-b-contract-2/run.py --all --seed 20260829

Every number is produced on MB-1's instrument, imported unchanged: its
40-scenario receipt corpus, its scorer (grounding, coverage, claims/turn, bars
b1-b5, invented-action matcher, perception rule), its trigger table and band
discipline, its CONV-1 transcript shape, and its frozen blind-adjudication
prompt.  MB-2 adds the contract and the two arms, and nothing else.

No hosted call is made from this file, and none can be: the only network client
here is ``urllib`` against ``127.0.0.1:8093``, a llama-server this card starts
and kills by process group on every exit path.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
if str(FOLDER) not in sys.path:
    sys.path.insert(0, str(FOLDER))

import arms
import contract as ct
from mb1 import BANDS, MB1_ADJUDICATION_PROMPT, MB1_RESULTS, ev, sc

RUN_ID = "mb2-run-v1"
CACHE = Path.home() / ".cache/parcel-0e/mb2"
MB1_CACHE = Path.home() / ".cache/parcel-0e/mb1"
LOCAL_PORT = 8093
LOCAL_MODEL = MB1_CACHE / "models/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
LLAMA_SERVER = FOLDER.parents[2] / "third_party/llama.cpp-bin/llama-b10235/llama-server"
LOCAL_MODEL_NAME = "Qwen2.5-7B-Instruct-Q4_K_M"

PARAPHRASE_PROMPT = FOLDER / "prompts/paraphrase_v1.txt"
JUDGE_PROMPT = FOLDER / "prompts/naturalness_judge_v1.txt"

PARAPHRASE_TEMPERATURE = 0.3
PARAPHRASE_MAX_TOKENS = 60

_server_process: subprocess.Popen | None = None


# ------------------------------------------------------------------ the model
@dataclass
class Reply:
    text: str
    ttft_ms: float | None = None
    total_ms: float | None = None
    error: str = ""


_QUOTES = re.compile(r'^[\s"“”\'`]+|[\s"“”\'`]+$')


class Paraphraser:
    """One local paraphrase per turn, through the frozen prompt.

    The ONLY post-processing is stripping surrounding whitespace and quotation
    marks: a model that answers ``"I'm at the door!"`` is answering, not
    overclaiming.  Nothing else is repaired — a candidate that adds a fact is
    handed to the checker exactly as it arrived, which is the whole point.
    """

    def __init__(self, base_url: str, model: str, *, seed: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.seed = int(seed)
        self.system = PARAPHRASE_PROMPT.read_text(encoding="utf-8")
        self.calls = 0
        self.errors = 0

    @staticmethod
    def _facts(utterance: arms.Utterance) -> str:
        rows = []
        for act in utterance.acts:
            slots = ", ".join(
                f"{k}={v}" for k, v in sorted(act.slots.items()) if v not in (False, (), "")
            )
            rows.append(f"{act.act}({slots})" if slots else act.act)
        if utterance.closing:
            rows.append("closing question")
        return "; ".join(rows)

    def paraphrase(self, utterance: arms.Utterance, template: str) -> Reply:
        user = f"SENTENCE: {template}\nFACTS IN IT: {self._facts(utterance)}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system},
                {"role": "user", "content": user},
            ],
            "temperature": PARAPHRASE_TEMPERATURE,
            "max_tokens": PARAPHRASE_MAX_TOKENS,
            "seed": self.seed,
            "stream": True,
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        start = time.perf_counter()
        first: float | None = None
        pieces: list[str] = []
        self.calls += 1
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                for raw in response:
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data: "):
                        continue
                    body = line[6:]
                    if body == "[DONE]":
                        break
                    try:
                        frame = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    piece = ((frame.get("choices") or [{}])[0].get("delta") or {}).get(
                        "content"
                    ) or ""
                    if piece:
                        if first is None:
                            first = time.perf_counter() - start
                        pieces.append(piece)
        except Exception as error:  # noqa: BLE001 - a model error is a fallback, not a crash
            self.errors += 1
            return Reply(text="", ttft_ms=None, total_ms=None, error=type(error).__name__)
        text = _QUOTES.sub("", "".join(pieces)).strip()
        return Reply(
            text=text,
            ttft_ms=None if first is None else round(first * 1000, 3),
            total_ms=round((time.perf_counter() - start) * 1000, 3),
        )


# ------------------------------------------------------------------- server
def _port_busy(port: int) -> bool:
    import socket

    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def start_local_server(log_path: Path, *, threads: int = 32) -> tuple[subprocess.Popen | None, str]:
    """Start the llama-server this card OWNS on :8093.  CPU build, by fact."""

    global _server_process
    if not LLAMA_SERVER.exists():
        return None, f"no llama-server binary at {LLAMA_SERVER}"
    if not LOCAL_MODEL.exists():
        return None, f"no GGUF at {LOCAL_MODEL}"
    if _port_busy(LOCAL_PORT):
        return None, f":{LOCAL_PORT} is already in use; this card refuses to share it"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8")
    env = dict(os.environ)
    env["OPENBLAS_NUM_THREADS"] = "32"
    process = subprocess.Popen(
        [
            str(LLAMA_SERVER),
            "--model", str(LOCAL_MODEL),
            "--host", "127.0.0.1",
            "--port", str(LOCAL_PORT),
            "--ctx-size", "4096",
            "--threads", str(threads),
            "--no-webui",
        ],
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    _server_process = process
    deadline = time.time() + 300
    while time.time() < deadline:
        if process.poll() is not None:
            return None, f"llama-server exited during startup (rc={process.returncode})"
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{LOCAL_PORT}/health", timeout=2
            ) as response:
                if response.status == 200:
                    return process, f"llama-server ready on :{LOCAL_PORT} (pid {process.pid})"
        except Exception:  # noqa: BLE001 - not ready yet
            time.sleep(2)
    return None, "llama-server never became healthy within 300 s"


def stop_local_server() -> None:
    """Kill by PROCESS GROUP, on every exit path, and never anyone else's."""

    global _server_process
    process = _server_process
    _server_process = None
    if process is None:
        return
    try:
        group = os.getpgid(process.pid)
    except ProcessLookupError:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=15)
            return
        except subprocess.TimeoutExpired:
            continue


# ------------------------------------------------------------------ scoring
def _host_row() -> dict[str, object]:
    try:
        uptime = subprocess.run(
            ["uptime"], capture_output=True, text=True, timeout=10, check=False
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        uptime = "unavailable"
    try:
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,utilization.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        gpu = "unavailable"
    return {
        "uptime": uptime,
        "nvidia_smi": gpu,
        "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _walk(corpus, registry, *, paraphraser, progress_every: int = 5):
    t_all: list[sc.Turn] = []
    tp_all: list[sc.Turn] = []
    raw_all: list[sc.Turn] = []
    records: list[arms.TurnRecord] = []
    for number, scenario in enumerate(corpus, start=1):
        t, tp, raw, recs = arms.run_scenario(
            scenario, registry=registry, bands=BANDS, paraphraser=paraphraser
        )
        t_all.extend(t)
        tp_all.extend(tp)
        raw_all.extend(raw)
        records.extend(recs)
        if progress_every and number % progress_every == 0:
            print(f"    [{number}/{len(corpus)}] {scenario.scenario_id}", flush=True)
    return t_all, tp_all, raw_all, records


def _score(corpus, turns, registry, *, arm: str, seed: int):
    by_scenario: dict[str, list[sc.Turn]] = {}
    for turn in turns:
        if turn.arm != arm:
            continue
        by_scenario.setdefault(turn.scenario_id, []).append(turn)
    results = [
        sc.score_scenario(scenario, by_scenario[scenario.scenario_id], registry)
        for scenario in corpus
        if by_scenario.get(scenario.scenario_id)
    ]
    return results, sc.aggregate(results, arm=arm, seed=seed)


def _checker_rows(records: list[arms.TurnRecord], *, gated: bool) -> dict[str, object]:
    total = len(records)
    template_ok = sum(1 for r in records if r.check_template and r.check_template.ok)
    row: dict[str, object] = {
        "turns": total,
        "template_self_check_pass": template_ok,
        "template_self_check_rate": round(template_ok / total, 4) if total else None,
        "template_reject_reasons": sc._tally(
            [reason for r in records if r.check_template for reason in r.check_template.reasons]
        ),
        "template_words_max": max((r.check_template.words for r in records if r.check_template), default=0),
    }
    if not gated:
        return row
    fell = sum(1 for r in records if r.fell_back)
    empty = sum(1 for r in records if not r.candidate)
    identical = sum(
        1 for r in records if r.candidate and sc.normalise(r.candidate) == sc.normalise(r.template)
    )
    row.update(
        {
            "paraphrases": total,
            "fallbacks": fell,
            "fallback_rate": round(fell / total, 4) if total else None,
            "paraphrase_empty_or_error": empty,
            "paraphrase_identical_to_template": identical,
            "rejection_reasons": sc._tally(
                [
                    reason
                    for r in records
                    if r.fell_back and r.check_candidate
                    for reason in r.check_candidate.reasons
                ]
            ),
            "rejection_reason_families": sc._tally(
                [
                    reason.split(":", 1)[0]
                    for r in records
                    if r.fell_back and r.check_candidate
                    for reason in r.check_candidate.reasons
                ]
            ),
        }
    )
    return row


def _latency_rows(records: list[arms.TurnRecord]) -> dict[str, object]:
    def _pct(values: list[float], q: float) -> float | None:
        if not values:
            return None
        values = sorted(values)
        return round(values[min(len(values) - 1, int(q * len(values)))], 3)

    render = [r.render_ms for r in records]
    check = [r.check_ms for r in records]
    total_t = [r.render_ms + r.check_ms for r in records]
    ttft = [r.ttft_ms for r in records if r.ttft_ms is not None]
    total_p = [r.total_ms for r in records if r.total_ms is not None]
    return {
        "T_render_ms_p50": _pct(render, 0.5),
        "T_render_ms_p95": _pct(render, 0.95),
        "T_check_ms_p50": _pct(check, 0.5),
        "T_render_plus_check_ms_p50": _pct(total_t, 0.5),
        "T_render_plus_check_ms_p95": _pct(total_t, 0.95),
        "T_render_plus_check_ms_max": round(max(total_t), 3) if total_t else None,
        "paraphrase_n": len(ttft),
        "paraphrase_ttft_ms_p50": _pct(ttft, 0.5),
        "paraphrase_ttft_ms_p95": _pct(ttft, 0.95),
        "paraphrase_total_ms_p50": _pct(total_p, 0.5),
        "paraphrase_total_ms_p95": _pct(total_p, 0.95),
    }


# -------------------------------------------------------------- the judge
def judge_naturalness(
    records: list[arms.TurnRecord], *, base_url: str, model: str, seed: int, pairs: int
) -> dict[str, object]:
    """Report-only: blind A/B naturalness, frozen prompt, seeded order."""

    system = JUDGE_PROMPT.read_text(encoding="utf-8")
    usable = [
        r
        for r in records
        if r.candidate
        and not r.fell_back
        and sc.normalise(r.candidate) != sc.normalise(r.template)
    ]
    by_scenario: dict[str, list[arms.TurnRecord]] = {}
    for record in usable:
        by_scenario.setdefault(record.scenario_id, []).append(record)
    rng = random.Random(seed)
    chosen: list[arms.TurnRecord] = []
    for scenario_id in sorted(by_scenario):
        chosen.append(rng.choice(by_scenario[scenario_id]))
    rng.shuffle(chosen)
    chosen = chosen[:pairs]

    rows: list[dict[str, object]] = []
    tally = {"T+P": 0, "T": 0, "TIE": 0, "UNCLEAR": 0}
    for record in chosen:
        tp_is_a = rng.random() < 0.5
        a = record.candidate if tp_is_a else record.template
        b = record.template if tp_is_a else record.candidate
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"A: {a}\nB: {b}"},
            ],
            "temperature": 0.0,
            "max_tokens": 90,
            "seed": seed,
        }
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = json.loads(response.read().decode())
            text = body["choices"][0]["message"]["content"].strip()
            parsed = json.loads(text[text.index("{") : text.rindex("}") + 1])
            choice = str(parsed.get("choice", "")).upper()
            why = str(parsed.get("why", ""))
        except Exception as error:  # noqa: BLE001 - a judge never blocks a run
            choice, why = "", f"judge error: {type(error).__name__}"
        if choice == "TIE":
            winner = "TIE"
        elif choice in {"A", "B"}:
            winner = "T+P" if ((choice == "A") == tp_is_a) else "T"
        else:
            winner = "UNCLEAR"
        tally[winner] += 1
        rows.append(
            {
                "scenario_id": record.scenario_id,
                "turn_index": record.turn_index,
                "tp_was": "A" if tp_is_a else "B",
                "raw_choice": choice,
                "winner": winner,
                "why": why,
                "template": record.template,
                "paraphrase": record.candidate,
            }
        )
    decided = tally["T+P"] + tally["T"]
    judged = decided + tally["TIE"]
    return {
        "report_only": True,
        "prompt": JUDGE_PROMPT.name,
        "model": model,
        "pairs_judged": len(rows),
        "tally": tally,
        "preference_TP_excluding_ties": round(tally["T+P"] / decided, 4) if decided else None,
        "preference_TP_including_ties": round(tally["T+P"] / judged, 4) if judged else None,
        "rows": rows,
    }


# ------------------------------------------------------------- references
def reference_rows() -> dict[str, object]:
    """MB-1's scripted-responder Q and hosted Q, copied and LABELLED as such."""

    if not MB1_RESULTS.exists():
        return {"error": f"missing {MB1_RESULTS}"}
    mb1 = json.loads(MB1_RESULTS.read_text(encoding="utf-8"))
    drop = {"per_scenario_grounded", "per_scenario_coverage"}

    def _row(stage: str, arm: str, note: str) -> dict[str, object]:
        row = {
            k: v
            for k, v in mb1["stages"][stage]["arms"][arm].items()
            if k not in drop
        }
        row["reference"] = True
        row["source"] = f"model-b-narration-1/results.json :: stages.{stage}.arms.{arm}"
        row["note"] = note
        return row

    return {
        "mb1_scripted_Q": _row(
            "fake",
            "Q",
            "REFERENCE ROW, not an MB-2 arm: MB-1's scripted deterministic responder "
            "over a real RealtimeLane. A harness proof — the ceiling a hand-written "
            "responder reaches on this scorer, with no language model anywhere.",
        ),
        "mb1_hosted_Q": _row(
            "hosted",
            "Q",
            "REFERENCE ROW, not an MB-2 arm: MB-1's hosted free-form narration "
            "(gpt-realtime-2.1-mini, 120 scenarios, hosted-live). The design MB-2 "
            "replaces. Point values are the pessimistic assignment of MB-1's "
            "recovered response slots; RESULTS.md there carries the admissible range.",
        ),
    }


# ------------------------------------------------------------------- output
def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _merge_into_results(key: str, payload: object, *, seed: int) -> None:
    path = FOLDER / "results.json"
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    else:
        current = {
            "run_id": RUN_ID,
            "seed": seed,
            "contract_id": ct.CONTRACT_ID,
            "scorer_id": sc.SCORER_ID,
            "corpus_id": ev.CORPUS_ID,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "corpus": ev.corpus_summary(),
            "bands": BANDS,
            "speech_acts": list(ct.SPEECH_ACTS),
            "capability_keys": list(ct.CAPABILITY_KEYS),
            "templates": ct.TEMPLATE_TABLE,
            "rejection_reason_enum": list(ct.REJECTION_REASONS),
            "hosted_calls": 0,
            "cost_usd": 0.0,
        }
    current[key] = payload
    current["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_json(path, current)


# --------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MB-2 — the receipt-typed utterance contract")
    parser.add_argument("--all", action="store_true", help="T, then T+P, then the judge")
    parser.add_argument("--arm", choices=["T", "T+P"], help="run one arm only")
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--judge-pairs", type=int, default=40)
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--threads", type=int, default=32)
    parser.add_argument("--limit", type=int, default=0, help="first N scenarios (a smoke run)")
    args = parser.parse_args(argv)

    if not args.all and not args.arm:
        parser.error("pass --all or --arm")

    corpus = ev.build_corpus()
    if args.limit:
        corpus = corpus[: args.limit]
    registry = sc.default_registry()
    host = _host_row()
    print(f"[mb2] host: {host['uptime']}")
    print(f"[mb2] gpu:  {host['nvidia_smi']}")
    _merge_into_results("host_at_start", host, seed=args.seed)
    _merge_into_results("capability_registry", registry.as_dict(), seed=args.seed)
    _merge_into_results("references", reference_rows(), seed=args.seed)

    want_t = args.all or args.arm == "T"
    want_tp = args.all or args.arm == "T+P"

    # ---------------------------------------------------------------- arm T
    if want_t:
        print("[mb2] arm T — templates only, no model")
        start = time.perf_counter()
        t_turns, _tp, _raw, records = _walk(corpus, registry, paraphraser=None)
        results, aggregate = _score(corpus, t_turns, registry, arm=arms.ARM_T, seed=args.seed)
        aggregate["checker"] = _checker_rows(records, gated=False)
        aggregate["latency_contract"] = _latency_rows(records)
        aggregate["wall_s"] = round(time.perf_counter() - start, 2)
        aggregate["tier"] = "replay"
        aggregate["mechanism"] = (
            "MB-1 trigger table + band discipline; contract templates; no model, no network"
        )
        sc.write_conv1_transcripts(results, FOLDER / "transcripts/T.jsonl")
        _write_json(FOLDER / "results/T.json", {
            "arm": arms.ARM_T,
            "aggregate": aggregate,
            "turns": [r.as_dict() for r in records],
        })
        _merge_into_results("arm_T", aggregate, seed=args.seed)
        print(json.dumps({k: v for k, v in aggregate.items()
                          if k in ("grounding_turn_rate", "coverage_rate", "invented_actions",
                                   "claims_per_turn", "robot_turns", "bars")}, indent=1))

    # -------------------------------------------------------------- arm T+P
    if want_tp:
        print("[mb2] arm T+P — local paraphrase, checker-gated")
        log = CACHE / "llama-server-8093.log"
        process, note = start_local_server(log, threads=args.threads)
        print(f"[mb2] {note}")
        if process is None:
            _merge_into_results(
                "arm_T+P",
                {"status": "UNMEASURED", "reason": note, "log": str(log)},
                seed=args.seed,
            )
            return 0
        try:
            paraphraser = Paraphraser(
                f"http://127.0.0.1:{LOCAL_PORT}", LOCAL_MODEL_NAME, seed=args.seed
            )
            start = time.perf_counter()
            _t, tp_turns, raw_turns, records = _walk(corpus, registry, paraphraser=paraphraser)
            tp_results, tp_aggregate = _score(
                corpus, tp_turns, registry, arm=arms.ARM_TP, seed=args.seed
            )
            raw_results, raw_aggregate = _score(
                corpus, raw_turns, registry, arm=arms.ARM_P_RAW, seed=args.seed
            )
            checker = _checker_rows(records, gated=True)
            tp_aggregate["checker"] = checker
            tp_aggregate["latency_contract"] = _latency_rows(records)
            tp_aggregate["wall_s"] = round(time.perf_counter() - start, 2)
            tp_aggregate["tier"] = "replay"
            tp_aggregate["model"] = LOCAL_MODEL_NAME
            tp_aggregate["server"] = f"llama-server on :{LOCAL_PORT} (CPU build)"
            tp_aggregate["prompt"] = PARAPHRASE_PROMPT.name
            tp_aggregate["temperature"] = PARAPHRASE_TEMPERATURE
            tp_aggregate["host_at_run"] = _host_row()
            raw_aggregate["report_only"] = True
            raw_aggregate["note"] = (
                "SHADOW ARM: the raw local paraphrases as they arrived, scored WITHOUT "
                "the checker. This is what the gate caught; T+P is the same turns after it."
            )
            sc.write_conv1_transcripts(tp_results, FOLDER / "transcripts/T+P.jsonl")
            sc.write_conv1_transcripts(raw_results, FOLDER / "transcripts/P-raw.jsonl")
            _write_json(FOLDER / "results/TP.json", {
                "arm": arms.ARM_TP,
                "aggregate": tp_aggregate,
                "shadow_raw": raw_aggregate,
                "turns": [r.as_dict() for r in records],
            })
            _merge_into_results("arm_T+P", tp_aggregate, seed=args.seed)
            _merge_into_results("arm_P-raw_shadow", raw_aggregate, seed=args.seed)
            print(json.dumps({"fallback_rate": checker["fallback_rate"],
                              "rejection_reason_families": checker["rejection_reason_families"],
                              "grounding": tp_aggregate["grounding_turn_rate"],
                              "coverage": tp_aggregate["coverage_rate"],
                              "raw_grounding": raw_aggregate["grounding_turn_rate"],
                              "raw_invented": raw_aggregate["invented_actions"]}, indent=1))

            # the blind flag audit, on MB-1's frozen prompt, over the SHADOW arm
            queue = FOLDER / "results/adjudication_queue.jsonl"
            key = FOLDER / "results/adjudication_key.json"
            flagged = sc.write_adjudication_queue(raw_results, queue, key, seed=args.seed)
            if flagged:
                audit = sc.adjudicate_blind(
                    queue,
                    base_url=f"http://127.0.0.1:{LOCAL_PORT}",
                    model=LOCAL_MODEL_NAME,
                    output=FOLDER / "results/adjudication-P-raw.json",
                )
                audit["prompt_file"] = str(MB1_ADJUDICATION_PROMPT)
                audit["over"] = "P-raw shadow arm (T and T+P produce no flags by construction)"
                _merge_into_results("blind_flag_audit", audit, seed=args.seed)
                print(f"[mb2] blind audit: {json.dumps(audit['tally'])}")
            else:
                _merge_into_results(
                    "blind_flag_audit",
                    {"flagged_turns": 0, "note": "no machine finding in any arm"},
                    seed=args.seed,
                )

            if not args.no_judge:
                print(f"[mb2] naturalness judge — {args.judge_pairs} blind pairs (report-only)")
                verdicts = judge_naturalness(
                    records,
                    base_url=f"http://127.0.0.1:{LOCAL_PORT}",
                    model=LOCAL_MODEL_NAME,
                    seed=args.seed,
                    pairs=args.judge_pairs,
                )
                _write_json(FOLDER / "results/naturalness.json", verdicts)
                _merge_into_results(
                    "naturalness_judge",
                    {k: v for k, v in verdicts.items() if k != "rows"},
                    seed=args.seed,
                )
                print(json.dumps(verdicts["tally"]))
        finally:
            stop_local_server()
            print("[mb2] llama-server stopped (process group)")

    _merge_into_results("host_at_end", _host_row(), seed=args.seed)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        stop_local_server()
