"""Replay a local proactive-conversation opportunity gate.

The policy intentionally does not import product code and never sends a model
request.  It consumes only the frozen numeric/boolean digest fields described
in DESIGN.md.  Natural-language noticing labels are hashed as opaque dedup
keys; their words are never inspected.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NOVELTY_THRESHOLD = 0.35
OWNER_TURN_GAP_S = 15.0
ROBOT_SPEECH_COOLDOWN_S = 90.0
NOTICING_MAX_AGE_S = 30.0
SUBJECT_DEDUP_S = 600.0
TIMER_GAP_S = 360.0
USEFUL_KINDS = frozenset({"remark", "ask"})


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _age_is_under(value: object, threshold: float) -> bool:
    return value is not None and float(value) < threshold


def _noticings(digest: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in digest.get("noticings", []) if isinstance(row, dict)]


def _fresh_noticings(digest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in _noticings(digest)
        if float(row.get("age_s", math.inf)) <= NOTICING_MAX_AGE_S
    ]


def _max_novelty(digest: dict[str, Any], *, fresh_only: bool = False) -> float:
    rows = _fresh_noticings(digest) if fresh_only else _noticings(digest)
    return max((_clamp(float(row.get("novelty", 0.0))) for row in rows), default=0.0)


def _drive_peak(digest: dict[str, Any]) -> float:
    eligible = {"curiosity", "social", "vigilance"}
    return max(
        (
            _clamp(float(row.get("level", 0.0)))
            for row in digest.get("drives", [])
            if isinstance(row, dict) and str(row.get("name", "")) in eligible
        ),
        default=0.0,
    )


def _subject_key(digest: dict[str, Any]) -> str:
    """Return an opaque key; policy code never interprets label words."""

    rows = _fresh_noticings(digest)
    if not rows:
        return "none"
    row = max(rows, key=lambda item: float(item.get("novelty", 0.0)))
    raw = str(row.get("label", "")).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def hard_prohibitions(digest: dict[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    if not bool(digest.get("owner_present", False)):
        reasons.append("verified_owner_absent")
    if bool(digest.get("owner_speaking", False)):
        reasons.append("owner_speaking")
    if bool(digest.get("lane_busy", False)):
        reasons.append("lane_busy")
    if bool(digest.get("quiet_hours", False)):
        reasons.append("quiet_hours")
    if bool(digest.get("emergency_stopped", False)):
        reasons.append("estop_latched")
    if _age_is_under(digest.get("last_owner_turn_age_s"), OWNER_TURN_GAP_S):
        reasons.append("owner_turn_gap")
    if _age_is_under(digest.get("last_robot_utterance_age_s"), ROBOT_SPEECH_COOLDOWN_S):
        reasons.append("robot_speech_cooldown")
    notices = _noticings(digest)
    if not notices:
        reasons.append("no_noticing")
    elif not _fresh_noticings(digest):
        reasons.append("noticing_stale")
    if any("remarked" in str(action).casefold() for action in digest.get("recent_actions", [])):
        reasons.append("recent_remark")
    return tuple(reasons)


@dataclass(frozen=True)
class Decision:
    admitted: bool
    reason: str
    score: float
    subject_key: str
    prohibitions: tuple[str, ...] = ()

    def compact(self) -> dict[str, object]:
        return {
            "a": self.admitted,
            "r": self.reason,
            "s": round(self.score, 6),
            "k": self.subject_key,
            "p": list(self.prohibitions),
        }


class OpportunityGate:
    """Stateful local gate with no text generation and no I/O."""

    def __init__(self) -> None:
        self._last_admission_at: float | None = None
        self._subject_admitted_at: dict[str, float] = {}

    def decide(
        self,
        digest: dict[str, Any],
        *,
        at_s: float | None = None,
        commit: bool = True,
    ) -> Decision:
        now = float(digest.get("at_s", 0.0) if at_s is None else at_s)
        subject = _subject_key(digest)
        prohibitions = hard_prohibitions(digest)
        if prohibitions:
            return Decision(False, prohibitions[0], 0.0, subject, prohibitions)

        if (
            self._last_admission_at is not None
            and now - self._last_admission_at < ROBOT_SPEECH_COOLDOWN_S
        ):
            return Decision(False, "internal_speech_cooldown", 0.0, subject)
        subject_at = self._subject_admitted_at.get(subject)
        if subject_at is not None and now - subject_at < SUBJECT_DEDUP_S:
            return Decision(False, "subject_dedup", 0.0, subject)

        novelty = _max_novelty(digest, fresh_only=True)
        score = novelty * (0.75 + 0.25 * _drive_peak(digest))
        if score < NOVELTY_THRESHOLD:
            return Decision(False, "score_below_threshold", score, subject)
        if commit:
            self._last_admission_at = now
            self._subject_admitted_at[subject] = now
        return Decision(True, "opportunity_admitted", score, subject)


def timer_only(digest: dict[str, Any]) -> Decision:
    age = digest.get("last_robot_utterance_age_s")
    admitted = age is None or float(age) >= TIMER_GAP_S
    return Decision(admitted, "timer_due" if admitted else "timer_holding", 0.0, "none")


def naive_novelty(digest: dict[str, Any]) -> Decision:
    score = _max_novelty(digest)
    admitted = score >= NOVELTY_THRESHOLD
    return Decision(admitted, "novelty_due" if admitted else "low_novelty", score, "none")


def context_timer(digest: dict[str, Any]) -> Decision:
    owner_age = digest.get("last_owner_turn_age_s")
    robot_age = digest.get("last_robot_utterance_age_s")
    admitted = (
        bool(digest.get("owner_present", False))
        and not bool(digest.get("lane_busy", False))
        and not bool(digest.get("quiet_hours", False))
        and (owner_age is None or float(owner_age) >= 90.0)
        and (robot_age is None or float(robot_age) >= TIMER_GAP_S)
    )
    return Decision(admitted, "context_timer_due" if admitted else "context_timer_holding", 0.0, "none")


def _metrics(cases: list[dict[str, Any]], decisions: list[Decision]) -> dict[str, object]:
    tp = fp = tn = fn = 0
    for case, decision in zip(cases, decisions, strict=True):
        useful = str(case["gold_kind"]) in USEFUL_KINDS
        if useful and decision.admitted:
            tp += 1
        elif useful:
            fn += 1
        elif decision.admitted:
            fp += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "cases": len(cases),
        "useful": tp + fn,
        "calls": tp + fp,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
    }


def _counterfactual_refuters(cases: list[dict[str, Any]]) -> dict[str, object]:
    source = [case for case in cases if case["gold_kind"] in USEFUL_KINDS and not case["arguable"]][
        :6
    ]
    mutations = (
        ("owner_absent", lambda row: row.__setitem__("owner_present", False)),
        ("owner_speaking", lambda row: row.__setitem__("owner_speaking", True)),
        ("lane_busy", lambda row: row.__setitem__("lane_busy", True)),
        ("quiet_hours", lambda row: row.__setitem__("quiet_hours", True)),
        ("estop", lambda row: row.__setitem__("emergency_stopped", True)),
        ("owner_turn_gap", lambda row: row.__setitem__("last_owner_turn_age_s", 1.0)),
        ("robot_cooldown", lambda row: row.__setitem__("last_robot_utterance_age_s", 1.0)),
        ("recent_remark", lambda row: row.setdefault("recent_actions", []).append("remarked on it")),
    )
    rows: list[dict[str, object]] = []
    for case in source:
        for name, mutate in mutations:
            digest = copy.deepcopy(case["digest"])
            mutate(digest)
            decision = OpportunityGate().decide(digest, commit=False)
            rows.append(
                {
                    "source": case["case_id"],
                    "mutation": name,
                    "admitted": decision.admitted,
                    "reason": decision.reason,
                }
            )
    admitted = sum(bool(row["admitted"]) for row in rows)
    return {
        "authored": True,
        "cases": len(rows),
        "admitted": admitted,
        "all_rejected": admitted == 0,
        "failures": [row for row in rows if row["admitted"]],
    }


def _stateful_sequence(cases: list[dict[str, Any]]) -> dict[str, object]:
    base_case = next(
        case for case in cases if case["gold_kind"] in USEFUL_KINDS and not case["arguable"]
    )
    base = copy.deepcopy(base_case["digest"])
    distinct = copy.deepcopy(base)
    distinct["noticings"][0]["label"] = "opaque-distinct-subject"
    gate = OpportunityGate()
    inputs = (
        ("subject@0", base, 0.0),
        ("subject@30", base, 30.0),
        ("subject@90", base, 90.0),
        ("subject@120", base, 120.0),
        ("distinct@120", distinct, 120.0),
        ("subject@601", base, 601.0),
    )
    expected = (True, False, False, False, True, True)
    rows: list[dict[str, object]] = []
    for (name, digest, at_s), want in zip(inputs, expected, strict=True):
        decision = gate.decide(digest, at_s=at_s)
        rows.append(
            {
                "step": name,
                "admitted": decision.admitted,
                "expected": want,
                "reason": decision.reason,
            }
        )
    return {
        "authored": True,
        "exact": all(row["admitted"] == row["expected"] for row in rows),
        "premature_repeats": sum(
            bool(row["admitted"])
            for row in rows
            if row["step"] in {"subject@30", "subject@90", "subject@120"}
        ),
        "rows": rows,
    }


def _exploratory_sensor_refuters(cases: list[dict[str, Any]]) -> dict[str, object]:
    """Post-registration dependency probes; they do not affect acceptance."""

    mutations = (
        (
            "owner_false_positive",
            lambda digest: not bool(digest.get("owner_present", False)),
            lambda digest: digest.__setitem__("owner_present", True),
        ),
        (
            "owner_speaking_false_negative",
            lambda digest: bool(digest.get("owner_speaking", False)),
            lambda digest: digest.__setitem__("owner_speaking", False),
        ),
        (
            "lane_busy_false_negative",
            lambda digest: bool(digest.get("lane_busy", False)),
            lambda digest: digest.__setitem__("lane_busy", False),
        ),
        (
            "quiet_hours_false_negative",
            lambda digest: bool(digest.get("quiet_hours", False)),
            lambda digest: digest.__setitem__("quiet_hours", False),
        ),
    )
    result: dict[str, object] = {"post_registered": True}
    for name, applies, mutate in mutations:
        rows: list[dict[str, object]] = []
        for case in cases:
            digest = copy.deepcopy(case["digest"])
            if not applies(digest):
                continue
            mutate(digest)
            decision = OpportunityGate().decide(digest, commit=False)
            rows.append(
                {
                    "id": case["case_id"],
                    "gold": case["gold_kind"],
                    "admitted": decision.admitted,
                    "reason": decision.reason,
                }
            )
        result[name] = {
            "mutated_cases": len(rows),
            "admitted": sum(bool(row["admitted"]) for row in rows),
            "admitted_ids": [row["id"] for row in rows if row["admitted"]],
        }
    return result


def _exploratory_contract_refuters(cases: list[dict[str, Any]]) -> dict[str, object]:
    """Post-registration malformed-input probes; never part of O1--O8."""

    source = next(
        case
        for case in cases
        if case["gold_kind"] in USEFUL_KINDS and not case["arguable"]
    )
    mutations: tuple[tuple[str, Any], ...] = (
        ("missing_owner_speaking", lambda row: row.pop("owner_speaking", None)),
        ("missing_lane_busy", lambda row: row.pop("lane_busy", None)),
        ("missing_quiet_hours", lambda row: row.pop("quiet_hours", None)),
        ("missing_estop", lambda row: row.pop("emergency_stopped", None)),
        (
            "missing_owner_turn_age",
            lambda row: row.pop("last_owner_turn_age_s", None),
        ),
        (
            "missing_robot_utterance_age",
            lambda row: row.pop("last_robot_utterance_age_s", None),
        ),
        ("string_false_owner_present", lambda row: row.__setitem__("owner_present", "false")),
        (
            "nan_owner_turn_age",
            lambda row: row.__setitem__("last_owner_turn_age_s", math.nan),
        ),
        (
            "nan_robot_utterance_age",
            lambda row: row.__setitem__("last_robot_utterance_age_s", math.nan),
        ),
    )
    rows: list[dict[str, object]] = []
    for name, mutate in mutations:
        digest = copy.deepcopy(source["digest"])
        mutate(digest)
        decision = OpportunityGate().decide(digest, commit=False)
        rows.append(
            {
                "mutation": name,
                "admitted": decision.admitted,
                "reason": decision.reason,
            }
        )
    return {
        "post_registered": True,
        "expected": "every malformed or incomplete candidate fails closed",
        "cases": len(rows),
        "admitted": sum(bool(row["admitted"]) for row in rows),
        "all_failed_closed": not any(bool(row["admitted"]) for row in rows),
        "rows": rows,
    }


def _exploratory_ablation(cases: list[dict[str, Any]]) -> dict[str, object]:
    hard_only = [
        Decision(
            admitted=not bool(hard_prohibitions(case["digest"])),
            reason="hard_clear" if not hard_prohibitions(case["digest"]) else "hard_refusal",
            score=0.0,
            subject_key="none",
        )
        for case in cases
    ]
    unarguable = [index for index, case in enumerate(cases) if not case["arguable"]]
    metric = _metrics(
        [cases[index] for index in unarguable],
        [hard_only[index] for index in unarguable],
    )
    scored_rejections: list[float] = []
    scored_admissions: list[float] = []
    for case in cases:
        digest = case["digest"]
        if hard_prohibitions(digest):
            continue
        score = _max_novelty(digest, fresh_only=True) * (0.75 + 0.25 * _drive_peak(digest))
        if OpportunityGate().decide(digest, commit=False).admitted:
            scored_admissions.append(score)
        else:
            scored_rejections.append(score)
    return {
        "post_registered": True,
        "hard_gates_without_score_unarguable": metric,
        "minimum_admitted_score": min(scored_admissions),
        "maximum_rejected_score_after_hard_gates": max(scored_rejections),
        "score_separation_margin": min(scored_admissions) - max(scored_rejections),
    }


def _decision_sha(cases: list[dict[str, Any]]) -> str:
    rows = [OpportunityGate().decide(case["digest"], commit=False).compact() for case in cases]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _latency(cases: list[dict[str, Any]], count: int) -> dict[str, object]:
    gate = OpportunityGate()
    samples_ns: list[int] = []
    for index in range(count):
        digest = cases[index % len(cases)]["digest"]
        started = time.perf_counter_ns()
        gate.decide(digest, commit=False)
        samples_ns.append(time.perf_counter_ns() - started)
    ordered = sorted(samples_ns)

    def percentile(fraction: float) -> float:
        position = math.ceil(fraction * len(ordered)) - 1
        return ordered[max(0, position)] / 1_000_000.0

    return {
        "decisions": count,
        "median_ms": statistics.median(ordered) / 1_000_000.0,
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "max_ms": max(ordered) / 1_000_000.0,
    }


def _h3_trace_summary(path: Path) -> dict[str, object]:
    owner_turns: list[float] = []
    remarks: list[float] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            at_s = float(row["t"])
            if "owner_turn" in row.get("ev", []):
                owner_turns.append(at_s)
            proposal = row.get("p")
            if isinstance(proposal, dict) and proposal.get("kind") == "remark":
                remarks.append(at_s)
    prior_gaps = [
        at_s - max(turn for turn in owner_turns if turn <= at_s)
        for at_s in remarks
        if any(turn <= at_s for turn in owner_turns)
    ]
    return {
        "owner_turns": len(owner_turns),
        "remark_proposals": len(remarks),
        "remark_at_s": remarks,
        "prior_owner_turn_gap_s": prior_gaps,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(repo: Path, latency_decisions: int) -> dict[str, object]:
    h2_path = repo / "research/20260823/local-cognition-gpu/results/gold_set.json"
    h1_path = repo / "research/20260823/ambient-ear-cost-ladder/results/p0_hosted_always.json"
    h3_path = repo / "research/20260823/drives-and-initiative/results/rows.json"
    h3_trace_path = (
        repo / "research/20260823/drives-and-initiative/logs/ticks_radius6_seed1.jsonl.gz"
    )
    h2 = json.loads(h2_path.read_text())
    cases: list[dict[str, Any]] = h2["cases"]
    h1 = json.loads(h1_path.read_text())
    h3 = json.loads(h3_path.read_text())

    decisions = {
        "timer_only": [timer_only(case["digest"]) for case in cases],
        "naive_novelty": [naive_novelty(case["digest"]) for case in cases],
        "context_timer": [context_timer(case["digest"]) for case in cases],
        "opportunity_gate": [
            OpportunityGate().decide(case["digest"], commit=False) for case in cases
        ],
    }
    unarguable_indexes = [index for index, case in enumerate(cases) if not case["arguable"]]
    all_metrics = {name: _metrics(cases, rows) for name, rows in decisions.items()}
    headline_metrics = {
        name: _metrics(
            [cases[index] for index in unarguable_indexes],
            [rows[index] for index in unarguable_indexes],
        )
        for name, rows in decisions.items()
    }

    proposed = decisions["opportunity_gate"]
    prohibited_admissions = [
        case["case_id"]
        for case, decision in zip(cases, proposed, strict=True)
        if decision.admitted and hard_prohibitions(case["digest"])
    ]
    naive_calls = int(headline_metrics["naive_novelty"]["calls"])
    proposed_calls = int(headline_metrics["opportunity_gate"]["calls"])
    call_reduction = (naive_calls - proposed_calls) / naive_calls if naive_calls else 0.0

    turn_cost = float(h1["models"]["mini"]["median_turn_usd_audio_modelled"])
    h3_d1 = h3["rows"]["D1_initiations_per_hour_headline"]
    h3_rate = float(h3_d1["mean"])
    month_candidates = h3_rate * 12.0 * 30.0
    costs: dict[str, dict[str, float]] = {}
    for name, metrics in headline_metrics.items():
        calls = int(metrics["calls"])
        admission_fraction = calls / int(metrics["cases"])
        costs[name] = {
            "corpus_pass_usd": calls * turn_cost,
            "per_1000_candidates_usd": admission_fraction * 1000.0 * turn_cost,
            "h3_normalized_month_usd": month_candidates * admission_fraction * turn_cost,
        }

    refuters = _counterfactual_refuters(cases)
    sequence = _stateful_sequence(cases)
    sensor_refuters = _exploratory_sensor_refuters(cases)
    contract_refuters = _exploratory_contract_refuters(cases)
    hashes = [_decision_sha(cases) for _ in range(10)]
    latency = _latency(cases, latency_decisions)
    headline = headline_metrics["opportunity_gate"]
    criteria = {
        "O1_zero_prohibited": not prohibited_admissions and refuters["all_rejected"],
        "O2_recall_ge_0_80": float(headline["recall"]) >= 0.80,
        "O3_precision_ge_0_80": float(headline["precision"]) >= 0.80,
        "O4_call_reduction_ge_0_50": call_reduction >= 0.50
        and float(headline["recall"]) >= 0.80,
        "O5_stateful_exact": sequence["exact"] and sequence["premature_repeats"] == 0,
        "O6_deterministic": len(set(hashes)) == 1,
        "O7_p95_le_1ms": float(latency["p95_ms"]) <= 1.0,
        "O8_cost_reported": True,
    }

    compact_cases = []
    for case, rows in zip(cases, zip(*decisions.values(), strict=True), strict=True):
        compact_cases.append(
            {
                "id": case["case_id"],
                "gold": case["gold_kind"],
                "arguable": case["arguable"],
                "arms": {
                    name: decision.admitted
                    for name, decision in zip(decisions, rows, strict=True)
                },
                "opportunity": rows[-1].compact(),
            }
        )

    return {
        "schema": "parcel.research.conversation-opportunity.v1",
        "evidence_tier": "preserved-authored-desktop-replay",
        "parameters": {
            "novelty_threshold": NOVELTY_THRESHOLD,
            "owner_turn_gap_s": OWNER_TURN_GAP_S,
            "robot_speech_cooldown_s": ROBOT_SPEECH_COOLDOWN_S,
            "noticing_max_age_s": NOTICING_MAX_AGE_S,
            "subject_dedup_s": SUBJECT_DEDUP_S,
            "timer_gap_s": TIMER_GAP_S,
            "h1_median_audio_turn_usd": turn_cost,
        },
        "provenance": {
            "h2_path": str(h2_path.relative_to(repo)),
            "h2_sha256": _sha256(h2_path),
            "h2_cases": len(cases),
            "h2_arguable": int(h2["arguable_count"]),
            "h1_path": str(h1_path.relative_to(repo)),
            "h3_path": str(h3_path.relative_to(repo)),
            "h3_trace_path": str(h3_trace_path.relative_to(repo)),
        },
        "metrics_unarguable_headline": headline_metrics,
        "metrics_all_cases": all_metrics,
        "prohibited_admissions": prohibited_admissions,
        "call_reduction_vs_naive": call_reduction,
        "costs": costs,
        "h3_context": {
            "initiative_candidates_per_hour": h3_rate,
            "remarks_across_three_headline_hours": int(h3_d1["by_kind_total"]["remark"]),
            "normalized_candidates_per_month": month_candidates,
            "preserved_trace": _h3_trace_summary(h3_trace_path),
        },
        "authored_counterfactual_refuters": refuters,
        "authored_stateful_sequence": sequence,
        "exploratory_sensor_refuters": sensor_refuters,
        "exploratory_contract_refuters": contract_refuters,
        "exploratory_ablation": _exploratory_ablation(cases),
        "determinism": {"repeats": 10, "unique_hashes": sorted(set(hashes)), "all_equal": len(set(hashes)) == 1},
        "latency": latency,
        "criteria": criteria,
        "overall_pass": all(criteria.values()),
        "cases": compact_cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("results.json"))
    parser.add_argument("--latency-decisions", type=int, default=120_000)
    args = parser.parse_args()
    result = run(args.repo.resolve(), args.latency_decisions)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"criteria": result["criteria"], "overall_pass": result["overall_pass"]}, indent=2))


if __name__ == "__main__":
    main()
