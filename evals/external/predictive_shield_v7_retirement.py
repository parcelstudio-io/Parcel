"""Fail-closed retirement guard for the invalidated v7 experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

RETIREMENT_RECORD = (
    Path(__file__).resolve().parent
    / "development"
    / "barn_predictive_shield_v7"
    / "RETIREMENT.json"
)
RETIREMENT_RECORD_SHA256 = "3ac5df5cb8b32386b01497ffc956f25dd30da16a120478a6775f15f90321f09c"


class RetiredExperimentError(RuntimeError):
    """Raised before any write or policy execution for a retired experiment."""


def v7_retirement_record() -> dict[str, Any]:
    """Load and authenticate the immutable pre-execution retirement decision."""

    if RETIREMENT_RECORD.is_symlink() or not RETIREMENT_RECORD.is_file():
        raise RuntimeError("the predictive-shield v7 retirement record is missing or unsafe")
    raw = RETIREMENT_RECORD.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RETIREMENT_RECORD_SHA256:
        raise RuntimeError("the predictive-shield v7 retirement record changed")
    payload = json.loads(raw)
    if (
        not isinstance(payload, dict)
        or payload.get("status") != "invalidated_pre_execution"
        or payload.get("score") is not None
        or payload.get("corpus_generated") is not False
        or payload.get("policy_execution_started") is not False
    ):
        raise RuntimeError("the predictive-shield v7 retirement contract is invalid")
    return payload


def refuse_v7_execution() -> None:
    """Authenticate the record, then unconditionally reject v7 execution."""

    record = v7_retirement_record()
    raise RetiredExperimentError(
        "predictive-shield v7 was invalidated before corpus generation or policy execution: "
        f"{record['reason']} See {RETIREMENT_RECORD}."
    )


__all__ = [
    "RETIREMENT_RECORD",
    "RETIREMENT_RECORD_SHA256",
    "RetiredExperimentError",
    "refuse_v7_execution",
    "v7_retirement_record",
]
