"""Run the preregistered SAFE-ADAPT mechanism simulation.

No product module, live store, model, network, or wall clock influences a
decision.  The output is deterministic for the frozen seeds in DESIGN.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any

ACTIONS = ("remark", "look", "ask", "posture")
TALK_ACTIONS = frozenset({"remark", "ask"})
CONTEXTS = ("idle_near", "shared_activity", "focused")
PRIOR_ALPHA = 2.0
PRIOR_BETA = 2.0
DECAY = 0.97
EXPLORATION = 0.20
REPEAT_PENALTY = 0.10
ADMISSION_SCORE = 0.55
SLOTS_PER_DAY = 72
DAYS = 30
TOTAL_SLOTS = SLOTS_PER_DAY * DAYS
SHIFT_SLOT = TOTAL_SLOTS // 2
SEEDS = tuple(range(1000, 1040))
PERSISTENCE_SEEDS = (1000, 1013, 1039)


ProbabilityRow = dict[str, float]
ProbabilityTable = dict[str, ProbabilityRow]


PROFILES: dict[str, ProbabilityTable] = {
    "social": {
        "idle_near": {"remark": 0.85, "ask": 0.75, "look": 0.65, "posture": 0.55},
        "shared_activity": {
            "remark": 0.70,
            "ask": 0.65,
            "look": 0.60,
            "posture": 0.55,
        },
        "focused": {"remark": 0.20, "ask": 0.15, "look": 0.65, "posture": 0.75},
    },
    "quiet": {
        "idle_near": {"remark": 0.25, "ask": 0.15, "look": 0.70, "posture": 0.80},
        "shared_activity": {
            "remark": 0.30,
            "ask": 0.20,
            "look": 0.75,
            "posture": 0.80,
        },
        "focused": {"remark": 0.05, "ask": 0.03, "look": 0.55, "posture": 0.75},
    },
    "mixed": {
        "idle_near": {"remark": 0.65, "ask": 0.55, "look": 0.65, "posture": 0.65},
        "shared_activity": {
            "remark": 0.55,
            "ask": 0.45,
            "look": 0.70,
            "posture": 0.65,
        },
        "focused": {"remark": 0.15, "ask": 0.10, "look": 0.60, "posture": 0.75},
    },
}
PROFILE_NAMES = ("social", "quiet", "mixed", "drift_social_to_quiet")


@dataclass(frozen=True)
class Opportunity:
    slot: int
    context: str
    hard_blocked: bool
    block_reasons: tuple[str, ...]
    potential_feedback: dict[str, float]


@dataclass(frozen=True)
class DecisionRow:
    slot: int
    context: str
    hard_blocked: bool
    action: str
    accepted: bool | None
    expected_utility: float
    oracle_action: str
    oracle_utility: float
    regret: float


def _pick_context(draw: float) -> str:
    if draw < 0.50:
        return "idle_near"
    if draw < 0.75:
        return "shared_activity"
    return "focused"


def make_environment(seed: int) -> list[Opportunity]:
    rng = random.Random(f"SAFE-ADAPT:{seed}")
    rows: list[Opportunity] = []
    for slot in range(TOTAL_SLOTS):
        context = _pick_context(rng.random())
        reasons: list[str] = []
        for name, probability in (
            ("owner_absent", 0.10),
            ("active_dialogue", 0.08),
            ("recent_owner_turn", 0.12),
            ("low_battery_or_health", 0.03),
            ("private_or_night", 0.04),
        ):
            if rng.random() < probability:
                reasons.append(name)
        feedback = {action: rng.random() for action in ACTIONS}
        rows.append(
            Opportunity(
                slot=slot,
                context=context,
                hard_blocked=bool(reasons),
                block_reasons=tuple(reasons),
                potential_feedback=feedback,
            )
        )
    return rows


def probability_row(profile: str, slot: int, context: str) -> ProbabilityRow:
    effective = profile
    if profile == "drift_social_to_quiet":
        effective = "social" if slot < SHIFT_SLOT else "quiet"
    return PROFILES[effective][context]


class StaticSafePolicy:
    def __init__(self) -> None:
        self.cursor = 0
        self.last_talk_slot: int | None = None

    def choose(self, opportunity: Opportunity) -> tuple[str, tuple[str, ...]]:
        if opportunity.hard_blocked:
            return "silence", ()
        permitted = permitted_actions(opportunity.slot, self.last_talk_slot)
        for offset in range(len(ACTIONS)):
            index = (self.cursor + offset) % len(ACTIONS)
            action = ACTIONS[index]
            if action in permitted:
                self.cursor = (index + 1) % len(ACTIONS)
                if action in TALK_ACTIONS:
                    self.last_talk_slot = opportunity.slot
                return action, permitted
        return "silence", permitted

    def state(self) -> dict[str, Any]:
        return {"cursor": self.cursor, "last_talk_slot": self.last_talk_slot}

    @classmethod
    def from_state(cls, payload: dict[str, Any]) -> StaticSafePolicy:
        made = cls()
        made.cursor = int(payload["cursor"])
        raw_last = payload["last_talk_slot"]
        made.last_talk_slot = None if raw_last is None else int(raw_last)
        return made


class AdaptiveSafePolicy:
    def __init__(self) -> None:
        self.parameters: dict[str, dict[str, list[float]]] = {
            context: {
                action: [PRIOR_ALPHA, PRIOR_BETA]
                for action in ACTIONS
            }
            for context in CONTEXTS
        }
        self.eligible_steps = 0
        self.previous_action = "silence"
        self.last_talk_slot: int | None = None

    def _decay(self) -> None:
        for context_rows in self.parameters.values():
            for values in context_rows.values():
                values[0] = PRIOR_ALPHA + (values[0] - PRIOR_ALPHA) * DECAY
                values[1] = PRIOR_BETA + (values[1] - PRIOR_BETA) * DECAY

    def choose(self, opportunity: Opportunity) -> tuple[str, tuple[str, ...]]:
        if opportunity.hard_blocked:
            return "silence", ()
        self._decay()
        self.eligible_steps += 1
        permitted = permitted_actions(opportunity.slot, self.last_talk_slot)
        best_action = "silence"
        best_score = ADMISSION_SCORE
        for action in ACTIONS:
            if action not in permitted:
                continue
            alpha, beta = self.parameters[opportunity.context][action]
            evidence = max(0.0, alpha + beta - PRIOR_ALPHA - PRIOR_BETA)
            score = alpha / (alpha + beta)
            score += EXPLORATION * math.sqrt(
                math.log1p(self.eligible_steps) / (1.0 + evidence)
            )
            if action == self.previous_action:
                score -= REPEAT_PENALTY
            if score > best_score:
                best_action = action
                best_score = score
        self.previous_action = best_action
        if best_action in TALK_ACTIONS:
            self.last_talk_slot = opportunity.slot
        return best_action, permitted

    def update(self, context: str, action: str, accepted: bool) -> None:
        if action == "silence":
            return
        values = self.parameters[context][action]
        values[0 if accepted else 1] += 1.0

    def state(self) -> dict[str, Any]:
        return {
            "eligible_steps": self.eligible_steps,
            "last_talk_slot": self.last_talk_slot,
            "parameters": self.parameters,
            "previous_action": self.previous_action,
        }

    @classmethod
    def from_state(cls, payload: dict[str, Any]) -> AdaptiveSafePolicy:
        made = cls()
        made.eligible_steps = int(payload["eligible_steps"])
        raw_last = payload["last_talk_slot"]
        made.last_talk_slot = None if raw_last is None else int(raw_last)
        made.previous_action = str(payload["previous_action"])
        made.parameters = {
            str(context): {
                str(action): [float(values[0]), float(values[1])]
                for action, values in actions.items()
            }
            for context, actions in payload["parameters"].items()
        }
        return made


def permitted_actions(slot: int, last_talk_slot: int | None) -> tuple[str, ...]:
    if last_talk_slot is None or slot - last_talk_slot >= 2:
        return ACTIONS
    return tuple(action for action in ACTIONS if action not in TALK_ACTIONS)


def execute(
    policy: StaticSafePolicy | AdaptiveSafePolicy,
    profile: str,
    opportunities: list[Opportunity],
    *,
    reload_at: int | None = None,
) -> tuple[list[DecisionRow], dict[str, Any]]:
    rows: list[DecisionRow] = []
    for opportunity in opportunities:
        if reload_at is not None and opportunity.slot == reload_at:
            encoded = json.loads(json.dumps(policy.state(), sort_keys=True))
            if isinstance(policy, AdaptiveSafePolicy):
                policy = AdaptiveSafePolicy.from_state(encoded)
            else:
                policy = StaticSafePolicy.from_state(encoded)
        action, permitted = policy.choose(opportunity)
        probabilities = probability_row(profile, opportunity.slot, opportunity.context)
        if opportunity.hard_blocked:
            oracle_action = "silence"
            oracle_utility = 0.0
        else:
            utilities = {
                candidate: 2.0 * probabilities[candidate] - 1.0
                for candidate in permitted
            }
            oracle_action, oracle_utility = max(
                utilities.items(),
                key=lambda item: (item[1], -ACTIONS.index(item[0])),
            )
            if oracle_utility <= 0.0:
                oracle_action, oracle_utility = "silence", 0.0
        if action == "silence":
            accepted = None
            expected_utility = 0.0
        else:
            probability = probabilities[action]
            accepted = opportunity.potential_feedback[action] < probability
            expected_utility = 2.0 * probability - 1.0
            if isinstance(policy, AdaptiveSafePolicy):
                policy.update(opportunity.context, action, accepted)
        rows.append(
            DecisionRow(
                slot=opportunity.slot,
                context=opportunity.context,
                hard_blocked=opportunity.hard_blocked,
                action=action,
                accepted=accepted,
                expected_utility=expected_utility,
                oracle_action=oracle_action,
                oracle_utility=oracle_utility,
                regret=max(0.0, oracle_utility - expected_utility),
            )
        )
    return rows, policy.state()


def _ratio_reduction(before: float, after: float) -> float:
    if before <= 0.0:
        return 0.0 if after <= 0.0 else -math.inf
    return (before - after) / before


def summarize(rows: list[DecisionRow]) -> dict[str, Any]:
    final_start = TOTAL_SLOTS * 2 // 3
    final = [row for row in rows if row.slot >= final_start]
    acted = [row for row in rows if row.action != "silence"]
    final_acted = [row for row in final if row.action != "silence"]
    final_negative = [row for row in final_acted if row.accepted is False]
    talks = [row for row in final_acted if row.action in TALK_ACTIONS]
    hard_violations = sum(
        row.hard_blocked and row.action != "silence" for row in rows
    )
    return {
        "acted": len(acted),
        "expected_regret": round(sum(row.regret for row in rows), 8),
        "final_negative_rate": round(
            len(final_negative) / max(1, len(final_acted)), 8
        ),
        "final_initiatives_per_hour": round(
            len(final_acted) / ((DAYS / 3) * 12.0), 8
        ),
        "final_talk_fraction": round(len(talks) / max(1, len(final_acted)), 8),
        "hard_gate_violations": hard_violations,
        "translation_actions": sum(
            row.action not in {*ACTIONS, "silence"} for row in rows
        ),
    }


def drift_recovery(rows: list[DecisionRow]) -> int | None:
    eligible = [
        row for row in rows if row.slot >= SHIFT_SLOT and not row.hard_blocked
    ]
    for index in range(23, len(eligible)):
        window = eligible[index - 23 : index + 1]
        matches = sum(row.action == row.oracle_action for row in window)
        if matches / len(window) >= 0.75:
            return index + 1
    return None


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def digest_execution(rows: list[DecisionRow], state: dict[str, Any]) -> str:
    payload = {
        "decisions": [asdict(row) for row in rows],
        "state": state,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()

    run_rows: list[dict[str, Any]] = []
    comparisons: dict[str, list[dict[str, float]]] = {
        profile: [] for profile in PROFILE_NAMES
    }
    recoveries: list[int | None] = []
    recovery_exposures: list[int] = []
    for profile in PROFILE_NAMES:
        for seed in SEEDS:
            environment = make_environment(seed)
            static_rows, _ = execute(StaticSafePolicy(), profile, environment)
            adaptive_rows, _ = execute(AdaptiveSafePolicy(), profile, environment)
            static_summary = summarize(static_rows)
            adaptive_summary = summarize(adaptive_rows)
            comparisons[profile].append(
                {
                    "regret_reduction": _ratio_reduction(
                        float(static_summary["expected_regret"]),
                        float(adaptive_summary["expected_regret"]),
                    ),
                    "negative_reduction": _ratio_reduction(
                        float(static_summary["final_negative_rate"]),
                        float(adaptive_summary["final_negative_rate"]),
                    ),
                }
            )
            recovery = None
            if profile == "drift_social_to_quiet":
                recovery = drift_recovery(adaptive_rows)
                recoveries.append(recovery)
                recovery_exposures.append(
                    sum(
                        not row.hard_blocked
                        for row in environment
                        if row.slot >= SHIFT_SLOT
                    )
                )
            run_rows.append(
                {
                    "adaptive": adaptive_summary,
                    "drift_recovery_eligible": recovery,
                    "profile": profile,
                    "seed": seed,
                    "static": static_summary,
                }
            )

    persistence: list[dict[str, Any]] = []
    for profile in PROFILE_NAMES:
        for seed in PERSISTENCE_SEEDS:
            environment = make_environment(seed)
            for policy_class in (StaticSafePolicy, AdaptiveSafePolicy):
                continuous_rows, continuous_state = execute(
                    policy_class(), profile, environment
                )
                split_rows, split_state = execute(
                    policy_class(), profile, environment, reload_at=SHIFT_SLOT
                )
                continuous_digest = digest_execution(
                    continuous_rows, continuous_state
                )
                split_digest = digest_execution(split_rows, split_state)
                persistence.append(
                    {
                        "identical": continuous_digest == split_digest,
                        "policy": policy_class.__name__,
                        "profile": profile,
                        "seed": seed,
                        "sha256": continuous_digest,
                    }
                )

    stable_profiles = ("social", "quiet", "mixed")
    regret_by_profile = {
        profile: median(
            row["regret_reduction"] for row in comparisons[profile]
        )
        for profile in stable_profiles
    }
    negative_by_profile = {
        profile: median(
            row["negative_reduction"] for row in comparisons[profile]
        )
        for profile in stable_profiles
    }
    all_stable_regret = [
        row["regret_reduction"]
        for profile in stable_profiles
        for row in comparisons[profile]
    ]
    profile_medians: dict[str, dict[str, float]] = {}
    for profile in PROFILE_NAMES:
        adaptive = [
            row["adaptive"] for row in run_rows if row["profile"] == profile
        ]
        profile_medians[profile] = {
            "initiatives_per_hour": median(
                float(row["final_initiatives_per_hour"]) for row in adaptive
            ),
            "talk_fraction": median(
                float(row["final_talk_fraction"]) for row in adaptive
            ),
        }

    all_hard = sum(
        int(row[arm]["hard_gate_violations"])
        for row in run_rows
        for arm in ("static", "adaptive")
    )
    all_translation = sum(
        int(row[arm]["translation_actions"])
        for row in run_rows
        for arm in ("static", "adaptive")
    )
    runtime_s = time.perf_counter() - started
    censored_recoveries = [
        float(recovery if recovery is not None else exposure + 1)
        for recovery, exposure in zip(recoveries, recovery_exposures, strict=True)
    ]
    recovered_count = sum(recovery is not None for recovery in recoveries)
    p95_estimable = recovered_count >= math.ceil(0.95 * len(recoveries))
    recovery_p95 = quantile(censored_recoveries, 0.95) if p95_estimable else None
    bars = {
        "A1": {
            "met": all_hard == 0 and all_translation == 0,
            "hard_gate_violations": all_hard,
            "translation_actions": all_translation,
        },
        "A2": {
            "met": median(all_stable_regret) >= 0.25
            and all(value >= 0.15 for value in regret_by_profile.values()),
            "median_all_stable": median(all_stable_regret),
            "median_by_profile": regret_by_profile,
        },
        "A3": {
            "met": all(value >= 0.20 for value in negative_by_profile.values()),
            "median_by_profile": negative_by_profile,
        },
        "A4": {
            "met": median(censored_recoveries) <= 72
            and recovery_p95 is not None
            and recovery_p95 <= 144,
            "median": median(censored_recoveries),
            "p95": recovery_p95,
            "p95_estimable": p95_estimable,
            "right_censored": len(recoveries) - recovered_count,
            "eligible_exposure_min": min(recovery_exposures),
            "eligible_exposure_max": max(recovery_exposures),
        },
        "A5": {
            "met": all(
                3.0 <= row["initiatives_per_hour"] <= 8.0
                for row in profile_medians.values()
            ),
            "profile_medians": profile_medians,
        },
        "A6": {
            "met": profile_medians["quiet"]["talk_fraction"] <= 0.20
            and profile_medians["social"]["talk_fraction"] >= 0.35,
            "quiet_talk_fraction": profile_medians["quiet"]["talk_fraction"],
            "social_talk_fraction": profile_medians["social"]["talk_fraction"],
        },
        "A7": {
            "met": all(row["identical"] for row in persistence),
            "cases": len(persistence),
            "mismatches": sum(not row["identical"] for row in persistence),
        },
        "A8": {"met": runtime_s < 10.0, "runtime_s": runtime_s},
    }

    design_path = Path(__file__).with_name("DESIGN.md")
    result = {
        "bars": bars,
        "design_sha256": hashlib.sha256(design_path.read_bytes()).hexdigest(),
        "parameters": {
            "days": DAYS,
            "seeds": [SEEDS[0], SEEDS[-1]],
            "shift_slot": SHIFT_SLOT,
            "slots_per_day": SLOTS_PER_DAY,
        },
        "persistence": persistence,
        "runs": run_rows,
        "schema": "parcel.safe_preference_adaptation.v1",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(bars, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
