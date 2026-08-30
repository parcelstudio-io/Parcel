"""Pure data helpers for the MA-2-P0 causal qualification probe."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import dataclass
from typing import Any

ROOT_SEED = 20260829
DT_S = 0.1
ROLES = ("door", "sofa", "bench", "elevator", "keys")
TASK_FAMILIES = ("plain", "interrupt_now", "queue_resume")
POLICY_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "header",
        "freshness",
        "robot_estimate",
        "local_world",
        "mission",
        "path",
        "dialogue",
        "safety",
        "history",
        "semantic_map",
    }
)
FORBIDDEN_POLICY_FRAGMENTS = (
    "truth",
    "oracle",
    "scorer",
    "actual_pose",
    "distance_to_goal",
    "inside_region",
    "collision_clearance",
    "future",
    "gold",
    "teacher_status",
)
ACTION_KEYS = frozenset({"vx", "vy", "vyaw"})


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def derive_u64(namespace: str, stable_id: str) -> int:
    raw = hashlib.sha256(f"MA2|{namespace}|{stable_id}".encode("ascii")).digest()
    return int.from_bytes(raw[:8], "big", signed=False)


def stable_token(namespace: str, stable_id: str, length: int = 24) -> str:
    return hashlib.sha256(f"MA2|{namespace}|{stable_id}".encode("ascii")).hexdigest()[:length]


def quantize(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("non-finite scalar")
    return float(f"{value:.6f}")


def validate_action(value: dict[str, object]) -> dict[str, float]:
    if set(value) != ACTION_KEYS:
        raise ValueError("action has non-canonical fields")
    result = {key: quantize(float(value[key])) for key in sorted(ACTION_KEYS)}
    if abs(result["vx"]) > 0.700001 or abs(result["vy"]) > 0.700001:
        raise ValueError("translation exceeds P0 bound")
    if abs(result["vyaw"]) > 1.000001:
        raise ValueError("yaw exceeds P0 bound")
    return result


def _walk_keys(value: object, prefix: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.append(path)
            out.extend(_walk_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.extend(_walk_keys(child, f"{prefix}[{index}]"))
    return out


def validate_policy_payload(payload: dict[str, Any]) -> None:
    if set(payload) != POLICY_TOP_LEVEL:
        extra = sorted(set(payload) - POLICY_TOP_LEVEL)
        missing = sorted(POLICY_TOP_LEVEL - set(payload))
        raise ValueError(f"policy top-level mismatch extra={extra} missing={missing}")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported policy schema")
    paths = _walk_keys(payload)
    lowered = [path.lower() for path in paths]
    for fragment in FORBIDDEN_POLICY_FRAGMENTS:
        if any(fragment in path for path in lowered):
            raise ValueError(f"forbidden policy field fragment: {fragment}")
    now_ns = int(payload["header"]["monotonic_ns"])
    if int(payload["freshness"]["observed_at_ns"]) > now_ns:
        raise ValueError("future observation timestamp")
    candidates = payload["semantic_map"]["candidates"]
    if not isinstance(candidates, list) or len(candidates) != 15:
        raise ValueError("semantic candidate inventory is not complete")
    target = payload["mission"]["target_ref"]
    matches = [row for row in candidates if row["entity_uuid"] == target]
    if len(matches) != 1:
        raise ValueError("exact target reference does not resolve uniquely")


@dataclass(frozen=True, slots=True)
class ReceiptExpectation:
    task_id: str
    plan_revision: int
    step_id: str
    attempt: int
    target_entity_uuid: str
    source_epoch: str
    speech_generation: int
    evidence_ref: str


class NarrativeSigner:
    """Experiment-local HMAC channel; never a production authority."""

    def __init__(self, *, authenticator_id: str, key: bytes):
        if len(key) < 32:
            raise ValueError("P0 receipt key must be at least 32 bytes")
        self.authenticator_id = authenticator_id
        self._key = key

    def sign(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = dict(payload)
        event["authenticator_id"] = self.authenticator_id
        tag = hmac.new(self._key, canonical_bytes(event), hashlib.sha256).hexdigest()
        event["tag"] = tag
        return event

    def verify(self, event: dict[str, Any]) -> bool:
        if event.get("authenticator_id") != self.authenticator_id:
            return False
        clean = dict(event)
        tag = clean.pop("tag", None)
        if not isinstance(tag, str):
            return False
        expected = hmac.new(self._key, canonical_bytes(clean), hashlib.sha256).hexdigest()
        return hmac.compare_digest(tag, expected)


class NarrativeConsumer:
    """Fail-closed receipt consumer used by the composed P0 bridge fixture."""

    def __init__(self, signer: NarrativeSigner):
        self._signer = signer
        self.last_sequence = 0
        self.terminal_tasks: set[str] = set()
        self.accepted_event_ids: set[str] = set()

    def snapshot(self) -> dict[str, object]:
        return {
            "last_sequence": self.last_sequence,
            "terminal_tasks": sorted(self.terminal_tasks),
            "accepted_event_ids": sorted(self.accepted_event_ids),
        }

    def accept(
        self,
        event: dict[str, Any],
        *,
        expected: ReceiptExpectation,
        now_ns: int,
    ) -> tuple[bool, str]:
        if not self._signer.verify(event):
            return False, "bad_authenticator"
        if event.get("event_id") in self.accepted_event_ids:
            return False, "duplicate"
        if int(event.get("sequence", -1)) <= self.last_sequence:
            return False, "sequence_regression"
        if event.get("source_epoch") != expected.source_epoch:
            return False, "wrong_epoch"
        if int(event.get("issued_at_ns", -1)) > now_ns:
            return False, "future"
        if int(event.get("expires_at_ns", -1)) < now_ns:
            return False, "expired"
        if int(event.get("speech_generation", -1)) != expected.speech_generation:
            return False, "stale_speech_generation"
        tuple_fields = {
            "task_id": expected.task_id,
            "plan_revision": expected.plan_revision,
            "step_id": expected.step_id,
            "attempt": expected.attempt,
            "target_entity_uuid": expected.target_entity_uuid,
        }
        for key, wanted in tuple_fields.items():
            if event.get(key) != wanted:
                return False, f"wrong_{key}"
        evidence = event.get("evidence_refs")
        if evidence != [expected.evidence_ref]:
            return False, "unrelated_evidence"
        if event.get("status") != "succeeded":
            return False, "nonterminal"
        if expected.task_id in self.terminal_tasks:
            return False, "post_terminal"
        self.last_sequence = int(event["sequence"])
        self.terminal_tasks.add(expected.task_id)
        self.accepted_event_ids.add(str(event["event_id"]))
        return True, "accepted"


def mint_narrative_event(
    signer: NarrativeSigner,
    *,
    expectation: ReceiptExpectation,
    sequence: int,
    issued_at_ns: int,
    parent_task_id: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "event_id": f"event-{stable_token('receipt', expectation.task_id + ':' + str(sequence))}",
        "sequence": sequence,
        "task_id": expectation.task_id,
        "plan_revision": expectation.plan_revision,
        "step_id": expectation.step_id,
        "attempt": expectation.attempt,
        "mission_id": f"mission-{stable_token('mission', expectation.task_id)}",
        "action_id": f"action-{stable_token('action', expectation.task_id)}",
        "status": "succeeded",
        "target_entity_uuid": expectation.target_entity_uuid,
        "source_epoch": expectation.source_epoch,
        "speech_generation": expectation.speech_generation,
        "issued_at_ns": issued_at_ns,
        "expires_at_ns": issued_at_ns + 5_000_000_000,
        "evidence_refs": [expectation.evidence_ref],
        "resume_parent_task_id": parent_task_id,
    }
    return signer.sign(payload)
