"""Mid-task goal amendment + grounded clarification (Phase 2 / Sol pure).

Amendment = pause → snapshot (ResumeIntent) → replan → verified resume.
Clarification is triggered by Grounder AMBIGUOUS/UNSEEN, not dialogue heuristics.
Fail-closed: no active task ⇒ no amend; no attributes ⇒ honest generic ask.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from parcel_robot.instructnav.grounding import GroundingOutcome, GroundingResult

AMEND_SUSPEND_REASON = "goal_amend"

_AMEND_PREFIX = re.compile(
    r"^(?:actually|instead|no[, ]+|change\s+(?:that|course)|correction\b|rather\b|"
    r"not\s+that\s+one|the\s+other\b)[,:]?\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AmendmentOutcome:
    ok: bool
    reply: str
    paused_channels: tuple[str, ...]
    reason: str
    pending: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "reply": self.reply,
            "paused_channels": list(self.paused_channels),
            "reason": self.reason,
            "pending": self.pending,
        }


@dataclass(frozen=True, slots=True)
class ClarificationAct:
    kind: str  # clarify | offer_scan | none
    reply: str
    asks_clarification: bool
    outcome: str
    candidate_labels: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "reply": self.reply,
            "asks_clarification": self.asks_clarification,
            "outcome": self.outcome,
            "candidate_labels": list(self.candidate_labels),
        }


def strip_amend_prefix(transcript: str) -> str:
    """Return the residual goal text after a closed goal-amend cue."""

    if not isinstance(transcript, str):
        raise TypeError("transcript must be a string")
    clean = " ".join(transcript.strip().split())
    if not clean:
        return ""
    stripped = _AMEND_PREFIX.sub("", clean, count=1).strip()
    # Drop leading "go to" / "the" noise when the cue ate the verb.
    stripped = re.sub(r"^(?:go\s+to\s+|head\s+to\s+)", "", stripped, flags=re.IGNORECASE)
    return " ".join(stripped.split())


def can_amend(*, active_channels: Sequence[str], paused_channels: Sequence[str] = ()) -> bool:
    """True when there is in-flight or paused work that amendment may revise."""

    return bool(active_channels) or bool(paused_channels)


def begin_goal_amend(
    *,
    active_channels: Sequence[str],
    paused_channels: Sequence[str] = (),
) -> AmendmentOutcome:
    """Fail-closed gate before pausing for mid-task amendment."""

    active = tuple(ch for ch in active_channels if isinstance(ch, str) and ch)
    paused = tuple(ch for ch in paused_channels if isinstance(ch, str) and ch)
    if not can_amend(active_channels=active, paused_channels=paused):
        return AmendmentOutcome(
            ok=False,
            reply="There's nothing active to revise right now.",
            paused_channels=(),
            reason="nothing_to_amend",
            pending=False,
        )
    targets = active if active else paused
    return AmendmentOutcome(
        ok=True,
        reply="Okay—I'll revise the current goal.",
        paused_channels=targets,
        reason=AMEND_SUSPEND_REASON,
        pending=True,
    )


def clarification_from_grounding(
    result: GroundingResult | Mapping[str, object],
    *,
    query: str = "",
) -> ClarificationAct:
    """Build a grounded clarification / scan offer from Grounder v2 outcomes."""

    if isinstance(result, GroundingResult):
        outcome = result.outcome
        candidates = result.candidates
    else:
        raw_outcome = str(result.get("outcome", ""))
        try:
            outcome = GroundingOutcome(raw_outcome)
        except ValueError as error:
            raise ValueError(f"unknown grounding outcome: {raw_outcome!r}") from error
        raw_cands = result.get("candidates") or ()
        if not isinstance(raw_cands, Sequence) or isinstance(raw_cands, (str, bytes)):
            raise TypeError("candidates must be a sequence of mappings")
        candidates = tuple(raw_cands)  # type: ignore[arg-type]

    label = " ".join(str(query).strip().split()) or "that"
    if outcome is GroundingOutcome.AMBIGUOUS:
        labels = _candidate_labels(candidates)
        reply = _ambiguous_question(label, labels)
        return ClarificationAct(
            kind="clarify",
            reply=reply,
            asks_clarification=True,
            outcome=outcome.value,
            candidate_labels=labels,
        )
    if outcome is GroundingOutcome.UNSEEN:
        return ClarificationAct(
            kind="offer_scan",
            reply=(
                f"I don't see a {label} yet. "
                "Want me to look around (scan) for one?"
            ),
            asks_clarification=True,
            outcome=outcome.value,
            candidate_labels=(),
        )
    return ClarificationAct(
        kind="none",
        reply="",
        asks_clarification=False,
        outcome=outcome.value,
        candidate_labels=_candidate_labels(candidates),
    )


def _candidate_labels(candidates: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    labels: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        raw = item.get("label") or item.get("class_id") or item.get("id")
        if raw is None:
            continue
        text = " ".join(str(raw).strip().split())
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        labels.append(text)
        if len(labels) >= 4:
            break
    return tuple(labels)


def _ambiguous_question(query: str, labels: tuple[str, ...]) -> str:
    if len(labels) >= 2:
        left, right = labels[0], labels[1]
        extras = ""
        if len(labels) > 2:
            extras = f" (I also see {', '.join(labels[2:])})"
        return f"Do you mean the {left}, or the {right}?{extras}"
    if labels:
        return (
            f"I can see more than one {query}; "
            f"is it the {labels[0]}, or another one?"
        )
    return f"I can see more than one {query}; please say which one you mean."


__all__ = [
    "AMEND_SUSPEND_REASON",
    "AmendmentOutcome",
    "ClarificationAct",
    "begin_goal_amend",
    "can_amend",
    "clarification_from_grounding",
    "strip_amend_prefix",
]
