"""Deterministic Monte Carlo cost model for EVENT-BUDGET.

The empirical voice-turn distribution is H1's measured/modelled mini-audio
row.  The experiment makes no network call and writes one compact JSON result.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean, median, pstdev

TEXT_INPUT_PER_M = 0.60
TEXT_OUTPUT_PER_M = 2.40
DAYS = 30
MONTHS = 10_000
SEED = 20260824


@dataclass(frozen=True)
class Scenario:
    name: str
    owner_turns_per_day: int
    false_opens_per_day: int
    planner_calls_per_day: int
    consolidation_calls_per_day: int
    hosted_proactive_calls_per_day: int = 0


def text_call_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens * TEXT_INPUT_PER_M + output_tokens * TEXT_OUTPUT_PER_M
    ) / 1_000_000.0


def quantile(rows: list[float], q: float) -> float:
    ordered = sorted(rows)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def simulate_months(scenario: Scenario, voice_costs: list[float]) -> list[float]:
    rng = random.Random(f"{SEED}:{scenario.name}")
    plan_cost = text_call_usd(1_200, 300)
    consolidation_cost = text_call_usd(2_000, 400)
    proactive_cost = text_call_usd(500, 80)
    monthly_voice_turns = (
        scenario.owner_turns_per_day + scenario.false_opens_per_day
    ) * DAYS
    voice_mean = monthly_voice_turns * fmean(voice_costs)
    voice_stddev = math.sqrt(monthly_voice_turns) * pstdev(voice_costs)
    fixed_cost = DAYS * (
        scenario.planner_calls_per_day * plan_cost
        + scenario.consolidation_calls_per_day * consolidation_cost
        + scenario.hosted_proactive_calls_per_day * proactive_cost
    )
    totals: list[float] = []
    for _ in range(MONTHS):
        # A month contains at least 5,700 voice turns in these scenarios. The
        # normal approximation to the sum is therefore both reproducible and
        # materially more efficient than drawing tens of millions of samples.
        sampled_voice_cost = max(0.0, rng.gauss(voice_mean, voice_stddev))
        totals.append(sampled_voice_cost + fixed_cost)
    return totals


def summary(scenario: Scenario, totals: list[float]) -> dict[str, object]:
    return {
        "scenario": asdict(scenario),
        "monthly_usd": {
            "p50": round(median(totals), 4),
            "p95": round(quantile(totals, 0.95), 4),
            "max": round(max(totals), 4),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    prices_path = (
        args.repo
        / "research/20260823/ambient-ear-cost-ladder/results/per_turn_prices.json"
    )
    payload = json.loads(prices_path.read_text(encoding="utf-8"))
    voice_costs = [float(row["usd"]) for row in payload["mini_audio"]]
    if len(voice_costs) != 174 or any(cost <= 0.0 for cost in voice_costs):
        raise RuntimeError("H1 mini_audio distribution is missing or malformed")

    gate_false_opens = 4 * 4
    scenarios = [
        Scenario("nominal", 174, gate_false_opens, 48, 24),
        Scenario("heavy_social", 500, gate_false_opens, 48, 24),
        Scenario("hosted_proactive_stress", 174, gate_false_opens, 48, 24, 96),
        Scenario("ungated_tv", 174, round(960.61 * 4), 48, 24),
    ]
    rows = [summary(scenario, simulate_months(scenario, voice_costs)) for scenario in scenarios]

    tick_calls = 1 * 60 * 60 * 12 * DAYS
    clock_tick_monthly = tick_calls * text_call_usd(600, 100)
    result = {
        "schema": "parcel.event_budget.v1",
        "seed": SEED,
        "months": MONTHS,
        "days_per_month": DAYS,
        "voice_distribution": {
            "source": str(prices_path.relative_to(args.repo)),
            "n": len(voice_costs),
            "per_turn_usd_p50": round(median(voice_costs), 8),
            "per_turn_usd_p95": round(quantile(voice_costs, 0.95), 8),
        },
        "text_rates_per_million": {
            "input": TEXT_INPUT_PER_M,
            "output": TEXT_OUTPUT_PER_M,
            "cached_discount_assumed": False,
        },
        "scenarios": rows,
        "clock_driven_tick": {
            "calls_per_month": tick_calls,
            "input_tokens_per_call": 600,
            "output_tokens_per_call": 100,
            "monthly_usd": round(clock_tick_monthly, 4),
        },
        "continuous_local_loops_hosted_calls": 0,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
