"""Rows G1-G4: monologue-tick latency idle, under perception, under both.

Four phases, each 300 ticks unless ``--ticks`` says otherwise:

  A_idle_8b     Ministral-8B alone on :8082
  A_idle_26b    gemma-26B alone on :8081 (the deliberative model doing the
                tick, for the sizing comparison the DESIGN asks for)
  B_perception  8B ticks while OWLv2+SigLIP-2 runs at 10 Hz
  C_contended   8B ticks while perception runs AND the 26B streams a
                512-token plan in a loop  ← the G2 row

Perception's own p95 is measured twice — alone (``P_alone``) and during the
tick phases — so G3's number can be read as a contention *cost* and not just a
level. ``nvidia-smi`` is captured at the start and end of every phase.

    .parcel/bin/python research/.../harness/run_latency.py --ticks 300
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3] / "src"))

from gold_set import gold_cases
from gpu import snapshot
from perception_load import PerceptionLoad
from tick import TickClient, percentile, summarize

FOLDER = HERE.parent
SOCKET = str(FOLDER / "h2_perception.sock")
URL_8B = "http://127.0.0.1:8082"
URL_26B = "http://127.0.0.1:8081"
PLAN_TOKENS = 512

PLAN_PROMPT = (
    "You are Parcel's deliberative planner. The owner said: 'take me to the bench by the "
    "lamp post, but stop if anyone gets close'. Write a careful step-by-step plan covering "
    "route, perception checks, safety stops, what to say to the owner at each step, and how "
    "you would recover from each failure you can foresee. Be thorough."
)


class PlanLoad:
    """A 26B generation running in a loop — the deliberative lane, busy."""

    def __init__(self, base_url: str, model: str, max_tokens: int = PLAN_TOKENS) -> None:
        self.base_url = base_url
        self.model = model
        self.max_tokens = max_tokens
        self.completions = 0
        self.errors = 0
        self.latencies_ms: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _once(self) -> None:
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": PLAN_PROMPT}],
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=180) as stream:
            stream.read()
        self.latencies_ms.append((time.perf_counter() - started) * 1000.0)
        self.completions += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._once()
            except (urllib.error.URLError, TimeoutError, OSError):
                self.errors += 1
                self._stop.wait(1.0)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="h2-plan-load", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=200.0)
            self._thread = None


def _perception_summary(load: PerceptionLoad) -> dict[str, object]:
    return {
        "frames": load.frames,
        "errors": load.errors,
        "detect_p50_ms": round(percentile(load.detect_ms, 0.50), 1),
        "detect_p95_ms": round(percentile(load.detect_ms, 0.95), 1),
        "detect_max_ms": round(max(load.detect_ms), 1) if load.detect_ms else None,
        "embed_p50_ms": round(percentile(load.embed_ms, 0.50), 1),
        "embed_p95_ms": round(percentile(load.embed_ms, 0.95), 1),
    }


def _run_ticks(client: TickClient, ticks: int, label: str) -> tuple[list, dict[str, object]]:
    cases = gold_cases()
    outcomes = []
    for index in range(ticks):
        case = cases[index % len(cases)]
        outcomes.append(client.tick(case.digest, digest_id=case.case_id))
    summary = summarize(outcomes)
    summary["phase"] = label
    return outcomes, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--perception-alone-s", type=float, default=30.0)
    parser.add_argument("--out", default=str(FOLDER / "results" / "latency.json"))
    parser.add_argument(
        "--phases",
        default="A_idle_8b,A_idle_26b,P_alone,B_perception,C_contended",
        help="comma-separated phase names to run",
    )
    args = parser.parse_args(argv)
    wanted = [name.strip() for name in args.phases.split(",") if name.strip()]

    client_8b = TickClient(URL_8B, "ministral-8b")
    client_26b = TickClient(URL_26B, "gemma-4-26b-a4b")
    report: dict[str, object] = {
        "ticks_per_phase": args.ticks,
        "plan_tokens": PLAN_TOKENS,
        "perception_socket": SOCKET,
        "phases": {},
        "gpu": [],
        "raw": {},
    }
    phases: dict[str, object] = report["phases"]  # type: ignore[assignment]
    gpu_rows: list[dict[str, object]] = report["gpu"]  # type: ignore[assignment]
    raw: dict[str, object] = report["raw"]  # type: ignore[assignment]

    cases = gold_cases()
    for _ in range(args.warmup):
        client_8b.tick(cases[0].digest, digest_id="warmup")
        client_26b.tick(cases[0].digest, digest_id="warmup")

    if "A_idle_8b" in wanted:
        gpu_rows.append(snapshot("A_idle_8b:start"))
        outcomes, summary = _run_ticks(client_8b, args.ticks, "A_idle_8b")
        gpu_rows.append(snapshot("A_idle_8b:end"))
        phases["A_idle_8b"] = summary
        raw["A_idle_8b"] = [outcome.as_dict() for outcome in outcomes]
        print(json.dumps(summary))

    if "A_idle_26b" in wanted:
        gpu_rows.append(snapshot("A_idle_26b:start"))
        outcomes, summary = _run_ticks(client_26b, args.ticks, "A_idle_26b")
        gpu_rows.append(snapshot("A_idle_26b:end"))
        phases["A_idle_26b"] = summary
        raw["A_idle_26b"] = [outcome.as_dict() for outcome in outcomes]
        print(json.dumps(summary))

    load = PerceptionLoad(SOCKET, hz=10.0)
    report["perception_health"] = load.probe()

    if "P_alone" in wanted:
        load.start()
        time.sleep(args.perception_alone_s)
        gpu_rows.append(snapshot("P_alone"))
        load.stop()
        phases["P_alone"] = _perception_summary(load)
        print(json.dumps(phases["P_alone"]))

    if "B_perception" in wanted:
        load.reset_samples()
        load.start()
        time.sleep(3.0)
        gpu_rows.append(snapshot("B_perception:start"))
        outcomes, summary = _run_ticks(client_8b, args.ticks, "B_perception")
        gpu_rows.append(snapshot("B_perception:end"))
        load.stop()
        summary["perception"] = _perception_summary(load)
        phases["B_perception"] = summary
        raw["B_perception"] = [outcome.as_dict() for outcome in outcomes]
        print(json.dumps(summary))

    if "C_contended" in wanted:
        load.reset_samples()
        plan = PlanLoad(URL_26B, "gemma-4-26b-a4b")
        load.start()
        plan.start()
        time.sleep(5.0)
        gpu_rows.append(snapshot("C_contended:start"))
        outcomes, summary = _run_ticks(client_8b, args.ticks, "C_contended")
        gpu_rows.append(snapshot("C_contended:end"))
        plan.stop()
        load.stop()
        summary["perception"] = _perception_summary(load)
        summary["plan_generations"] = plan.completions
        summary["plan_errors"] = plan.errors
        summary["plan_p50_ms"] = round(percentile(plan.latencies_ms, 0.50), 1)
        phases["C_contended"] = summary
        raw["C_contended"] = [outcome.as_dict() for outcome in outcomes]
        print(json.dumps({k: v for k, v in summary.items() if k != "perception"}))
        print(json.dumps(summary["perception"]))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
