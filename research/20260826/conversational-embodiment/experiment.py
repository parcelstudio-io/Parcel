#!/usr/bin/env python3
"""Deterministic authored replay for conversational embodiment architecture.

This script does not parse the illustrative utterances and does not call a
model, simulator, microphone, speaker, network service, or robot. It imports
the current Parcel configuration/prompt/tool components to build the effective
capability surface, then evaluates authored semantic frames against research
policies and deliberately simple comparison proxies.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "conversational-embodiment-results-v1"
TRAVEL_ACTIONS = frozenset(
    {
        "navigate_to",
        "follow_owner",
        "circle_owner",
        "roam",
        "search_owner",
        "approach_owner",
        "climb_stairs",
    }
)

PROACTIVE_BOOL_FIELDS = frozenset(
    {
        "owner_verified",
        "proactive_consent",
        "owner_speaking",
        "lane_busy",
        "quiet_hours",
        "estop",
        "private_zone",
        "nearby_non_owner",
    }
)
PROACTIVE_REAL_FIELDS = frozenset(
    {
        "novelty",
        "confidence",
        "owner_turn_age_s",
        "robot_utterance_age_s",
        "evidence_age_s",
        "last_subject_age_s",
    }
)
PROACTIVE_TEXT_FIELDS = frozenset(
    {"version", "event_id", "subject_id", "event_class"}
)
PROACTIVE_REQUIRED = (
    PROACTIVE_BOOL_FIELDS
    | PROACTIVE_REAL_FIELDS
    | PROACTIVE_TEXT_FIELDS
    | {"source_epoch"}
)

RATES_USD_PER_MILLION = {
    "text_input": 4.0,
    "text_output": 24.0,
    "audio_input": 32.0,
    "audio_output": 64.0,
}


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _percentile(values: Sequence[float], proportion: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * proportion) - 1)
    return ordered[index]


def _exact_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    correct = sum(row["predicted"] == row["gold"] for row in rows)
    return {
        "cases": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows) if rows else 0.0,
    }


def _classification_metrics(gold: Sequence[str], predicted: Sequence[str]) -> dict[str, Any]:
    true_positive = sum(g == "ADMIT" and p == "ADMIT" for g, p in zip(gold, predicted))
    false_positive = sum(g != "ADMIT" and p == "ADMIT" for g, p in zip(gold, predicted))
    false_negative = sum(g == "ADMIT" and p != "ADMIT" for g, p in zip(gold, predicted))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
    }


def load_repo_surface(repo: Path) -> dict[str, Any]:
    sys.path.insert(0, str(repo / "src"))
    from parcel_robot.config import ConfigStore
    from parcel_robot.prompting.loader import PromptLibrary
    from parcel_robot.realtime.prompting import (
        DI_VERSION,
        SI_VERSION,
        DeveloperFlags,
        render_developer_instruction,
        render_system_instruction,
    )
    from parcel_robot.realtime.tool_broker import build_tool_specs

    store = ConfigStore(repo / "configs/robot.yaml", profile="go2_edu_plus")
    agent = store.agent_config()
    brain = agent["brain"]
    configured_emotes = tuple(str(name) for name in brain["emotes"])
    configured_poses = tuple(sorted(store.poses()))
    specs = build_tool_specs(gestures=configured_emotes, poses=configured_poses)
    tool_names = tuple(spec["name"] for spec in specs)

    gesture_spec = next(spec for spec in specs if spec["name"] == "play_gesture")
    gesture_names = tuple(
        gesture_spec["parameters"]["properties"]["name"].get("enum", ())
    )
    pose_spec = next(spec for spec in specs if spec["name"] == "set_pose")
    pose_names = tuple(pose_spec["parameters"]["properties"]["name"].get("enum", ()))

    library = PromptLibrary(repo / "prompts")
    personas = library.list_personalities()
    affect_rows = []
    for persona in personas:
        for affect, action in sorted(persona.affect_actions.items()):
            affect_rows.append(
                {
                    "personality": persona.id,
                    "affect": affect,
                    "action": action,
                    "in_effective_gesture_enum": action in gesture_names,
                }
            )

    system = render_system_instruction(
        profile_id=str(agent["personality"]),
        library=library,
    )
    developer = render_developer_instruction(DeveloperFlags())

    available_actions = {
        *(f"gesture:{name}" for name in gesture_names),
        *(f"pose:{name}" for name in pose_names),
        *(name for name in tool_names if name in TRAVEL_ACTIONS),
    }
    present_affect = sum(row["in_effective_gesture_enum"] for row in affect_rows)
    return {
        "profile": "go2_edu_plus",
        "configured_emotes": list(configured_emotes),
        "configured_poses": list(configured_poses),
        "realtime_tool_names": list(tool_names),
        "gesture_enum": list(gesture_names),
        "pose_enum": list(pose_names),
        "available_actions": sorted(available_actions),
        "personality_affect_closure": {
            "rows": affect_rows,
            "mapped_actions": len(affect_rows),
            "present": present_affect,
            "absent": len(affect_rows) - present_affect,
            "closure_rate": present_affect / len(affect_rows),
        },
        "prompt_plane": {
            "si_version": SI_VERSION,
            "si_digest": system.digest,
            "di_version": DI_VERSION,
            "di_default_keys": sorted(DeveloperFlags().as_dict()),
            "si_mentions_companion_friend": "companion quadruped friend" in system.text,
            "si_mentions_exact_capability_envelope": "EmbodimentEnvelope" in system.text,
            "di_mentions_action_receipt": "action_receipt" in developer.text,
        },
    }


def proposed_embodiment(
    case: Mapping[str, Any], available_actions: frozenset[str]
) -> dict[str, str | None]:
    action = case["candidate_action"]
    if action is None:
        return {"decision": "SPEECH_ONLY", "action": None}
    action = str(action)
    if case["hypothetical"] or case["negated"] or case["quoted"]:
        return {"decision": "SPEECH_ONLY", "action": None}
    if case["source"] == "system" and action in TRAVEL_ACTIONS:
        return {"decision": "REFUSE", "action": None}
    if action not in available_actions:
        decision = "REFUSE" if case["explicit"] else "SPEECH_ONLY"
        return {"decision": decision, "action": None}
    if action in TRAVEL_ACTIONS and not case["explicit"]:
        return {"decision": "REFUSE", "action": None}
    if action in TRAVEL_ACTIONS and not case["owner_verified"]:
        return {"decision": "CLARIFY", "action": None}
    if not case["affordance_ready"]:
        return {"decision": "REFUSE", "action": None}
    if not case["body_idle"]:
        return {"decision": "DEFER", "action": action}
    if not case["explicit"] and not case["social_motion_allowed"]:
        return {"decision": "SPEECH_ONLY", "action": None}
    return {"decision": "EXECUTE", "action": action}


def persona_only_proxy(case: Mapping[str, Any]) -> dict[str, str | None]:
    action = case["candidate_action"]
    if action is None:
        return {"decision": "SPEECH_ONLY", "action": None}
    return {"decision": "EXECUTE", "action": str(action)}


def run_embodiment(
    cases: Sequence[Mapping[str, Any]], available_actions: frozenset[str]
) -> dict[str, Any]:
    proposed_rows = []
    proxy_rows = []
    for case in cases:
        gold = case["gold"]
        proposed = proposed_embodiment(case, available_actions)
        proxy = persona_only_proxy(case)
        proposed_rows.append(
            {"id": case["id"], "gold": gold, "predicted": proposed}
        )
        proxy_rows.append({"id": case["id"], "gold": gold, "predicted": proxy})

    def arm(rows: list[dict[str, Any]]) -> dict[str, Any]:
        unavailable = sum(
            row["predicted"]["decision"] == "EXECUTE"
            and row["predicted"]["action"] not in available_actions
            for row in rows
        )
        unsafe = sum(
            row["predicted"]["decision"] == "EXECUTE"
            and row["gold"]["decision"] != "EXECUTE"
            for row in rows
        )
        safe_explicit = [
            row
            for row, case in zip(rows, cases)
            if case["explicit"] and row["gold"]["decision"] == "EXECUTE"
        ]
        recalled = sum(row["predicted"] == row["gold"] for row in safe_explicit)
        return {
            **_exact_metrics(rows),
            "unavailable_executions": unavailable,
            "unsafe_executions": unsafe,
            "safe_explicit_cases": len(safe_explicit),
            "safe_explicit_recall": recalled / len(safe_explicit),
            "rows": rows,
        }

    proposed = arm(proposed_rows)
    proxy = arm(proxy_rows)
    passed = (
        proposed["unavailable_executions"] == 0
        and proposed["unsafe_executions"] == 0
        and proposed["safe_explicit_recall"] >= 0.90
        and proposed["accuracy"] >= 0.90
    )
    return {
        "evidence_note": (
            "Authored pre-parsed semantic frames; no language model or NLU was evaluated."
        ),
        "proposed_envelope": proposed,
        "persona_only_proxy": proxy,
        "bars": {
            "unavailable_executions_eq_0": proposed["unavailable_executions"] == 0,
            "unsafe_executions_eq_0": proposed["unsafe_executions"] == 0,
            "safe_explicit_recall_ge_0_90": proposed["safe_explicit_recall"] >= 0.90,
            "exact_accuracy_ge_0_90": proposed["accuracy"] >= 0.90,
        },
        "passed": passed,
    }


def proposed_dialogue(case: Mapping[str, Any]) -> str:
    kind = case["kind"]
    state = case["state"]
    event = case["event"]
    pending = state.get("pending")
    if kind == "repeat":
        if pending is not None:
            return f"DEFER:{pending['action']}"
        completed = state.get("last_completed")
        return f"EXECUTE:{completed}" if completed else "CLARIFY"
    if kind == "result":
        if pending is None or pending["action"] != event["action"]:
            return "IGNORE_STALE"
        status = event["status"]
        if status == "started":
            return f"STARTED:{event['action']}"
        if status == "completed":
            return f"COMPLETED:{event['action']}"
        if status == "rejected":
            return f"NOT_STARTED:{event['action']}"
        return "IGNORE_STALE"
    if kind == "correction_hold":
        return f"CANCEL_AND_HOLD:{pending['action']}" if pending else "HOLD"
    if kind == "status":
        if pending is not None:
            return f"STARTED:{pending['action']}"
        completed = state.get("last_completed")
        return f"COMPLETED:{completed}" if completed else "IDLE"
    if kind == "memory":
        key = event["key"]
        query_at = event["query_at"]
        candidates = [
            record
            for record in state["records"]
            if record["key"] == key
            and record["source"] == "owner"
            and record["valid_from"] <= query_at
            and (record["valid_to"] is None or query_at < record["valid_to"])
        ]
        if not candidates:
            return "ABSTAIN"
        latest = max(candidates, key=lambda record: record["turn"])
        return "ABSTAIN" if latest["revoked"] else f"FACT:{latest['value']}"
    raise ValueError(f"unknown dialogue case kind: {kind}")


def tail_only_proxy(case: Mapping[str, Any]) -> str:
    kind = case["kind"]
    state = case["state"]
    event = case["event"]
    if kind == "repeat":
        proposed = state.get("last_proposed")
        return f"EXECUTE:{proposed}" if proposed else "CLARIFY"
    if kind == "result":
        if event["status"] == "rejected":
            return f"NOT_STARTED:{event['action']}"
        return f"COMPLETED:{event['action']}"
    if kind == "correction_hold":
        return "HOLD"
    if kind == "status":
        proposed = state.get("last_proposed")
        return f"COMPLETED:{proposed}" if proposed else "IDLE"
    if kind == "memory":
        for record in state["records"]:
            if record["key"] == event["key"]:
                return f"FACT:{record['value']}"
        return "ABSTAIN"
    raise ValueError(f"unknown dialogue case kind: {kind}")


def run_dialogue(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    proposed_rows = []
    proxy_rows = []
    for case in cases:
        proposed_rows.append(
            {
                "id": case["id"],
                "gold": case["gold"],
                "predicted": proposed_dialogue(case),
            }
        )
        proxy_rows.append(
            {
                "id": case["id"],
                "gold": case["gold"],
                "predicted": tail_only_proxy(case),
            }
        )

    def arm(rows: list[dict[str, Any]]) -> dict[str, Any]:
        false_completion = sum(
            row["predicted"].startswith("COMPLETED:")
            and not row["gold"].startswith("COMPLETED:")
            for row in rows
        )
        unsupported_memory = sum(
            row["predicted"].startswith("FACT:") and row["gold"] == "ABSTAIN"
            for row in rows
        )
        return {
            **_exact_metrics(rows),
            "false_completion": false_completion,
            "unsupported_memory_answers": unsupported_memory,
            "rows": rows,
        }

    proposed = arm(proposed_rows)
    proxy = arm(proxy_rows)
    passed = (
        proposed["accuracy"] >= 0.90
        and proposed["false_completion"] == 0
        and proposed["unsupported_memory_answers"] == 0
    )
    return {
        "evidence_note": (
            "Authored state snapshots and deterministic outputs; no model memory "
            "extraction, retrieval ranking, or natural-language coreference was evaluated."
        ),
        "proposed_state_graph": proposed,
        "tail_only_proxy": proxy,
        "bars": {
            "exact_accuracy_ge_0_90": proposed["accuracy"] >= 0.90,
            "false_completion_eq_0": proposed["false_completion"] == 0,
            "unsupported_memory_answers_eq_0": proposed["unsupported_memory_answers"] == 0,
        },
        "passed": passed,
    }


def proactive_candidate(case: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in case.items() if key not in {"id", "gold"}}


def validate_proactive(candidate: Mapping[str, Any]) -> tuple[bool, str]:
    keys = set(candidate)
    missing = sorted(PROACTIVE_REQUIRED - keys)
    unknown = sorted(keys - PROACTIVE_REQUIRED)
    if missing:
        return False, f"missing:{','.join(missing)}"
    if unknown:
        return False, f"unknown:{','.join(unknown)}"
    for field in PROACTIVE_BOOL_FIELDS:
        if type(candidate[field]) is not bool:
            return False, f"wrong_type:{field}:bool"
    for field in PROACTIVE_REAL_FIELDS:
        value = candidate[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, f"wrong_type:{field}:real"
        if not math.isfinite(float(value)):
            return False, f"non_finite:{field}"
    for field in PROACTIVE_TEXT_FIELDS:
        if not isinstance(candidate[field], str) or not candidate[field].strip():
            return False, f"wrong_type:{field}:nonempty_text"
    if candidate["version"] != "opportunity-v1":
        return False, "unknown_version"
    epoch = candidate["source_epoch"]
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
        return False, "wrong_type:source_epoch:nonnegative_int"
    return True, "valid"


def proposed_proactive(candidate: Mapping[str, Any]) -> tuple[str, str]:
    valid, reason = validate_proactive(candidate)
    if not valid:
        return "DROP_INVALID", reason
    hard_drop_fields = (
        (not candidate["owner_verified"], "owner_unverified"),
        (not candidate["proactive_consent"], "consent_off"),
        (candidate["owner_speaking"], "owner_speaking"),
        (candidate["lane_busy"], "lane_busy"),
        (candidate["quiet_hours"], "quiet_hours"),
        (candidate["estop"], "estop"),
        (candidate["private_zone"], "private_zone"),
        (candidate["nearby_non_owner"], "non_owner_nearby"),
        (candidate["evidence_age_s"] > 2.0, "stale_evidence"),
        (candidate["owner_turn_age_s"] < 15.0, "owner_turn_tail"),
        (candidate["robot_utterance_age_s"] < 30.0, "robot_turn_tail"),
        (candidate["last_subject_age_s"] < 600.0, "subject_dedup"),
        (candidate["novelty"] < 0.60, "low_novelty"),
        (candidate["confidence"] < 0.70, "low_confidence"),
    )
    for blocked, block_reason in hard_drop_fields:
        if blocked:
            return "DROP", block_reason
    return "ADMIT", "admitted"


def permissive_proactive_proxy(candidate: Mapping[str, Any]) -> str:
    """A fail-open comparison proxy, not current product code."""

    if not bool(candidate.get("owner_verified", True)):
        return "DROP"
    if not bool(candidate.get("proactive_consent", True)):
        return "DROP"
    if bool(candidate.get("owner_speaking", False)):
        return "DROP"
    if bool(candidate.get("lane_busy", False)):
        return "DROP"
    if bool(candidate.get("quiet_hours", False)):
        return "DROP"
    if bool(candidate.get("estop", False)):
        return "DROP"
    if bool(candidate.get("private_zone", False)):
        return "DROP"
    if bool(candidate.get("nearby_non_owner", False)):
        return "DROP"
    if float(candidate.get("evidence_age_s", 0.0)) > 2.0:
        return "DROP"
    if float(candidate.get("owner_turn_age_s", 999.0)) < 15.0:
        return "DROP"
    if float(candidate.get("robot_utterance_age_s", 999.0)) < 30.0:
        return "DROP"
    if float(candidate.get("last_subject_age_s", 999.0)) < 600.0:
        return "DROP"
    if float(candidate.get("novelty", 1.0)) < 0.60:
        return "DROP"
    if float(candidate.get("confidence", 1.0)) < 0.70:
        return "DROP"
    return "ADMIT"


def malformed_proactive_candidates(seed: Mapping[str, Any]) -> list[dict[str, Any]]:
    mutations: list[dict[str, Any]] = []
    for field in sorted(PROACTIVE_REQUIRED):
        candidate = copy.deepcopy(dict(seed))
        del candidate[field]
        mutations.append({"id": f"missing:{field}", "candidate": candidate})
    for field in sorted(PROACTIVE_BOOL_FIELDS):
        candidate = copy.deepcopy(dict(seed))
        candidate[field] = "false"
        mutations.append({"id": f"wrong_bool:{field}", "candidate": candidate})
    for field in sorted(PROACTIVE_REAL_FIELDS):
        candidate = copy.deepcopy(dict(seed))
        candidate[field] = float("nan")
        mutations.append({"id": f"nan:{field}", "candidate": candidate})
    wrong_epoch = copy.deepcopy(dict(seed))
    wrong_epoch["source_epoch"] = True
    mutations.append({"id": "wrong_int:source_epoch", "candidate": wrong_epoch})
    wrong_version = copy.deepcopy(dict(seed))
    wrong_version["version"] = "opportunity-v2"
    mutations.append({"id": "unknown_version", "candidate": wrong_version})
    unknown_field = copy.deepcopy(dict(seed))
    unknown_field["surprise"] = True
    mutations.append({"id": "unknown_field", "candidate": unknown_field})
    return mutations


def run_proactive(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    proposed_rows = []
    proxy_rows = []
    gold_labels = []
    proposed_labels = []
    proxy_labels = []
    for case in cases:
        candidate = proactive_candidate(case)
        proposed, reason = proposed_proactive(candidate)
        proxy = permissive_proactive_proxy(candidate)
        gold = case["gold"]
        proposed_rows.append(
            {"id": case["id"], "gold": gold, "predicted": proposed, "reason": reason}
        )
        proxy_rows.append({"id": case["id"], "gold": gold, "predicted": proxy})
        gold_labels.append(gold)
        proposed_labels.append(proposed)
        proxy_labels.append(proxy)

    mutations = malformed_proactive_candidates(proactive_candidate(cases[0]))
    mutation_rows = []
    proxy_invalid_admissions = 0
    for mutation in mutations:
        predicted, reason = proposed_proactive(mutation["candidate"])
        proxy = permissive_proactive_proxy(mutation["candidate"])
        proxy_invalid_admissions += proxy == "ADMIT"
        mutation_rows.append(
            {
                "id": mutation["id"],
                "proposed": predicted,
                "proposed_reason": reason,
                "permissive_proxy": proxy,
            }
        )

    proposed_metrics = _classification_metrics(gold_labels, proposed_labels)
    proxy_metrics = _classification_metrics(gold_labels, proxy_labels)
    valid_prohibited_admissions = sum(
        row["gold"] != "ADMIT" and row["predicted"] == "ADMIT"
        for row in proposed_rows
    )
    malformed_admissions = sum(row["proposed"] != "DROP_INVALID" for row in mutation_rows)
    passed = (
        valid_prohibited_admissions == 0
        and proposed_metrics["precision"] >= 0.80
        and proposed_metrics["recall"] >= 0.80
        and malformed_admissions == 0
    )
    return {
        "evidence_note": (
            "New authored valid cases plus rule-generated malformed mutations; "
            "no owner-preference or sensor-identity accuracy was measured."
        ),
        "proposed_typed_gate": {
            **proposed_metrics,
            "prohibited_admissions": valid_prohibited_admissions,
            "rows": proposed_rows,
        },
        "permissive_default_proxy": {
            **proxy_metrics,
            "invalid_mutation_admissions": proxy_invalid_admissions,
            "rows": proxy_rows,
        },
        "malformed_refuters": {
            "cases": len(mutation_rows),
            "admitted_by_proposed": malformed_admissions,
            "rows": mutation_rows,
        },
        "bars": {
            "prohibited_admissions_eq_0": valid_prohibited_admissions == 0,
            "precision_ge_0_80": proposed_metrics["precision"] >= 0.80,
            "recall_ge_0_80": proposed_metrics["recall"] >= 0.80,
            "all_malformed_drop_invalid": malformed_admissions == 0,
        },
        "passed": passed,
    }


def proposed_route(case: Mapping[str, Any]) -> str:
    if case["safety_critical"] or case["closed_act"] or case["proactive_candidate"]:
        return "local"
    if case["complexity"] == "high" or case["memory_horizon"] == "long":
        return "reasoning"
    return "realtime"


def realtime_cost(case: Mapping[str, Any]) -> float:
    audio_input_tokens = float(case["user_audio_s"]) * 10.0
    audio_output_tokens = float(case["assistant_audio_s"]) * 20.0
    total = (
        float(case["context_text_tokens"]) * RATES_USD_PER_MILLION["text_input"]
        + float(case["assistant_text_tokens"])
        * RATES_USD_PER_MILLION["text_output"]
        + audio_input_tokens * RATES_USD_PER_MILLION["audio_input"]
        + audio_output_tokens * RATES_USD_PER_MILLION["audio_output"]
    )
    return total / 1_000_000.0


def reasoning_cost(case: Mapping[str, Any]) -> float:
    input_tokens = float(case["context_text_tokens"]) + 250.0
    output_tokens = float(case["reasoning_output_tokens"])
    return (
        input_tokens * RATES_USD_PER_MILLION["text_input"]
        + output_tokens * RATES_USD_PER_MILLION["text_output"]
    ) / 1_000_000.0


def run_routing(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    proposed_rows = []
    always_rows = []
    for case in cases:
        proposed = proposed_route(case)
        proposed_rows.append(
            {"id": case["id"], "gold": case["gold_route"], "predicted": proposed}
        )
        always_rows.append(
            {"id": case["id"], "gold": case["gold_route"], "predicted": "realtime"}
        )

    safety_cases = [case for case in cases if case["safety_critical"]]
    safety_local = sum(proposed_route(case) == "local" for case in safety_cases)
    gold_hosted = [case for case in cases if case["gold_route"] != "local"]
    preserved_hosted = sum(proposed_route(case) == case["gold_route"] for case in gold_hosted)
    always_hosted = len(cases)
    proposed_hosted = sum(proposed_route(case) != "local" for case in cases)
    reduction = (always_hosted - proposed_hosted) / always_hosted

    always_cost = sum(realtime_cost(case) for case in cases)
    hybrid_cost = sum(
        0.0
        if proposed_route(case) == "local"
        else reasoning_cost(case)
        if proposed_route(case) == "reasoning"
        else realtime_cost(case)
        for case in cases
    )
    monthly_turns = 12_000
    scale = monthly_turns / len(cases)
    proposed_metrics = _exact_metrics(proposed_rows)
    passed = (
        safety_local == len(safety_cases)
        and proposed_metrics["accuracy"] >= 0.90
        and reduction >= 0.40
        and preserved_hosted == len(gold_hosted)
    )
    return {
        "evidence_note": (
            "Authored route labels and modelled list-price arithmetic. Local means "
            "deterministic/template response; reasoning assumes local TTS. It is not "
            "measured API spend, quality, network latency, or Orin throughput."
        ),
        "proposed_router": {
            **proposed_metrics,
            "hosted_generations": proposed_hosted,
            "hosted_reduction_vs_always_realtime": reduction,
            "safety_cases": len(safety_cases),
            "safety_routed_local": safety_local,
            "gold_hosted_cases": len(gold_hosted),
            "gold_hosted_routes_preserved": preserved_hosted,
            "rows": proposed_rows,
        },
        "always_realtime_proxy": {
            **_exact_metrics(always_rows),
            "hosted_generations": always_hosted,
            "rows": always_rows,
        },
        "price_projection": {
            "rate_source": "OpenAI GPT-Realtime-2 model page accessed 2026-08-26",
            "rates_usd_per_million": RATES_USD_PER_MILLION,
            "audio_token_assumptions": {
                "user_audio_tokens_per_second": 10,
                "assistant_audio_tokens_per_second": 20,
            },
            "fixture_pass_usd": {
                "always_realtime": always_cost,
                "hybrid_local_tts": hybrid_cost,
            },
            "proportional_12000_turn_month_usd": {
                "always_realtime": always_cost * scale,
                "hybrid_local_tts": hybrid_cost * scale,
            },
            "exclusions": [
                "provider special-token variation",
                "context growth and cache-hit distribution",
                "transcription or separate TTS provider charges",
                "local compute, energy, and Starlink charges",
                "hosted realtime narration after the reasoning tier",
            ],
        },
        "bars": {
            "all_safety_local": safety_local == len(safety_cases),
            "exact_accuracy_ge_0_90": proposed_metrics["accuracy"] >= 0.90,
            "hosted_reduction_ge_0_40": reduction >= 0.40,
            "all_gold_hosted_routes_preserved": preserved_hosted == len(gold_hosted),
        },
        "passed": passed,
    }


def semantic_run(fixtures: Mapping[str, Any], surface: Mapping[str, Any]) -> dict[str, Any]:
    available = frozenset(surface["available_actions"])
    return {
        "audit": surface,
        "h1_capability_closure": run_embodiment(fixtures["embodiment_cases"], available),
        "h2_dialogue_state": run_dialogue(fixtures["dialogue_cases"]),
        "h3_proactive_contract": run_proactive(fixtures["proactive_cases"]),
        "h4_edge_cloud_router": run_routing(fixtures["route_cases"]),
    }


def microbenchmark(
    fixtures: Mapping[str, Any], surface: Mapping[str, Any], decisions: int = 150_000
) -> dict[str, Any]:
    embodiment_cases = fixtures["embodiment_cases"]
    proactive_cases = fixtures["proactive_cases"]
    route_cases = fixtures["route_cases"]
    available = frozenset(surface["available_actions"])
    durations_ms = []
    accumulator = 0
    for index in range(decisions):
        started = time.perf_counter_ns()
        embodiment = proposed_embodiment(
            embodiment_cases[index % len(embodiment_cases)], available
        )
        proactive, _ = proposed_proactive(
            proactive_candidate(proactive_cases[index % len(proactive_cases)])
        )
        route = proposed_route(route_cases[index % len(route_cases)])
        elapsed = time.perf_counter_ns() - started
        durations_ms.append(elapsed / 1_000_000.0)
        accumulator += len(str(embodiment["decision"])) + len(proactive) + len(route)
    return {
        "evidence_note": (
            "Desktop CPython policy latency only; excludes ASR, semantic frame "
            "production, TTS, networking, model generation, and motion."
        ),
        "decisions": decisions,
        "median_ms": statistics.median(durations_ms),
        "p95_ms": _percentile(durations_ms, 0.95),
        "p99_ms": _percentile(durations_ms, 0.99),
        "max_ms": max(durations_ms),
        "bar_p95_le_1_ms": _percentile(durations_ms, 0.95) <= 1.0,
        "anti_optimization_accumulator": accumulator,
    }


def git_head(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def source_hashes(repo: Path) -> dict[str, str]:
    relative_paths = (
        "configs/robot.yaml",
        "configs/robot.go2_edu_plus.yaml",
        "prompts/personalities/calm_guardian.yaml",
        "prompts/personalities/gentle_companion.yaml",
        "prompts/personalities/playful_companion.yaml",
        "src/parcel_robot/prompting/dynamic.py",
        "src/parcel_robot/prompting/loader.py",
        "src/parcel_robot/realtime/prompting.py",
        "src/parcel_robot/realtime/relationship_prompt.py",
        "src/parcel_robot/realtime/tool_broker.py",
        "src/parcel_robot/memory/tiered.py",
        "scrum/20260824/task_4/QUALITY_EVAL_REPORT.md",
        "research/20260824/conversation-opportunity/RESULTS.md",
        "research/20260824/conversation-opportunity/VERDICT.md",
    )
    return {relative: _sha256_file(repo / relative) for relative in relative_paths}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    fixture_path = args.fixtures.resolve()
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    surface = load_repo_surface(repo)

    semantic_replays = [semantic_run(fixtures, surface) for _ in range(10)]
    digests = [_sha256_bytes(_canonical(run).encode("utf-8")) for run in semantic_replays]
    semantic = semantic_replays[0]
    benchmark = microbenchmark(fixtures, surface)

    hypotheses = {
        key: value["passed"]
        for key, value in semantic.items()
        if key.startswith("h") and isinstance(value, dict) and "passed" in value
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_tier": "repository-audit-plus-authored-deterministic-desktop-replay",
        "model_evidence": {
            "hosted_or_local_model_called": False,
            "natural_language_parsed": False,
            "simulator_called": False,
            "robot_or_orin_called": False,
        },
        "provenance": {
            "repo_head": git_head(repo),
            "fixtures_path": str(fixture_path.relative_to(repo)),
            "fixtures_sha256": _sha256_file(fixture_path),
            "experiment_sha256": _sha256_file(Path(__file__).resolve()),
            "source_sha256": source_hashes(repo),
            "python": sys.version,
            "platform": platform.platform(),
        },
        "semantic_replay": {
            "repeats": len(digests),
            "unique_digests": sorted(set(digests)),
            "deterministic": len(set(digests)) == 1,
        },
        **semantic,
        "local_policy_microbenchmark": benchmark,
        "acceptance": {
            "hypotheses": hypotheses,
            "semantic_determinism": len(set(digests)) == 1,
            "local_policy_p95_le_1_ms": benchmark["bar_p95_le_1_ms"],
            "all_architecture_bars_passed": (
                all(hypotheses.values())
                and len(set(digests)) == 1
                and benchmark["bar_p95_le_1_ms"]
            ),
            "physical_readiness_claim": False,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out": str(args.out),
                "hypotheses": hypotheses,
                "deterministic": result["semantic_replay"]["deterministic"],
                "p95_ms": benchmark["p95_ms"],
                "all_architecture_bars_passed": result["acceptance"][
                    "all_architecture_bars_passed"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
